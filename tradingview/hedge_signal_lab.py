#!/usr/bin/env python3
"""週權當儀表（2026-09-25）：期限結構斜率能否幫動態對沖？

slope = VIX9D − VIX（週權 IV − 月權 IV 的代理，2011 起 14 年）。
正常市場 slope < 0（週權便宜）；倒掛 slope > 0 = 市場為「即刻的大動作」付錢。

測三件事：
  A. slope 分五檔 → 未來 5 天 RV、RV−VIX（實現壓過我們賣出的 IV = 受傷週）
  B. 對沖負載：未來 5 天 |日變動|>1% / >1.5% 的天數（帶狀過界頻率的代理）
  C. 警報質量：倒掛日之後 5 天內出現 >2% 單日下跌的機率 vs 無條件；災難月
     進場前 5 天有無倒掛（有預警力嗎）；誤報率
"""
import numpy as np
import pandas as pd

D = 'data_external'
v9 = pd.read_csv(f'{D}/vix9d_daily.csv', parse_dates=['Date']).set_index('Date').Close
vx = pd.read_csv(f'{D}/vix_daily.csv', parse_dates=['Date']).set_index('Date').Close
px = pd.read_csv(f'{D}/spx_daily.csv', parse_dates=['Date']).set_index('Date').Close
df = pd.concat([v9.rename('v9'), vx.rename('vix'), px.rename('px')], axis=1, sort=True).dropna()
df['slope'] = df.v9 - df.vix
df['r'] = np.log(df.px).diff()
n = len(df)
fwd_rv, fwd_big1, fwd_big15, fwd_dn2 = [], [], [], []
for i in range(n):
    w = df.r.iloc[i + 1:i + 6]
    if len(w) < 5:
        fwd_rv.append(np.nan); fwd_big1.append(np.nan)
        fwd_big15.append(np.nan); fwd_dn2.append(np.nan)
        continue
    fwd_rv.append(w.std() * np.sqrt(252) * 100)
    fwd_big1.append((w.abs() > 0.01).sum())
    fwd_big15.append((w.abs() > 0.015).sum())
    fwd_dn2.append(int((w < -0.02).any()))
df['fwd_rv'], df['big1'], df['big15'], df['dn2'] = fwd_rv, fwd_big1, fwd_big15, fwd_dn2
df = df.dropna()

print(f"樣本 {len(df)} 日（{df.index[0].date()} → {df.index[-1].date()}）")
print(f"slope 分布：中位 {df.slope.median():+.2f}  倒掛(>0)日佔 {(df.slope > 0).mean()*100:.0f}%")

print("\nA/B. slope 五檔 → 未來 5 天（RV、受傷度、對沖負載）")
df['q'] = pd.qcut(df.slope, 5, labels=['最平(便宜)', 'Q2', 'Q3', 'Q4', '最陡(倒掛)'])
g = df.groupby('q', observed=True)
tab = pd.DataFrame({'slope均': g.slope.mean(), 'VIX均': g.vix.mean(),
                    '未來5日RV': g.fwd_rv.mean(), 'RV−VIX': (g.fwd_rv.mean() - g.vix.mean()),
                    '>1%天數': g.big1.mean(), '>1.5%天數': g.big15.mean(),
                    '週內見-2%日%': g.dn2.mean() * 100})
print(tab.round(2).to_string())

inv = df.slope > 0
print(f"\nC. 倒掛日警報質量（{inv.sum()} 日）")
print(f"  倒掛→5天內見 -2% 單日：{df.dn2[inv].mean()*100:.0f}%   無條件：{df.dn2.mean()*100:.0f}%"
      f"   提升 {df.dn2[inv].mean()/df.dn2.mean():.1f}x")
print(f"  誤報率（倒掛但整週平靜，無 >1.5% 日）：{(df.big15[inv] == 0).mean()*100:.0f}%")
print(f"  倒掛日未來5日RV {df.fwd_rv[inv].mean():.1f} vs 非倒掛 {df.fwd_rv[~inv].mean():.1f}")

# 災難月前的預警：月度模擬中虧>1x權利金的月份，進場前 5 天最大 slope
VEGA = 0.8 * np.sqrt(21 / 252)
firsts = df.groupby(df.index.to_period('M')).head(1).index
hits, miss = [], []
for d0 in firsts:
    i0 = df.index.get_loc(d0)
    if i0 + 21 >= len(df) or i0 < 5:
        continue
    iv0 = df.vix.iloc[i0]
    rv = df.r.iloc[i0 + 1:i0 + 22].std() * np.sqrt(252) * 100
    pnl = VEGA * (iv0 - rv)
    if pnl <= -VEGA * iv0:
        pre = df.slope.iloc[i0 - 5:i0 + 1].max()
        (hits if pre > 0 else miss).append((str(d0.to_period('M')), round(pre, 1)))
print(f"\n  災難月（2011 起）進場前後 5 天曾倒掛：{len(hits)}/{len(hits)+len(miss)}")
print(f"  命中 {hits}  漏 {miss}")
