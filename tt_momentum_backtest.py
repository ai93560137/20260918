#!/usr/bin/env python3
"""趨勢模板動量組合（預先登記：stock_research/TT_MOMENTUM_BACKTEST.md，寫程式前已 commit；9 國一次、只測一次）。

    python3 tt_momentum_backtest.py --selftest                 # 月報酬與成本的手算例子
    python3 tt_momentum_backtest.py --market hk --inspect 3    # 印前 3 個換倉日的名單（不看績效）
    python3 tt_momentum_backtest.py --market hk --random 200   # 正式：P0／9 格／P1／R1／R2
    python3 tt_momentum_backtest.py --pool                     # 9 市場合併檢定 + 判決

- 每月最後一個交易日 t 收市：宇宙內、通過趨勢模板（含 RS ≥ 70）的股票，按 252 日報酬取前 20 檔；t 收市 ETF > 50 且 > 200 日線才持股，否則持現金
- t+1 開市成交，持有到下一個換倉日的 t+1 開市；等權；進入／離開名單各扣一邊成本
"""
import argparse
import gzip
import json
import math
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
from discipline_backtest import GROUPS, MARKETS, split_abn, diff_series  # noqa: E402

GRID = [(k, lb) for k in (10, 20, 40) for lb in (126, 252, 63)]
DEFAULT = (20, 252)
MIN_CAND = 5
OUT = ROOT / "research" / "tt_momentum"


def key(k: int, lb: int) -> str:
    return f"{k}檔 回看{lb}日"


def month_return(rets: list[float], n_enter: int, n_leave: int, n_hold: int, cost: float) -> float:
    """月報酬 = 持股平均報酬 − 成本 × (進入數 + 離開數) ÷ 持股數；清倉月 = −成本 × 離開數 ÷ 原持股數。"""
    if n_hold == 0:
        return -cost if n_leave > 0 else 0.0
    return float(np.mean(rets)) - cost * (n_enter + n_leave) / n_hold


def selftest() -> None:
    r = month_return([0.10, -0.05, 0.02], 2, 1, 3, 0.001)
    assert abs(r - (0.07 / 3 - 0.001)) < 1e-12, r
    assert month_return([], 0, 3, 0, 0.001) == -0.001
    assert month_return([], 0, 0, 0, 0.001) == 0.0
    print("selftest ok:", round(r, 6))


