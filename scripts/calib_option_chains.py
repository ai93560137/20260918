#!/usr/bin/env python3
"""期權鏈校準（OPTIONS_EQUITY_BACKTEST.md 第一部分「期權定價模型」）：從真實 SPX／恒指期權鏈快照
算平值 IV ÷ 波動率指數（k）、偏斜斜率（s_put、s_call）、平值半價差（波動點）。

    python3 scripts/calib_option_chains.py <快照目錄>

快照來自雲垂分支 tradingview/data_external/quotes_us/spx_chain_*.json、quotes_colab/options_*.json，
加 vix_daily.csv、vhsi_daily.csv（同目錄）。IV 一律用買賣中間價、由看漲看跌平價推遠期 F 後自己反推
（來源自帶的 IV call／put 不一致，不用）；價外那一邊的期權才用；|m| > 0.6 不用。
偏斜：IV(K) − ATM = s × m，m = ln(K/F)/√T，兩邊各自最小平方（過原點）。
"""
import os, sys
import json, glob, math, csv, re, statistics as st
os.chdir(sys.argv[1] if len(sys.argv) > 1 else '.')
from datetime import datetime, date
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def b76(F,K,T,v,cp):
    d1=(math.log(F/K)+.5*v*v*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    c=F*N(d1)-K*N(d2); return c if cp=='c' else c-F+K
def iv(F,K,T,px,cp):
    lo,hi=1e-3,3.0
    if px<=max(0,(F-K) if cp=='c' else (K-F))+1e-9: return None
    for _ in range(80):
        m=(lo+hi)/2
        if b76(F,K,T,m,cp)>px: hi=m
        else: lo=m
    return (lo+hi)/2
def num(x):
    if x in (None,'',): return None
    return float(str(x).replace(',',''))
def fit(chain,F,T):
    # chain: list of (K, cbid,cask,pbid,pask)
    pts=[];spreads=[]
    for K,cb,ca,pb,pa in chain:
        cp='p' if K<F else 'c'; b,a=(pb,pa) if cp=='p' else (cb,ca)
        if not b or not a or a<=b: continue
        v=iv(F,K,T,(a+b)/2,cp)
        if not v: continue
        m=math.log(K/F)/math.sqrt(T)
        if abs(m)>0.6: continue
        # vega (per 1 vol pt)
        d1=(math.log(F/K)+.5*v*v*T)/(v*math.sqrt(T)); vega=F*math.sqrt(T)*math.exp(-d1*d1/2)/math.sqrt(2*math.pi)/100
        pts.append((m,v)); spreads.append(((a-b)/2/vega, m))
    atm=min(pts,key=lambda x:abs(x[0]))[1]
    def slope(side):
        xs=[(m,v-atm) for m,v in pts if (m<0 if side<0 else m>0) and abs(m)>0.02]
        return sum(m*y for m,y in xs)/sum(m*m for m,y in xs) if xs else float('nan')
    hs=[s for s,m in spreads if abs(m)<0.15]
    return atm, slope(-1), slope(1), st.median(hs) if hs else float('nan'), len(pts)
def load_idx(fn):
    return {r['Date']:float(r['Close']) for r in csv.DictReader(open(fn))}
vix=load_idx('vix_daily.csv'); vhsi=load_idx('vhsi_daily.csv')
US=[];HK=[]
print("== SPX")
for fn in sorted(glob.glob('spx_chain_*.json')):
    d=json.load(open(fn)); T=d['dte']/365
    ch=[]
    for K,x in d['strikes'].items():
        c=x.get('c',{});p=x.get('p',{})
        ch.append((float(K),c.get('bid'),c.get('ask'),p.get('bid'),p.get('ask')))
    both=[(K,(ca+cb)/2-(pa+pb)/2) for K,cb,ca,pb,pa in ch if cb and ca and pb and pa]
    Kc,diff=min(both,key=lambda t:abs(t[1])); F=Kc+diff
    atm,sp,sc,hs,n=fit(ch,F,T); day=d['fetched_utc'][:10]
    US.append((atm*100/vix[day] if day in vix else None,sp,sc,hs,n))
    print(f"{fn[10:23]} dte{d['dte']:3d} F{F:8.1f} ATM {atm*100:5.2f} VIX {vix.get(day,float('nan')):5.2f} putslope {sp*100:6.2f} callslope {sc*100:6.2f} halfspread(volpt) {hs:.3f} n{n}")
print("== HSI")
for fn in sorted(glob.glob('options_*.json')):
    d=json.load(open(fn))['data']; lst=d['optionlist']
    mo=re.search(r'options_(\w+)-(\d+)_(\d{8})',fn); exp_m=datetime.strptime(mo.group(1)+mo.group(2),'%b%y'); asof=datetime.strptime(mo.group(3),'%Y%m%d')
    # HSI expiry = second-last business day of month; approx day 28
    import calendar
    last=calendar.monthrange(exp_m.year,exp_m.month)[1]; ex=datetime(exp_m.year,exp_m.month,last-2)
    T=max((ex-asof).days,1)/365
    ch=[(num(o['strike']),num(o['c']['bd']),num(o['c']['as']),num(o['p']['bd']),num(o['p']['as'])) for o in lst]
    both=[(K,(ca+cb)/2-(pa+pb)/2) for K,cb,ca,pb,pa in ch if cb and ca and pb and pa]
    if not both: continue
    Kc,diff=min(both,key=lambda t:abs(t[1])); F=Kc+diff
    atm,sp,sc,hs,n=fit(ch,F,T); day=asof.strftime('%Y-%m-%d')
    HK.append((atm,sp,sc,hs,n,T))
    print(f"{fn[8:30]} T{T*365:4.0f}d F{F:8.0f} ATM {atm*100:5.2f} VHSI {vhsi.get(day,float('nan')):5.2f} putslope {sp*100:6.2f} callslope {sc*100:6.2f} halfspread(volpt) {hs:.3f} n{n}")

med=lambda xs: st.median([x for x in xs if x==x])
u=[r for r in US if r[4]>=20]
print(f"\n美股中位數：k {med([r[0] for r in u if r[0]]):.3f}  s_put {med([r[1] for r in u]):.3f}  s_call {med([r[2] for r in u]):.3f}  半價差 {med([r[3] for r in u]):.3f}  （{len(u)} 快照）")
h=[r for r in HK if r[4]>=5 and r[3]<1 and r[5]*365>=20]
vh=vhsi[max(vhsi)]
print(f"港股中位數（20 日以上到期）：ATM {med([r[0] for r in h])*100:.2f} ÷ VHSI {vh:.2f}（最後一日 {max(vhsi)}）= k {med([r[0] for r in h])*100/vh:.3f}  s_put {med([r[1] for r in h]):.3f}  s_call {med([r[2] for r in h]):.3f}  半價差 {med([r[3] for r in h]):.3f}  （{len(h)} 快照）")
