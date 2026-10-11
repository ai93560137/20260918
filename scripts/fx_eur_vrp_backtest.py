#!/usr/bin/env python3
"""歐元波動溢價回測（賣出 21 交易日 EUR/USD 方差，EVZ 為行使價近似）。登記：forex_research/FX_EUR_VRP_BACKTEST.md。

    python3 scripts/fx_eur_vrp_backtest.py --beacon <含 vix_daily 等 CSV 的資料夾> --check        # 跑數前機制檢查（不看績效）
    python3 scripts/fx_eur_vrp_backtest.py --beacon <資料夾> --out forex_research/fx_eur_vrp      # 正式跑（V1、V0 與敏感度各一次）

損益（賣方，每 1 vega 名義，單位波動點）= (K² − RV²) / (2K)，K = EVZ_t − c，RV = √(252/n × Σ r²) × 100，r = 進場日之後 n 個交易日的日對數報酬。
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EVZ_END = pd.Timestamp("2025-03-11")


def load_evz() -> pd.Series:
    s = pd.read_csv(ROOT / "data_forex_rates" / "info" / "EVZCLS.csv", parse_dates=["Date"]).set_index("Date")["Value"].astype(float)
    return s[s > 0].sort_index()


def load_eurusd() -> pd.Series:
    d = ROOT / "data_forex" / "EURUSD"
    bid = pd.read_csv(d / "EURUSD_D1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    ask = pd.read_csv(d / "EURUSD_D1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    mid = ((bid + ask.reindex(bid.index)) / 2).dropna()
    return mid[mid.index.weekday < 5].sort_index()


def intraday_sumsq(freq: str = "5min") -> pd.Series:
    """HistData M1 → freq 收市對數報酬的平方和，按 UTC 日加總（敏感度用；週末缺口報酬極小）。"""
    parts = []
    for f in sorted((ROOT / "data_forex" / "EURUSD").glob("EURUSD_M1_20??.csv.gz")):
        s = pd.read_csv(f, parse_dates=["Time"], usecols=["Time", "Close"]).set_index("Time")["Close"]
        parts.append(s.resample(freq).last().dropna())
    p = pd.concat(parts)
    p = p[~p.index.duplicated()].sort_index()
    r = np.log(p).diff().dropna()
    return (r ** 2).groupby(r.index.normalize()).sum()


def load_lights(beacon: Path) -> pd.DataFrame:
    def rd(name):
        return pd.read_csv(beacon / name, parse_dates=["Date"]).set_index("Date")["Close"].astype(float).sort_index()
    vix, v9, v3 = rd("vix_daily.csv"), rd("vix9d_daily.csv"), rd("vix3m_daily.csv")
    idx = vix.index
    lights = pd.DataFrame(index=idx)
    lights["red"] = ((v9.reindex(idx) - vix) > 0).fillna(False)            # 2011-01-04 前無 VIX9D → 非紅（登記時已知）
    lights["deep"] = ((vix - v3.reindex(idx)) > 0).fillna(False)
    y = pd.Series(False, index=idx)
    for n in ("vvix_daily.csv", "move_daily.csv", "axvi_daily.csv"):
        s = rd(n)
        q = s.rolling(252, min_periods=126).quantile(0.9)
        y = y | (s > q).reindex(idx).fillna(False)
    lights["yellow"] = y
    return lights


def payoff(K: float, ret_window: np.ndarray, n: int) -> tuple[float, float]:
    rv = math.sqrt(252.0 / n * float((ret_window ** 2).sum())) * 100.0
    return (K * K - rv * rv) / (2.0 * K), rv


def run(evz, px, lights, c, n, use_beacon, sumsq=None, last_end=EVZ_END):
    """回傳逐期 DataFrame：slot_start, entry, exit, status(traded/skipped_deep/skipped_red/skipped_end), K, rv, pnl。"""
    T = px.index
    r = np.log(px).diff().dropna()
    pos = {d: i for i, d in enumerate(r.index)}
    lt = lights.reindex(T).fillna(False) if lights is not None else None
    rows = []
    # 第一個候選日：EVZ 起點之後第一個有 EVZ 與 EURUSD 的交易日
    start = [d for d in T if d >= evz.index[0] and d in evz.index][0]
    i = list(T).index(start)
    while i + n < len(T):
        c_day = T[i]
        status, entry = "traded", None
        if c_day > last_end or T[min(i + n, len(T) - 1)] > last_end:        # 本期（含空手期）會跨過 EVZ 最後一天 → 不計
            break
        if use_beacon:
            if bool(lt.loc[c_day, "deep"]):
                status = "skipped_deep"
            elif bool(lt.loc[c_day, "red"]):
                status = "skipped_red"
                for k in range(1, 11):
                    if i + k + n >= len(T):
                        break
                    d = T[i + k]
                    if d in evz.index and not bool(lt.loc[d, "red"]) and not bool(lt.loc[d, "deep"]):
                        entry, status = i + k, "traded"
                        break
            else:
                entry = i
        else:
            entry = i
        if status == "traded" and (entry is None or T[entry] not in evz.index):
            # 候選日沒有 EVZ（美國假日）：順延到下一個有 EVZ 的日子（最多 5 日），否則跳過
            j = entry if entry is not None else i
            for k in range(0, 6):
                if j + k + n < len(T) and T[j + k] in evz.index:
                    entry = j + k
                    break
            else:
                status, entry = "skipped_noevz", None
        if status == "traded":
            d = T[entry]
            if T[entry + n] > last_end:                                       # 進場後 n 日會超過 EVZ 最後一天 → 本期與之後都不計
                break
            win_dates = r.index[pos[T[entry + 1]]: pos[T[entry + n]] + 1]
            if sumsq is not None:
                ss = sumsq.reindex(win_dates).fillna(0.0).sum()
                rv = math.sqrt(252.0 / n * ss) * 100.0
                K = float(evz.loc[d]) - c
                pnl = (K * K - rv * rv) / (2 * K)
            else:
                K = float(evz.loc[d]) - c
                pnl, rv = payoff(K, r.loc[win_dates].values, n)
            rows.append({"slot_start": c_day, "entry": d, "exit": T[entry + n], "status": "traded", "K": K, "rv": rv, "pnl": pnl, "delay": entry - i})
            i = entry + n
        else:
            rows.append({"slot_start": c_day, "entry": pd.NaT, "exit": T[min(i + n, len(T) - 1)], "status": status, "K": np.nan, "rv": np.nan, "pnl": 0.0})
            i = i + n
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    p = df["pnl"].values
    k = len(p)
    if k < 3:
        return {"periods": k}
    t = float(p.mean() / p.std(ddof=1) * math.sqrt(k)) if p.std(ddof=1) > 0 else float("nan")
    tr_df = df[df.status == "traded"]
    tr = tr_df["pnl"].values
    t_tr = float(tr.mean() / tr.std(ddof=1) * math.sqrt(len(tr))) if len(tr) > 2 else float("nan")
    cum = np.cumsum(p)
    dd = float((np.maximum.accumulate(cum) - cum).max())
    half = k // 2
    yr = df.groupby(df["slot_start"].dt.year)["pnl"].sum()
    mean = float(p.mean())
    worst = float(p.min())
    return {"periods": k, "traded": int(len(tr)), "skipped_deep": int((df.status == "skipped_deep").sum()),
            "skipped_red": int((df.status == "skipped_red").sum()), "delayed": int((tr_df["delay"] > 0).sum()) if "delay" in df else 0, "mean": round(mean, 3), "t": round(t, 2), "t_traded_only": round(t_tr, 2),
            "total_vega_periods": round(float(p.sum()), 1), "win_rate_traded": round(float((tr > 0).mean()), 3) if len(tr) else None,
            "worst_period": round(worst, 2), "worst_over_mean": round(worst / mean, 1) if mean > 0 else None,
            "max_dd": round(dd, 1), "first_half_mean": round(float(p[:half].mean()), 3), "second_half_mean": round(float(p[half:].mean()), 3),
            "pos_years": f"{int((yr > 0).sum())}/{len(yr)}", "best_year_share": round(float(yr.max() / p.sum()), 2) if p.sum() > 0 else None,
            "yearly": {int(a): round(float(b), 1) for a, b in yr.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--beacon", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="跑數前機制檢查（不看績效）")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    evz, px = load_evz(), load_eurusd()
    lights = load_lights(args.beacon)
    if args.check:
        print(f"EVZ {evz.index[0].date()} → {evz.index[-1].date()}，{len(evz)} 筆，範圍 {evz.min():.2f}–{evz.max():.2f}，中位 {evz.median():.2f}")
        T = px.index[(px.index >= evz.index[0]) & (px.index <= evz.index[-1])]
        miss = [d for d in T if d not in evz.index]
        print(f"EURUSD 交易日 {len(T)}，其中 EVZ 缺 {len(miss)} 日（{len(miss) / len(T) * 100:.1f}%）；EVZ 有而 EURUSD 無 {len([d for d in evz.index if d not in px.index])} 日")
        r = np.log(px).diff()
        trail = r.rolling(21).std() * math.sqrt(252) * 100
        j = pd.concat([evz.rename("evz"), trail.rename("rv")], axis=1, sort=True).dropna()
        print(f"EVZ 與過去 21 日實現波動：相關 {j.evz.corr(j.rv):.2f}（{len(j)} 日）")
        lt = lights.loc[evz.index[0]:evz.index[-1]]
        by = pd.DataFrame({"紅": lt.red.groupby(lt.index.year).sum(), "深紅": lt.deep.groupby(lt.index.year).sum(), "黃": lt.yellow.groupby(lt.index.year).sum(),
                           "交易日": lt.red.groupby(lt.index.year).size()})
        print("烽燧燈天數（年）：\n" + by.to_string())
        rng = np.random.default_rng(1)
        sig = 8.0
        ps = []
        for _ in range(4000):
            rr = rng.normal(0, sig / 100 / math.sqrt(252), 21)
            ps.append(payoff(sig - 0.5, rr, 21)[0])
        print(f"迴歸測試：模擬 σ={sig}% 常態報酬、K=σ−0.5，4000 期平均損益 {np.mean(ps):.3f}（預期約 −0.5 附近，t {np.mean(ps) / np.std(ps, ddof=1) * math.sqrt(len(ps)):.1f}）")
        for ub in (True, False):
            d = run(evz, px, lights, 0.5, 21, ub)
            vc = d.status.value_counts().to_dict()
            dl = int((d.get("delay", pd.Series(dtype=float)) > 0).sum())
            print(f"{'V1 烽燧' if ub else 'V0 無響應'}：期數 {len(d)}，狀態 {vc}，其中延後進場 {dl} 期，首期進場 {d.entry.dropna().iloc[0].date()}，末期出場 {d.exit.iloc[-1].date()}")
        return
    res = {}
    out = args.out
    if out:
        out.mkdir(parents=True, exist_ok=True)

    def do(name, **kw):
        d = run(evz, px, lights, kw.get("c", 0.5), kw.get("n", 21), kw.get("beacon", True), sumsq=kw.get("sumsq"))
        s = summarize(d)
        res[name] = s
        if out:
            d.to_csv(out / f"{name}_periods.csv", index=False)
        print(f"== {name}: 期數 {s['periods']}（進場 {s.get('traded')}〔延後 {s.get('delayed')}〕、深紅跳過 {s.get('skipped_deep')}、紅跳過 {s.get('skipped_red')}）、平均 {s['mean']}、t = {s['t']}（只計有進場 {s['t_traded_only']}）、"
              f"勝率 {s['win_rate_traded']}、最差期 {s['worst_period']}（= {s['worst_over_mean']} 倍平均）、最大回撤 {s['max_dd']}、前後半 {s['first_half_mean']}／{s['second_half_mean']}、正年 {s['pos_years']}、最好年佔 {s['best_year_share']}")
        return d
    do("V1", beacon=True)
    do("V0", beacon=False)
    for c in (0.0, 0.25, 1.0):
        do(f"V1_c{c}", beacon=True, c=c)
        do(f"V0_c{c}", beacon=False, c=c)
    for n in (10, 30):
        do(f"V1_n{n}", beacon=True, n=n)
        do(f"V0_n{n}", beacon=False, n=n)
    ss = intraday_sumsq()
    do("V1_rv5min", beacon=True, sumsq=ss)
    do("V0_rv5min", beacon=False, sumsq=ss)
    if out:
        (out / "stats.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        for k in ("V1", "V0"):
            print(k, "按年（vega-期）：", "、".join(f"{a} {b:+.1f}" for a, b in res[k]["yearly"].items()))


if __name__ == "__main__":
    main()
