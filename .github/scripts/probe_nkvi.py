"""日經 VI 數據源偵察（一次抓齊證據）：官網頁面連結、dataload 參數變體、cookie 重試。
輸出全部存 data_external/nkvi_probe/，供 session 分析後定正式抓法。"""
import os
import re

import requests

OUT = 'tradingview/data_external/nkvi_probe'
os.makedirs(OUT, exist_ok=True)
log = []
S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
                  'Accept': 'text/html,application/xhtml+xml,text/csv,*/*'})

pages = ['https://indexes.nikkei.co.jp/en/nkave/archives?list=vi',
         'https://indexes.nikkei.co.jp/en/nkave/archives',
         'https://indexes.nikkei.co.jp/en/nkave/index/profile?idx=nk225vi',
         'https://indexes.nikkei.co.jp/en/nkave/']
for i, u in enumerate(pages):
    try:
        r = S.get(u, timeout=30)
        body = r.text
        with open(f'{OUT}/page{i}.html', 'w') as f:
            f.write(body[:60000])
        hrefs = sorted(set(re.findall(r'href="([^"]*(?:csv|file|download|archiv)[^"]*)"', body, re.I)))
        log.append(f"PAGE {u} -> HTTP {r.status_code}, {len(body)}b, links: {hrefs[:12]}")
    except Exception as e:
        log.append(f"PAGE {u} ERR: {e!r}")

# dataload 參數變體
base = 'https://indexes.nikkei.co.jp/en/nkave/statistics/dataload'
for j, q in enumerate(['?list=vi', '?list=vi&year=2020', '?idx=nk225vi&csv=1',
                       '?list=nk225vi&csv=1', '?list=vi&csv=1&year=2015']):
    try:
        r = S.get(base + q, timeout=30)
        with open(f'{OUT}/dataload{j}.txt', 'w') as f:
            f.write(r.text[:20000])
        vals = re.findall(r'<td>([\d.,]+)</td>', r.text)
        log.append(f"DATALOAD {q} -> HTTP {r.status_code}, {len(r.content)}b, 數值td數: {len(vals)}, 樣本: {vals[:4]}")
    except Exception as e:
        log.append(f"DATALOAD {q} ERR: {e!r}")

# 帶 cookie 後重試官方 CSV
for u in ['https://indexes.nikkei.co.jp/en/nkave/archives/file/nikkei_stock_average_vi_daily_en.csv']:
    try:
        r = S.get(u, headers={'Referer': 'https://indexes.nikkei.co.jp/en/nkave/archives?list=vi'}, timeout=30)
        log.append(f"CSV(cookie) -> HTTP {r.status_code}, {len(r.content)}b")
        if r.status_code == 200:
            with open(f'{OUT}/vi_daily.csv', 'wb') as f:
                f.write(r.content)
    except Exception as e:
        log.append(f"CSV(cookie) ERR: {e!r}")

with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
