"""[IDEAS #1164–#1170] 急動順勢家族 嚴格 M1 版 第三批（多日持有）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/momo_strict_1164.py → research/strategy_search/MOMO_STRICT_1164.md"""
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

OUT = os.path.join(HERE, "MOMO_STRICT_1164.md")
H = 3600


def d1ctx(d):
    return M.Ctx(d, 86400)


def ext5(h, l, c):
    return lambda k, sg: (c[k] < l[max(0, k - 5):k].min()) if sg > 0 else (c[k] > h[max(0, k - 5):k].max())


def r1164(d):
    cx = d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]; rng = h[i] - l[i]
        if np.isnan(ap) or ap <= 0 or rng <= 0:
            continue
        mv = c[i] - c[i - 1]; pos = (c[i] - l[i]) / rng
        if mv >= 1.5 * ap and pos >= 0.75:
            sg = 1
        elif mv <= -1.5 * ap and pos <= 0.25:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * ap, None, 10, ext5(h, l, c)))
    return M.run_m1(cx, sigs)


def r1165(d):
    cx = d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 50); sigs = []
    for i in range(51, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or np.isnan(m[i]):
            continue
        mv = c[i] - c[i - 1]
        if mv >= 1.5 * ap and c[i] > m[i]:
            sg = 1
        elif mv <= -1.5 * ap and c[i] < m[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * ap, None, 10, ext5(h, l, c)))
    return M.run_m1(cx, sigs)


class WCtx(M.Ctx):
    def __init__(self, d):
        self.d = d; self.b = F2.weekly(d); self.sec = 7 * 86400
        import fade_strict_1143 as F3
        self.atr_d = F3.d1_atr_by_day(d)


def r1166(d):
    cx = WCtx(d); b = cx.b; a = B.atr(b); c = b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        if np.isnan(a[i]):
            continue
        mv = c[i] - c[i - 1]
        if abs(mv) < a[i]:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 1.5 * a[i], None, 4, None))
    return M.run_m1(cx, sigs)


def r1167(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; tr = F2.d1_trend(d, 50); sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a[i]) or not M.liquid(b["t"][i] + 4 * H):
            continue
        if c[i] > h[i - 20:i].max():
            sg = 1
        elif c[i] < l[i - 20:i].min():
            sg = -1
        else:
            continue
        if tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        ex = (lambda k, sg: (c[k] < l[max(0, k - 10):k].min()) if sg > 0 else (c[k] > h[max(0, k - 10):k].max()))
        sigs.append((i, sg, 2 * a[i], None, 30, ex))
    return M.run_m1(cx, sigs)


def r1168(d):
    cx = d1ctx(d); b = cx.b; a = B.atr(b); sigs = []
    wd = [dt.datetime.fromtimestamp(int(x), dt.timezone.utc).weekday() for x in b["t"]]
    for i in range(15, len(b["c"]) - 1):
        ap = a[i]
        if np.isnan(ap) or ap <= 0 or wd[i + 1] not in (1, 2, 3, 4):
            continue
        gap = b["o"][i + 1] - b["c"][i]
        if abs(gap) < 0.5 * ap:
            continue
        sigs.append((i, 1 if gap > 0 else -1, 0.5 * ap, None, 1, None))
    return M.run_m1(cx, sigs)


def r1169(d):
    cx = d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0:
            continue
        mv = c[i] - c[i - 3]
        if abs(mv) < 2 * ap:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 2 * ap, None, 5, None))
    return M.run_m1(cx, sigs)


def r1170(d):
    cx = d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    rng = h - l; pos = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5)
    for i in range(15, len(c) - 1):
        ap = a[i]
        if np.isnan(ap) or ap <= 0:
            continue
        up = all(pos[k] >= 0.7 and c[k] > c[k - 1] for k in (i - 2, i - 1, i))
        dn = all(pos[k] <= 0.3 and c[k] < c[k - 1] for k in (i - 2, i - 1, i))
        if not (up or dn):
            continue
        sigs.append((i, 1 if up else -1, 2 * ap, None, 10, ext5(h, l, c)))
    return M.run_m1(cx, sigs)


RULES = [("#1164", "D1 急動順勢持 10 日", r1164, "lf"), ("#1165", "D1 急動順勢＋SMA50 同向", r1165, "lf"), ("#1166", "週線急動順勢", r1166, "lf"),
         ("#1167", "H4 唐奇安 20＋D1 同向（#1158 事後變體）", r1167, "hf"), ("#1168", "D1 跳空順勢（非週一）", r1168, "lf"),
         ("#1169", "3 日動量", r1169, "lf"), ("#1170", "D1 連續 3 日強收市", r1170, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動順勢家族 嚴格 M1 版 第三批・多日（IDEAS #1164–#1170）", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；順勢共試 21 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
