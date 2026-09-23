"""日經 VI 偵察第四輪：XHR 標頭 + cookie 流程（profile 選指數 → dataload 取月表）。"""
import os
import re

import requests

OUT = 'tradingview/data_external/nkvi_probe'
os.makedirs(OUT, exist_ok=True)
log = []
S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'})
B = 'https://indexes.nikkei.co.jp'
# 1) 建 session：訪 profile 選定 nk225vi，再訪 archives/data
for p in ['/en/nkave/index/profile?idx=nk225vi', '/en/nkave/archives/data?idx=nk225vi']:
    r = S.get(B + p, timeout=30)
    log.append(f"visit {p}: {r.status_code}, cookies={list(S.cookies.keys())}")
# 2) XHR 呼叫 dataload
xhr = {'X-Requested-With': 'XMLHttpRequest',
       'Referer': B + '/en/nkave/archives/data?idx=nk225vi'}
for name, q in [('m2015_09', '?list=daily&year=2015&month=9'),
                ('m2026_08', '?list=daily&year=2026&month=8'),
                ('m2020_03', '?list=daily&year=2020&month=3')]:
    r = S.get(B + '/en/nkave/statistics/dataload' + q, headers=xhr, timeout=30)
    with open(f'{OUT}/xhr_{name}.txt', 'w') as f:
        f.write(r.text[:30000])
    vals = re.findall(r'<td>([\d.,]+)</td>', r.text)
    log.append(f"XHR {q}: {r.status_code}, {len(r.content)}b, 數值td: {len(vals)}, 樣本: {vals[:6]}")
with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
