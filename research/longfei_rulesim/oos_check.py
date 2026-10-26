"""[IDEAS #130] R295 規則變體樣本外檢查（只係研究，唔改每日回測、唔落單）。

10-14 至 10-26 嘅 93 單（樣本內）睇到兩條線索：
  - 突破後頭 30 分鐘入場（美股 10:00–10:30）46 單平均 −0.11R；10:30 之後入場好啲。
  - 開市區間（OR）窄過中位數嗰半 −0.11R，闊嗰半 +0.13R。
兩樣都係 93 單入面揀出嚟，好可能係巧合，所以喺 10-14 之前、規則冇見過嘅日子再驗。

數據：yfinance 5 分鐘 K 線（最多 60 日）；美股 23 隻 ETF／股票 + ^HSI（恒指現貨指數，近似大期）。
變體（10-27 預先登記，唔再調參數）：
  A 原版 R295 v1
  B 開市區間完結後 30 分鐘內唔入場（美股 10:30、HSI 10:15 前唔入）
  C 開市區間闊度 ≥ 該產品前 20 日 OR 闊度中位數先做
  D B＋C
成功標準（IDEAS #130）：樣本外變體 ≥ 150 單、平均 ≥ +0.10R、t ≥ 2，而且比 A 高 ≥ 0.10R；過咗先改每日回測做 v2。

用法：python3 research/longfei_rulesim/oos_check.py [--before 2026-10-14] [--no-upload]
"""
import argparse
import json
import math
import statistics
import sys
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulesim import SPEC, US, run_day, us_trend  # noqa: E402

FIRST = {"US": time(10, 30), "HSI": time(10, 15)}
VARIANTS = {"A": (False, False), "B": (True, False), "C": (False, True), "D": (True, True)}


def load(yf, ticker, tz):
    df = yf.download(ticker, period="60d", interval="5m", progress=False, auto_adjust=False)
    if df is None or df.empty:
        return {}
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    idx = df.index.tz_convert(tz) if df.index.tz is not None else df.index
    days = {}
    for t, r in zip(idx, df.itertuples()):
        dt = datetime(t.year, t.month, t.day, t.hour, t.minute)
        days.setdefault(dt.date().isoformat(), []).append((dt, float(r.Open), float(r.High), float(r.Low), float(r.Close)))
    return days


def daily_closes(yf, ticker):
    s = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=False)["Close"]
    if hasattr(s, "columns"):
        s = s.iloc[:, 0]
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in s.dropna().items()}


def stats(rs):
    n = len(rs)
    if n < 2:
        return {"n": n}
    m = sum(rs) / n
    sd = statistics.stdev(rs)
    return {"n": n, "avg_r": round(m, 3), "win": round(sum(r > 0 for r in rs) / n, 3),
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="2026-10-14", help="只計呢日之前（樣本外）")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    rows = {k: [] for k in VARIANTS}
    for prod in ["HSI"] + US:
        mk, ticker, tz = ("HSI", "^HSI", "Asia/Hong_Kong") if prod == "HSI" else ("US", prod, "America/New_York")
        sp = SPEC[mk]
        days, closes = load(yf, ticker, tz), daily_closes(yf, ticker)
        widths = []                                           # 前幾日 OR 闊度（佔價 %），只用當日之前
        for day in sorted(days):
            bars = [b for b in days[day] if sp["open"] <= b[0].time() <= sp["close"]]
            orb = [b for b in bars if sp["open"] <= b[0].time() < sp["or_end"]]
            if len(orb) < 6:
                continue
            w = (max(b[2] for b in orb) - min(b[3] for b in orb)) / orb[-1][4]
            med = statistics.median(widths[-20:]) if len(widths) >= 10 else None
            widths.append(w)
            if day >= a.before:
                continue
            trend = us_trend(closes, day)
            for k, (late, wide) in VARIANTS.items():
                if wide and med is None:
                    continue
                tr, _ = run_day(bars, trend, sp, min_or_bars=6, first_entry=FIRST[mk] if late else None,
                                min_or_width=med * orb[-1][4] if wide else None)
                if tr:
                    rows[k].append({"date": day, "product": prod, "r": tr["r"]})
        print(prod, len(days), "日", {k: len(v) for k, v in rows.items()}, flush=True)

    # C／D 要前 10 日先有中位數，A／B 同一批日子先公平比較
    first_ok = {}
    for x in rows["C"] + rows["D"]:
        first_ok[x["product"]] = min(first_ok.get(x["product"], x["date"]), x["date"])
    report = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "before": a.before,
              "variants": {}, "rule": "IDEAS #130 預先登記：≥150 單、avg ≥ +0.10R、t ≥ 2、比 A 高 ≥ 0.10R"}
    for k, v in rows.items():
        report["variants"][k] = {"all_days": stats([x["r"] for x in v])}
    base_same = [x["r"] for x in rows["A"] if x["product"] in first_ok and x["date"] >= first_ok[x["product"]]]
    report["variants"]["A"]["same_days_as_C"] = stats(base_same)
    a_avg = report["variants"]["A"]["all_days"].get("avg_r", 0)
    for k in "BCD":
        s = report["variants"][k]["all_days"]
        ref = a_avg if k == "B" else report["variants"]["A"]["same_days_as_C"].get("avg_r", 0)
        s["pass"] = bool(s.get("n", 0) >= 150 and s.get("avg_r", -9) >= 0.10 and (s.get("t") or 0) >= 2
                         and s["avg_r"] - ref >= 0.10)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/report.json").upload_from_string(
            json.dumps({**report, "trades": rows}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
