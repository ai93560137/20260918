#!/usr/bin/env python3
"""低勝率、30:1 風險回報策略回測（預先登記：stock_research/RRR30_BACKTEST.md，寫程式前已 commit；9 個市場同一規格、只測一次）。

    python3 rrr30_backtest.py --market hk --check-sim      # 機制檢查：退化參數（7.5%／保本 1.15／50 日線／252 日）必須與 Minervini.simulate 逐筆相同
    python3 rrr30_backtest.py --market hk --inspect 10     # 機制檢查：印預設格前 10 筆（不看績效）
    python3 rrr30_backtest.py --market hk --random 200     # 正式：先抽 300 筆內部一致性（可疑 > 5% 就停），再跑 S0／9 格／R
    python3 rrr30_backtest.py --pool                       # 9 市場合併檢定 + 判決（M 用 research/discipline/<m>.json 的 abn["M"]）

- 入場 = Minervini 忠實版（VCP 樞紐點盤中成交、不追高 5%、大市 50/200 日線過濾）
- S0 出場：硬止損 成交價 × (1 − 3%) 永不移動；收市跌破 200 日線 → 下一日開市出；
  收市曾 ≥ 成交價 × 1.90（30R）之後，收市跌破入場後最高收市 × (1 − 20%) → 下一日開市出；無持有上限
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
from discipline_backtest import GROUPS, MARKETS, abn_vs, minervini_suspects, split_abn, diff_series  # noqa: E402

GRID = [(stop, trail) for stop in (0.02, 0.03, 0.04) for trail in (0.15, 0.20, 0.25)]
DEFAULT = (0.03, 0.20)
TARGET_R = 30
OUT = ROOT / "research" / "rrr30"
DISC = ROOT / "research" / "discipline"
SAMPLE_N, SAMPLE_MAX_SUSPECT = 300, 0.05


def key(stop: float, trail: float) -> str:
    return f"止損{stop:.0%} 追蹤{trail:.0%}"


def sim_gen(rw: dict, p: int, fill: float, stop_pct: float, ma_key: str, trail: float | None, target_mult: float | None,
            be_at: float | None, cap: int | None) -> tuple[int, float, bool, bool]:
    """通用出場模擬（骨架 = discipline_backtest.sim_fast，已與 Minervini.simulate 逐筆比對）。
    回傳 (出場 raw 索引, 出場原始價, 收市出場, 曾到達目標)。
    每日次序：入場日只看止損；之後每日先看「前一日已觸發的下一日開市出」（MA／追蹤），再看盤中止損 min(開市, 止損)，
    再更新保本、目標、峰值、MA 與追蹤旗標。"""
    low, close, opn, adj, ma = rw["low"], rw["close"], rw["open"], rw["adj"], rw[ma_key]
    n = len(close)
    stop0 = fill * (1 - stop_pct)
    if low[p] <= stop0:
        return p, stop0, False, False
    end = min(n, p + cap + 1) if cap else n
    L = end - p
    c, lo, o, a, mm = close[p:end], low[p:end], opn[p:end], adj[p:end], ma[p:end]
    o = np.where((o == o) & (o > 0), o, c)
    idx = np.arange(L)
    if be_at:
        be = np.nonzero(c >= fill * be_at)[0]
        be_i = be[0] if len(be) else L
        stop_lvl = np.where(idx > be_i, fill, stop0)
    else:
        stop_lvl = np.full(L, stop0)
    hit = np.nonzero((lo <= stop_lvl) & (idx > 0))[0]
    stop_i = int(hit[0]) if len(hit) else L
    mah = np.nonzero((mm == mm) & (a < mm))[0]
    ma_i = int(mah[0]) + 1 if len(mah) else L
    reached = False
    trail_i = L
    if target_mult and trail:
        rc = np.nonzero(c >= fill * target_mult)[0]
        if len(rc):
            r0 = int(rc[0])
            peak = np.maximum.accumulate(c)
            th = np.nonzero((idx >= r0) & (c < peak * (1 - trail)))[0]
            trail_i = int(th[0]) + 1 if len(th) else L
            reached_i = r0
        else:
            reached_i = L
    else:
        reached_i = L
    cap_i = L - 1
    ei = min(stop_i, ma_i, trail_i, cap_i)
    reached = reached_i < ei or (reached_i == ei and ei == cap_i)
    k = p + ei
    if ei == ma_i or ei == trail_i:
        return k, float(o[ei]), False, reached
    if ei == stop_i:
        return k, float(min(o[ei], stop_lvl[ei])), False, reached
    return k, float(c[ei]), True, reached


class RRR30:
    def __init__(self, mk: str):
        self.mk = mk
        self.vf = vf = vb.VCPData(mk, full=True, scan=False)
        self.m = m = vf.m
        self.mv = mv = vm.Minervini(mk, minervini_suspects(mk), v=vf)
        self.locked = ob.locked_matrix(m, mk)
        n0 = len(mv.setups)
        mv.setups = [x for x in mv.setups if not self.locked[x[0], x[2]]]
        self.locked_skipped = n0 - len(mv.setups)
        for s, rw in vf.raw.items():                              # 200 日線（還原價）
            rw["ma200"] = pd.Series(rw["adj"]).rolling(200).mean().to_numpy(dtype=float)
        self.last_cal = m.cal[-5]
        print(f"[{mk}] VCP 樞紐點突破 {len(mv.setups)}（漲停鎖死跳過 {self.locked_skipped}）", file=sys.stderr)

    def _trade(self, s, p, fill, k, px, at_close, reached) -> dict:
        t = self.mv._trade(s, p, fill, k, px, at_close)
        rw = self.vf.raw[s]
        dl = list(rw["dates"])
        t["reached"] = bool(reached)
        t["open_pos"] = bool(at_close and k == len(dl) - 1 and dl[k] >= self.last_cal)
        return t

    def trades(self, stop: float, trail: float, random_seed: int | None = None) -> list[dict]:
        m, v, mv = self.m, self.vf, self.mv
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy, by_day = [], {}, {}
        for (s_i, p, j, pivot, o, _) in mv.setups:
            by_day.setdefault(j, set()).add(s_i)
        for (s_i, p, j, pivot, o, _) in sorted(mv.setups, key=lambda x: (x[2], x[0])):
            if o > pivot * (1 + vm.DEFAULT[1]):
                continue
            if rng is None:
                if p <= busy.get(s_i, -1):
                    continue
                fill = max(o, pivot)
                k, px, ac, rc = sim_gen(v.raw[s_i], p, fill, stop, "ma200", trail, 1 + TARGET_R * stop, None, None)
                busy[s_i] = k
                out.append(self._trade(s_i, p, fill, k, px, ac, rc))
            else:   # 隨機對照：同日 t−1 通過趨勢模板、當天不是 VCP 突破的股票，t 開市買、同一套出場（同 Minervini 的隨機對照）
                pool = np.nonzero(v.tt[:, j - 1])[0]
                pool = pool[~np.isin(pool, list(by_day[j]))]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
                if self.locked[r, j]:
                    continue
                pr = v.raw[r]["dates"].get(m.cal[j])
                if pr is None:
                    continue
                o_r = v.raw[r]["open"][pr]
                if not (o_r == o_r and o_r > 0):
                    continue
                k, px, ac, rc = sim_gen(v.raw[r], pr, o_r, stop, "ma200", trail, 1 + TARGET_R * stop, None, None)
                out.append(self._trade(r, pr, o_r, k, px, ac, rc))
        return out

    def stats(self, trs: list[dict]) -> tuple[dict, dict, dict]:
        m = self.m
        daily, tr, n = self.mv.daily(trs)
        st = ob.summary(m, daily, tr, [t["b"] - t["a"] for t in trs], len(trs))
        mo = m.monthly(daily)
        st["t_ew"] = m.capm(mo, m.monthly(m.ew_ret))[2]
        st["avg_pos"] = float(n[m.start_j:].mean())
        s_tr = [x for x in tr if x == x]
        st["top10_share"] = float(sum(sorted(s_tr, reverse=True)[:10]) / sum(s_tr)) if sum(s_tr) > 0 else float("nan")
        st["reached_30r"] = float(np.mean([t["reached"] for t in trs])) if trs else float("nan")
        st["open_positions"] = int(sum(t["open_pos"] for t in trs))
        wins_hold = [t["b"] - t["a"] for t, x in zip(trs, tr) if x == x and x > 0]
        st["avg_hold_win"] = float(np.mean(wins_hold)) if wins_hold else float("nan")
        run = best = 0
        for x in tr:
            run = run + 1 if (x == x and x <= 0) else 0
            best = max(best, run)
        st["max_consec_loss"] = best
        st["tr_list"] = [float(x) for x in tr]
        return st, ob.abn(m, daily), abn_vs(m, daily, m.ew_ret)

    def sample_check(self, trs: list[dict]) -> dict:
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
            why = []
            if c_prev > 0 and abs(o / c_prev - 1) > 0.30:
                why.append(f"入場開市較前收跳 {o / c_prev - 1:+.0%}")
            if k > p and rw["close"][k - 1] > 0 and abs(px / rw["close"][k - 1] - 1) > 0.50:
                why.append(f"出場價較前收跳 {px / rw['close'][k - 1] - 1:+.0%}")
            if why:
                sus.append({"ticker": self.m.tickers[t["s"]], "entry": self.m.cal[t["a"]].isoformat(),
                            "exit": self.m.cal[t["b"]].isoformat(), "why": why})
        return {"n_sample": len(smp), "n_suspect": len(sus), "share": len(sus) / max(len(smp), 1), "suspects": sus}

    def inspect(self, n: int) -> None:
        m, v = self.m, self.vf
        for t in self.trades(*DEFAULT)[:n]:
            s, rw = t["s"], v.raw[t["s"]]
            p = rw["dates"][m.cal[t["a"]]]
            fill = t["in_adj"] / rw["adj"][p] * rw["close"][p]
            print(f"{m.tickers[s]:12} 入 {m.cal[t['a']]} 成交 {fill:.4g}（止損 {fill * (1 - DEFAULT[0]):.4g}、目標 {fill * (1 + TARGET_R * DEFAULT[0]):.4g}）"
                  f" → 出 {m.cal[t['b']]} {'收市（未平倉/下市）' if t['at_close'] else '開市/止損'}  到達30R {t['reached']}  "
                  f"毛 {t['out_adj'] / t['in_adj'] - 1:+.1%}")

    def check_sim(self) -> None:
        bad = n = 0
        for (s, p, j, pivot, o, _) in self.mv.setups:
            if o > pivot * (1 + vm.DEFAULT[1]):
                continue
            fill = max(o, pivot)
            for stop in (0.06, 0.075, 0.09):
                n += 1
                a = self.mv.simulate(s, p, fill, stop)
                b = sim_gen(self.vf.raw[s], p, fill, stop, "ma50", None, None, vm.BREAKEVEN_AT, vm.MAX_HOLD)[:3]
                if a[0] != b[0] or abs(a[1] - b[1]) > 1e-9 * max(1.0, abs(a[1])) or a[2] != b[2]:
                    bad += 1
                    if bad <= 5:
                        print(f"  不同：{self.m.tickers[s]} p={p} stop={stop} simulate={a} gen={b}", file=sys.stderr)
        print(f"[{self.mk}] 退化參數逐筆比對 {n} 次（{n // 3} 筆 × 3 個止損格）：不同 {bad}", file=sys.stderr)


def run_market(mk: str, n_random: int) -> None:
    r = RRR30(mk)
    trs0 = r.trades(*DEFAULT)
    chk = r.sample_check(trs0)
    print(f"[{mk}] S0 預設格 {len(trs0)} 筆；抽 {chk['n_sample']} 筆內部一致性：可疑 {chk['n_suspect']}（{chk['share']:.1%}）", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}_sample.json").write_text(json.dumps(chk, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if chk["share"] > SAMPLE_MAX_SUSPECT:
        print(f"[{mk}] 可疑 > {SAMPLE_MAX_SUSPECT:.0%}：按登記先查數據，未算績效", file=sys.stderr)
        return
    res = {"market": mk, "locked_skipped": r.locked_skipped, "sample_check": {k: v for k, v in chk.items() if k != "suspects"},
           "cells": {}, "abn": {}, "abn_ew": {}}
    for stop, trail in GRID:
        trs = trs0 if (stop, trail) == DEFAULT else r.trades(stop, trail)
        st, ab, ab_ew = r.stats(trs)
        k = key(stop, trail)
        res["cells"][k], res["abn"][k] = st, ab
        if (stop, trail) == DEFAULT:
            res["cells"]["S0"], res["abn"]["S0"], res["abn_ew"]["S0"] = st, ab, ab_ew
    rnd, rnd_tr = [], []
    for sd in range(n_random):
        trs = r.trades(*DEFAULT, random_seed=sd)
        daily, tr, _ = r.mv.daily(trs)
        rnd.append(ob.abn(r.m, daily))
        w = [x for x in tr if x == x and x > 0]
        l_ = [x for x in tr if x == x and x <= 0]
        rnd_tr.append(float(np.mean(w) / -np.mean(l_)) if w and l_ and np.mean(l_) < 0 else float("nan"))
    if rnd:
        ts = sorted(ob.tstat(pd.Series(x)) for x in rnd)
        real = res["cells"]["S0"]["alpha_t"]
        rr = sorted(x for x in rnd_tr if x == x)
        res["random"] = {"n": len(ts), "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))],
                         "real_pctl": sum(x < real for x in ts) / len(ts),
                         "rrr_median": rr[len(rr) // 2] if rr else None}
    st = res["cells"]["S0"]
    print(f"[{mk}] S0 筆數 {st['trades']:5d}  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
          f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}  勝率 {st['win']:.1%}  "
          f"平均贏 {st['avg_win']:+.1%}  平均輸 {st['avg_loss']:+.2%}  RRR {st['rrr']:.1f}  期望值 {st['expectancy']:+.2%}  "
          f"到達30R {st['reached_30r']:.1%}  前10筆 {st['top10_share']:.0%}  最長連虧 {st['max_consec_loss']}  "
          f"贏家持有 {st['avg_hold_win']:.0f} 日  未平倉 {st['open_positions']}", file=sys.stderr)
    for stop, trail in GRID:
        c = res["cells"][key(stop, trail)]
        print(f"[{mk}] {key(stop, trail)}  筆數 {c['trades']:5d}  alpha t {c['alpha_t']:5.2f}  RRR {c['rrr']:.1f}  勝率 {c['win']:.1%}", file=sys.stderr)
    if rnd:
        q = res["random"]
        print(f"[{mk}] 隨機對照 {q['n']} 次：alpha t 中位 {q['median']:.2f}、p95 {q['p95']:.2f}；S0 在第 {q['real_pctl']:.0%} 百分位；隨機 RRR 中位 {q['rrr_median']:.1f}",
              file=sys.stderr)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def pool_all() -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}
    M = {mk: json.loads((DISC / f"{mk}.json").read_text(encoding="utf-8"))["abn"]["M"] for mk in MARKETS}

    def pt(k, mks=MARKETS, src="abn"):
        return ob.tstat(ob.pooled([R[mk][src][k] for mk in mks]))

    out = {"pooled": {"S0": pt("S0"), "S0_vs_ew": pt("S0", src="abn_ew"),
                      "M": ob.tstat(ob.pooled([M[mk] for mk in MARKETS]))}, "groups": {}, "grid": {}, "per_market": {}}
    out["pooled"]["S0_pre"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["S0"])[0] for mk in MARKETS]))
    out["pooled"]["S0_post"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["S0"])[1] for mk in MARKETS]))
    out["diff"] = {"S0-M": ob.tstat(ob.pooled([diff_series(R[mk]["abn"]["S0"], M[mk]) for mk in MARKETS]))}
    for g, mks in GROUPS.items():
        out["groups"][g] = {"S0": pt("S0", mks), "M": ob.tstat(ob.pooled([M[mk] for mk in mks]))}
    for stop, trail in GRID:
        out["grid"][key(stop, trail)] = pt(key(stop, trail))
    n = min(len(RN[mk]) for mk in MARKETS)
    rt = sorted(ob.tstat(ob.pooled([RN[mk][i] for mk in MARKETS])) for i in range(n))
    real = out["pooled"]["S0"]
    out["random"] = {"n": n, "median": rt[n // 2], "p95": rt[int(0.95 * n)], "real_pctl": sum(x < real for x in rt) / n}
    # RRR：9 市場全部交易合併（每筆等權）
    all_tr = np.array([x for mk in MARKETS for x in R[mk]["cells"]["S0"]["tr_list"] if x == x])
    w, l_ = all_tr[all_tr > 0], all_tr[all_tr <= 0]
    out["rrr"] = {"pooled": float(w.mean() / -l_.mean()), "win": float(len(w) / len(all_tr)), "avg_win": float(w.mean()),
                  "avg_loss": float(l_.mean()), "expectancy": float(all_tr.mean()), "n": int(len(all_tr)),
                  "t_per_trade": float(all_tr.mean() / (all_tr.std(ddof=1) / np.sqrt(len(all_tr)))),
                  "reached_30r": float(np.mean([t for mk in MARKETS for t in [R[mk]["cells"]["S0"]["reached_30r"]] * R[mk]["cells"]["S0"]["trades"]])),
                  "per_market_ge20": sum(R[mk]["cells"]["S0"]["rrr"] >= 20 for mk in MARKETS)}
    for mk in MARKETS:
        c = R[mk]["cells"]["S0"]
        out["per_market"][mk] = {x: c[x] for x in ("alpha_t", "t_ew", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "cum_etf", "mdd",
                                                    "trades", "win", "avg_win", "avg_loss", "rrr", "expectancy", "profit_factor",
                                                    "reached_30r", "top10_share", "max_consec_loss", "avg_hold", "avg_hold_win",
                                                    "open_positions", "avg_pos")}
        out["per_market"][mk]["random"] = R[mk].get("random")
        out["per_market"][mk]["grid_ge15"] = sum(R[mk]["cells"][key(s, t)]["alpha_t"] >= 1.5 for s, t in GRID)
        out["per_market"][mk]["grid_rrr"] = {key(s, t): R[mk]["cells"][key(s, t)]["rrr"] for s, t in GRID}
    pos = sum(R[mk]["cells"]["S0"]["alpha_t"] > 0 for mk in MARKETS)
    neg = sum(R[mk]["cells"]["S0"]["alpha_t"] < 0 for mk in MARKETS)
    grid_ok = sum(v >= 1.5 for v in out["grid"].values())
    min_trades = min(R[mk]["cells"]["S0"]["trades"] for mk in MARKETS)
    A = {"A1 合併實現 RRR ≥ 30": out["rrr"]["pooled"] >= 30, "A2 ≥ 6/9 市場 RRR ≥ 20": out["rrr"]["per_market_ge20"] >= 6}
    B = {"B1 合併 alpha t ≥ 2.5": real >= 2.5, "B2 ≥ 6/9 市場 alpha t > 0": pos >= 6, "B3 隨機對照 ≥ 95%": out["random"]["real_pctl"] >= 0.95,
         "B4 鄰域 ≥ 6/9 格合併 ≥ 1.5": grid_ok >= 6, "B5 前後段合併都 > 0": out["pooled"]["S0_pre"] > 0 and out["pooled"]["S0_post"] > 0,
         "B6 相對等權合併 ≥ 1.5": out["pooled"]["S0_vs_ew"] >= 1.5, "B7 每市場 ≥ 100 筆": min_trades >= 100}
    if all(A.values()) and all(B.values()):
        v = "🔍 有希望未證實（A、B 全過）"
    elif real < 1.0 or neg >= 4 or out["rrr"]["pooled"] < 10:
        v = "☠️"
    elif all(A.values()) and real >= 1.0:
        v = "RRR 達標、無 alpha"
    else:
        v = "不確定"
    out["conditions"], out["verdict"] = {**A, **B}, v
    out["summary"] = {"pos_markets": pos, "neg_markets": neg, "grid_ge15": grid_ok, "min_trades": min_trades}
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    q = out["rrr"]
    print(f"RRR 合併 {q['pooled']:.1f}（勝率 {q['win']:.1%}、平均贏 {q['avg_win']:+.1%}、平均輸 {q['avg_loss']:+.2%}、期望值 {q['expectancy']:+.2%}、"
          f"逐筆 t {q['t_per_trade']:.2f}、到達 30R {q['reached_30r']:.1%}、{q['n']} 筆）  各市場 RRR ≥ 20：{q['per_market_ge20']}/9", file=sys.stderr)
    print(f"S0 合併 alpha t {real:.2f}（前 {out['pooled']['S0_pre']:.2f}／後 {out['pooled']['S0_post']:.2f}；vs 等權 {out['pooled']['S0_vs_ew']:.2f}）  "
          f"M 合併 {out['pooled']['M']:.2f}  S0−M {out['diff']['S0-M']:.2f}  隨機第 {out['random']['real_pctl']:.0%} 百分位（中位 {out['random']['median']:.2f}）  "
          f"alpha>0 {pos}/9  鄰域 {grid_ok}/9  最少筆數 {min_trades}", file=sys.stderr)
    for g, r in out["groups"].items():
        print(f"{g}：S0 {r['S0']:.2f}  M {r['M']:.2f}", file=sys.stderr)
    for k, ok in out["conditions"].items():
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
        RRR30(args.market).check_sim()
    elif args.market and args.inspect:
        RRR30(args.market).inspect(args.inspect)
    elif args.market:
        run_market(args.market, args.random)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
