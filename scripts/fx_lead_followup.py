#!/usr/bin/env python3
"""探索性掃描線索 L1／L2 跟進（跟進 a 描述、b 跨來源複核、c 樣本外）。登記：forex_research/FX_EXPLORATORY_SCAN.md 第三部分。

    python3 scripts/fx_lead_followup.py --out forex_research/fx_exploratory
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LEADS = {"L1": (9, 12, -1.0), "L2": (1, 6, 1.0)}            # (起點小時, 終點小時, 預測方向 +1 多 −1 空)
OOS = (pd.Timestamp("2000-05-30"), pd.Timestamp("2003-07-31"))
MAIN = (pd.Timestamp("2003-08-04"), pd.Timestamp("2026-08-31"))


def window_prices(close_times: np.ndarray, prices: np.ndarray, days: pd.DatetimeIndex, hours) -> dict:
    out = {}
    for h in hours:
        t = (days + pd.Timedelta(hours=h)).values
        ix = np.clip(np.searchsorted(close_times, t, side="right") - 1, 0, len(prices) - 1)
        out[h] = prices[ix]
    return out


def dukascopy_series(side: str):
    d = ROOT / "data_forex" / "EURUSD"
    b = pd.read_csv(d / "EURUSD_H1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(d / "EURUSD_H1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    j = pd.concat([b.rename("b"), a.rename("a")], axis=1, sort=True).dropna()
    s = {"bid": j.b, "ask": j.a, "mid": (j.a + j.b) / 2}[side]
    s.index = s.index + pd.Timedelta(hours=1)
    return s


def leads_from_series(s: pd.Series, days: pd.DatetimeIndex) -> pd.DataFrame:
    P = window_prices(s.index.values, s.values, days, (1, 6, 9, 12))
    out = {}
    for k, (a, b, sg) in LEADS.items():
        out[k] = sg * np.log(P[b] / P[a])
    return pd.DataFrame(out, index=days)


def histdata_leads(days: pd.DatetimeIndex) -> pd.DataFrame:
    """逐年讀 HistData M1（UTC），只取四個邊界小時的價；年與年之間帶上一年最後一筆。"""
    rows = {k: [] for k in (1, 6, 9, 12)}
    carry = None
    for y in range(2000, 2027):
        f = ROOT / "data_forex" / "EURUSD" / f"EURUSD_M1_{y}.csv.gz"
        if not f.exists():
            continue
        s = pd.read_csv(f, parse_dates=["Time"], usecols=["Time", "Close"]).set_index("Time")["Close"]
        s.index = s.index + pd.Timedelta(minutes=1)
        if carry is not None:
            s = pd.concat([carry, s])
        carry = s.iloc[[-1]]
        dy = days[days.year == y]
        if len(dy):
            P = window_prices(s.index.values, s.values, dy, (1, 6, 9, 12))
            for h in rows:
                rows[h].append(pd.Series(P[h], index=dy))
    P = {h: pd.concat(v) for h, v in rows.items()}
    out = {k: sg * np.log(P[b] / P[a]) for k, (a, b, sg) in LEADS.items()}
    return pd.DataFrame(out)


def tstat(x) -> float:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def summ(x: pd.Series) -> dict:
    lo, hi = x.quantile(0.01), x.quantile(0.99)
    return {"n": int(x.notna().sum()), "mean_bp": round(float(x.mean() * 1e4), 3), "median_bp": round(float(x.median() * 1e4), 3), "t": round(tstat(x), 2),
            "win": round(float((x > 0).mean()), 3), "t_winsor1": round(tstat(x.clip(lo, hi)), 2)}


def european_summer(d: pd.Timestamp) -> bool:
    def last_sun(y, m):
        x = pd.Timestamp(y, m, 31) if m in (3, 10) else None
        return x - pd.Timedelta(days=(x.weekday() + 1) % 7)
    return last_sun(d.year, 3) <= d < last_sun(d.year, 10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    res = {}
    days_main = pd.bdate_range(*MAIN)
    # ---- a：同樣本描述
    mid = leads_from_series(dukascopy_series("mid"), days_main)
    for k in LEADS:
        x = mid[k]
        r = {"all": summ(x)}
        r["by_year_bp"] = {int(y): round(float(v * 1e4), 2) for y, v in x.groupby(x.index.year).mean().items()}
        r["by_year_t"] = {int(y): round(tstat(v), 2) for y, v in x.groupby(x.index.year)}
        summer = np.array([european_summer(d) for d in x.index])
        r["summer"], r["winter"] = summ(x[summer]), summ(x[~summer])
        r["by_weekday"] = {n: summ(x[x.index.weekday == i]) for i, n in enumerate(["一", "二", "三", "四", "五"])}
        r["bid_only"] = summ(leads_from_series(dukascopy_series("bid"), days_main)[k])
        r["ask_only"] = summ(leads_from_series(dukascopy_series("ask"), days_main)[k])
        r["first_half"], r["second_half"] = summ(x[x.index < "2015-01-01"]), summ(x[x.index >= "2015-01-01"])
        res[k] = {"a": r}
    # IB 成本核對
    ib = pd.read_csv(ROOT / "data_forex_ibkr" / "spot_EURUSD_M5_bid_ask.csv.gz", parse_dates=["Time"]).set_index("Time")
    rel = (ib["Close"] - ib["Open"]) / ((ib["Open"] + ib["Close"]) / 2)
    hm = ib.index.hour * 60 + ib.index.minute
    def near(h):                                                     # 起點 h:00–h:15 與終點前 15 分鐘的平均相對點差
        return float(rel[(hm >= h * 60) & (hm < h * 60 + 15)].mean())
    def before(h):
        return float(rel[(hm >= h * 60 - 15) & (hm < h * 60)].mean())
    for k, (a, b, sg) in LEADS.items():
        sp = (near(a) + before(b)) / 2
        net_period = mid[k][(mid.index >= "2024-09-17") & (mid.index <= "2026-08-31")]
        gross = float(net_period.mean())
        res[k]["a"]["ib_cost"] = {"spread_bp_start": round(near(a) * 1e4, 2), "spread_bp_end": round(before(b) * 1e4, 2), "half_each_side_bp": round(sp * 1e4, 2),
                                   "commission_bp": 0.4, "gross_bp_2024_09_to_2026_08": round(gross * 1e4, 2),
                                   "net_bp": round((gross - sp - 0.4e-4) * 1e4, 2), "n": int(net_period.notna().sum()), "t_gross": round(tstat(net_period), 2)}
    # ---- b / c：HistData M1
    all_days = pd.bdate_range(OOS[0], MAIN[1])
    hd = histdata_leads(all_days)
    for k in LEADS:
        x = hd[k]
        dm = x[(x.index >= MAIN[0]) & (x.index <= MAIN[1])]
        j = pd.concat([mid[k].rename("duka"), dm.rename("hd")], axis=1, sort=True).dropna()
        corr = float(j.duka.corr(j.hd))
        diff = float((j.hd.mean() - j.duka.mean()) * 1e4)
        b_pass = bool(corr >= 0.9 and np.sign(j.hd.mean()) == np.sign(j.duka.mean()) and abs(diff) <= 0.5)
        oos = x[(x.index >= OOS[0]) & (x.index <= OOS[1])]
        c = summ(oos)
        c["pass_one_sided_1.96"] = bool(c["t"] >= 1.96)
        res[k]["b"] = {"histdata_main": summ(dm), "corr_with_dukascopy": round(corr, 3), "mean_diff_bp": round(diff, 3), "pass": b_pass}
        res[k]["c"] = {"oos_2000_05_to_2003_07": c, "by_year_bp": {int(y): round(float(v * 1e4), 2) for y, v in oos.groupby(oos.index.year).mean().items()}}
        # 補充（描述）：HistData 全期 2000-05 → 2026-08 按年毛均值
        res[k]["histdata_by_year_bp"] = {int(y): round(float(v * 1e4), 2) for y, v in x.groupby(x.index.year).mean().items()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "lead_followup.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in LEADS:
        r = res[k]
        print(f"=== {k}（{ 'EURUSD 做空 09–12 UTC' if k == 'L1' else 'EURUSD 做多 01–06 UTC'}）")
        print("a 全樣本：", r["a"]["all"], "｜前半", r["a"]["first_half"], "｜後半", r["a"]["second_half"])
        print("a 夏令/冬令：", r["a"]["summer"], "/", r["a"]["winter"])
        print("a 買價/賣價：", r["a"]["bid_only"], "/", r["a"]["ask_only"])
        print("a 星期：", {n: (v["mean_bp"], v["t"]) for n, v in r["a"]["by_weekday"].items()})
        print("a 按年毛均值 bp：", r["a"]["by_year_bp"])
        print("a IB 成本核對：", r["a"]["ib_cost"])
        print("b 跨來源：", r["b"])
        print("c 樣本外：", r["c"])
        print("HistData 按年毛均值 bp：", r["histdata_by_year_bp"])


if __name__ == "__main__":
    main()
