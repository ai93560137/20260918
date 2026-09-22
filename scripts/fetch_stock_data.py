#!/usr/bin/env python3
"""抓取股票/指數日線數據，存成 data/stocks/<TICKER>.csv.gz。

由 .github/workflows/fetch_stock_data.yml 排程執行；本機也可手動跑：
    python3 scripts/fetch_stock_data.py scripts/universe_hk.txt scripts/universe_us.txt

每次執行對每個 ticker 重抓全部歷史（yfinance period=max）並整檔覆寫，
不做增量合併——日線資料量小，整檔覆寫可自動修正 Adj Close 的股息回溯調整，
邏輯也最簡單。
"""
import argparse
import csv
import gzip
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks"


def read_universe(path: Path) -> list[str]:
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line)
    return tickers


def safe_filename(ticker: str) -> str:
    return ticker.replace("^", "_") + ".csv.gz"


def fetch_one(ticker: str) -> None:
    hist = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=False)
    if hist.empty:
        raise RuntimeError("yfinance 回傳空資料（可能是暫時性 rate limit，重跑一次通常會好）")

    out_path = DATA_DIR / safe_filename(ticker)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Open", "High", "Low", "Close", "AdjClose", "Volume"])
        for idx, row in hist.iterrows():
            volume = 0 if pd.isna(row["Volume"]) else int(row["Volume"])
            writer.writerow([
                idx.strftime("%Y-%m-%d"),
                f"{row['Open']:.4f}",
                f"{row['High']:.4f}",
                f"{row['Low']:.4f}",
                f"{row['Close']:.4f}",
                f"{row['Adj Close']:.4f}",
                volume,
            ])
    print(f"OK {ticker}: {len(hist)} 根 -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "universe", nargs="+", type=Path,
        help="ticker 清單檔（每行一個代碼，# 開頭整行為註解）",
    )
    args = ap.parse_args()

    tickers: list[str] = []
    for path in args.universe:
        tickers.extend(read_universe(path))

    if not tickers:
        print("ERROR: 空的 ticker 清單", file=sys.stderr)
        sys.exit(1)

    def fetch_all(ts: list[str]) -> list[str]:
        still_failed = []
        for ticker in ts:
            try:
                fetch_one(ticker)
            except Exception as exc:
                print(f"ERROR {ticker}: {exc}", file=sys.stderr)
                still_failed.append(ticker)
            time.sleep(0.3)  # 降低連續請求觸發 yfinance/Yahoo rate limit 的機率
        return still_failed

    failed = fetch_all(tickers)
    if failed:
        print(f"第一輪 {len(failed)} 個失敗，重試一次: {failed}", file=sys.stderr)
        time.sleep(5)
        failed = fetch_all(failed)

    if failed:
        print(f"重試後仍失敗 {len(failed)} 個: {failed}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
