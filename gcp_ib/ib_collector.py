#!/usr/bin/env python3
"""IB 數據採集器 v1（2026-09-25）—— 跑在使用者的 GCP VM / 本機，不在沙盒。

目的：用 IB 延遲數據（免訂閱費，reqMarketDataType(3)）每日記錄
  日經 N225（OSE）與 EURO STOXX 50（EUREX）的
  最近週權 vs 最近月權 ATM IV → 期限結構斜率 → 併入雲垂陣金絲雀/週度腿研究。
監測數據永不用於下單（下單以券商實時報價為準）。

前置：IB Gateway 已登入（paper 埠 4002 / live 4001），pip install ib_insync。
用法：python ib_collector.py            # 採集並追加 CSV
      python ib_collector.py --dry      # 只列出發現的鏈，不寫檔（首次調試用）
輸出：../tradingview/data_external/ib_iv_log.csv（由 push_repo.sh 推回 GitHub）
"""
import argparse
import math
import sys
from datetime import date, datetime

from ib_insync import IB, Index, Option

MARKETS = [
    # (標籤, Index 參數, 期權 exchange, tradingClass 候選——None=用 reqSecDefOptParams 全部)
    ('N225', dict(symbol='N225', exchange='OSE.JPN', currency='JPY'), 'OSE.JPN'),
    ('ESTX50', dict(symbol='ESTX50', exchange='EUREX', currency='EUR'), 'EUREX'),
]


def mid_or_last(t):
    if t.bid and t.ask and t.bid > 0 and t.ask > 0:
        return (t.bid + t.ask) / 2
    return t.last if t.last and t.last > 0 else None


def iv_of(ib, opt, spot):
    """優先用 IB 的 modelGreeks IV；沒有就用中間價反推 Black-76 IV。
    延遲數據要等幾秒才灌進 ticker，輪詢最多 ~16 秒。"""
    tk = ib.reqMktData(opt, '', False, False)
    prem = None
    for _ in range(4):
        ib.sleep(4)
        g = tk.modelGreeks
        if g and g.impliedVol and 0.01 < g.impliedVol < 3:
            ib.cancelMktData(opt)
            return round(g.impliedVol * 100, 2)
        prem = mid_or_last(tk)
    ib.cancelMktData(opt)
    if not prem:
        return None
    dte = (datetime.strptime(opt.lastTradeDateOrContractMonth[:8], '%Y%m%d').date()
           - date.today()).days
    T = max(dte, 1) / 365
    K, F, right = float(opt.strike), spot, opt.right

    def px(sigma):
        d1 = (math.log(F / K) + sigma * sigma * T / 2) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        N = lambda x: (1 + math.erf(x / math.sqrt(2))) / 2
        c = F * N(d1) - K * N(d2)
        return c if right == 'C' else c + K - F
    lo, hi = 0.01, 3.0
    for _ in range(60):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if px(m) < prem else (lo, m)
    return round((lo + hi) / 2 * 100, 2)


def pick_expiries(exps):
    """回傳 (短腿 1–14 天, 長腿 15–60 天) 到期字串——N225 只有月權時
    取最近兩個月度也能量斜率。長窗落空就取短腿之後最近的一個。"""
    today = date.today()
    parsed = sorted((datetime.strptime(e, '%Y%m%d').date(), e) for e in exps)
    dtes = [((d - today).days, e) for d, e in parsed]
    wk = next((e for dd, e in dtes if 1 <= dd <= 14), None)
    mon = next((e for dd, e in dtes if 15 <= dd <= 60), None)
    if wk and mon is None:
        mon = next((e for dd, e in dtes if dd > 14), None)
    return wk, mon


def atm_pair_iv(ib, label, und, opt_exch, expiry, spot, chains, dry):
    """ATM (c+p)/2 IV。月權行使價網格較疏（如 Eurex 週權 5 點/月權 25 點），
    同一鏈的 strikes 是全到期聯集——挑中的檔位不一定在該到期掛牌，
    所以按距離試最多 6 檔，qualify 不到就跳下一檔。"""
    ch = next((c for c in chains if c.exchange == opt_exch and expiry in c.expirations), None)
    if not ch:
        return None
    for strike in sorted(ch.strikes, key=lambda k: abs(k - spot))[:6]:
        ivs = []
        for right in ('C', 'P'):
            o = Option(und.symbol, expiry, strike, right, opt_exch,
                       currency=und.currency, tradingClass=ch.tradingClass)
            try:
                if not ib.qualifyContracts(o):
                    break
                iv = iv_of(ib, o, spot)
                if dry:
                    print(f"  {label} {expiry} {strike}{right}: iv={iv}")
                if iv:
                    ivs.append(iv)
            except Exception as e:
                print(f"  {label} {expiry} {strike}{right} ERR: {e}")
                break
        if len(ivs) == 2:
            return (round(sum(ivs) / 2, 2), strike)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--port', type=int, default=4002)   # paper 4002 / live 4001
    a = ap.parse_args()
    ib = IB()
    ib.connect('127.0.0.1', a.port, clientId=17, timeout=20)
    ib.reqMarketDataType(3)                              # 延遲數據，免訂閱
    rows = []
    for label, params, opt_exch in MARKETS:
        try:
            und = Index(**params)
            ib.qualifyContracts(und)
            [ut] = ib.reqTickers(und)
            spot = mid_or_last(ut) or ut.close
            chains = ib.reqSecDefOptParams(und.symbol, '', und.secType, und.conId)
            exps = sorted({e for c in chains if c.exchange == opt_exch for e in c.expirations})
            wk, mon = pick_expiries(exps)
            print(f"{label}: spot {spot}  wk {wk}  mon {mon}  ({len(exps)} expiries)")
            if a.dry:
                print(f"  expiries: {exps[:12]}")
            w = atm_pair_iv(ib, label, und, opt_exch, wk, spot, chains, a.dry) if wk else None
            m = atm_pair_iv(ib, label, und, opt_exch, mon, spot, chains, a.dry) if mon else None
            if w and m:
                dte_w = (datetime.strptime(wk, '%Y%m%d').date() - date.today()).days
                dte_m = (datetime.strptime(mon, '%Y%m%d').date() - date.today()).days
                rows.append(f"{date.today()},{label},{spot:.1f},{wk},{dte_w},{w[1]:.0f},{w[0]},"
                            f"{mon},{dte_m},{m[1]:.0f},{m[0]},{round(m[0] - w[0], 2)}")
        except Exception as e:
            print(f"{label} ERR: {e}")
    ib.disconnect()
    if a.dry or not rows:
        print('dry run or no rows - nothing written')
        return
    import os
    logf = os.path.join(os.path.dirname(__file__) or '.',
                        '..', 'tradingview', 'data_external', 'ib_iv_log.csv')
    new = not os.path.exists(logf)
    with open(logf, 'a') as f:
        if new:
            f.write('date,market,spot,wk_exp,wk_dte,wk_atm,wk_iv,mon_exp,mon_dte,mon_atm,mon_iv,slope\n')
        f.write('\n'.join(rows) + '\n')
    print('\n'.join(rows))


if __name__ == '__main__':
    sys.exit(main())
