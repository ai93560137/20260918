import pandas as pd, numpy as np
from math import erf, log, sqrt

def N(x): return 0.5*(1+erf(x/sqrt(2)))
def bs(S, K, T, vol, cp):
    d1 = (log(S/K)+0.5*vol*vol*T)/(vol*sqrt(T)); d2 = d1-vol*sqrt(T)
    c = S*N(d1)-K*N(d2)
    return c if cp=='c' else c-S+K   # put-call parity, r=q=0

def t_of(x): return x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>5 and x.std()>0 else np.nan

v = pd.read_csv('data_external/vhsi_daily.csv', parse_dates=['Date']).set_index('Date')
h = pd.read_csv('data_external/hsi_daily.csv', parse_dates=['Date']).set_index('Date')
al = pd.DataFrame({'iv': v.Close/100, 'S': h.Close}).dropna()
al['S_T'] = al.S.shift(-21)          # 21 個交易日後結算
mo = al.groupby(al.index.to_period('M')).first().dropna()
T = 21/252
COST = 0.0005   # 每個兩腿結構的進場成本 ≈ 名義的 0.05%（持有到結算，無出場成本）

def payoff(row, legs):
    """legs: list of (cp, K_ratio, +1買/-1賣)。回傳 P&L 佔名義 S0 的 %"""
    S0, ST, iv = row.S, row.S_T, row.iv
    pnl = 0.0
    for cp, kr, sgn in legs:
        K = kr*S0
        prem = bs(S0, K, T, iv, cp)
        term = max(ST-K, 0) if cp=='c' else max(K-ST, 0)
        pnl += sgn*(term - prem)
    return pnl/S0*100 - COST*100*1  # 一個結構收一次成本

STRUCTS = {
 'Put credit spread 97/92（NQ 式）': [('p',0.97,-1),('p',0.92,+1)],
 'Call credit spread 103/108':       [('c',1.03,-1),('c',1.08,+1)],
 'Iron condor 97/92 + 103/108':      [('p',0.97,-1),('p',0.92,+1),('c',1.03,-1),('c',1.08,+1)],
 'ATM 跨式（§10 對照）':               [('p',1.00,-1),('c',1.00,-1)],
}
half = len(mo)//2
print(f"n={len(mo)} 個不重疊月份  {mo.index[0]} → {mo.index[-1]}   成本 {COST*100:.2f}%/結構\n")
print(f"{'結構':<32}{'月均%':>8}{'t':>7}{'勝率':>7}{'最壞月':>8}{'去頂5%':>8}{'前半t':>7}{'後半t':>7}{'22-08起':>9}")
for name, legs in STRUCTS.items():
    pnl = mo.apply(payoff, axis=1, legs=legs)
    if 'condor' in name.lower(): pnl -= COST*100  # 四腿收兩份成本
    s = pnl.sort_values(); k = max(1,int(len(s)*0.05))
    trim = s.iloc[:-k].mean()
    rec = pnl[pnl.index >= '2022-08']
    print(f"{name:<32}{pnl.mean():>+8.3f}{t_of(pnl):>+7.2f}{(pnl>0).mean()*100:>6.0f}%{pnl.min():>+8.2f}"
          f"{trim:>+8.3f}{t_of(pnl.iloc[:half]):>+7.2f}{t_of(pnl.iloc[half:]):>+7.2f}{rec.mean():>+9.3f}")

print("\n══ 災難月對照：哪邊被誰殺 ══")
ps = mo.apply(payoff, axis=1, legs=STRUCTS['Put credit spread 97/92（NQ 式）'])
cs = mo.apply(payoff, axis=1, legs=STRUCTS['Call credit spread 103/108'])
print("  Put spread 最壞 5 個月：", ", ".join(f"{d}({x:+.1f})" for d,x in ps.nsmallest(5).items()))
print("  Call spread 最壞 5 個月：", ", ".join(f"{d}({x:+.1f})" for d,x in cs.nsmallest(5).items()))
c = np.corrcoef(ps, cs)[0,1]
print(f"  兩者月度相關 = {c:+.2f}")

print("\n══ 補測：越貼近平值，溢價越看得到？ ══")
STRUCTS2 = {
 'ATM put spread 100/95':        [('p',1.00,-1),('p',0.95,+1)],
 'ATM call spread 100/105':      [('c',1.00,-1),('c',1.05,+1)],
 '近值勒式 98/102（不對沖）':        [('p',0.98,-1),('c',1.02,-1)],
}
print(f"{'結構':<28}{'月均%':>8}{'t':>7}{'勝率':>7}{'最壞月':>8}{'去頂5%':>8}{'前半t':>7}{'後半t':>7}")
for name, legs in STRUCTS2.items():
    pnl = mo.apply(payoff, axis=1, legs=legs)
    s = pnl.sort_values(); k = max(1,int(len(s)*0.05))
    print(f"{name:<28}{pnl.mean():>+8.3f}{t_of(pnl):>+7.2f}{(pnl>0).mean()*100:>6.0f}%{pnl.min():>+8.2f}"
          f"{s.iloc[:-k].mean():>+8.3f}{t_of(pnl.iloc[:half]):>+7.2f}{t_of(pnl.iloc[half:]):>+7.2f}")
