"""[IDEAS #1240–#1244] C 門檻第一批（全新 5 條假設）。規格以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
C 門檻（只用喺 #1240 起）：①②③ 黃金三段每段平均 > 0、PF ≥ 1.15、張數 ≥ 20／10／15、① 正年 ≥ 5／8、剔最好 5%（向上取整、最少 1 張）後平均 > 0；
④ 黃金 2005–09（H1）平均 > 0、PF ≥ 1.10、n ≥ 15；⑤ 白銀 2010–25（H1；成本 0.03、最低止蝕 0.3×ATR）平均 > 0、PF ≥ 1.10、n ≥ 30。
用法：python3 research/strategy_search/gate_c_1240.py → research/strategy_search/GATE_C_1240.md"""
import datetime as dt
import math
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import fade_strict_1129 as F    # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import h1_lab as HL             # noqa: E402
import indep_1235 as I1         # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import tsmom_1213 as TS         # noqa: E402

OUT = os.path.join(HERE, "GATE_C_1240.md")
MAXB = 120


def edge_sigs(cx, cond, k_sl, mb, ex=None, start=1):
    """cond[i]＝+1／−1／0；由唔成立（或者反向）變成立嗰日入。"""
    b = cx.b; a = B.atr(b); sigs = []
    for i in range(start, len(cond) - 1):
        if cond[i] == 0 or cond[i] == cond[i - 1] or np.isnan(a[i]):
            continue
        sigs.append((i, int(cond[i]), k_sl * a[i], None, mb, ex))
    return M.run_m1(cx, sigs)


def r1240(d):
    cx = M3.d1ctx(d); c = cx.b["c"]; m = F2.sma(c, 100); n = len(c); cond = np.zeros(n)
    for i in range(100, n):
        r1, r0 = c[i] - c[i - 20], c[i - 20] - c[i - 40]
        if r1 > 0 and r1 > r0 and c[i] > m[i]:
            cond[i] = 1
        elif r1 < 0 and r1 < r0 and c[i] < m[i]:
            cond[i] = -1
    return edge_sigs(cx, cond, 2.5, 20)


def r1241(d):
    cx = M3.d1ctx(d); b = cx.b; h, l, c = b["h"], b["l"], b["c"]; n = len(c); cond = np.zeros(n)
    for i in range(252, n):
        hh, ll = h[i - 251:i + 1].max(), l[i - 251:i + 1].min()
        if c[i] >= hh * 0.97:
            cond[i] = 1
        elif c[i] <= ll * 1.03:
            cond[i] = -1
    return edge_sigs(cx, cond, 2.5, 20)


def r1242(d):
    cx = M3.d1ctx(d); c = cx.b["c"]; n = len(c); m50, m200 = F2.sma(c, 50), F2.sma(c, 200)
    r = np.r_[0, np.diff(np.log(c))]; vol = np.full(n, np.nan)
    for i in range(20, n):
        vol[i] = r[i - 19:i + 1].std()
    med = np.full(n, np.nan); p80 = np.full(n, np.nan)
    for i in range(270, n):
        w = vol[i - 249:i + 1]; med[i] = np.median(w); p80[i] = np.quantile(w, 0.8)
    trend = np.where(np.isnan(m200), 0, np.sign(m50 - m200)); cond = np.zeros(n)
    for i in range(270, n):
        if trend[i] != 0 and vol[i] < med[i]:
            cond[i] = trend[i]
    ex = (lambda k, sg: trend[k] != sg or (not np.isnan(p80[k]) and vol[k] > p80[k]))
    return edge_sigs(cx, cond, 3.0, MAXB, ex)


