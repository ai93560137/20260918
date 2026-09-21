"""探測 HKEX 網頁報價 API（延遲 15 分鐘的免費行情）能否從 Actions 抓取。
流程：抓報價頁 → 正則抽 token → 試打 widget 端點 → 把回應樣本寫進 log。"""
import os
import re
import json
import time
import requests

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
log = []
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://www.hkex.com.hk/'}

token = None
for page in ['https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/Equity-Index/'
             'Hang-Seng-Index-Futures-and-Options?sc_lang=en',
             'https://www.hkex.com.hk/?sc_lang=en']:
    try:
        r = requests.get(page, headers=H, timeout=30)
        log.append(f"page {page[:70]}: HTTP {r.status_code}, {len(r.text)} chars")
        m = re.search(r'return\s*"(evLts[^"]+)"', r.text) or re.search(r'"token"\s*[:=]\s*"([^"]{30,})"', r.text)
        if m:
            token = m.group(1)
            log.append(f"token found: {token[:25]}... (len {len(token)})")
            break
    except Exception as e:
        log.append(f"page ERR: {e!r}")

qid = str(int(time.time()*1000))
endpoints = [
    ('futures', f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures?lang=eng&token={token}&ati=HSI&type=0&qid={qid}&callback=j'),
    ('options_expiries', f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesoption?lang=eng&token={token}&ati=HSI&type=0&qid={qid}&callback=j'),
    ('chain', f'https://www1.hkex.com.hk/hkexwidget/data/getchainoption?lang=eng&token={token}&ati=HSI&type=0&qid={qid}&callback=j'),
]
if token:
    for name, u in endpoints:
        try:
            r = requests.get(u, headers=H, timeout=30)
            body = r.text[:1500]
            log.append(f"--- {name}: HTTP {r.status_code}, {len(r.text)} chars ---")
            log.append(body)
            if r.status_code == 200 and len(r.text) > 500:
                with open(f'{OUT}/hkex_probe_{name}.txt', 'w') as f:
                    f.write(r.text[:100000])
        except Exception as e:
            log.append(f"{name} ERR: {e!r}")
else:
    log.append("NO TOKEN — widget API 這條路不通，需要換源")

with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log)[:3000])
