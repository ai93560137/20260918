import math, random
# --- 1. verify the post ---
p=0.5; 
def g(f): return 0.5*math.log(1+f)+0.5*math.log(1-0.5*f)
best=max((g(f/100),f/100) for f in range(1,100))
print("post: kelly f*=",best[1],"growth/toss=",round(best[0],4),"median after 240 tosses =",round(100*math.exp(240*best[0])/1e8,2),"億")
random.seed(1); N=20000
allin=[]; half=[]
for _ in range(N):
    w1=100.0; w2=100.0
    for _ in range(240):
        if random.random()<0.5: w1*=2; w2*=1.5
        else: w1*=0.5; w2*=0.75
    allin.append(w1); half.append(w2)
print(" all-in: P(<100)=%.1f%%  median=%.1f" % (100*sum(w<100 for w in allin)/N, sorted(allin)[N//2]))
print(" half  : P(<100)=%.2f%%  P(>10億)=%.1f%%  median=%.0f" % (100*sum(w<100 for w in half)/N, 100*sum(w>1e9 for w in half)/N, sorted(half)[N//2]))

# --- 2. the four strategies: binary Kelly f = p - q/b  and continuous Kelly = mu/sigma^2 ---
def binary(p,b): return p-(1-p)/b
def cont(mu,sd): return mu/sd**2
rows=[
 ("蛇蟠陣 HSI1! 8.5年(TV)",      0.395, 1.93),
 ("蛇蟠陣 Futu 2.5年",           0.41,  2.09),
 ("鳥翔 Minervini 港",           0.37,  4.37),
 ("鳥翔 Minervini 美",           0.29,  3.45),
 ("鳥翔 趨勢模板全等權 9市場(月)",0.65,  1.17),
 ("風揚 1σ勒式+Δ0.5對沖(51週)",   0.71,  0.88),
 ("風揚 1σ勒式不對沖(51週)",      0.84,  0.49),
 ("風揚 1σ勒式 36年合成",         0.72,  0.32),
 ("風揚 1.5σ勒式 36年合成",       0.84,  0.12),
 ("雲垂 月沽平值跨式(23年)",      0.72,  None),
]
print("\n二元凱利 f* = p - (1-p)/b   (以『平均虧損』為 1 單位)")
for n,p,b in rows:
    if b: print(f"  {n:32s} p={p:.2f} b={b:.2f} -> f*={binary(p,b)*100:6.1f}%  打和勝率={100/(1+b):.0f}%")

print("\n連續型凱利（每張／每單位名義應配多少資本 = σ²/μ）")
# 蛇: EV 60pt/筆, 二元近似 W=737 L=382 (HK$50/pt)
p,W,L=0.395,737,382; mu=p*W-(1-p)*L; var=p*W*W+(1-p)*L*L-mu*mu
print(f"  蛇蟠陣: μ={mu:.0f}點 σ={var**.5:.0f}點 → 全凱利每張資本 HK${50*var/mu/1e3:,.0f}k ；repo 規則 HK$1,500k/張 ≈ 1/{1500e3/(50*var/mu):.0f} 凱利")
mu,sd=40,119  # 風揚 對沖版 每週
print(f"  風揚對沖勒式: μ={mu}點/週 σ={sd} → 全凱利每張資本 HK${50*sd*sd/mu/1e3:,.1f}k ；repo 規則 HK$1,000k/張 ≈ 1/{1000e3/(50*sd*sd/mu):.0f} 凱利")
mu,sd=0.0165,0.0426 # 鳥翔 P_ALL 持股月
print(f"  鳥翔 P_ALL: μ={mu*100:.2f}%/月 σ={sd*100:.2f}% → 全凱利槓桿 {cont(mu,sd):.1f}x（最差月 −12%~−35% → 爆倉）")
mu,sd=0.0038,0.046/0.77/12**.5 # 雲垂 月淨 0.38%, 年化 4.6%/夏普 0.77
print(f"  雲垂 VRP: μ={mu*100:.2f}%/月 σ={sd*100:.2f}% → 全凱利名義槓桿 {cont(mu,sd):.1f}x（最壞月 −14.5% → 爆倉）；手冊建議名義 ≤30% NAV ≈ 1/{cont(mu,sd)/0.3:.0f} 凱利")
