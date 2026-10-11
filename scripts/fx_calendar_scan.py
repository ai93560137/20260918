#!/usr/bin/env python3
"""日曆與時段規律掃描（S，美元籃子）。登記：forex_research/FX_DOLLAR_CALENDAR_BACKTEST.md 第一部分 S。

    python3 scripts/fx_calendar_scan.py --out forex_research/fx_dollar_calendar --check
    python3 scripts/fx_calendar_scan.py --out forex_research/fx_dollar_calendar
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
SIGN = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCHF": 1, "USDCAD": 1}   # 做多美元籃子
START, END = pd.Timestamp("2003-08-04"), pd.Timestamp("2026-08-31")
SESS = {"A亞洲[00,07)": (0, 7), "L倫敦[07,13)": (7, 13), "O重疊[13,17)": (13, 17), "N紐約[17,24)": (17, 24)}
COMM_BP = 0.4          # 兩邊佣金合計（基點）


def load_close(pair: str):
    """回傳（收市時間索引的中價收市, 相對點差序列 = (賣−買)/中價，按收市時間）。H1 時間標籤是該小時開始，收市時間 = 標籤 + 1 小時。"""
    d = ROOT / "data_forex" / pair
    b = pd.read_csv(d / f"{pair}_H1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(d / f"{pair}_H1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    j = pd.concat([b.rename("b"), a.rename("a")], axis=1, sort=True).dropna()
    j.index = j.index + pd.Timedelta(hours=1)
    mid = (j.b + j.a) / 2
    return mid, ((j.a - j.b) / mid).clip(lower=0)


def boundary_prices(mid: pd.Series, days: pd.DatetimeIndex) -> pd.DataFrame:
    """每個平日 00,07,13,17 與次日 00 的邊界價（asof：收市時間 ≤ 邊界的最後一根）。"""
    cols = {}
    for h in (0, 7, 13, 17):
        cols[h] = mid.reindex(mid.index.union(days + pd.Timedelta(hours=h)), method="ffill").reindex(days + pd.Timedelta(hours=h)).values
    cols[24] = mid.reindex(mid.index.union(days + pd.Timedelta(days=1)), method="ffill").reindex(days + pd.Timedelta(days=1)).values
    return pd.DataFrame(cols, index=days)


def tcell(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def build():
    days = pd.bdate_range(START, END)
    sess = {k: [] for k in SESS}
    daily = []
    spread = []
    for p in PAIRS:
        mid, rs = load_close(p)
        bp = boundary_prices(mid, days)
        lr = {}
        for k, (a, b) in SESS.items():
            lr[k] = SIGN[p] * np.log(bp[b] / bp[a])
        for k in SESS:
            sess[k].append(lr[k])
        daily.append(SIGN[p] * np.log(bp[24] / bp[0]))
        spread.append(rs.resample("D").median().reindex(days).ffill())
    S = pd.DataFrame({k: pd.concat(v, axis=1).mean(axis=1) for k, v in sess.items()})
    D = pd.concat(daily, axis=1).mean(axis=1)
    rel_spread = pd.concat(spread, axis=1).mean(axis=1)              # 七個對的平均相對點差（比例）
    return S, D, rel_spread


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    S, D, rel = build()
    cost = rel * 1.0 + COMM_BP * 1e-4                                  # 一次來回成本（比例）：點差 × 1 + 兩邊佣金
    if args.check:
        print(f"樣本 {S.index[0].date()} → {S.index[-1].date()}，{len(S)} 個平日；缺值：{S.isna().sum().to_dict()}；D 缺值 {int(D.isna().sum())}")
        chk = (S.sum(axis=1) - D).abs().max()
        print(f"四個時段報酬加總 vs 日報酬 最大差 {chk:.2e}（應 ≈ 0）")
        print(f"七個對平均相對點差：中位 {rel.median() * 1e4:.2f} 基點、2005 年 {rel.loc['2005'].median() * 1e4:.2f}、2015 年 {rel.loc['2015'].median() * 1e4:.2f}、2024 年 {rel.loc['2024'].median() * 1e4:.2f}；一次來回成本中位 {cost.median() * 1e4:.2f} 基點")
        print("各時段日內報酬標準差（基點）：", {k: round(float(S[k].std() * 1e4), 1) for k in S})
        rng = np.random.default_rng(3)
        ts = []
        for _ in range(300):
            x = pd.Series(rng.normal(0, 1, len(S)))
            ts.append([tcell(x.iloc[i::22]) for i in range(1)])
        print("迴歸測試：22 個隨機常態序列的 t 範圍（應在 ±3 內）：", np.round(np.percentile([tcell(pd.Series(rng.normal(0, 1, 1200))) for _ in range(22)], [0, 50, 100]), 2))
        return
    half = pd.Timestamp("2015-01-01")
    cells = {}
    daily_series = {}
    for k in SESS:
        daily_series[k] = S[k]
    for wd, nm in enumerate(["週一", "週二", "週三", "週四", "週五"]):
        daily_series[f"星期{nm}"] = D[D.index.weekday == wd]
    # 月底月初：每月最後 2 個與下月前 3 個交易日
    ym = pd.Series(D.index.to_period("M"), index=D.index)
    rank_from_start = D.groupby(ym).cumcount() + 1
    rank_from_end = D.groupby(ym).cumcount(ascending=False) + 1
    tom = (rank_from_end <= 2) | (rank_from_start <= 3)
    daily_series["月底月初(末2+初3)"] = D[tom]
    mret = D.groupby(D.index.to_period("M")).sum()
    for m in range(1, 13):
        sel = mret[mret.index.month == m]
        sel.index = sel.index.to_timestamp()
        daily_series[f"{m}月(月報酬)"] = sel
    out = []
    for name, x in daily_series.items():
        x = x.dropna()
        t, n = tcell(x), len(x)
        a, b = x[x.index < half], x[x.index >= half]
        sign = 1 if x.mean() > 0 else -1
        cst = cost.reindex(x.index).ffill() if not name.endswith("(月報酬)") else cost.reindex(x.index).ffill()
        net = sign * x - cst
        cells[name] = {"n": n, "mean_bp": round(float(x.mean() * 1e4), 3), "t": round(t, 2), "t_h1": round(tcell(a), 2), "t_h2": round(tcell(b), 2),
                       "mean_h1_bp": round(float(a.mean() * 1e4), 3), "mean_h2_bp": round(float(b.mean() * 1e4), 3),
                       "cost_bp": round(float(cst.mean() * 1e4), 2), "net_mean_bp": round(float(net.mean() * 1e4), 3), "net_t": round(tcell(net), 2)}
        c = cells[name]
        c["pass"] = bool(abs(t) >= 3.1 and np.sign(c["t_h1"]) == np.sign(c["t_h2"]) == np.sign(t) and abs(c["t_h1"]) >= 1.5 and abs(c["t_h2"]) >= 1.5 and c["net_mean_bp"] > 0 and c["net_t"] >= 2)
        out.append((name, c))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "S_stats.json").write_text(json.dumps(cells, ensure_ascii=False, indent=1), encoding="utf-8")
    print("格子                      n   均值bp    t    t前半  t後半  成本bp  淨均值bp 淨t  通過")
    for name, c in out:
        print(f"{name:22} {c['n']:6} {c['mean_bp']:8.3f} {c['t']:6.2f} {c['t_h1']:6.2f} {c['t_h2']:6.2f} {c['cost_bp']:6.2f} {c['net_mean_bp']:8.3f} {c['net_t']:6.2f}  {'✔' if c['pass'] else ''}")
    print(f"22 格中 |t| ≥ 3.1 的格數 {sum(abs(c['t']) >= 3.1 for _, c in out)}（若全無信息期望 0.05 個）；全過者 {sum(c['pass'] for _, c in out)}")


if __name__ == "__main__":
    main()
