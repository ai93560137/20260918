#!/usr/bin/env python3
"""全市場日線（VCP_FULLMARKET_BACKTEST.md）→ data_full/<market>/<TICKER>.csv.gz（不進 git，存 Actions 快取）。

    python3 scripts/fetch_full_market.py --market us --budget-min 300

- 讀 universes/full/<market>_pool.txt，缺的才抓（可中斷續抓：已有檔就跳過；--refresh-days N 重抓 N 天前的舊檔）
- yfinance 分批下載（每批 100 檔，auto_adjust=False），欄位 Date,Open,High,Low,Close,AdjClose,Volume
- 抓不到的代碼（下市/改名）記在 data_full/<market>/_failed.txt，下次不再重試（除非 --retry-failed）
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCH = 100


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--refresh-days", type=int, default=0, help="檔案比這更舊就重抓（0 = 不重抓）")
    args = ap.parse_args()
    import pandas as pd
    import yfinance as yf

    pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{args.market}_pool.txt").read_text(
        encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    out = ROOT / "data_full" / args.market
    out.mkdir(parents=True, exist_ok=True)
    failed_p = out / "_failed.txt"
    failed = set() if args.retry_failed or not failed_p.exists() else set(failed_p.read_text().split())
    now = time.time()

    def stale(t: str) -> bool:
        p = out / f"{t.replace('^', '_')}.csv.gz"
        if not p.exists():
            return True
        return args.refresh_days > 0 and now - p.stat().st_mtime > args.refresh_days * 86400

    todo = [t for t in pool if t not in failed and stale(t)]
    print(f"{args.market}: 候選池 {len(pool)}、已有 {len(pool) - len(todo) - len(failed & set(pool))}、"
          f"失敗跳過 {len(failed & set(pool))}、要抓 {len(todo)}")
    started = time.monotonic()
    n_ok = 0
    for b in range(0, len(todo), BATCH):
        if time.monotonic() - started > args.budget_min * 60:
            print(f"WARN 超過 {args.budget_min} 分鐘，停在第 {b} 檔（下輪續抓）")
            break
        batch = todo[b:b + BATCH]
        for attempt in range(3):
            try:
                df = yf.download(batch, start="1995-01-01", auto_adjust=False, actions=False, group_by="ticker",
                                 threads=True, progress=False)
                break
            except Exception as exc:
                print(f"WARN 第 {b} 批失敗（{exc}），{10 * (attempt + 1)} 秒後重試", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                sub = df[t] if len(batch) > 1 else df
            except KeyError:
                failed.add(t)
                continue
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                failed.add(t)
                continue
            sub = sub.rename(columns={"Adj Close": "AdjClose"})[["Open", "High", "Low", "Close", "AdjClose", "Volume"]]
            sub.index = pd.to_datetime(sub.index).date
            sub.index.name = "Date"
            sub.to_csv(out / f"{t.replace('^', '_')}.csv.gz", float_format="%.6g", compression="gzip")
            n_ok += 1
        print(f"  {min(b + BATCH, len(todo))}/{len(todo)}  成功累計 {n_ok}、失敗累計 {len(failed)}", flush=True)
        time.sleep(2)
    failed_p.write_text("\n".join(sorted(failed)) + "\n")
    have = len(list(out.glob("*.csv.gz")))
    (out / "_status.txt").write_text(f"{date.today()} 候選池 {len(pool)}、有數據 {have}、失敗 {len(failed)}\n")
    print(f"完成：本輪成功 {n_ok}；目錄共有 {have} 檔、失敗名單 {len(failed)}")
    missing = [t for t in pool if t not in failed and stale(t)]
    sys.exit(0 if not missing else 3)     # 3 = 還沒抓完（下一步不要跑回測）


if __name__ == "__main__":
    main()
