"""[IDEAS #1192–#1198] 趨勢回調家族 嚴格 M1 版 第二批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1（同第一批 pullback_1185.py）。
用法：python3 research/strategy_search/pullback_1192.py → research/strategy_search/PULLBACK_1192.md"""
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

OUT = os.path.join(HERE, "PULLBACK_1192.md")
H = 3600


def wilder(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def adx(b, n=14):
    h, l, c = b["h"], b["l"], b["c"]
    up = np.r_[0, h[1:] - h[:-1]]; dn = np.r_[0, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = wilder(tr, n); pdi = 100 * wilder(pdm, n) / atr; mdi = 100 * wilder(mdm, n) / atr
    dx = 100 * abs(pdi - mdi) / np.where((pdi + mdi) > 0, pdi + mdi, np.nan)
    out = np.full(len(c), np.nan); v = ~np.isnan(dx); idx = np.nonzero(v)[0]
    if len(idx) >= n:
        out[idx[n - 1]:] = 0
        s = idx[0]; adx_ = wilder(dx[s:], n); out[s:] = adx_
    return out, pdi, mdi


def r1192(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 50); sigs = []
    for i in range(61, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m[i - 10]):
            continue
        if c[i] > m[i] and m[i] > m[i - 10] and c[i - 1] < c[i - 2] < c[i - 3] and c[i] > h[i - 1]:
            sg = 1
        elif c[i] < m[i] and m[i] < m[i - 10] and c[i - 1] > c[i - 2] > c[i - 3] and c[i] < l[i - 1]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, M4.opp(h, l, c, 5)))
    return M.run_m1(cx, sigs)


def r1193(d):
    cx = M3.WCtx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 20); sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m[i]):
            continue
        if c[i] > m[i] and c[i] < l[i - 1]:
            sg = 1
        elif c[i] < m[i] and c[i] > h[i - 1]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 1.5 * a[i], None, 4, None))
    return M.run_m1(cx, sigs)


def r1194(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; e10 = F3.ema(c, 10); e20 = F3.ema(c, 20)
    ax, pdi, mdi = adx(b); sigs = []
    for i in range(40, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(ax[i]) or np.isnan(e20[i]) or ax[i] <= 25:
            continue
        if pdi[i] > mdi[i] and l[i] <= e10[i] and c[i] > e20[i]:
            sg = 1
        elif mdi[i] > pdi[i] and h[i] >= e10[i] and c[i] < e20[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 15, lambda k, sg: (c[k] < e20[k]) if sg > 0 else (c[k] > e20[k])))
    return M.run_m1(cx, sigs)


def r1195(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; e = F3.ema(c, 20); sigs = []
    up = c > e + 2 * a; dn = c < e - 2 * a
    for i in range(31, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(e[i]):
            continue
        if up[i - 10:i].any() and l[i] <= e[i] < c[i]:
            sg = 1
        elif dn[i - 10:i].any() and h[i] >= e[i] > c[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 20, lambda k, sg: (c[k] < e[k] - a[k]) if sg > 0 else (c[k] > e[k] + a[k])))
    return M.run_m1(cx, sigs)


def r1196(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 50); sigs = []
    for i in range(81, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m[i]):
            continue
        nh = any(h[j] >= h[j - 60:j].max() for j in range(i - 19, i + 1))
        nl = any(l[j] <= l[j - 60:j].min() for j in range(i - 19, i + 1))
        if nh and c[i] <= c[i - 4:i + 1].min() and c[i] > m[i]:
            sg = 1
        elif nl and c[i] >= c[i - 4:i + 1].max() and c[i] < m[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, lambda k, sg: (c[k] > c[k - 5:k].max()) if sg > 0 else (c[k] < c[k - 5:k].min())))
    return M.run_m1(cx, sigs)


def r1197(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]
    macd = F3.ema(c, 12) - F3.ema(c, 26); sig = F3.ema(np.nan_to_num(macd, nan=0.0), 9); hist = macd - sig; sigs = []
    for i in range(45, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(hist[i - 2]):
            continue
        if macd[i] > 0 and hist[i] > hist[i - 1] and hist[i - 1] < hist[i - 2]:
            sg = 1
        elif macd[i] < 0 and hist[i] < hist[i - 1] and hist[i - 1] > hist[i - 2]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 15, lambda k, sg: (macd[k] < 0) if sg > 0 else (macd[k] > 0)))
    return M.run_m1(cx, sigs)


def r1198(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; e = F3.ema(c, 50); tr = F2.d1_trend(d, 50); sigs = []
    for i in range(51, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(e[i]) or not M.liquid(b["t"][i] + 4 * H):
            continue
        t = tr.get(int(b["t"][i]) // 86400)
        if t == 1 and l[i] <= e[i] < c[i]:
            sg = 1
        elif t == -1 and h[i] >= e[i] > c[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 30, M4.opp(h, l, c, 10)))
    return M.run_m1(cx, sigs)


RULES = [("#1192", "D1 兩日回調後恢復", r1192, "lf"), ("#1193", "週線上升趨勢中嘅跌週", r1193, "lf"), ("#1194", "ADX 強趨勢回踩 EMA10", r1194, "lf"),
         ("#1195", "Keltner 突破後回踩 EMA20", r1195, "lf"), ("#1196", "60 日新高後 5 日低位", r1196, "lf"),
         ("#1197", "MACD 零軸上回調轉向", r1197, "lf"), ("#1198", "H4 回踩 EMA50（D1 同向）", r1198, "hf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 趨勢回調家族 嚴格 M1 版 第二批（IDEAS #1192–#1198）", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；回調家族共 14 條）；最後一欄只作穩健度描述，唔影響判決", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
