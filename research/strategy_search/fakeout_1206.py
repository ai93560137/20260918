"""[IDEAS #1206–#1212] 假突破／區間反轉家族 嚴格 M1 版 第一批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/fakeout_1206.py → research/strategy_search/FAKEOUT_1206.md"""
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
import momo_strict_1171 as M4   # noqa: E402
import pullback_1192 as P2      # noqa: E402

OUT = os.path.join(HERE, "FAKEOUT_1206.md")
H = 3600


def r1206(d):
    cx = M3.d1ctx(d); b = cx.b; o, h, l, c = b["o"], b["h"], b["l"], b["c"]; sigs = []
    for i in range(21, len(c) - 1):
        hh, ll = h[i - 20:i].max(), l[i - 20:i].min()
        if h[i] > hh and c[i] < hh:
            sg, risk = -1, h[i] - o[i + 1]
        elif l[i] < ll and c[i] > ll:
            sg, risk = 1, o[i + 1] - l[i]
        else:
            continue
        sigs.append((i, sg, max(risk, 0.0), None, 10, lambda k, sg: (c[k] < l[k - 10:k].min()) if sg < 0 else (c[k] > h[k - 10:k].max())))
    return M.run_m1(cx, sigs)


def r1207(d):
    cx = M3.d1ctx(d); b = cx.b; o, h, l, c = b["o"], b["h"], b["l"], b["c"]; sigs = []
    for i in range(11, len(c) - 1):
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        pos = (c[i] - l[i]) / rng
        if l[i] < l[i - 10:i].min() and c[i] > c[i - 1] and pos >= 0.7:
            sg, risk = 1, o[i + 1] - l[i]
        elif h[i] > h[i - 10:i].max() and c[i] < c[i - 1] and pos <= 0.3:
            sg, risk = -1, h[i] - o[i + 1]
        else:
            continue
        sigs.append((i, sg, max(risk, 0.0), None, 5, None))
    return M.run_m1(cx, sigs)


def r1208(d):
    cx = M3.WCtx(d); b = cx.b; o, h, l, c = b["o"], b["h"], b["l"], b["c"]; sigs = []
    for i in range(14, len(c) - 1):
        hh, ll = h[i - 13:i].max(), l[i - 13:i].min()
        if h[i] > hh and c[i] < hh:
            sg, risk = -1, h[i] - o[i + 1]
        elif l[i] < ll and c[i] > ll:
            sg, risk = 1, o[i + 1] - l[i]
        else:
            continue
        sigs.append((i, sg, max(risk, 0.0), None, 4, None))
    return M.run_m1(cx, sigs)


def r1209(d):
    cx = M3.d1ctx(d); b = cx.b; o, h, l, c, t = b["o"], b["h"], b["l"], b["c"], b["t"]
    mk = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year * 12 + dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in t])
    prev = {}
    for m in np.unique(mk):
        idx = np.nonzero(mk == m)[0]; prev[m + 1] = (h[idx].max(), l[idx].min())
    sigs = []; done = set()
    for i in range(2, len(c) - 1):
        m = mk[i]
        if m not in prev or mk[i - 1] != m:
            continue
        ph, pl = prev[m]
        idx_m = np.nonzero(mk[:i] == m)[0]
        left = int(np.sum(mk[i + 1:] == m))
        if left < 1:
            continue
        mb = min(20, left)
        if (m, 1) not in done and c[i - 1] > ph and c[i] < ph and not np.any(c[idx_m[:-1]] > ph):
            done.add((m, 1)); top = h[idx_m[0]:i + 1].max()
            sigs.append((i, -1, max(top - o[i + 1], 0.0), None, mb, None))
        elif (m, -1) not in done and c[i - 1] < pl and c[i] > pl and not np.any(c[idx_m[:-1]] < pl):
            done.add((m, -1)); bot = l[idx_m[0]:i + 1].min()
            sigs.append((i, 1, max(o[i + 1] - bot, 0.0), None, mb, None))
    return M.run_m1(cx, sigs)


def r1210(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; m20 = F2.sma(c, 20); ax, _, _ = P2.adx(b); sigs = []
    sd = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        sd[i] = c[i - 19:i + 1].std()
    for i in range(40, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(ax[i]) or np.isnan(sd[i]) or ax[i] >= 20:
            continue
        if c[i] > m20[i] + 2 * sd[i]:
            sg = -1
        elif c[i] < m20[i] - 2 * sd[i]:
            sg = 1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, lambda k, sg: (c[k] < m20[k]) if sg < 0 else (c[k] > m20[k])))
    return M.run_m1(cx, sigs)


def r1211(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c, t = b["h"], b["l"], b["c"], b["t"]
    db = B.resample(d, 86400); a5 = B.atr(db, 5); a50 = B.atr(db, 50); ratio = {}
    for k in range(1, len(db["c"])):
        if not np.isnan(a5[k - 1]) and not np.isnan(a50[k - 1]) and a50[k - 1] > 0:
            ratio[int(db["t"][k]) // 86400] = a5[k - 1] / a50[k - 1]
    sigs = []
    for i in range(21, len(c) - 1):
        q = ratio.get(int(t[i]) // 86400)
        if q is None or q >= 0.8 or np.isnan(a[i]) or not M.liquid(t[i] + 4 * H):
            continue
        hh, ll = h[i - 20:i].max(), l[i - 20:i].min(); mid = (hh + ll) / 2
        if c[i] > hh:
            sg = -1
        elif c[i] < ll:
            sg = 1
        else:
            continue
        en = b["o"][i + 1]; risk = max(1.5 * a[i], cx.floor(t[i]) or 0); dist = (mid - en) * sg
        if dist <= 0:
            continue
        sigs.append((i, sg, risk, dist / risk, 12, None))
    return M.run_m1(cx, sigs)


def r1212(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; ax, _, _ = P2.adx(b); sigs = []
    for i in range(40, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(ax[i]) or ax[i] >= 20:
            continue
        mv = c[i] - c[i - 3]
        if c[i] > c[i - 1] > c[i - 2] > c[i - 3] and mv >= 1.5 * a[i]:
            sg = -1
        elif c[i] < c[i - 1] < c[i - 2] < c[i - 3] and -mv >= 1.5 * a[i]:
            sg = 1
        else:
            continue
        sigs.append((i, sg, 1.5 * a[i], None, 5, None))
    return M.run_m1(cx, sigs)


RULES = [("#1206", "D1 20 日假突破", r1206, "lf"), ("#1207", "D1 關鍵反轉日", r1207, "lf"), ("#1208", "週線 13 週假突破", r1208, "lf"),
         ("#1209", "上月高低位假突破", r1209, "lf"), ("#1210", "ADX＜20 布林極端反向", r1210, "lf"), ("#1211", "低波幅 H4 區間回中", r1211, "hf"),
         ("#1212", "ADX＜20 三日連升反向", r1212, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 假突破／區間反轉家族 嚴格 M1 版 第一批（IDEAS #1206–#1212）", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過）；最後一欄只作穩健度描述，唔影響判決", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
