"""日經 VI 偵察第三輪：archives/data 頁 + get_* API 變體。"""
import os
import re

import requests

OUT = 'tradingview/data_external/nkvi_probe'
os.makedirs(OUT, exist_ok=True)
log = []
S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
                  'Referer': 'https://indexes.nikkei.co.jp/en/nkave/index/profile?idx=nk225vi'})
B = 'https://indexes.nikkei.co.jp'
targets = [('data_idx', '/en/nkave/archives/data?idx=nk225vi'),
           ('data_plain', '/en/nkave/archives/data'),
           ('realchart', '/nkave/get_real_daily_chart?idx=nk225vi'),
           ('histchart', '/nkave/get_historical_chart?idx=nk225vi'),
           ('dl_combo', '/en/nkave/statistics/dataload?idx=nk225vi&list=vi&year=2015&csv=1')]
for name, path in targets:
    try:
        r = S.get(B + path, timeout=30)
        with open(f'{OUT}/{name}.txt', 'w') as f:
            f.write(r.text[:80000])
        forms = re.findall(r'<form[^>]*action="([^"]*)"', r.text)
        sels = re.findall(r'<select[^>]*name="([^"]*)"', r.text)
        csvs = re.findall(r'href="([^"]*csv[^"]*)"', r.text, re.I)
        log.append(f"{name}: HTTP {r.status_code}, {len(r.content)}b, forms={forms[:3]}, selects={sels[:6]}, csv-links={csvs[:5]}")
    except Exception as e:
        log.append(f"{name} ERR: {e!r}")
with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
