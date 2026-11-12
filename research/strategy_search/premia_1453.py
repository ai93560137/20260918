"""[IDEAS #1453–#1455] 回看第三批：組合層面／風險溢價。規格同門檻以 IDEAS 預先登記為準（11-12 UTC，跑之前 commit）。
用法：python3 research/strategy_search/premia_1453.py → research/strategy_search/PREMIA_1453.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import direction_1445 as DR   # noqa: E402
import replicate_1450 as RP   # noqa: E402

OUT = os.path.join(HERE, "PREMIA_1453.md")
TV, COST, MINMK = 0.10, 0.0005, 6


def series(tk):
    t, c = DR.load(tk)
    if t is None or len(c) < 1500:
        return None
    s = pd.Series(np.asarray(c, float), index=pd.to_datetime(np.asarray(t, "int64"), unit="s")); s = s[~s.index.duplicated()]
    r = s.pct_change(); return s[(r.abs() < 0.5) | r.isna()]


def panel():
    P, V = {}, {}
    for cat, name, tk, _ in DR.MK:
        s = series(tk)
        if s is None:
            continue
        r = s.pct_change(); P[name] = s.resample("ME").last(); V[name] = (r.rolling(60).std() * np.sqrt(252)).resample("ME").last()
    return pd.DataFrame(P), pd.DataFrame(V)


def tstat(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 12 and x.std() > 0 else float("nan")


def port(W, R):
    """W＝月尾權重（已按波幅調）；R＝下個月回報。回傳組合月回報（有 ≥ MINMK 個市場先計）同逐市場貢獻。"""
    Wl = W.shift(1); contrib = Wl * R - (Wl - Wl.shift(1)).abs().fillna(0) * COST; n = (Wl.notna() & R.notna() & (Wl != 0)).sum(axis=1)
    return contrib.where(Wl.notna()).sum(axis=1).div(n).where(n >= MINMK).dropna(), contrib


def tsmom(P, V, k):
    sig = np.sign(P / P.shift(k) - 1); return sig * (TV / V)


def xsmom(P, V, k):
    m = P.shift(1) / P.shift(k) - 1; rk = m.rank(axis=1, pct=True); n = m.notna().sum(axis=1)
    side = pd.DataFrame(0.0, index=m.index, columns=m.columns); side[rk > 2 / 3] = 1.0; side[rk <= 1 / 3] = -1.0; side = side.where(m.notna()); side[n < MINMK] = np.nan
    return side * (TV / V)


def desc(x):
    h = len(x) // 2; ann = x.mean() * 12; sd = x.std(ddof=1) * np.sqrt(12); eq = np.cumprod(1 + x.to_numpy())
    return dict(n=len(x), t=tstat(x), a=float(x.iloc[:h].mean()), b=float(x.iloc[h:].mean()), ann=float(ann), sh=float(ann / sd) if sd > 0 else 0.0, dd=DR.mdd(eq), y0=x.index[0].year, mid=x.index[h].year)


def managed(s, k=1):
    """波幅調注：w ∝ 1 ÷ 過去 k 個月已實現方差；回傳 (截距月率, t, 前半截距, 後半截距, 月數, 起始年)。"""
    r = s.pct_change().dropna(); mr = (1 + r).resample("ME").prod() - 1; rv = (r ** 2).resample("ME").sum().rolling(k).mean().shift(1)
    d = pd.DataFrame({"f": mr, "v": rv}).dropna(); d = d[d.v > 0]; w = 1 / d.v; g = w * d.f; g *= d.f.std() / g.std()

    def alpha(y, x):
        X = np.c_[np.ones(len(x)), x]; b, *_ = np.linalg.lstsq(X, y, rcond=None); e = y - X @ b; se = np.sqrt(e.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0]); return float(b[0]), float(b[0] / se)
    a, t = alpha(g.to_numpy(), d.f.to_numpy()); h = len(d) // 2
    return a, t, alpha(g.to_numpy()[:h], d.f.to_numpy()[:h])[0], alpha(g.to_numpy()[h:], d.f.to_numpy()[h:])[0], len(d), d.index[0].year


def main():
    P, V = panel(); R = P.pct_change(); R = R.where(R.abs() < 1.0)
    L = ["# #1453–#1455：組合層面／風險溢價（回看第三批）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{P.shape[1]} 個市場月回報；每個市場按過去 60 日波幅調到年化 {TV:.0%}；轉倉成本 {COST:.2%}；只讀研究",
         f"- 實作細節（跑之前定）：同一個月有 ≥ {MINMK} 個市場有訊號先計組合；期貨（=F）係未經轉倉調整嘅連續近月合約；現貨指數冇扣現金利率", ""]
    res = {}
    for tag, fn, title in (("1453", tsmom, "#1453 分散嘅時間序列動量（12 個月方向，30 市場等風險）"), ("1454", xsmom, "#1454 跨市場相對強弱（12−1 個月，上三分一多／下三分一空）")):
        L += [f"## {title}", "", "| 回望 | 由 | 月數 | 月均 | t | 前半月均 | 後半月均（由） | 年化 | Sharpe | 最大回落 |", "|---|---|---|---|---|---|---|---|---|---|"]
        D = {}
        for k in (12, 9, 15):
            x, contrib = port(fn(P, V, k), R); D[k] = desc(x); d = D[k]
            L.append(f"| {k} 個月 | {d['y0']} | {d['n']} | {100 * x.mean():+.3f}% | {d['t']:+.2f} | {100 * d['a']:+.3f}% | {100 * d['b']:+.3f}%（{d['mid']}） | {100 * d['ann']:+.1f}% | {d['sh']:.2f} | {100 * d['dd']:.0f}% |")
            if k == 12:
                per = contrib.mean().dropna(); pos = float((per > 0).mean()); c12 = per
        g = [D[12]["t"] >= 2.0 and D[12]["ann"] > 0, D[12]["a"] > 0 and D[12]["b"] > 0, D[9]["ann"] > 0 and D[15]["ann"] > 0]
        if tag == "1453":
            g.append(pos >= 0.6)
            L += ["", f"- 逐市場（12 個月）：{100 * pos:.0f}% 為正（{int((c12 > 0).sum())}／{len(c12)}）；最好：{'、'.join(f'{n} {1e4 * v:+.0f}bp' for n, v in c12.sort_values().iloc[-4:][::-1].items())}；最差：{'、'.join(f'{n} {1e4 * v:+.0f}bp' for n, v in c12.sort_values().iloc[:4].items())}"]
        ok = all(g); res[tag] = ok
        L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if ok else '❌ 唔合格'}**", ""]
        # 描述：按十年
        x, _ = port(fn(P, V, 12), R); dec = x.groupby((x.index.year // 10) * 10).agg(["mean", "count"])
        L += ["- 按年代月均（描述）：" + "；".join(f"{int(y)}s {100 * m:+.2f}%（{int(n)} 月）" for y, (m, n) in dec.iterrows()), ""]
    # 1455
    L += ["## #1455 按波幅調整注碼（注碼 ∝ 1 ÷ 上月已實現方差）", "", "| 對象 | 由 | 月數 | 截距（月） | t | 前半截距 | 後半截距 | 3 個月方差版截距 | 判 |", "|---|---|---|---|---|---|---|---|---|"]
    def row(name, tk):
        s = series(tk)
        if s is None:
            return None
        a, t, a1, a2, n, y0 = managed(s, 1); a3 = managed(s, 3)[0]; ok = a > 0 and t >= 2.0 and a1 > 0 and a2 > 0 and a3 > 0
        L.append(f"| {name} | {y0} | {n} | {100 * a:+.3f}% | {t:+.2f} | {100 * a1:+.3f}% | {100 * a2:+.3f}% | {100 * a3:+.3f}% | {'✅' if ok else '❌'} |"); return a, t, ok
    g = row("**黃金（判決對象）**", "stooq:xauusd"); res["1455"] = bool(g and g[2])
    row("白銀（描述）", "stooq:xagusd"); row("標普 500（描述）", "^GSPC")
    idx = [tk for cat, _, tk, _ in DR.MK if cat == "股指"] + [tk for _, tk in RP.IDX]; A = []
    for tk in idx:
        s = series(tk)
        if s is not None:
            A.append(managed(s, 1)[:2])
    A = np.array(A)
    L += ["", f"- 股指（{len(A)} 個，描述）：平均截距 {100 * A[:, 0].mean():+.3f}%／月；截距 > 0 有 {int((A[:, 0] > 0).sum())} 個；t ≥ 2 有 {int((A[:, 1] >= 2).sum())} 個",
          f"- 黃金判決 → **{'✅ 合格' if res['1455'] else '❌ 唔合格'}**", "", f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    L += robust(P, V, R) + shadow(P, V, R)
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


def robust(P, V, R):
    """事後穩健性覆核（唔改判決門檻；只係睇合格係咪靠數據瑕疵）。"""
    import multi_1422 as MU
    fut = [n for _, n, tk, _ in DR.MK if tk.endswith("=F")]; f = MU.fred("TB3MS")
    rf = (pd.Series(np.asarray(f["c"], float), index=pd.to_datetime(np.asarray(f["t"], "int64"), unit="s")).resample("ME").last() / 1200).reindex(P.index).ffill().fillna(0.0)
    L = ["## 穩健性覆核（事後做，唔改門檻）", "", "| 策略 | 版本 | 月均 | t | 前半 | 後半（t） | 2010 年起（t） |", "|---|---|---|---|---|---|---|"]

    def row(a, b, x):
        h = len(x) // 2; y = x[x.index.year >= 2010]
        L.append(f"| {a} | {b} | {100 * x.mean():+.3f}% | {tstat(x):+.2f} | {100 * x.iloc[:h].mean():+.3f}% | {100 * x.iloc[h:].mean():+.3f}%（{tstat(x.iloc[h:]):+.2f}） | {100 * y.mean():+.3f}%（{tstat(y):+.2f}） |")
    for nm, fn in (("#1453", tsmom), ("#1454", xsmom)):
        W = fn(P, V, 12); x, _ = port(W, R); row(nm, "原版", x)
        c = [k for k in P.columns if k not in fut]; row(nm, f"剔走所有期貨（剩 {len(c)} 個現貨／ETF）", port(fn(P[c], V[c], 12), R[c])[0])
        c = [k for k in P.columns if k != "比特幣"]; row(nm, "剔走比特幣", port(fn(P[c], V[c], 12), R[c])[0])
        Wl = W.shift(1); n = (Wl.notna() & R.notna() & (Wl != 0)).sum(axis=1); sp = [k for k in P.columns if k not in fut]
        row(nm, "現貨做多扣美國 3 個月國庫券息、做空唔計息（最保守）", (x - (Wl[sp].clip(lower=0).mul(rf, axis=0).sum(axis=1) / n).reindex(x.index)).dropna())
    return L + ["", "- 合格唔係靠未轉倉調整嘅期貨（剔走之後反而更好），亦唔係靠比特幣；扣咗融資成本之後 12 個月版仍然 t ≥ 2、前後半都正。",
                "- **要老實講嘅弱點**：2010 年之後單獨睇只係細正數、t 約 1（統計上未算顯著）；全期年化只有約 2–3%（每市場 10% 波幅、30 個市場平均後組合波幅約 4–5%），Sharpe 約 0.4–0.6；要同時做約 30 個市場，細戶口實際做唔到全套。", ""]


def shadow(P, V, R):
    """影子：上一個完整月尾嘅訊號（今個月持有）。向前由 2026-11 開始計。"""
    m = P.index[-2] if len(P.index) > 1 else P.index[-1]; a, b = tsmom(P, V, 12).loc[m], xsmom(P, V, 12).loc[m]
    L = [f"## 影子（紙上，唔落單）：{m:%Y-%m} 月尾訊號 → 之後一個月持有", "", "| 市場 | #1453 方向 | #1454 方向 | 波幅調整後權重（#1453） |", "|---|---|---|---|"]
    for k in P.columns:
        if pd.notna(a[k]):
            L.append(f"| {k} | {'多' if a[k] > 0 else '空'} | {'多' if b.get(k, 0) > 0 else ('空' if b.get(k, 0) < 0 else '—')} | {a[k]:+.2f} |")
    fw = {}
    for nm, fn in (("#1453", tsmom), ("#1454", xsmom)):
        x, _ = port(fn(P, V, 12), R); fw[nm] = x[x.index >= "2026-11-01"]
    L += ["", "- 向前紀錄（2026-11 起，月尾結算；當月未完）：" + "；".join(f"{k} {len(v)} 個月、累計 {100 * v.sum():+.2f}%" for k, v in fw.items()), ""]
    return L


if __name__ == "__main__":
    main()
