#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""恒指觸軌警報:HKEX 延遲報價 vs levels.json 通道,觸及上/下軌發 Telegram。

由預設分支的 hsi_touch_alert.yml 每 15 分鐘排程執行(交易時段)。
限制:報價延遲 15 分鐘 + 排程間隔,警報比實際觸價慢 15~30 分鐘——
只作後備提醒,條件單必須預先掛在券商。
狀態檔 .github/touch_alert_state.json 防重發(每方向每通道值每日一次),
只在發警報時 commit。輸出:GITHUB_OUTPUT 設 alert=1 及 msg 檔供 workflow 發送。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

HKT = timezone(timedelta(hours=8))
STATE = '.github/touch_alert_state.json'
now = datetime.now(HKT)

lv = json.load(open('tradingview/data_external/levels.json', encoding='utf-8'))
h = lv.get('hsi') or {}
if h.get('h1') is None:
    print('no hsi levels; skip'); sys.exit(0)
up = max(h['h1'], h['h2'], h['h3'])
lo = min(h['l1'], h['l2'], h['l3'])

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                  'Referer': 'https://www.hkex.com.hk/'})
page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
             'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


best = None                                     # (ts, mid, tag)
for typ, tag in ((0, '日市'), (1, '夜市')):
    try:
        qid = str(int(time.time() * 1000))
        u = (f'https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures'
             f'?lang=eng&token={token}&ats=HSI&type={typ}&qid={qid}&callback=j')
        body = S.get(u, timeout=30).text
        d = json.loads(re.search(r'^j\((.*)\)\s*$', body, re.S).group(1))
        qd = d.get('data', {})
        row = (qd.get('futureslist') or [{}])[0]
        bd, as_ = num(row.get('bd')), num(row.get('as'))
        lu = str(qd.get('lastupd', ''))
        m = re.match(r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})', lu)
        if m and bd and as_ and 15000 < bd <= as_ < 40000:
            ts = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                          int(m.group(4)), int(m.group(5)), tzinfo=HKT)
            mid = (bd + as_) / 2
            if best is None or ts > best[0]:
                best = (ts, mid, tag)
        print(f'{tag}: bd={bd} as={as_} lastupd={lu!r}')
    except Exception as e:
        print(f'type={typ} fail: {e}')

if not best:
    print('no usable quote; skip'); sys.exit(0)
ts, px, tag = best
if now - ts > timedelta(minutes=25):            # 呆滯報價(休市/凍結)不比對
    print(f'quote stale ({ts:%H:%M}); skip'); sys.exit(0)

hit = None
if px >= up:
    hit = ('up', up, f'🔔🔺 觸及通道上軌!\n報價 {px:,.0f} ≥ 上軌 {up:,.0f}({tag},{ts:%H:%M},延遲15分鐘)')
elif px <= lo:
    hit = ('dn', lo, f'🔔🔻 觸及通道下軌!\n報價 {px:,.0f} ≤ 下軌 {lo:,.0f}({tag},{ts:%H:%M},延遲15分鐘)')
print(f'px={px:,.0f} rails=[{lo:,.0f}, {up:,.0f}] hit={hit and hit[0]}')
if not hit:
    sys.exit(0)

try:
    st = json.load(open(STATE, encoding='utf-8'))
except Exception:
    st = {}
key = f'{hit[0]}:{hit[1]:.0f}:{now:%Y-%m-%d}'
if st.get('last') == key:
    print('already alerted; skip'); sys.exit(0)
st['last'] = key
with open(STATE, 'w', encoding='utf-8') as f:
    json.dump(st, f)

msg = (f'🐍 八陣圖 · 蛇蟠陣 警報\n{hit[2]}\n\n'
       f'📈 上軌 {up:,.0f} ／ 📉 下軌 {lo:,.0f}\n'
       f'👉 若條件單已掛好應已成交——去券商核對,成交後把指令台「目前實倉」改成新倉位。\n'
       f'⚠️ 警報有 15~30 分鐘延遲,成交以券商為準\n'
       f'🌐 https://claude.ai/artifact/Qovghgidoao32zWai3gffX')
with open('.github/touch_alert_msg.txt', 'w', encoding='utf-8') as f:
    f.write(msg)
out = os.environ.get('GITHUB_OUTPUT')
if out:
    with open(out, 'a') as f:
        f.write('alert=1\n')
print('ALERT:', msg)
