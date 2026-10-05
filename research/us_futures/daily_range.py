"""ES／NQ／YM 連續合約日線 26 年（data/us_futures/，yfinance，CME 全段）：HAR 波幅預測與高低位校準（2026-10-05）。
與恒指同一程式（main.har_forecasts、main.futu_accuracy），逐日前推；最後一列（進行中的今天）剔除。
用法：python3 research/us_futures/daily_range.py → research/us_futures/daily_range/REPORT.md、<sym>_daily_forecast.csv
"""
import csv, os, sys, types
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent; REPO = HERE.parents[1]
sys.path.insert(0, str(REPO)); os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "x")
import google, google.cloud                                      # noqa: E402
_sm = types.ModuleType("google.cloud.storage"); _sm.Client = lambda *a, **k: None; sys.modules["google.cloud.storage"] = _sm; google.cloud.storage = _sm
_g = types.ModuleType("google.genai"); _g.Client = lambda *a, **k: None; _g.types = types.SimpleNamespace(); sys.modules["google.genai"] = _g
_e = types.ModuleType("google.api_core.exceptions"); _e.PreconditionFailed = type("PC", (Exception,), {}); _e.NotFound = KeyError
_ac = types.ModuleType("google.api_core"); _ac.exceptions = _e; sys.modules["google.api_core"] = _ac; sys.modules["google.api_core.exceptions"] = _e
import main                                                      # noqa: E402

OUT = HERE / "daily_range"


def main_():
    OUT.mkdir(exist_ok=True)
    L = ["# ES／NQ／YM 日線 26 年：HAR 波幅預測與高低位校準（daily_range.py）", "",
         "- 來源 data/us_futures/<sym>_daily.csv（yfinance 連續合約，CME 全段日線）；與恒指同一程式逐日前推；預計範圍 2%／98% 分位；✓ 門檻 1%。", "",
         "| 合約 | 期間 | 天數 | 波幅落在 80% 範圍 | 高低都落在範圍 | 高／低各自 | 都在 1% 內 | 高位誤差中位 | 2000s 範圍／1% | 2010s | 2020s |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for sym in ("ES", "NQ", "YM"):
        rows = [r for r in csv.DictReader(open(REPO / "data" / "us_futures" / f"{sym}_daily.csv")) if float(r["High"]) > float(r["Low"])][:-1]
        daily = [{"time_key": f"{r['Date']} 00:00:00", "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
                  "close": float(r["Close"]), "volume": 1, "source": "yf"} for r in rows]
        rr = main.futu_range_rows(daily); har = main.har_forecasts(rr); acc = main.futu_accuracy(rr, har)
        d = acc["day"]; recs = [r for r in d["records"] if r.get("err_high") is not None]
        dec = {}
        for r in recs:
            dec.setdefault(r["key"][:3] + "0s", []).append(r)
        cell = lambda v: f"{np.mean([r['hit'] for r in v]):.0%}／{np.mean([abs(r['err_high']) / r['high'] * 100 <= 1 and abs(r['err_low']) / r['low'] * 100 <= 1 for r in v]):.0%}"
        L.append(f"| {sym} | {rows[0]['Date']} 至 {rows[-1]['Date']} | {d['n']} | {d['hit_range_rate']}% | **{d['hit_rate']}%** | {d['hit_high_rate']}／{d['hit_low_rate']} | "
                 f"{d['within_rate']}% | {np.median([abs(r['err_high']) / r['high'] * 100 for r in recs]):.2f}% | " + " | ".join(cell(dec[k]) for k in sorted(dec)) + " |")
        with open(OUT / f"{sym}_daily_forecast.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["date", "rhat", "lo", "hi", "actual_range", "high", "high_lo", "high_hi", "actual_high", "low", "low_lo", "low_hi", "actual_low", "hit"])
            for r in d["records"]:
                w.writerow([r["key"], r["forecast"], r["lo"], r["hi"], r["actual"], r.get("high"), r.get("high_lo"), r.get("high_hi"), r["actual_high"],
                            r.get("low"), r.get("low_lo"), r.get("low_hi"), r["actual_low"], r.get("hit")])
    L += ["", "恒指期貨對照（Futu 558 天）：落在範圍 92%、1% 內 65%、高位誤差中位 0.52%。NQ 差價合約 15 分 K 合成日線（4.2 年）：91%／72%／0.38%，與這裡的 NQ 日線一致。"]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8"); print("\n".join(L))


if __name__ == "__main__":
    main_()
