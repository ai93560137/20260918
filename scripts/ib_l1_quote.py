#!/usr/bin/env python3
"""L1 前向測試的 IBKR 真實報價快照（給雲垂分支 GCP VM 的 cron 跑；只讀）。

    # crontab（UTC；週一至週五）：
    # 59 8  * * 1-5  cd <repo> && python3 scripts/ib_l1_quote.py --label 0859
    # 59 11 * * 1-5  cd <repo> && python3 scripts/ib_l1_quote.py --label 1159

在 08:59 與 11:59 UTC 各記一次 EURUSD IDEALPRO 的 bid／ask（即時報價（IDEALPRO 外匯通常免訂閱；--delayed 只作連線測試）），追加到 data_forex_ibkr/l1_quotes.csv。
用途：前向測試的「真實可成交點差」第二來源，與 Dukascopy M1 紙上成交對照。不下單。
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--label", required=True)
    ap.add_argument("--client-id", type=int, default=31)
    ap.add_argument("--delayed", action="store_true", help="用延遲報價（15 分鐘前；與 09:00／12:00 不對時，僅作連線測試）")
    args = ap.parse_args()
    from ib_insync import IB, Forex
    ib = IB()
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=20)
    ib.reqMarketDataType(3 if args.delayed else 1)
    c = Forex("EURUSD")
    ib.qualifyContracts(c)
    tk = ib.reqMktData(c, "", False, False)
    ib.sleep(5)
    bid, ask = tk.bid, tk.ask
    if not (bid and ask and bid == bid and ask == ask and bid > 0 and ask > 0):   # nan／0／None 一律當缺價
        bid, ask = "", ""
    ib.cancelMktData(c)
    ib.disconnect()
    f = ROOT / "data_forex_ibkr" / "l1_quotes.csv"
    f.parent.mkdir(exist_ok=True)
    new = not f.exists()
    with open(f, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["utc_time", "label", "bid", "ask", "spread_bp"])
        sp = (ask - bid) / ((ask + bid) / 2) * 1e4 if bid and ask else ""
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), args.label + ("_delayed" if args.delayed else ""), bid, ask, f"{sp:.3f}" if sp != "" else ""])
    print(args.label, bid, ask)


if __name__ == "__main__":
    main()
