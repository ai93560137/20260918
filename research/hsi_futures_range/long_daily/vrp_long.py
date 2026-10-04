"""賣期權（波動率溢價）長期測試：VHSI 2003–2026 對恒指之後實際波幅。"""
import sys, numpy as np, pandas as pd
from math import erf, sqrt, log, exp
S = sys.argv[1]
h = pd.read_csv(f"{S}/hsi.csv", parse_dates=["Date"]).set_index("Date")
v = pd.read_csv(f"{S}/vhsi.csv", parse_dates=["Date"]).set_index("Date").Close.rename("vhsi")
d = h.join(v, how="inner").dropna()
d = d[d.index >= "2003-07-01"]
r = np.log(d.Close).diff()
# Parkinson 日內波幅（用高低）＋ HAR 預測下月波幅（簡化：日/週/月 平均的加權）
pk = (np.log(d.High / d.Low) ** 2 / (4 * log(2)))
cc = r ** 2
var_d = pk  # 用高低估日方差
har = (0.3 * var_d.rolling(1).mean() + 0.35 * var_d.rolling(5).mean() + 0.35 * var_d.rolling(22).mean())
d["har_vol"] = np.sqrt(har * 252) * 100 * 1.15   # 高低估計偏低（無隔夜跳空），粗略放大
d["rv22"] = np.sqrt(cc.rolling(22).mean() * 252) * 100

def ncdf(x): return 0.5 * (1 + erf(x / sqrt(2)))
def straddle(sig, T):   # ATM 跨式（佔現價百分比），r=0
    s = sig * sqrt(T); return 2 * (ncdf(s / 2) - ncdf(-s / 2))

def test(H, haircut, ratio_min=None, label=""):
    idx = d.index
    out = []
    i = 22
    while i + H < len(d):
        iv = d.vhsi.iloc[i] * haircut / 100
        ok = ratio_min is None or d.vhsi.iloc[i] / d.har_vol.iloc[i] >= ratio_min
        if ok:
            prem = straddle(iv, H / 252)
            move = abs(d.Close.iloc[i + H] / d.Close.iloc[i] - 1)
            out.append((idx[i], prem - move - 0.0010, prem))   # 成本：來回 0.1% 現價
        i += H
    t = pd.DataFrame(out, columns=["date", "pnl", "prem"]).set_index("date")
    x = t.pnl.values
    yrs = t.groupby(t.index.year).pnl.sum()
    eq = np.cumsum(x); dd = (np.maximum.accumulate(eq) - eq).max()
    print(f"{label:28s} {len(x):4d} 次 每次 {x.mean()*100:+.2f}% (權利金 {t.prem.mean()*100:.2f}%) 勝率 {(x>0).mean():.0%} "
          f"t {x.mean()/x.std(ddof=1)*sqrt(len(x)):+.2f} 最差 {x.min()*100:+.1f}% 回撤 {dd*100:.1f}% 賺錢年 {(yrs>0).sum()}/{len(yrs)}")
    return t

print("VHSI 平均", round(d.vhsi.mean(), 1), "／之後 22 日實際波幅平均", round(d.rv22.shift(-22).mean(), 1),
      "／VHSI 高過之後實際的比例", f"{(d.vhsi > d.rv22.shift(-22)).mean():.0%}")
print("HAR 預測 vs 之後實際 相關", round(d.har_vol.corr(d.rv22.shift(-22)), 2), "；VHSI vs 之後實際", round(d.vhsi.corr(d.rv22.shift(-22)), 2))
for H, nm in ((22, "月"), (5, "週")):
    print(f"\n== 賣 {nm} ATM 跨式（2003–2026）")
    for hc in (1.0, 0.9, 0.85):
        test(H, hc, None, f"IV = VHSI×{hc}")
    for rm in (1.0, 1.2, 1.4):
        test(H, 0.9, rm, f"IV=VHSI×0.9 且 VHSI/HAR≥{rm}")
t = test(5, 0.9, 1.2, "週 0.9 ≥1.2 逐年")
print(" ".join(f"{y}:{s*100:+.0f}%" for y, s in t.groupby(t.index.year).pnl.sum().items()))
