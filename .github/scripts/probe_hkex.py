"""HKEX 探測第四輪：把 equity.js 整檔帶回來研究參數組法。"""
import os
import requests

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://www.hkex.com.hk/'}
r = requests.get('https://www.hkex.com.hk/lhkexw/js/equity.js', headers=H, timeout=30)
with open(f'{OUT}/hkex_equity.js', 'w') as f:
    f.write(r.text)
with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write(f"equity.js: HTTP {r.status_code}, {len(r.text)} chars")
print(f"equity.js: HTTP {r.status_code}, {len(r.text)} chars")
