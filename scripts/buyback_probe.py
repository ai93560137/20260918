#!/usr/bin/env python3
"""回購公告數據來源探測（一次性）：打各市場的公告查詢端點，把原始回應存到 data/buyback/probe/，
用來決定各市場的事件定義與抓法。金鑰從環境變數讀（EDINET_API_KEY、DART_API_KEY），沒有就略過。"""
import os
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "buyback", "probe")
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}
SEC = {"User-Agent": os.environ.get("SEC_USER_AGENT", ""), "Accept-Encoding": "gzip, deflate"}
EDINET = os.environ.get("EDINET_API_KEY", "")
DART = os.environ.get("DART_API_KEY", "")

HK_SEARCH = ("https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime"
             "&category=0&market=SEHK&stockId=-1&documentType=-1&fromDate={f}&toDate={t}&title={q}"
             "&searchType=0&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=100&lang=E")

PROBES = [
    # 美國：SEC 全文搜尋（8-K 回購授權）
    ("us_efts_2024", "GET", "https://efts.sec.gov/LATEST/search-index?q=%22repurchase%20program%22%20authorized"
     "&forms=8-K&dateRange=custom&startdt=2024-02-01&enddt=2024-02-07", None, SEC),
    ("us_efts_2006", "GET", "https://efts.sec.gov/LATEST/search-index?q=%22repurchase%20program%22%20authorized"
     "&forms=8-K&dateRange=custom&startdt=2006-02-01&enddt=2006-02-07", None, SEC),
    # 港股：港交所披露易的標題分類與標題搜尋
    ("hk_tier1", "GET", "https://www1.hkexnews.hk/ncms/script/eds/tierone_e.json", None, BROWSER),
    ("hk_tier2", "GET", "https://www1.hkexnews.hk/ncms/script/eds/tiertwo_e.json", None, BROWSER),
    ("hk_search_buyback_2024", "GET", HK_SEARCH.format(f="20240301", t="20240307", q="buy-back"), None, BROWSER),
    ("hk_search_ndr_2012", "GET", HK_SEARCH.format(f="20120301", t="20120307", q="Next%20Day%20Disclosure"),
     None, BROWSER),
    # 台股：公開資訊觀測站（新版 API 與舊版查詢頁）
    ("tw_mops_new_home", "GET", "https://mops.twse.com.tw/mops/", None, BROWSER),
    ("tw_mopsov_t35sc09", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09",
     {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "sii",
      "year": "112", "month": "", "b_date": "", "e_date": "", "co_id": ""}, BROWSER),
    ("tw_mopsov_t35sc09_2330", "POST", "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09",
     {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "sii",
      "co_id": "2330", "year": "", "month": "", "b_date": "", "e_date": ""}, BROWSER),
    ("tw_twse_openapi_list", "GET", "https://openapi.twse.com.tw/v1/swagger.json", None, BROWSER),
]
if EDINET:
    PROBES += [
        ("jp_edinet_2024", "GET", "https://api.edinet-fsa.go.jp/api/v2/documents.json?date=2024-03-15&type=2"
         f"&Subscription-Key={EDINET}", None, BROWSER),
        ("jp_edinet_2014", "GET", "https://api.edinet-fsa.go.jp/api/v2/documents.json?date=2014-06-16&type=2"
         f"&Subscription-Key={EDINET}", None, BROWSER),
    ]
if DART:
    PROBES += [
        ("kr_dart_list_2024", "GET", f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART}"
         "&bgn_de=20240301&end_de=20240315&pblntf_detail_ty=B001&page_count=100", None, BROWSER),
        ("kr_dart_tsstk_samsung", "GET", f"https://opendart.fss.or.kr/api/tsstkAqDecsn.json?crtfc_key={DART}"
         "&corp_code=00126380&bgn_de=20150101&end_de=20241231", None, BROWSER),
    ]


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = []
    for name, method, url, data, headers in PROBES:
        try:
            r = requests.request(method, url, data=data, headers=headers, timeout=60)
            body = r.content[:200_000]
            status, ctype = r.status_code, r.headers.get("content-type", "")
        except requests.RequestException as e:
            body, status, ctype = str(e).encode(), "ERR", ""
        safe_url = url.replace(EDINET, "***") if EDINET else url
        safe_url = safe_url.replace(DART, "***") if DART else safe_url
        with open(os.path.join(OUT, f"{name}.txt"), "wb") as f:
            f.write(f"{method} {safe_url}\nstatus={status} content-type={ctype} bytes={len(body)}\n\n".encode())
            f.write(body)
        summary.append(f"| {name} | {status} | {ctype[:40]} | {len(body):,} |")
        print(summary[-1])
        time.sleep(1)
    with open(os.path.join(OUT, "SUMMARY.md"), "w", encoding="utf-8") as f:
        f.write("| 探測 | 狀態 | 類型 | 位元組 |\n|---|---|---|---|\n" + "\n".join(summary) + "\n")
        f.write(f"\nEDINET 金鑰：{'有' if EDINET else '沒有'}；DART 金鑰：{'有' if DART else '沒有'}\n")


if __name__ == "__main__":
    main()
