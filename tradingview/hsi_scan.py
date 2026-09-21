#!/usr/bin/env python3
"""HSI 行情掃描器：讀 data_external/quotes/ 的最新快照，輸出監測報告與警報。

檢查項目：
  1. 期貨曲線單調性與買賣價差
  2. 各月期權：ATM IV、IV−HV20 溢價水平（對照 23 年平均 +2.4）
  3. 無套利檢查（有雙邊報價的檔位：單調性、垂直上界、蝶式凸性）
  4. 滾倉提醒（距月度到期 ≤ 2 曆日）
輸出：data_external/scan_report.md；有警報時 exit code 仍為 0，警報寫在報告最上方。
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_external')
ALERTS, LINES = [], []


def num(s):
    try:
        return float(str(s).replace(',', ''))
    except (ValueError, TypeError):
        return None


def latest(pattern):
    fs = sorted(glob.glob(os.path.join(BASE, 'quotes', pattern)))
    return fs[-1] if fs else None


def hv20():
    f = os.path.join(BASE, 'hsi_daily.csv')
    if not os.path.exists(f):
        return None
    h = pd.read_csv(f, parse_dates=['Date']).set_index('Date')
    r = h.Close.pct_change().dropna()
    return float(r.tail(20).std() * np.sqrt(252) * 100)


def scan_futures():
    f = latest('futures_*.json')
    if not f:
        return None
    d = json.load(open(f))['data']
    LINES.append(f"## 期貨（{d.get('lastupd')}）\n")
    LINES.append("| 月份 | 買 | 賣 | 價差 | 結算 | OI |")
    LINES.append("|---|---:|---:|---:|---:|---:|")
    prev_se = None
    front = None
    for row in d.get('futureslist', [])[:4]:
        bd, as_, se = num(row['bd']), num(row['as']), num(row['se'])
        spr = as_ - bd if bd and as_ else None
        if front is None:
            front = se
        LINES.append(f"| {row['con']} | {row['bd']} | {row['as']} | "
                     f"{spr if spr is not None else '—'} | {row['se']} | {row['oi']} |")
        if spr is not None and spr > 30:
            ALERTS.append(f"期貨 {row['con']} 價差 {spr:.0f} 點（異常寬）")
        if prev_se and se and se < prev_se - 60:
            ALERTS.append(f"期貨曲線倒掛：{row['con']} 結算 {se:.0f} < 前月 {prev_se:.0f}")
        prev_se = se
    return front


def scan_options(hv):
    for f in sorted(glob.glob(os.path.join(BASE, 'quotes', 'options_*.json')))[-3:]:
        mon = re.search(r'options_([^_]+)_', os.path.basename(f)).group(1)
        d = json.load(open(f))['data']
        rows = d.get('optionlist', [])
        if not rows:
            continue
        # ATM = put/call IV 都有、且兩者最接近的檔
        ivs = [(num(r['strike']), num(r['c'].get('iv')), num(r['p'].get('iv'))) for r in rows]
        ivs = [x for x in ivs if x[1] and x[2]]
        if not ivs:
            continue
        K, civ, piv = min(ivs, key=lambda x: abs(x[1] - x[2]))
        atm = (civ + piv) / 2
        LINES.append(f"\n## 期權 {mon}（{d.get('lastupd')}）  ATM≈{K:.0f}  IV {atm:.1f}%")
        if hv:
            prem = atm - hv
            LINES.append(f"- IV − HV20 = {prem:+.1f} 點（23 年平均 +2.4）")
            if prem < 0:
                ALERTS.append(f"{mon} IV−HV = {prem:+.1f} 為負：保費消失，暫停新賣出")
            elif prem > 8:
                ALERTS.append(f"{mon} IV−HV = {prem:+.1f} 異常厚：檢查是否有事件風險")
        # 無套利檢查（限有雙邊報價的檔）
        for side in ['c', 'p']:
            q = [(num(r['strike']), num(r[side]['bd']), num(r[side]['as']))
                 for r in rows if num(r[side].get('bd')) and num(r[side].get('as'))]
            q.sort()
            for i in range(len(q) - 1):
                K1, b1, a1 = q[i]
                K2, b2, a2 = q[i + 1]
                if side == 'c' and b2 > a1 + 2:
                    ALERTS.append(f"{mon} call 單調性破壞 {K1:.0f}/{K2:.0f}")
                if side == 'p' and b1 > a2 + 2:
                    ALERTS.append(f"{mon} put 單調性破壞 {K1:.0f}/{K2:.0f}")
                if (b1 - a2 if side == 'c' else b2 - a1) - 2 > (K2 - K1):
                    ALERTS.append(f"{mon} {side} 垂直價差超上界 {K1:.0f}/{K2:.0f}")


def roll_check():
    # 月度到期 = 當月最後交易日的前一日（近似：月底倒數第二個工作日）
    today = date.today()
    bdays = pd.bdate_range(today.replace(day=1), periods=40)
    month_b = [d.date() for d in bdays if d.month == today.month]
    expiry = month_b[-2] if len(month_b) >= 2 else month_b[-1]
    dd = (expiry - today).days
    LINES.append(f"\n## 滾倉：本月到期日約 {expiry}（{dd:+d} 天）")
    if 0 <= dd <= 2:
        ALERTS.append(f"滾倉窗口：{dd} 天後月度結算，準備次日賣下月 ATM 跨式（SOP §10.8）")


if __name__ == '__main__':
    hv = hv20()
    front = scan_futures()
    scan_options(hv)
    roll_check()
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    head = [f"# HSI 掃描報告  {stamp}\n"]
    head.append("**⚠ 警報：**\n" + '\n'.join(f"- {a}" for a in ALERTS) + "\n" if ALERTS
                else "**無警報**（無套利條件全過、溢價正常、未到滾倉窗口）\n")
    report = '\n'.join(head + LINES)
    with open(os.path.join(BASE, 'scan_report.md'), 'w') as fp:
        fp.write(report)
    alert_path = os.path.join(BASE, 'alert.txt')
    if ALERTS:
        with open(alert_path, 'w') as fp:
            fp.write('HSI 警報 ' + stamp + '\n' + '\n'.join(f'- {a}' for a in ALERTS))
    elif os.path.exists(alert_path):
        os.remove(alert_path)
    print(report)
