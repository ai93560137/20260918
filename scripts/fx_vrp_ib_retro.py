#!/usr/bin/env python3
"""C 階段：IB 七貨幣隱含波動的方差賣方回溯（登記：forex_research/FX_EUR_VRP_IBKR.md 階段 C）。只跑一次。

    python3 scripts/fx_vrp_ib_retro.py --check                 # 跑前機制檢查（不算績效）
    python3 scripts/fx_vrp_ib_retro.py --out forex_research/fx_eur_vrp/ibkr_C
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PAIRS = {"EUR": "EURUSD", "GBP": "GBPUSD", "AUD": "AUDUSD", "NZD": "NZDUSD", "JPY": "USDJPY", "CHF": "USDCHF", "CAD": "USDCAD"}
ROLL_DAYS = ["2025-12-05", "2026-03-06", "2026-06-05", "2026-09-04"]
START, LAST_DAY, N = pd.Timestamp("2025-12-08"), pd.Timestamp("2026-09-23"), 21


def load_iv(ccy: str) -> pd.Series:
    d = pd.read_csv(ROOT / "data_forex_ibkr" / f"fut_{ccy}_D1_option_implied_volatility.csv.gz", parse_dates=["Time"])
    s = d.set_index("Time")["Close"] * 100
    s[s <= 0] = np.nan
    med = s.median()
    for r in ROLL_DAYS:
        t = pd.Timestamp(r)
        if t in s.index and s[t] > 1.8 * med:
            s[t] = np.nan
    return s


def load_ret(pair: str) -> pd.Series:
    d = pd.read_csv(ROOT / "data_forex" / pair / f"{pair}_D1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(ROOT / "data_forex" / pair / f"{pair}_D1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    m = ((d + a) / 2).dropna()
    return np.log(m).diff()


def periods(days: pd.DatetimeIndex) -> list[tuple[int, int]]:
    """(進場索引, 出場索引)：第 1 期從 START 之後第 1 個交易日起，每 21 個交易日一期，出場日 <= LAST_DAY。"""
    i0 = int(days.searchsorted(START))
    out = []
    while i0 + N < len(days) and days[i0 + N] <= LAST_DAY:
        out.append((i0, i0 + N))
        i0 += N
    return out


def payoff(iv: float, rv: float, c: float) -> float:
    k = iv - c
    return (k * k - rv * rv) / (2 * k)


def run(c_list=(0.0, 0.25, 0.5, 1.0)) -> dict:
    days = load_ret("EURUSD").dropna().index
    days = days[(days >= pd.Timestamp("2025-09-01")) & (days <= LAST_DAY)]
    pers = periods(days)
    res = {"periods": [(str(days[a].date()), str(days[b].date())) for a, b in pers], "ccy": {}}
    for ccy, pair in PAIRS.items():
        iv, ret = load_iv(ccy), load_ret(pair)
        rows = []
        for a, b in pers:
            j = a
            while j < b and not np.isfinite(iv.get(days[j], np.nan)):
                j += 1                                          # 當日 IV 缺值 → 順延進場（出場日不動）
            if j >= b:
                continue
            r = ret.reindex(days[j + 1: b + 1]).dropna().values
            if len(r) < 15:
                continue
            rv = float(np.sqrt(252 / len(r) * (r ** 2).sum()) * 100)
            row = {"entry": str(days[j].date()), "exit": str(days[b].date()), "iv": float(iv[days[j]]), "rv": rv, "n_days": len(r)}
            for c in c_list:
                row[f"pnl_c{c}"] = payoff(row["iv"], rv, c)
            rows.append(row)
        res["ccy"][ccy] = rows
    return res


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def summarize(res: dict) -> dict:
    out = {"per_ccy": {}, "pooled": {}}
    for ccy, rows in res["ccy"].items():
        d = pd.DataFrame(rows)
        out["per_ccy"][ccy] = {"n": len(d), "iv_mean": float(d.iv.mean()), "rv_mean": float(d.rv.mean()),
                               **{f"mean_c{c}": float(d[f'pnl_c{c}'].mean()) for c in (0.0, 0.25, 0.5, 1.0)},
                               "win_c0": float((d["pnl_c0.0"] > 0).mean()), "worst_c0": float(d["pnl_c0.0"].min())}
    # 日期群集：每個進場序號取七貨幣平均
    k = min(len(v) for v in res["ccy"].values())
    for c in (0.0, 0.25, 0.5, 1.0):
        m = np.array([[res["ccy"][ccy][i][f"pnl_c{c}"] for ccy in PAIRS] for i in range(k)]).mean(axis=1)
        sd = m.std(ddof=1) / np.sqrt(k)
        from math import isfinite
        tcrit = {8: 1.860, 9: 1.833, 10: 1.812, 11: 1.796}.get(k - 1, 1.833)       # 單尾 95% = 雙尾 90% 置信區間
        out["pooled"][f"c{c}"] = {"k": k, "mean": float(m.mean()), "t": tstat(m), "ci90": [float(m.mean() - tcrit * sd), float(m.mean() + tcrit * sd)],
                                  "by_period": [float(v) for v in m]}
    for name, sub in (("ex_NZD", [c for c in PAIRS if c != "NZD"]), ("EUR_GBP_AUD", ["EUR", "GBP", "AUD"])):     # 敏感度，只報告
        m = np.array([[res["ccy"][ccy][i]["pnl_c0.0"] for ccy in sub] for i in range(k)]).mean(axis=1)
        out["pooled"][f"c0.0_{name}"] = {"k": k, "mean": float(m.mean()), "t": tstat(m), "ci90": [float("nan")] * 2, "by_period": [float(v) for v in m]}
    return out


def check() -> None:
    days = load_ret("EURUSD").dropna().index
    days = days[(days >= pd.Timestamp("2025-09-01")) & (days <= LAST_DAY)]
    pers = periods(days)
    print(f"期數 {len(pers)}：{days[pers[0][0]].date()} → {days[pers[-1][1]].date()}")
    for ccy, pair in PAIRS.items():
        iv, ret = load_iv(ccy), load_ret(pair)
        v = iv[(iv.index >= START) & (iv.index <= LAST_DAY)]
        rv21 = ret.rolling(21).apply(lambda x: np.sqrt(252 * (x ** 2).mean()) * 100)
        j = pd.concat([v, rv21], axis=1, sort=True).dropna()
        print(f"  {ccy}: 有效 IV {v.notna().sum()}/{len(v)} 天，範圍 {v.min():.2f}–{v.max():.2f}，中位 {v.median():.2f}；與過去 21 日實現波動相關 {j.iloc[:,0].corr(j.iloc[:,1]):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.check:
        check()
        return
    res = run()
    s = summarize(res)
    for ccy, st in s["per_ccy"].items():
        print(f"{ccy}: n={st['n']} IV均 {st['iv_mean']:.2f} RV均 {st['rv_mean']:.2f} 毛(c0) {st['mean_c0.0']:+.3f} c0.25 {st['mean_c0.25']:+.3f} c0.5 {st['mean_c0.5']:+.3f} c1.0 {st['mean_c1.0']:+.3f} 勝率 {st['win_c0']:.2f} 最差 {st['worst_c0']:+.2f}")
    for c, st in s["pooled"].items():
        print(f"七貨幣日期群集 {c}: k={st['k']} 平均 {st['mean']:+.3f} t={st['t']:.2f} 90%CI [{st['ci90'][0]:+.3f}, {st['ci90'][1]:+.3f}] 逐期 {[round(v,2) for v in st['by_period']]}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{args.out}.json").write_text(json.dumps({"summary": s, "periods": res["periods"], "detail": res["ccy"]}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
