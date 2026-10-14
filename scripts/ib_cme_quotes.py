#!/usr/bin/env python3
"""[R184] ib-data VM：用 IB 延遲行情抓富途實倉嘅 CME 合約報價，推上 Cloud Run（只讀：唔落單、唔改單）。

流程：POST action=cme_watchlist 攞富途最新快照嘅 CME 代碼 → IB 延遲報價（reqMarketDataType 4）
→ POST action=cme_quotes 存 GCS futu/ext/cme_quotes.json → 使用者部機 auto_risk 用嚟計風險。

設定（使用者喺 VM 自己做，權杖唔好貼入對話）：
    ~/zhuge/env 入面兩行（chmod 600）：
        export ZHUGE_GCP_URL="https://…run.app/"
        export WEBHOOK_SECRET_TOKEN="…"
crontab（UTC，每 15 分鐘，週日晚至週五）：
    */15 * * * 0-5  . $HOME/zhuge/env && python3 $HOME/zhuge/ib_cme_quotes.py >> $HOME/zhuge/cme_quotes.log 2>&1

clientId 54（VM 已用 17、23、24、31、41、53、77）。--dry 只印唔推。
"""
import argparse
import calendar
import json
import math
import os
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone

FUT_RE = re.compile(r"^US\.(ES|MES)(\d{2})(\d{2})$")
EW_RE = re.compile(r"^US\.EW(\d{2})(\d{2})([CP])(\d+)x\d$")
EX_RE = re.compile(r"^US\.EX(\d)(\d{2})(\d{2})([CP])(\d+)x\d$")


def last_business_day(y, m):
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def nth_friday(y, m, n):
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def contract_for(code):
    """富途代碼 → ib_insync 合約；唔識就 None。"""
    from ib_insync import Future, FuturesOption
    m = FUT_RE.match(code)
    if m:
        return Future(m.group(1), f"20{m.group(2)}{m.group(3)}", "CME", currency="USD")
    m = EW_RE.match(code)
    if m:
        y, mo = 2000 + int(m.group(1)), int(m.group(2))
        return FuturesOption("ES", last_business_day(y, mo).strftime("%Y%m%d"), float(m.group(4)), m.group(3), "CME",
                             currency="USD", tradingClass="EW")
    m = EX_RE.match(code)
    if m:
        n, y, mo = int(m.group(1)), 2000 + int(m.group(2)), int(m.group(3))
        return FuturesOption("MES", nth_friday(y, mo, n).strftime("%Y%m%d"), float(m.group(5)), m.group(4), "CME",
                             currency="USD", tradingClass=f"EX{n}")
    return None


def post(url, body, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def num(x):
    return x if isinstance(x, (int, float)) and not math.isnan(x) and x > 0 else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=54)
    ap.add_argument("--wait", type=float, default=8)
    ap.add_argument("--dry", action="store_true", help="只印，唔推 Cloud Run")
    a = ap.parse_args()
    url, tok = os.environ.get("ZHUGE_GCP_URL", "").strip(), os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not url or not tok:
        print(now, "冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN（. ~/zhuge/env）"); return
    try:
        codes = post(url, {"action": "cme_watchlist", "token": tok}).get("codes") or []
    except Exception as e:                      # noqa: BLE001  唔印網址同權杖
        print(now, f"cme_watchlist 失敗：{e.__class__.__name__}"); return
    from ib_insync import IB
    ib = IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20, readonly=True)
    ib.reqMarketDataType(4)                     # 延遲凍結：冇訂閱用延遲，休市用最後值
    tickers = []
    for code in codes:
        c = contract_for(code)
        if c is None:
            print(now, code, "唔識轉 IB 合約，跳過"); continue
        try:
            if not ib.qualifyContracts(c):
                print(now, code, "qualify 失敗"); continue
        except Exception as e:                  # noqa: BLE001
            print(now, code, f"qualify 例外 {e!r}"); continue
        tickers.append((code, c, ib.reqMktData(c, "", False, False)))
    ib.sleep(a.wait)
    quotes = {}
    for code, c, t in tickers:
        row = {"bid": num(t.bid), "ask": num(t.ask), "last": num(t.last), "close": num(t.close),
               "md_type": t.marketDataType, "local_symbol": c.localSymbol,
               "quote_time": t.time.strftime("%Y-%m-%d %H:%M:%S") if t.time else now}
        ib.cancelMktData(c)
        if any(row[k] for k in ("bid", "ask", "last", "close")):
            quotes[code] = row
    ib.disconnect()
    print(now, json.dumps(quotes, ensure_ascii=False))
    if a.dry or not quotes:
        return
    try:
        res = post(url, {"action": "cme_quotes", "token": tok, "fetched_utc": now, "source": "IB 延遲行情（約 15 分鐘）",
                         "quotes": quotes})
        print(now, "推送：", res.get("status"), res.get("count"))
    except Exception as e:                      # noqa: BLE001
        print(now, f"cme_quotes 推送失敗：{e.__class__.__name__}")


if __name__ == "__main__":
    main()
