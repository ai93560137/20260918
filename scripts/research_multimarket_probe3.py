#!/usr/bin/env python3
"""一次性探勘第三輪（Actions 上跑）：第二來源能不能拿「全部歷史」做全量比對。

- 美股 Nasdaq.com historical API：一次最多拿幾年、有沒有已出榜/已下市代碼
- 日股 Yahoo!ファイナンス 歷史頁：月線（timeFrame=m）分頁格式、每頁幾筆、能回溯到哪年
"""
import json
import re
import time
from pathlib import Path

import requests

OUT = Path("research_output/multimarket/probe3")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
NQ = dict(UA, **{"Accept": "application/json, text/plain, */*",
                 "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
LOG = []


def get(name, url, headers=UA, params=None, keep=1_500_000):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=60)
    except Exception as exc:
        LOG.append(f"{name}: ERROR {exc}")
        return None
    LOG.append(f"{name}: HTTP {r.status_code} {len(r.content)} bytes {r.url[:160]}")
    (OUT / f"{name}.txt").write_text(r.text[:keep], encoding="utf-8")
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 美股：長區間、ETF、已出榜仍上市（AAL）、已下市（CELG）、改代碼（META 前身 FB）
    for sym, cls in (("AAPL", "stocks"), ("SPY", "etf"), ("AAL", "stocks"), ("CELG", "stocks"), ("FB", "stocks")):
        r = get(f"nasdaq_hist_{sym}", f"https://api.nasdaq.com/api/quote/{sym}/historical", headers=NQ,
                params={"assetclass": cls, "fromdate": "1995-01-01", "todate": "2026-09-22", "limit": "20000"})
        if r is not None and r.status_code == 200:
            try:
                d = r.json()["data"]
                rows = (d or {}).get("tradesTable", {}).get("rows") or []
                LOG.append(f"  {sym}: totalRecords={d.get('totalRecords') if d else None} 回傳 {len(rows)} 列 "
                           f"最早 {rows[-1]['date'] if rows else None} 最晚 {rows[0]['date'] if rows else None}")
            except Exception as exc:
                LOG.append(f"  {sym}: 解析失敗 {exc} {r.text[:200]}")
        time.sleep(1)
    # 日股：月線歷史頁 1、2 頁與遠期
    for name, url in (
        ("yj_7203_m_p1", "https://finance.yahoo.co.jp/quote/7203.T/history?timeFrame=m&page=1"),
        ("yj_7203_m_p2", "https://finance.yahoo.co.jp/quote/7203.T/history?timeFrame=m&page=2"),
        ("yj_7203_m_range", "https://finance.yahoo.co.jp/quote/7203.T/history?from=20000101&to=20091231&timeFrame=m&page=1"),
        ("yj_7203_d_p1", "https://finance.yahoo.co.jp/quote/7203.T/history?timeFrame=d&page=1"),
    ):
        r = get(name, url)
        if r is not None and r.status_code == 200:
            u = r.text.replace('\\"', '"')
            dates = re.findall(r'"baseDatetime":"([^"]+)"', u)[:40]
            closes = re.findall(r'"closePrice":"([^"]+)"', u)[:5]
            LOG.append(f"  {name}: baseDatetime x{len(dates)} {dates[:3]}...{dates[-2:]} closePrice {closes}")
        time.sleep(1)
    (OUT / "probe_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print("\n".join(LOG))


if __name__ == "__main__":
    main()
