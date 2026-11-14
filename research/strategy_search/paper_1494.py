"""[IDEAS #1494–#1499] 論文實證第三批：月頭回吐（#1494–#1497）、月中安慰劑（#1498）、訊號拆解（#1499）。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/paper_1494.py → research/strategy_search/PAPER_1494.md（要先跑過 fund_1464.py）"""
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
import paper_robust as PR    # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "PAPER_1494.md")
COST = 0.0004
REV = [("1494", "美國", [("^GSPC", False)]), ("1495", "歐洲", [("^GDAXI", False), ("^FTSE", False)]), ("1496", "亞洲", [("^N225", True), ("^AXJO", True)]), ("1497", "加拿大", [("^GSPTSE", False)])]
W0, W1 = pd.Period("2010-07", "M"), pd.Period("2026-10", "M")


def months(tk, zn, lag):
    """每個月一行：月尾訊號（rel、指數當月、美債當月）、最後 5 日回報、月頭回吐回報、月中安慰劑（rel11、之後 5 日回報）。"""
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; b = (zn.shift(1) if lag else zn).reindex(s.index, method="ffill")
    z = pd.DataFrame({"s": s, "b": b}).dropna(); gs = [(p, g) for p, g in z.groupby(z.index.to_period("M"))]; out = []
    for i in range(1, len(gs) - 1):
        p, g = gs[i]; p0 = gs[i - 1][1].iloc[-1]; g2 = gs[i + 1][1]
        if len(g) < 12 or len(g2) < 3 or not (W0 <= p <= W1):
            continue
        a, e = g.iloc[-6], g.iloc[-1]; im, bm = a.s / p0.s - 1, a.b / p0.b - 1; row = {"m": p, "rel": im - bm, "im": im, "bm": bm, "r": e.s / a.s - 1, "rev": g2.iloc[2].s / e.s - 1, "rel11": np.nan, "r11": np.nan}
        if len(g) >= 20:
            c = g.iloc[10]; row["rel11"] = (c.s / p0.s - 1) - (c.b / p0.b - 1); row["r11"] = g.iloc[15].s / c.s - 1
        out.append(row)
    return pd.DataFrame(out).set_index("m")


def diff(r, cond):
    lo, hi = r[cond].to_numpy(), r[~cond].to_numpy(); return 100 * (lo.mean() - hi.mean()), DR.welch(lo, hi)


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; m0, idx, target = G.base(); S = pd.Period(f"{F.SPLIT}-01", "M"); M = {tk: months(tk, zn, lag) for _, tk, lag in PR.MK}
    L = ["# #1494–#1499：論文實證第三批（月頭回吐、月中安慰劑、訊號拆解）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；2010-07–2026-10；來回成本 {100 * COST:.2f}%；只讀研究", ""]
    # ---- 月頭回吐
    legs = {}; res = {}
    for tag, nm, idxs in REV:
        X = {}
        for tk, _ in idxs:
            z = M[tk]; x = pd.Series(-np.where(z.rel < 0, 1.0, -1.0) * z.rev.to_numpy() - COST, index=z.index + 1); X[tk] = x      # 入賬喺出場月
        D = pd.DataFrame(X); st = D.mean(axis=1); a, b = st[st.index < S], st[st.index >= S]
        solo = st.mean() > 0 and PM.tstat(st) >= 2.0 and all(D[c].mean() > 0 for c in D) and a.mean() > 0 and b.mean() > 0
        legs[nm] = st.reindex(idx).fillna(0.0)
        res[tag] = F3.judge(L, f"#{tag} 月頭回吐：{nm}", legs[nm], m0, target, solo,
                            f"{len(st)} 個月；策略每月淨 {100 * st.mean():+.3f}%（t {PM.tstat(st):+.2f}）；" + "、".join(f"{c} {100 * D[c].mean():+.3f}%" for c in D) + f"；前半／後半 {100 * a.mean():+.3f}%／{100 * b.mean():+.3f}%", S)
    C = pd.DataFrame(legs).corr(); L += ["- 四條之間每月相關：" + "、".join(f"{a}–{b} {C.loc[a, b]:+.2f}" for i, a in enumerate(C) for b in list(C)[i + 1:]), f"- 小結：月頭回吐合格 {sum(res.values())}／4", ""]
    # ---- 安慰劑同拆解
    L += ["## #1498 月中安慰劑／#1499 訊號拆解（14 個市場；「差」＝訊號做多月份 − 做空月份 嘅其後 5 日指數回報）", "",
          "| 市場 | 月尾 指數−美債 差（t） | 月中安慰劑 差（t） | 月尾 只睇指數 差（t） | 月尾 只睇美債 差（t） |", "|---|---|---|---|---|"]; A = []
    for nm, tk, _ in PR.MK:
        z = M[tk]; q = z.dropna(subset=["rel11"]); d1, t1 = diff(z.r, z.rel < 0); d2, t2 = diff(q.r11, q.rel11 < 0); d3, t3 = diff(z.r, z.im < 0); d4, t4 = diff(z.r, z.bm > 0); A.append((d1, t1, d2, t2, d3, t3, d4, t4))
        L.append(f"| {nm} {tk} | {d1:+.3f}%（{t1:+.2f}） | {d2:+.3f}%（{t2:+.2f}） | {d3:+.3f}%（{t3:+.2f}） | {d4:+.3f}%（{t4:+.2f}） |")
    A = np.array(A); me, pl, so, bo = A[:, 0].mean(), A[:, 2].mean(), A[:, 4].mean(), A[:, 6].mean(); npl = int((A[:, 3] >= 2).sum())
    ok98 = pl < 0.5 * me and npl <= 2; ok99 = me >= so and me >= bo
    L += [f"| **14 個市場平均** | **{me:+.3f}%** | **{pl:+.3f}%** | **{so:+.3f}%** | **{bo:+.3f}%** |", "",
          f"- #1498：月中平均 {pl:+.3f}% 對月尾 {me:+.3f}%（比例 {pl / me:.2f}）；月中 t ≥ 2 嘅市場 {npl} 個 → {'✅ 支持再平衡解釋' if ok98 else '❌ 唔支持（月中都有類似效應）'}",
          f"- #1499：原本訊號 {me:+.3f}% 對 只睇指數 {so:+.3f}%、只睇美債 {bo:+.3f}% → {'✅ 支持（相對訊號最強）' if ok99 else '❌ 唔支持（單一訊號一樣或者更強）'}", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
