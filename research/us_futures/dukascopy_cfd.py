"""Dukascopy 差價合約 15 分 K（data/dukascopy/<instrument>_m15.csv.gz，UTC、K 線開市時間）→ CME 全段交易日。
交易日 = 紐約時間 + 6 小時後的日期（18:00 起算下一天，與 main.MARKETS['US'] 相同）；time_key 轉成紐約時間、收市時間（+15 分鐘）。
2016–2017 的早期數據只有 07:00–21:00 UTC（不是全段），少於 MIN_BARS 根的交易日剔除，所以分析實際由全段數據開始的那天起。
用法（模組）：bars, daily = dukascopy_cfd.load("usa500idxusd")
"""
import csv, gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
NY = ZoneInfo("America/New_York")
MIN_BARS = 80                      # 全段約 89–92 根；少於 80 根（早期縮短時段、假期）剔除


def load(instrument="usa500idxusd", path=None):
    p = Path(path) if path else REPO / "data" / "dukascopy" / f"{instrument}_m15.csv.gz"
    by = {}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(NY).replace(tzinfo=None) + timedelta(minutes=15)
            d = (t + timedelta(hours=6)).strftime("%Y-%m-%d")
            by.setdefault(d, []).append({"time_key": t.strftime("%Y-%m-%d %H:%M:%S"), "open": float(r["open"]), "high": float(r["high"]),
                                         "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"] or 0) or 1.0, "session": d})
    bars, daily = [], []
    for d in sorted(by):
        seq = sorted(by[d], key=lambda b: b["time_key"])
        if len(seq) < MIN_BARS or datetime.strptime(d, "%Y-%m-%d").weekday() >= 5:
            continue
        bars += seq
        daily.append({"time_key": f"{d} 00:00:00", "open": seq[0]["open"], "high": max(b["high"] for b in seq), "low": min(b["low"] for b in seq),
                      "close": seq[-1]["close"], "volume": sum(b["volume"] for b in seq), "source": f"dukascopy:{instrument}", "bars": len(seq)})
    return bars, daily


if __name__ == "__main__":
    import sys
    b, d = load(sys.argv[1] if len(sys.argv) > 1 else "usa500idxusd")
    print(len(b), "bars", len(d), "days", d[0]["time_key"], "→", d[-1]["time_key"], "bars/day median", sorted(x["bars"] for x in d)[len(d) // 2])
