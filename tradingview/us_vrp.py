import pandas as pd, numpy as np
from math import erf, log, sqrt
def N(x): return 0.5*(1+erf(x/sqrt(2)))
def bs(S,K,T,vol,cp):
    d1=(log(S/K)+0.5*vol*vol*T)/(vol*sqrt(T)); d2=d1-vol*sqrt(T)
    c=S*N(d1)-K*N(d2); return c if cp=='c' else c-S+K
def t_of(x): return x.mean()/(x.std()/np.sqrt(len(x)))

BASE='/home/user/20260918/tradingview/data_external/'
def load(f): 
    d=pd.read_csv(BASE+f,parse_dates=['Date']).set_index('Date'); return d.Close
VEGA=0.8*np.sqrt(21/252); COST_PTS=0.12

def pipeline(name, iv_file, px_file):
    iv, px = load(iv_file), load(px_file)
    r = px.pct_change()
    rv = (r[::-1].rolling(21).std()[::-1]).shift(-1)*np.sqrt(252)*100
    al = pd.DataFrame({'iv':iv,'rv':rv}).dropna()
    mo = al.groupby(al.index.to_period('M')).first()
    mo['net'] = (mo.iv-mo.rv-COST_PTS)*VEGA
    yr = al.groupby(al.index.year)['iv'].count()
    vrp_yr = al.assign(v=al.iv-al.rv).groupby(al.index.year).v.mean()
    s = mo.net.sort_values(); k=max(1,int(len(s)*0.05))
    half=len(mo)//2
    print(f"\n═══ {name}  {al.index[0].date()} → {al.index[-1].date()}  n={len(mo)} 月 ═══")
    print(f"  VRP 全期平均 {al.iv.sub(al.rv).mean():+.2f} 點  正比例 {(al.iv>al.rv).mean()*100:.0f}%  逐年為正 {int((vrp_yr>0).sum())}/{len(vrp_yr)} 年")
    print(f"  跨式月度淨: 月均 {mo.net.mean():+.3f}%  t={t_of(mo.net):+.2f}  年化 {mo.net.mean()*12:+.2f}%  勝率 {(mo.net>0).mean()*100:.0f}%")
    print(f"  去頂5%後 {s.iloc[:-k].mean():+.3f}%（{'仍正 ✓' if s.iloc[:-k].mean()>0 else '翻負 ✗'}）  切半 t: 前 {t_of(mo.net.iloc[:half]):+.2f} / 後 {t_of(mo.net.iloc[half:]):+.2f}")
    print(f"  最壞月 {mo.net.min():+.2f}%  月σ {mo.net.std():.2f}%  夏普 {mo.net.mean()/mo.net.std()*np.sqrt(12):.2f}")
    # 平坦vol 97/92 put spread 模擬（NQ 使用者現行策略的對照）
    px_al = pd.DataFrame({'iv':iv/100,'S':px}).dropna()
    px_al['ST'] = px_al.S.shift(-21)
    m2 = px_al.groupby(px_al.index.to_period('M')).first().dropna()
    T=21/252
    def psp(row):
        prem = bs(row.S,0.97*row.S,T,row.iv,'p') - bs(row.S,0.92*row.S,T,row.iv,'p')
        pay  = max(0.97*row.S-row.ST,0) - max(0.92*row.S-row.ST,0)
        return (prem-pay)/row.S*100 - 0.05
    sp = m2.apply(psp,axis=1)
    s2=sp.sort_values(); k2=max(1,int(len(s2)*0.05))
    print(f"  [對照] 97/92 put spread（平坦vol）: 月均 {sp.mean():+.3f}%  t={t_of(sp):+.2f}  去頂5% {s2.iloc[:-k2].mean():+.3f}%")

pipeline('ES / SPX（VIX）','vix_daily.csv','spx_daily.csv')
pipeline('NQ / NDX（VXN）','vxn_daily.csv','ndx_daily.csv')
print("\n─── 對照：HSI（VHSI）同流程數字（§10）───")
pipeline('HSI（VHSI）','vhsi_daily.csv','hsi_daily.csv')
