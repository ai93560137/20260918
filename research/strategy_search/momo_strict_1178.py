"""[IDEAS #1178–#1184] 急動順勢家族 嚴格 M1 版 第五批（波幅擴張／收窄突破、通道突破；多日）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/momo_strict_1178.py → research/strategy_search/MOMO_STRICT_1178.md"""
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
import fade_strict_1129 as F    # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import fade_strict_1143 as F3   # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import momo_strict_1171 as M4   # noqa: E402

OUT = os.path.join(HERE, "MOMO_STRICT_1178.md")
H = 3600


def r1178(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; e = F3.ema(c, 20); sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(e[i]):
            continue
        if c[i] > e[i] + 2 * a[i]:
            sg = 1
        elif c[i] < e[i] - 2 * a[i]:
            sg = -1
        else:
            continue
        ex = (lambda k, sg: (c[k] < e[k]) if sg > 0 else (c[k] > e[k]))
        sigs.append((i, sg, 2 * a[i], None, 20, ex))
    return M.run_m1(cx, sigs)


def r1179(d):
    cx = M3.d1ctx(d); b = cx.b; h, l, c = b["h"], b["l"], b["c"]; a5 = B.atr(b, 5); a20 = B.atr(b, 20); a14 = B.atr(b); sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a5[i]) or np.isnan(a20[i]) or a20[i] <= 0 or np.isnan(a14[i]) or a5[i] / a20[i] < 1.5:
            continue
        if c[i] > c[i - 10:i].max():
            sg = 1
        elif c[i] < c[i - 10:i].min():
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a14[i], None, 15, M4.opp(h, l, c, 5)))
    return M.run_m1(cx, sigs)


def r1180(d):
    cx = M3.WCtx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]; rng = h[i] - l[i]
        if np.isnan(ap) or ap <= 0 or rng < 1.5 * ap:
            continue
        pos = (c[i] - l[i]) / rng; mid = (h[i] + l[i]) / 2
        if pos >= 0.75:
            sg = 1
        elif pos <= 0.25:
            sg = -1
        else:
            continue
        sigs.append((i, sg, max((b["o"][i + 1] - mid) * sg, 0.0), None, 3, None))
    return M.run_m1(cx, sigs)


def r1181(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c, o = b["h"], b["l"], b["c"], b["o"]; tr = F2.d1_trend(d, 50); sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]; rng = h[i] - l[i]
        if np.isnan(ap) or ap <= 0 or rng < 2 * ap or not M.liquid(b["t"][i] + 4 * H):
            continue
        pos = (c[i] - l[i]) / rng
        if pos >= 0.8:
            sg = 1
        elif pos <= 0.2:
            sg = -1
        else:
            continue
        if tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        sigs.append((i, sg, 2 * ap, None, 30, M4.opp(h, l, c, 10)))
    return M.run_m1(cx, sigs)


def inside_or_nr7(d, kind):
    cx = M3.d1ctx(d); b = cx.b; h, l, c, o = b["h"], b["l"], b["c"], b["o"]; sigs = []
    rng = h - l
    for i in range(9, len(c) - 1):
        j = i - 1                                                     # 前一日（內包日／NR7）
        if kind == "inside":
            ok = h[j] <= h[j - 1] and l[j] >= l[j - 1]
        else:
            ok = rng[j] <= rng[j - 6:j + 1].min()
        if not ok:
            continue
        if c[i] > h[j]:
            sg = 1; risk = o[i + 1] - l[j]
        elif c[i] < l[j]:
            sg = -1; risk = h[j] - o[i + 1]
        else:
            continue
        sigs.append((i, sg, max(risk, 0.0), None, 5, None))
    return M.run_m1(cx, sigs)


def r1182(d):
    return inside_or_nr7(d, "inside")


def r1183(d):
    return inside_or_nr7(d, "nr7")


def r1184(d):
    cx = M3.WCtx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        rng = h[i] - l[i]
        if np.isnan(a[i]) or rng <= 0:
            continue
        pos = (c[i] - l[i]) / rng
        if c[i] > c[i - 3:i].max() and pos >= 0.7:
            sg = 1
        elif c[i] < c[i - 3:i].min() and pos <= 0.3:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 1.5 * a[i], None, 4, None))
    return M.run_m1(cx, sigs)


RULES = [("#1178", "D1 Keltner 突破順勢", r1178, "lf"), ("#1179", "波幅擴張突破", r1179, "lf"), ("#1180", "週線寬幅強收市", r1180, "lf"),
         ("#1181", "H4 急動強收市＋D1 同向", r1181, "hf"), ("#1182", "D1 內包日突破", r1182, "lf"), ("#1183", "NR7 突破順勢", r1183, "lf"),
         ("#1184", "3 週新高＋週線強收市", r1184, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動順勢家族 嚴格 M1 版 第五批・多日（IDEAS #1178–#1184）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、M1 逐根判出場、最低止蝕 max(3 美元, 0.3×ATR D1)、每張扣 0.5 美元、一次一張", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 | 剔最好 3 張後平均（①／②／③） |", "|---|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn, kind in RULES:
        cells, ok, rob = [], True, []
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT[kind]):
            tr = fn(sets[seg]); r = [x[2] for x in tr]; st = A.stats(r)
            n = st["n"]; avg = st.get("avg", 0.0); pf = st.get("pf", 0.0)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]
            extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra} {'✅' if good else '❌'}" if n else "0 張 ❌")
            rob.append(f"{np.mean(sorted(r)[:-3]):+.3f}" if n > 3 else "—")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} | {'／'.join(rob)} |")
        if ok:
            passed.append(key)
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；順勢共試 35 條）；最後一欄只作穩健度描述，唔影響判決", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
