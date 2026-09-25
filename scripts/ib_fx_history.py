#!/usr/bin/env python3
"""IBKR 外匯歷史數據採集（給雲垂分支的 GCP VM 跑；沙盒連不到 IB Gateway）。2026-09-25
需求說明與交付格式：forex_research/IBKR_DATA_REQUEST.md（本分支 claude/forex-data-testing-w4q3m2）。

    pip install ib_insync
    python3 scripts/ib_fx_history.py --port 4002 --job iv          # P0：CME 外匯期貨隱含／歷史波動日線（能拉多深拉多深）
    python3 scripts/ib_fx_history.py --port 4002 --job fut         # P0：CME 外匯期貨連續合約日線（TRADES、BID_ASK）
    python3 scripts/ib_fx_history.py --port 4002 --job spot5m      # P1：IDEALPRO 現貨 5 分鐘 BID_ASK（預設 2 年）
    python3 scripts/ib_fx_history.py --port 4002 --job probe       # 先跑：只測每種請求能不能拿到、回傳幾根、有沒有權限錯誤

輸出 data_forex_ibkr/<檔名>.csv.gz（UTC 時間、可續抓：已有的檔會從最早一筆往前補）與 data_forex_ibkr/_status.txt。
節流：IB 歷史數據每 10 分鐘最多 60 個請求；本腳本每個請求間隔 11 秒、同一合約同一種數據連續 3 次空回應就停。
只讀：不下單、不改帳戶；帳密只在 VM 的 IBC config.ini。
"""
import argparse
import gzip
import io
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_ibkr"
# CME 外匯期貨：IB symbol（不是 6E 這種 Globex 代碼）；連續合約由 ContFuture 解析
FUTS = {"EUR": "EUR", "JPY": "JPY", "GBP": "GBP", "CHF": "CHF", "AUD": "AUD", "CAD": "CAD", "NZD": "NZD", "MXN": "MXP"}
SPOTS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
PACE = 11.0                                        # 秒；60 個請求／10 分鐘的上限之內


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(OUT / "_status.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_existing(path: Path):
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = f.read().splitlines()
    return rows if len(rows) > 1 else None


def write_rows(path: Path, header: str, rows: dict) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(header + "\n")
        for k in sorted(rows):
            f.write(rows[k] + "\n")


def fetch_backwards(ib, contract, what: str, bar: str, duration: str, path: Path, header: str, max_req: int, use_rth: bool) -> int:
    """從最新往前一段一段抓，直到 IB 回空／出錯連續 3 次或到 max_req；已有檔就從其最早一筆之前接著抓。"""
    from ib_insync import util
    rows = {}
    old = read_existing(path)
    end = ""                                       # "" = 現在
    if old:
        for line in old[1:]:
            rows[line.split(",")[0]] = line
        first = min(rows)
        end = (datetime.fromisoformat(first) - timedelta(seconds=1)).strftime("%Y%m%d %H:%M:%S") + " UTC"
        log(f"  {path.name}：已有 {len(rows)} 筆，從 {first} 之前續抓")
    empty, n_req, added = 0, 0, 0
    while n_req < max_req and empty < 3:
        try:
            bars = ib.reqHistoricalData(contract, endDateTime=end, durationStr=duration, barSizeSetting=bar, whatToShow=what,
                                        useRTH=use_rth, formatDate=2, keepUpToDate=False, timeout=90)
        except Exception as exc:  # noqa: BLE001
            log(f"  {path.name} 請求失敗：{exc!r}")
            bars = []
        n_req += 1
        if not bars:
            empty += 1
            log(f"  {path.name}：空回應（第 {empty} 次），end={end or 'now'}")
            time.sleep(PACE)
            continue
        empty = 0
        df = util.df(bars)
        new = 0
        for r in df.itertuples():
            t = r.date if isinstance(r.date, datetime) else datetime.combine(r.date, datetime.min.time())
            if t.tzinfo is not None:
                t = t.astimezone(timezone.utc).replace(tzinfo=None)
            key = t.strftime("%Y-%m-%d %H:%M:%S")
            if key not in rows:
                rows[key] = f"{key},{r.open},{r.high},{r.low},{r.close},{r.volume},{getattr(r, 'barCount', '')}"
                new += 1
        added += new
        first_t = min(rows)
        log(f"  {path.name}：+{new} 筆（共 {len(rows)}），最早 {first_t}")
        write_rows(path, header, rows)
        if new == 0:
            empty += 1
        end = (datetime.fromisoformat(first_t) - timedelta(seconds=1)).strftime("%Y%m%d %H:%M:%S") + " UTC"
        time.sleep(PACE)
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--job", choices=["probe", "iv", "fut", "spot5m"], required=True)
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--years", type=float, default=2.0, help="spot5m 回溯幾年")
    ap.add_argument("--max-req", type=int, default=400, help="每個序列最多幾個請求（iv／fut 每個請求 1 年）")
    ap.add_argument("--client-id", type=int, default=23)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    from ib_insync import IB, ContFuture, Forex
    ib = IB()
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=30)
    ib.reqMarketDataType(3)                        # 延遲數據也可；歷史數據權限由 IB 決定，錯誤會記進 _status.txt
    log(f"== job={args.job} 連線 port {args.port}")
    header = "Time,Open,High,Low,Close,Volume,BarCount"

    if args.job in ("probe", "iv", "fut"):
        for ccy, sym in FUTS.items():
            if args.symbols and ccy not in args.symbols:
                continue
            c = ContFuture(sym, "CME", "USD")
            try:
                ib.qualifyContracts(c)
            except Exception as exc:  # noqa: BLE001
                log(f"{ccy}：ContFuture {sym} 解析失敗 {exc!r}")
                continue
            log(f"{ccy}：{c.localSymbol} conId {c.conId}")
            whats = {"probe": ["TRADES", "BID_ASK", "OPTION_IMPLIED_VOLATILITY", "HISTORICAL_VOLATILITY"],
                     "iv": ["OPTION_IMPLIED_VOLATILITY", "HISTORICAL_VOLATILITY"], "fut": ["TRADES", "BID_ASK"]}[args.job]
            for what in whats:
                if args.job == "probe":
                    try:
                        bars = ib.reqHistoricalData(c, "", "1 M", "1 day", what, False, 2, timeout=60)
                        log(f"  probe {ccy} {what} 1 day × 1 M → {len(bars)} 根" + (f"（最早 {bars[0].date}）" if bars else ""))
                    except Exception as exc:  # noqa: BLE001
                        log(f"  probe {ccy} {what} 失敗：{exc!r}")
                    time.sleep(PACE)
                    continue
                path = OUT / f"fut_{ccy}_D1_{what.lower()}.csv.gz"
                fetch_backwards(ib, c, what, "1 day", "1 Y", path, header, args.max_req, use_rth=False)
    if args.job in ("probe", "spot5m"):
        for pair in SPOTS:
            if args.symbols and pair not in args.symbols:
                continue
            c = Forex(pair)
            ib.qualifyContracts(c)
            if args.job == "probe":
                for what in ("MIDPOINT", "BID_ASK"):
                    try:
                        bars = ib.reqHistoricalData(c, "", "1 W", "5 mins", what, False, 2, timeout=60)
                        log(f"  probe {pair} {what} 5 mins × 1 W → {len(bars)} 根")
                    except Exception as exc:  # noqa: BLE001
                        log(f"  probe {pair} {what} 失敗：{exc!r}")
                    time.sleep(PACE)
                continue
            path = OUT / f"spot_{pair}_M5_bid_ask.csv.gz"
            n_weeks = int(args.years * 53)
            fetch_backwards(ib, c, "BID_ASK", "5 mins", "1 W", path, header, n_weeks, use_rth=False)
    ib.disconnect()
    log("== 完成")


if __name__ == "__main__":
    main()
