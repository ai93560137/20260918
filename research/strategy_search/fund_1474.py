"""[IDEAS #1474–#1476] 基金層面第六批：股指短期回調買入、期權結算週。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1474.py → research/strategy_search/FUND_1474.md（要先跑過 fund_1464.py）"""
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
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1474.md")
COST = 0.0004
SPLIT = pd.Period(f"{F.SPLIT}-01", "M")


def px(tk):
    c = B6.ohlc(tk).c; c = c[(c > 0) & (c.index.dayofweek < 5)]; return c[c.index >= "2009-06-01"]


def rsi2(c):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def dip(c, swap):
    """收市 > SMA200 且 RSI2 < 10 → 收市買；收市 > SMA5 或滿 10 個交易日 → 收市平。回傳每次淨回報（index＝出場日）。"""
    s200, s5, r = c.rolling(200).mean(), c.rolling(5).mean(), rsi2(c); v = c.to_numpy(); out = []; i = 200; n = len(c)
    while i < n - 1:
        if v[i] > s200.iloc[i] and r.iloc[i] < 10:
            j = i + 1
            while j < n - 1 and j - i < 10 and not v[j] > s5.iloc[j]:
                j += 1
            nights = (c.index[j] - c.index[i]).days
            out.append((c.index[j], v[j] / v[i] - 1 - COST - swap * nights / 365)); i = j
        else:
            i += 1
    x = pd.Series(dict(out)); return x[x.index >= "2010-07-01"]


def opex(c, swap):
    """第三個星期五嗰週：前一個星期五收市 → 第三個星期五收市。回傳（結算週淨回報，其餘星期毛回報）。"""
    w = c.resample("W-FRI").last().dropna(); r = w.pct_change().dropna(); third = pd.Series([8 + (4 - dt.date(d.year, d.month, 1).weekday()) % 7 + 7 == d.day for d in r.index], index=r.index)
    r = r[r.index >= "2010-07-01"]; third = third.reindex(r.index); return r[third] - COST - swap * 7 / 365, r[~third]


def mon(x, idx):
    return x.groupby(x.index.to_period("M")).sum().reindex(idx).fillna(0.0)


def hmean(x):
    a, b = x[x.index < f"{F.SPLIT}-01-01"], x[x.index >= f"{F.SPLIT}-01-01"]; return float(a.mean()), float(b.mean())


def main():
    m0, idx, target = G.base(); res = {}
    zn = B6.ohlc("ZN=F").c; z = B6.rebal(px("^GSPC"), zn[zn > 0]); me = pd.Series(np.where(z.rel < 0, 1.0, -1.0) * z.r.to_numpy() - COST, index=z.index).reindex(idx).fillna(0.0)
    L = ["# #1474–#1476：基金層面第六批（股指短期回調、期權結算週）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；現貨指數日線＋券商成本同隔夜息；樣本內；只讀研究", ""]

    def run(tag, title, x, solo, txt):
        m = mon(x, idx); cm = float(np.corrcoef(m, me)[0, 1]); ok = F3.judge(L, title, m, m0, target, solo, txt, SPLIT) and cm <= 0.5
        L[-2:-2] = [f"- 同月尾再平衡腳（現貨標普版）每月相關 {cm:+.2f}（> 0.5 判唔合格）→ {'✓' if cm <= 0.5 else '✗'}；最終 **{'✅' if ok else '❌'}**"]; res[tag] = ok

    def txt(x):
        a, b = hmean(x); return f"{len(x)} 次，每次淨 {100 * x.mean():+.3f}%（t {PM.tstat(x):+.2f}）、勝率 {100 * (x > 0).mean():.0f}%、最差 {100 * x.min():+.1f}%；前半／後半 {100 * a:+.3f}%／{100 * b:+.3f}%"

    x = dip(px("^GSPC"), 0.078); a, b = hmean(x)
    run("1474", "#1474 標普短期回調買入（SMA200 上、RSI2 < 10）", x, x.mean() > 0 and PM.tstat(x) >= 2.0 and a > 0 and b > 0, txt(x))
    by = x.groupby(x.index.year).sum(); L += ["- 按年淨回報合計（%）：" + "；".join(f"{y} {100 * v:+.1f}" for y, v in by.items()), ""]
    xs = {"GER40": dip(px("^GDAXI"), 0.056), "UK100": dip(px("^FTSE"), 0.075)}; pool = pd.concat(xs.values()).sort_index(); a, b = hmean(pool)
    mm = sum(mon(v, idx) for v in xs.values()) / 2
    m = mm; cm = float(np.corrcoef(m, me)[0, 1]); solo = pool.mean() > 0 and PM.tstat(pool) >= 2.0 and all(v.mean() > 0 for v in xs.values()) and a > 0 and b > 0
    ok = F3.judge(L, "#1475 歐洲股指短期回調買入（GER40＋UK100）", m, m0, target, solo, txt(pool) + "；" + "、".join(f"{k} {100 * v.mean():+.3f}%（{len(v)} 次）" for k, v in xs.items()), SPLIT) and cm <= 0.5
    L[-2:-2] = [f"- 同月尾再平衡腳每月相關 {cm:+.2f} → {'✓' if cm <= 0.5 else '✗'}；最終 **{'✅' if ok else '❌'}**"]; res["1475"] = ok
    g, o = opex(px("^GSPC"), 0.078); a, b = hmean(g); dif = float(g.mean() + COST + 0.078 * 7 / 365 - o.mean()); td = DR.welch((g + COST + 0.078 * 7 / 365).to_numpy(), o.to_numpy())
    run("1476", "#1476 期權結算週做多標普", g, g.mean() > 0 and PM.tstat(g) >= 2.0 and dif > 0 and td >= 2.0 and a > 0 and b > 0, txt(g) + f"；其餘 {len(o)} 個星期毛 {100 * o.mean():+.3f}%，差 {100 * dif:+.3f}%（t {td:+.2f}）")
    L += [f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
