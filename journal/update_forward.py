#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前向測試每日盈虧記錄:用 levels.json 收市報價對 position.json 持倉做逐日結算,
追加/更新 journal/forward_test.csv 當日一行,並寫 journal/forward_line.txt
給 compose_tg.py 附進每日 Telegram。

由 16:45 排程在通道更新後執行(mark 價 = 當日 16:29 延遲中間價,方法論固定)。
持倉變動(反手/加減)由對帳工作階段改 position.json 的 pos/entry/realized/fees。
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
POS = os.path.join(BASE, 'position.json')
CSV = os.path.join(BASE, 'forward_test.csv')
LINE = os.path.join(BASE, 'forward_line.txt')
LV = os.path.join(BASE, '..', 'tradingview', 'data_external', 'levels.json')

p = json.load(open(POS, encoding='utf-8'))
lv = json.load(open(LV, encoding='utf-8'))
today = datetime.now(HKT).strftime('%Y-%m-%d')

h = p.get('hsi') or {}
q = ((lv.get('hsi') or {}).get('quote') or {})
mark = q.get('px')
if not h or mark is None:
    print('no position or no quote; skip')
    raise SystemExit(0)

# 非交易日(港股假期/週末)不結算:mark 必須是今天日市收市報價
if not (str(q.get('asof', '')).startswith(datetime.now(HKT).strftime('%d/%m/%Y'))
        and '日市' in str(q.get('kind', ''))):
    print(f"quote not today's day close ({q.get('kind')} {q.get('asof')}); 非交易日不結算")
    if os.path.exists(LINE):
        old = open(LINE, encoding='utf-8').read().split('\n')
        if old and today not in old[0]:
            last = old[0].split('(')[-1].rstrip(')')
            old[0] = f'📒 前向測試:{today} 休市不結算(以下為 {last} 結算)'
            with open(LINE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(old))
    raise SystemExit(0)

pos, entry, pv = h['pos'], h['entry'], h.get('point_value', 50)
open_pnl = round((mark - entry) * pos * pv)
realized, fees = h.get('realized', 0), h.get('fees', 0)
equity = p['capital'] + realized + open_pnl - fees

row = {'date': today, 'instrument': h.get('contract', 'HSI'), 'pos': pos,
       'entry': entry, 'mark': mark, 'open_pnl': open_pnl,
       'realized_cum': realized, 'fees_cum': fees, 'equity': equity,
       'quote_asof': q.get('asof', '')}
fields = list(row.keys())

rows = []
if os.path.exists(CSV):
    with open(CSV, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f)]
rows = [r for r in rows if r['date'] != today] + [row]   # 同日重跑覆蓋
prev_eq = None
for r in rows:
    if r['date'] < today:
        prev_eq = float(r['equity'])
day_chg = round(equity - prev_eq) if prev_eq is not None else open_pnl
with open(CSV, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

sign = lambda v: f'+{v:,.0f}' if v >= 0 else f'−{abs(v):,.0f}'
line = (f"📒 前向測試({today})\n"
        f"持倉:{'空' if pos < 0 else '多'} {abs(pos)} 張 @ {entry:,}(mark {mark:,})\n"
        f"今日損益 {sign(day_chg)} · 浮動 {sign(open_pnl)} · 已實現 {sign(realized)}\n"
        f"權益 {equity:,.0f}(本金 {p['capital']:,},含費用 −{fees:,})")
# 承諾資金/帳戶資金分開(RULES.md):帳戶淨值 = 承諾權益 − 場外儲備,檢查補倉觸發線
fd = p.get('funding') or {}
if fd.get('active'):
    lots = max(1, int(equity // 1_500_000))
    acct = equity - fd.get('reserve', 0)
    line += f"\n🏦 帳戶 {acct:,.0f}(場外儲備 {fd.get('reserve', 0):,.0f};觸發線 {200_000 * lots:,})"
    if acct < 200_000 * lots:
        line += (f"\n⚠️ 需補倉 {300_000 * lots - acct:,.0f} 到帳戶"
                 f"(下一交易日 12:00 前;富途通知較早則以富途為準)")
    elif acct > 400_000 * lots:
        line += f"\n💡 月底可提回儲備 {acct - 300_000 * lots:,.0f}(只在每月最後交易日執行)"
with open(LINE, 'w', encoding='utf-8') as f:
    f.write(line)
print(line)
