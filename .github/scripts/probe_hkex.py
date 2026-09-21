"""HKEX 探測第三輪：全 JS 掃描 + iframe + 日報新入口。"""
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
html = S.get(page_url, timeout=30).text
token = (re.search(r'return\s*"(evLts[^"]+)"', html) or [None, None])[1] if re.search(r'return\s*"(evLts[^"]+)"', html) else None
m = re.search(r'return\s*"(evLts[^"]+)"', html)
token = m.group(1) if m else None
log.append(f"token: {'OK' if token else 'MISSING'}")

# iframe / www1 引用
for mm in re.finditer(r'<iframe[^>]+src="([^"]+)"', html):
    log.append("IFRAME: " + mm.group(1))
for mm in re.finditer(r'.{80}www1\.hkex\.com\.hk[^"\'\s]{0,100}.{80}', html):
    log.append("WWW1 CTX: " + mm.group(0).replace('\n', ' ')[:280])

# 全部 JS 檔搜 hkexwidget / getderivatives / tokenget
js_files = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))
for jf in js_files:
    u = jf if jf.startswith('http') else ('https://www.hkex.com.hk' + jf)
    try:
        t = S.get(u, timeout=30).text
        for pat in [r'hkexwidget/data/\w+', r'getderivatives\w*', r'dfutures\w*', r'doption\w*']:
            hits = sorted(set(re.findall(pat, t)))
            if hits:
                log.append(f"{jf.split('?')[0]}: {pat} → {hits[:10]}")
                for h_ in hits[:4]:
                    mm = re.search(r'.{100}' + re.escape(h_) + r'.{300}', t)
                    if mm:
                        log.append("  CTX: " + mm.group(0).replace('\n', ' ')[:400])
    except Exception as e:
        log.append(f"{jf[:50]} ERR: {e!r}")

# 日報新入口
for u in ['https://www.hkex.com.hk/Market-Data/Statistics/Consolidated-Reports/Daily-Market-Report?sc_lang=en',
          'https://www.hkex.com.hk/Market-Data/Statistics/Consolidated-Reports?sc_lang=en']:
    try:
        r = S.get(u, timeout=30)
        links = sorted(set(re.findall(r'href="([^"]*(?:dayrpt|dqe|hsio|DMR|dmr)[^"]*)"', r.text, re.I)))
        log.append(f"REPORT PAGE {u[60:110]}: HTTP {r.status_code}, links: {links[:10]}")
    except Exception as e:
        log.append(f"REPORT ERR: {e!r}")

with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log)[:4000])
