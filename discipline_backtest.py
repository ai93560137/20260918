#!/usr/bin/env python3
"""「紀律本身」回測（預先登記：stock_research/DISCIPLINE_BACKTEST.md，寫程式前已 commit；9 個市場同一規格、只測一次）。

    python3 discipline_backtest.py --market hk --check-sim      # 機制檢查：向量化出場 vs Minervini.simulate 逐筆比對（不看績效）
    python3 discipline_backtest.py --market hk --inspect 10     # 機制檢查：印預設格前 10 筆逐筆明細（不看績效）
    python3 discipline_backtest.py --market hk --random 200     # 正式：先抽 300 筆內部一致性（可疑 > 5% 就停），再跑 D0／9 格／R／D1／D2／D3／M
    python3 discipline_backtest.py --pool                       # 9 市場合併檢定 + 判決

- D0：t−1 收市「剛進入趨勢模板」（t−1 通過、t−2 在宇宙內有數據且不通過）＋ 大市 50／200 日線過濾 → t 開市買；
  出場 = Minervini 忠實版（止損 7.5% 盤中、1.15 倍保本、收市跌破 50 日線下一日開市出、252 日上限）
- R：同日隨機「宇宙內、200 日線上、不通過趨勢模板」股票，同一套出場；D1：不用大市過濾；D2：只有 252 日上限；D3：X2 出場；
  M：Minervini 忠實版預設格重跑（規格凍結，只作並列）
"""
import argparse
import gzip
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import newhigh_backtest as nb  # noqa: E402
import oos_backtest as ob  # noqa: E402
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402

MARKETS = ("hk", "jp", "us", "tw", "kr", "au", "ca", "in", "sg")
GROUPS = {"港日美": ("hk", "jp", "us"), "台韓澳": ("tw", "kr", "au"), "加印新": ("ca", "in", "sg")}
GRID = [(stop, be) for stop in (0.06, 0.075, 0.09) for be in (1.10, 1.15, 1.20)]
DEFAULT = (0.075, 1.15)
MAX_HOLD = vm.MAX_HOLD
OUT = ROOT / "research" / "discipline"
SAMPLE_N, SAMPLE_MAX_SUSPECT = 300, 0.05


def key(stop: float, be: float) -> str:
    return f"止損{stop:.1%} 保本{be:.2f}"


def minervini_suspects(mk: str) -> set:
    """重跑 M 時沿用原判決那一輪的可疑交易剔除：港日美 = research/vcp_full（XV 那輪）；加印新 = research/oos；台韓澳 = 無。"""
    p = {"hk": ROOT / "research" / "vcp_full", "jp": ROOT / "research" / "vcp_full", "us": ROOT / "research" / "vcp_full",
         "ca": ROOT / "research" / "oos", "in": ROOT / "research" / "oos", "sg": ROOT / "research" / "oos"}.get(mk)
    f = p / f"{mk}_suspect.json" if p else None
    return {tuple(x) for x in json.loads(f.read_text())} if f and f.exists() else set()


def sim_fast(rw: dict, p: int, fill: float, stop_pct: float, be_at: float) -> tuple[int, float, bool]:
    """vcp_minervini.Minervini.simulate 的向量化版（同一規則：入場日觸及止損按止損價；之後每日先看「昨收跌破 50 日線→今開出」、
    再看盤中止損 min(開市, 止損)；收市 ≥ fill×be_at 之後止損 = fill；252 日上限收市出）。--check-sim 逐筆比對過才用。"""
    low, close, opn, adj, ma50 = rw["low"], rw["close"], rw["open"], rw["adj"], rw["ma50"]
    n = len(close)
    stop0 = fill * (1 - stop_pct)
    if low[p] <= stop0:
        return p, stop0, False
    end = min(n, p + MAX_HOLD + 1)
    L = end - p
    c, lo, o, a, m5 = close[p:end], low[p:end], opn[p:end], adj[p:end], ma50[p:end]
    o = np.where((o == o) & (o > 0), o, c)
    idx = np.arange(L)
    be = np.nonzero(c >= fill * be_at)[0]
    be_i = be[0] if len(be) else L
    stop_lvl = np.where(idx > be_i, fill, stop0)
    hit = np.nonzero((lo <= stop_lvl) & (idx > 0))[0]
    stop_i = int(hit[0]) if len(hit) else L
    ma = np.nonzero((m5 == m5) & (a < m5))[0]
    ma_i = int(ma[0]) + 1 if len(ma) else L
    cap_i = L - 1
    ei = min(stop_i, ma_i, cap_i)
    k = p + ei
    if ei == ma_i:
        return k, float(o[ei]), False
    if ei == stop_i:
        return k, float(min(o[ei], stop_lvl[ei])), False
    return k, float(c[ei]), True


