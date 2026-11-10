"""[IDEAS #1185–#1191] 趨勢回調家族 嚴格 M1 版 第一批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/pullback_1185.py → research/strategy_search/PULLBACK_1185.md"""
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

OUT = os.path.join(HERE, "PULLBACK_1185.md")
H = 3600


def rsi(c, n):
    """Wilder RSI。"""
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(c)):
        if i > n:
            au = (au * (n - 1) + up[i - 1]) / n; ad = (ad * (n - 1) + dn[i - 1]) / n
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def r1185(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; m200 = F2.sma(c, 200); m5 = F2.sma(c, 5); r2 = rsi(c, 2); sigs = []
    for i in range(201, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m200[i]) or np.isnan(r2[i]):
            continue
        if c[i] > m200[i] and r2[i] < 10:
            sg = 1
        elif c[i] < m200[i] and r2[i] > 90:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, lambda k, sg: (c[k] > m5[k]) if sg > 0 else (c[k] < m5[k])))
    return M.run_m1(cx, sigs)


def r1186(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 100); sigs = []
    for i in range(121, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m[i - 20]):
            continue
        dn3 = c[i] < c[i - 1] < c[i - 2] < c[i - 3]; up3 = c[i] > c[i - 1] > c[i - 2] > c[i - 3]
        if m[i] > m[i - 20] and c[i] > m[i] and dn3:
            sg = 1
        elif m[i] < m[i - 20] and c[i] < m[i] and up3:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 7, lambda k, sg: (c[k] > h[k - 1]) if sg > 0 else (c[k] < l[k - 1])))
    return M.run_m1(cx, sigs)


def r1187(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; e20 = F3.ema(c, 20); e50 = F3.ema(c, 50); sigs = []
    for i in range(51, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(e50[i]):
            continue
        if e20[i] > e50[i] and l[i] <= e20[i] and c[i] > e50[i]:
            sg = 1
        elif e20[i] < e50[i] and h[i] >= e20[i] and c[i] < e50[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 20, lambda k, sg: (c[k] < e50[k]) if sg > 0 else (c[k] > e50[k])))
    return M.run_m1(cx, sigs)


def r1188(d):
    cx = M.Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; r = rsi(c, 14); tr = F2.d1_trend(d, 50); sigs = []
    for i in range(16, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(r[i - 1]) or not M.liquid(b["t"][i] + 4 * H):
            continue
        if r[i - 1] < 35 <= r[i]:
            sg = 1
        elif r[i - 1] > 65 >= r[i]:
            sg = -1
        else:
            continue
        if tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        sigs.append((i, sg, 2 * a[i], None, 30, M4.opp(h, l, c, 10)))
    return M.run_m1(cx, sigs)


def r1189(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c, t = b["h"], b["l"], b["c"], b["t"]
    w = F2.weekly(d); wm = F2.sma(w["c"], 10); wk_d = (w["t"] // 86400 + 3) // 7
    wtr = {}
    for j in range(len(w["c"])):
        if not np.isnan(wm[j]):
            wtr[int(wk_d[j]) + 1] = 1 if w["c"][j] > wm[j] else -1          # 下一週用上一週已收市
    sigs = []
    for i in range(11, len(c) - 1):
        if np.isnan(a[i]):
            continue
        tw = wtr.get((int(t[i]) // 86400 + 3) // 7)
        if tw == 1 and c[i] < c[i - 10:i].min():
            sg = 1
        elif tw == -1 and c[i] > c[i - 10:i].max():
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, lambda k, sg: (c[k] > c[k - 5:k].max()) if sg > 0 else (c[k] < c[k - 5:k].min())))
    return M.run_m1(cx, sigs)


def r1190(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); c = b["c"]; m200 = F2.sma(c, 200); m20 = F2.sma(c, 20); sigs = []
    sd = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        sd[i] = c[i - 19:i + 1].std()
    for i in range(201, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m200[i]) or np.isnan(sd[i]):
            continue
        if c[i] > m200[i] and c[i] < m20[i] - 2 * sd[i]:
            sg = 1
        elif c[i] < m200[i] and c[i] > m20[i] + 2 * sd[i]:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 2 * a[i], None, 10, lambda k, sg: (c[k] > m20[k]) if sg > 0 else (c[k] < m20[k])))
    return M.run_m1(cx, sigs)


def r1191(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; m = F2.sma(c, 50); sigs = []
    for i in range(70, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(m[i - 10]):
            continue
        nh = [j for j in range(i - 4, i + 1) if h[j] >= h[j - 20:j].max()]
        nl = [j for j in range(i - 4, i + 1) if l[j] <= l[j - 20:j].min()]
        if nh and m[i] > m[i - 10]:
            top = h[nh[-1]:i + 1].max()
            if top - c[i] >= 1.5 * a[i]:
                sigs.append((i, 1, 2 * a[i], None, 15, (lambda top: lambda k, sg: c[k] >= top)(top)))
                continue
        if nl and m[i] < m[i - 10]:
            bot = l[nl[-1]:i + 1].min()
            if c[i] - bot >= 1.5 * a[i]:
                sigs.append((i, -1, 2 * a[i], None, 15, (lambda bot: lambda k, sg: c[k] <= bot)(bot)))
    return M.run_m1(cx, sigs)


RULES = [("#1185", "D1 RSI2 回調順勢", r1185, "lf"), ("#1186", "D1 三連跌回調（SMA100 上升）", r1186, "lf"),
         ("#1187", "D1 回踩 EMA20（EMA20 > EMA50）", r1187, "lf"), ("#1188", "H4 RSI 回調（D1 SMA50 同向）", r1188, "hf"),
         ("#1189", "週線趨勢＋日線 10 日低位", r1189, "lf"), ("#1190", "D1 布林下軌（SMA200 上方）", r1190, "lf"),
         ("#1191", "20 日高後 1.5 ATR 回調", r1191, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 趨勢回調家族 嚴格 M1 版 第一批（IDEAS #1185–#1191）", "",
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
