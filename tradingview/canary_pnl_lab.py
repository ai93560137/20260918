#!/usr/bin/env python3
"""金絲雀警報的利潤價值（2026-09-25）。

定義（使用者定調）：金絲雀 = 週度期權腿，只讀價不交易。
  紅警報   = 9D 倒掛（VIX9D > VIX，週權貴過月權）
  深紅警報 = 3M 倒掛（VIX > VIX3M，月權貴過季權）

問題：警報怎麼用才真的多賺錢/少虧錢？逐條規則對月度短跨式實測：
  hold        照常做（基準）
  delay_red   進場日紅警報 → 延後到首個綠燈日才進（最多等 10 天，等不到跳過）
  skip_deep   進場日深紅 → 該月不做
  exit_red    持倉中紅警報亮 → 立即平倉（餘日空倉）
  exit_deep   持倉中深紅亮 → 立即平倉
  exit_deep_re 深紅平倉 + 轉綠即重進（殘餘天數）

逐日路徑近似同 mes_dynamic_exit（方差收割 + vega MTM）。
美股用本土訊號；恒指用前一日美訊號（時差先導，恒指無本土歷史）。
成本每 round trip：SPX 0.056 / HSI 0.12 vol 點 ×VEGA；重進多收一次。
樣本：2011-01 起（VIX9D 起點），~176 個月。
"""
import numpy as np
import pandas as pd

D = 'data_external'
VEGA = 0.8 * np.sqrt(21 / 252)


def load(px_csv, iv_csv, lag):
    px = pd.read_csv(f'{D}/{px_csv}', parse_dates=['Date']).set_index('Date').Close
    iv = pd.read_csv(f'{D}/{iv_csv}', parse_dates=['Date']).set_index('Date').Close
    v9 = pd.read_csv(f'{D}/vix9d_daily.csv', parse_dates=['Date']).set_index('Date').Close
    vx = pd.read_csv(f'{D}/vix_daily.csv', parse_dates=['Date']).set_index('Date').Close
    v3 = pd.read_csv(f'{D}/vix3m_daily.csv', parse_dates=['Date']).set_index('Date').Close
    red = ((v9 - vx) > 0).astype(float)
    deep = ((vx - v3) > 0).astype(float)
    df = pd.concat([px.rename('px'), iv.rename('iv'),
                    red.rename('red'), deep.rename('deep')], axis=1, sort=True)
    df[['red', 'deep']] = df[['red', 'deep']].ffill().shift(lag)
    df = df.dropna(subset=['px', 'iv', 'red', 'deep'])
    df = df[df.index >= '2011-01-01']
    df['r'] = np.log(df.px).diff()
    return df.dropna()


def paths(df):
    out = []
    for d0 in df.groupby(df.index.to_period('M')).head(1).index:
        i0 = df.index.get_loc(d0)
        if i0 + 32 >= len(df):
            break
        out.append(i0)
    return out


def path_pnl(df, i0, days=21):
    w = df.iloc[i0:i0 + days + 1]
    iv0 = w.iv.iloc[0]
    rets, ivs = w.r.iloc[1:].values, w.iv.iloc[1:].values
    rv_d2 = (rets * 100) ** 2 * 252
    k = 0.8 * np.sqrt(252 / days) / (2 * iv0)
    carry = np.cumsum(k * (iv0 ** 2 - rv_d2) / 252)
    t = np.arange(1, days + 1)
    vega_rem = 0.8 * np.sqrt((days - t) / 252)
    return carry + vega_rem * (iv0 - ivs), iv0


def run(df, cost):
    C = cost * VEGA
    starts = paths(df)
    res = {k: [] for k in ['hold', 'delay_red', 'skip_deep',
                           'exit_red', 'exit_deep', 'exit_deep_re']}
    stats = {'delay_used': 0, 'skip_used': 0, 'xr': 0, 'xd': 0, 're': 0}
    for i0 in starts:
        pnl, _ = path_pnl(df, i0)
        red = df.red.iloc[i0 + 1:i0 + 22].values
        deep = df.deep.iloc[i0 + 1:i0 + 22].values
        res['hold'].append(pnl[20] - C)
        # 延後進場：進場日紅 → 首個綠日（≤10 天）
        if df.red.iloc[i0] > 0:
            stats['delay_used'] += 1
            j = next((k for k in range(1, 11) if df.red.iloc[i0 + k] == 0), None)
            if j is None:
                res['delay_red'].append(0.0)
            else:
                p2, _ = path_pnl(df, i0 + j)
                res['delay_red'].append(p2[20] - C)
        else:
            res['delay_red'].append(pnl[20] - C)
        # 深紅跳過
        if df.deep.iloc[i0] > 0:
            stats['skip_used'] += 1
            res['skip_deep'].append(0.0)
        else:
            res['skip_deep'].append(pnl[20] - C)
        # 持倉中警報平倉
        tr = next((t for t in range(21) if red[t] > 0), None)
        td = next((t for t in range(21) if deep[t] > 0), None)
        res['exit_red'].append((pnl[tr] if tr is not None else pnl[20]) - C)
        stats['xr'] += tr is not None
        res['exit_deep'].append((pnl[td] if td is not None else pnl[20]) - C)
        stats['xd'] += td is not None
        # 深紅平倉 + 轉綠重進殘餘天數
        if td is None:
            res['exit_deep_re'].append(pnl[20] - C)
        else:
            v = pnl[td] - C
            g = next((k for k in range(td + 1, 21) if deep[k] == 0), None)
            if g is not None and 21 - g >= 3:
                p3, _ = path_pnl(df, i0 + g + 1, days=21 - g - 1)
                v += p3[-1] - C
                stats['re'] += 1
            res['exit_deep_re'].append(v)
    print(f"  觸發統計：進場日紅 {stats['delay_used']}、進場日深紅 {stats['skip_used']}、"
          f"月中紅 {stats['xr']}、月中深紅 {stats['xd']}、重進 {stats['re']}（共 {len(starts)} 月）")
    print(f"  {'規則':<14}{'月均%':>7}{'t':>6}{'最壞月%':>9}{'勝率%':>6}{'年化%':>7}")
    base = None
    for k, v in res.items():
        s = pd.Series(v)
        t = s.mean() / s.std() * np.sqrt(len(s))
        if k == 'hold':
            base = s.mean()
        d = (s.mean() - base) * 12
        print(f"  {k:<14}{s.mean():>7.2f}{t:>6.1f}{s.min():>9.1f}"
              f"{(s > 0).mean() * 100:>6.0f}{s.mean() * 12:>7.1f}  （對基準 {d:+.1f}%/年）")


print("=== 美股 SPX（本土訊號，2011 起）===")
run(load('spx_daily.csv', 'vix_daily.csv', lag=0), 0.056)
print("\n=== 美股 SPX 防偽檢查（訊號延遲 1 天）===")
run(load('spx_daily.csv', 'vix_daily.csv', lag=1), 0.056)
print("\n=== 恒指 HSI（美訊號前一日先導，2011 起）===")
run(load('hsi_daily.csv', 'vhsi_daily.csv', lag=1), 0.12)
