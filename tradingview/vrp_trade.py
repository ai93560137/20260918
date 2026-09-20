import pandas as pd, numpy as np
def t_of(x): return x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>5 and x.std()>0 else np.nan

v = pd.read_csv('data_external/vhsi_daily.csv', parse_dates=['Date']).set_index('Date')
h = pd.read_csv('data_external/hsi_daily.csv', parse_dates=['Date']).set_index('Date')
r = h.Close.pct_change()
rv_fwd = (r[::-1].rolling(21).std()[::-1]).shift(-1) * np.sqrt(252) * 100
al = pd.DataFrame({'iv': v.Close, 'rv': rv_fwd}).dropna()

# 不重疊：每月第一個交易日「賣」一次，持有 21 個交易日
mo = al.groupby(al.index.to_period('M')).first()
mo['pnl_pts'] = mo.iv - mo.rv                      # 每月一筆，單位＝波動點
VEGA = 0.8 * np.sqrt(21/252)                        # ATM 跨式每 1 波動點 ≈ 名義的 0.8·√T％
mo['pnl_pct'] = mo.pnl_pts * VEGA                   # 換成名義本金的 %
COST_PTS = 0.65                                     # 跨式來回價差 ≈ 0.65 個波動點（40 指數點）
mo['net_pct'] = (mo.pnl_pts - COST_PTS) * VEGA

print(f"每月賣出 1 個月平值跨式（delta 對沖近似），n={len(mo)} 個月，1 波動點 ≈ 名義 {VEGA:.3f}%")
for lbl, s in [('毛（波動點）', mo.pnl_pts), ('毛（名義%）', mo.pnl_pct), ('淨（名義%）', mo.net_pct)]:
    print(f"  {lbl:<10} 月均 {s.mean():+.3f}  中位 {s.median():+.3f}  t={t_of(s):+.2f}  年化 {s.mean()*12:+.2f}")
print(f"  最壞月（淨）: {mo.net_pct.min():+.2f}%  最好月 {mo.net_pct.max():+.2f}%  月σ {mo.net_pct.std():.2f}%")
print(f"  年化夏普（淨）≈ {mo.net_pct.mean()/mo.net_pct.std()*np.sqrt(12):.2f}")

print("\n══ 異常值檢查：拿掉最賺的 5% 月份 ══")
s = mo.net_pct.sort_values()
k = max(1, int(len(s)*0.05))
print(f"  去頂 5% 後月均 {s.iloc[:-k].mean():+.3f}%（原 {mo.net_pct.mean():+.3f}%）→ {'仍為正 ✓' if s.iloc[:-k].mean()>0 else '翻負 ✗'}")

print("\n══ 切半驗證（淨）══")
half = len(mo)//2
for lbl, sub in [('前半', mo.iloc[:half]), ('後半', mo.iloc[half:])]:
    print(f"  {lbl} {sub.index[0]}→{sub.index[-1]}: 月均 {sub.net_pct.mean():+.3f}%  t={t_of(sub.net_pct):+.2f}  勝率 {(sub.net_pct>0).mean()*100:.0f}%")

print("\n══ 近年（2022-08 起）══")
rec = mo[mo.index >= '2022-08']
print(f"  月均淨 {rec.net_pct.mean():+.3f}%  t={t_of(rec.net_pct):+.2f}  勝率 {(rec.net_pct>0).mean()*100:.0f}%  n={len(rec)}")

print("\n══ 連續回撤（淨，複利名義）══")
eq = (1 + mo.net_pct/100).cumprod()
dd = (eq/eq.cummax()-1)
print(f"  最大回撤 {dd.min()*100:.1f}%（{dd.idxmin()}）  年化（全期）{(eq.iloc[-1]**(12/len(mo))-1)*100:+.2f}%")
