#!/usr/bin/env python3
# =============================================================================
# IBKR 波動率與利率資料匯出（在 GCP VM 上跑，VM 需已開著登入的 IB Gateway / TWS）
# -----------------------------------------------------------------------------
# 用途：MOVE / VIX 特徵工程與回測的資料源（GitHub Actions 抓 Yahoo 會被 429 限流）。
#
# 抓取（日線，能抓多長抓多長，已有 CSV 則只補新資料）：
#   MOVE      ICE BofA MOVE 指數 —— IBKR 不一定有，先用合約搜尋確認，沒有就略過
#   VIX VIX3M CBOE 股市隱含波動率（VIX3M 用來算期限結構）
#   TNX       CBOE 10 年期殖利率指數（數值 = 殖利率 × 10）
#   TLT IEF   價格 + 選擇權隱含波動率（MOVE 的替代指標）+ 歷史波動率
#   ZN ZB     10 年 / 30 年公債期貨（連續合約）
#   NQ        那斯達克 100 期貨（連續合約，MNQ 回測用；NQ 歷史比 MNQ 長）
#   XAUUSD    倫敦金現貨（中間價）
# 任何一檔失敗（例如沒訂閱該行情）只印警告，其他照抓。
#
# 用法（VM 上）：
#   pip install ib_async
#   python3 scripts/ibkr_vol_export.py --probe            # 只搜尋 MOVE 等合約，不下載
#   python3 scripts/ibkr_vol_export.py                    # 全部下載到 data/vol/
#   python3 scripts/ibkr_vol_export.py --port 4002        # IB Gateway 模擬帳戶
# 連線參數也可用環境變數：IB_HOST、IB_PORT（預設 4001 = Gateway 真實帳戶）、IB_CLIENT_ID。
# clientId 預設 77，避免和交易程式的連線撞號。只讀取行情，不會下單。
# =============================================================================
import argparse
import csv
import os
import sys
from datetime import date, datetime

try:
    from ib_async import IB, Commodity, ContFuture, Index, Stock
except ImportError:  # 舊環境可能只裝了 ib_insync（API 相同）
    from ib_insync import IB, Commodity, ContFuture, Index, Stock

FIELDS = ["date", "open", "high", "low", "close", "volume"]

# (檔名, 合約建構, whatToShow, 說明)
SERIES = [
    ("vix", lambda: Index("VIX", "CBOE", "USD"), "TRADES", "VIX"),
    ("vix3m", lambda: Index("VIX3M", "CBOE", "USD"), "TRADES", "VIX 3 個月"),
    ("tnx", lambda: Index("TNX", "CBOE", "USD"), "TRADES", "10 年期殖利率 ×10"),
    ("tlt", lambda: Stock("TLT", "SMART", "USD"), "ADJUSTED_LAST", "TLT 還原價"),
    ("tlt_iv", lambda: Stock("TLT", "SMART", "USD"), "OPTION_IMPLIED_VOLATILITY", "TLT 30 天隱含波動率"),
    ("tlt_hv", lambda: Stock("TLT", "SMART", "USD"), "HISTORICAL_VOLATILITY", "TLT 30 天歷史波動率"),
    ("ief_iv", lambda: Stock("IEF", "SMART", "USD"), "OPTION_IMPLIED_VOLATILITY", "IEF 30 天隱含波動率"),
    ("zn", lambda: ContFuture("ZN", "CBOT", currency="USD"), "TRADES", "10 年公債期貨"),
    ("zb", lambda: ContFuture("ZB", "CBOT", currency="USD"), "TRADES", "30 年公債期貨"),
    ("nq", lambda: ContFuture("NQ", "CME", currency="USD"), "TRADES", "那斯達克 100 期貨"),
]


def read_existing(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k, "") for k in FIELDS})


def duration_for(existing):
    """已有資料只補最近一段；沒有就抓最長。IB 日線可用年為單位。"""
    if not existing:
        return "30 Y"
    last = datetime.strptime(max(existing), "%Y-%m-%d").date()
    days = (date.today() - last).days + 10
    return f"{days} D" if days < 365 else f"{days // 365 + 1} Y"


def fetch(ib, contract, what, duration):
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr=duration, barSizeSetting="1 day",
        whatToShow=what, useRTH=True, formatDate=1, timeout=120)
    out = {}
    for b in bars or []:
        d = b.date if isinstance(b.date, date) else b.date.date()
        out[d.isoformat()] = {"date": d.isoformat(), "open": b.open, "high": b.high,
                              "low": b.low, "close": b.close,
                              "volume": "" if b.volume in (None, -1) else b.volume}
    return out