class TTMom:
    def __init__(self, mk: str):
        self.mk = mk
        self.vf = vf = vb.VCPData(mk, full=True, scan=False)
        self.m = m = vf.m
        self.tt = vf.tt
        S, D = m.adj.shape
        self.D = D
        self.cost = m.cfg["cost"]
        lvl = np.cumprod(1 + m.etf_ret)
        s = pd.Series(lvl)
        self.mkt_ok = ((s > s.rolling(50).mean()) & (s > s.rolling(200).mean())).to_numpy()
        idx = pd.to_datetime(m.cal)
        ser = pd.Series(range(D), index=idx)
        reb = [int(g.iloc[-1]) for _, g in ser.groupby([idx.year, idx.month])]
        self.reb = [j for j in reb if j >= m.start_j and j + 1 < D]
        self.locked = ob.locked_matrix(m, mk)
        filled = pd.DataFrame(m.adj.T).ffill().to_numpy().T      # 停牌日用前收（只用於回看報酬）
        self.filled = filled
        # 回看報酬用每檔股票的完整歷史（日曆只從樣本起點前 30 日開始，矩陣算不到第一年的 252 日報酬）
        idx_cal = pd.Index(m.cal)
        self.rl = {lb: np.full((S, D), np.nan) for lb in sorted({lb for _, lb in GRID})}
        for s_i, rw in vf.raw.items():
            ser = pd.Series(rw["adj"], index=list(rw["dates"]))
            for lb, r in self.rl.items():
                r[s_i] = (ser / ser.shift(lb) - 1).reindex(idx_cal).to_numpy(dtype=float)
        for r in self.rl.values():
            r[~m.has] = np.nan
        # 數據斷點（手冊第 11 條：跑數前先掃極端報酬）：原始收市一日 > +100% 或 < −60%（Close 已按拆股還原，多為上市前垃圾列縫接、代碼重用）
        # → 該股在斷點前 25 日至後 252 日不作候選、不入等權基準（9 市場同一規則，跑數前定）
        self.bad = np.zeros((S, D), dtype=bool)
        n_break = 0
        for s_i, rw in vf.raw.items():
            c = rw["close"]
            pc = c[1:] / c[:-1] - 1
            for i in np.nonzero((pc > 1.0) | (pc < -0.6))[0]:
                jb = m.ci.get(list(rw["dates"])[i + 1])
                if jb is None:
                    continue
                self.bad[s_i, max(0, jb - 25):min(D, jb + 253)] = True      # 換倉日 j：斷點在回看窗口 (j−252, j] 或持有月 (j, j+25] 內都不作候選
                n_break += 1
        mask = m.member & m.has & ~self.bad
        self.ew_clean = np.where(mask.sum(0) > 0, (m.ret * mask).sum(0) / np.maximum(mask.sum(0), 1), 0.0)
        self.n_break = n_break
        print(f"[{mk}] 數據斷點 {n_break} 個；斷點窗口內的股票日 {int((self.bad & m.member).sum())}（宇宙內）", file=sys.stderr)
        self.ew_m = None
        print(f"[{mk}] 換倉日 {len(self.reb)} 個（{m.cal[self.reb[0]]} ~ {m.cal[self.reb[-1]]}）、大市過濾通過 {sum(self.mkt_ok[j] for j in self.reb)} 個", file=sys.stderr)

    # ---------- 價格 ----------
    def px_in(self, s: int, a: int) -> float | None:
        m = self.m
        j = m.next_px[s, a]
        if j >= self.D or j > a + 5:                 # 換倉後 5 日內沒有價格 → 買不到
            return None
        return float(m.aopen[s, j])

    def px_out(self, s: int, b: int) -> float:
        m = self.m
        if m.has[s, b]:
            return float(m.aopen[s, b])
        if m.last_px[s] < b:                        # 下市：最後收市
            return float(m.adj[s, m.last_px[s]])
        j = m.next_px[s, b]
        return float(m.aopen[s, j]) if j < self.D else float(self.filled[s, b])

    # ---------- 選股 ----------
    def select(self, j: int, k: int, lb: int, rng=None, pool: str = "tt") -> list[int]:
        m = self.m
        a = j + 1
        if pool == "tt":
            cand = np.nonzero(self.tt[:, j] & ~np.isnan(self.rl[lb][:, j]) & ~self.locked[:, a] & ~self.bad[:, j])[0]
        else:                                        # R2：宇宙內有數據
            cand = np.nonzero(m.member[:, j] & m.has[:, j] & ~self.locked[:, a] & ~self.bad[:, j])[0]
        if len(cand) < MIN_CAND:
            return []
        if rng is None:
            order = np.argsort(-self.rl[lb][cand, j], kind="stable")
            return [int(x) for x in cand[order[:k]]]
        return [int(x) for x in rng.choice(cand, size=min(k, len(cand)), replace=False)]

    # ---------- 回測 ----------
    def run(self, k: int, lb: int, market_filter: bool = True, seed: int | None = None, pool: str = "tt") -> dict:
        m = self.m
        rng = np.random.default_rng(seed) if seed is not None else None
        held: list[int] = []
        rows = []
        for i, j in enumerate(self.reb):
            a = j + 1
            b = self.reb[i + 1] + 1 if i + 1 < len(self.reb) else self.D - 1
            if market_filter and not self.mkt_ok[j]:
                new = []
            else:
                new = self.select(j, k, lb, rng, pool)
            rets = []
            kept = []
            for s in new:
                pi = self.px_in(s, a)
                if pi is None or not (pi > 0):
                    continue
                po = self.px_out(s, b)
                rets.append(po / pi - 1)
                kept.append(s)
            n_enter = len([s for s in kept if s not in held])
            n_leave = len([s for s in held if s not in kept])
            r = month_return(rets, n_enter, n_leave, len(kept), self.cost)
            etf = float(np.prod(1 + m.etf_ret[a:b + 1]) - 1)
            ew = float(np.prod(1 + self.ew_clean[a:b + 1]) - 1)
            rows.append({"month": m.cal[b].isoformat()[:7], "ret": r, "etf": etf, "ew": ew, "n": len(kept),
                         "turn": (n_enter + n_leave) / 2 / max(k, 1), "invested": len(kept) > 0, "date": m.cal[j]})
            held = kept
        return self.stats(pd.DataFrame(rows))

    def stats(self, df: pd.DataFrame) -> dict:
        m = self.m
        mo = pd.Series(df["ret"].to_numpy(), index=pd.to_datetime(df["month"]))
        me = pd.Series(df["etf"].to_numpy(), index=mo.index)
        mw = pd.Series(df["ew"].to_numpy(), index=mo.index)
        a, b, t = m.capm(mo, me)
        t_ew = m.capm(mo, mw)[2]
        sp = pd.Timestamp(m.cfg["split"])
        pre = m.capm(mo[mo.index < sp], me[me.index < sp])[2] if (mo.index < sp).sum() > 24 else float("nan")
        post = m.capm(mo[mo.index >= sp], me[me.index >= sp])[2] if (mo.index >= sp).sum() > 24 else float("nan")
        eq, eqe = (1 + mo).cumprod(), (1 + me).cumprod()
        yrs = len(mo) / 12
        w, l_ = mo[mo > 0], mo[mo <= 0]
        _, bb, _ = m.capm(mo, me)
        abn = (mo - bb * me)
        return {"months": int(len(mo)), "invested_months": int(df["invested"].sum()), "alpha_t": t, "beta": b, "t_ew": t_ew,
                "t_pre": pre, "t_post": post, "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "cagr_etf": float(eqe.iloc[-1] ** (1 / yrs) - 1),
                "cum": float(eq.iloc[-1] - 1), "cum_etf": float(eqe.iloc[-1] - 1),
                "mdd": float((eq / eq.cummax() - 1).min()), "mdd_etf": float((eqe / eqe.cummax() - 1).min()),
                "win": float((mo > 0).mean()), "profit_factor": float(w.sum() / -l_.sum()) if len(l_) and l_.sum() < 0 else float("nan"),
                "avg_month": float(mo.mean()), "turnover_year": float(df["turn"].mean() * 12), "avg_n": float(df.loc[df["invested"], "n"].mean()) if df["invested"].any() else 0.0,
                "abn": {str(kk.date())[:7]: float(v) for kk, v in abn.items()},
                "abn_ew": {str(kk.date())[:7]: float(v) for kk, v in (mo - m.capm(mo, mw)[1] * mw).items()},
                "monthly": {str(kk.date())[:7]: float(v) for kk, v in mo.items()},
                "period": f"{df['date'].iloc[0]}~{df['date'].iloc[-1]}"}

    def inspect(self, n: int) -> None:
        m = self.m
        shown = 0
        for j in self.reb:
            if not self.mkt_ok[j]:
                continue
            sel = self.select(j, *DEFAULT)
            print(f"換倉日 {m.cal[j]}  大市過濾 {self.mkt_ok[j]}  候選（通過模板）{int(self.tt[:, j].sum())} 檔 → 選 {len(sel)} 檔")
            for s in sel[:20]:
                print(f"   {m.tickers[s]:12} 252日報酬 {self.rl[252][s, j]:+.1%}  模板 {self.tt[s, j]}  t+1 開市 {self.px_in(s, j + 1)}")
            shown += 1
            if shown >= n:
                break


