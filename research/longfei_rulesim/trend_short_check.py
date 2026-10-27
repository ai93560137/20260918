"""[IDEAS #132] 使用者方法「日線跌勢＋當日向下就沽空」長歷史驗證（只係研究，唔落單）。

使用者富途恒指紀錄：日線跌勢＋當日向下沽空 34 筆獲利因子 5.1；做好 29 筆獲利因子 0.05（IDEAS #129）。
呢度將佢寫成機械規則，用 yfinance ^HSI 1 小時 K 線（約 730 日）驗。

規則（10-27 預先登記，唔再調參數）：
  日線跌勢＝昨收 < 之前 20 日收市平均（同 rulesim.us_trend）。
  當日向下＝某支 1 小時 K 線（唔計第一支同最後一支）收市 < 當日開市價 而且 < 昨收；當日第一個訊號就喺嗰個收市價沽空。
  止蝕＝當日到訊號為止嘅最高位（最少 0.15%）。
  S1：收市平倉。S2：目標 2R，冇到收市平倉。同一支 K 線掂止蝕同目標當止蝕。成本每邊 HSI 2 點、美股 0.015%。
  L1（鏡像：日線升勢＋當日向上做好）只做對照。
成功標準：^HSI 嘅 S1 或 S2 ≥ 100 單、平均 ≥ +0.10R、t ≥ 2，而且前後兩半各自平均 > 0。
SPY／QQQ／DIA 只做參考，唔計入標準。過咗下一步係將佢寫入恒指教學簿做 MHI 真倉入場條件（要使用者批准）；唔過就棄用。

用法：python3 research/longfei_rulesim/trend_short_check.py [--no-upload]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fade_check import daily_closes, load_1h, sim, stats  # noqa: E402
from rulesim import us_trend  # noqa: E402

PRODUCTS = [("HSI", "^HSI", "Asia/Hong_Kong"), ("SPY", "SPY", "America/New_York"),
            ("QQQ", "QQQ", "America/New_York"), ("DIA", "DIA", "America/New_York")]


def run_day(bars, trend, prev_close, is_hsi):
    """回傳 {"S1": R, "S2": R} 或 {"L1": R}。"""
    if not trend or prev_close is None or len(bars) < 4:
        return {}
    day_open = bars[0][1]
    for i in range(1, len(bars) - 1):
        c = bars[i][4]
        down = c < day_open and c < prev_close
        up = c > day_open and c > prev_close
        if (trend < 0 and down) or (trend > 0 and up):
            side = -1 if trend < 0 else 1
            cost = 2.0 if is_hsi else c * 0.00015
            mr = c * 0.0015
            stop = max(b[2] for b in bars[:i + 1]) if side < 0 else min(b[3] for b in bars[:i + 1])
            if abs(stop - c) < mr:
                stop = c - side * mr
            risk = abs(stop - c)
            if side < 0:
                return {"S1": sim(bars, i, side, c, stop, None, cost),
                        "S2": sim(bars, i, side, c, stop, c - 2 * risk, cost)}
            return {"L1": sim(bars, i, side, c, stop, None, cost)}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    rows = []
    for prod, ticker, tz in PRODUCTS:
        days, closes = load_1h(yf, ticker, tz), daily_closes(yf, ticker)
        cd = sorted(closes)
        for day in sorted(days):
            prev = [d for d in cd if d < day]
            pc = closes[prev[-1]] if prev else None
            for k, r in run_day(days[day], us_trend(closes, day), pc, prod == "HSI").items():
                rows.append({"date": day, "product": prod, "v": k, "r": round(r, 4)})
        print(prod, len(days), "日", sum(x["product"] == prod for x in rows), "單", flush=True)

    report = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
              "rule": "IDEAS #132 預先登記：^HSI S1 或 S2 ≥100 單、avg ≥ +0.10R、t ≥ 2、前後兩半平均都 > 0", "results": {}}
    for prod, _, _ in PRODUCTS:
        for v in ("S1", "S2", "L1"):
            sel = [x for x in rows if x["product"] == prod and x["v"] == v]
            if not sel:
                continue
            ds = sorted({x["date"] for x in sel})
            split = ds[len(ds) // 2]
            s = {"period": [ds[0], ds[-1]], "all": stats([x["r"] for x in sel]),
                 "first_half": stats([x["r"] for x in sel if x["date"] < split]),
                 "second_half": stats([x["r"] for x in sel if x["date"] >= split])}
            if prod == "HSI" and v in ("S1", "S2"):
                al = s["all"]
                s["pass"] = bool(al.get("n", 0) >= 100 and al.get("avg_r", -9) >= 0.10 and (al.get("t") or 0) >= 2
                                 and s["first_half"].get("avg_r", -9) > 0 and s["second_half"].get("avg_r", -9) > 0)
            report["results"][f"{prod}_{v}"] = s
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/trend_short_report.json").upload_from_string(
            json.dumps({**report, "trades": rows}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
