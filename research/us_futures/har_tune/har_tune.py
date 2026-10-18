"""[R231] ES／NQ 日波幅 HAR 調校回測（使用者 2026-10-18：「NQ 預測波幅 日週月都不準 再調較」）。
數據：data/us_futures/<ES|NQ>_daily.csv（yfinance 連續合約，2000 起）；評分期 2016-01-01 起，逐日前推（main.har_forecasts）。
比較：舊（HAR(1,5,22)＋平均 smearing）對 新（中位＋前一日跌幅／升幅＋星期一／五）。另計週／月波幅 ÷（日 R̂ × √交易日數）分位，
用作 main.MARKETS 的 period_ratio。輸出：<sym>_daily.csv（逐日預測）、ratios.csv、REPORT.md 的數字。
用法：python3 research/us_futures/har_tune/har_tune.py
"""
import contextlib, csv, io, math, os, statistics as st, sys
from datetime import date
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
with contextlib.redirect_stdout(io.StringIO()):
    import main
OUT = os.path.dirname(os.path.abspath(__file__))
START = "2016-01-01"


def quant(v, q):
    v = sorted(v); return main._quantile(v, q)


ratio_rows = []
for sym, alias in (("NQ", "US.NQ_FRONT"), ("ES", "US.ES_FRONT")):
    raw = list(csv.DictReader(open(os.path.join(ROOT, "data", "us_futures", f"{sym}_daily.csv"))))
    bars = [{"time_key": r["Date"] + " 00:00:00", "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
             "close": float(r["Close"]), "volume": 1} for r in raw if float(r["High"]) > 0]
    rr = main.futu_range_rows(bars)
    old, new = main.har_forecasts(rr), main.har_forecasts(rr, symbol=alias)
    with open(os.path.join(OUT, f"{sym}_daily.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "actual_range", "old_fc", "old_lo80", "old_hi80", "new_fc", "new_lo80", "new_hi80"])
        for i, r in enumerate(rr):
            if r["date"] >= START and i in old and i in new:
                w.writerow([r["date"], round(r["high"] - r["low"], 2), *old[i], *new[i]])
    for label, har in (("old", old), ("new", new)):
        sel = [(rr[i], har[i]) for i in sorted(har) if i < len(rr) and rr[i]["date"] >= START]
        act = [r["high"] - r["low"] for r, _ in sel]
        err = [abs(a - f[0]) / a for (r, f), a in zip(sel, act)]
        print(f"{sym} 日 {label}: n={len(sel)} 平均誤差 {st.mean(err):.1%} 偏差 {st.mean((f[0] - a) / a for (r, f), a in zip(sel, act)):+.1%} "
              f"80% 覆蓋 {st.mean(1 if f[1] <= a <= f[2] else 0 for (r, f), a in zip(sel, act)):.1%}")
        for kind in ("week", "month"):
            groups = {}
            for i, r in enumerate(rr):
                y, m, d = map(int, r["date"].split("-"))
                groups.setdefault(tuple(date(y, m, d).isocalendar()[:2]) if kind == "week" else (y, m), []).append(i)
            v = [(max(rr[i]["high"] for i in ii) - min(rr[i]["low"] for i in ii)) / (har[ii[0]][0] * math.sqrt(len(ii)))
                 for ii in groups.values() if ii[0] in har and rr[ii[0]]["date"] >= START]
            q = [round(quant(v, x), 3) for x in (0.1, 0.5, 0.9)]
            ratio_rows.append([sym, label, kind, len(v), *q])
            print(f"   {kind} 比例 10/50/90%: {q}（n={len(v)}）")
with open(os.path.join(OUT, "ratios.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["symbol", "model", "kind", "n", "q10", "q50", "q90"]); w.writerows(ratio_rows)