def run_market(mk: str, n_random: int) -> None:
    x = TTMom(mk)
    res = {"market": mk, "n_break": x.n_break, "cells": {}}
    for k, lb in GRID:
        st = x.run(k, lb)
        res["cells"][key(k, lb)] = st
        if (k, lb) == DEFAULT:
            res["cells"]["P0"] = st
    res["cells"]["P1"] = x.run(*DEFAULT, market_filter=False)
    r1 = [x.run(*DEFAULT, seed=sd, pool="tt")["abn"] for sd in range(n_random)]
    r2 = [x.run(*DEFAULT, seed=sd, pool="all")["abn"] for sd in range(n_random)]
    real = res["cells"]["P0"]["alpha_t"]
    for name, rr in (("R1", r1), ("R2", r2)):
        if rr:
            ts = sorted(ob.tstat(pd.Series(v)) for v in rr)
            res[name] = {"n": len(ts), "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))], "real_pctl": sum(v < real for v in ts) / len(ts)}
    for k in ("P0", "P1"):
        st = res["cells"][k]
        print(f"[{mk}] {k}  {st['period']}  月數 {st['months']}（持股 {st['invested_months']}）  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  beta {st['beta']:.2f}  "
              f"前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}（ETF {st['mdd_etf']:.0%}）  "
              f"月勝率 {st['win']:.0%}  月PF {st['profit_factor']:.2f}  年換手 {st['turnover_year']:.0%}  平均持股 {st['avg_n']:.0f}", file=sys.stderr)
    for k, lb in GRID:
        c = res["cells"][key(k, lb)]
        print(f"[{mk}] {key(k, lb)}  alpha t {c['alpha_t']:5.2f}  vs等權 {c['t_ew']:5.2f}  年化 {c['cagr']:+.1%}  MDD {c['mdd']:.0%}  換手 {c['turnover_year']:.0%}", file=sys.stderr)
    for name in ("R1", "R2"):
        if name in res:
            q = res[name]
            print(f"[{mk}] {name} 隨機 {q['n']} 次：中位 {q['median']:.2f}、p95 {q['p95']:.2f}；P0 在第 {q['real_pctl']:.0%} 百分位", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"R1": r1, "R2": r2}, f)


