"""[IDEAS #1171–#1177] 急動順勢家族 嚴格 M1 版 第四批（多日持有）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/momo_strict_1171.py → research/strategy_search/MOMO_STRICT_1171.md"""
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
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402

OUT = os.path.join(HERE, "MOMO_STRICT_1171.md")
H = 3600


def opp(h, l, c, n):
    return lambda k, sg: (c[k] < l[max(0, k - n):k].min()) if sg > 0 else (c[k] > h[max(0, k - n):k].max())


def r1171(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; tr = F2.d1_trend(d, 50); sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or (h[i] - l[i]) < 2 * ap or c[i] == b["o"][i] or not M.liquid(b["t"][i] + 4 * H):
            continue
        sg = 1 if c[i] > b["o"][i] else -1
        if tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        sigs.append((i, sg, 2 * ap, None, 30, opp(h, l, c, 10)))
    return M.run_m1(cx, sigs)


def r1172(d):
    cx = M3.WCtx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        if np.isnan(a[i]):
            continue
        if c[i] > h[i - 4:i].max():
            sg = 1
        elif c[i] < l[i - 4:i].min():
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 8, opp(h, l, c, 2)))
    return M.run_m1(cx, sigs)


def r1173(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(21, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0:
            continue
        mv = c[i] - c[i - 1]
        if c[i] > c[i - 20:i].max() and mv >= ap:
            sg = 1
        elif c[i] < c[i - 20:i].min() and mv <= -ap:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * ap, None, 10, opp(h, l, c, 5)))
    return M.run_m1(cx, sigs)


def r1174(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or (h[i] - l[i]) < 2 * ap or c[i] == o[i]:
            continue
        sg = 1 if c[i] > o[i] else -1; mid = (h[i] + l[i]) / 2; risk = (o[i + 1] - mid) * sg
        sigs.append((i, sg, max(risk, 0.0), None, 5, None))
    return M.run_m1(cx, sigs)


def r1175(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(16, len(c) - 1):
        a1, a2 = a[i - 2], a[i - 1]
        if np.isnan(a1) or np.isnan(a2):
            continue
        m1, m2 = c[i - 1] - c[i - 2], c[i] - c[i - 1]
        if m1 >= a1 and m2 >= a2:
            sg = 1
        elif m1 <= -a1 and m2 <= -a2:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a2, None, 10, opp(h, l, c, 5)))
    return M.run_m1(cx, sigs)


def r1176(d):
    cx = M.Ctx(d, H); b = cx.b; a = B.atr(b); h, l, c, o, t = b["h"], b["l"], b["c"], b["o"], b["t"]; tr = F2.d1_trend(d, 50); sigs = []
    day_open = {}
    for k in range(len(t)):
        day_open.setdefault(int(t[k]) // 86400, o[k])
    for i in range(15, len(c) - 1):
        ap = a[i - 1]; dk = int(t[i]) // 86400; ad = cx.atr_d.get(dk)
        if np.isnan(ap) or ap <= 0 or ad is None or not M.liquid(t[i] + H) or (h[i] - l[i]) < 2 * ap or c[i] == o[i]:
            continue
        sg = 1 if c[i] > o[i] else -1; dmv = c[i] - day_open[dk]
        if dmv * sg < 0.7 * ad or tr.get(dk) != sg:
            continue
        sigs.append((i, sg, 2 * ap, None, 48, opp(h, l, c, 12)))
    return M.run_m1(cx, sigs)


def r1177(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c, t = b["c"], b["t"]; sigs = []
    mon = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in t])
    for i in range(15, len(c) - 1):
        if mon[i] == mon[i - 1] or np.isnan(a[i - 1]):
            continue                                                  # i＝當月第一個交易日
        mv = c[i] - c[i - 1]
        if abs(mv) < a[i - 1]:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 2 * a[i - 1], None, 10, None))
    return M.run_m1(cx, sigs)


RULES = [("#1171", "H4 急動順勢＋D1 同向（多日）", r1171, "hf"), ("#1172", "週線 4 週突破順勢", r1172, "lf"),
         ("#1173", "D1 新 20 日高＋急動", r1173, "lf"), ("#1174", "D1 寬幅日順勢", r1174, "lf"), ("#1175", "D1 兩連急動日", r1175, "lf"),
         ("#1176", "H1 急動＋當日走勢＋D1 共振", r1176, "hf"), ("#1177", "月初動量延續", r1177, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動順勢家族 嚴格 M1 版 第四批・多日（IDEAS #1171–#1177）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、M1 逐根判出場、最低止蝕 max(3 美元, 0.3×ATR D1)、每張扣 0.5 美元、一次一張", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 |", "|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn, kind in RULES:
        cells, ok = [], True
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT[kind]):
            tr = fn(sets[seg]); st = A.stats([x[2] for x in tr])
            n = st["n"]; avg = st.get("avg", 0.0); pf = st.get("pf", 0.0)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]
            extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra} {'✅' if good else '❌'}" if n else "0 張 ❌")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；順勢共試 28 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
