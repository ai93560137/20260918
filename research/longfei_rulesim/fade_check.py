"""[IDEAS #131] 反向做開市突破（fade）長歷史驗證（只係研究，唔改每日回測、唔落單）。

#130 樣本外（08-03→10-13，5 分鐘）見到：順日線追開市區間突破 644 單 −0.127R（t −3.97），即係突破多數失敗。
假說：咁反方向做（突破收市後博返入區間）應該有正期望。呢個假說係由 08-03 之後嘅數據諗出嚟，
所以只可以用 **2026-08-01 之前** 嘅數據驗（yfinance 1 小時 K 線，最多約 730 日）。

規則（10-27 預先登記，唔再調參數）：
  開市區間（OR）＝ 當日第一支 1 小時 K 線（美股 09:30–10:30 美東；^HSI 第一支）。
  之後第一支「順日線方向」收市突破 OR 嘅 1 小時 K 線（唔計當日最後一支）＝ 訊號；趨勢＝昨收 vs 20 日均線。
  F1 反向：喺訊號 K 線收市價反方向入場；止蝕＝訊號 K 線極端位（最少 0.15%）；目標＝OR 中位；冇到就收市平倉。
  F2 反向：同 F1，但冇目標，收市平倉。
  A1 對照（唔係成功標準）：順勢入場，止蝕 OR 另一邊（最少 0.15%），收市平倉 — 睇 1 小時版同 5 分鐘版係咪一致。
  同一支 K 線掂止蝕同目標當止蝕（保守）。成本每邊 0.015%（HSI 2 點）。
成功標準：F1 或 F2 ≥ 300 單、平均 ≥ +0.10R、t ≥ 2，而且前後兩半各自平均 > 0。
過咗下一步只係加入每日紙上回測做前向測試（唔係真倉）；唔過就棄用。

用法：python3 research/longfei_rulesim/fade_check.py [--before 2026-08-01] [--no-upload]
"""
import argparse
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulesim import US, us_trend  # noqa: E402

PRODUCTS = [("HSI", "^HSI", "Asia/Hong_Kong")] + [(p, p, "America/New_York") for p in US]


def load_1h(yf, ticker, tz):
    df = yf.download(ticker, period="730d", interval="1h", progress=False, auto_adjust=False)
    if df is None or df.empty:
        return {}
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    idx = df.index.tz_convert(tz) if df.index.tz is not None else df.index
    days = {}
    for t, r in zip(idx, df.itertuples()):
        if any(math.isnan(x) for x in (r.Open, r.High, r.Low, r.Close)):
            continue
        dt = datetime(t.year, t.month, t.day, t.hour, t.minute)
        days.setdefault(dt.date().isoformat(), []).append((dt, float(r.Open), float(r.High), float(r.Low), float(r.Close)))
    return {d: sorted(v) for d, v in days.items()}


def daily_closes(yf, ticker):
    s = yf.download(ticker, period="5y", interval="1d", progress=False, auto_adjust=False)["Close"]
    if hasattr(s, "columns"):
        s = s.iloc[:, 0]
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in s.dropna().items()}


def sim(bars, i, side, entry, stop, target, cost):
    """由第 i+1 支 K 線開始行；回傳 R。"""
    risk = abs(entry - stop)
    exit_px = None
    for _, o, h, l, c in bars[i + 1:]:
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            exit_px = min(stop, o) if side > 0 else max(stop, o)
            break
        if target is not None and ((side > 0 and h >= target) or (side < 0 and l <= target)):
            exit_px = target
            break
    if exit_px is None:
        exit_px = bars[-1][4]
    return ((exit_px - entry) * side - 2 * cost) / risk


def run_day(bars, trend, is_hsi):
    if not trend or len(bars) < 4:
        return {}
    orh, orl = bars[0][2], bars[0][3]
    mid = (orh + orl) / 2
    for i in range(1, len(bars) - 1):
        b = bars[i]
        if (trend > 0 and b[4] > orh) or (trend < 0 and b[4] < orl):
            entry = b[4]
            cost = 2.0 if is_hsi else entry * 0.00015
            mr = entry * 0.0015
            side = -trend                                         # 反向
            stop = b[2] if side < 0 else b[3]
            if abs(stop - entry) < mr:
                stop = entry - side * mr
            f1_target = mid if (mid - entry) * side > 0 else None
            a_stop = orl if trend > 0 else orh
            if abs(a_stop - entry) < mr:
                a_stop = entry - trend * mr
            return {"F1": sim(bars, i, side, entry, stop, f1_target, cost),
                    "F2": sim(bars, i, side, entry, stop, None, cost),
                    "A1": sim(bars, i, trend, entry, a_stop, None, cost)}
    return {}


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
    ap.add_argument("--before", default="2026-08-01")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    rows = {k: [] for k in ("F1", "F2", "A1")}
    for prod, ticker, tz in PRODUCTS:
        days, closes = load_1h(yf, ticker, tz), daily_closes(yf, ticker)
        for day in sorted(days):
            if day >= a.before:
                continue
            for k, r in run_day(days[day], us_trend(closes, day), prod == "HSI").items():
                rows[k].append({"date": day, "product": prod, "r": round(r, 4)})
        print(prod, len(days), "日", {k: len(v) for k, v in rows.items()}, flush=True)

    dates = sorted({x["date"] for x in rows["A1"]})
    split = dates[len(dates) // 2] if dates else ""
    report = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "before": a.before,
              "period": [dates[0], dates[-1]] if dates else None, "split": split,
              "rule": "IDEAS #131 預先登記：≥300 單、avg ≥ +0.10R、t ≥ 2、前後兩半平均都 > 0", "variants": {}}
    for k, v in rows.items():
        s = {"all": stats([x["r"] for x in v]),
             "first_half": stats([x["r"] for x in v if x["date"] < split]),
             "second_half": stats([x["r"] for x in v if x["date"] >= split]),
             "hsi": stats([x["r"] for x in v if x["product"] == "HSI"])}
        if k != "A1":
            al = s["all"]
            s["pass"] = bool(al.get("n", 0) >= 300 and al.get("avg_r", -9) >= 0.10 and (al.get("t") or 0) >= 2
                             and s["first_half"].get("avg_r", -9) > 0 and s["second_half"].get("avg_r", -9) > 0)
        report["variants"][k] = s
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/fade_report.json").upload_from_string(
            json.dumps({**report, "trades": rows}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
