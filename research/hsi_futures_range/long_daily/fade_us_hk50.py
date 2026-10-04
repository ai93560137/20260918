"""用 HK50 15 分 K 驗證：日市逆隔夜美股方向（2022-08 → 2026-09）。"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1])); import hk50_cfd
S = sys.argv[1]
bars, _ = hk50_cfd.load()
b = pd.DataFrame(bars); b["t"] = pd.to_datetime(b.time_key); b["hm"] = b.t.dt.strftime("%H:%M"); b["d"] = b.t.dt.normalize()
day = b[(b.hm > "09:15") & (b.hm <= "16:30")]                 # 收市時間 09:30 … 16:30（日市，含午休前後）
g = day.groupby("d")
D = pd.DataFrame({"open": g.open.first(), "close": g.close.last(), "n": g.size()})
D = D[D.n >= 20]
s = pd.read_csv(f"{S}/spx.csv", parse_dates=["Date"]).set_index("Date").Close; sr = np.log(s).diff()
rows = []
for i in range(1, len(D)):
    p, t = D.index[i - 1], D.index[i]
    us = sr[(sr.index >= p) & (sr.index < t)].sum()
    night = np.log(D.open.iloc[i] / D.close.iloc[i - 1])            # 昨日日市收市 → 今日開市（含夜市＋開市跳空）
    rows.append((t, us, night, D.close.iloc[i] - D.open.iloc[i], D.open.iloc[i]))
x = pd.DataFrame(rows, columns=["d", "us", "night", "pts", "px"]).set_index("d")
COST = 3
for nm, sig in (("逆美股", -np.sign(x.us)), ("逆夜市＋跳空", -np.sign(x.night))):
    p = sig * x.pts - COST
    print(f"{nm}：{len(p)} 日 每日 {p.mean():+.1f} 點 勝率 {(p>0).mean():.0%} t {p.mean()/p.std()*np.sqrt(len(p)):+.2f}  "
          + " ".join(f"{y}:{v:+.0f}" for y, v in p.groupby(p.index.year).mean().items()))
    big = x[x.us.abs() > 0.01] if nm == "逆美股" else x[x.night.abs() > 0.01]
    pb = (-np.sign(big.us if nm == "逆美股" else big.night)) * big.pts - COST
    print(f"   只做 >1% 的日子：{len(pb)} 日 每日 {pb.mean():+.1f} 點 t {pb.mean()/pb.std()*np.sqrt(len(pb)):+.2f}")
