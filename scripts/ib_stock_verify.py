#!/usr/bin/env python3
"""IBKR 股票收市／開市覆核數據（給雲垂分支的 GCP VM 跑；沙盒連不到 IB Gateway）。2026-09-25
需求說明與交付格式：stock_research/IBKR_DATA_REQUEST.md（本分支 claude/stock-research-k9nzau）。

    pip install ib_insync
    python3 scripts/ib_stock_verify.py --port 4002 --job probe                 # 先跑：每個市場各試 1 檔，看合約能不能解析、有沒有權限錯誤
    python3 scripts/ib_stock_verify.py --port 4002 --job closes                # P0：request 檔裡每檔的訊號日收市 + 下一交易日開市（1 day TRADES）
    python3 scripts/ib_stock_verify.py --port 4002 --job closes --market hk sg # 只跑某些市場
    python3 scripts/ib_stock_verify.py --port 4002 --job closes --market au --no-rth  # 日線含收市競價（澳洲對照用）

輸入 analysis/tt_all/ibkr_request.csv（欄位 market,ticker,signal_date；由鳥翔分支產生）。
輸出 data_stock_ibkr/<市場>_<訊號日>.csv（ticker,ib_symbol,exchange,currency,con_id,signal_date,ib_close,next_date,ib_next_open,ib_next_close,status,note）
與 data_stock_ibkr/_status.txt。可續抓：已有 status=ok 的列跳過。
節流：每個請求間隔 --pace 秒（預設 2.5；遇 pacing violation 自動等 60 秒重試）。只讀：不下單、不改帳戶。
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "analysis" / "tt_all" / "ibkr_request.csv"
OUT = ROOT / "data_stock_ibkr"
FIELDS = ["ticker", "ib_symbol", "exchange", "currency", "con_id", "signal_date", "ib_close", "next_date", "ib_next_open", "ib_next_close", "status", "note"]

# Yahoo 代號 → IB 合約（exchange, currency, symbol 轉換）
def to_ib(mk: str, t: str):
    if mk == "hk":
        return t[:-3].lstrip("0") or "0", "SEHK", "HKD"
    if mk == "sg":
        return t[:-3], "SGX", "SGD"
    if mk == "ca":
        return t[:-3].replace("-", "."), "TSE", "CAD"      # BAM-A.TO → BAM.A
    if mk == "au":
        return t[:-3], "ASX", "AUD"
    if mk == "us":
        return t.replace("-", " "), "SMART", "USD"        # BRK-B → BRK B
    if mk == "jp":
        return t[:-2], "TSEJ", "JPY"
    if mk == "in":
        return t[:-3], "NSE", "INR"                        # IB 一般不對非印度居民提供，預期失敗，交回錯誤訊息即可
    if mk == "tw":
        return t.rsplit(".", 1)[0], "TWSE", "TWD"          # IB 沒有台股，預期失敗
    if mk == "kr":
        return t[:-3], "KSE", "KRW"                        # 預期失敗
    raise ValueError(mk)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "_status.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_request(markets: list[str] | None) -> dict[tuple[str, str], list[str]]:
    jobs: dict[tuple[str, str], list[str]] = {}
    with open(REQ, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if markets and r["market"] not in markets:
                continue
            jobs.setdefault((r["market"], r["signal_date"]), []).append(r["ticker"])
    return jobs


def load_done(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["ticker"]: r for r in csv.DictReader(f)}


def save(path: Path, rows: dict[str, dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for t in sorted(rows):
            w.writerow({k: rows[t].get(k, "") for k in FIELDS})


def fetch_one(ib, mk: str, t: str, d: str, pace: float, rth: bool = True) -> dict:
    from ib_insync import Stock, util
    sym, exch, cur = to_ib(mk, t)
    row = {"ticker": t, "ib_symbol": sym, "exchange": exch, "currency": cur, "signal_date": d, "status": "", "note": ""}
    try:
        c = Stock(sym, exch, cur)
        q = ib.qualifyContracts(c)
        if not q or not c.conId:
            row["status"] = "no_contract"
            return row
        row["con_id"] = c.conId
        end = datetime.strptime(d, "%Y-%m-%d").strftime("%Y%m%d") + " 23:59:59"
        # 取訊號日前後：以訊號日 + 5 個日曆日為 end，抓 2 週日線，找訊號日與下一交易日
        end_dt = datetime.strptime(d, "%Y-%m-%d")
        end2 = (end_dt.replace(hour=23, minute=59, second=59)).strftime("%Y%m%d %H:%M:%S")
        bars = ib.reqHistoricalData(c, endDateTime="", durationStr="1 M", barSizeSetting="1 day", whatToShow="TRADES",
                                    useRTH=rth, formatDate=1, keepUpToDate=False, timeout=60)
        time.sleep(pace)
        if not bars:
            row["status"] = "no_data"
            return row
        df = util.df(bars)
        df["date"] = df["date"].astype(str).str[:10]
        dates = list(df["date"])
        if d not in dates:
            row["status"] = "no_data"
            row["note"] = f"IB 沒有 {d} 的日線（有 {dates[0]}~{dates[-1]}）"
            return row
        i = dates.index(d)
        row["ib_close"] = float(df.iloc[i]["close"])
        if i + 1 < len(df):
            row["next_date"] = dates[i + 1]
            row["ib_next_open"] = float(df.iloc[i + 1]["open"])
            row["ib_next_close"] = float(df.iloc[i + 1]["close"])
        row["status"] = "ok"
        _ = end, end2
    except Exception as exc:  # noqa: BLE001
        msg = repr(exc)
        row["status"] = "error"
        row["note"] = msg[:200]
        if "pacing" in msg.lower() or "162" in msg:
            log(f"  {t}: pacing／162，等 60 秒")
            time.sleep(60)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--job", choices=["probe", "closes"], required=True)
    ap.add_argument("--market", nargs="*", default=None)
    ap.add_argument("--pace", type=float, default=2.5)
    ap.add_argument("--client-id", type=int, default=24)
    ap.add_argument("--no-rth", action="store_true", help="useRTH=False：日線含收市競價（2026-09 澳洲 4 檔小型股 IB 與 Yahoo 差 1–4.6%，懷疑是 RTH 日線少了尾盤競價；下月澳洲用此旗標對照）")
    args = ap.parse_args()
    from ib_insync import IB
    ib = IB()
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=30)
    ib.reqMarketDataType(3)
    jobs = read_request(args.market)
    log(f"job={args.job} 市場 {sorted({m for m, _ in jobs})}，共 {sum(len(v) for v in jobs.values())} 檔")
    for (mk, d), tickers in sorted(jobs.items()):
        path = OUT / f"{mk}_{d}.csv"
        rows = load_done(path)
        todo = tickers[:1] if args.job == "probe" else [t for t in tickers if rows.get(t, {}).get("status") != "ok"]
        log(f"[{mk}] {d}：{len(tickers)} 檔，待抓 {len(todo)}")
        for k, t in enumerate(todo, 1):
            r = fetch_one(ib, mk, t, d, args.pace, rth=not args.no_rth)
            rows[t] = r
            if args.job == "probe" or k % 20 == 0 or k == len(todo):
                save(path, rows)
            if r["status"] != "ok":
                log(f"  {t} → {r['status']} {r['note']}")
            elif args.job == "probe":
                log(f"  {t} → ok 收市 {r['ib_close']} 下一日 {r['next_date']} 開市 {r['ib_next_open']}")
        save(path, rows)
        n_ok = sum(1 for r in rows.values() if r.get("status") == "ok")
        log(f"[{mk}] {d} 完成：ok {n_ok}／{len(rows)}")
    ib.disconnect()


if __name__ == "__main__":
    main()
