#!/usr/bin/env python3
"""NQ 期權收權金研究 — 用 OHLC 能算的部分（README 第二十一節）。

期權把「找方向」換成「賭波動率定價」。賣方的損益 = 收到的權金 − 標的路徑造成的賠付。
賠付端完全由 OHLC 決定，可以精確計算；權金端需要 IV（VXN 或實際報價），
資料抓得到就一起算，抓不到就把「收支平衡所需的 IV」算出來給人對照。

    python3 nq_options_study.py                 # OHLC 部分
    python3 nq_options_study.py --vxn VXN.csv   # 加上 VRP 檢定
"""
import argparse
import numpy as np
import pandas as pd

STRADDLE_K = 0.7979  # BS 近似：ATM straddle 價 ≈ S·σ·√T·√(2/π)


def load_d1():
    d = pd.read_csv("data/NAS100_D1.csv.gz", parse_dates=["Time"],
                    date_format="%Y.%m.%d %H:%M:%S").set_index("Time")
    return d


def monthly_paths(d):
    """每月：起點收盤、終點收盤、月內最低/最高（賣方的路徑風險）"""
    g = d.groupby(d.index.to_period("M"))
    out = pd.DataFrame(dict(
        open_=g.Close.first(), close=g.Close.last(),
        lo=g.Low.min(), hi=g.High.max(), n=g.Close.count()))
    out["ret"] = out.close / out.open_ - 1
    out["dn_path"] = out.lo / out.open_ - 1   # 月內最深
    out["up_path"] = out.hi / out.open_ - 1   # 月內最高
    return out[out.n >= 15]  # 去掉殘月


def part_rv(d):
    r = np.log(d.Close / d.Close.shift(1)).dropna()
    mrv = r.groupby(r.index.to_period("M")).std() * np.sqrt(252) * 100
    mrv = mrv[r.groupby(r.index.to_period("M")).count() >= 15]
    print("=" * 78)
    print("A. 已實現波動的結構（賣方的『貨』）")
    print("=" * 78)
    print(f"月 RV 分佈：中位 {mrv.median():.1f}%  P25 {mrv.quantile(.25):.1f}%  "
          f"P75 {mrv.quantile(.75):.1f}%  P95 {mrv.quantile(.95):.1f}%  最高 {mrv.max():.1f}%"
          f"（{mrv.idxmax()}）")
    print(f"月 RV lag-1 自相關 {mrv.autocorr(1):+.2f}（波動叢聚 → 本月 RV 對下月有預測力）")
    up = (mrv.shift(-1) - mrv).dropna()
    print(f"月 RV 環比變化：標準差 {up.std():.1f} 個波動點  最大單月跳升 +{up.max():.1f} 點"
          f"（{up.idxmax()} → 下月）")
    return mrv


def part_breakeven(mp):
    print("\n" + "=" * 78)
    print("B. 收支平衡所需權金（到期結算，賠付端由路徑精確決定）")
    print("=" * 78)
    n = len(mp)
    yrs = n / 12
    # ATM straddle：賣方賠 |R|
    pay = mp.ret.abs()
    be_iv = pay.mean() / (STRADDLE_K * np.sqrt(1 / 12)) * 100
    print(f"\n【賣月度 ATM straddle】n={n} 個月")
    print(f"  平均賠付 {pay.mean()*100:.2f}%/月  中位 {pay.median()*100:.2f}%  "
          f"最壞 {pay.max()*100:.2f}%（{pay.idxmax()}）")
    print(f"  → 收支平衡所需 IV ≈ {be_iv:.1f}%（低於這個 IV 賣 straddle 必虧）")

    print(f"\n【賣月度 strangle ±k%・到期結算】")
    print(f"  {'k':>5} {'月破率':>7} {'平均賠付':>9} {'最壞賠付':>9} {'損益兩平權金':>11} "
          f"{'月內觸價率':>9} {'觸而未破':>8}")
    for k in [0.03, 0.05, 0.07, 0.10]:
        breach = np.maximum(mp.ret - k, 0) + np.maximum(-mp.ret - k, 0)
        touched = (mp.dn_path < -k) | (mp.up_path > k)
        endbr = breach > 0
        print(f"  {k*100:>4.0f}% {endbr.mean()*100:>6.1f}% {breach.mean()*100:>8.3f}% "
              f"{breach.max()*100:>8.2f}% {breach.mean()*100:>10.3f}%/月 "
              f"{touched.mean()*100:>8.1f}% {(touched & ~endbr).mean()*100:>7.1f}%")
    print("  （損益兩平權金 = 平均賠付；觸而未破 = 月內穿過履約價但月底收回來 —— "
          "這些月對「抱到期」是 0 賠付，對「觸價就砍」是實虧）")

    print(f"\n【只賣 put（收跌方權金）±k%】")
    print(f"  {'k':>5} {'月破率':>7} {'平均賠付':>9} {'最壞賠付':>9} {'月內觸價率':>9}")
    for k in [0.03, 0.05, 0.07, 0.10]:
        breach = np.maximum(-mp.ret - k, 0)
        touched = mp.dn_path < -k
        print(f"  {k*100:>4.0f}% {(breach>0).mean()*100:>6.1f}% {breach.mean()*100:>8.3f}% "
              f"{breach.max()*100:>8.2f}% {touched.mean()*100:>8.1f}%")