def r1243(d):
    cx = M3.d1ctx(d); b = cx.b; t, c = b["t"], b["c"]; n = len(c); keys = np.array([TS.wkey(x) for x in t])
    ends = [j for j in range(n) if j + 1 == n or keys[j + 1] != keys[j]]; starts = [0] + [e + 1 for e in ends[:-1]]
    wc = np.array([c[e] for e in ends]); wh = np.array([b["h"][s:e + 1].max() for s, e in zip(starts, ends)])
    wl = np.array([b["l"][s:e + 1].min() for s, e in zip(starts, ends)])
    wb = {"h": wh, "l": wl, "c": wc}; wa = B.atr(wb); a = B.atr(b); sigs = []
    for k in range(17, len(ends) - 1):
        if np.isnan(wa[k]):
            continue
        rng_ok = all((wh[j] - wl[j]) < 1.5 * wa[j] for j in (k - 2, k - 1, k) if not np.isnan(wa[j]))
        if not rng_ok:
            continue
        if wc[k] > wc[k - 1] > wc[k - 2] > wc[k - 3]:
            sg = 1
        elif wc[k] < wc[k - 1] < wc[k - 2] < wc[k - 3]:
            sg = -1
        else:
            continue
        i = ends[k]
        if np.isnan(a[i]):
            continue
        mb = min(23, (ends[k + 4] if k + 4 < len(ends) else n - 1) - i)
        sigs.append((i, sg, 3 * a[i], None, max(mb, 1), None))
    return M.run_m1(cx, sigs)


def r1244(d):
    cx = M3.d1ctx(d); b = cx.b; h, l, c = b["h"], b["l"], b["c"]; n = len(c); a = B.atr(b); sigs = []
    for i in range(121, n - 1):
        if np.isnan(a[i]):
            continue
        hi_pre, lo_pre = h[i - 120:i - 20].max(), l[i - 120:i - 20].min()      # 近 20 日之前嘅 100 日高／低（唔包今日新高）
        dd = (hi_pre - c[i - 20:i].min()) / hi_pre                            # 由嗰個高位回落到近 20 日最低收市
        ru = (c[i - 20:i].max() - lo_pre) / lo_pre
        if dd >= 0.08 and c[i] > h[i - 20:i].max():
            sg = 1
        elif ru >= 0.08 and c[i] < l[i - 20:i].min():
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2.5 * a[i], None, 30, (lambda k, sg: (c[k] < l[k - 10:k].min()) if sg > 0 else (c[k] > h[k - 10:k].max()))))
    return M.run_m1(cx, sigs)


RULES = [("#1240", "動量加速", r1240), ("#1241", "52 週高位附近（錨定）", r1241), ("#1242", "平靜趨勢", r1242),
         ("#1243", "週線穩步上升", r1243), ("#1244", "調整後恢復", r1244)]


def stats(tr):
    r = np.array([x[2] for x in tr], float); n = len(r)
    if not n:
        return 0, 0.0, 0.0, -1.0
    w, ls = r[r > 0].sum(), -r[r < 0].sum(); cut = max(1, math.ceil(0.05 * n))
    rob = float(np.mean(sorted(r)[:-cut])) if n > cut else -1.0
    return n, float(r.mean()), float(w / ls) if ls else 99.0, rob


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    g05 = HL.h1("xau/sig/duka_h1/", 2005, 2009); s10 = HL.h1("xau/sig/duka_h1_xagusd/", 2010, 2025)
    L = ["# C 門檻第一批（全新 5 條假設，IDEAS #1240–#1244）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；①②③ 黃金三段平均 > 0、PF ≥ 1.15、張數 ≥ 20／10／15、① 正年 ≥ 5／8、剔最好 5% 後平均 > 0；"
         "④ 黃金 2005–09 平均 > 0、PF ≥ 1.10、n ≥ 15；⑤ 白銀 2010–25 平均 > 0、PF ≥ 1.10、n ≥ 30", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | ④ 黃金 2005–09 | ⑤ 白銀 2010–25 | 判 |", "|---|---|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn in RULES:
        cells, ok = [], True
        for seg, nmin in (("d15", 20), ("m23", 10), ("d10", 15)):
            tr = fn(sets[seg]); n, avg, pf, rob = stats(tr)
            good = n >= nmin and avg > 0 and pf >= 1.15 and rob > 0; extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra}；剔 5% {rob:+.3f} {'✅' if good else '❌'}")
        tr = fn(g05); n, avg, pf, _ = stats(tr); good = n >= 15 and avg > 0 and pf >= 1.10; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        I1.silver_mode(True)
        try:
            tr = fn(s10)
        finally:
            I1.silver_mode(False)
        n, avg, pf, _ = stats(tr); good = n >= 30 and avg > 0 and pf >= 1.10; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- C 門檻合格（五關全過）：{'、'.join(passed) if passed else '冇'}（同批 5 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
