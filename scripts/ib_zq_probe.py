#!/usr/bin/env python3
"""IB 試拉 30 天聯邦基金期貨 ZQ（CBOT）：列出 IB 還認得的到期月（含已到期），逐合約拉日線，另拉連續合約看深度。只讀。
登記：forex_research/FOMC_DATA_REQUEST.md 第 3 節。

    python3 scripts/ib_zq_probe.py --out data_forex_ibkr/zq --client-id 43 [--port 4002]
"""
import argparse
import csv
import gzip
import time
from datetime import date
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=43)
    ap.add_argument("--pace", type=float, default=11.0, help="每個歷史請求間隔秒（IB 節流）")
    ap.add_argument("--months", nargs="*", default=[], help="明示到期月 YYYYMM（含已到期，includeExpired），例如 202501 202502 … 202508；不給則用 reqContractDetails 列出的")
    a = ap.parse_args()
    from ib_insync import IB, ContFuture, Future
    a.out.mkdir(parents=True, exist_ok=True)
    ib = IB(); ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20)
    if a.months:
        cons = []
        for m in a.months:
            c = Future("ZQ", lastTradeDateOrContractMonth=m, exchange="CBOT", currency="USD", includeExpired=True)
            try:
                q = ib.qualifyContracts(c)
                if q:
                    cons.append(q[0]); print(f"  {m}: qualify 成功 {q[0].localSymbol}")
                else:
                    print(f"  {m}: qualify 失敗（IB 不再認得）")
            except Exception as e:
                print(f"  {m}: 例外 {e!r}")
    else:
        cds = ib.reqContractDetails(Future("ZQ", exchange="CBOT", currency="USD", includeExpired=True))
        cons = sorted((cd.contract for cd in cds), key=lambda c: c.lastTradeDateOrContractMonth)
    print(f"IB 認得 {len(cons)} 個 ZQ 合約：{cons[0].lastTradeDateOrContractMonth if cons else '-'} → {cons[-1].lastTradeDateOrContractMonth if cons else '-'}")
    status = [f"# ZQ 試拉 {date.today()}；IB 認得 {len(cons)} 個合約"]
    today = date.today().strftime("%Y%m%d")
    for c in cons:
        exp = c.lastTradeDateOrContractMonth[:8]
        end = "" if exp >= today else f"{exp} 23:59:59 US/Central"
        try:
            bars = ib.reqHistoricalData(c, endDateTime=end, durationStr="3 Y", barSizeSetting="1 day", whatToShow="TRADES", useRTH=False, formatDate=2)
        except Exception as e:
            bars = []; print(f"  {c.localSymbol} 例外 {e!r}")
        tag = exp[:6]
        if bars:
            with gzip.open(a.out / f"ZQ_{tag}.csv.gz", "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh); w.writerow(["Time", "Open", "High", "Low", "Close", "Volume"])
                for b in bars:
                    w.writerow([str(b.date), b.open, b.high, b.low, b.close, b.volume])
            line = f"{c.localSymbol} ({tag}): {len(bars)} 根 {bars[0].date} → {bars[-1].date}"
        else:
            line = f"{c.localSymbol} ({tag}): 無資料"
        print("  " + line); status.append(line)
        time.sleep(a.pace)
    try:
        cf = ContFuture("ZQ", exchange="CBOT", currency="USD"); ib.qualifyContracts(cf)
        bars = ib.reqHistoricalData(cf, endDateTime="", durationStr="20 Y", barSizeSetting="1 day", whatToShow="TRADES", useRTH=False, formatDate=2)
        if bars:
            with gzip.open(a.out / "ZQ_continuous_D1.csv.gz", "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh); w.writerow(["Time", "Open", "High", "Low", "Close", "Volume"])
                for b in bars:
                    w.writerow([str(b.date), b.open, b.high, b.low, b.close, b.volume])
        line = f"連續合約 ContFuture: {len(bars)} 根 {bars[0].date if bars else '-'} → {bars[-1].date if bars else '-'}（回溯調整價，只看深度）"
    except Exception as e:
        line = f"連續合約失敗 {e!r}"
    print(line); status.append(line)
    status.append("結算價核對：IB 日線 Close 是否等於 CME 結算，待人工對照最近 3 個合約各 20 天（CME 網站需瀏覽器）。")
    with open(a.out / "_status.txt", "a", encoding="utf-8") as fh:
        fh.write("\n".join(status) + "\n")
    ib.disconnect()


if __name__ == "__main__":
    main()
