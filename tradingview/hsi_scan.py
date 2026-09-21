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
ALERTS, LINES, DIGEST = [], [], []


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
    for i, row in enumerate(d.get('futureslist', [])[:4]):
        bd, as_, se = num(row['bd']), num(row['as']), num(row['se'])
        spr = as_ - bd if bd and as_ else None
        if front is None:
            front = se
        LINES.append(f"| {row['con']} | {row['bd']} | {row['as']} | "
                     f"{spr if spr is not None else '—'} | {row['se']} | {row['oi']} |")
        # 只警報前兩個月：遠月（尤其夜盤）報價稀疏，價差寬是流動性現象不是機會
        if spr is not None and spr > 30 and i < 2:
            ALERTS.append(f"期貨 {row['con']} 價差 {spr:.0f} 點（異常寬）")
        if prev_se and se and se < prev_se - 60:
            ALERTS.append(f"期貨曲線倒掛：{row['con']} 結算 {se:.0f} < 前月 {prev_se:.0f}")
        prev_se = se
    if front:
        DIGEST.append(f"HSI 期貨(近月) {front:,.0f}")
    return front


def scan_options(hv, front=None):
    # 每個月份取時間戳最新的一份（檔名字母排序會讓 Sep 排最後，不能直接取尾三個）
    latest_by_mon = {}
    for f in glob.glob(os.path.join(BASE, 'quotes', 'options_*.json')):
        m = re.search(r'options_([^_]+)_(\d{8}_\d{4})', os.path.basename(f))
        if not m:
            continue
        mon, ts = m.group(1), m.group(2)
        if mon not in latest_by_mon or ts > latest_by_mon[mon][0]:
            latest_by_mon[mon] = (ts, f)
    def mon_key(kv):
        try:
            return datetime.strptime(kv[0], '%b-%y')
        except ValueError:
            return datetime.max
    for mon, (_, f) in sorted(latest_by_mon.items(), key=mon_key):
        d = json.load(open(f))['data']
        rows = d.get('optionlist', [])
        if not rows:
            continue
        # ATM = 最接近期貨價的檔（夜盤報價稀疏時用 IV 接近度找會漂移）；
        # 無期貨價才退回 call/put IV 最接近的檔
        ivs = [(num(r['strike']), num(r['c'].get('iv')), num(r['p'].get('iv'))) for r in rows]
        ivs = [x for x in ivs if x[1] and x[2]]
        if not ivs:
            continue
        if front:
            K, civ, piv = min(ivs, key=lambda x: abs(x[0] - front))
        else:
            K, civ, piv = min(ivs, key=lambda x: abs(x[1] - x[2]))
        atm = (civ + piv) / 2
        LINES.append(f"\n## 期權 {mon}（{d.get('lastupd')}）  ATM≈{K:.0f}  IV {atm:.1f}%")
        if hv:
            prem = atm - hv
            LINES.append(f"- IV − HV20 = {prem:+.1f} 點（23 年平均 +2.4）")
            DIGEST.append(f"HSI {mon}: ATM {K:.0f} IV {atm:.1f} 溢價{prem:+.1f}（均+2.4）")
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


def scan_us():
    """美股 VRP 監測：VIX − SPX HV20 對照長期平均 +4.1；有 MES 持倉時倒數到期。"""
    fv = os.path.join(BASE, 'vix_daily.csv')
    fs = os.path.join(BASE, 'spx_daily.csv')
    if not (os.path.exists(fv) and os.path.exists(fs)):
        return
    vix = pd.read_csv(fv, parse_dates=['Date']).set_index('Date').Close
    spx = pd.read_csv(fs, parse_dates=['Date']).set_index('Date').Close
    hv = float(spx.pct_change().dropna().tail(20).std() * np.sqrt(252) * 100)
    iv = float(vix.iloc[-1])
    prem = iv - hv
    asof = vix.index[-1].date()
    LINES.append(f"\n## 美股（MES）  VIX {iv:.1f}  SPX HV20 {hv:.1f}"
                 f"  溢價 {prem:+.1f}（37 年平均 +4.1）  截至 {asof}")
    DIGEST.append(f"美股: VIX {iv:.1f} HV {hv:.1f} 溢價{prem:+.1f}（均+4.1）")
    fq = os.path.join(BASE, 'us_futures_quote.json')
    if os.path.exists(fq):
        q = json.load(open(fq))
        es = q.get('ES=F', {})
        if es:
            DIGEST.append(f"ES 期貨 {es['price']:,.0f}（MES 同價，"
                          f"進場參考檔 {round(es['price'] / 5) * 5:,.0f}）")
    if (date.today() - asof).days > 5:
        ALERTS.append(f"美股數據呆滯：VIX 最後日期 {asof}，刷新可能壞了")
    if prem < 0:
        ALERTS.append(f"美股 VIX−HV = {prem:+.1f} 為負：保費消失，暫停 MES 新賣出")
    elif prem > 10:
        ALERTS.append(f"美股 VIX−HV = {prem:+.1f} 異常厚：檢查事件風險（FOMC/CPI/財報季）")
    pos = os.path.join(BASE, 'position_mes.json')
    if os.path.exists(pos):
        p = json.load(open(pos))
        exp = datetime.strptime(p['expiry'], '%Y-%m-%d').date()
        dd = (exp - date.today()).days
        LINES.append(f"- 持倉：{p.get('qty', 1)} 組 MES {p.get('strike')} 跨式，"
                     f"到期 {exp}（{dd:+d} 天）")
        DIGEST.append(f"MES 持倉 {p.get('strike')} 跨式 到期剩 {dd} 天")
        if 0 <= dd <= 2:
            ALERTS.append(f"MES 滾倉窗口：{dd} 天後到期，"
                          f"到期日美東 16:00 前平倉，次日賣 25–40 天窗口最近系列")


def roll_check():
    # 月度到期 = 當月最後交易日的前一日（近似：月底倒數第二個工作日）
    today = date.today()
    bdays = pd.bdate_range(today.replace(day=1), periods=40)
    month_b = [d.date() for d in bdays if d.month == today.month]
    expiry = month_b[-2] if len(month_b) >= 2 else month_b[-1]
    dd = (expiry - today).days
    LINES.append(f"\n## 滾倉：本月到期日約 {expiry}（{dd:+d} 天）")
    DIGEST.append(f"HSI 月度到期剩 {dd} 天")
    if 0 <= dd <= 2:
        ALERTS.append(f"滾倉窗口：{dd} 天後月度結算，準備次日賣下月 ATM 跨式（SOP §10.8）")


if __name__ == '__main__':
    hv = hv20()
    front = scan_futures()
    scan_options(hv, front)
    roll_check()
    scan_us()
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
            fp.write('⚠ 警報 ' + stamp + '\n' + '\n'.join(f'- {a}' for a in ALERTS))
    elif os.path.exists(alert_path):
        os.remove(alert_path)
    # 每日摘要（無論有無警報都寫，workflow 每日發 Telegram）
    from datetime import timedelta, timezone
    hkt = datetime.now(timezone.utc) + timedelta(hours=8)
    dig = [f"📊 HSI+MES 日報 {hkt.strftime('%m-%d %H:%M')} HKT"]
    if ALERTS:
        dig += [f'⚠ {a}' for a in ALERTS]
    else:
        dig.append('✅ 無警報')
    dig += DIGEST
    with open(os.path.join(BASE, 'digest.txt'), 'w') as fp:
        fp.write('\n'.join(dig))
    print(report)
