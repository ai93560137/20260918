#!/usr/bin/env python3
"""一次性探勘（在 GitHub Actions 跑，sandbox 沒外網）：日股/美股擴展前的資料源摸底。

A. Point-in-time 成分股來源（Wikipedia 修訂歷史，每年 6/30 一份 + 現行版）：
   - Nasdaq-100（en "Nasdaq-100"）
   - 日經225（en "Nikkei 225"）
   - 道指（en "Historical components of the Dow Jones Industrial Average"，現行版即有完整歷史）
   - S&P 500（en "List of S&P 500 companies" 現行版的 changes 表——給改代碼對照用；
     成分股本身用 fja05680/sp500 逐日數據）
B. 第二收市數據源 + 官方名字的可達性：
   - 美股：Nasdaq.com screener API（全市場收市/名字/行業一次拿）、historical API
   - 日股：JPX 上場銘柄一覧（官方名字+33業種）、日經官網成分股頁、Yahoo!ファイナンス
   - stooq（上次在 Actions 回 HTML，再確認一次）

輸出 research_output/multimarket/，原始內容截斷保存供 session 本機解析。
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("research_output/multimarket")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
WIKI_UA = {"User-Agent": "Mozilla/5.0 (research script; point-in-time index constituents)"}
API = "https://en.wikipedia.org/w/api.php"
LOG = []


def log(msg: str) -> None:
    print(msg)
    LOG.append(msg)


def wiki_rev(title: str, rvstart: str | None) -> dict | None:
    params = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": 1,
              "rvprop": "content|timestamp", "rvslots": "main", "format": "json", "formatversion": 2}
    if rvstart:
        params.update(rvstart=rvstart, rvdir="older")
    for attempt in range(5):
        try:
            r = requests.get(API, params=params, headers=WIKI_UA, timeout=30)
        except Exception as exc:
            log(f"wiki {title} {rvstart}: ERROR {exc}")
            return None
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        break
    if r.status_code != 200:
        log(f"wiki {title} {rvstart}: HTTP {r.status_code}")
        return None
    pages = r.json().get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        log(f"wiki {title} {rvstart}: 沒有修訂版本")
        return None
    rev = pages[0]["revisions"][0]
    return {"ts": rev["timestamp"], "text": rev["slots"]["main"]["content"]}


def wiki_series(slug: str, title: str, years: range) -> None:
    d = OUT / "wiki" / slug
    d.mkdir(parents=True, exist_ok=True)
    targets = [(str(y), f"{y}-06-30T00:00:00Z") for y in years] + [("current", None)]
    for label, start in targets:
        p = d / f"{label}.txt"
        if p.exists():
            continue
        rev = wiki_rev(title, start)
        if rev:
            p.write_text(f"<!-- revision {rev['ts']} -->\n" + rev["text"], encoding="utf-8")
            log(f"wiki {slug} {label}: {rev['ts']} {len(rev['text'])} chars")
        time.sleep(1)


def probe(name: str, url: str, headers: dict | None = None, keep: int = 300_000, binary: bool = False,
          params: dict | None = None) -> requests.Response | None:
    try:
        r = requests.get(url, headers=headers or UA, params=params, timeout=45)
    except Exception as exc:
        log(f"probe {name}: ERROR {exc}")
        return None
    ctype = r.headers.get("content-type", "")
    log(f"probe {name}: HTTP {r.status_code} {ctype} {len(r.content)} bytes")
    ext = "bin" if binary else "txt"
    (OUT / "probe").mkdir(parents=True, exist_ok=True)
    if binary:
        (OUT / "probe" / f"{name}.{ext}").write_bytes(r.content[:5_000_000])
    else:
        (OUT / "probe" / f"{name}.{ext}").write_text(r.text[:keep], encoding="utf-8")
    return r


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # --- A. Wikipedia ---
    wiki_series("ndx", "Nasdaq-100", range(2008, 2027))
    wiki_series("n225", "Nikkei 225", range(2008, 2027))
    wiki_series("djia_hist", "Historical components of the Dow Jones Industrial Average", range(0))
    wiki_series("sp500_list", "List of S&P 500 companies", range(0))

    # --- B. 美股第二來源 ---
    nasdaq_h = dict(UA, **{"Accept": "application/json, text/plain, */*",
                           "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    r = probe("nasdaq_screener", "https://api.nasdaq.com/api/screener/stocks",
              headers=nasdaq_h, params={"tableonly": "true", "download": "true"}, keep=0)
    if r is not None and r.status_code == 200:
        try:
            rows = r.json()["data"]["rows"]
            keep = ["symbol", "name", "lastsale", "netchange", "pctchange", "marketCap",
                    "country", "ipoyear", "volume", "sector", "industry"]
            (OUT / "probe" / "nasdaq_screener.json").write_text(
                json.dumps([{k: x.get(k) for k in keep} for x in rows], ensure_ascii=False), encoding="utf-8")
            log(f"nasdaq screener: {len(rows)} 檔，範例 {rows[0]}")
        except Exception as exc:
            log(f"nasdaq screener 解析失敗 {exc}: {r.text[:300]}")
    probe("nasdaq_hist_aapl", "https://api.nasdaq.com/api/quote/AAPL/historical", headers=nasdaq_h,
          params={"assetclass": "stocks", "fromdate": "2026-08-01", "limit": "30"})
    probe("nasdaq_info_aapl", "https://api.nasdaq.com/api/quote/AAPL/info", headers=nasdaq_h,
          params={"assetclass": "stocks"})

    # --- B. 日股 ---
    probe("jpx_listed_xls", "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls",
          binary=True)
    probe("nikkei_components_en", "https://indexes.nikkei.co.jp/en/nkave/index/component?idx=nk225")
    probe("nikkei_components_ja", "https://indexes.nikkei.co.jp/nkave/index/component?idx=nk225")
    probe("nikkei_changes_ja", "https://indexes.nikkei.co.jp/nkave/archives/news")
    probe("yahoojp_7203", "https://finance.yahoo.co.jp/quote/7203.T")
    probe("yahoojp_7203_hist", "https://finance.yahoo.co.jp/quote/7203.T/history")
    probe("kabutan_7203", "https://kabutan.jp/stock/kabuka?code=7203")

    # --- stooq 再確認 ---
    probe("stooq_aapl", "https://stooq.com/q/d/l/?s=aapl.us&i=d")
    probe("stooq_7203", "https://stooq.com/q/d/l/?s=7203.jp&i=d")

    (OUT / "probe_log.txt").write_text(
        f"run {datetime.now(timezone.utc).isoformat()}\n" + "\n".join(LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
