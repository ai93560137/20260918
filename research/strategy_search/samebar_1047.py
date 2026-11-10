import sys, numpy as np
sys.path.insert(0,__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'..','student_offline')); sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import asia_sweep as A, ai_entry_forward as af, batch_1045 as B45
orig=af.sim
def strict(d, ts, side, entry, sl, tp, lo=None, hi=None):
    t,o,h,l=d["t"],d["o"],d["h"],d["l"]; sgn=1 if side=="BUY" else -1
    lo=entry if lo is None else lo; hi=entry if hi is None else hi
    a=int(np.searchsorted(t,ts)); fi=None
    for j in range(a,len(t)):
        if t[j]-ts>af.TTL: break
        if l[j]<=hi+af.TOL and h[j]>=lo-af.TOL:
            near=hi if sgn>0 else lo
            fill=min(o[j],max(near,l[j])) if sgn>0 else max(o[j],min(near,h[j])); fi=j; break
    if fi is None: return None
    risk=abs(fill-sl) if lo==hi else abs((lo+hi)/2-sl)
    for j in range(fi,len(t)):
        if t[j]-t[fi]>af.HORIZON: return None
        if (l[j]<=sl) if sgn>0 else (h[j]>=sl): return (sgn*(sl-fill)-af.COST)/risk
        if j>fi and ((h[j]>=tp) if sgn>0 else (l[j]<=tp)): return (sgn*(tp-fill)-af.COST)/risk
    return None
for seg,a_,b_ in (("mt5","2023-01-01","2026-10-30"),("duka","2010-01-01","2014-12-31")):
    d=A.load(seg,a_,b_)
    af.sim=orig; x=np.array([r for _,_,r in B45.r1047(d)]); af.sim=strict; y=np.array([r for _,_,r in B45.r1047(d)])
    print(f"{seg} #1047: 原版 n={len(x)} {x.mean():+.3f}R → 嚴格版 n={len(y)} {y.mean():+.3f}R")