def part_tail(mp, d):
    print("\n" + "=" * 78)
    print("C. 尾部與規模（空城計算術）")
    print("=" * 78)
    r = d.Close.pct_change().dropna()
    gap = (d.Open / d.Close.shift(1) - 1).dropna()
    print(f"最壞單日 {r.min()*100:+.2f}%  最壞隔夜跳空 {gap.min()*100:+.2f}%  "
          f"最壞單月 {mp.ret.min()*100:+.2f}%（{mp.ret.idxmin()}）")
    print(f"歷史最壞（2020-03，不在本資料內）：單日 −12%、單月 −20% 量級 —— 尾部要用這個算")
    worst = 0.20
    for tol in [0.20]:
        cap = tol / worst
        print(f"裸賣 put 的名義曝險 = 賣出的行使名義。容忍回撤 {tol*100:.0f}%、"
              f"最壞月 {worst*100:.0f}% → 高水位上限 {cap:.2f}x（比做多期貨的 1.67x 更緊）")


def part_vrp(mrv, vxn_csv):
    print("\n" + "=" * 78)
    print("D. VRP 檢定：VXN（隱含）vs 其後已實現 —— 這是決定性的量")
    print("=" * 78)
    vx = pd.read_csv(vxn_csv)
    dcol = [c for c in vx.columns if c.upper().startswith("DATE")][0]
    ccol = "CLOSE" if "CLOSE" in [c.upper() for c in vx.columns] else vx.columns[-1]
    vx.columns = [c.upper() for c in vx.columns]
    vx["DATE"] = pd.to_datetime(vx["DATE"])
    vx = vx.set_index("DATE")["CLOSE"].astype(float)
    # 月初 VXN vs 該月已實現
    vxm = vx.groupby(vx.index.to_period("M")).first()
    common = vxm.index.intersection(mrv.index)
    vxm, rv = vxm[common], mrv[common]
    prem = vxm - rv
    print(f"樣本 {len(common)} 個月（{common[0]} → {common[-1]}）")
    print(f"月初 VXN 平均 {vxm.mean():.1f}%  該月 RV 平均 {rv.mean():.1f}%  "
          f"→ 平均 IV−RV = {prem.mean():+.1f} 個波動點")
    print(f"IV > RV 的月份：{(prem>0).mean()*100:.0f}%   IV−RV 中位 {prem.median():+.1f}  "
          f"最壞 {prem.min():+.1f}（{prem.idxmin()}）")
    t = prem.mean() / (prem.std() / np.sqrt(len(prem)))
    print(f"IV−RV 的 t = {t:+.2f}")
    for y in sorted(set(common.year)):
        m = common.year == y
        print(f"  {y}: VXN {vxm[m].mean():.1f}  RV {rv[m].mean():.1f}  "
              f"差 {prem[m].mean():+.1f}  正月率 {(prem[m]>0).mean()*100:.0f}%")
    # 換算成 straddle 語言
    print(f"\n以 B 段的公式換算：IV 每高於收支平衡 1 個波動點 ≈ "
          f"月權金多 {STRADDLE_K*np.sqrt(1/12)*100:.2f}% 名義")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vxn", default=None)
    a = ap.parse_args()
    d = load_d1()
    mp = monthly_paths(d)
    mrv = part_rv(d)
    part_breakeven(mp)
    part_tail(mp, d)
    if a.vxn:
        part_vrp(mrv, a.vxn)
