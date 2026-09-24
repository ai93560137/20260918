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


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


# ---- 恒指報價(HKEX 15分鐘延遲);失敗或呆滯只跳過恒指,黃金照查 ----
best = None                                     # (ts, mid, tag)
if h.get('h1') is not None:
    try:
        S = requests.Session()
        S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                          'Referer': 'https://www.hkex.com.hk/'})
        page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                     'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
        token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)
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
    except Exception as e:
        print(f'hkex fail: {e}')
    if best and now - best[0] > timedelta(minutes=25):   # 呆滯報價(休市/凍結)不比對
        print(f'hsi quote stale ({best[0]:%H:%M}); skip hsi')
        best = None

up = lo = px = ts = tag = None
if best and h.get('h1') is not None:
    up = max(h['h1'], h['h2'], h['h3'])
    lo = min(h['l1'], h['l2'], h['l3'])
    ts, px, tag = best

try:
    st = json.load(open(STATE, encoding='utf-8'))
except Exception:
    st = {}
if 'last' in st:                                # 舊格式遷移
    st['hsi'] = st.pop('last')
alerts = []

hit = None
if px is not None and px >= up:
    hit = ('up', up, f'🔔🔺 恒指觸及通道上軌!\n報價 {px:,.0f} ≥ 上軌 {up:,.0f}({tag},{ts:%H:%M},延遲15分鐘)')
elif px is not None and px <= lo:
    hit = ('dn', lo, f'🔔🔻 恒指觸及通道下軌!\n報價 {px:,.0f} ≤ 下軌 {lo:,.0f}({tag},{ts:%H:%M},延遲15分鐘)')
if px is not None:
    print(f'hsi px={px:,.0f} rails=[{lo:,.0f}, {up:,.0f}] hit={hit and hit[0]}')
if hit:
    key = f'{hit[0]}:{hit[1]:.0f}:{now:%Y-%m-%d}'
    if st.get('hsi') == key:
        print('hsi already alerted; skip')
    else:
        st['hsi'] = key
        alerts.append(f'{hit[2]}\n📈 上軌 {up:,.0f} ／ 📉 下軌 {lo:,.0f}\n'
                      f'🌐 https://claude.ai/artifact/Qovghgidoao32zWai3gffX')

# ---- 黃金 XAUUSD:現貨即時價(Swissquote→gold-api)vs 現貨口徑通道 ----
g = lv.get('mgc') or {}
if g.get('h1') is not None:
    gup = max(g['h1'], g['h2'], g['h3'])
    glo = min(g['l1'], g['l2'], g['l3'])
    gpx = None
    try:
        r = requests.get('https://forex-data-feed.swissquote.com/public-quotes/'
                         'bboquotes/instrument/XAU/USD', timeout=20).json()
        p = r[0]['spreadProfilePrices'][0]
        m = (float(p['bid']) + float(p['ask'])) / 2
        if 1500 < m < 6000:
            gpx = m
    except Exception as e:
        print(f'swissquote fail: {e}')
    if gpx is None:
        try:
            j = requests.get('https://api.gold-api.com/price/XAU', timeout=20).json()
            m = float(j['price'])
            if 1500 < m < 6000:
                gpx = m
        except Exception as e:
            print(f'gold-api fail: {e}')
    if gpx is not None:
        fu = g.get('fut') or {}
        fut_note = ''
        ghit = None
        if gpx >= gup:
            fr = max(fu['h1'], fu['h2'], fu['h3']) if fu.get('h1') else None
            fut_note = f'\nMGC 期貨口徑上軌:{fr:,.1f}(掛單以期貨價為準)' if fr else ''
            ghit = ('up', gup, f'🥇🔺 黃金觸及通道上軌!\n現貨 {gpx:,.1f} ≥ 上軌 {gup:,.1f}(即時)')
        elif gpx <= glo:
            fr = min(fu['l1'], fu['l2'], fu['l3']) if fu.get('l1') else None
            fut_note = f'\nMGC 期貨口徑下軌:{fr:,.1f}(掛單以期貨價為準)' if fr else ''
            ghit = ('dn', glo, f'🥇🔻 黃金觸及通道下軌!\n現貨 {gpx:,.1f} ≤ 下軌 {glo:,.1f}(即時)')
        print(f'gold px={gpx:,.1f} rails=[{glo:,.1f}, {gup:,.1f}] hit={ghit and ghit[0]}')
        if ghit:
            gkey = f'{ghit[0]}:{ghit[1]:.1f}:{now:%Y-%m-%d}'
            if st.get('au') == gkey:
                print('gold already alerted; skip')
            else:
                st['au'] = gkey
                alerts.append(f'{ghit[2]}{fut_note}\n'
                              f'📈 現貨上軌 {gup:,.1f} ／ 📉 現貨下軌 {glo:,.1f}\n'
                              f'🌐 https://claude.ai/artifact/26ZLBsaqoMFKoAxsD7E1iw')

if not alerts:
    sys.exit(0)
with open(STATE, 'w', encoding='utf-8') as f:
    json.dump(st, f)

msg = ('🐍 八陣圖 · 蛇蟠陣 警報\n' + '\n\n'.join(alerts) + '\n\n'
       '👉 空手者:此為進場訊號,條件單已掛好應已成交;持反向倉者:反手單應已成交——'
       '去券商核對,把指令台「目前實倉」改成新倉位。\n'
       '👉 已持同方向倉者:無動作(絕不加倉)。\n'
       '⚠️ 警報有延遲,成交以券商為準')
with open('.github/touch_alert_msg.txt', 'w', encoding='utf-8') as f:
    f.write(msg)
out = os.environ.get('GITHUB_OUTPUT')
if out:
    with open(out, 'a') as f:
        f.write('alert=1\n')
print('ALERT:', msg)
