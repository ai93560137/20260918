"""[IDEAS #1456–#1458] 回看第四批。規格同門檻以 IDEAS 預先登記為準（11-12 UTC，跑之前 commit）。
用法：python3 research/strategy_search/batch4_1456.py → research/strategy_search/BATCH4_1456.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import direction_1445 as DR   # noqa: E402
import premia_1453 as PM      # noqa: E402
import replicate_1450 as RP   # noqa: E402

OUT = os.path.join(HERE, "BATCH4_1456.md")
ETF = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "IWM", "VNQ", "EEM", "HYG"]
FX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY"]


def tom(s):
    """回傳 DataFrame(r, w)：w＝月尾最後 1 個交易日或者月頭 3 個交易日。"""
    r = s.pct_change().dropna(); ym = r.index.to_period("M"); g = pd.Series(np.arange(len(r)), index=r.index).groupby(ym)
    first = g.cumcount(); last = g.cumcount(ascending=False)
    return pd.DataFrame({"r": r, "w": ((first < 3) | (last == 0)).to_numpy()})


def alpha(y, x):
    X = np.c_[np.ones(len(x)), x]; b, *_ = np.linalg.lstsq(X, y, rcond=None); e = y - X @ b
    return float(b[0]), float(b[0] / np.sqrt(e.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0]))


def mgd(s, k):
    r = s.pct_change().dropna(); mr = (1 + r).resample("ME").prod() - 1; rv = (r ** 2).resample("ME").sum().rolling(k).mean().shift(1)
    d = pd.DataFrame({"f": mr, "v": rv}).dropna(); d = d[d.v > 0]; g = d.f / d.v; return d.f, g * d.f.std() / g.std()


def main():
    L = ["# #1456–#1458：回看第四批", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只讀研究", ""]; res = {}
    # ---- 1456
    idx = [(n, tk) for c, n, tk, _ in DR.MK if c == "股指"] + list(RP.IDX); D = {}; per = []
    L += ["## #1456 月頭月尾效應（最後 1 日＋頭 3 日）", "", "| 指數 | 由 | 窗口日均 | 其餘日均 | 差 |", "|---|---|---|---|---|"]
    for n, tk in idx:
        s = PM.series(tk)
        if s is None:
            continue
        d = tom(s); D[n] = d; df = d.r[d.w].mean() - d.r[~d.w].mean(); per.append(df)
        L.append(f"| {n} | {d.index[0].year} | {1e4 * d.r[d.w].mean():+.1f}bp | {1e4 * d.r[~d.w].mean():+.1f}bp | {1e4 * df:+.1f}bp |")
    R = pd.DataFrame({n: d.r for n, d in D.items()}); W = pd.DataFrame({n: d.w for n, d in D.items()})
    a = R.where(W == True).mean(axis=1).dropna(); b = R.where(W == False).mean(axis=1).dropna()  # noqa: E712
    def dd(a, b):
        return a.mean() - b.mean(), DR.welch(a.to_numpy(), b.to_numpy())
    d0, t0 = dd(a, b); mid = R.index[len(R) // 2]; d1 = dd(a[a.index < mid], b[b.index < mid])[0]; d2, t2 = dd(a[a.index >= mid], b[b.index >= mid]); d3, t3 = dd(a[a.index.year >= 2010], b[b.index.year >= 2010])
    pos = float((np.array(per) > 0).mean()); g = [d0 > 0 and t0 >= 2.0, d1 > 0 and d2 > 0, d3 > 0, pos >= 0.7]; res["1456"] = all(g)
    L += ["", f"- 合併（每日先取跨指數平均）：窗口 {1e4 * a.mean():+.1f}bp（{len(a):,} 日）對其餘 {1e4 * b.mean():+.1f}bp（{len(b):,} 日），差 {1e4 * d0:+.1f}bp，t {t0:+.2f}",
          f"- 前半差 {1e4 * d1:+.1f}bp；後半（{mid:%Y} 起）差 {1e4 * d2:+.1f}bp（t {t2:+.2f}）；2010 起差 {1e4 * d3:+.1f}bp（t {t3:+.2f}）；單獨為正 {int((np.array(per) > 0).sum())}／{len(per)}",
          f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1456'] else '❌ 唔合格'}**", ""]
    # ---- 1457
    L += ["## #1457 波幅調注喺 13 隻未睇過嘅美國 ETF 重現", "", "| ETF | 由 | 月數 | 截距（月） | t |", "|---|---|---|---|---|"]; F, G, G3, al = {}, {}, {}, []
    for tk in ETF:
        s = PM.series(tk)
        if s is None:
            L.append(f"| {tk} | 冇數據 | | | |"); continue
        f, g_ = mgd(s, 1); F[tk], G[tk] = f, g_; G3[tk] = mgd(s, 3)[1]; a_, t_ = alpha(g_.to_numpy(), f.to_numpy()); al.append(a_)
        L.append(f"| {tk} | {f.index[0].year} | {len(f)} | {100 * a_:+.3f}% | {t_:+.2f} |")
    F, G, G3 = pd.DataFrame(F), pd.DataFrame(G), pd.DataFrame(G3); ok = F.notna().sum(axis=1) >= 6; f, g_ = F.mean(axis=1)[ok], G.mean(axis=1)[ok]; g3 = G3.mean(axis=1).reindex(f.index)
    a0, t0 = alpha(g_.to_numpy(), f.to_numpy()); h = len(f) // 2; a1 = alpha(g_.to_numpy()[:h], f.to_numpy()[:h])[0]; a2 = alpha(g_.to_numpy()[h:], f.to_numpy()[h:])[0]
    m3 = g3.notna(); a3 = alpha(g3[m3].to_numpy(), f[m3].to_numpy())[0]; pos = float((np.array(al) > 0).mean()); g = [a0 > 0 and t0 >= 2.0, a1 > 0 and a2 > 0, a3 > 0, pos >= 0.7]; res["1457"] = all(g)
    sh = lambda x: float(x.mean() / x.std() * np.sqrt(12))  # noqa: E731
    L += ["", f"- 等權組合（{f.index[0]:%Y-%m} 起 {len(f)} 個月）：截距 {100 * a0:+.3f}%／月，t {t0:+.2f}；前半 {100 * a1:+.3f}%、後半（{f.index[h]:%Y} 起）{100 * a2:+.3f}%；3 個月方差版 {100 * a3:+.3f}%；單獨為正 {int((np.array(al) > 0).sum())}／{len(al)}",
          f"- Sharpe：調注 {sh(g_):.2f} 對長揸 {sh(f):.2f}；最大回落：調注 {100 * DR.mdd(np.cumprod(1 + g_.to_numpy())):.0f}% 對長揸 {100 * DR.mdd(np.cumprod(1 + f.to_numpy())):.0f}%（調注版已調到同各自長揸一樣波幅）",
          f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1457'] else '❌ 唔合格'}**", ""]
    # ---- 1458
    P, V = {}, {}
    for n in FX:
        s = PM.series(n + "=X")
        if s is None:
            continue
        r = s.pct_change(); P[n] = s.resample("ME").last(); V[n] = (r.rolling(60).std() * np.sqrt(252)).resample("ME").last()
    P, V = pd.DataFrame(P), pd.DataFrame(V); R = P.pct_change(); R = R.where(R.abs() < 1.0)
    L += [f"## #1458 #1453 喺外匯重現（{P.shape[1]} 對）", "", "| 回望 | 由 | 月數 | 月均 | t | 前半 | 後半（由） | Sharpe | 最大回落 |", "|---|---|---|---|---|---|---|---|---|"]; Dd = {}
    for k in (12, 9, 15):
        x, _ = PM.port(PM.tsmom(P, V, k), R); d = PM.desc(x); Dd[k] = d
        L.append(f"| {k} 個月 | {d['y0']} | {d['n']} | {100 * x.mean():+.3f}% | {d['t']:+.2f} | {100 * d['a']:+.3f}% | {100 * d['b']:+.3f}%（{d['mid']}） | {d['sh']:.2f} | {100 * d['dd']:.0f}% |")
    g = [Dd[12]["t"] >= 2.0 and Dd[12]["ann"] > 0, Dd[12]["a"] > 0 and Dd[12]["b"] > 0, Dd[9]["ann"] > 0 and Dd[15]["ann"] > 0]; res["1458"] = all(g)
    L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1458'] else '❌ 唔合格'}**", "",
          f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
