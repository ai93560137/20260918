"""恒指週權 IV 記錄儀（2026-09-25，管道 ats=HSIW 由 probe_hsi_weekly 確認）。
每日記一筆：最近週權 ATM (c_iv+p_iv)/2 vs 最近月權（≥15 天）同法，
斜率 = 月 − 週 = 折讓 h 的恒指實測。輸出 hsi_weekly_iv_log.csv。
只測量，不下單。"""
import glob
import json
import os
import re
import time
from datetime import date, datetime

import requests

D = 'tradingview/data_external'
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
     'Referer': 'https://www.hkex.com.hk/'}
page = requests.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                    'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en',
                    headers=H, timeout=30).text
token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)


def call(ep, **kw):
    qid = str(int(time.time() * 1000))
    q = '&'.join(f'{k}={v}' for k, v in kw.items())
    u = (f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}'
         f'&{q}&qid={qid}&callback=j')
    body = requests.get(u, headers=H, timeout=30).text
    return json.loads(body[body.index('(') + 1:body.rindex(')')])


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (ValueError, TypeError):
        return None


def atm_iv(optionlist, front):
    best, iv = None, None
    for row in optionlist:
        k = num(row.get('strike'))
        civ, piv = num(row.get('c', {}).get('iv')), num(row.get('p', {}).get('iv'))
        if k is None or civ is None or piv is None:
            continue
        if best is None or abs(k - front) < abs(best - front):
            best, iv = k, round((civ + piv) / 2, 2)
    return best, iv


# 期貨中間價（front）
fut = call('getderivativesfutures', ats='HSI', type=0)
f0 = (fut.get('data', {}).get('futureslist') or [{}])[0]
bd, ask = num(f0.get('bd')), num(f0.get('as'))
front = (bd + ask) / 2 if bd and ask else num(f0.get('se'))

# 週權：最近 dte>=1 的到期
cl = call('getoptioncontractlist', ats='HSIW', type=0)
cands = []
for c in cl.get('data', {}).get('conlist', []):
    cid = c.get('id', '')
    try:
        exp = datetime.strptime(cid, '%d%m%Y').date()
    except ValueError:
        continue
    dte = (exp - date.today()).days
    if dte >= 1:
        cands.append((dte, cid, exp))
dte, cid, exp = sorted(cands)[0]
opt = call('getderivativesoption', ats='HSIW', con=cid, fr='null', to='null', type=0)
wk_atm, wk_iv = atm_iv(opt.get('data', {}).get('optionlist', []), front)

# 月權：當天快照裡剩餘 >=15 天的最近月份（fetch_hkex_quotes 已先跑）
mon_label, mon_atm, mon_iv = None, None, None
byname = {}
for f in sorted(glob.glob(f'{D}/quotes_colab/options_*.json')):
    m = re.match(r'options_(.+)_(\d{8}_\d{4})\.json', os.path.basename(f))
    if m:
        byname[m.group(1)] = f          # 同月留最新 stamp
best_dte = None
for label, f in byname.items():
    try:
        expm = datetime.strptime('01-' + label, '%d-%b-%y').date()
        expm = date(expm.year + expm.month // 12, expm.month % 12 + 1, 1)  # 月底≈次月1日
        dtem = (expm - date.today()).days
    except ValueError:
        continue
    if dtem >= 15 and (best_dte is None or dtem < best_dte):
        js = json.load(open(f))
        a, i = atm_iv(js.get('data', {}).get('optionlist', []), front)
        if i:
            best_dte, mon_label, mon_atm, mon_iv = dtem, label, a, i

if wk_iv and mon_iv and front:
    logf = f'{D}/hsi_weekly_iv_log.csv'
    new = not os.path.exists(logf)
    with open(logf, 'a') as f:
        if new:
            f.write('date,front,wk_exp,wk_dte,wk_atm,wk_iv,mon,mon_atm,mon_iv,slope\n')
        f.write(f"{date.today()},{front:.0f},{exp},{dte},{wk_atm:.0f},{wk_iv},"
                f"{mon_label},{mon_atm:.0f},{mon_iv},{round(mon_iv - wk_iv, 2)}\n")
    print(f"HSIW {exp} ({dte}d) ATM {wk_atm:.0f} IV {wk_iv} | "
          f"{mon_label} ATM {mon_atm:.0f} IV {mon_iv} | slope {mon_iv - wk_iv:+.2f}")
else:
    print(f"incomplete: front={front} wk_iv={wk_iv} mon_iv={mon_iv} - not logged")