def pool_all() -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}

    def pt(k, mks=MARKETS, src="abn"):
        return ob.tstat(ob.pooled([R[mk]["cells"][k][src] for mk in mks]))

    out = {"pooled": {"P0": pt("P0"), "P0_vs_ew": pt("P0", src="abn_ew"), "P1": pt("P1")},
           "groups": {g: {"P0": pt("P0", mks), "P0_vs_ew": pt("P0", mks, "abn_ew")} for g, mks in GROUPS.items()},
           "grid": {key(k, lb): pt(key(k, lb)) for k, lb in GRID}, "per_market": {}}
    out["pooled"]["P0_pre"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["cells"]["P0"]["abn"])[0] for mk in MARKETS]))
    out["pooled"]["P0_post"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["cells"]["P0"]["abn"])[1] for mk in MARKETS]))
    out["diff"] = {"P0-P1": ob.tstat(ob.pooled([diff_series(R[mk]["cells"]["P0"]["monthly"], R[mk]["cells"]["P1"]["monthly"]) for mk in MARKETS]))}
    out["random"] = {}
    for name in ("R1", "R2"):
        n = min(len(RN[mk][name]) for mk in MARKETS)
        rt = sorted(ob.tstat(ob.pooled([RN[mk][name][i] for mk in MARKETS])) for i in range(n))
        out["random"][name] = {"n": n, "median": rt[n // 2], "p95": rt[int(0.95 * n)], "real_pctl": sum(v < out["pooled"]["P0"] for v in rt) / n}
    allm = [v for mk in MARKETS for v in R[mk]["cells"]["P0"]["monthly"].values()]
    w = sum(v for v in allm if v > 0)
    l_ = -sum(v for v in allm if v <= 0)
    out["A"] = {"months": len(allm), "win": sum(v > 0 for v in allm) / len(allm), "profit_factor": w / l_ if l_ > 0 else float("nan"),
                "mdd_ok_markets": sum(R[mk]["cells"]["P0"]["mdd"] >= 1.5 * R[mk]["cells"]["P0"]["mdd_etf"] for mk in MARKETS),
                "turnover_year_avg": float(np.mean([R[mk]["cells"]["P0"]["turnover_year"] for mk in MARKETS]))}
    for mk in MARKETS:
        c = R[mk]["cells"]
        out["per_market"][mk] = {k: {x: c[k][x] for x in ("alpha_t", "t_ew", "beta", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "cum_etf", "mdd", "mdd_etf",
                                                           "months", "invested_months", "win", "profit_factor", "turnover_year", "avg_n")} for k in ("P0", "P1")}
        out["per_market"][mk]["R1"], out["per_market"][mk]["R2"] = R[mk].get("R1"), R[mk].get("R2")
        out["per_market"][mk]["grid_ge15"] = sum(c[key(k, lb)]["alpha_t"] >= 1.5 for k, lb in GRID)
    real = out["pooled"]["P0"]
    pos = sum(R[mk]["cells"]["P0"]["alpha_t"] > 0 for mk in MARKETS)
    neg = sum(R[mk]["cells"]["P0"]["alpha_t"] < 0 for mk in MARKETS)
    grid_ok = sum(v >= 1.5 for v in out["grid"].values())
    min_inv = min(R[mk]["cells"]["P0"]["invested_months"] for mk in MARKETS)
    A = {"A1 月獲利因子 ≥ 1.3": out["A"]["profit_factor"] >= 1.3, "A2 MDD ≤ 1.5×ETF 的市場 ≥ 6/9": out["A"]["mdd_ok_markets"] >= 6,
         "A3 年換手 ≤ 800%": out["A"]["turnover_year_avg"] <= 8.0}
    B = {"B1 合併 alpha t ≥ 2.5": real >= 2.5, "B2 ≥ 6/9 市場 alpha t > 0": pos >= 6, "B3 R2 ≥ 95%": out["random"]["R2"]["real_pctl"] >= 0.95,
         "B4 鄰域 ≥ 6/9 格 ≥ 1.5": grid_ok >= 6, "B5 前後段都 > 0": out["pooled"]["P0_pre"] > 0 and out["pooled"]["P0_post"] > 0,
         "B6 相對等權合併 ≥ 2.0": out["pooled"]["P0_vs_ew"] >= 2.0, "B7 每市場持股月 ≥ 60": min_inv >= 60}
    if all(A.values()) and all(B.values()):
        v = "🔍 有希望未證實（A、B 全過）"
    elif real < 1.0 or neg >= 4:
        v = "☠️"
    elif B["B1 合併 alpha t ≥ 2.5"] and B["B2 ≥ 6/9 市場 alpha t > 0"] and B["B5 前後段都 > 0"] and not (B["B3 R2 ≥ 95%"] and B["B6 相對等權合併 ≥ 2.0"]):
        v = "只是動量 beta（B1、B2、B5 過，B3 或 B6 不過）"
    else:
        v = "不確定"
    out["conditions"], out["verdict"] = {**A, **B}, v
    out["summary"] = {"pos_markets": pos, "neg_markets": neg, "grid_ge15": grid_ok, "min_invested_months": min_inv}
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    a = out["A"]
    print(f"A：{a['months']} 個月  月勝率 {a['win']:.0%}  月PF {a['profit_factor']:.2f}  MDD 達標市場 {a['mdd_ok_markets']}/9  平均年換手 {a['turnover_year_avg']:.0%}", file=sys.stderr)
    print(f"P0 合併 alpha t {real:.2f}（前 {out['pooled']['P0_pre']:.2f}／後 {out['pooled']['P0_post']:.2f}；vs 等權 {out['pooled']['P0_vs_ew']:.2f}）  P1（無大市過濾）{out['pooled']['P1']:.2f}  "
          f"P0−P1 {out['diff']['P0-P1']:.2f}  R2 第 {out['random']['R2']['real_pctl']:.0%} 百分位（中位 {out['random']['R2']['median']:.2f}）  R1 第 {out['random']['R1']['real_pctl']:.0%}（中位 {out['random']['R1']['median']:.2f}）  "
          f"alpha>0 {pos}/9  鄰域 {grid_ok}/9", file=sys.stderr)
    for g, r in out["groups"].items():
        print(f"{g}：P0 {r['P0']:.2f}  vs等權 {r['P0_vs_ew']:.2f}", file=sys.stderr)
    for k, ok in out["conditions"].items():
        print(f"  {'✓' if ok else '✗'} {k}", file=sys.stderr)
    print(f"→ {v}", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--selftest", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.selftest:
        selftest()
    elif args.pool:
        pool_all()
    elif args.market and args.inspect:
        TTMom(args.market).inspect(args.inspect)
    elif args.market:
        run_market(args.market, args.random)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
