"""HKEX API 探測第二輪：從頁面 JS 挖出真正的端點與參數格式，照抄呼叫。"""
import os
import re
import time
import requests

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
log = []
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://www.hkex.com.hk/'}
S = requests.Session()
S.headers.update(H)

page_url = ('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/Equity-Index/'
            'Hang-Seng-Index-Futures-and-Options?sc_lang=en')
r = S.get(page_url, timeout=30)
html = r.text
log.append(f"page: HTTP {r.status_code}, {len(html)} chars")
m = re.search(r'return\s*"(evLts[^"]+)"', html)
token = m.group(1) if m else None
log.append(f"token: {token[:25]}..." if token else "NO TOKEN")

# 1) 頁面裡所有 hkexwidget 端點與前後文
for mm in re.finditer(r'.{120}hkexwidget[^"\'\s]{0,80}.{120}', html):
    log.append("CTX: " + mm.group(0).replace('\n', ' ')[:320])
# 2) 頁面引用的 JS 檔（widget 的呼叫邏輯多半在外部 JS）
js_files = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))
log.append("JS files: " + " | ".join(js_files[:20]))
# 3) 抓最像 widget 的 JS，挖端點與參數
for jf in js_files:
    if not re.search(r'widget|derivat|quote|market', jf, re.I):
        continue
    u = jf if jf.startswith('http') else ('https://www.hkex.com.hk' + jf)
    try:
        jr = S.get(u, timeout=30)
        hits = re.findall(r'[\w/]*hkexwidget/data/(\w+)', jr.text)
        if hits:
            log.append(f"JS {u[:80]}: endpoints {sorted(set(hits))}")
            for ep in sorted(set(hits)):
                for mm in re.finditer(r'.{60}data/' + ep + r'.{260}', jr.text):
                    log.append(f"  {ep} CTX: " + mm.group(0).replace('\n', ' ')[:400])
                    break
    except Exception as e:
        log.append(f"JS {u[:60]} ERR: {e!r}")

# 4) 用常見參數變體再試 futures 端點
qid = str(int(time.time() * 1000))
variants = [
    f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures?lang=eng&token={token}&ati=HSI&type=0&qid={qid}&callback=jQuery{qid}',
    f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures?lang=eng&token={token}&ati=HSI&qid={qid}&callback=jQuery{qid}',
    f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures?lang=eng&token={token}&assetid=HSI&type=0&qid={qid}&callback=jQuery{qid}',
]
for u in variants:
    try:
        rr = S.get(u, timeout=20)
        log.append(f"TRY {u[100:160]}: {rr.text[:200]}")
    except Exception as e:
        log.append(f"TRY ERR: {e!r}")

with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log)[:4000])
