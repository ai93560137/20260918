"""[IDEAS #1500–#1503] 論文實證第四批：跨地區月尾再平衡（市場中性，#1500／#1501）、債券一邊（#1502）、劑量反應（#1503）。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/paper_1500.py → research/strategy_search/PAPER_1500.md（要先跑過 fund_1464.py）"""
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
import paper_1482 as P       # noqa: E402
import paper_1494 as P4      # noqa: E402
import paper_robust as PR    # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "PAPER_1500.md")
COST = 0.0004
SIX = ("^GSPC", "^GDAXI", "^FTSE", "^N225", "^AXJO", "^GSPTSE")
W0, W1 = pd.Period("2010-07", "M"), pd.Period("2026-10", "M")


def xs(S, tks):
    """跨地區：訊號日 D＝美國倒數第 6 個交易日；各市場用 ≤ D 嘅最後收市計當月至今；D 之後下一個自己交易日收市入、當月最後交易日收市出。"""
    us = S["^GSPC"]; out = {}
    for p, g in us.groupby(us.index.to_period("M")):
        if not (W0 <= p <= W1) or len(g) < 12:
            continue
        D = g.index[-6]; r, fw = {}, {}
        for tk in tks:
            s = S[tk]; prev = s[s.index.to_period("M") < p]; cur = s[s.index.to_period("M") == p]; a = cur[cur.index <= D]; b = cur[cur.index > D]
            if len(prev) and len(a) and len(b) >= 2:
                r[tk] = a.iloc[-1] / prev.iloc[-1] - 1; fw[tk] = b.iloc[-1] / b.iloc[0] - 1
        if len(r) < max(4, len(tks) - 2):
            continue
        v = pd.Series(r); dm = v - v.mean(); w = -dm / dm.abs().sum(); out[p] = float((w * pd.Series(fw)).sum()) - COST
    return pd.Series(out)


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; m0, idx, target = G.base(); SP = pd.Period(f"{F.SPLIT}-01", "M")
    S = {}
    for _, tk, _ in PR.MK:
        s = B6.ohlc(tk).c; S[tk] = s[(s > 0) & (s.index.dayofweek < 5)]
    base = {"美國": P.leg("^GSPC", zn, False, "2010-07", "2026-10")[1], "歐洲": pd.DataFrame({t: P.leg(t, zn, False, "2010-07", "2026-10")[1] for t in ("^GDAXI", "^FTSE")}).mean(axis=1),
            "亞洲": pd.DataFrame({t: P.leg(t, zn, True, "2010-07", "2026-10")[1] for t in ("^N225", "^AXJO")}).mean(axis=1), "加拿大": P.leg("^GSPTSE", zn, False, "2010-07", "2026-10")[1]}
    base = {k: v.reindex(idx).fillna(0.0) for k, v in base.items()}
    L = ["# #1500–#1503：論文實證第四批（跨地區再平衡、債券一邊、劑量反應）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；2010-07–2026-10；成本 {100 * COST:.2f}%；只讀研究", ""]
    legs = {}; res = {}
    for tag, nm, tks in (("1500", "14 個市場", [tk for _, tk, _ in PR.MK]), ("1501", "6 個市場", list(SIX))):
        x = xs(S, tks); a, b = x[x.index < SP], x[x.index >= SP]; solo = x.mean() > 0 and PM.tstat(x) >= 2.0 and a.mean() > 0 and b.mean() > 0; st = x.reindex(idx).fillna(0.0); legs[tag] = st
        ok = F3.judge(L, f"#{tag} 跨地區月尾再平衡（{nm}，市場中性）", st, m0, target, solo, f"{len(x)} 個月；每月淨 {100 * x.mean():+.3f}%（t {PM.tstat(x):+.2f}）、勝率 {100 * (x > 0).mean():.0f}%、最差月 {100 * x.min():+.2f}%；前半／後半 {100 * a.mean():+.3f}%／{100 * b.mean():+.3f}%", SP)
        cr = {k: float(np.corrcoef(st, v)[0, 1]) for k, v in base.items()}; dup = [k for k, v in cr.items() if v > 0.7]
        L[-1:-1] = ["- 同時間序列腳每月相關：" + "、".join(f"{k} {v:+.2f}" for k, v in cr.items()) + ("；> 0.7 → 唔另計" if dup else "")]; res[tag] = ok and not dup
    c01 = float(np.corrcoef(legs["1500"], legs["1501"])[0, 1]); L += [f"- #1500 同 #1501 每月相關 {c01:+.2f}" + ("（> 0.7，兩條都過都只計一條）" if c01 > 0.7 else ""), ""]
    # ---- 1502 債券一邊
    z = pd.DataFrame({"s": S["^GSPC"], "b": zn}).dropna(); rows = []; gs = [(p, g) for p, g in z.groupby(z.index.to_period("M"))]
    for i in range(1, len(gs)):
        p, g = gs[i]; p0 = gs[i - 1][1].iloc[-1]
        if len(g) >= 12 and W0 <= p <= W1:
            a, e = g.iloc[-6], g.iloc[-1]; rows.append((p, (a.s / p0.s - 1) - (a.b / p0.b - 1), e.b / a.b - 1))
    zb = pd.DataFrame(rows, columns=["m", "rel", "rb"]).set_index("m"); lo, hi = zb.rb[zb.rel < 0].to_numpy(), zb.rb[zb.rel >= 0].to_numpy(); d0 = float(hi.mean() - lo.mean()); t_ = DR.welch(hi, lo)
    xb = pd.Series(np.where(zb.rel < 0, -1.0, 1.0) * zb.rb.to_numpy() - COST, index=zb.index); a, b = xb[xb.index < SP], xb[xb.index >= SP]; ok2 = d0 > 0 and t_ >= 2.0 and xb.mean() > 0 and a.mean() > 0 and b.mean() > 0
    L += ["## #1502 債券一邊（ZN=F；股票跑輸做空美債、跑贏做多）", "",
          f"- {len(zb)} 個月；美債最後 5 日回報：股票跑贏月份 {100 * hi.mean():+.3f}%（{len(hi)} 個月）、跑輸月份 {100 * lo.mean():+.3f}%（{len(lo)} 個月）；差 {100 * d0:+.3f}%（Welch t {t_:+.2f}）",
          f"- 策略每月淨 {100 * xb.mean():+.3f}%（t {PM.tstat(xb):+.2f}）；前半／後半 {100 * a.mean():+.3f}%／{100 * b.mean():+.3f}% → {'✅ 過（機制喺債券一邊有獨立證據；唔計可交易策略數）' if ok2 else '❌ 唔過'}", ""]
    # ---- 1503 劑量反應
    zn_ = zn; T = []; Q = []
    L += ["## #1503 劑量反應（14 個市場）", "", "| 市場 | |偏離| 最細三分一 | 中間 | 最大三分一 | 季尾月 差（t） | 其他月 差（t） |", "|---|---|---|---|---|---|"]
    for nm, tk, lag in PR.MK:
        zz = P4.months(tk, zn_, lag); pnl = np.where(zz.rel < 0, 1.0, -1.0) * zz.r; q = pd.qcut(zz.rel.abs(), 3, labels=False); t3 = [float(pnl[q == k].mean()) for k in range(3)]; T.append(t3)
        isq = zz.index.month % 3 == 0; dq, tq = P4.diff(zz.r[isq], zz.rel[isq] < 0); dn, tn = P4.diff(zz.r[~isq], zz.rel[~isq] < 0); Q.append((dq, dn))
        L.append(f"| {nm} {tk} | {100 * t3[0]:+.3f}% | {100 * t3[1]:+.3f}% | {100 * t3[2]:+.3f}% | {dq:+.3f}%（{tq:+.2f}） | {dn:+.3f}%（{tn:+.2f}） |")
    T = np.array(T).mean(axis=0); Q = np.array(Q).mean(axis=0); oka = T[2] > T[1] > T[0] and T[2] - T[0] > 0; okb = Q[0] > Q[1]
    L += [f"| **平均** | **{100 * T[0]:+.3f}%** | **{100 * T[1]:+.3f}%** | **{100 * T[2]:+.3f}%** | **{Q[0]:+.3f}%** | **{Q[1]:+.3f}%** |", "",
          f"- (a) 偏離越大效應越強：{'✅ 支持（單調）' if oka else '❌ 唔支持'}；(b) 季尾強過其他月尾：{'✅ 支持' if okb else '❌ 唔支持'}", "",
          f"## 總結：可另計嘅新策略 {int(res['1500'] or res['1501']) if c01 > 0.7 else int(res['1500']) + int(res['1501'])} 條（#1500 {'✅' if res['1500'] else '❌'}、#1501 {'✅' if res['1501'] else '❌'}）；#1502 {'✅' if ok2 else '❌'}；#1503 (a) {'✅' if oka else '❌'} (b) {'✅' if okb else '❌'}", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
