#!/usr/bin/env python3
"""第二收市數據源：Stooq（免費、免 API key 的 CSV 下載），存成
data/stocks_stooq/<TICKER>.csv.gz，給 scripts/check_data_quality.py
跟 yfinance（data/stocks/）交叉比對收市價——手冊鐵律第9條「第二數據源複核」。

跟 fetch_stock_data.py 吃同一批 universe 清單：
    python3 scripts/fetch_stooq.py scripts/universe_hk.txt scripts/pool_hsi_full.txt ...

Stooq 抓不到某檔（沒收錄、代碼格式不同、每日次數上限）只記錄原因、
不算失敗——這是複核用的第二來源，缺了只代表那檔沒有交叉驗證。
"""
import argparse
import csv
import gzip
import io
import sys
import time
from pathlib import Path

import requests

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks_stooq"
HEADERS = {"User-Agent": "Mozilla/5.0 (data-quality cross-check)"}
URL = "https://stooq.com/q/d/l/?s={sym}&i=d"

INDEX_MAP = {"^HSI": ["^hsi"], "^GSPC": ["^spx"]}


def read_universe(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def stooq_candidates(ticker: str) -> list[str]:
    if ticker in INDEX_MAP:
        return INDEX_MAP[ticker]
    if ticker.endswith(".HK"):
        code = ticker[:-3]
        # Stooq 港股代碼有沒有補零不確定，兩種都試
        return [f"{code}.hk".lower(), f"{code.lstrip('0')}.hk"]
    if ticker.startswith("^"):
        return [ticker.lower()]
    return [f"{ticker.lower()}.us"]


def fetch_one(ticker: str) -> tuple[int, str]:
    """回傳 (根數, 說明)；根數 0 代表沒抓到，說明是原因。"""
    last_reason = ""
    for sym in stooq_candidates(ticker):
        try:
            r = requests.get(URL.format(sym=sym), headers=HEADERS, timeout=30)
        except Exception as exc:
            last_reason = f"{sym}: {exc}"
            continue
        text = r.text.lstrip("﻿")
        if r.status_code != 200 or not text.startswith("Date,"):
            last_reason = f"{sym}: HTTP {r.status_code} {text[:80]!r}"
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            last_reason = f"{sym}: 空 CSV"
            continue
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / (ticker.replace("^", "_") + ".csv.gz")
        with gzip.open(out_path, "wt", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
            for row in rows:
                w.writerow([row.get("Date"), row.get("Open"), row.get("High"),
                            row.get("Low"), row.get("Close"), row.get("Volume", "")])
        return len(rows), sym
    return 0, last_reason


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("universe", nargs="+", type=Path)
    args = ap.parse_args()

    tickers: list[str] = []
    for p in args.universe:
        for t in read_universe(p):
            if t not in tickers:
                tickers.append(t)

    ok, missing = 0, []
    for t in tickers:
        n, info = fetch_one(t)
        if n:
            ok += 1
            print(f"OK {t}: {n} 根 ({info})")
        else:
            missing.append((t, info))
            print(f"MISS {t}: {info}", file=sys.stderr)
        time.sleep(0.5)

    print(f"\nStooq 覆蓋: {ok}/{len(tickers)}")
    if missing:
        # 次數上限類的訊息會讓整批都 MISS，印出前幾筆原因方便判斷
        print("前幾筆沒抓到的原因:", missing[:5])


if __name__ == "__main__":
    main()
