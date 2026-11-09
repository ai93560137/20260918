"""[11-09 審計，只讀] fit_rules.simulate 同一根 K 線「先成交後止賺」偏差：原版容許成交嗰根 M1 就計 TP（tph 用 cols >= f），
但 E6S4 嘅 TP 喺現價同入場區中間，K 線由上面跌落入場區之前已經掂過 TP → 入場之前嘅價當咗贏（+0.375R）。
嚴格版：成交嗰根唔計 TP（SL 照計）；中間版：成交嗰根開市已經喺入場區先准同根 TP。
注意：呢個係事後審計（11-09 對拍時發現），唔係預先登記嘅新策略。
用法：python3 research/strategy_search/samebar_audit.py <mt5|duka> <由> <到>"""
import sys, numpy as np
ARGV=list(sys.argv)
import os; _H=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(_H,'..','student_offline')); sys.path.insert(0,_H)
import fit_rules as fr, batch_1120 as B120, batch_1079 as B79, asia_sweep as A
def sim(mats, E, Z, S, RT, strict, mid_rule=False):
    O,H,L,T = mats; m=O.shape[0]
    if m==0: return np.array([]), np.array([])
    mid=-E; lo,hi=mid-Z,mid+Z; sl=mid-S; tp=mid+RT*S
    fm=(L<=hi+fr.TOL)&(H>=lo-fr.TOL)&(T<=fr.TTL); has=fm.any(axis=1); f=fm.argmax(axis=1); rows=np.arange(m)
    fill=np.minimum(O[rows,f],np.maximum(hi,L[rows,f])); cols=np.arange(O.shape[1])[None,:]
    slh=(L<=sl)&(cols>=f[:,None]); tph=(H>=tp)&((cols>f[:,None]) if strict else (cols>=f[:,None]))
    if mid_rule:
        okf=(O[rows,f]<=hi+fr.TOL)                  # 成交嗰根開市已經喺入場區（或更低）先准同根 TP
        tph=(H>=tp)&((cols>f[:,None])|((cols==f[:,None])&okf[:,None]))
    s_any,t_any=slh.any(axis=1),tph.any(axis=1)
    si=np.where(s_any,slh.argmax(axis=1),10**9); ti=np.where(t_any,tph.argmax(axis=1),10**9)
    done=has&(s_any|t_any); ex=np.where(si<=ti,sl,tp); r=(ex-fill-fr.COST)/S
    same=(ti==f)&(ti<si)
    return np.where(done,r,np.nan), same&done
# monkeypatch e6s4_at to capture sigs
cap={}
def e6(d, raw, cd):
    t=d["t"]; sigs=fr.cooldown(sorted(raw),t,cd,int(t[0]),int(t[-1])+60); cap['s']=(d,sigs); return []
B79.e6s4_at=e6
def run(d, fn):
    fn(d); dd,sigs=cap['s']; mats=fr.future_mats(dd,sigs)
    r0,same=sim(mats,6,2,4,1,False); r1,_=sim(mats,6,2,4,1,True); r2,_=sim(mats,6,2,4,1,False,True)
    k=~np.isnan(r0); k1=~np.isnan(r1)
    return k.sum(), np.nanmean(r0), same.sum(), k1.sum(), np.nanmean(r1), np.nanmean(r2)
seg=ARGV[1]; a,b=ARGV[2],ARGV[3]
d=A.load(seg,a,b)
for nm,fn in (("m5spike",B120.r1121),("dopen15",B120.r1122),("spike2",B120.r1123)):
    n0,m0,s,n1,m1,m2=run(d,fn)
    print(f"{seg} {a}~{b} {nm}: 原版 n={n0} 平均 {m0:+.3f}R｜同一根先成交後止賺 {s} 張（{s/n0:.0%}）｜嚴格版（成交嗰根唔計 TP） n={n1} 平均 {m1:+.3f}R｜中間版 {m2:+.3f}R")
import rev15_session as RS
t,o,c=d["t"],d["o"],d["c"]; n=len(t); mv=np.full(n,np.nan); mv[RS.LB:]=c[RS.LB:]-o[:-RS.LB]
ok=(np.abs(mv)>=RS.TH)&(np.arange(n)>=29)
raw=[(int(i),"BUY" if mv[i]<0 else "SELL") for i in np.nonzero(ok)[0]]
sigs=fr.cooldown(raw,t,60,int(t[0]),int(t[-1])+60); mats=fr.future_mats(d,sigs)
r0,same=sim(mats,RS.E,RS.Z,RS.S,RS.RT,False); r1,_=sim(mats,RS.E,RS.Z,RS.S,RS.RT,True)
k=~np.isnan(r0)
print(f"{seg} {a}~{b} rev15（E{RS.E}Z{RS.Z}S{RS.S}R{RS.RT}）: 原版 n={k.sum()} 平均 {np.nanmean(r0):+.3f}R｜同根 {same.sum()} 張（{same.sum()/k.sum():.0%}）｜嚴格版 平均 {np.nanmean(r1):+.3f}R")
