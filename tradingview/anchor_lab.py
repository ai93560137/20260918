#!/usr/bin/env python3
"""月度腿做錨（2026-09-25）。

問題：月度腿受傷到某個層面（對沖變頻、浮虧過半、觸止損）時，
市場處於什麼狀態？那之後有什麼機會？

方法：月度模擬逐月記錄
  iv_rise = 持有期內波指最高點 − 進場 IV（警戒探針）
  rv>iv0  = 實現波動壓過進場 IV（≈ 對沖變頻的月份）
  pnl<=−prem = 觸及止損等級的月份（買回 2x 權利金）
然後看「事件月的下一個月」短跨式表現與進場條件——機會是否真的變肥。
"""
import numpy as np
import pandas as pd

D = 'data_external'
VEGA = 0.8 * np.sqrt(21 / 252)


def monthly(vol_csv, px_csv, cost):
    iv = pd.read_csv(f'{D}/{vol_csv}', parse_dates=['Date']).set_index('Date').Close
    px = pd.read_csv(f'{D}/{px_csv}', parse_dates=['Date']).set_index('Date').Close
    df = pd.concat([iv.rename('iv'), px.rename('px')], axis=1, sort=True).dropna()
    df['r'] = np.log(df.px).diff()
    df['hv20'] = df.r.rolling(20).std() * np.sqrt(252) * 100
    df = df.dropna()
    rows = []
    for d0 in df.groupby(df.index.to_period('M')).head(1).index:
        i0 = df.index.get_loc(d0)
        if i0 + 21 >= len(df):
            break
        w = df.iloc[i0:i0 + 22]
        iv0 = w.iv.iloc[0]
        rv = w.r.iloc[1:].std() * np.sqrt(252) * 100
        rows.append(dict(month=str(d0.to_period('M')), iv0=iv0,
                         spread=iv0 - w.hv20.iloc[0],
                         iv_rise=w.iv.iloc[1:].max() - iv0,
                         idx_chg=(w.px.iloc[-1] / w.px.iloc[0] - 1) * 100,
                         rv=rv, prem=VEGA * iv0,
                         pnl=VEGA * (iv0 - rv) - cost * VEGA))
    return pd.DataFrame(rows)


def nextm(m, mask, label):
    idx = np.where(mask.values[:-1])[0] + 1          # 事件月的下一個月
    s = m.pnl.iloc[idx]
    if len(s) < 8:
        print(f"{label:<26} 樣本 {len(s)} 太少")
        return
    t = s.mean() / s.std() * np.sqrt(len(s))
    print(f"{label:<26} N={len(s):>3}  下月均 {s.mean():+5.2f}%  t={t:+4.1f}  "
          f"勝率 {(s > 0).mean() * 100:3.0f}%  下月進場IV {m.iv0.iloc[idx].mean():5.1f}  "
          f"權利金 {m.prem.iloc[idx].mean():4.2f}%")


for name, v, p, c in [('恒指 HSI', 'vhsi_daily.csv', 'hsi_daily.csv', 0.12),
                      ('美股 SPX', 'vix_daily.csv', 'spx_daily.csv', 0.056)]:
    m = monthly(v, p, c)
    print(f"\n=== {name}  {len(m)} 月 ===")
    nextm(m, pd.Series(True, index=m.index), '基準（所有月份）')
    nextm(m, m.iv_rise >= 5, '事件：月內波指 +5 點')
    nextm(m, m.iv_rise >= 10, '事件：月內波指 +10 點')
    nextm(m, m.rv > m.iv0, '事件：RV壓過進場IV(頻對沖)')
    nextm(m, m.pnl <= -0.5 * m.prem, '事件：浮虧過半權利金')
    nextm(m, m.pnl <= -m.prem, '事件：觸止損等級(虧>1x)')
    # 事件月當下的市況畫像
    for lab, mask in [('波指+10 的月份', m.iv_rise >= 10), ('止損等級月份', m.pnl <= -m.prem)]:
        e = m[mask]
        if len(e):
            print(f"  [{lab}畫像] 指數平均 {e.idx_chg.mean():+.1f}%  "
                  f"RV 平均 {e.rv.mean():.0f}(進場IV {e.iv0.mean():.0f})  共 {len(e)} 次")
