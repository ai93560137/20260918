#!/usr/bin/env python3
"""IBKR 新聞歷史採集（給雲垂分支的 GCP VM 跑；沙盒連不到 IB Gateway）。2026-09-25
需求說明與交付格式：research/news_trade/IBKR_NEWS_REQUEST.md（本分支 claude/pelosi-stock-tracking-f9f94g）。

    pip install ib_insync
    python3 scripts/ib_news_history.py --port 4002 --job probe        # 先跑：有哪些新聞源、每個源能不能拿到標題與全文、最早到哪
    python3 scripts/ib_news_history.py --port 4002 --job headlines    # P0：S&P 500 現任成分股的歷史新聞標題（能拉多深拉多深）
    python3 scripts/ib_news_history.py --port 4002 --job headlines --symbols AAPL MSFT   # 只抓指定代號
    python3 scripts/ib_news_history.py --port 4002 --job articles --max-articles 2000  # P1：抽樣下載全文

輸出 data_news_ibkr/：
  _status.txt                          每個請求的結果與錯誤碼（10276 = 沒有該新聞源的 API 權限）
  _providers.csv                       reqNewsProviders 的結果
  headlines/<MARKET>_<SYMBOL>.csv.gz   time,provider,article_id,headline（可續抓：從已有檔的最早一筆往前補）
  articles/<provider>/<article_id>.txt.gz
只讀：不下單、不改帳戶、不訂閱任何新聞源；帳密只在 VM 的 IBC config.ini。
"""
import argparse
import csv
import gzip
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_news_ibkr"
PACE = 2.0            # 秒；IB 沒有公布新聞請求的上限，保守一點
PER_REQ = 300         # reqHistoricalNews 單次上限
# probe 用的樣本：美、港、日、台各一檔，加一檔 ETF
PROBE = [("US", "AAPL", "SMART", "USD"), ("US", "SPY", "SMART", "USD"), ("HK", "700", "SEHK", "HKD"),
         ("JP", "7203", "TSEJ", "JPY"), ("TW", "2330", "TWSE", "TWD")]
