#!/usr/bin/env python3
"""每日抓 ZQ（30 天聯邦基金期貨）最近幾個月合約的日線結算，追加到 data_forex_ibkr/zq/zq_daily.csv；給雲垂 VM 的 cron。只讀。
協議：forex_research/FX_FOMC_DRIFT_FORWARD.md。

    # crontab（UTC；平日 23:30，CME 結算後）：
    # 30 23 * * 1-5  cd $HOME/20260918 && python3 scripts/ib_zq_daily.py --push >> data_forex_ibkr/zq/zq_daily.log 2>&1

    python3 scripts/ib_zq_daily.py [--port 4002] [--client-id 45] [--months 4] [--push]
每次抓「本月＋之後 N−1 個月」各合約最近 10 天日線（IB 期貨日線 Close＝結算價），按 (date, contract) 去重合併；--push 則 commit 並推回本分支。
"""
import argparse
import csv
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_ibkr" / "zq" / "zq_daily.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=45)
    ap.add_argument("--months", type=int, default=4)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    from ib_insync import IB, Future
    ib = IB(); ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20)
    today = date.today()
    rows = {}
    if OUT.exists():
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            rows[(r["date"], r["contract"])] = r
    for k in range(a.months):
        y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        ym = f"{y}{m:02d}"
        c = Future("ZQ", lastTradeDateOrContractMonth=ym, exchange="CBOT", currency="USD")
        try:
            if not ib.qualifyContracts(c):
                print(f"{ym}: qualify 失敗"); continue
            bars = ib.reqHistoricalData(c, endDateTime="", durationStr="10 D", barSizeSetting="1 day", whatToShow="TRADES", useRTH=False, formatDate=2)
        except Exception as e:
            print(f"{ym}: 例外 {e!r}"); continue
        for b in bars:
            rows[(str(b.date), ym)] = {"date": str(b.date), "contract": ym, "close": f"{b.close:.4f}", "volume": int(b.volume), "fetched_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
        print(f"{ym}: {len(bars)} 根，最後 {bars[-1].date if bars else '-'} close {bars[-1].close if bars else '-'}")
        time.sleep(3)
    ib.disconnect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "contract", "close", "volume", "fetched_utc"])
        w.writeheader(); w.writerows(sorted(rows.values(), key=lambda r: (r["date"], r["contract"])))
    print(f"zq_daily.csv 共 {len(rows)} 列")
    if a.push:
        subprocess.run(["git", "-C", str(ROOT), "config", "rebase.autostash", "true"], check=False)
        subprocess.run(["git", "-C", str(ROOT), "pull", "--rebase", "-q", "origin", "claude/dazzling-curie-f3xzb8"], check=False)
        subprocess.run(["git", "-C", str(ROOT), "add", str(OUT)], check=False)
        r = subprocess.run(["git", "-C", str(ROOT), "commit", "-q", "-m", "data(zq): ZQ 每日結算"], capture_output=True, text=True)
        if r.returncode == 0:
            for i in range(4):
                if subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "claude/dazzling-curie-f3xzb8"]).returncode == 0:
                    print("已推送"); break
                time.sleep(2 ** (i + 1))
        else:
            print("沒有新列，不推")


if __name__ == "__main__":
    main()
