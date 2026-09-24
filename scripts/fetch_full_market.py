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
# 收市時間（當地）+ 30 分鐘緩衝：還沒到就丟掉「今天」那根（盤中抓到的是未收市的半根，2026-09-23 美股 09:40 ET 抓到過）
CLOSE = {"hk": ("Asia/Hong_Kong", 16, 40), "jp": ("Asia/Tokyo", 16, 0), "us": ("America/New_York", 16, 30),
         # 樣本外驗證新市場（OOS_VALIDATION.md）：台灣 13:30、韓國 15:30、澳洲 16:10（收市競價）收市
         "tw": ("Asia/Taipei", 14, 0), "kr": ("Asia/Seoul", 16, 0), "au": ("Australia/Sydney", 16, 40),
         "ca": ("America/Toronto", 16, 30), "in": ("Asia/Kolkata", 16, 0), "sg": ("Asia/Singapore", 17, 40)}


def last_complete_cutoff(market: str) -> date:
    """回傳「可以保留的最後日期」（含）：當地已過收市 + 緩衝 → 今天；否則 → 昨天。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz, h, mi = CLOSE[market]
    now = datetime.now(ZoneInfo(tz))
    today = now.date()
    return today if (now.hour, now.minute) >= (h, mi) else today - timedelta(days=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=list(CLOSE))
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--refresh-days", type=int, default=0, help="檔案比這更舊就重抓（0 = 不重抓）")
    ap.add_argument("--refresh-all", action="store_true", help="全部重抓（例如之前在盤中抓到半根）")
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
        if not p.exists() or args.refresh_all:
            return True
        return args.refresh_days > 0 and now - p.stat().st_mtime > args.refresh_days * 86400

    todo = [t for t in pool if t not in failed and stale(t)]
    print(f"{args.market}: 候選池 {len(pool)}、已有 {len(pool) - len(todo) - len(failed & set(pool))}、"
          f"失敗跳過 {len(failed & set(pool))}、要抓 {len(todo)}")
    cutoff = last_complete_cutoff(args.market)
    print(f"只保留 {cutoff}（含）以前的日線（之後的是未收市的半根）")
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
            sub = sub[sub.index <= cutoff]
            sub.to_csv(out / f"{t.replace('^', '_')}.csv.gz", float_format="%.6g", compression="gzip")
            n_ok += 1
        print(f"  {min(b + BATCH, len(todo))}/{len(todo)}  成功累計 {n_ok}、失敗累計 {len(failed)}", flush=True)
        time.sleep(2)
    failed_p.write_text("\n".join(sorted(failed)) + "\n")
    have = len(list(out.glob("*.csv.gz")))
    (out / "_status.txt").write_text(f"{date.today()} 候選池 {len(pool)}、有數據 {have}、失敗 {len(failed)}\n")
    print(f"完成：本輪成功 {n_ok}；目錄共有 {have} 檔、失敗名單 {len(failed)}")
    args.refresh_all = False
    missing = [t for t in pool if t not in failed and stale(t)]
    sys.exit(0 if not missing else 3)     # 3 = 還沒抓完（下一步不要跑回測）


if __name__ == "__main__":
    main()
