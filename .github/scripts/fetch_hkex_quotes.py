"""HKEX 延遲行情抓取器：恒指期貨全月份 + 近月期權鏈。
端點與參數逆向自 hkex.com.hk 的 equity.js（ats/con/type）。
輸出 JSON 到 tradingview/data_external/quotes/，由 workflow commit 回分支。"""
import os
import re
import json
import time
import requests

OUT = 'tradingview/data_external/quotes'
os.makedirs(OUT, exist_ok=True)
log = []
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://www.hkex.com.hk/'}
S = requests.Session()
S.headers.update(H)

page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/Equity-Index/'
             'Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)
log.append(f"token OK ({len(token)})")

def call(ep, **params):
    qid = str(int(time.time() * 1000))
    q = '&'.join(f"{k}={v}" for k, v in params.items() if v is not None)
    u = f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}&{q}&qid={qid}&callback=j'
    r = S.get(u, timeout=30)
    body = r.text
    m = re.search(r'^j\((.*)\)\s*$', body, re.S)
    data = json.loads(m.group(1)) if m else None
    code = data.get('data', {}).get('responsecode', data.get('data', {}).get('responseCode', '?')) if data else 'HTTP'+str(r.status_code)
    log.append(f"{ep}({q[:40]}): code={code}, {len(body)} chars")
    return data

stamp = time.strftime('%Y%m%d_%H%M')
# 1) 期貨全月份
fut = call('getderivativesfutures', ats='HSI', type=0)
if fut:
    json.dump(fut, open(f'{OUT}/futures_{stamp}.json', 'w'), ensure_ascii=False)
# 2) 期權合約月份清單（conlist 的 id 才是 con 參數的合法值）
cl = call('getoptioncontractlist', ats='HSI', type=0)
cons = []
if cl:
    conlist = cl.get('data', {}).get('conlist', []) or []
    cons = [(c.get('id'), c.get('mon')) for c in conlist]
    log.append(f"contracts: {cons[:8]}")
# 3) 期權鏈：前三個月份
for cid, mon in cons[:3]:
    opt = call('getderivativesoption', ats='HSI', con=cid, fr='null', to='null', type=0)
    if opt and len(json.dumps(opt)) > 500:
        safe = str(mon or cid).replace('/', '-').replace(' ', '')
        json.dump(opt, open(f'{OUT}/options_{safe}_{stamp}.json', 'w'), ensure_ascii=False)

with open('tradingview/data_external/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
