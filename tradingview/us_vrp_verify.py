import pandas as pd, numpy as np
BASE='/home/user/20260918/tradingview/data_external/'
def t_of(x): return x.mean()/(x.std()/np.sqrt(len(x)))
def load(f):
    d=pd.read_csv(BASE+f,parse_dates=['Date']).set_index('Date'); return d

print("══ 1. 資料品質檢查 ══")
for f,lo,hi in [('vix_daily.csv',5,100),('vxn_daily.csv',5,120),('spx_daily.csv',100,10000),('ndx_daily.csv',50,30000),('vhsi_daily.csv',5,120)]:
    d=load(f); c=d.Close
    # 平日缺口（連續 >5 個平日沒資料）
    idx=pd.bdate_range(c.index[0],c.index[-1])
    missing=idx.difference(c.index)
    # 連續重複值（呆滯報價）
    stale=(c.diff()==0).astype(int).groupby((c.diff()!=0).cumsum()).sum().max()
    # 單日極端跳動
    jump=c.pct_change().abs().max()
    bad=((c<lo)|(c>hi)).sum()
    print(f"  {f:<16} n={len(c):>5}  缺平日 {len(missing):>4}({len(missing)/len(idx)*100:.1f}%)  最長呆滯 {stale:>3} 天  最大單日跳動 {jump*100:5.1f}%  範圍外值 {bad}")

print("\n══ 2. 著名數值抽查（對照公開紀錄）══")
vix=load('vix_daily.csv').Close; spx=load('spx_daily.csv').Close
checks=[('VIX 2020-03-16（史上最高收盤，公認 82.69）', vix.get(pd.Timestamp('2020-03-16'))),
        ('VIX 2008-11-20（金融海嘯峰值，公認 80.86）', vix.get(pd.Timestamp('2008-11-20'))),
        ('VIX 2018-02-05（Volmageddon，公認 37.32）', vix.get(pd.Timestamp('2018-02-05'))),
        ('SPX 2020-03-23（疫情底，公認 2237.40）', spx.get(pd.Timestamp('2020-03-23'))),
        ('VIX 2017 全年均值（公認 ~11.1，史上最低年）', vix['2017'].mean())]
for name,val in checks:
    print(f"  {name}: 我們的資料 = {val:.2f}")

print("\n══ 3. 分年代穩健性（跨式月度淨，同 §10 流程）══")
VEGA=0.8*np.sqrt(21/252); COST=0.12
def monthly_net(ivf,pxf,offset=0,rvwin=21):
    iv=load(ivf).Close; px=load(pxf).Close; r=px.pct_change()
    rv=(r[::-1].rolling(rvwin).std()[::-1]).shift(-1)*np.sqrt(252)*100
    al=pd.DataFrame({'iv':iv,'rv':rv}).dropna()
    g=al.groupby(al.index.to_period('M'))
    mo=g.nth(offset).dropna() if offset else g.first()
    return ((mo.iv-mo.rv-COST)*VEGA).dropna()
for name,ivf,pxf in [('ES','vix_daily.csv','spx_daily.csv'),('NQ','vxn_daily.csv','ndx_daily.csv')]:
    net=monthly_net(ivf,pxf)
    print(f"  {name}:")
    for dec in [(1990,1999),(2000,2009),(2010,2019),(2020,2026),(2021,2026)]:
        sub=net[(net.index.year>=dec[0])&(net.index.year<=dec[1])]
        if len(sub)<12: continue
        lbl=f"{dec[0]}–{dec[1]}" if dec!=(2021,2026) else "近5年"
        print(f"    {lbl:<10} n={len(sub):>3}  月均 {sub.mean():+.3f}%  t={t_of(sub):+.2f}  勝率 {(sub>0).mean()*100:.0f}%")

print("\n══ 4. 方法敏感度 ══")
for name,ivf,pxf in [('ES','vix_daily.csv','spx_daily.csv'),('NQ','vxn_daily.csv','ndx_daily.csv')]:
    base=monthly_net(ivf,pxf)
    off=monthly_net(ivf,pxf,offset=9)         # 改月中第10個交易日取樣
    rv26=monthly_net(ivf,pxf,rvwin=26)        # RV 窗口 26 交易日 ≈ 30 曆日（貼 VIX 定義）
    print(f"  {name}: 基準 t={t_of(base):+.2f} | 月中取樣 t={t_of(off):+.2f}（月均 {off.mean():+.3f}%）| RV=26日 t={t_of(rv26):+.2f}（月均 {rv26.mean():+.3f}%）")
