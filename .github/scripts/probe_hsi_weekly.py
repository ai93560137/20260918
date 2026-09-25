"""HSI 週權管道探測（2026-09-25）：HKEX widget 有沒有恒指週權的期權鏈？
一、getoptioncontractlist ats=HSI 全量倒出——週權可能混在合約單裡（W 標記）
二、試候選產品碼 ats=HSIW/WHI/HSI.W/PHS
結果進 data_external/hsi_weekly_probe/，只偵察不下單。"""
import json
import os
import re
import time

import requests

OUT = 'tradingview/data_external/hsi_weekly_probe'
os.makedirs(OUT, exist_ok=True)
log = []
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
     'Referer': 'https://www.hkex.com.hk/'}
page = requests.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                    'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en',
                    headers=H, timeout=30).text
m = re.search(r'return\s*"(evLts[^"]+)"', page)
token = m.group(1) if m else None
log.append(f"token: {'OK' if token else 'MISS'}")


def call(ep, **kw):
    qid = str(int(time.time() * 1000))
    q = '&'.join(f'{k}={v}' for k, v in kw.items())
    u = (f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}'
         f'&{q}&qid={qid}&callback=j')
    r = requests.get(u, headers=H, timeout=30)
    body = r.text
    js = json.loads(body[body.index('(') + 1:body.rindex(')')])
    return js


if token:
    # 一、全量合約單：找 W / weekly 標記
    try:
        cl = call('getoptioncontractlist', ats='HSI', type=0)
        cons = cl.get('data', {}).get('conlist', [])
        log.append(f"HSI conlist: {len(cons)} entries")
        with open(f'{OUT}/conlist_full.json', 'w') as f:
            json.dump(cons, f, ensure_ascii=False, indent=1)
        wk = [c for c in cons if any(ch in json.dumps(c).upper() for ch in ('W1', 'W2', 'W3', 'W4', 'W5', 'WEEK'))]
        log.append(f"weekly-flagged entries: {len(wk)} -> {wk[:6]}")
    except Exception as e:
        log.append(f"conlist ERR: {e!r}")
    # 二、候選週權產品碼
    for ats in ['HSIW', 'WHI', 'PHS', 'HSI.W', 'WTI1']:
        try:
            cl = call('getoptioncontractlist', ats=ats, type=0)
            cons = cl.get('data', {}).get('conlist', [])
            log.append(f"ats={ats}: conlist {len(cons)} -> {cons[:3]}")
            if cons:
                with open(f'{OUT}/conlist_{ats}.json', 'w') as f:
                    json.dump(cons, f, ensure_ascii=False, indent=1)
        except Exception as e:
            log.append(f"ats={ats} ERR: {e!r}")

with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
