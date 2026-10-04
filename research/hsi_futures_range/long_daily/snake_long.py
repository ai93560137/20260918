"""蛇蟠陣（Donchian N 日 SAR）在恒指日線 1990–2026 的長期測試。"""
import sys, numpy as np, pandas as pd
d = pd.read_csv(sys.argv[1], parse_dates=["Date"])
d = d[d.Date >= "1990-01-01"].reset_index(drop=True)
COST = 2e-4   # 每筆來回 2 個基點（恒指 25000 點 ≈ 5 點）

def run(N, cost=COST):
    O, H, L = d.Open.values, d.High.values, d.Low.values
    pos, px, tr = 0, None, []
    for k in range(N, len(d)):
        up, lo = H[k-N:k].max(), L[k-N:k].min()
        hits = []
        if H[k] >= up and pos <= 0: hits.append(("up", max(up, O[k])))
        if L[k] <= lo and pos >= 0: hits.append(("dn", min(lo, O[k])))
        # 同一日兩邊都碰：離開市價近的先觸發
        hits.sort(key=lambda h: abs(h[1] - O[k]))
        for side, f in hits:
            if side == "up" and pos <= 0:
                if pos < 0: tr.append((d.Date[k], -1, (px - f) / px - cost))
                pos, px = 1, f
            elif side == "dn" and pos >= 0:
                if pos > 0: tr.append((d.Date[k], 1, (f - px) / px - cost))
                pos, px = -1, f
    return pd.DataFrame(tr, columns=["date", "side", "ret"])

def st(x):
    x = np.asarray(x)
    if len(x) < 2: return "—"
    w = x[x > 0]; l = x[x <= 0]
    return (f"{len(x):5d} 筆 每筆 {x.mean()*1e4:+6.1f}bp 勝率 {len(w)/len(x):.0%} RRR {w.mean()/-l.mean():.2f} "
            f"t {x.mean()/x.std(ddof=1)*np.sqrt(len(x)):+.2f} 年化 {x.sum()/36.7*100:+.1f}%")

print("== N 敏感度（1990–2026，成本 2bp）")
for N in (2, 3, 4, 5, 7, 10, 15, 20, 30, 50):
    print(f"N={N:2d}", st(run(N).ret))
t = run(3)
print("\n== N=3 按年代")
for a, b in ((1990, 2000), (2000, 2010), (2010, 2020), (2020, 2027)):
    print(a, b, st(t[(t.date.dt.year >= a) & (t.date.dt.year < b)].ret))
print("\n== N=3 做多／做空")
for s in (1, -1): print(s, st(t[t.side == s].ret))
print("\n== N=3 逐年（每筆 bp）")
g = t.groupby(t.date.dt.year).ret
print(" ".join(f"{y}:{m*1e4:+.0f}" for y, m in g.mean().items()))
print("賺錢年份", (g.sum() > 0).sum(), "/", g.ngroups)
print("\n== 零成本 N=3", st(run(3, 0).ret))
