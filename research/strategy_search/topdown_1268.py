"""[IDEAS #1268–#1269] 由上而下：先用 200 日線定長線方向，再喺方向之內搵入場（使用者 11-11「你用 top down approach，先定咗長線係升定跌，再做回測」＋「繼續研究」）。
規格以 IDEAS 預先登記為準（跑之前 commit；長線方向只定一個版本＝收市對 SMA200，冇試其他；參數教科書預設、冇網格）。
用埋方法 E 第二階段剩低嘅 2 條配額；之後停。標準＝「方向一致」（使用者 11-11 同意 #1267 用呢個標準）：
第一關（舊黃金 1975–2004 日線，成交模擬同成本同 #1260）：前後兩半每張平均都 > 0、做多做空每張平均都 > 0、PF ≥ 1.15、≥ 60 張、白銀 1970–2004 每張平均 > 0。
第二關（過第一關先跑、一次過；2010–2026 黃金 M1 嚴格版）：三段每段每張平均 > 0（≥ 5 張）、合併 PF ≥ 1.15。
用法：python3 research/strategy_search/topdown_1268.py → research/strategy_search/TOPDOWN_1268.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import gate_c_1240 as GC        # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import oldgold_1260 as OG       # noqa: E402

OUT = os.path.join(HERE, "TOPDOWN_1268.md")


def run_state(d, build):
    cx = M3.d1ctx(d); s = build(cx.b)
    return GC.edge_sigs(cx, s, 3.0, 250, lambda k, sg: s[k] != sg)


def r1268(d):
    """200 日線方向＋回調後重拾 20 日線：收市 > SMA200 而且收市由 SMA20 之下升返上去 → 買；跌穿之前 20 日最低收市或者跌穿 SMA200 → 平（做空相反）。SL 3×ATR14。"""
    def build(b):
        c = b["c"]; n = len(c); m200, m20 = F2.sma(c, 200), F2.sma(c, 20); s = np.zeros(n); cur = 0
        for i in range(201, n):
            up, dn = c[i] > m200[i], c[i] < m200[i]
            if cur > 0 and (not up or c[i] < c[i - 20:i].min()):
                cur = 0
            elif cur < 0 and (not dn or c[i] > c[i - 20:i].max()):
                cur = 0
            if cur == 0:
                if up and c[i] > m20[i] and c[i - 1] <= m20[i - 1]:
                    cur = 1
                elif dn and c[i] < m20[i] and c[i - 1] >= m20[i - 1]:
                    cur = -1
            s[i] = cur
        return s
    return run_state(d, build)


def r1269(d):
    """200 日線方向＋20 日突破：收市 > SMA200 而且收市破之前 20 日最高收市 → 買；跌穿之前 10 日最低收市或者跌穿 SMA200 → 平（做空相反）。SL 3×ATR14。"""
    def build(b):
        c = b["c"]; n = len(c); m200 = F2.sma(c, 200); s = np.zeros(n); cur = 0
        for i in range(201, n):
            up, dn = c[i] > m200[i], c[i] < m200[i]
            if cur > 0 and (not up or c[i] < c[i - 10:i].min()):
                cur = 0
            elif cur < 0 and (not dn or c[i] > c[i - 10:i].max()):
                cur = 0
            if cur == 0:
                if up and c[i] > c[i - 20:i].max():
                    cur = 1
                elif dn and c[i] < c[i - 20:i].min():
                    cur = -1
            s[i] = cur
        return s
    return run_state(d, build)


RULES = [("#1268", "200 日線方向＋回調後重拾 20 日線", r1268), ("#1269", "200 日線方向＋20 日突破", r1269)]
SEGS = [("① Duka 2015–22", "duka", "2015-01-01", "2022-12-31"), ("② MT5 2023–26", "mt5", "2023-01-01", "2026-10-30"), ("③ Duka 2010–14", "duka", "2010-01-01", "2014-12-31")]


def old(kind, name, start, y0):
    d = OG.load(name, start); restore = OG.patch(kind)
    try:
        return {k: [(int(a), int(b), float(c)) for a, b, c in fn(d) if OG.year(a) >= y0] for k, _, fn in RULES}
    finally:
        restore()


def main():
    gold = old("gold", "xauusd", "1973-01-01", 1975); silver = old("silver", "xagusd", "1968-01-01", 1970)
    mk = lambda v: "✅" if v else "❌"  # noqa: E731
    L = ["# 由上而下：200 日線定方向＋方向內入場（IDEAS #1268–#1269）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；標準＝方向一致（冇顯著度要求）",
         "- 第一關：舊黃金 1975–2004 前後兩半都正、多空都正、PF ≥ 1.15、≥ 60 張、白銀 1970–2004 正", "",
         "| IDEAS | 規則 | 張數 | 每張平均 R | PF | 前半／後半 | 多／空 | 每年 t（參考） | 白銀 | 第一關 |", "|---|---|---|---|---|---|---|---|---|---|"]
    stage1 = []
    for key, nm, _ in RULES:
        tr = gold[key]; n, avg, pf = OG.stats(tr)
        a1 = OG.stats([x for x in tr if OG.year(x[0]) < 1990])[1]; a2 = OG.stats([x for x in tr if OG.year(x[0]) >= 1990])[1]
        lo = OG.stats([x for x in tr if x[1] > 0])[1]; sh = OG.stats([x for x in tr if x[1] < 0])[1]
        sn, sa, sp = OG.stats(silver[key]); t_ = OG.tstat(OG.yearly(tr, 1975, 2004))
        ok = a1 > 0 and a2 > 0 and lo > 0 and sh > 0 and pf >= 1.15 and n >= 60 and sa > 0
        L.append(f"| {key} | {nm} | {n} {mk(n >= 60)} | {avg:+.3f} | {pf:.2f} {mk(pf >= 1.15)} | {a1:+.3f}／{a2:+.3f} {mk(a1 > 0 and a2 > 0)} | {lo:+.3f}／{sh:+.3f} {mk(lo > 0 and sh > 0)} | {t_:.2f} | {sn} 張 {sa:+.3f}R PF {sp:.2f} {mk(sa > 0)} | {'✅ 過' if ok else '❌'} |")
        if ok:
            stage1.append(key)
    L += ["", f"- 第一關過：{'、'.join(stage1) if stage1 else '冇'}", ""]
    passed = []
    if stage1:
        data = [(nm, A.load(src, a, b)) for nm, src, a, b in SEGS]; fns = {k: f for k, _, f in RULES}
        L += ["## 第二關：2010–2026 黃金 M1 嚴格版（一次過）", "", "| IDEAS | " + " | ".join(s[0] for s in SEGS) + " | 合併 | 多／空 | 判 |", "|---|---|---|---|---|---|---|"]
        for key in stage1:
            cells, ok, allr, allsg = [], True, [], []
            for _, d in data:
                tr = fns[key](d); r = np.array([x[2] for x in tr]); good = len(r) >= 5 and r.mean() > 0; ok = ok and good
                allr += list(r); allsg += [x[1] for x in tr]
                cells.append(f"{len(r)} 張 {r.mean() if len(r) else 0:+.3f}R {mk(good)}")
            r = np.array(allr); sg = np.array(allsg); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()); ok = ok and pf >= 1.15
            lo = r[sg > 0].mean() if (sg > 0).any() else 0.0; sh = r[sg < 0].mean() if (sg < 0).any() else 0.0
            L.append(f"| {key} | " + " | ".join(cells) + f" | {len(r)} 張 {r.mean():+.3f}R PF {pf:.2f} {mk(pf >= 1.15)} | {lo:+.3f}／{sh:+.3f} | {'✅ 合格' if ok else '❌'} |")
            if ok:
                passed.append(key)
    L += ["", f"- **兩關都過（合格）：{'、'.join(passed) if passed else '冇'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
