#!/usr/bin/env python3
"""金絲雀驗證室（2026-09-25）：VIX9D 之外，還有哪隻鳥值得養？

候選（皆 Yahoo 免費日線）：
  vix3m 倒掛  VIX − VIX3M > 0（月/季斜率，慢速金絲雀）
  vvix 高位   VVIX > 滾動 252 日 90 分位（vol-of-vol，只用過去資料，無前視）
  move 高位   MOVE > 滾動 252 日 90 分位（債券波動，跨資產先導）
  skew 高位   SKEW > 滾動 252 日 90 分位（尾部定價）
  vxn 溢價    VXN − VIX > 滾動 252 日 90 分位（科技股壓力）

考核（對 SPX 與 HSI 各一份）：
  1. 亮燈日未來 5 天 RV vs 不亮燈（倍率）
  2. 亮燈日 5 天內見 -2% 單日機率 vs 無條件（提升）＋誤報率
  3. 增量：VIX9D 綠燈（未倒掛）時亮燈，是否仍有預測力（不重複的資訊才值得養）
  4. 災難月覆蓋：進場前後 5 天曾亮燈幾個
"""
import numpy as np
import pandas as pd

D = 'data_external'


def s(f):
    return pd.read_csv(f'{D}/{f}', parse_dates=['Date']).set_index('Date').Close


def fwd(px):
    r = np.log(px).diff()
    rv, dn = [], []
    for i in range(len(r)):
        w = r.iloc[i + 1:i + 6]
        rv.append(w.std() * np.sqrt(252) * 100 if len(w) == 5 else np.nan)
        dn.append(int((w < -0.02).any()) if len(w) == 5 else np.nan)
    return pd.Series(rv, index=r.index), pd.Series(dn, index=r.index)


def disasters(ivs, px):
    VEGA = 0.8 * np.sqrt(21 / 252)
    df = pd.concat([ivs.rename('iv'), px.rename('px')], axis=1, sort=True).dropna()
    df['r'] = np.log(df.px).diff()
    out = []
    for d0 in df.groupby(df.index.to_period('M')).head(1).index:
        i0 = df.index.get_loc(d0)
        if i0 + 21 >= len(df):
            break
        iv0 = df.iv.iloc[i0]
        rv = df.r.iloc[i0 + 1:i0 + 22].std() * np.sqrt(252) * 100
        if VEGA * (iv0 - rv) <= -VEGA * iv0:
            out.append(d0)
    return out


spx, hsi = s('spx_daily.csv'), s('hsi_daily.csv')
vix, v9 = s('vix_daily.csv'), s('vix9d_daily.csv')
sigs = {}
sigs['vix3m倒掛'] = (vix - s('vix3m_daily.csv')).dropna() > 0
for name, f in [('vvix高位', 'vvix_daily.csv'), ('move高位', 'move_daily.csv'),
                ('skew高位', 'skew_daily.csv')]:
    try:
        x = s(f)
        sigs[name] = x > x.rolling(252).quantile(0.9)
    except Exception as e:
        print(f"{name} 無數據: {e!r}")
vxn = s('vxn_daily.csv')
sp_vxn = (vxn - vix).dropna()
sigs['vxn溢價'] = sp_vxn > sp_vxn.rolling(252).quantile(0.9)
green = ((v9 - vix).dropna() <= 0)          # VIX9D 未倒掛 = 現有儀表沒響

dis = {'SPX': disasters(vix, spx), 'HSI': disasters(s('vhsi_daily.csv'), hsi)}
for mkt, px in [('SPX', spx), ('HSI', hsi)]:
    rv5, dn2 = fwd(px)
    print(f"\n=== 對 {mkt} 的預測力 ===")
    base_rv, base_dn = rv5.mean(), dn2.mean()
    print(f"{'金絲雀':<10}{'樣本':>6}{'亮燈佔%':>7}{'RV倍率':>7}{'-2%提升':>8}"
          f"{'誤報%':>6}{'綠燈下RV倍率':>11}{'災難月覆蓋':>9}")
    for name, sig in sigs.items():
        idx = sig.index.intersection(rv5.dropna().index)
        g = sig.reindex(idx).fillna(False).infer_objects(copy=False)
        if g.sum() < 30:
            continue
        rvr = rv5[idx][g].mean() / rv5[idx][~g].mean()
        lift = dn2[idx][g].mean() / max(dn2[idx].mean(), 1e-9)
        fa = (rv5[idx][g] < rv5[idx].median()).mean() * 100
        gi = idx.intersection(green[green].index)
        gg = sig.reindex(gi).fillna(False).infer_objects(copy=False)
        inc = rv5[gi][gg].mean() / rv5[gi][~gg].mean() if gg.sum() > 30 else np.nan
        cov = 0
        for d0 in dis[mkt]:
            w = sig.loc[:d0].tail(6)
            cov += int(bool(len(w)) and w.any())
        print(f"{name:<10}{len(idx):>6}{g.mean()*100:>7.0f}{rvr:>7.2f}{lift:>8.1f}"
              f"{fa:>6.0f}{inc:>11.2f}{cov:>6}/{len(dis[mkt])}")
