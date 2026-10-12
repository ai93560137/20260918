#!/usr/bin/env python3
"""L1（倫敦上午 09→12 UTC）在其他外匯對。登記：forex_research/FX_L1_OTHER_PAIRS.md。

    python3 scripts/fx_l1_other_pairs.py --out forex_research/fx_exploratory
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
END = pd.Timestamp("2026-08-31")
DIRECTIONAL = {"EURGBP": -1, "EURJPY": -1, "EURCHF": -1, "EURAUD": -1, "EURCAD": -1,
               "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCHF": 1, "USDCAD": 1}
REPORT_ONLY = ["GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY", "GBPCHF", "GBPAUD", "AUDNZD", "AUDCAD", "USDSGD", "XAUUSD", "XAGUSD"]
MAJORS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
FOREIGN_SIGN = {"EURUSD": 1, "GBPUSD": 1, "AUDUSD": 1, "NZDUSD": 1, "USDJPY": -1, "USDCHF": -1, "USDCAD": -1}   # 外幣對美元
HOURS = (7, 8, 9, 10, 11, 12, 13)
COMM = 0.4e-4


def load_h1(pair: str):
    d = ROOT / "data_forex" / pair
    b = pd.read_csv(d / f"{pair}_H1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    a = pd.read_csv(d / f"{pair}_H1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
    j = pd.concat([b.rename("b"), a.rename("a")], axis=1, sort=True).dropna()
    j.index = j.index + pd.Timedelta(hours=1)
    mid = (j.b + j.a) / 2
    rel = ((j.a - j.b) / mid).clip(lower=0)
    start = (mid.index[0] + pd.Timedelta(days=2)).normalize()
    days = pd.bdate_range(start, END)
    return mid, rel, days


def bounds(mid: pd.Series, days: pd.DatetimeIndex, hours) -> dict:
    out = {}
    for h in hours:
        t = (days + pd.Timedelta(hours=h)).values
        ix = np.clip(np.searchsorted(mid.index.values, t, side="right") - 1, 0, len(mid) - 1)
        out[h] = np.log(mid.values[ix])
    return out


def spread_cost(rel: pd.Series, days: pd.DatetimeIndex) -> np.ndarray:
    r = pd.DataFrame({"rel": rel.values, "year": rel.index.year, "hour": (rel.index - pd.Timedelta(hours=1)).hour})
    med = r.groupby(["year", "hour"]).rel.median()
    s9 = np.array([med.get((y, 9), np.nan) for y in days.year])
    s12 = np.array([med.get((y, 12), np.nan) for y in days.year])
    c = (pd.Series(s9).ffill().bfill().values + pd.Series(s12).ffill().bfill().values) / 2 + COMM
    return c


def tstat(x) -> float:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def histdata_window(pair: str, days: pd.DatetimeIndex) -> pd.Series:
    rows9, rows12, idxs = [], [], []
    carry = None
    for y in range(2000, 2027):
        f = ROOT / "data_forex" / pair / f"{pair}_M1_{y}.csv.gz"
        if not f.exists():
            continue
        s = pd.read_csv(f, parse_dates=["Time"], usecols=["Time", "Close"]).set_index("Time")["Close"]
        s.index = s.index + pd.Timedelta(minutes=1)
        if carry is not None:
            s = pd.concat([carry, s])
        carry = s.iloc[[-1]]
        dy = days[days.year == y]
        if not len(dy):
            continue
        for h, rows in ((9, rows9), (12, rows12)):
            t = (dy + pd.Timedelta(hours=h)).values
            ix = np.clip(np.searchsorted(s.index.values, t, side="right") - 1, 0, len(s) - 1)
            rows.append(np.log(s.values[ix]))
        idxs.append(dy)
    di = idxs[0].append(idxs[1:]) if len(idxs) > 1 else idxs[0]
    return pd.Series(np.concatenate(rows12) - np.concatenate(rows9), index=di)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    res = {"pairs": {}, "hourly_bp": {}}
    series = {}
    daily = {}
    pairs = list(DIRECTIONAL) + REPORT_ONLY + MAJORS[:1]
    for p in dict.fromkeys(pairs + MAJORS):
        mid, rel, days = load_h1(p)
        B = bounds(mid, days, HOURS)
        w = pd.Series(B[12] - B[9], index=days)
        series[p] = (w, spread_cost(rel, days), B, days)
        res["hourly_bp"][p] = {h: round(float((B[h + 1] - B[h]).mean() * 1e4), 2) for h in HOURS[:-1]}
    # ---- 主檢定
    for p in dict.fromkeys(list(DIRECTIONAL) + ["EURUSD"] + REPORT_ONLY):
        w, cost, B, days = series[p]
        sg = DIRECTIONAL.get(p, -1 if p == "EURUSD" else 1)
        x = sg * w if (p in DIRECTIONAL or p == "EURUSD") else w
        h = len(x) // 2
        r = {"type": "directional" if p in DIRECTIONAL else ("reference" if p == "EURUSD" else "report"), "dir": sg if p in DIRECTIONAL or p == "EURUSD" else 0,
             "start": str(days[0].date()), "n": int(len(x)), "gross_bp": round(float(x.mean() * 1e4), 3), "t": round(tstat(x), 2),
             "h1_bp": round(float(x.iloc[:h].mean() * 1e4), 3), "h2_bp": round(float(x.iloc[h:].mean() * 1e4), 3),
             "t_h1": round(tstat(x.iloc[:h]), 2), "t_h2": round(tstat(x.iloc[h:]), 2), "win": round(float((x > 0).mean()), 3), "cost_bp": round(float(cost.mean() * 1e4), 2)}
        if p in DIRECTIONAL:
            r["exists"] = bool(r["t"] >= 2.0 and r["h1_bp"] > 0 and r["h2_bp"] > 0)
            r["bonf_2.6"] = bool(r["t"] >= 2.6)
        res["pairs"][p] = r
    # ---- 貨幣層面分解
    common = series["EURUSD"][3]
    for p in MAJORS:
        common = common.intersection(series[p][3])
    R = pd.DataFrame({p: FOREIGN_SIGN[p] * series[p][0].reindex(common) for p in MAJORS})
    cusd = -R.sum(axis=1) / 8
    C = R.add(cusd, axis=0)
    C["USD"] = cusd
    cur = {}
    for k in C.columns:
        cur[k.replace("USD", "") if k != "USD" else "USD"] = {"mean_bp": round(float(C[k].mean() * 1e4), 3), "t": round(tstat(C[k]), 2),
                                                              "h1_bp": round(float(C[k].iloc[:len(C) // 2].mean() * 1e4), 3), "h2_bp": round(float(C[k].iloc[len(C) // 2:].mean() * 1e4), 3)}
    res["currency_decomposition"] = cur
    # ---- 「存在」的對：跨來源、樣本外、淨經濟性、組合
    exist = [p for p, r in res["pairs"].items() if r.get("exists")]
    res["exist"] = exist
    res["replication"] = {}
    nets = {}
    for p in exist + ["EURUSD"]:
        w, cost, B, days = series[p]
        sg = DIRECTIONAL.get(p, -1)
        x = sg * w
        net = x - pd.Series(cost, index=days)
        nets[p] = net
        r = {"net_bp": round(float(net.mean() * 1e4), 3), "net_t": round(tstat(net), 2), "net_sharpe": round(float(net.mean() / net.std() * math.sqrt(252)), 2),
             "net_ann_pct_1x": round(float(net.mean() * 252 * 100), 2)}
        try:
            hd = histdata_window(p, pd.bdate_range("2000-01-03", END))
            main = hd[hd.index >= days[0]]
            j = pd.concat([x.rename("duka"), (sg * main).rename("hd")], axis=1, sort=True).dropna()
            r["hd_same_period"] = {"gross_bp": round(float(j.hd.mean() * 1e4), 3), "corr": round(float(j.duka.corr(j.hd)), 3), "diff_bp": round(float((j.hd.mean() - j.duka.mean()) * 1e4), 3)}
            pre = hd[hd.index < days[0]]
            pre = pre[pre.index >= hd.index[0]]
            if len(pre) > 150:
                # HistData 該對第一個年檔之前沒有資料 → 以 hd 實際涵蓋日為準
                first = (ROOT / "data_forex" / p).glob(f"{p}_M1_20??.csv.gz")
                y0 = min(int(f.name.split("_")[-1][:4]) for f in first)
                pre = pre[pre.index >= pd.Timestamp(y0, 1, 1)]
            if len(pre) > 150:
                xp = sg * pre
                r["pre_h1_oos"] = {"n": int(len(xp)), "gross_bp": round(float(xp.mean() * 1e4), 3), "t": round(tstat(xp), 2), "pass_1.65": bool(tstat(xp) >= 1.65)}
        except Exception as exc:  # noqa: BLE001
            r["hd_error"] = repr(exc)
        res["replication"][p] = r
    if len(exist) >= 1:
        N = pd.concat([nets[p].rename(p) for p in exist], axis=1, sort=True).dropna()
        G = pd.concat([(DIRECTIONAL[p] * series[p][0]).rename(p) for p in exist], axis=1, sort=True).dropna().reindex(N.index)
        port_net, port_gross = N.mean(axis=1), G.mean(axis=1)
        eu = nets["EURUSD"].reindex(N.index)
        res["portfolio"] = {"pairs": exist, "n": int(len(N)), "gross_bp": round(float(port_gross.mean() * 1e4), 3),
                            "net_bp": round(float(port_net.mean() * 1e4), 3), "net_t": round(tstat(port_net), 2), "net_sharpe": round(float(port_net.mean() / port_net.std() * math.sqrt(252)), 2),
                            "net_ann_pct_1x": round(float(port_net.mean() * 252 * 100), 2), "vol_ann_pct": round(float(port_net.std() * math.sqrt(252) * 100), 2),
                            "corr_with_EURUSD": round(float(port_net.corr(eu)), 2),
                            "corr_matrix": {a: {b: round(float(N[a].corr(N[b])), 2) for b in N.columns} for a in N.columns}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "L1_other_pairs.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("== 主檢定（窗 09→12 UTC；方向性＝預測方向，report＝未乘方向的原始報酬）")
    for p, r in res["pairs"].items():
        print(f"{p:7} {r['type']:11} 起 {r['start']} n={r['n']} 毛 {r['gross_bp']:6.2f}bp t={r['t']:6.2f} 前/後半 {r['h1_bp']:6.2f}/{r['h2_bp']:6.2f} (t {r['t_h1']}/{r['t_h2']}) 勝率 {r['win']} 成本 {r['cost_bp']}"
              + (f"  存在={r['exists']} Bonf2.6={r['bonf_2.6']}" if 'exists' in r else ""))
    print("== 貨幣層面（七大，每日最小二乘；正 = 該貨幣相對籃子走強）：", json.dumps(res["currency_decomposition"], ensure_ascii=False))
    print("== 各對每小時漂移（基點，原始報酬 07→08 … 12→13）：")
    for p, h in res["hourly_bp"].items():
        print(f"  {p:7}", h)
    print("== 存在的對：", exist)
    for p, r in res["replication"].items():
        print("  ", p, r)
    print("== 組合：", json.dumps(res.get("portfolio"), ensure_ascii=False))


if __name__ == "__main__":
    main()