ERRORS = []


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(OUT / "_status.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def on_error(req_id, code, msg, contract=None):  # IB 錯誤碼一律記下來，這是交回的重點
    if code in (2104, 2106, 2107, 2108, 2158):   # 連線狀態通知，不是錯誤
        return
    ERRORS.append((code, msg))
    log(f"  IB error {code}：{msg}" + (f"（{getattr(contract, 'symbol', '')}）" if contract else ""))


def ib_time(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S.0")


def sp500_current():
    """data/news/sp500_cik_map.csv 裡現任（end 空白）的成分股代號。"""
    path = ROOT / "data" / "news" / "sp500_cik_map.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return sorted({r["ticker"] for r in csv.DictReader(f) if not r.get("end")})


def read_headlines(path: Path) -> dict:
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {(r["provider"], r["article_id"]): r for r in csv.DictReader(f)}


def write_headlines(path: Path, rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "provider", "article_id", "headline"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: (r["time"], r["article_id"])))


def fetch_headlines(ib, conid: int, providers: str, path: Path, max_req: int) -> int:
    """從現在往前一段一段抓（每次最多 300 則），直到連續 3 次沒有新標題或到 max_req。"""
    rows = read_headlines(path)
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    if rows:
        end = datetime.fromisoformat(min(r["time"] for r in rows.values())) - timedelta(seconds=1)
        log(f"  {path.name}：已有 {len(rows)} 則，從 {end} 之前續抓")
    empty, added = 0, 0
    for _ in range(max_req):
        if empty >= 3:
            break
        try:
            news = ib.reqHistoricalNews(conid, providers, "", ib_time(end), PER_REQ)
        except Exception as exc:  # noqa: BLE001
            log(f"  {path.name} 請求失敗：{exc!r}")
            news = []
        time.sleep(PACE)
        new = 0
        for n in news or []:
            t = n.time if isinstance(n.time, datetime) else datetime.fromisoformat(str(n.time))
            if t.tzinfo is not None:
                t = t.astimezone(timezone.utc).replace(tzinfo=None)
            key = (n.providerCode, n.articleId)
            if key not in rows:
                rows[key] = {"time": t.strftime("%Y-%m-%d %H:%M:%S"), "provider": n.providerCode,
                             "article_id": n.articleId, "headline": n.headline}
                new += 1
        if not new:
            empty += 1
            log(f"  {path.name}：沒有新標題（第 {empty} 次），end={end}")
            end -= timedelta(days=30)  # 可能只是這段時間沒新聞：往前跳一個月再試
            continue
        empty = 0
        added += new
        write_headlines(path, rows)
        first = min(r["time"] for r in rows.values())
        log(f"  {path.name}：+{new} 則（共 {len(rows)}），最早 {first}")
        end = datetime.fromisoformat(first) - timedelta(seconds=1)
    return added


def stock(ib, market, sym, exch, ccy):
    from ib_insync import Stock
    c = Stock(sym, exch, ccy) if exch != "SMART" else Stock(sym, "SMART", ccy, primaryExchange="")
    got = ib.qualifyContracts(c)
    return got[0] if got else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--job", choices=["probe", "headlines", "articles"], required=True)
    ap.add_argument("--symbols", nargs="*", default=None, help="headlines：只抓這些美股代號（預設 S&P 500 現任成分股）")
    ap.add_argument("--providers", default=None, help="用 + 連接的新聞源代碼；預設 = probe 時能用的全部")
    ap.add_argument("--max-req", type=int, default=200, help="每檔最多幾個請求（每個最多 300 則）")
    ap.add_argument("--max-articles", type=int, default=2000, help="articles：最多下載幾篇全文")
    ap.add_argument("--client-id", type=int, default=29, help="每日採集用 17、外匯腳本用 23，這裡用 29")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    from ib_insync import IB
    ib = IB()
    ib.errorEvent += on_error
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=30)
    log(f"== job={args.job} 連線 port {args.port} clientId {args.client_id}")

    providers = ib.reqNewsProviders()
    with open(OUT / "_providers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        w.writerows((p.code, p.name) for p in providers)
    codes = args.providers or "+".join(p.code for p in providers)
    log(f"新聞源 {len(providers)} 個：{codes or '（沒有）'}")
    if not codes:
        log("沒有任何新聞源權限，停止。")
        ib.disconnect()
        return

    if args.job == "probe":
        # 每檔、每個新聞源各試一次最近一個月；再試最早能到哪（往前跳 1、3、5、10 年）；再試一篇全文
        sample = None
        for market, sym, exch, ccy in PROBE:
            c = stock(ib, market, sym, exch, ccy)
            if not c:
                log(f"{market} {sym}：合約解析失敗")
                continue
            log(f"{market} {sym}：conId {c.conId}")
            for p in codes.split("+"):
                n_before = len(ERRORS)
                try:
                    news = ib.reqHistoricalNews(c.conId, p, "", "", 50)
                except Exception as exc:  # noqa: BLE001
                    news = []
                    log(f"  probe {sym} {p} 失敗：{exc!r}")
                time.sleep(PACE)
                span = f"{news[-1].time} → {news[0].time}" if news else "—"
                log(f"  probe {sym} {p}：最近 {len(news)} 則（{span}）" + ("，有錯誤" if len(ERRORS) > n_before else ""))
                if news and not sample:
                    sample = news[0]
            for yrs in (1, 3, 5, 10):
                end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * yrs)
                try:
                    news = ib.reqHistoricalNews(c.conId, codes, "", ib_time(end), 10)
                except Exception as exc:  # noqa: BLE001
                    news = []
                    log(f"  probe {sym} {yrs} 年前 失敗：{exc!r}")
                time.sleep(PACE)
                log(f"  probe {sym} {yrs} 年前：{len(news)} 則" + (f"（{news[0].time}）" if news else ""))
        if sample:
            try:
                art = ib.reqNewsArticle(sample.providerCode, sample.articleId)
                log(f"  probe 全文 {sample.providerCode} {sample.articleId}：type {art.articleType}，{len(art.articleText)} 字元")
            except Exception as exc:  # noqa: BLE001
                log(f"  probe 全文失敗：{exc!r}")
        codes_seen = sorted({c for c, _ in ERRORS})
        log(f"== probe 完成；錯誤碼：{codes_seen or '無'}")

    elif args.job == "headlines":
        syms = args.symbols or sp500_current()
        log(f"標題：{len(syms)} 檔，新聞源 {codes}")
        for i, sym in enumerate(syms, 1):
            c = stock(ib, "US", sym.replace("-", " "), "SMART", "USD")
            if not c:
                log(f"[{i}/{len(syms)}] {sym}：合約解析失敗")
                continue
            n = fetch_headlines(ib, c.conId, codes, OUT / "headlines" / f"US_{sym}.csv.gz", args.max_req)
            log(f"[{i}/{len(syms)}] {sym}：新增 {n} 則")

    elif args.job == "articles":
        # 從已抓的標題隨機抽樣下載全文（固定種子，重跑會抽到同一批、已下載的略過）
        pool = []
        for path in sorted((OUT / "headlines").glob("*.csv.gz")):
            pool += list(read_headlines(path).values())
        random.Random(20260925).shuffle(pool)
        got = 0
        for r in pool[:args.max_articles]:
            dest = OUT / "articles" / r["provider"] / f"{r['article_id'].replace('/', '_')}.txt.gz"
            if dest.exists():
                continue
            try:
                art = ib.reqNewsArticle(r["provider"], r["article_id"])
            except Exception as exc:  # noqa: BLE001
                log(f"  全文 {r['provider']} {r['article_id']} 失敗：{exc!r}")
                time.sleep(PACE)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(dest, "wt", encoding="utf-8") as f:
                f.write(f"time: {r['time']}\nheadline: {r['headline']}\ntype: {art.articleType}\n\n{art.articleText}")
            got += 1
            time.sleep(PACE)
        log(f"全文：下載 {got} 篇")

    ib.disconnect()
    log(f"== job={args.job} 結束")


if __name__ == "__main__":
    main()
