"""隔夜美股 → 翌日恒指：開市跳空吸收了多少？開市後會延續還是回吐？（1990–2026）"""
import sys, numpy as np, pandas as pd
S = sys.argv[1]
h = pd.read_csv(f"{S}/hsi.csv", parse_dates=["Date"]).set_index("Date"); h = h[h.index >= "1990-01-01"]
s = pd.read_csv(f"{S}/spx.csv", parse_dates=["Date"]).set_index("Date").Close
v = pd.read_csv(f"{S}/vix.csv", parse_dates=["Date"]).set_index("Date").Close
sr = np.log(s).diff()
rows = []
dates = h.index
for i in range(1, len(dates)):
    p, t = dates[i - 1], dates[i]
    us = sr[(sr.index >= p) & (sr.index < t)]       # 恒指前一日收市後到今日開市前完成的美股交易日
    if len(us) == 0: continue
    rows.append((t, us.sum(), np.log(h.Open.iloc[i] / h.Close.iloc[i - 1]), np.log(h.Close.iloc[i] / h.Open.iloc[i]),
                 v[v.index < t].iloc[-1] if (v.index < t).any() else np.nan))
x = pd.DataFrame(rows, columns=["date", "us", "gap", "intra", "vix"]).set_index("date")
x = x[x.gap.abs() > 1e-6]          # 剔除開市價＝昨收的劣質數據
print("可用日數", len(x), x.index[0].date(), "→", x.index[-1].date())
for a, b in (("1990", "2000"), ("2000", "2010"), ("2010", "2020"), ("2020", "2027")):
    y = x[(x.index >= a) & (x.index < b)]
    bg = np.polyfit(y.us, y.gap, 1)[0]; bi = np.polyfit(y.us, y.intra, 1)[0]
    # 策略：跟美股方向，開市買／沽，收市平（成本 1bp）
    pnl = np.sign(y.us) * y.intra - 1e-4
    big = y[y.us.abs() > 0.01]; pb = np.sign(big.us) * big.intra - 1e-4
    print(f"{a}-{b}: 跳空吸收 β={bg:.2f} 相關 {y.us.corr(y.gap):.2f}｜開市後 β={bi:+.3f} 相關 {y.us.corr(y.intra):+.3f}｜"
          f"跟美股方向日內 每日 {pnl.mean()*1e4:+.1f}bp t {pnl.mean()/pnl.std()*np.sqrt(len(pnl)):+.2f}｜"
          f"美股>1% 日 {len(big)} 日 每日 {pb.mean()*1e4:+.1f}bp t {pb.mean()/pb.std()*np.sqrt(len(pb)):+.2f}")
# 跳空本身：大跳空之後日內延續還是回補？
print("\n跳空之後日內（2010–2026）：")
y = x[x.index >= "2010"]
for lo, hi in ((0.01, 1), (0.005, 0.01), (0, 0.005)):
    m = y[(y.gap.abs() >= lo) & (y.gap.abs() < hi)]
    f = -np.sign(m.gap) * m.intra - 1e-4
    print(f"|跳空| {lo:.1%}–{hi:.1%}: {len(m)} 日，逆跳空（回補）每日 {f.mean()*1e4:+.1f}bp t {f.mean()/f.std()*np.sqrt(len(f)):+.2f}")
