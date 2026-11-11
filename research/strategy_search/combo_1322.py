"""[IDEAS #1322] 組合（照 #1272–#1321 預先登記嘅規則揀）：入場＝合格入場類入面舊黃金 PF 最高（#1273 RSI(14) 由下升穿 40，PF 1.99）；
出場＝#1300 只用方向反轉（2.28）；過濾＝#1307 SMA50 都喺 SMA200 上（1.74）；倉位＝#1314 持倉中收市破 20 日新高加一張（1.74）。
照關 1–3 同新黃金測一次；另要 PF 高過基準（#1268 事件版）。鄰近＝方向均線 5 個 × 入場參數 35／40／45／50。
用法：python3 research/strategy_search/combo_1322.py → research/strategy_search/COMBO_1322.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import frame_1272 as F          # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import oldgold_1260 as OG       # noqa: E402
import robust_1270 as RB        # noqa: E402

OUT = os.path.join(HERE, "COMBO_1322.md")


def simulate(cx, nd=200, pe=40):
    b = cx.b; a = B.atr(b); n = len(b["c"]); out = []; busy = -1; side = {}
    for sg, q in ((1, b), (-1, F.neg(b))):
        md = F.sma(q["c"], nd)
        side[sg] = (q, md, F.e2(q, a, pe), F.f6(q, a, md, 50), F.x9(q, a, md, 0), F.pmax(q["c"], 20))
    for i in range(max(nd, 60) + 1, n - 1):
        if i <= busy or np.isnan(a[i]):
            continue
        sg = 0
        for s in (1, -1):
            q, md, trig, filt, mk, hi = side[s]
            if not np.isnan(md[i]) and q["c"][i] > md[i] and trig[i] and filt[i]:
                sg = s; break
        if not sg:
            continue
        q, md, trig, filt, mk, hi = side[sg]; ex = mk(i)
        x = M.trade_m1(cx, i, sg, 3.0 * a[i], None, 250, (lambda k, s, ex=ex: ex(k)))
        if not x:
            continue
        out.append((x[0], sg, x[2])); busy = kx = x[3]
        for j in range(i + 1, kx):
            if q["c"][j] > hi[j]:
                if not np.isnan(a[j]):
                    ex3 = mk(i)
                    z = M.trade_m1(cx, j, sg, 3.0 * a[j], None, kx - j, (lambda k, s, ex=ex3: ex(k)))
                    if z:
                        out.append((z[0], sg, z[2]))
                break
    return sorted(out)


def main():
    mk = lambda v: "✅" if v else "❌"  # noqa: E731
    restore = OG.patch("gold"); cxg = M3.d1ctx(RB.load())
    try:
        tr = simulate(cxg); base = F.simulate(cxg, F.BASE)
        nb = sum(1 for nd in F.DIRS for pe in (35, 40, 45, 50)
                 if (lambda t: OG.stats(F.seg(t, 1975, 2004))[1] > 0 and OG.stats(F.seg(t, 2005, 2026))[1] > 0)(simulate(cxg, nd, pe)))
    finally:
        restore()
    restore = OG.patch("silver")
    try:
        sil = [x for x in simulate(M3.d1ctx(OG.load("xagusd", "1968-01-01"))) if OG.year(x[0]) >= 1970]
    finally:
        restore()
    old = F.seg(tr, 1975, 2004); n, avg, pf = OG.stats(old); bo = OG.stats(F.seg(base, 1975, 2004))
    a1 = OG.stats(F.seg(old, 1975, 1989))[1]; a2 = OG.stats(F.seg(old, 1990, 2004))[1]
    lo = OG.stats([x for x in old if x[1] > 0])[1]; sh = OG.stats([x for x in old if x[1] < 0])[1]; sa = OG.stats(sil)[1]
    g1 = a1 > 0 and a2 > 0 and lo > 0 and sh > 0 and pf >= 1.15 and n >= 60 and sa > 0; g3 = nb >= 16; g4o = pf > bo[2]
    L = ["# 組合（IDEAS #1322）：#1273 入場＋#1300 出場＋#1307 過濾＋#1314 加倉", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；照 #1272–#1321 預先登記嘅揀法（每類舊黃金 PF 最高嘅合格者）",
         f"- 舊黃金 1975–2004：{n} 張 {avg:+.3f}R PF {pf:.2f}（基準 {bo[0]} 張 {bo[1]:+.3f}R PF {bo[2]:.2f}）；前半／後半 {a1:+.2f}／{a2:+.2f}；多／空 {lo:+.2f}／{sh:+.2f}；白銀 {sa:+.3f}",
         f"- 關 1 {mk(g1)}；鄰近 {nb}／20 → 關 3 {mk(g3)}；舊黃金 PF 高過基準 {mk(g4o)}"]
    final = False
    if g1 and g3 and g4o:
        cells, ok, allr, ballr = [], True, [], []
        for _, src, a_, b_ in F.SEGS:
            cx = M3.d1ctx(A.load(src, a_, b_)); t = simulate(cx); r = np.array([x[2] for x in t]); good = len(r) >= 5 and r.mean() > 0; ok = ok and good
            allr += list(r); ballr += [x[2] for x in F.simulate(cx, F.BASE)]; cells.append(f"{len(r)} 張 {r.mean() if len(r) else 0:+.2f}{mk(good)}")
        r = np.array(allr); br = np.array(ballr); pf2 = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()); bpf = br[br > 0].sum() / max(1e-9, -br[br < 0].sum())
        final = ok and pf2 >= 1.15 and pf2 > bpf
        L.append(f"- 新黃金 2010–2026（M1 嚴格版）：{' '.join(cells)}；合併 {len(r)} 張 {r.mean():+.3f}R PF {pf2:.2f}（基準 PF {bpf:.2f}）→ {mk(final)}")
    L += ["", f"- **判：{'✅ 合格' if final else '❌ 唔合格'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
