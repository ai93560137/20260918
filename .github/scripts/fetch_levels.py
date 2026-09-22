#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八陣圖指令台數據:抓恒指期貨即月 + 金期貨最近 3 個完整交易日的日高/日低。

跑在 GitHub Actions runner(外網全通),輸出 tradingview/data_external/levels.json,
session 端 git pull 後讀取並寫入 Artifact 資料庫。
HKEX widget 手法(token/JSONP/headers)同 fetch_hkex_quotes.py,詳見
tradingview/DATA_PIPELINE.md。
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests

HKT = timezone(timedelta(hours=8))
ET = timezone(timedelta(hours=-4))          # 夏令;冬令差 1 小時對「排除未完日」判斷無影響
OUT = 'tradingview/data_external'
log = []

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                  'Referer': 'https://www.hkex.com.hk/'})

result = {'fetched_at': datetime.now(HKT).strftime('%Y-%m-%d %H:%M HKT')}


def hsi_levels():
    page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                 'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
    token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)

    def call(ep, **params):
        qid = str(int(time.time() * 1000))
        q = '&'.join(f"{k}={v}" for k, v in params.items())
        u = f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}&{q}&qid={qid}&callback=j'
        body = S.get(u, timeout=30).text
        m = re.search(r'^j\((.*)\)\s*$', body, re.S)
        return json.loads(m.group(1)) if m else None

    # getchartdata2 的 int/span 組合未在別處驗證過:網格嘗試,取到合理日線序列為準
    rows = None
    for i, sp in [(8, 6), (8, 3), (9, 6), (6, 6), (7, 6), (8, 2)]:
        try:
            d = call('getchartdata2', hchart=1, span=sp, int=i, ric='HSIc1')
            dl = (d or {}).get('data', {}).get('datalist') or []
            # 期望格式 [ts_ms, open, high, low, close, ...];至少 5 根、價位合理
            cand = [r for r in dl if isinstance(r, list) and len(r) >= 5
                    and r[2] and r[3] and 15000 < float(r[3]) < float(r[2]) < 40000]
            if len(cand) >= 5:
                # 判斷是否日線:相鄰時間戳間隔 >= 20 小時
                gaps = [(cand[k+1][0] - cand[k][0]) / 3600000 for k in range(len(cand)-1)]
                if gaps and min(gaps[-5:]) >= 20:
                    rows = cand
                    log.append(f'getchartdata2 int={i} span={sp}: {len(cand)} daily rows')
                    break
        except Exception as e:
            log.append(f'getchartdata2 int={i} span={sp}: {e}')
    if not rows:
        raise RuntimeError('getchartdata2 no usable daily series: ' + ' | '.join(log[-6:]))

    today_hk = datetime.now(HKT).date()
    days = []
    for r in rows:
        d = datetime.fromtimestamp(r[0] / 1000, tz=HKT).date()
        if d < today_hk:                                   # 只要已完結的日
            days.append((d, float(r[2]), float(r[3])))     # (date, high, low)
    days = days[-3:]
    if len(days) < 3:
        raise RuntimeError(f'only {len(days)} completed days')
    days.reverse()                                          # [0]=最近一日
    out = {}
    for n, (d, h, l) in enumerate(days, 1):
        out[f'h{n}'], out[f'l{n}'] = round(h), round(l)
    out['dates'] = [str(d) for d, _, _ in days]
    return out


def gold_levels():
    import yfinance as yf
    df = yf.download('GC=F', period='10d', interval='1d', progress=False, auto_adjust=False)
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)
    today_et = datetime.now(ET).date()
    rows = []
    for idx, r in df.iterrows():
        d = idx.date()
        h, l = float(r['High']), float(r['Low'])
        if d <= today_et and 1500 < l < h < 6000:          # 排除進行中的次日 bar
            rows.append((d, h, l))
    rows = rows[-3:]
    if len(rows) < 3:
        raise RuntimeError(f'only {len(rows)} completed days')
    rows.reverse()
    out = {}
    for n, (d, h, l) in enumerate(rows, 1):
        out[f'h{n}'], out[f'l{n}'] = round(h, 1), round(l, 1)
    out['dates'] = [str(d) for d, _, _ in rows]
    return out


for key, fn, src in (('hsi', hsi_levels, 'HKEX 即月期貨 HSIc1(15分鐘延遲)'),
                     ('mgc', gold_levels, 'Yahoo GC=F')):
    try:
        v = fn()
        v['source'] = src
        result[key] = v
        log.append(f'{key}: OK {v["dates"]}')
    except Exception as e:
        result[key] = {'error': str(e)[:300]}
        log.append(f'{key}: FAIL {e}')

result['log'] = log
import os
os.makedirs(OUT, exist_ok=True)
with open(f'{OUT}/levels.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print('\n'.join(log))
