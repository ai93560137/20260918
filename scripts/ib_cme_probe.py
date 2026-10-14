#!/usr/bin/env python3
"""[R183] 測試 IB 延遲行情攞唔攞到富途持倉嘅 CME 合約報價（只讀：唔落單、唔改單）。

喺 ib-data VM（IB Gateway paper 4002）由使用者用瀏覽器 SSH 跑：
    python3 ib_cme_probe.py            # 預設 5 張合約
    python3 ib_cme_probe.py --port 4002 --client-id 53

印出每張合約嘅 bid／ask／last／close 同行情類別（1 即時、3 延遲、4 延遲凍結）。
目的係確認之後每 15 分鐘抓報價（ib_cme_quotes）值唔值得做；呢個腳本本身唔寫檔、唔推送。
clientId 53：VM 上已用 17、23、24、31、41、77。
"""
import argparse
import math

CONTRACTS = [  # (標籤, 種類, 參數)
    ("ES2612", "FUT", dict(symbol="ES", lastTradeDateOrContractMonth="202612")),
    ("MES2612", "FUT", dict(symbol="MES", lastTradeDateOrContractMonth="202612")),
    ("EW2610 P7750", "FOP", dict(symbol="ES", lastTradeDateOrContractMonth="20261030", strike=7750, right="P", tradingClass="EW")),
    ("EX3 10/16 C7830", "FOP", dict(symbol="MES", lastTradeDateOrContractMonth="20261016", strike=7830, right="C", tradingClass="EX3")),
    ("EX3 10/16 P7830", "FOP", dict(symbol="MES", lastTradeDateOrContractMonth="20261016", strike=7830, right="P", tradingClass="EX3")),
]


def num(x):
    return x if isinstance(x, (int, float)) and not math.isnan(x) and x > 0 else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=53)
    ap.add_argument("--wait", type=float, default=8, help="等報價秒數")
    a = ap.parse_args()
    from ib_insync import IB, Future, FuturesOption
    ib = IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20, readonly=True)
    ib.reqMarketDataType(4)                     # 延遲凍結：冇訂閱用延遲，休市用最後值
    rows = []
    for label, kind, kw in CONTRACTS:
        c = (Future(exchange="CME", currency="USD", **kw) if kind == "FUT"
             else FuturesOption(exchange="CME", currency="USD", **kw))
        try:
            q = ib.qualifyContracts(c)
        except Exception as e:                  # noqa: BLE001
            q = []
            print(f"{label}: qualify 例外 {e!r}")
        if not q:
            print(f"{label}: 搵唔到合約（qualify 失敗）")
            continue
        rows.append((label, c, ib.reqMktData(c, "", False, False)))
    ib.sleep(a.wait)
    print(f"{'合約':<18}{'localSymbol':<22}{'類別':>4}{'bid':>10}{'ask':>10}{'last':>10}{'close':>10}")
    for label, c, t in rows:
        print(f"{label:<18}{c.localSymbol:<22}{t.marketDataType:>4}"
              + "".join(f"{(num(v) or 0):>10.2f}" for v in (t.bid, t.ask, t.last, t.close)))
        ib.cancelMktData(c)
    ib.disconnect()
    print("類別：1 即時、2 凍結、3 延遲、4 延遲凍結；0.00 即係冇數。只讀，冇落單。")


if __name__ == "__main__":
    main()
