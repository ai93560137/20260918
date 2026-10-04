"""蛇蟠陣 N=3 加過濾：只做大趨勢方向／只做高波動期。逐日持倉計回報（可以空手）。"""
import sys, numpy as np, pandas as pd
S = sys.argv[1]
d = pd.read_csv(f"{S}/hsi.csv", parse_dates=["Date"]).set_index("Date"); d = d[d.index >= "1990-01-01"]
v = pd.read_csv(f"{S}/vhsi.csv", parse_dates=["Date"]).set_index("Date").Close.reindex(d.index).ffill()
O, H, L, C = d.Open.values, d.High.values, d.Low.values, d.Close.values
N, COST = 3, 2e-4
# 逐日蛇方向（收市時的持倉）與當日成交
pos = np.zeros(len(d)); p = 0
for k in range(N, len(d)):
    up, lo = H[k-N:k].max(), L[k-N:k].min()
    if p <= 0 and H[k] >= up: p = 1
    elif p >= 0 and L[k] <= lo: p = -1
    pos[k] = p
# 簡化：以收市價計，持倉 = 昨日收市時的蛇方向（保守：比真實止損單晚成交）
ret = np.r_[0, np.diff(np.log(C))]
def evalf(mask_fn, label):
    w = np.r_[0, pos[:-1]] * mask_fn()
    turn = np.abs(np.diff(np.r_[0, w]))
    r = w * ret - turn * COST / 2
    s = pd.Series(r, index=d.index)
    out = []
    for a, b in (("1990", "2000"), ("2000", "2010"), ("2010", "2020"), ("2020", "2027")):
        x = s[a:b]; out.append(f"{x.mean()*252*100:+5.1f}%/{x.mean()/x.std()*np.sqrt(252):+.2f}")
    x = s["2010":]
    print(f"{label:24s} 年化回報/夏普  90s {out[0]}  00s {out[1]}  10s {out[2]}  20s {out[3]}  | 2010起在市 {np.mean(w[d.index>='2010']!=0):.0%}")
ma = lambda n: pd.Series(C).rolling(n).mean().values
one = lambda: np.ones(len(d))
evalf(one, "蛇（收市價版）")
evalf(lambda: (np.r_[0, pos[:-1]] > 0).astype(float), "只做多")
for n in (50, 100, 200):
    m = ma(n); tr = np.sign(C - m); tr = np.r_[0, tr[:-1]]
    evalf(lambda tr=tr: (np.r_[0, pos[:-1]] == tr).astype(float), f"只跟 {n} 日均線方向")
vv = np.r_[np.nan, v.values[:-1]]
for q in (20, 25):
    evalf(lambda q=q: (vv >= q).astype(float), f"VHSI ≥ {q} 才做")
    evalf(lambda q=q: (vv < q).astype(float), f"VHSI < {q} 才做")
bh = pd.Series(ret, index=d.index)
print("買入持有 年化/夏普 " + "  ".join(f"{bh[a:b].mean()*252*100:+.1f}%/{bh[a:b].mean()/bh[a:b].std()*np.sqrt(252):+.2f}"
      for a, b in (("1990", "2000"), ("2000", "2010"), ("2010", "2020"), ("2020", "2027"))))
