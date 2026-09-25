#!/usr/bin/env python3
"""Gamma 策略設計實驗室（2026-09-25）。

問題：雲垂陣現在是「短 gamma 收 VRP」。gamma 方向還有什麼可設計？
  A. 長 gamma（買跨式 + delta 對沖）：無條件 / 便宜波動率過濾（spread<=0、<=-2、最低十分位）
  B. 週度短 gamma（賣 5 天跨式）：theta 更陡但 gamma 風險集中——用 30 天波指近似，
     減去期限結構折讓 h（0/2/4 點敏感度，因為沒有歷史週權 IV）
  C. 長 gamma 當尾部保險：災難月（短倉虧超過 1x 權利金）時便宜過濾器有沒有亮燈？

方法：與月度 VRP 模擬同構。
  月度 P&L% 名義 = ±VEGA·(RV21 − IV0) − 成本, VEGA = 0.8·√(21/252)
  週度 P&L% 名義 = ±VEGA_w·(RV5 − (IV0−h)) − 成本_w, VEGA_w = 0.8·√(5/252)
  成本（vol 點）：月度 HSI 0.12 / SPX 0.056（實測）；週度 ×√(21/5)≈2.05 →
  HSI 0.25 / SPX 0.115（假設點差現金額不變、vega 減半 → vol 點成本翻倍）
"""
import numpy as np
import pandas as pd

D = 'data_external'
VEGA_M = 0.8 * np.sqrt(21 / 252)
VEGA_W = 0.8 * np.sqrt(5 / 252)


def load(vol_csv, px_csv):
    iv = pd.read_csv(f'{D}/{vol_csv}', parse_dates=['Date']).set_index('Date').Close
    px = pd.read_csv(f'{D}/{px_csv}', parse_dates=['Date']).set_index('Date').Close
    df = pd.concat([iv.rename('iv'), px.rename('px')], axis=1).dropna()
    df['r'] = np.log(df.px).diff()
    df['hv20'] = df.r.rolling(20).std() * np.sqrt(252) * 100
    return df.dropna()


def monthly(df, cost):
    rows = []
    for d0 in df.groupby(df.index.to_period('M')).head(1).index:
        i0 = df.index.get_loc(d0)
        if i0 + 21 >= len(df):
            break
        iv0 = df.iv.iloc[i0]
        rv = df.r.iloc[i0 + 1:i0 + 22].std() * np.sqrt(252) * 100
        rows.append(dict(month=str(d0.to_period('M')), iv0=iv0,
                         spread=iv0 - df.hv20.iloc[i0],
                         prem=VEGA_M * iv0,
                         short=VEGA_M * (iv0 - rv) - cost * VEGA_M,
                         long=VEGA_M * (rv - iv0) - cost * VEGA_M))
    return pd.DataFrame(rows)


def weekly(df, cost_w, haircut):
    out = []
    idx = range(0, len(df) - 6, 5)
    for i0 in idx:
        iv0 = df.iv.iloc[i0] - haircut
        rv = df.r.iloc[i0 + 1:i0 + 6].std() * np.sqrt(252) * 100
        out.append(VEGA_W * (iv0 - rv) - cost_w * VEGA_W)
    return pd.Series(out)


def stat(s, per_year):
    s = pd.Series(s).dropna()
    if len(s) < 10:
        return f"  (樣本 {len(s)} 太少)"
    t = s.mean() / s.std() * np.sqrt(len(s))
    return (f"N={len(s):>4}  均值 {s.mean():+6.2f}%  t={t:+5.1f}  "
            f"最壞 {s.min():+6.1f}%  勝率 {(s > 0).mean() * 100:3.0f}%  "
            f"年化 {s.mean() * per_year:+6.1f}%")


def run_market(name, vol_csv, px_csv, cost_m, cost_w):
    df = load(vol_csv, px_csv)
    m = monthly(df, cost_m)
    print(f"\n=== {name}  ({m.month.iloc[0]} → {m.month.iloc[-1]}, {len(m)} 月) ===")
    print(f"短 gamma 月度(基準)   {stat(m.short, 12)}")
    print(f"長 gamma 無條件       {stat(m.long, 12)}")
    for lab, mask in [('長 spread<=0 ', m.spread <= 0),
                      ('長 spread<=-2', m.spread <= -2),
                      ('長 最低十分位*', m.spread <= m.spread.quantile(0.1))]:
        sub = m.long[mask]
        act = mask.mean() * 12
        print(f"長 gamma {lab}  {stat(sub, act if len(sub) >= 10 else 12)}")
    print("  *十分位門檻用全樣本＝有前視偏差，僅供方向判斷")
    print("週度短 gamma（期限結構折讓 h 敏感度；~50 期/年）")
    for h in [0, 2, 4]:
        print(f"  h={h} 點   {stat(weekly(df, cost_w, h), 50)}")
    # C. 尾部保險檢驗：災難月裡便宜過濾器有沒有亮燈
    dis = m[m.short < -m.prem]
    lit = (dis.spread <= 0).sum()
    print(f"災難月（短倉虧>1x權利金）{len(dis)} 個：進場時 spread<=0 亮燈 {lit} 個")
    if len(dis):
        print('  ' + '  '.join(f"{r.month}(sp{r.spread:+.1f})" for r in dis.itertuples()))
    return m


if __name__ == '__main__':
    run_market('恒指 HSI', 'vhsi_daily.csv', 'hsi_daily.csv', 0.12, 0.25)
    run_market('美股 SPX', 'vix_daily.csv', 'spx_daily.csv', 0.056, 0.115)