class Discipline:
    def __init__(self, mk: str):
        self.mk = mk
        self.vf = vf = vb.VCPData(mk, full=True, scan=False)
        self.m = m = vf.m
        self.mv = mv = vm.Minervini(mk, minervini_suspects(mk), v=vf)   # 順便建 mkt_ok、VCP 形態（M 用）
        self.locked = ob.locked_matrix(m, mk)
        n0 = len(mv.setups)
        mv.setups = [x for x in mv.setups if not self.locked[x[0], x[2]]]
        self.m_locked_skipped = n0 - len(mv.setups)
        tt, mem, has = vf.tt, m.member, m.has
        S, D = tt.shape
        cross = np.zeros((S, D), dtype=bool)
        cross[:, 2:] = tt[:, 1:-1] & ~tt[:, :-2] & mem[:, :-2] & has[:, :-2]
        cross[:, :m.start_j] = False
        self.cross = cross
        mkt_prev = np.r_[False, mv.mkt_ok[:-1]]                           # 大市過濾看 t−1 收市
        self.E0 = cross & mkt_prev[None, :]
        self.E1 = cross
        print(f"[{mk}] 剛進入趨勢模板事件 {int(cross.sum())}、大市過濾後 {int(self.E0.sum())}", file=sys.stderr)

    def entries(self, E: np.ndarray) -> list[tuple[int, int, int, float]]:
        """(s, raw 索引 p, 日曆索引 j, 開市價)；漲停鎖死、無開市價、raw 沒有那天 → 跳過。"""
        out, self.n_locked, self.n_noopen = [], 0, 0
        for s, j in zip(*np.nonzero(E)):
            if self.locked[s, j]:
                self.n_locked += 1
                continue
            rw = self.vf.raw[s]
            p = rw["dates"].get(self.m.cal[j])
            if p is None:
                continue
            o = rw["open"][p]
            if not (o == o and o > 0):
                self.n_noopen += 1
                continue
            out.append((int(s), int(p), int(j), float(o)))
        return sorted(out, key=lambda x: (x[2], x[0]))

    def trades(self, ents: list, stop: float, be: float, hold_only: bool = False) -> list[dict]:
        busy, out = {}, []
        for s, p, j, o in ents:
            if p <= busy.get(s, -1):
                continue
            rw = self.vf.raw[s]
            if hold_only:
                k = min(len(rw["close"]), p + MAX_HOLD + 1) - 1
                px, ac = float(rw["close"][k]), True
            else:
                k, px, ac = sim_fast(rw, p, o, stop, be)
            busy[s] = k
            out.append(self.mv._trade(s, p, o, k, px, ac))
        return out

    def trades_x2(self, ents: list) -> list[tuple[int, int, int, bool]]:
        """D3：同入場、X2 出場（newhigh_backtest 引擎；日曆索引）。"""
        m, busy, out = self.m, {}, []
        for s, p, j, o in ents:
            if j <= busy.get(s, -1):
                continue
            ex, at_open = m.exit_index(s, j, "x2")
            if ex < j:
                continue
            busy[s] = ex
            out.append((s, j, ex, at_open))
        return out

    def random_trades(self, trs0: list[dict], seed: int, stop: float, be: float) -> list[dict]:
        """R：每筆 D0 入場同一天 t，改從 t−1「宇宙內、200 日線上、不通過趨勢模板、當天不是 D0 事件」隨機挑一檔，t 開市買、同一套出場。"""
        rng = np.random.default_rng(seed)
        m, vf, out, cache = self.m, self.vf, [], {}
        for t in trs0:
            j = t["a"]
            if j not in cache:
                cache[j] = np.nonzero(m.member[:, j - 1] & m.above[:, j - 1] & ~vf.tt[:, j - 1] & ~self.E0[:, j])[0]
            pool = cache[j]
            if len(pool) == 0:
                continue
            r = int(pool[rng.integers(len(pool))])
            if self.locked[r, j]:
                continue
            pr = vf.raw[r]["dates"].get(m.cal[j])
            if pr is None:
                continue
            o = vf.raw[r]["open"][pr]
            if not (o == o and o > 0):
                continue
            k, px, ac = sim_fast(vf.raw[r], pr, o, stop, be)
            out.append(self.mv._trade(r, pr, o, k, px, ac))
        return out

    # ---------- 統計 ----------
    def stats(self, trs: list[dict]) -> tuple[dict, dict, dict]:
        m = self.m
        daily, tr, n = self.mv.daily(trs)
        st = ob.summary(m, daily, tr, [t["b"] - t["a"] for t in trs], len(trs))
        mo = m.monthly(daily)
        st["t_ew"] = m.capm(mo, m.monthly(m.ew_ret))[2]
        st["avg_pos"] = float(n[m.start_j:].mean())
        s_tr = [x for x in tr if x == x]
        st["top10_share"] = float(sum(sorted(s_tr, reverse=True)[:10]) / sum(s_tr)) if sum(s_tr) > 0 else float("nan")
        return st, ob.abn(m, daily), abn_vs(m, daily, m.ew_ret)

    def stats_x2(self, trades: list) -> tuple[dict, dict]:
        m = self.m
        daily, tr, n = m.portfolio(trades)
        st = ob.summary(m, daily, tr, [b - a for _, a, b, _ in trades], len(trades))
        st["t_ew"] = m.capm(m.monthly(daily), m.monthly(m.ew_ret))[2]
        st["avg_pos"] = float(n[m.start_j:].mean())
        return st, ob.abn(m, daily)

    # ---------- 檢查（不看績效）----------
    def sample_check(self, trs: list[dict]) -> dict:
        """抽 300 筆內部一致性：入場開市較 t−1 收市跳 > 30%、或出場價較前一日收市跳 > 50% → 可疑。"""
        smp = random.Random(0).sample(trs, min(SAMPLE_N, len(trs)))
        sus = []
        for t in smp:
            rw = self.vf.raw[t["s"]]
            dl = list(rw["dates"])
            p = rw["dates"][self.m.cal[t["a"]]]
            k = p
            while k + 1 < len(dl) and self.mv.cal_j(dl[k + 1]) <= t["b"]:
                k += 1
            o, c_prev = rw["open"][p], rw["close"][p - 1]
            px = t["out_adj"] / rw["adj"][k] * rw["close"][k]
            reasons = []
            if c_prev > 0 and abs(o / c_prev - 1) > 0.30:
                reasons.append(f"入場開市較前收跳 {o / c_prev - 1:+.0%}")
            if k > p and rw["close"][k - 1] > 0 and abs(px / rw["close"][k - 1] - 1) > 0.50:
                reasons.append(f"出場價較前收跳 {px / rw['close'][k - 1] - 1:+.0%}")
            if reasons:
                sus.append({"ticker": self.m.tickers[t["s"]], "entry": self.m.cal[t["a"]].isoformat(),
                            "exit": self.m.cal[t["b"]].isoformat(), "why": reasons})
        return {"n_sample": len(smp), "n_suspect": len(sus), "share": len(sus) / max(len(smp), 1), "suspects": sus}

    def inspect(self, n: int) -> None:
        m, vf = self.m, self.vf
        ents = self.entries(self.E0)
        for t in self.trades(ents, *DEFAULT)[:n]:
            s, j = t["s"], t["a"]
            rw = vf.raw[s]
            p = rw["dates"][m.cal[j]]
            print(f"{m.tickers[s]:12} 訊號 {m.cal[j - 1]}（模板 t−1 {vf.tt[s, j - 1]}、t−2 {vf.tt[s, j - 2]}、大市 {self.mv.mkt_ok[j - 1]}）"
                  f" 入 {m.cal[j]} 開 {rw['open'][p]:.4g} → 出 {m.cal[t['b']]} "
                  f"{'收市出（上限/下市）' if t['at_close'] else '開市/止損出'}  入還原 {t['in_adj']:.4g} 出還原 {t['out_adj']:.4g}")

    def check_sim(self) -> None:
        """向量化出場 vs Minervini.simulate：對全部 Minervini 突破（不追高 5% 內）逐筆比對三個止損格。"""
        bad = n = 0
        for (s, p, j, pivot, o, _) in self.mv.setups:
            if o > pivot * (1 + vm.DEFAULT[1]):
                continue
            fill = max(o, pivot)
            for stop in (0.06, 0.075, 0.09):
                n += 1
                a, b = self.mv.simulate(s, p, fill, stop), sim_fast(self.vf.raw[s], p, fill, stop, vm.BREAKEVEN_AT)
                if a[0] != b[0] or abs(a[1] - b[1]) > 1e-9 * max(1.0, abs(a[1])) or a[2] != b[2]:
                    bad += 1
                    if bad <= 5:
                        print(f"  不同：{self.m.tickers[s]} p={p} stop={stop} simulate={a} fast={b}", file=sys.stderr)
        print(f"[{self.mk}] 逐筆比對 {n} 次（{n // 3} 筆 × 3 個止損格）：不同 {bad}", file=sys.stderr)


