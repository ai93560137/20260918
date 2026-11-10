import sys, numpy as np
ARGV=list(sys.argv)
sys.path.insert(0,__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'..','student_offline')); sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import fit_rules as fr, asia_sweep as A
orig=fr.simulate
def strict(mats,E,Z,S,RT):
    O,H,L,T=mats; m=O.shape[0]
    if m==0: return np.array([])
    mid=-E; lo,hi=mid-Z,mid+Z; sl=mid-S; tp=mid+RT*S
    fm=(L<=hi+fr.TOL)&(H>=lo-fr.TOL)&(T<=fr.TTL); has=fm.any(axis=1); f=fm.argmax(axis=1); rows=np.arange(m)
    fill=np.minimum(O[rows,f],np.maximum(hi,L[rows,f])); cols=np.arange(O.shape[1])[None,:]
    slh=(L<=sl)&(cols>=f[:,None]); tph=(H>=tp)&(cols>f[:,None])
    s_any,t_any=slh.any(axis=1),tph.any(axis=1)
    si=np.where(s_any,slh.argmax(axis=1),10**9); ti=np.where(t_any,tph.argmax(axis=1),10**9)
    done=has&(s_any|t_any); ex=np.where(si<=ti,sl,tp); r=(ex-fill-fr.COST)/S
    return np.where(done,r,np.nan)
import batch_1015 as B15, batch_1067 as B67, batch_1083 as B83, batch_1033 as B33, batch_1045 as B45, batch_1059 as B59, batch_1079 as B79
rules=[("#1017 rev60",B15.r1017),("#1067 M1 急動",B67.r1067),("#1083 偏離EMA60",B83.r1083),("#1033 rev15+D1",B33.r1033),("#1047 紐約開市",B45.r1047),("#1061",B59.r1061),("#1080 連4根",B79.r1080)]
d=A.load(ARGV[1],ARGV[2],ARGV[3])
def rs(out):
    if isinstance(out,tuple): out=out[0]
    return np.array([x[2] for x in out],float)
for nm,fn in rules:
    fr.simulate=orig; a=rs(fn(d)); fr.simulate=strict; b=rs(fn(d))
    print(f"{ARGV[1]} {nm}: 原版 n={len(a)} {np.mean(a):+.3f}R → 嚴格版 n={len(b)} {np.mean(b):+.3f}R")
