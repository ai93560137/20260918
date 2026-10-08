import csv, random, statistics as st
def load(p):
    rows=[r for r in csv.DictReader(open(p)) if r['strat']=='SNAKE']
    return [float(r['net']) for r in rows], rows
MARGIN_BIG=130_000; MARGIN_MINI=26_000
def run(pts, K, start, mult=50, margin=MARGIN_BIG, monthly=None, dates=None):
    """K = capital per contract; lots = max(1, floor(E/K)) recalculated每筆（或每月）；爆倉 = 淨值 < 1張保證金"""
    E=start; peak=start; mdd=0; lots=max(1,int(E//K)); cur_month=None; ruin=False
    for i,p in enumerate(pts):
        if monthly and dates:
            m=dates[i][:7]
            if m!=cur_month: cur_month=m; lots=max(1,int(E//K))
        else: lots=max(1,int(E//K))
        if E<margin*lots: # 保證金不夠 → 減到可持；全無 → 爆倉
            lots=int(E//margin)
            if lots<1: ruin=True; break
        E+=p*mult*lots; peak=max(peak,E); mdd=max(mdd,(peak-E)/peak)
        if E<=0: ruin=True; break
    return E, mdd, ruin
for name,path in [("Futu 2.5年(109筆)","research/hsi_futures_range/gate_tilt/trades_futu.csv"),("HK50 3.6年(161筆)","research/hsi_futures_range/gate_tilt/trades_hk50.csv")]:
    pts,rows=load(path); dates=[r['entry_date'] for r in rows]
    w=[p for p in pts if p>0]; l=[p for p in pts if p<=0]
    print(f"\n==== {name}: 勝率 {len(w)/len(pts):.0%}  平均賺 {st.mean(w):.0f} 平均蝕 {st.mean(l):.0f}  最差單筆 {min(pts):.0f} 點")
    # 最長連虧與連虧累計
    worst=0; run_=0; cum=0; worstcum=0
    for p in pts:
        if p<=0: run_+=1; cum+=p; worst=max(worst,run_); worstcum=min(worstcum,cum)
        else: run_=0; cum=0
    print(f"     最長連虧 {worst} 筆、連虧累計最深 {worstcum:.0f} 點 = HK${-worstcum*50/1e3:.0f}k／張大合約")
    START=1_500_000
    print(f"     起始 HK$1.5M，歷史順序，每筆重算張數（大合約 HK$50/點，保證金 {MARGIN_BIG//1000}k/張）")
    for K in [1_500_000,500_000,250_000,150_000,100_000]:
        E,mdd,ruin=run(pts,K,START,dates=dates,monthly=True)
        print(f"       每張 HK${K/1e3:>5.0f}k（起始 {START//K:>2} 張）: 期末 HK${E/1e6:5.2f}M  回撤 {mdd:5.0%}  {'💀爆倉' if ruin else ''}")
    print(f"     同樣規則改小型合約（HK$10/點，保證金 {MARGIN_MINI//1000}k/張）")
    for K in [300_000,100_000,50_000,20_000]:
        E,mdd,ruin=run(pts,K,START,mult=10,margin=MARGIN_MINI,dates=dates,monthly=True)
        print(f"       每張小型 HK${K/1e3:>4.0f}k（起始 {START//K:>2} 張小型 = {START//K/5:.0f} 張大）: 期末 HK${E/1e6:5.2f}M  回撤 {mdd:5.0%}  {'💀爆倉' if ruin else ''}")
    # bootstrap：打亂順序 5000 次
    random.seed(7)
    print("     打亂交易順序 5,000 次（大合約）：")
    for K in [1_500_000,500_000,250_000,150_000,100_000]:
        ends=[];ruins=0;mdds=[]
        for _ in range(5000):
            s=pts[:]; random.shuffle(s)
            E,mdd,r=run(s,K,START); ends.append(E); mdds.append(mdd); ruins+=r
        ends.sort()
        print(f"       每張 HK${K/1e3:>5.0f}k: 中位期末 HK${ends[2500]/1e6:5.2f}M  最差5% HK${ends[250]/1e6:5.2f}M  回撤中位 {st.median(mdds):4.0%}  爆倉機率 {ruins/5000:5.1%}")
