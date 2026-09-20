import pandas as pd, numpy as np, sys

def t_of(x): return x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>5 and x.std()>0 else np.nan

v = pd.read_csv('data_external/vhsi_daily.csv', parse_dates=['Date']).set_index('Date')
h = pd.read_csv('data_external/hsi_daily.csv', parse_dates=['Date']).set_index('Date')
r = h.Close.pct_change()

# 未來 21 個交易日的實際波動（年化，%）——與 VHSI 的 30 曆日對齊
rv_fwd = (r[::-1].rolling(21).std()[::-1]).shift(-1) * np.sqrt(252) * 100
al = pd.DataFrame({'iv': v.Close, 'rv': rv_fwd}).dropna()
al['vrp'] = al.iv - al.rv          # 正 = 隱含高於後來的實際 = 賣方被多付
print(f"樣本 {al.index[0].date()} → {al.index[-1].date()}  n={len(al)}")

print("\n══ VRP = VHSI − 未來21日實際波動 ══")
print(f"  全期平均 {al.vrp.mean():+.2f} 個百分點   中位 {al.vrp.median():+.2f}   正的比例 {(al.vrp>0).mean()*100:.1f}%")
# t 值用月度平均避免重疊窗口
mo = al.vrp.resample('ME').mean().dropna()
print(f"  t（月度，n={len(mo)}）= {t_of(mo):+.2f}")

print("\n  逐年：")
yr = al.groupby(al.index.year).agg(iv=('iv','mean'), rv=('rv','mean'), vrp=('vrp','mean'),
                                   pos=('vrp', lambda x:(x>0).mean()*100))
for y, row in yr.iterrows():
    print(f"    {y}: IV均 {row.iv:5.1f}  RV均 {row.rv:5.1f}  VRP {row.vrp:+6.2f}  正比例 {row.pos:4.0f}%")

print("\n══ 切半驗證 ══")
half = len(al)//2
for lbl, sub in [('前半', al.iloc[:half]), ('後半', al.iloc[half:])]:
    m2 = sub.vrp.resample('ME').mean().dropna()
    print(f"  {lbl} {sub.index[0].date()}→{sub.index[-1].date()}: VRP {sub.vrp.mean():+.2f}  正比例 {(sub.vrp>0).mean()*100:.0f}%  t(月)={t_of(m2):+.2f}")

print("\n══ 條件：IV 高低分位的 VRP（『尖峰後賣』假設）══")
q = al.iv.rolling(252).rank(pct=True)   # 過去一年內的分位，避免用未來資訊
al2 = al.assign(q=q).dropna()
for lo, hi, lbl in [(0, .2, 'IV 低分位(0-20%)'), (.4, .6, 'IV 中位(40-60%)'), (.8, 1.01, 'IV 高分位(80-100%)')]:
    m = al2[(al2.q >= lo) & (al2.q < hi)]
    mm = m.vrp.resample('ME').mean().dropna()
    print(f"  {lbl:<18} n={len(m):>5}  VRP {m.vrp.mean():+.2f}  正比例 {(m.vrp>0).mean()*100:.0f}%  t(月)={t_of(mm):+.2f}")

print("\n══ 尾部：VRP 最壞的月份（賣方的災難清單）══")
worst = mo.nsmallest(8)
for d, x in worst.items():
    print(f"    {d.strftime('%Y-%m')}: {x:+.1f}")

print("\n══ 近年（2022-08 起，與 CFD 樣本重疊期）══")
rec = al[al.index >= '2022-08-01']
mr = rec.vrp.resample('ME').mean().dropna()
print(f"  VRP {rec.vrp.mean():+.2f}  正比例 {(rec.vrp>0).mean()*100:.0f}%  t(月)={t_of(mr):+.2f}  n={len(rec)}")
