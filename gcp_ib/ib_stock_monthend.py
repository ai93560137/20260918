#!/usr/bin/env python3
"""IBKR 股票收市／開市覆核數據——ib-data VM 月底自動核對用的「固定複本」。2026-10-31
來源：claude/stock-research-k9nzau 的 scripts/ib_stock_verify.py（2026-09-25 版）；由 gcp_ib/run_monthend_closes.sh 呼叫，
不直接執行別的分支。需求說明與交付格式：該分支 stock_research/IBKR_DATA_REQUEST.md。
與原版不同處：--req／--out／--suffix 參數；readonly 連線；預設 clientId 61（不與 17/23/24/31/32/41/43/45/55/77 撞）；
已有 ok 但未有下一交易日的列會重抓（月底後太早跑也安全）；連不到 Gateway 時以代碼 3 結束並寫清原因。
2026-10-31 修：connect 唔做啟動同步（fetchFields=StartupFetchNONE；週六維護時持倉／戶口同步逾時令 connect 失敗）；
TCP 連唔到 vs 握手／同步逾時分開報；ib_insync 日誌嘅戶口號換成 <acct>。

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
import asyncio
import csv
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "analysis" / "tt_all" / "ibkr_request.csv"
OUT = ROOT / "data_stock_ibkr"
MAX_FAIL_STREAK = 8
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


ACCT_RE = re.compile(r"\b(?:DU|DF|DI|U|F|I)\d{5,}\b")   # IB 戶口號（例如 DU1234567、U1234567）


class _RedactAcct(logging.Filter):
    """ib_insync 自己的日誌會印戶口號（例如 account updates for DU… timed out）→ 換成 <acct>，日誌會同步去 /srv/ibshare。"""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = ACCT_RE.sub("<acct>", record.getMessage())
        record.args = ()
        return True


def quiet_ib_logs() -> None:
    lg = logging.getLogger("ib_insync")
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s ib_insync %(levelname)s %(message)s"))
    h.addFilter(_RedactAcct())
    lg.handlers[:] = [h]
    lg.propagate = False
    lg.setLevel(logging.WARNING)


def connect_ib(ib, port: int, client_id: int) -> None:
    """只讀連線，唔做啟動同步（持倉／戶口／成交）：週末 IB 伺服器維護時，啟動同步會逾時令 connect() 失敗，
    而核對收市價根本唔需要嗰啲資料。舊版 ib_insync（冇 fetchFields）就退而求其次：timeout 加長到 120 秒。"""
    try:
        from ib_insync import StartupFetchNONE  # ib_insync ≥ 0.9.86
    except ImportError:
        StartupFetchNONE = None
    if StartupFetchNONE is not None:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=30, readonly=True, fetchFields=StartupFetchNONE)
    else:
        log("⚠️ ib_insync 版本冇 fetchFields，改用 timeout=120（啟動同步可能慢）")
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=120, readonly=True)


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
    ap.add_argument("--client-id", type=int, default=61)
    ap.add_argument("--req", default=None, help="請求檔（預設 analysis/tt_all/ibkr_request.csv）")
    ap.add_argument("--out", default=None, help="輸出資料夾（預設 data_stock_ibkr）")
    ap.add_argument("--suffix", default="", help="輸出檔名後綴，例如 _nortrh → au_<日>_nortrh.csv")
    ap.add_argument("--no-rth", action="store_true", help="useRTH=False：日線含收市競價（2026-09 澳洲 4 檔小型股 IB 與 Yahoo 差 1–4.6%，懷疑是 RTH 日線少了尾盤競價；下月澳洲用此旗標對照）")
    args = ap.parse_args()
    global REQ, OUT
    if args.req:
        REQ = Path(args.req)
    if args.out:
        OUT = Path(args.out)
    quiet_ib_logs()
    from ib_insync import IB
    ib = IB()
    try:
        connect_ib(ib, args.port, args.client_id)
    except (ConnectionRefusedError, ConnectionResetError) as exc:
        log(f"❌ TCP 連唔到 IB Gateway 127.0.0.1:{args.port}（{type(exc).__name__}）——Gateway 冇行緊或者未開 API 埠；"
            "睇 health.txt 有冇 java／4002 LISTEN")
        sys.exit(3)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        log(f"❌ 連到 4002 但 API 握手／啟動同步逾時（{ACCT_RE.sub('<acct>', repr(exc))}）——"
            "週末或深夜 IB 伺服器維護時常見，遲啲排程會自動再試；如果平日亦咁，多半卡喺免責聲明"
            "（AGENTIC.md「IB Gateway 重啟後卡在免責聲明」，用 VNC 按接受）")
        sys.exit(3)
    except Exception as exc:  # noqa: BLE001
        log(f"❌ 連 IB Gateway 失敗（{ACCT_RE.sub('<acct>', repr(exc))}）")
        sys.exit(3)
    ib.reqMarketDataType(3)
    jobs = read_request(args.market)
    log(f"job={args.job} 市場 {sorted({m for m, _ in jobs})}，共 {sum(len(v) for v in jobs.values())} 檔")
    for (mk, d), tickers in sorted(jobs.items()):
        path = OUT / f"{mk}_{d}{args.suffix}.csv"
        rows = load_done(path)
        streak = 0
        todo = tickers[:1] if args.job == "probe" else [t for t in tickers if rows.get(t, {}).get("status") != "ok" or not rows[t].get("next_date")]
        log(f"[{mk}] {d}：{len(tickers)} 檔，待抓 {len(todo)}")
        for k, t in enumerate(todo, 1):
            r = fetch_one(ib, mk, t, d, args.pace, rth=not args.no_rth)
            failed = r["status"] in ("no_data", "error") and not r.get("ib_close")
            if r["status"] in ("no_data", "error") and rows.get(t, {}).get("status") == "ok":
                log(f"  {t} → {r['status']}（保留上次 ok 結果）")
                r = rows[t]
            rows[t] = r
            # 一連串空 K 線／錯誤 = 多半係 IB 歷史數據伺服器維護（週末），唔好逐檔等 60 秒等幾粒鐘
            streak = streak + 1 if failed else 0
            if streak >= MAX_FAIL_STREAK:
                save(path, rows)
                log(f"⛔ 連續 {streak} 檔冇數據／出錯，疑似 IB 歷史數據伺服器維護；今次停，下次排程再試")
                ib.disconnect()
                sys.exit(5)
            if args.job == "probe" or k % 20 == 0 or k == len(todo):
                save(path, rows)
            if r["status"] != "ok":
                log(f"  {t} → {r['status']} {r['note']}")
            elif args.job == "probe":
                log(f"  {t} → ok 收市 {r['ib_close']} 下一日 {r.get('next_date') or '（未有）'} 開市 {r.get('ib_next_open') or '—'}")
        save(path, rows)
        n_ok = sum(1 for r in rows.values() if r.get("status") == "ok")
        n_next = sum(1 for r in rows.values() if r.get("status") == "ok" and r.get("next_date"))
        log(f"[{mk}] {d}{args.suffix} 完成：ok {n_ok}／{len(rows)}，有下一交易日 {n_next}")
    ib.disconnect()


if __name__ == "__main__":
    main()
