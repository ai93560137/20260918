#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 levels.json 組出八陣圖指令台的 Telegram 每日訊息,寫入 .github/tg_outbox.txt。

用法: python3 .github/scripts/compose_tg.py [--out PATH]
session 每日排程(12:00 / 16:45 HKT)更新完通道後執行,commit+push 即經
send-telegram.yml 發送。
"""
import argparse
import json
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--out', default='.github/tg_outbox.txt')
ap.add_argument('--src', default='tradingview/data_external/levels.json')
a = ap.parse_args()

d = json.load(open(a.src, encoding='utf-8'))
h = d.get('hsi') or {}
if 'error' in h or h.get('h1') is None:
    print(f"levels.json 無可用 hsi 數據: {h.get('error', 'h1 missing')}", file=sys.stderr)
    sys.exit(1)

hs = [h['h1'], h['h2'], h['h3']]
ls = [h['l1'], h['l2'], h['l3']]
dates = [s[5:].replace('-', '-') for s in h['dates']]        # YYYY-MM-DD → MM-DD
up, up_d = max(zip(hs, dates))
lo, lo_d = min(zip(ls, dates))
f = lambda v: f'{v:,.0f}'

q = h.get('quote') or {}
px = q.get('px')
quote_line = (f"💰 現價:{f(px)}({q.get('kind', '')} · {q.get('asof', '')},延遲≥15分鐘)\n"
              f"↕️ 距上軌 {f(up - px)} 點 · 距下軌 {f(px - lo)} 點\n") if px else ''

msg = f"""🐍 八陣圖 · 蛇蟠陣 · 大恒指 HSI
🕐 {d.get('fetched_at', '')}

📊 前 3 個完整交易日
📅 {dates[0]}:🔼 {f(hs[0])} ／ 🔽 {f(ls[0])}
📅 {dates[1]}:🔼 {f(hs[1])} ／ 🔽 {f(ls[1])}
📅 {dates[2]}:🔼 {f(hs[2])} ／ 🔽 {f(ls[2])}

📈 通道上軌:{f(up)}({up_d})
📉 通道下軌:{f(lo)}({lo_d})
{quote_line}
🧭 今日指令(每次 1 張)
🈳 空手:
 ① 價 ≥ {f(up)} → 市價買入 1 張(開多倉)
 ② 價 ≤ {f(lo)} → 市價賣出 1 張(開空倉)
🐂 持 1 張多倉:
 ▶ 價 ≤ {f(lo)} → 市價賣出 2 張(平多＋反手做空)
🐻 持 1 張空倉:
 ▶ 價 ≥ {f(up)} → 市價買入 2 張(平空＋反手做多)

⚠️ 成交以券商實時價為準
🌐 恒指指令台:https://claude.ai/artifact/Qovghgidoao32zWai3gffX
"""

g = d.get('mgc') or {}
if g.get('h1') is not None:
    gh = [g['h1'], g['h2'], g['h3']]
    gl = [g['l1'], g['l2'], g['l3']]
    gd = [s[5:] for s in g['dates']]
    gup, gup_d = max(zip(gh, gd))
    glo, glo_d = min(zip(gl, gd))
    g1 = lambda v: f'{v:,.1f}'
    gq = g.get('quote') or {}
    gpx = gq.get('px')
    gq_line = (f"💰 現價:{g1(gpx)}({gq.get('kind', '')} · {gq.get('asof', '')})\n"
               f"↕️ 距上軌 {g1(gup - gpx)} · 距下軌 {g1(gpx - glo)}\n") if gpx else ''
    fu = g.get('fut') or {}
    if fu.get('h1') is not None:
        fup = max(fu['h1'], fu['h2'], fu['h3'])
        flo = min(fu['l1'], fu['l2'], fu['l3'])
        fq = (fu.get('quote') or {}).get('px')
        mgc_line = (f"🧭 MGC 期貨口徑{'(期貨現價 ' + g1(fq) + ')' if fq else ''}:"
                    f"空手 ①價 ≥ {g1(fup)} → 買 1 張;②價 ≤ {g1(flo)} → 賣 1 張;持倉觸反向軌 → 雙倍反手")
    else:
        mgc_line = (f"🧭 MGC 多空雙向:空手 ①價 ≥ {g1(gup)} → 買 1 張;"
                    f"②價 ≤ {g1(glo)} → 賣 1 張;持倉觸反向軌 → 雙倍反手")
    msg += f"""
──────────────
🥇 黃金(微型金 MGC ／ ETF 只做多)

📈 現貨通道上軌:{g1(gup)}({gup_d})
📉 現貨通道下軌:{g1(glo)}({glo_d})
{gq_line}
{mgc_line}
🧭 ETF 只做多(現貨口徑):升破 {g1(gup)} → 買入;跌破 {g1(glo)} → 只平倉不做空
🌐 黃金指令台:https://claude.ai/artifact/26ZLBsaqoMFKoAxsD7E1iw
"""

with open(a.out, 'w', encoding='utf-8') as fp:
    fp.write(msg)
print(msg)
