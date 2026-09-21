#!/usr/bin/env python3
"""MES/ES 對沖跨式的「動態退出」測試（2026-09-22）。

問題：持有到期 vs 提早退出（止盈 / 止損 / VIX 尖峰逃生 / 避開結算週）哪個好？

方法：無逐日期權報價，用近似路徑重建每月逐日損益（% 名義）：
  carry（每日）  = k · (IV0² − rv_d²)/252，k 校準使 21 天合計 ≈ VEGA·(IV0 − RV)
                   —— 即 delta 對沖短跨式的「日方差收割」
  MTM（重估值） = vega_rem · (IV0 − VIX_t)，vega_rem = 0.8·√((21−t)/252)
                   —— 提早退出要按當下 VIX 回補，尖峰時退出鎖定虧損
  P&L(t) = carry 累計 + MTM(t)；t=21 時 MTM=0，回到月度模擬的終值。

規則集固定（不掃參數，全數報告）：
  hold        持有到期（基準）
  pt50        止盈：P&L ≥ +50% 權利金 → 平倉，餘日空倉
  sl50/sl100  止損：P&L ≤ −50%/−100% 權利金 → 平倉
  spike5/10   逃生：VIX ≥ 進場 IV +5/+10 點 → 平倉
  day14       避結算週：第 14 個交易日一律平倉（HSI §10.8 結算週 gamma 警告的美股版）

成本：每次進出扣 0.056 波動點×VEGA（實測 MES 成本）；提早退出不另加
（同樣一次round trip），但尖峰時實際價差會更寬——結果對止損型規則偏樂觀。
"""
import numpy as np
import pandas as pd

D = 'data_external'
VEGA = 0.8 * np.sqrt(21 / 252)
COST = 0.056 * VEGA          # % 名義 / 每次 round trip

vix = pd.read_csv(f'{D}/vix_daily.csv', parse_dates=['Date']).set_index('Date').Close
spx = pd.read_csv(f'{D}/spx_daily.csv', parse_dates=['Date']).set_index('Date').Close
df = pd.concat([vix.rename('iv'), spx.rename('px')], axis=1, sort=False).dropna()
df['r'] = np.log(df.px).diff()
df = df.dropna()

months = []
first_days = df.groupby(df.index.to_period('M')).head(1).index
for d0 in first_days:
    i0 = df.index.get_loc(d0)
    if i0 + 21 >= len(df):
        break
    w = df.iloc[i0:i0 + 22]           # 進場日 + 21 個持有日
    iv0 = w.iv.iloc[0]
    prem = 0.8 * iv0 * np.sqrt(21 / 252)          # 跨式權利金 % 名義
    rets = w.r.iloc[1:].values                     # 持有期 21 天日報酬
    ivs = w.iv.iloc[1:].values
    rv_d2 = (rets * 100) ** 2 * 252                # 日實現方差（年化 %²）
    k = 0.8 * np.sqrt(252 / 21) / (2 * iv0)
    carry = np.cumsum(k * (iv0 ** 2 - rv_d2) / 252)
    t = np.arange(1, 22)
    vega_rem = 0.8 * np.sqrt((21 - t) / 252)
    pnl = carry + vega_rem * (iv0 - ivs)           # 逐日 P&L 路徑 % 名義
    months.append(dict(month=str(d0.to_period('M')), iv0=iv0, prem=prem,
                       pnl=pnl, ivs=ivs))

def run(rule):
    out = []
    n_early = 0
    for m in months:
        pnl, prem, iv0, ivs = m['pnl'], m['prem'], m['iv0'], m['ivs']
        exit_t = 21
        for t in range(21):
            if rule == 'pt50' and pnl[t] >= 0.5 * prem:
                exit_t = t + 1; break
            if rule == 'sl50' and pnl[t] <= -0.5 * prem:
                exit_t = t + 1; break
            if rule == 'sl100' and pnl[t] <= -1.0 * prem:
                exit_t = t + 1; break
            if rule == 'spike5' and ivs[t] >= iv0 + 5:
                exit_t = t + 1; break
            if rule == 'spike10' and ivs[t] >= iv0 + 10:
                exit_t = t + 1; break
            if rule == 'day14' and t + 1 >= 14:
                exit_t = t + 1; break
        n_early += (exit_t < 21)
        out.append(pnl[exit_t - 1] - COST)
    s = pd.Series(out)
    return dict(mean=s.mean(), t=s.mean() / s.std() * np.sqrt(len(s)),
                worst=s.min(), pos=(s > 0).mean() * 100,
                early=n_early / len(s) * 100,
                ann=s.mean() * 12)

if __name__ == '__main__':
    print(f'月數: {len(months)}  ({months[0]["month"]} → {months[-1]["month"]})')
    base = run('hold')
    print(f"\n{'規則':<8}{'月均%':>8}{'t':>7}{'最壞月%':>9}{'勝率%':>7}{'提早退出%':>10}{'年化%':>8}")
    for r in ['hold', 'pt50', 'sl50', 'sl100', 'spike5', 'spike10', 'day14']:
        x = run(r)
        print(f"{r:<8}{x['mean']:>8.2f}{x['t']:>7.1f}{x['worst']:>9.1f}"
              f"{x['pos']:>7.0f}{x['early']:>10.0f}{x['ann']:>8.1f}")
    # 對照：月度模擬應與 hold 同量級（模型自洽檢查）
    print(f"\n自洽檢查：hold 月均 {base['mean']:+.2f}% vs 月度模擬(us_vrp) +0.93% —— 應同量級")