def abn_vs(m, daily: np.ndarray, bench: np.ndarray) -> dict:
    mo, mb = m.monthly(daily), m.monthly(bench)
    _, b, _ = m.capm(mo, mb)
    x = (mo - b * mb).dropna()
    return {str(k.date())[:7]: float(v) for k, v in x.items()}


def run_market(mk: str, n_random: int) -> None:
    d = Discipline(mk)
    m = d.m
    ents0 = d.entries(d.E0)
    counts = {"cross_events": int(d.cross.sum()), "after_market_filter": int(d.E0.sum()), "locked_skipped": d.n_locked,
              "no_open_skipped": d.n_noopen, "entries": len(ents0)}
    trs0 = d.trades(ents0, *DEFAULT)
    chk = d.sample_check(trs0)
    print(f"[{mk}] D0 預設格 {len(trs0)} 筆；抽 {chk['n_sample']} 筆內部一致性：可疑 {chk['n_suspect']}（{chk['share']:.1%}）", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}_sample.json").write_text(json.dumps(chk, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if chk["share"] > SAMPLE_MAX_SUSPECT:
        print(f"[{mk}] 可疑 > {SAMPLE_MAX_SUSPECT:.0%}：按登記先查數據，未算績效", file=sys.stderr)
        return
    res = {"market": mk, "counts": counts, "sample_check": {k: v for k, v in chk.items() if k != "suspects"},
           "m_locked_skipped": d.m_locked_skipped, "cells": {}, "abn": {}, "abn_ew": {}}
    # D0 + 9 格鄰域
    for stop, be in GRID:
        trs = trs0 if (stop, be) == DEFAULT else d.trades(ents0, stop, be)
        st, ab, ab_ew = d.stats(trs)
        k = key(stop, be)
        res["cells"][k], res["abn"][k] = st, ab
        if (stop, be) == DEFAULT:
            res["cells"]["D0"], res["abn"]["D0"], res["abn_ew"]["D0"] = st, ab, ab_ew
    # D1 不用大市過濾
    st, ab, _ = d.stats(d.trades(d.entries(d.E1), *DEFAULT))
    res["cells"]["D1"], res["abn"]["D1"] = st, ab
    # D2 只有 252 日上限
    st, ab, _ = d.stats(d.trades(ents0, *DEFAULT, hold_only=True))
    res["cells"]["D2"], res["abn"]["D2"] = st, ab
    # D3 X2 出場
    st, ab = d.stats_x2(d.trades_x2(ents0))
    res["cells"]["D3"], res["abn"]["D3"] = st, ab
    # M Minervini 忠實版重跑（凍結規格）
    st, ab, _ = d.stats(d.mv.trades(*vm.DEFAULT))
    res["cells"]["M"], res["abn"]["M"] = st, ab
    # R 隨機對照
    rnd = [ob.abn(m, d.mv.daily(d.random_trades(trs0, sd, *DEFAULT))[0]) for sd in range(n_random)]
    if rnd:
        ts = sorted(ob.tstat(pd.Series(x)) for x in rnd)
        real = res["cells"]["D0"]["alpha_t"]
        res["random"] = {"n": len(ts), "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))],
                         "real_pctl": sum(x < real for x in ts) / len(ts)}
    for k in ("D0", "D1", "D2", "D3", "M"):
        st = res["cells"][k]
        print(f"[{mk}] {k:3} 筆數 {st['trades']:6d}  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  beta {st['beta']:.2f}  "
              f"前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  "
              f"MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}  期望值 {st['expectancy']:+.2%}  持有 {st['avg_hold']:.0f} 日  "
              f"持倉 {st['avg_pos']:.0f}", file=sys.stderr)
    for stop, be in GRID:
        st = res["cells"][key(stop, be)]
        print(f"[{mk}] {key(stop, be)}  筆數 {st['trades']:6d}  alpha t {st['alpha_t']:5.2f}", file=sys.stderr)
    if rnd:
        r = res["random"]
        print(f"[{mk}] 隨機對照 {r['n']} 次：中位 {r['median']:.2f}、第 95 百分位 {r['p95']:.2f}；D0 在第 {r['real_pctl']:.0%} 百分位", file=sys.stderr)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def split_abn(mk: str, ab: dict) -> tuple[dict, dict]:
    sp = nb.MARKETS[mk]["split"].isoformat()[:7]
    return {k: v for k, v in ab.items() if k < sp}, {k: v for k, v in ab.items() if k >= sp}


