#!/usr/bin/env python3
"""美元利差擇時（D）。登記：forex_research/FX_DOLLAR_CALENDAR_BACKTEST.md 第一部分 D。

    python3 scripts/fx_dollar_carry.py --out forex_research/fx_dollar_calendar --check     # 跑數前機制檢查
    python3 scripts/fx_dollar_carry.py --out forex_research/fx_dollar_calendar              # 正式跑（機構、零售各一次，含隨機對照）
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
from fx_basket_backtest import USD_PAIRS, daily_rates, load_prices, load_rates, portfolio_pnl, stats  # noqa: E402

CCY = {"EURUSD": "EUR", "GBPUSD": "GBP", "AUDUSD": "AUD", "NZDUSD": "NZD", "USDJPY": "JPY", "USDCHF": "CHF", "USDCAD": "CAD"}
COMM = 0.20e-4            # 每邊 0.20 基點


def signal_table(idx, rates_m, rates_d):
    ccys = list(CCY.values())
    month_ends = pd.Series(idx, index=idx).groupby(idx.to_period("M")).max().values
    s = {}
    for me in month_ends:
        r = rates_d.loc[me]
        if r[ccys + ["USD"]].isna().any():
            continue
        s[pd.Timestamp(me)] = int(np.sign(r[ccys].mean() - r["USD"]))
    return pd.Series(s), pd.DatetimeIndex(month_ends)


def weights_from_signal(sig: pd.Series, idx, month_ends, cols):
    w = pd.DataFrame(0.0, index=idx, columns=cols)
    me_list = list(month_ends)
    for i, me in enumerate(me_list):
        if pd.Timestamp(me) not in sig.index:
            continue
        nxt = me_list[i + 1] if i + 1 < len(me_list) else idx[-1]
        span = idx[(idx > me) & (idx <= nxt)]
        for p in cols:
            sign_pair = 1 if p.endswith("USD") else -1               # 做多外幣：XXXUSD 做多、USDXXX 做空
            w.loc[span, p] = sig[pd.Timestamp(me)] * sign_pair / len(cols)
    return w


def run(prices, w, rates_d, hc, split="2015-01-01"):
    fco = pd.DataFrame(COMM, index=w.index, columns=w.columns)
    daily, contrib = portfolio_pnl(prices, w, rates_d, 1.0, 0.2, hc, fill_cost_override=fco)
    daily = daily[(daily.index >= "2003-06-01") & (daily.index <= "2026-08-31")]
    st, monthly = stats(daily, contrib.loc[daily.index], split)
    return st, monthly, daily


def tstat(m):
    return float(m.mean() / m.std(ddof=1) * math.sqrt(len(m))) if len(m) > 2 and m.std(ddof=1) > 0 else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    prices = load_prices(ROOT, USD_PAIRS, "2002-04-01", "2026-08-31")
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in prices.values()])))
    ccys = sorted(set(CCY.values()) | {"USD"})
    rates_m = load_rates(ROOT / "data_forex_rates", ccys)
    rates_d = daily_rates(rates_m, idx, 1)
    sig, month_ends = signal_table(idx, rates_m, rates_d)
    sig = sig[sig.index >= "2003-05-01"]
    cols = list(USD_PAIRS)
    if args.check:
        chg = sig[sig != sig.shift(1)]
        runs = []
        for a, b in zip(chg.index, list(chg.index[1:]) + [sig.index[-1]]):
            runs.append((str(a.date()), int(chg.loc[a]), round((b - a).days / 30.4)))
        print("s 轉換（日期、新方向、持續月數）：", runs)
        print(f"月數 {len(sig)}，做多外幣月數 {(sig > 0).sum()}，做空 {(sig < 0).sum()}，轉換 {len(chg) - 1} 次")
        r = rates_d.loc[pd.Timestamp("2025-12-31")]
        print("2025-12 利率：", {c: round(float(r[c]), 2) for c in ccys}, "外幣平均", round(float(r[[c for c in ccys if c != 'USD']].mean()), 2))
        w = weights_from_signal(sig, idx, month_ends, cols)
        daily, _ = portfolio_pnl(prices, w, rates_d, 1.0, 0.2, 0.25, fill_cost_override=pd.DataFrame(COMM, index=w.index, columns=w.columns))
        ww = w[(w.index >= "2003-06-01")]
        yrs = (ww.index[-1] - ww.index[0]).days / 365.25
        print(f"平均總曝險 {ww.abs().sum(axis=1).mean():.2f}，每年換手 {(ww - ww.shift(1)).abs().sum(axis=1).sum() / yrs:.2f} 倍名義")
        return
    res = {}
    w = weights_from_signal(sig, idx, month_ends, cols)
    w_long = weights_from_signal(pd.Series(1, index=sig.index), idx, month_ends, cols)
    w_short = weights_from_signal(pd.Series(-1, index=sig.index), idx, month_ends, cols)
    args.out.mkdir(parents=True, exist_ok=True)
    for tag, hc in (("inst", 0.25), ("retail", 1.25)):
        st, mon, _ = run(prices, w, rates_d, hc)
        stl, monl, _ = run(prices, w_long, rates_d, hc)
        sts, mons, _ = run(prices, w_short, rates_d, hc)
        res[tag] = {"D1": st, "always_long_foreign": {k: stl[k] for k in ("t", "ann_return_pct", "sharpe", "max_dd_pct", "t_before_split", "t_from_split")},
                    "always_short_foreign": {k: sts[k] for k in ("t", "ann_return_pct", "sharpe", "max_dd_pct")}}
        excess = mon - monl
        res[tag]["D1_minus_always_long_t"] = round(tstat(excess), 2)
        mon.to_csv(args.out / f"D1_{tag}_monthly.csv", header=["ret"])
        print(f"== D1 {tag}（加價 {hc}%）：t = {st['t']}、年化 {st['ann_return_pct']}%、波動 {st['ann_vol_pct']}%、夏普 {st['sharpe']}、最大回撤 {st['max_dd_pct']}%、正年 {st['pos_years']}、"
              f"2003–2014 t {st['t_before_split']}／2015–2026 t {st['t_from_split']}")
        print(f"   診斷：永遠做多外幣 t {stl['t']}（年化 {stl['ann_return_pct']}%、回撤 {stl['max_dd_pct']}%）、永遠做空 t {sts['t']}；D1 相對永遠做多的超額 t {res[tag]['D1_minus_always_long_t']}")
    # 隨機對照：循環平移訊號（機構口徑）
    rng = np.random.default_rng(20261011)
    ts = []
    sv = sig.values
    for _ in range(1000):
        k = int(rng.integers(12, len(sv) - 12))
        shifted = pd.Series(np.roll(sv, k), index=sig.index)
        wr = weights_from_signal(shifted, idx, month_ends, cols)
        _, m, _ = run(prices, wr, rates_d, 0.25)
        ts.append(tstat(m))
    ts = np.array(ts)
    pct = {q: round(float(np.percentile(ts, q)), 2) for q in (2.5, 50, 97.5)}
    res["random_shift_t"] = {"percentiles": pct, "D1_inst_t": res["inst"]["D1"]["t"], "D1_percentile": round(float((ts < res["inst"]["D1"]["t"]).mean() * 100), 1)}
    print(f"== 隨機循環平移 1000 次（機構）：t 分位 {pct}；D1 落在第 {res['random_shift_t']['D1_percentile']} 百分位")
    (args.out / "D_stats.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
