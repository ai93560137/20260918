#!/usr/bin/env python3
"""趨勢模板股全部等權（預先登記：stock_research/TT_MOMENTUM_BACKTEST.md 第三部分，寫程式前已 commit；9 國一次、只測一次）。

    python3 tt_all_backtest.py --market hk --inspect 2     # 印前 2 個換倉日的名單數目（不看績效）
    python3 tt_all_backtest.py --market hk --random 200    # 正式：P_ALL／9 格／R2
    python3 tt_all_backtest.py --pool

- 每月月底：宇宙內、通過趨勢模板（含 RS ≥ 70）、非斷點窗口、非漲停鎖死的股票**全部**等權；t 收市 ETF > 50 且 > 200 日線否則持現金
- 鄰域：上限 {40, 80, 不設}（超過時隨機抽，種子 0）× 大市過濾 {50 且 200, 只 200, 不用}
- R2：同一換倉日、同大市過濾，宇宙內隨機挑同樣檔數（200 次）
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import oos_backtest as ob  # noqa: E402
import tt_momentum_backtest as T  # noqa: E402
from discipline_backtest import GROUPS, MARKETS, split_abn, diff_series  # noqa: E402

CAPS = (40, 80, None)
MFS = ("50&200", "200", "none")
GRID = [(cap, mf) for cap in CAPS for mf in MFS]
DEFAULT = (None, "50&200")
OUT = ROOT / "research" / "tt_all"
ROUND1 = ROOT / "research" / "tt_momentum"


def key(cap, mf: str) -> str:
    return f"上限{cap if cap else '無'} 過濾{mf}"


class TTAll(T.TTMom):
    def __init__(self, mk: str):
        super().__init__(mk)
        s = pd.Series(np.cumprod(1 + self.m.etf_ret))
        self.mkt = {"50&200": self.mkt_ok, "200": (s > s.rolling(200).mean()).to_numpy(), "none": np.ones(self.D, dtype=bool)}

    def cand_tt(self, j: int) -> np.ndarray:
        return np.nonzero(self.tt[:, j] & ~self.locked[:, j + 1] & ~self.bad[:, j])[0]

    def cand_all(self, j: int) -> np.ndarray:
        m = self.m
        return np.nonzero(m.member[:, j] & m.has[:, j] & ~self.locked[:, j + 1] & ~self.bad[:, j])[0]

    def run_all(self, cap, mf: str, seed: int | None = None, pool: str = "tt") -> dict:
        m = self.m
        rng_cap = np.random.default_rng(0)
        rng = np.random.default_rng(seed) if seed is not None else None
        held: list[int] = []
        rows = []
        for i, j in enumerate(self.reb):
            a = j + 1
            b = self.reb[i + 1] + 1 if i + 1 < len(self.reb) else self.D - 1
            new: list[int] = []
            if self.mkt[mf][j]:
                c = self.cand_tt(j)
                if len(c) >= T.MIN_CAND:
                    n = len(c) if not cap else min(cap, len(c))
                    if pool == "tt":
                        new = [int(x) for x in (c if n == len(c) else rng_cap.choice(c, size=n, replace=False))]
                    else:
                        u = self.cand_all(j)
                        new = [int(x) for x in rng.choice(u, size=min(n, len(u)), replace=False)]
            rets, kept = [], []
            for s in new:
                pi = self.px_in(s, a)
                if pi is None or not (pi > 0):
                    continue
                rets.append(self.px_out(s, b) / pi - 1)
                kept.append(s)
            hs = set(held)
            ks = set(kept)
            n_enter, n_leave = len(ks - hs), len(hs - ks)
            r = T.month_return(rets, n_enter, n_leave, len(kept), self.cost)
            rows.append({"month": m.cal[b].isoformat()[:7], "ret": r, "etf": float(np.prod(1 + m.etf_ret[a:b + 1]) - 1),
                         "ew": float(np.prod(1 + self.ew_clean[a:b + 1]) - 1), "n": len(kept),
                         "turn": (n_enter + n_leave) / 2 / max(len(kept), len(held), 1), "invested": len(kept) > 0, "date": m.cal[j]})
            held = kept
        return self.stats(pd.DataFrame(rows))

    def inspect_all(self, n: int) -> None:
        m = self.m
        shown = 0
        for j in self.reb:
            if not self.mkt_ok[j]:
                continue
            c = self.cand_tt(j)
            print(f"換倉日 {m.cal[j]}  通過模板 {int(self.tt[:, j].sum())} 檔、扣斷點窗口／漲停 → 候選 {len(c)} 檔  大市 50&200 {self.mkt['50&200'][j]}  只200 {self.mkt['200'][j]}"
                  f"  例：{[m.tickers[s] for s in c[:5]]}")
            shown += 1
            if shown >= n:
                break


def run_market(mk: str, n_random: int) -> None:
    x = TTAll(mk)
    res = {"market": mk, "n_break": x.n_break, "cells": {}}
    for cap, mf in GRID:
        st = x.run_all(cap, mf)
        res["cells"][key(cap, mf)] = st
        if (cap, mf) == DEFAULT:
            res["cells"]["P_ALL"] = st
    r2 = [x.run_all(*DEFAULT, seed=sd, pool="all")["abn"] for sd in range(n_random)]
    if r2:
        ts = sorted(ob.tstat(pd.Series(v)) for v in r2)
        real = res["cells"]["P_ALL"]["alpha_t"]
        res["R2"] = {"n": len(ts), "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))], "real_pctl": sum(v < real for v in ts) / len(ts)}
    st = res["cells"]["P_ALL"]
    print(f"[{mk}] P_ALL  {st['period']}  月數 {st['months']}（持股 {st['invested_months']}）  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  beta {st['beta']:.2f}  "
          f"前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}（ETF {st['mdd_etf']:.0%}）  "
          f"月勝率 {st['win']:.0%}  月PF {st['profit_factor']:.2f}  年換手 {st['turnover_year']:.0%}  平均持股 {st['avg_n']:.0f}", file=sys.stderr)
    for cap, mf in GRID:
        c = res["cells"][key(cap, mf)]
        print(f"[{mk}] {key(cap, mf):18}  alpha t {c['alpha_t']:5.2f}  vs等權 {c['t_ew']:5.2f}  年化 {c['cagr']:+.1%}  MDD {c['mdd']:.0%}  換手 {c['turnover_year']:.0%}  持股 {c['avg_n']:.0f}", file=sys.stderr)
    if r2:
        q = res["R2"]
        print(f"[{mk}] R2 隨機 {q['n']} 次：中位 {q['median']:.2f}、p95 {q['p95']:.2f}；P_ALL 在第 {q['real_pctl']:.0%} 百分位", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"R2": r2}, f)


def pool_all() -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}
    R1 = {mk: json.loads((ROUND1 / f"{mk}.json").read_text(encoding="utf-8"))["cells"]["P0"] for mk in MARKETS}

    def pt(k, mks=MARKETS, src="abn"):
        return ob.tstat(ob.pooled([R[mk]["cells"][k][src] for mk in mks]))

    out = {"pooled": {"P_ALL": pt("P_ALL"), "P_ALL_vs_ew": pt("P_ALL", src="abn_ew")},
           "groups": {g: {"P_ALL": pt("P_ALL", mks), "P_ALL_vs_ew": pt("P_ALL", mks, "abn_ew")} for g, mks in GROUPS.items()},
           "grid": {key(cap, mf): pt(key(cap, mf)) for cap, mf in GRID},
           "grid_vs_ew": {key(cap, mf): pt(key(cap, mf), src="abn_ew") for cap, mf in GRID}, "per_market": {}}
    out["pooled"]["P_ALL_pre"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["cells"]["P_ALL"]["abn"])[0] for mk in MARKETS]))
    out["pooled"]["P_ALL_post"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["cells"]["P_ALL"]["abn"])[1] for mk in MARKETS]))
    out["pooled"]["P0_round1"] = ob.tstat(ob.pooled([R1[mk]["abn"] for mk in MARKETS]))
    out["diff"] = {"P_ALL-P0": ob.tstat(ob.pooled([diff_series(R[mk]["cells"]["P_ALL"]["monthly"], R1[mk]["monthly"]) for mk in MARKETS]))}
    n = min(len(RN[mk]["R2"]) for mk in MARKETS)
    rt = sorted(ob.tstat(ob.pooled([RN[mk]["R2"][i] for mk in MARKETS])) for i in range(n))
    real = out["pooled"]["P_ALL"]
    out["random"] = {"R2": {"n": n, "median": rt[n // 2], "p95": rt[int(0.95 * n)], "real_pctl": sum(v < real for v in rt) / n}}
    allm = [v for mk in MARKETS for v in R[mk]["cells"]["P_ALL"]["monthly"].values()]
    w = sum(v for v in allm if v > 0)
    l_ = -sum(v for v in allm if v <= 0)
    out["A"] = {"months": len(allm), "win": sum(v > 0 for v in allm) / len(allm), "profit_factor": w / l_ if l_ > 0 else float("nan"),
                "mdd_ok_markets": sum(R[mk]["cells"]["P_ALL"]["mdd"] >= 1.5 * R[mk]["cells"]["P_ALL"]["mdd_etf"] for mk in MARKETS),
                "turnover_year_avg": float(np.mean([R[mk]["cells"]["P_ALL"]["turnover_year"] for mk in MARKETS]))}
    for mk in MARKETS:
        c = R[mk]["cells"]
        out["per_market"][mk] = {"P_ALL": {x: c["P_ALL"][x] for x in ("alpha_t", "t_ew", "beta", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "cum_etf", "mdd", "mdd_etf",
                                                                   "months", "invested_months", "win", "profit_factor", "turnover_year", "avg_n")},
                                 "R2": R[mk].get("R2"), "grid_ge15": sum(c[key(cap, mf)]["alpha_t"] >= 1.5 for cap, mf in GRID),
                                 "grid": {key(cap, mf): {"alpha_t": c[key(cap, mf)]["alpha_t"], "t_ew": c[key(cap, mf)]["t_ew"], "avg_n": c[key(cap, mf)]["avg_n"]} for cap, mf in GRID}}
    pos = sum(R[mk]["cells"]["P_ALL"]["alpha_t"] > 0 for mk in MARKETS)
    neg = sum(R[mk]["cells"]["P_ALL"]["alpha_t"] < 0 for mk in MARKETS)
    grid_ok = sum(v >= 1.5 for v in out["grid"].values())
    min_inv = min(R[mk]["cells"]["P_ALL"]["invested_months"] for mk in MARKETS)
    A = {"A1 月獲利因子 ≥ 1.3": out["A"]["profit_factor"] >= 1.3, "A2 MDD ≤ 1.5×ETF 的市場 ≥ 6/9": out["A"]["mdd_ok_markets"] >= 6,
         "A3 年換手 ≤ 800%": out["A"]["turnover_year_avg"] <= 8.0}
    B = {"B1 合併 alpha t ≥ 2.5": real >= 2.5, "B2 ≥ 6/9 市場 alpha t > 0": pos >= 6, "B3 R2 ≥ 95%": out["random"]["R2"]["real_pctl"] >= 0.95,
         "B4 鄰域 ≥ 6/9 格 ≥ 1.5": grid_ok >= 6, "B5 前後段都 > 0": out["pooled"]["P_ALL_pre"] > 0 and out["pooled"]["P_ALL_post"] > 0,
         "B6 相對等權合併 ≥ 2.0": out["pooled"]["P_ALL_vs_ew"] >= 2.0, "B7 每市場持股月 ≥ 60": min_inv >= 60}
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
    print(f"P_ALL 合併 alpha t {real:.2f}（前 {out['pooled']['P_ALL_pre']:.2f}／後 {out['pooled']['P_ALL_post']:.2f}；vs 等權 {out['pooled']['P_ALL_vs_ew']:.2f}）  "
          f"第一輪 P0 {out['pooled']['P0_round1']:.2f}  P_ALL−P0 {out['diff']['P_ALL-P0']:.2f}  R2 第 {out['random']['R2']['real_pctl']:.0%} 百分位（中位 {out['random']['R2']['median']:.2f}）  "
          f"alpha>0 {pos}/9  鄰域 {grid_ok}/9", file=sys.stderr)
    print("鄰域 vs ETF：" + "  ".join(f"{k} {v:.2f}" for k, v in out["grid"].items()), file=sys.stderr)
    print("鄰域 vs 等權：" + "  ".join(f"{k} {v:.2f}" for k, v in out["grid_vs_ew"].items()), file=sys.stderr)
    for g, r in out["groups"].items():
        print(f"{g}：P_ALL {r['P_ALL']:.2f}  vs等權 {r['P_ALL_vs_ew']:.2f}", file=sys.stderr)
    for k, ok in out["conditions"].items():
        print(f"  {'✓' if ok else '✗'} {k}", file=sys.stderr)
    print(f"→ {v}", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        pool_all()
    elif args.market and args.inspect:
        TTAll(args.market).inspect_all(args.inspect)
    elif args.market:
        run_market(args.market, args.random)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