def diff_series(a: dict, b: dict) -> dict:
    return {k: a[k] - b[k] for k in a if k in b}


def pool_all() -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}

    def pt(k: str, mks=MARKETS, src="abn") -> float:
        return ob.tstat(ob.pooled([R[mk][src][k] for mk in mks]))

    out = {"pooled": {k: pt(k) for k in ("D0", "D1", "D2", "D3", "M")}, "groups": {}, "grid": {}, "per_market": {}}
    out["pooled"]["D0_vs_ew"] = pt("D0", src="abn_ew")
    for g, mks in GROUPS.items():
        out["groups"][g] = {k: pt(k, mks) for k in ("D0", "M")}
    for stop, be in GRID:
        out["grid"][key(stop, be)] = pt(key(stop, be))
    pre = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["D0"])[0] for mk in MARKETS]))
    post = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["D0"])[1] for mk in MARKETS]))
    out["pooled"]["D0_pre"], out["pooled"]["D0_post"] = pre, post
    out["diff"] = {f"{a}-{b}": ob.tstat(ob.pooled([diff_series(R[mk]["abn"][a], R[mk]["abn"][b]) for mk in MARKETS]))
                   for a, b in (("M", "D0"), ("D0", "D1"), ("D0", "D2"), ("D0", "D3"))}
    n = min(len(RN[mk]) for mk in MARKETS)
    rt = sorted(ob.tstat(ob.pooled([RN[mk][i] for mk in MARKETS])) for i in range(n))
    real = out["pooled"]["D0"]
    out["random"] = {"n": n, "median": rt[n // 2], "p95": rt[int(0.95 * n)], "real_pctl": sum(x < real for x in rt) / n}
    for mk in MARKETS:
        c = R[mk]["cells"]
        out["per_market"][mk] = {k: {x: c[k].get(x) for x in ("alpha_t", "t_ew", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "cum_etf",
                                                           "mdd", "trades", "win", "avg_hold", "avg_pos", "top10_share")}
                                 for k in ("D0", "D1", "D2", "D3", "M")}
        out["per_market"][mk]["random"] = R[mk].get("random")
        out["per_market"][mk]["grid_ge15"] = sum(c[key(s, b)]["alpha_t"] >= 1.5 for s, b in GRID)
    pos = sum(R[mk]["cells"]["D0"]["alpha_t"] > 0 for mk in MARKETS)
    neg = sum(R[mk]["cells"]["D0"]["alpha_t"] < 0 for mk in MARKETS)
    grid_ok = sum(v >= 1.5 for v in out["grid"].values())
    min_trades = min(R[mk]["cells"]["D0"]["trades"] for mk in MARKETS)
    cond = {"1 合併 t ≥ 2.5": real >= 2.5, "2 ≥ 6/9 市場 alpha t > 0": pos >= 6, "3 隨機對照 ≥ 95%": out["random"]["real_pctl"] >= 0.95,
            "4 鄰域 ≥ 6/9 格合併 ≥ 1.5": grid_ok >= 6, "5 前後段合併都 > 0": pre > 0 and post > 0,
            "6 相對等權合併 ≥ 1.5": out["pooled"]["D0_vs_ew"] >= 1.5, "7 每市場 ≥ 100 筆": min_trades >= 100}
    if all(cond.values()):
        v = "🔍 有希望未證實（全部門檻通過）"
    elif real < 1.0 or neg >= 4:
        v = "☠️"
    else:
        v = "不確定"
    out["conditions"], out["verdict"] = cond, v
    out["summary"] = {"pos_markets": pos, "neg_markets": neg, "grid_ge15": grid_ok, "min_trades": min_trades}
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    print(f"D0 合併 alpha t {real:.2f}（前 {pre:.2f}／後 {post:.2f}；vs 等權 {out['pooled']['D0_vs_ew']:.2f}）  "
          f"隨機第 {out['random']['real_pctl']:.0%} 百分位（中位 {out['random']['median']:.2f}、p95 {out['random']['p95']:.2f}）  "
          f"alpha>0 {pos}/9  鄰域 ≥1.5 {grid_ok}/9  最少筆數 {min_trades}", file=sys.stderr)
    print("合併：" + "  ".join(f"{k} {v:.2f}" for k, v in out["pooled"].items()), file=sys.stderr)
    print("分解 t：" + "  ".join(f"{k} {v:.2f}" for k, v in out["diff"].items()), file=sys.stderr)
    for g, r in out["groups"].items():
        print(f"{g}：D0 {r['D0']:.2f}  M {r['M']:.2f}", file=sys.stderr)
    for k, ok in cond.items():
        print(f"  {'✓' if ok else '✗'} {k}", file=sys.stderr)
    print(f"→ {v}", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--check-sim", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        pool_all()
    elif args.market and args.check_sim:
        Discipline(args.market).check_sim()
    elif args.market and args.inspect:
        Discipline(args.market).inspect(args.inspect)
    elif args.market:
        run_market(args.market, args.random)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
