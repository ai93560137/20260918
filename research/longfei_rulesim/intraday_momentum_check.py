"""[IDEAS #142] 美股「日內動量」：開市頭段回報預測收市尾段方向（Gao, Han, Li, Zhou 2018，Journal of Financial Economics
"Market Intraday Momentum"：SPY 頭半個鐘回報（由昨收計）預測最後半個鐘回報）。

我哋數據得 1 小時 K 線（yfinance，約 730 日），所以用近似：
  訊號 r1 ＝ 第一支 1 小時 K 線收市 ÷ 昨日收市 − 1（包括隔夜）。
  交易：喺最後一支 K 線（15:30–16:00）開市價按 r1 方向入場，收市平；|r1| < 0.1% 唔做。
  成本每邊 0.015%。
只用指數 ETF：SPY、QQQ、DIA、IWM（論文主要係 SPY）。

預先登記（10-27）成功標準：4 隻合計每筆平均回報（扣成本）> 0、t ≥ 2、前後兩半都 > 0，而且 SPY 單獨 > 0。
過咗先加入即日回測做紙上前向測試；唔過就棄用。只係研究，唔落單。

用法：python3 research/longfei_rulesim/intraday_momentum_check.py [--no-upload]
"""
import argparse
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fade_check import load_1h  # noqa: E402

TICKERS = ["SPY", "QQQ", "DIA", "IWM"]
COST = 0.00015
MIN_SIG = 0.001


def stats(xs):
    n = len(xs)
    if n < 2:
        return {"n": n}
    m = sum(xs) / n
    sd = statistics.stdev(xs)
    return {"n": n, "avg_bp": round(m * 1e4, 2), "win": round(sum(x > 0 for x in xs) / n, 3),
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    rows = []
    for p in TICKERS:
        days = load_1h(yf, p, "America/New_York")
        keys = sorted(days)
        for i in range(1, len(keys)):
            prev, bars = days[keys[i - 1]], days[keys[i]]
            if len(bars) < 6 or not prev:
                continue
            last = bars[-1]
            if last[0].hour != 15 or last[0].minute != 30:          # 要係 15:30 嗰支（半日市跳過）
                continue
            r1 = bars[0][4] / prev[-1][4] - 1
            if abs(r1) < MIN_SIG:
                continue
            side = 1 if r1 > 0 else -1
            ret = (last[4] / last[1] - 1) * side - 2 * COST
            rows.append({"date": keys[i], "p": p, "r1": round(r1, 5), "ret": ret})
        print(p, len(keys), "日", sum(x["p"] == p for x in rows), "單", flush=True)

    ds = sorted({x["date"] for x in rows})
    split = ds[len(ds) // 2] if ds else ""
    rep = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "period": [ds[0], ds[-1]] if ds else None, "split": split,
           "rule": "IDEAS #142：合計扣費平均 > 0、t ≥ 2、前後兩半 > 0、SPY 單獨 > 0",
           "all": stats([x["ret"] for x in rows]),
           "h1": stats([x["ret"] for x in rows if x["date"] < split]),
           "h2": stats([x["ret"] for x in rows if x["date"] >= split]),
           "by": {p: stats([x["ret"] for x in rows if x["p"] == p]) for p in TICKERS},
           "gross_all_bp": round(sum(x["ret"] + 2 * COST for x in rows) / max(len(rows), 1) * 1e4, 2)}
    al = rep["all"]
    rep["pass"] = bool(al.get("avg_bp", -1) > 0 and (al.get("t") or 0) >= 2 and rep["h1"].get("avg_bp", -1) > 0
                       and rep["h2"].get("avg_bp", -1) > 0 and rep["by"]["SPY"].get("avg_bp", -1) > 0)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/intraday_momentum_report.json").upload_from_string(
            json.dumps(rep, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
