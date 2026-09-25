#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探測:哪些免費報價源可讓瀏覽器(指令台網頁)直接跨域讀取。
檢查 CORS 頭與回應格式(JSONP/script 可繞 CORS)。跑在 Actions runner。"""
import requests

targets = [
    ('gold-api XAU', 'https://api.gold-api.com/price/XAU', {}),
    ('swissquote XAU', 'https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD', {}),
    ('tencent hkHSI', 'https://qt.gtimg.cn/q=hkHSI', {}),
    ('tencent r_hkHSI', 'https://qt.gtimg.cn/q=r_hkHSI', {}),
    ('tencent hf_HSI', 'https://qt.gtimg.cn/q=hf_HSI', {}),
    ('tencent ifzq hkHSI', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hkHSI,day,,,2', {}),
]
for name, url, hdr in targets:
    try:
        h = {'Origin': 'https://claude.site', 'User-Agent': 'Mozilla/5.0'}
        h.update(hdr)
        r = requests.get(url, headers=h, timeout=15)
        cors = r.headers.get('Access-Control-Allow-Origin', '(無)')
        ctype = r.headers.get('Content-Type', '?')
        body = r.text[:220].replace('\n', ' ')
        print(f'== {name}\n   status={r.status_code} CORS={cors} type={ctype}\n   body: {body}\n')
    except Exception as e:
        print(f'== {name}\n   FAIL {e}\n')
