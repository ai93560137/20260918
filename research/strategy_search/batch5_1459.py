"""[IDEAS #1459–#1461] 回看第五批。規格同門檻以 IDEAS 預先登記為準（11-12 UTC，跑之前 commit）。
用法：python3 research/strategy_search/batch5_1459.py → research/strategy_search/BATCH5_1459.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import direction_1445 as DR   # noqa: E402
import index_1427 as IX       # noqa: E402
import premia_1453 as PM      # noqa: E402
import replicate_1450 as RP   # noqa: E402

OUT = os.path.join(HERE, "BATCH5_1459.md")
MD = os.path.join(HERE, "..", "macro_data")
CCY = [("EUR", "EURUSD=X", 0, "EZ"), ("GBP", "GBPUSD=X", 0, "GB"), ("JPY", "JPY=X", 1, "JP"), ("CHF", "CHF=X", 1, "CH"), ("CAD", "CAD=X", 1, "CA"),
       ("AUD", "AUDUSD=X", 0, "AU"), ("NZD", "NZDUSD=X", 0, "NZ"), ("NOK", "NOK=X", 1, "NO"), ("SEK", "SEK=X", 1, "SE")]
T = PM.tstat


def rate(c):
    d = pd.read_csv(os.path.join(MD, f"fred_IR3TIB01{c}M156N.csv")); s = pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").to_numpy(), index=pd.to_datetime(d.iloc[:, 0])).dropna()
    return s.resample("ME").last()


def carry(n):
    V, D = {}, {}; us = rate("US")
    for c, tk, inv, rc in CCY:
        s = PM.series(tk)
        if s is None:
            continue
        v = (1 / s if inv else s).resample("ME").last(); V[c] = v; D[c] = (rate(rc).reindex(v.index).ffill() - us.reindex(v.index).ffill()).shift(1)
    V, D = pd.DataFrame(V), pd.DataFrame(D); R = V.pct_change(); R = R.where(R.abs() < 0.5); D = D.where(V.notna())
    rk = D.rank(axis=1, ascending=False); cnt = D.notna().sum(axis=1); W = pd.DataFrame(0.0, index=D.index, columns=D.columns)
    W[rk <= n] = 1.0 / n; W[rk.gt(cnt - n, axis=0)] = -1.0 / n; W = W.where(D.notna(), 0.0); W[cnt < 6] = np.nan
    Wl = W.shift(1); x = (Wl * (R + D.shift(1) / 1200)).sum(axis=1) - (Wl - Wl.shift(1)).abs().sum(axis=1) * 0.0003
    spot = (Wl * R).sum(axis=1); return x[Wl.notna().all(axis=1) & R.notna().any(axis=1)].dropna(), spot


def rsi2(c):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=0.5, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=0.5, adjust=False).mean()
    return (100 * up / (up + dn).replace(0, np.nan)).to_numpy()


def dip(t, c, th=10.0, cost=0.0004, H=5):
    """回傳 DataFrame(入場時間, 淨回報, 超額)。"""
    c = np.asarray(c, float); n = len(c); md = pd.Series(c).rolling(200).mean().to_numpy(); r = rsi2(c); f = np.full(n, np.nan); f[:-H] = c[H:] / c[:-H] - 1
    ok = ~np.isnan(md) & (c > md) & ~np.isnan(f) & (np.abs(f) < 0.5); bench = f[ok].mean(); out = []; i = 200
    while i < n - H:
        if ok[i] and r[i] < th:
            out.append((t[i], f[i] - cost, f[i] - cost - bench)); i += H
        else:
            i += 1
    d = pd.DataFrame(out, columns=["t", "r", "x"]); d["t"] = pd.to_datetime(d.t.astype("int64"), unit="s"); return d


def clus(d):
    return d.groupby(d.t.dt.to_period("M")).x.mean()


def main():
    L = ["# #1459–#1461：回看第五批", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只讀研究", ""]; res = {}
    # ---- 1459
    L += ["## #1459 外匯息差（9 種貨幣對美元；高息 3 隻多、低息 3 隻空）", "", "| 版本 | 由 | 月數 | 月均 | t | 前半 | 後半（由） | 2010 起 | Sharpe | 最大回落 | 其中匯價部分月均 |", "|---|---|---|---|---|---|---|---|---|---|---|"]; D = {}
    for n in (3, 2, 4):
        x, spot = carry(n); d = PM.desc(x); D[n] = d; y = x[x.index.year >= 2010]; d["y"] = float(y.mean())
        L.append(f"| {n} 多 {n} 空 | {d['y0']} | {d['n']} | {100 * x.mean():+.3f}% | {d['t']:+.2f} | {100 * d['a']:+.3f}% | {100 * d['b']:+.3f}%（{d['mid']}） | {100 * d['y']:+.3f}%（t {T(y):+.2f}） | {d['sh']:.2f} | {100 * d['dd']:.0f}% | {100 * spot.reindex(x.index).mean():+.3f}% |")
    g = [D[3]["ann"] > 0 and D[3]["t"] >= 2.0, D[3]["a"] > 0 and D[3]["b"] > 0, D[3]["y"] > 0, D[2]["ann"] > 0 and D[4]["ann"] > 0]; res["1459"] = all(g)
    L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1459'] else '❌ 唔合格'}**", ""]
    # ---- 1460
    idx = [(n, tk) for c, n, tk, _ in DR.MK if c == "股指"] + list(RP.IDX); S = {}
    for n, tk in idx:
        t, c = DR.load(tk)
        if t is not None and len(c) >= 1500:
            S[n] = (np.asarray(t, "int64"), np.asarray(c, float))
    L += ["## #1460 股指升市入面嘅急跌回彈（收市 > SMA200 而且 RSI(2) < 10 → 收市買、揸 5 日）", "", "| 門檻 | 張 | 每張淨回報 | 超額 | t（按月聚類） | 前半超額 | 後半超額 | 2010 起超額（t） | 單獨為正 |", "|---|---|---|---|---|---|---|---|---|"]; G = {}
    for th in (10, 5, 15):
        A = {n: dip(t, c, th) for n, (t, c) in S.items()}; al = pd.concat(A.values()); m = clus(al); h = len(m) // 2; y = m[m.index.year >= 2010]; pos = np.mean([a.x.mean() > 0 for a in A.values() if len(a)])
        G[th] = dict(x=float(al.x.mean()), t=T(m), a=float(m.iloc[:h].mean()), b=float(m.iloc[h:].mean()), y=float(y.mean()), pos=float(pos))
        L.append(f"| RSI(2) < {th} | {len(al):,} | {1e4 * al.r.mean():+.1f}bp | {1e4 * al.x.mean():+.1f}bp | {T(m):+.2f} | {1e4 * m.iloc[:h].mean():+.1f}bp | {1e4 * m.iloc[h:].mean():+.1f}bp | {1e4 * y.mean():+.1f}bp（{T(y):+.2f}） | {100 * pos:.0f}% |")
    L += ["", "| 可交易數據 | 由 | 張 | 每張淨回報 | 超額 | 2010 起每張淨／超額 | 勝率 |", "|---|---|---|---|---|---|---|"]; fut = []
    for nm, key in (("ES 期貨", "ES_F"), ("NQ 期貨", "NQ_F"), ("恒指", "HSI")):
        d = IX.load(key); a = dip(np.asarray(d["t"], "int64"), d["c"]); y = a[a.t.dt.year >= 2010]; fut.append((a.r.mean(), a.x.mean()))
        L.append(f"| {nm} | {a.t.iloc[0].year} | {len(a)} | {1e4 * a.r.mean():+.1f}bp | {1e4 * a.x.mean():+.1f}bp | {1e4 * y.r.mean():+.1f}／{1e4 * y.x.mean():+.1f}bp | {100 * (a.r > 0).mean():.0f}% |")
    q = G[10]; g = [q["x"] > 0 and q["t"] >= 2.0, q["a"] > 0 and q["b"] > 0, q["y"] > 0, q["pos"] >= 0.7, G[5]["x"] > 0 and G[15]["x"] > 0, all(r > 0 for r, _ in fut) and sum(x > 0 for _, x in fut) >= 2]; res["1460"] = all(g)
    L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1460'] else '❌ 唔合格'}**", ""]
    # ---- 1461
    sp, vx = PM.series("^GSPC"), PM.series("^VIX"); r = sp.pct_change().dropna(); r = r[r.index >= "1990-01-01"]
    rv = (r ** 2).resample("ME").sum(); iv = ((vx / 100) ** 2 / 12).resample("ME").last(); vrp = (iv - rv).dropna(); med = vrp.expanding(36).median().shift(1); hi = (vrp > med)[med.notna()]

    def nxt(s):
        m = s.resample("ME").last().pct_change(); return m.shift(-1)

    def dd(nx, a=None, b=None):
        z = pd.DataFrame({"h": hi, "r": nx}).dropna(); z = z if a is None else z.iloc[a:b]; u, v = z.r[z.h.astype(bool)], z.r[~z.h.astype(bool)]
        return float(u.mean() - v.mean()), DR.welch(u.to_numpy(), v.to_numpy()), len(u), len(v), z
    es = IX.load("ES_F"); es = pd.Series(np.asarray(es["c"], float), index=pd.to_datetime(np.asarray(es["t"], "int64"), unit="s"))
    L += ["## #1461 波幅風險溢價擇時（溢價 > 歷史中位數 → 下個月揸）", "", "| 對象 | 由 | 高溢價月／低溢價月 | 高之後月均 | 低之後月均 | 差 | t |", "|---|---|---|---|---|---|---|"]; O = {}
    for nm, s in (("標普 500（判決）", sp), ("ES 期貨", es), ("納指 100", PM.series("^NDX"))):
        d0, t0, nu, nv, z = dd(nxt(s)); O[nm] = (d0, t0, z); u, v = z.r[z.h.astype(bool)], z.r[~z.h.astype(bool)]
        L.append(f"| {nm} | {z.index[0].year} | {nu}／{nv} | {100 * u.mean():+.2f}% | {100 * v.mean():+.2f}% | {100 * d0:+.2f}% | {t0:+.2f} |")
    d0, t0, z = O["標普 500（判決）"]; h = len(z) // 2; d1 = dd(nxt(sp), 0, h)[0]; d2 = dd(nxt(sp), h, None)[0]; zy = z[z.index.year >= 2010]; d3 = zy.r[zy.h.astype(bool)].mean() - zy.r[~zy.h.astype(bool)].mean()
    w = z.h.astype(float); tim = w * z.r - w.diff().abs().fillna(0) * 0.0002; sh = lambda x: float(x.mean() / x.std() * np.sqrt(12))  # noqa: E731
    g = [d0 > 0 and t0 >= 2.0, d1 > 0 and d2 > 0, d3 > 0, O["ES 期貨"][0] > 0 and O["納指 100"][0] > 0, sh(tim) >= sh(z.r)]; res["1461"] = all(g)
    L += ["", f"- 標普：前半差 {100 * d1:+.2f}%、後半（{z.index[h]:%Y} 起）{100 * d2:+.2f}%；2010 起 {100 * d3:+.2f}%；擇時 Sharpe {sh(tim):.2f} 對長揸 {sh(z.r):.2f}；最大回落 {100 * DR.mdd(np.cumprod(1 + tim.to_numpy())):.0f}% 對 {100 * DR.mdd(np.cumprod(1 + z.r.to_numpy())):.0f}%；在場 {100 * w.mean():.0f}%",
          f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1461'] else '❌ 唔合格'}**", "",
          f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
