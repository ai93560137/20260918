#!/usr/bin/env python3
"""X1 探索性日線規則大網格（curve fitting）。登記：forex_research/FX_EXPLORATORY_SCAN.md。不給判決，只出線索。

    python3 scripts/fx_explore_daily.py --out forex_research/fx_exploratory [--null 30]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fx_basket_backtest import daily_rates, load_rates, real_start  # noqa: E402

PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
         "EURGBP", "EURCHF", "EURAUD", "EURCAD", "GBPCHF", "GBPAUD", "AUDNZD", "AUDCAD", "USDSGD", "XAUUSD", "XAGUSD"]
COMM = 2e-5            # 每邊 0.20 基點
WARM = 250
SPLIT = pd.Timestamp("2015-01-01")


def load(pair: str):
    d = ROOT / "data_forex" / pair
    b = pd.read_csv(d / f"{pair}_D1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(d / f"{pair}_D1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    j = pd.concat([b.rename("b"), a.rename("a")], axis=1, sort=True).dropna()
    j = j[(j.index.weekday < 5) & (j.index >= max(real_start(pair), pd.Timestamp("2003-05-01"))) & (j.index <= "2026-08-31")]
    mid = (j.b + j.a) / 2
    rel = ((j.a - j.b) / mid).clip(lower=0).rolling(20, min_periods=1).median()
    return mid, rel


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def rules(c: pd.Series):
    """產生 (家族, 參數字串, 持倉 Series)。"""
    lc = np.log(c)
    for L in (5, 10, 20, 40, 60, 90, 120, 180, 250):
        yield "TSMOM", f"L{L}", np.sign(lc - lc.shift(L))
    sma = {n: c.rolling(n).mean() for n in (5, 10, 20, 50, 100, 200)}
    for f in (5, 10, 20, 50):
        for s in (20, 50, 100, 200):
            if f < s:
                yield "MA", f"{f}/{s}", np.sign(sma[f] - sma[s])
    for N in (10, 20, 40, 55, 100, 200):
        hh, ll = c.shift(1).rolling(N).max(), c.shift(1).rolling(N).min()
        sig = pd.Series(np.where(c > hh, 1.0, np.where(c < ll, -1.0, np.nan)), index=c.index)
        yield "Donchian", f"N{N}", sig.ffill().fillna(0)
    for L in (5, 10, 20, 50):
        m, sd = c.rolling(L).mean(), c.rolling(L).std()
        z = (c - m) / sd.replace(0, np.nan)
        for k in (1.0, 1.5, 2.0):
            vl = pd.Series(np.where(z < -k, 1.0, np.where(z >= 0, 0.0, np.nan)), index=c.index).ffill().fillna(0)
            vs = pd.Series(np.where(z > k, -1.0, np.where(z <= 0, 0.0, np.nan)), index=c.index).ffill().fillna(0)
            yield "MeanRev", f"L{L}k{k}", vl + vs
    r = rsi(c)
    for lo, hi in ((20, 80), (30, 70)):
        vl = pd.Series(np.where(r < lo, 1.0, np.where(r > 50, 0.0, np.nan)), index=c.index).ffill().fillna(0)
        vs = pd.Series(np.where(r > hi, -1.0, np.where(r < 50, 0.0, np.nan)), index=c.index).ffill().fillna(0)
        yield "RSI逆勢", f"{lo}/{hi}", vl + vs
    for hi in (60, 70):
        yield "RSI順勢", f"{hi}/{100 - hi}", pd.Series(np.where(r > hi, 1.0, np.where(r < 100 - hi, -1.0, 0.0)), index=c.index)


def evaluate(pos: pd.Series, ret: pd.Series, cost: pd.Series, extra: pd.Series | None = None):
    p1, p2 = pos.shift(1), pos.shift(2)
    net = p1 * ret - (p1 - p2).abs() * cost.shift(1)
    if extra is not None:
        net = net + extra
    net = net.iloc[WARM:].dropna()
    if len(net) < 500 or net.std() == 0:
        return None
    sh = net.mean() / net.std() * math.sqrt(252)

    def shp(x):
        return float(x.mean() / x.std() * math.sqrt(252)) if len(x) > 100 and x.std() > 0 else float("nan")
    h1, h2 = net[net.index < SPLIT], net[net.index >= SPLIT]
    cum = net.cumsum()
    turns = float((p1 - p2).abs().iloc[WARM:].sum() / (len(net) / 252))
    return {"sharpe": float(sh), "t": float(sh * math.sqrt(len(net) / 252)), "ann_ret_pct": float(net.mean() * 252 * 100), "sharpe_h1": shp(h1), "sharpe_h2": shp(h2),
            "max_dd_pct": float((cum.cummax() - cum).max() * 100), "turnover_per_yr": turns, "years": len(net) / 252}


def grid(universe):
    rows = []
    for pair, (c, rel) in universe.items():
        ret = c.pct_change()
        cost = 0.5 * rel + COMM
        for fam, par, pos in rules(c):
            ev = evaluate(pos, ret, cost)
            if ev:
                rows.append({"pair": pair, "family": fam, "param": par, **ev})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--null", type=int, default=30)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    uni = {p: load(p) for p in PAIRS}
    print("標的起點：", {p: str(c.index[0].date()) for p, (c, _) in uni.items()})
    R = grid(uni)
    R.to_csv(args.out / "X1_all.csv", index=False)
    print(f"網格 {len(R)} 條；夏普 > 0 的 {int((R.sharpe > 0).sum())} 條；最高 {R.sharpe.max():.2f}、中位 {R.sharpe.median():.2f}、最低 {R.sharpe.min():.2f}")
    top = R.sort_values("sharpe", ascending=False).head(40)
    fam_avg = R.groupby(["pair", "family"]).sharpe.mean().rename("family_avg_sharpe")
    top = top.join(fam_avg, on=["pair", "family"])
    print("== 前 40 名（扣成本、不含 swap）")
    print(top[["pair", "family", "param", "sharpe", "t", "ann_ret_pct", "sharpe_h1", "sharpe_h2", "max_dd_pct", "turnover_per_yr", "family_avg_sharpe"]].round(2).to_string(index=False))
    print("== 每個規則家族的最好一條")
    print(R.loc[R.groupby("family").sharpe.idxmax()][["family", "pair", "param", "sharpe", "sharpe_h1", "sharpe_h2"]].round(2).to_string(index=False))
    print("== 每個標的的最好一條")
    print(R.loc[R.groupby("pair").sharpe.idxmax()][["pair", "family", "param", "sharpe", "sharpe_h1", "sharpe_h2"]].round(2).sort_values("sharpe", ascending=False).to_string(index=False))
    print("== 家族平均夏普（全標的全參數）：", R.groupby("family").sharpe.mean().round(3).to_dict())
    # 半樣本前向表
    wf = {}
    for a, b, nm in (("sharpe_h1", "sharpe_h2", "2003-2014選→2015-2026看"), ("sharpe_h2", "sharpe_h1", "2015-2026選→2003-2014看")):
        sel = R.dropna(subset=[a, b]).sort_values(a, ascending=False).head(40)
        wf[nm] = {"選中平均夏普": round(float(sel[a].mean()), 2), "另一半平均夏普": round(float(sel[b].mean()), 2), "另一半夏普>0比例": round(float((sel[b] > 0).mean()), 2),
                  "全網格另一半平均夏普": round(float(R[b].mean()), 2)}
    print("== 半樣本前向表：", json.dumps(wf, ensure_ascii=False))
    # 純雜訊對照
    rng = np.random.default_rng(20261011)
    nulls = []
    for k in range(args.null):
        sim = {}
        for p, (c, rel) in uni.items():
            r = c.pct_change().fillna(0.0).values
            sg = rng.choice([-1.0, 1.0], size=len(r))
            sim[p] = (pd.Series(c.iloc[0] * np.cumprod(1 + r * sg), index=c.index), rel)
        Rn = grid(sim)
        s = Rn.sharpe.sort_values(ascending=False)
        nulls.append({"max": float(s.iloc[0]), "p40": float(s.iloc[39]), "mean": float(s.mean()), "max_t": float(Rn.t.max())})
        print(f"  雜訊宇宙 {k + 1}/{args.null}：全網格最高夏普 {s.iloc[0]:.2f}、第 40 名 {s.iloc[39]:.2f}")
    N = pd.DataFrame(nulls)
    summ = {"actual_max": round(float(R.sharpe.max()), 2), "actual_p40": round(float(R.sharpe.sort_values(ascending=False).iloc[39]), 2), "actual_max_t": round(float(R.t.max()), 2),
            "null_max_median": round(float(N["max"].median()), 2), "null_max_p95": round(float(N["max"].quantile(0.95)), 2), "null_max_max": round(float(N["max"].max()), 2),
            "null_p40_median": round(float(N.p40.median()), 2), "null_maxt_median": round(float(N.max_t.median()), 2), "null_maxt_p95": round(float(N.max_t.quantile(0.95)), 2),
            "actual_above_null_p95": bool(R.sharpe.max() > N["max"].quantile(0.95))}
    print("== 雜訊對照：", json.dumps(summ, ensure_ascii=False))
    (args.out / "null_X1.json").write_text(json.dumps({"summary": summ, "runs": nulls, "walkforward": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    top.to_csv(args.out / "X1_top40.csv", index=False)

    # 前 30 名含 swap（外匯對，加價 1.25%）
    rates_m = load_rates(ROOT / "data_forex_rates", ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"])
    out = []
    for _, row in R.sort_values("sharpe", ascending=False).head(30).iterrows():
        p = row["pair"]
        base, quote = p[:3], p[3:]
        if base not in rates_m.columns or quote not in rates_m.columns:
            out.append({**row[["pair", "family", "param", "sharpe"]].to_dict(), "sharpe_with_swap": None, "note": "無 swap 模型"})
            continue
        c, rel = uni[p]
        rd = daily_rates(rates_m, c.index, 1)
        diff = (rd[base] - rd[quote]).ffill().fillna(0.0) / 100.0
        for fam, par, pos in rules(c):
            if fam == row["family"] and par == row["param"]:
                p1 = pos.shift(1)
                extra = p1 * diff / 365.0 - p1.abs() * 0.0125 / 365.0
                ev = evaluate(pos, c.pct_change(), 0.5 * rel + COMM, extra)
                out.append({**row[["pair", "family", "param", "sharpe"]].to_dict(), "sharpe_with_swap": round(ev["sharpe"], 2), "t_with_swap": round(ev["t"], 2), "note": ""})
    print("== 前 30 名含 swap（加價 1.25%）：")
    print(pd.DataFrame(out).round(2).to_string(index=False))
    pd.DataFrame(out).to_csv(args.out / "X1_top30_swap.csv", index=False)


if __name__ == "__main__":
    main()
