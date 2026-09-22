#!/usr/bin/env python3
"""第二收市數據源：港交所官方行情（HKEX 網站 widget API，免費、免註冊），
每天存一份快照 data/stocks_hkex/quotes_<YYYY-MM-DD>.json，給
scripts/check_data_quality.py 跟 yfinance 交叉比對收市價與**官方公司名**。

方法沿用 claude/dazzling-curie-f3xzb8 分支 tradingview/DATA_PIPELINE.md
（HKEX widget 逆向：每次現抓 token、JSONP 剝殼、responsecode=='000'）。
只提供「當天」報價，沒有歷史——每天存一份，第二來源的歷史從今天開始累積。

只抓 .HK 代碼（美股 HKEX 沒有）。抓不到只記錄原因、不算失敗。
    python3 scripts/fetch_hkex_equity.py scripts/pool_hsi_full.txt ...
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks_hkex"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.hkex.com.hk/",
}
TOKEN_PAGES = [
    "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities?sc_lang=en",
    "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=700&sc_lang=en",
]
ENDPOINT = "https://www1.hkex.com.hk/hkexwidget/data/getequityquote"
PROBE_N = 5
TIME_BUDGET_S = 300
HKT = timezone(timedelta(hours=8))


def read_universe(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def get_token(session: requests.Session) -> str:
    for url in TOKEN_PAGES:
        try:
            page = session.get(url, timeout=15).text
        except Exception as exc:
            print(f"token 頁面 {url} 失敗: {exc}", file=sys.stderr)
            continue
        m = re.search(r'return\s*"(evLts[^"]+)"', page)
        if m:
            return m.group(1)
    raise SystemExit("抓不到 HKEX token（頁面改版？），放棄第二來源")


def fetch_quote(session: requests.Session, token: str, ticker: str) -> dict | None:
    sym = ticker[:-3].lstrip("0") or "0"
    params = {"sym": sym, "token": token, "lang": "eng",
              "qid": int(time.time() * 1000), "callback": "j"}
    r = session.get(ENDPOINT, params=params, timeout=10)
    m = re.match(r"^\s*j\((.*)\)\s*$", r.text, re.DOTALL)
    if not m:
        print(f"MISS {ticker}: 非 JSONP 回應 {r.text[:80]!r}", file=sys.stderr)
        return None
    data = json.loads(m.group(1)).get("data", {})
    if data.get("responsecode") != "000" or not data.get("quote"):
        print(f"MISS {ticker}: responsecode={data.get('responsecode')} "
              f"{str(data.get('responsemsg', ''))[:60]}", file=sys.stderr)
        return None
    return data["quote"]


def pick(q: dict, *keys: str) -> str:
    for k in keys:
        v = q.get(k)
        if v not in (None, "", "-"):
            return str(v)
    return ""


def to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("universe", nargs="+", type=Path)
    args = ap.parse_args()

    tickers: list[str] = []
    for p in args.universe:
        for t in read_universe(p):
            if t.endswith(".HK") and t not in tickers:
                tickers.append(t)

    s = requests.Session()
    s.headers.update(HEADERS)
    token = get_token(s)

    started = time.monotonic()
    quotes: dict[str, dict] = {}
    for i, t in enumerate(tickers):
        if time.monotonic() - started > TIME_BUDGET_S:
            print(f"超過時間預算 {TIME_BUDGET_S}s，停在第 {i} 檔", file=sys.stderr)
            break
        try:
            q = fetch_quote(s, token, t)
        except Exception as exc:
            print(f"MISS {t}: {exc}", file=sys.stderr)
            q = None
        if q is not None:
            if not quotes:
                # 第一檔印出全部欄位，方便確認/調整欄位對應（端點欄位沒有公開文件）
                print(f"第一檔 {t} 原始欄位: {json.dumps(q, ensure_ascii=False)[:1500]}", flush=True)
            quotes[t] = {
                "name": pick(q, "nm", "nm_s", "nm_l", "name"),
                "close": to_float(pick(q, "ls", "lp", "last")),
                "prev_close": to_float(pick(q, "hc", "pc")),
                "high": to_float(pick(q, "hi")),
                "low": to_float(pick(q, "lo")),
                "update_time": pick(q, "updatetime", "update_time", "lastupd"),
                "raw": q,
            }
        if i + 1 == PROBE_N and not quotes:
            print(f"前 {PROBE_N} 檔全部失敗，判定 HKEX 端點目前不可用，放棄", file=sys.stderr)
            break
        time.sleep(0.3)

    print(f"HKEX 覆蓋: {len(quotes)}/{len(tickers)}")
    if not quotes:
        return
    # 快照日期用港股交易日：香港時間 09:30 開市前抓到的是前一個交易日的收市
    now_hkt = datetime.now(HKT)
    snap = (now_hkt - timedelta(days=1)) if now_hkt.hour < 9 else now_hkt
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"quotes_{snap.date().isoformat()}.json"
    out.write_text(json.dumps({"fetched_at_hkt": now_hkt.isoformat(timespec="seconds"),
                               "trade_date_guess": snap.date().isoformat(),
                               "quotes": quotes}, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
