"""[影子判定力分析，描述性，唔係新策略] #190／#194／#208 三個影子候選同 935 逐月 R 差：要幾多個月先 t=2、1／2 年影子贏 935 機會（月份 bootstrap）。
用法：python3 research/strategy_search/shadow_power.py"""
import sys, datetime as dt, numpy as np
sys.path.insert(0, '/home/user/20260918/research/strategy_search')
import portfolio as P, portfolio_single as PS, robust_long as R, d1_indicators as Q, h4_indicators as H, exits_a as X, xag_lead as XL, candle_ind as CI
R.COST = 0.5
gd = R.load_duka(); sd = XL.load_xag()
ds, _ = P.streams(gd); keys = [k for k in ds if not k.startswith("7")]
fr = {"D1": Q.DI(*gd), "H4": H.H4I(*gd)}
imp = dict(ds)
for name, fam, tf, th in X.COMPS:
    D = fr[tf]; grid = [dict(p, xm=m) for p in Q.FAMILIES[fam] for m in X.MODES]
    T = [X.run(D, fam, p, th) for p in grid]; o, _ = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid); imp[name] = [x for x in o if R.yr(x[0]) >= 2009]
PR = XL.Pair(H.H4I(*gd), H.H4I(*sd), 14400); xg = XL.FAMILIES["X1 白銀均線交叉"]
T = [XL.run(PR, "X1 白銀均線交叉", p, 80) for p in xg]; o, _ = P.wf_stream(lambda p: T[xg.index(p)], xg); xs = [x for x in o if R.yr(x[0]) >= 2009]
Q.T_H = 480; D = fr["D1"]; cg = CI.FAMILIES["C3 內包線突破"]
T = [CI.run(D, "C3 內包線突破", p, 480) for p in cg]; o, _ = P.wf_stream(lambda p: T[cg.index(p)], cg); cs = [x for x in o if R.yr(x[0]) >= 2009]
def mon(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc); mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return mm
base = mon(PS.single(ds, keys)); allm = sorted({(y, m) for y in range(2009, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)})
b = np.array([base.get(k, 0) for k in allm])
rng = np.random.default_rng(0)
for lab, trs in (("改良版", PS.single(imp, keys)), ("935＋白銀", PS.single({**ds, "X": xs}, keys + ["X"])), ("935＋內包線", PS.single({**ds, "C": cs}, keys + ["C"]))):
    c = np.array([mon(trs).get(k, 0) for k in allm]); d = c - b
    mu, sdv = d.mean(), d.std(ddof=1); need = (2 * sdv / mu) ** 2 if mu > 0 else float('inf')
    # 1 年（12 個月）影子贏 935 嘅機會（月份 bootstrap）
    win12 = np.mean([rng.choice(d, 12).sum() > 0 for _ in range(20000)])
    win24 = np.mean([rng.choice(d, 24).sum() > 0 for _ in range(20000)])
    print(lab, f"每月多 {mu:+.3f}R 標準差 {sdv:.2f}", f"t=2 要 {need:.0f} 個月（{need/12:.0f} 年）", f"1 年贏 935 機會 {win12:.0%}", f"2 年 {win24:.0%}", f"18 年合計差 {d.sum():+.1f}R")
