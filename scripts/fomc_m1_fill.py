#!/usr/bin/env python3
"""補抓指定 UTC 日的 Dukascopy M1 bid（FOMC 漂移回測的缺價日；HistData 2023-02→07 系統性缺奇數小時）。登記：FX_FOMC_DRIFT_BACKTEST.md 第 0 節。

    python3 scripts/fomc_m1_fill.py --days 2023-03-20 2023-03-22 ... --pairs EURUSD USDCHF USDJPY GBPUSD --out data_forex_rates/fomc/m1_fill
輸出 <out>/<PAIR>_<YYYY-MM-DD>.csv.gz（Time,Open,High,Low,Close，UTC）；已存在的日子跳過。
"""
import argparse
import csv
import gzip
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DEC = {"EURUSD": 5, "USDCHF": 5, "USDJPY": 3, "GBPUSD": 5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", required=True)
    ap.add_argument("--pairs", nargs="+", default=list(DEC))
    ap.add_argument("--out", type=Path, default=ROOT / "data_forex_rates" / "fomc" / "m1_fill")
    a = ap.parse_args()
    from fetch_forex import Feed, Throttled, log
    feed = Feed(2, 1.0)
    a.out.mkdir(parents=True, exist_ok=True)
    for ds in a.days:
        d = date.fromisoformat(ds)
        for p in a.pairs:
            f = a.out / f"{p}_{ds}.csv.gz"
            if f.exists():
                continue
            try:
                rows = feed.candles(f"{p}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5", datetime(d.year, d.month, d.day), 10 ** DEC[p])
            except Throttled as e:
                log(f"限流到頂 {p} {ds}: {e}"); return
            if not rows:
                log(f"{p} {ds}: 無數據"); continue
            with gzip.open(f, "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh); w.writerow(["Time", "Open", "High", "Low", "Close"])
                for r in rows:
                    w.writerow([r[0], f"{r[1]:.{DEC[p]}f}", f"{r[2]:.{DEC[p]}f}", f"{r[3]:.{DEC[p]}f}", f"{r[4]:.{DEC[p]}f}"])
            log(f"{p} {ds}: {len(rows)} 根")


if __name__ == "__main__":
    main()
