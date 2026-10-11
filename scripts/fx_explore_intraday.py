#!/usr/bin/env python3
"""X2 探索性日內時窗大網格（curve fitting）。登記：forex_research/FX_EXPLORATORY_SCAN.md。不給判決，只出線索。

    python3 scripts/fx_explore_intraday.py --out forex_research/fx_exploratory [--null 30]
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
START, END = pd.Timestamp("2003-08-04"), pd.Timestamp("2026-08-31")
SPLIT = pd.Timestamp("2015-01-01")
COMM_BP = 0.4e-4
WINDOWS = [(a, b) for a in range(24) for b in range(a + 1, 25)]


def load_pair(pair: str):
    d = ROOT / "data_forex" / pair
    b = pd.read_csv(d / f"{pair}_H1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(d / f"{pair}_H1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    j = pd.concat([b.rename("b"), a.rename("a")], axis=1, sort=True).dropna()
    j.index = j.index + pd.Timedelta(hours=1)                      # 收市時間
    mid = (j.b + j.a) / 2
    rel = ((j.a - j.b) / mid).clip(lower=0)
    days = pd.bdate_range(START, END)
    times = (days.values[:, None] + (np.arange(25) * np.timedelta64(1, "h"))[None, :])
    ix = np.searchsorted(mid.index.values, times, side="right") - 1
    ix = np.clip(ix, 0, len(mid) - 1)
    L = np.log(mid.values[ix])                                     # 日 × 25 邊界
    # 相對點差：按（年, 小時）中位，對應到邊界小時 h（0..24；24 用次日 0 點的值 = 當日 h=0 的下一格，簡化取 h%24）
    r = pd.DataFrame({"rel": rel.values, "year": rel.index.year, "hour": (rel.index - pd.Timedelta(hours=1)).hour})
    med = r.groupby(["year", "hour"]).rel.median()
    S = np.zeros((len(days), 25))
    for h in range(25):
        hh = h % 24
        S[:, h] = [med.get((y, hh), np.nan) for y in days.year]
    S = pd.DataFrame(S).ffill(axis=1).bfill(axis=1).fillna(1e-4).values
    return days, L, S


def stats(net: np.ndarray, days: pd.DatetimeIndex):
    n = len(net)
    if n < 500 or net.std() == 0:
        return None
    t = net.mean() / net.std(ddof=1) * math.sqrt(n)
    h1, h2 = net[days < SPLIT], net[days >= SPLIT]
    th = lambda x: float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 100 and x.std() > 0 else float("nan")
    return {"t": float(t), "sharpe": float(net.mean() / net.std() * math.sqrt(252)), "mean_bp": float(net.mean() * 1e4), "t_h1": th(h1), "t_h2": th(h2)}


def scan(data, flip=None):
    rows = []
    for pair, (days, L, S) in data.items():
        Lx = L if flip is None else (L - L[:, [0]]) * flip[pair][:, None] + L[:, [0]]
        for a, b in WINDOWS:
            ret = Lx[:, b] - Lx[:, a]
            sgn = 1.0 if ret.mean() >= 0 else -1.0
            cost = (S[:, a] + S[:, b]) / 2 + COMM_BP
            net = sgn * ret - cost
            st = stats(net, days)
            if st:
                gross = sgn * ret
                rows.append({"pair": pair, "start_h": a, "end_h": b, "dir": "多" if sgn > 0 else "空", "gross_bp": float(gross.mean() * 1e4), "cost_bp": float(cost.mean() * 1e4), **st})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--null", type=int, default=30)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = {p: load_pair(p) for p in PAIRS}
    print("日數", {p: len(v[0]) for p, v in data.items()})
    R = scan(data)
    R.to_csv(args.out / "X2_all.csv", index=False)
    print(f"網格 {len(R)} 條；淨 t > 0 的 {int((R.t > 0).sum())} 條；最高淨 t {R.t.max():.2f}、中位 {R.t.median():.2f}")
    top = R.sort_values("t", ascending=False).head(30)
    print("== 前 30 名（扣成本；方向為全樣本均值符號）")
    print(top.round(2).to_string(index=False))
    print("== 毛均值（基點／日）最大前 10（未扣成本）")
    print(R.sort_values("gross_bp", ascending=False).head(10).round(2).to_string(index=False))
    print("== 每個對的最好一條")
    print(R.loc[R.groupby("pair").t.idxmax()].round(2).to_string(index=False))
    wf = {}
    for a, b, nm in (("t_h1", "t_h2", "2003-2014選→2015-2026看"), ("t_h2", "t_h1", "2015-2026選→2003-2014看")):
        sel = R.dropna(subset=[a, b]).sort_values(a, ascending=False).head(40)
        wf[nm] = {"選中平均t": round(float(sel[a].mean()), 2), "另一半平均t": round(float(sel[b].mean()), 2), "另一半t>0比例": round(float((sel[b] > 0).mean()), 2), "全網格另一半平均t": round(float(R[b].mean()), 2)}
    print("== 半樣本前向表：", json.dumps(wf, ensure_ascii=False))
    rng = np.random.default_rng(20261011)
    nulls = []
    for k in range(args.null):
        flip = {p: rng.choice([-1.0, 1.0], size=len(data[p][0])) for p in PAIRS}
        Rn = scan(data, flip)
        s = Rn.t.sort_values(ascending=False)
        nulls.append({"max_t": float(s.iloc[0]), "p30": float(s.iloc[29]), "n_t_pos": int((Rn.t > 0).sum())})
        print(f"  雜訊 {k + 1}/{args.null}：最高淨 t {s.iloc[0]:.2f}、第 30 名 {s.iloc[29]:.2f}")
    N = pd.DataFrame(nulls)
    summ = {"actual_max_t": round(float(R.t.max()), 2), "actual_p30_t": round(float(R.t.sort_values(ascending=False).iloc[29]), 2),
            "null_max_t_median": round(float(N.max_t.median()), 2), "null_max_t_p95": round(float(N.max_t.quantile(0.95)), 2), "null_max_t_max": round(float(N.max_t.max()), 2),
            "null_p30_median": round(float(N.p30.median()), 2), "actual_above_null_p95": bool(R.t.max() > N.max_t.quantile(0.95))}
    print("== 雜訊對照：", json.dumps(summ, ensure_ascii=False))
    (args.out / "null_X2.json").write_text(json.dumps({"summary": summ, "runs": nulls, "walkforward": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    top.to_csv(args.out / "X2_top30.csv", index=False)


if __name__ == "__main__":
    main()