def probe(ib):
    """搜尋 MOVE 相關合約；回傳可用的 MOVE 合約或 None。"""
    print("== 合約搜尋：MOVE ==")
    found = None
    for desc in ib.reqMatchingSymbols("MOVE") or []:
        c = desc.contract
        print(f"  {c.symbol:<8} {c.secType:<5} {c.primaryExchange or c.exchange:<10} {c.currency}")
        if c.secType == "IND" and c.symbol.upper() == "MOVE":
            found = c
    if found is None:
        for exch in ("ICE", "NYSE", "CBOE", "SMART"):
            try:
                q = ib.qualifyContracts(Index("MOVE", exch, "USD"))
                if q:
                    found = q[0]
                    break
            except Exception:  # noqa: BLE001
                continue
    print("  → MOVE：" + (f"找到 {found.symbol}@{found.exchange}" if found else "IBKR 沒有 MOVE，改用 TLT/IEF 隱含波動率當替代"))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("IB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("IB_PORT", "4001")))
    ap.add_argument("--client-id", type=int, default=int(os.environ.get("IB_CLIENT_ID", "77")))
    ap.add_argument("--out", default="data/vol")
    ap.add_argument("--probe", action="store_true", help="只搜尋合約，不下載")
    ap.add_argument("--only", nargs="*", help="只抓這些檔名（例：vix tlt_iv）")
    args = ap.parse_args()

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=20)
    except (OSError, TimeoutError) as e:
        sys.exit(f"連不上 IB Gateway {args.host}:{args.port}：{e}\n"
                 "確認 Gateway 已登入、API 已啟用（設定 → API → Enable ActiveX and Socket Clients），"
                 "埠號正確（Gateway 真實 4001 / 模擬 4002；TWS 真實 7496 / 模擬 7497）。")
    ib.reqMarketDataType(1)
    print(f"已連線 {args.host}:{args.port}（clientId {args.client_id}，唯讀）")

    move = probe(ib)
    if args.probe:
        ib.disconnect()
        return

    series = list(SERIES)
    if move is not None:
        series.insert(0, ("move", lambda: move, "TRADES", "MOVE"))
    if args.only:
        series = [s for s in series if s[0] in args.only]

    os.makedirs(args.out, exist_ok=True)
    summary, failed = [], []
    for name, mk, what, label in series:
        path = os.path.join(args.out, f"{name}.csv")
        rows = read_existing(path)
        try:
            contract = mk()
            if contract.conId == 0:
                ib.qualifyContracts(contract)
            dur = duration_for(rows)
            try:
                new = fetch(ib, contract, what, dur)
            except Exception:  # noqa: BLE001 — 有些資料類型不接受太長的期間，縮短重試
                if not dur.endswith("Y"):
                    raise
                new = fetch(ib, contract, what, "10 Y")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ {name}（{label}）失敗：{e}")
            failed.append(name)
            continue
        if not new:
            print(f"⚠️ {name}（{label}）沒有資料（可能缺行情訂閱）")
            failed.append(name)
            continue
        rows.update(new)
        write_rows(path, rows)
        first, last = min(rows), max(rows)
        summary.append((name, label, what, first, last, len(rows)))
        print(f"✅ {name:<7} {first} ～ {last}  {len(rows):>6} 筆  +{len(new)}")
        ib.sleep(2)  # IB 歷史資料有節流限制

    ib.disconnect()
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write("# 波動率與利率日線（IBKR）\n\n"
                f"由 `scripts/ibkr_vol_export.py` 於 {datetime.now():%Y-%m-%d %H:%M} 產生。"
                "資料來自 IBKR，僅供個人研究使用。\n\n"
                "| 檔案 | 內容 | IB whatToShow | 起 | 迄 | 筆數 |\n|---|---|---|---|---|---|\n")
        for name, label, what, first, last, n in summary:
            f.write(f"| `{name}.csv` | {label} | {what} | {first} | {last} | {n} |\n")
        if move is None:
            f.write("\nIBKR 沒有 MOVE 指數，以 `tlt_iv.csv` / `ief_iv.csv`（美債 ETF 選擇權隱含波動率）替代。\n")
        if failed:
            f.write(f"\n這次失敗：{', '.join(failed)}（多半是缺該市場的行情訂閱）。\n")
    sys.exit(1 if not summary else 0)


if __name__ == "__main__":
    main()
