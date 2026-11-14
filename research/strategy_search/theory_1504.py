"""[IDEAS #1504–#1508] 理論測試：衰減顯著性（#1504）、效應提前（#1505）、多空唔對稱係咪只係股票平均升幅（#1506）、波幅條件（#1507）、市場深度（#1508，探索）。
規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。用法：python3 research/strategy_search/theory_1504.py → research/strategy_search/THEORY_1504.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import paper_robust as PR    # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "THEORY_1504.md")
COST = 0.0004
W0, W1 = pd.Period("2010-07", "M"), pd.Period("2026-10", "M")
DEEP = ("^GSPC", "^GDAXI", "^FTSE", "^N225", "^FCHI", "^HSI", "^KS11")


def table(tk, zn, lag):
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; b = (zn.shift(1) if lag else zn).reindex(s.index, method="ffill")
    z = pd.DataFrame({"s": s, "b": b}).dropna(); z["v"] = z.s.pct_change().rolling(20).std(); r5 = (z.s.shift(-5) / z.s - 1).dropna()
    gs = [(p, g) for p, g in z.groupby(z.index.to_period("M"))]; out = []
    for i in range(1, len(gs)):
        p, g = gs[i]; p0 = gs[i - 1][1].iloc[-1]
        if len(g) < 16 or not (W0 <= p <= W1):
            continue
        a11, a6, e = g.iloc[-11], g.iloc[-6], g.iloc[-1]; rel6 = (a6.s / p0.s - 1) - (a6.b / p0.b - 1); rel11 = (a11.s / p0.s - 1) - (a11.b / p0.b - 1)
        out.append({"m": p, "rel": rel6, "r": e.s / a6.s - 1, "early": (1.0 if rel11 < 0 else -1.0) * (a6.s / a11.s - 1), "late": (1.0 if rel6 < 0 else -1.0) * (e.s / a6.s - 1), "vol": a6.v})
    d = pd.DataFrame(out).set_index("m"); d["x"] = d.late - COST
    return d, float(r5[(r5.index >= "2010-07-01") & (r5.index <= "2026-10-31")].mean())


def per(x, a, b):
    return x[(x.index.year >= a) & (x.index.year <= b)]


def trend(y):
    t = np.arange(len(y), dtype=float); X = np.c_[np.ones(len(y)), t]; beta, *_ = np.linalg.lstsq(X, y.to_numpy(), rcond=None); e = y.to_numpy() - X @ beta
    se = np.sqrt(e @ e / (len(y) - 2) * np.linalg.inv(X.T @ X)[1, 1]); return float(beta[1]), float(beta[1] / se)


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; T = {}; MU = {}
    for nm, tk, lag in PR.MK:
        T[tk], MU[tk] = table(tk, zn, lag)
    L = ["# #1504–#1508：理論測試（月尾股債再平衡，14 個市場，2010-07–2026-10）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每月面板＝14 個市場當月平均；只讀研究", ""]
    P = pd.DataFrame({tk: T[tk].x for tk in T}).mean(axis=1); E = pd.DataFrame({tk: T[tk].early for tk in T}).mean(axis=1); La = pd.DataFrame({tk: T[tk].late for tk in T}).mean(axis=1)
    # ---- 1504
    a, b, c = per(P, 2010, 2015), per(P, 2016, 2020), per(P, 2021, 2026); d = float(c.mean() - a.mean()); tw = DR.welch(c.to_numpy(), a.to_numpy()); sl, ts = trend(P); ok4 = (d < 0 and tw <= -2.0) or (sl < 0 and ts <= -2.0)
    L += ["## #1504 衰減係咪統計上顯著", "", f"- 面板策略每月淨：2010–15 {100 * a.mean():+.3f}%（{len(a)} 個月）、2016–20 {100 * b.mean():+.3f}%、2021–26 {100 * c.mean():+.3f}%（{len(c)} 個月）；全期 {100 * P.mean():+.3f}%（t {PM.tstat(P):+.2f}）",
          f"- (i) 2021–26 − 2010–15＝{100 * d:+.3f}%，Welch t {tw:+.2f}；(ii) 線性趨勢斜率 {1e4 * sl * 12:+.2f} bp／年，t {ts:+.2f}",
          f"- 分段各自 t：2010–15 {PM.tstat(a):+.2f}、2016–20 {PM.tstat(b):+.2f}、2021–26 {PM.tstat(c):+.2f}",
          f"- 判決：{'✅ 減弱統計上顯著' if ok4 else '❌ 點估計下降，但統計上唔顯著（唔可以寫「效應已減弱」，只可以寫「近年點估計較低」）'}", ""]
    # ---- 1505
    D = E - La; da, dc = per(D, 2010, 2015), per(D, 2021, 2026); dd = float(dc.mean() - da.mean()); td = DR.welch(dc.to_numpy(), da.to_numpy())
    L += ["## #1505 理論 A1：效應提前", "", "| 時期 | 早段（倒數第 11→6 日） | 尾段（倒數第 6 日→月尾） | 早段 − 尾段 |", "|---|---|---|---|"]
    for nm, (y0, y1) in (("2010–15", (2010, 2015)), ("2016–20", (2016, 2020)), ("2021–26", (2021, 2026))):
        L.append(f"| {nm} | {100 * per(E, y0, y1).mean():+.3f}% | {100 * per(La, y0, y1).mean():+.3f}% | {100 * per(D, y0, y1).mean():+.3f}% |")
    v5 = "✅ 支持（效應向前移）" if dd > 0 and td >= 2.0 else ("❌ 證偽（冇向前移）" if dd <= 0 else "未能判斷（方向啱但唔顯著）")
    L += ["", f"- 「早段 − 尾段」2021–26 減 2010–15＝{100 * dd:+.3f}%，Welch t {td:+.2f} → {v5}", f"- 早段全期平均 {100 * E.mean():+.3f}%（t {PM.tstat(E):+.2f}）", ""]
    # ---- 1506
    rows = []; L += ["## #1506 多空唔對稱係咪只係股票平均升幅", "", "| 市場 | 所有 5 日平均 μ_全部 | 月尾 5 日無條件平均 | 做多月份回報 | 做空月份指數回報 | 做多超額 | 做空超額 |", "|---|---|---|---|---|---|---|"]
    for nm, tk, _ in PR.MK:
        z = T[tk]; mu = MU[tk]; lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; rows.append((mu, float(z.r.mean()), float(lo.mean() - mu), float(mu - hi.mean())))
        L.append(f"| {nm} | {100 * mu:+.3f}% | {100 * z.r.mean():+.3f}% | {100 * lo.mean():+.3f}% | {100 * hi.mean():+.3f}% | {100 * (lo.mean() - mu):+.3f}% | {100 * (mu - hi.mean()):+.3f}% |")
    R = np.array(rows); me = pd.DataFrame({tk: T[tk].r - MU[tk] for tk in T}).mean(axis=1); tme = PM.tstat(me); ok6 = R[:, 3].mean() >= 0.5 * R[:, 2].mean() and abs(tme) < 2
    L += [f"| **平均** | **{100 * R[:, 0].mean():+.3f}%** | **{100 * R[:, 1].mean():+.3f}%** | | | **{100 * R[:, 2].mean():+.3f}%** | **{100 * R[:, 3].mean():+.3f}%** |", "",
          f"- 月尾 5 日無條件平均 − μ_全部（面板每月序列）平均 {100 * me.mean():+.3f}%，t {tme:+.2f}；做空超額÷做多超額＝{R[:, 3].mean() / R[:, 2].mean():.2f}",
          f"- 判決：{'唔對稱主要係股票平均升幅造成，唔係新現象（扣返平均升幅之後多空兩邊差唔多）' if ok6 else '扣返股票平均升幅之後仍然唔對稱（或者月尾本身有額外漂移）→ 要再解釋'}", ""]
    # ---- 1507
    hi_all, lo_all, npos = [], [], 0; hi3, lo3 = [], []
    for nm, tk, _ in PR.MK:
        z = T[tk]; q = z[z.rel < 0].dropna(subset=["vol"]); med = z.vol.median(); h, l = q.r[q.vol > med], q.r[q.vol <= med]; hi_all += list(h); lo_all += list(l); npos += int(h.mean() > l.mean())
        big = q[q.rel.abs() >= z.rel.abs().quantile(2 / 3)]; hi3 += list(big.r[big.vol > med]); lo3 += list(big.r[big.vol <= med])
    d7 = float(np.mean(hi_all) - np.mean(lo_all)); t7 = DR.welch(np.array(hi_all), np.array(lo_all)); d73 = float(np.mean(hi3) - np.mean(lo3)); t73 = DR.welch(np.array(hi3), np.array(lo3))
    v7 = "✅ 支持" if d7 > 0 and t7 >= 2.0 and npos >= 10 else ("❌ 證偽" if d7 <= 0 else "未能判斷")
    L += ["## #1507 理論 B2：波幅高嗰陣做多效應更大", "", f"- 做多月份最後 5 日回報：高波幅 {100 * np.mean(hi_all):+.3f}%（{len(hi_all)} 個市場月）、低波幅 {100 * np.mean(lo_all):+.3f}%（{len(lo_all)}）；差 {100 * d7:+.3f}%，Welch t {t7:+.2f}；差為正嘅市場 {npos}／14 → {v7}",
          f"- 控制偏離（只睇偏離最大三分一嘅做多月份）：高波幅 {100 * np.mean(hi3):+.3f}%（{len(hi3)}）、低波幅 {100 * np.mean(lo3):+.3f}%（{len(lo3)}）；差 {100 * d73:+.3f}%，t {t73:+.2f}", ""]
    # ---- 1508
    dec = {tk: float(per(T[tk].x, 2010, 2015).mean() - per(T[tk].x, 2021, 2026).mean()) for tk in T}; g1 = [dec[k] for k in dec if k in DEEP]; g2 = [dec[k] for k in dec if k not in DEEP]
    L += ["## #1508 理論 A3（探索性，唔作判斷）：越容易套利嘅市場衰減越快", "", "- 各市場跌幅（2010–15 − 2021–26 策略每月淨）：" + "、".join(f"{nm} {100 * dec[tk]:+.2f}%" for nm, tk, _ in PR.MK),
          f"- 期貨成交大嗰組平均跌幅 {100 * np.mean(g1):+.3f}%、另一組 {100 * np.mean(g2):+.3f}%；差 {100 * (np.mean(g1) - np.mean(g2)):+.3f}%（Welch t {DR.welch(np.array(g1), np.array(g2)):+.2f}；7 對 7，只作描述）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
