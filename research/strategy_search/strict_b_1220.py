"""[IDEAS #1220–#1227] B 門檻（使用者 11-10「B，收緊門檻再揾」）：原本三段標準＋(B2) 三段剔最好 3 張後平均 > 0＋(B3) ① t ≥ 2.0。
#1220：用 B 門檻重驗現有 8 條合格規則（只作描述）。#1221–#1227：趨勢指標轉向第一批（嚴格 M1 版，同 #1157）。規格以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
用法：python3 research/strategy_search/strict_b_1220.py → research/strategy_search/STRICT_B_1220.md"""
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
import fade_strict_1143 as F3   # noqa: E402
import h1_lab3 as L3            # noqa: E402
import h1_lab4 as L4            # noqa: E402
import h1_lab5 as L5            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import momo_strict_1171 as M4   # noqa: E402
import momo_strict_1178 as M5   # noqa: E402

OUT = os.path.join(HERE, "STRICT_B_1220.md")
MAXB = 120


def set_trend_cost(c):
    for m in (L3, L4, L5, H6, H7, H8):
        if hasattr(m, "COST"):
            m.COST = c


def trend(fn):
    def run(d):
        set_trend_cost(2.0)
        out = fn(B.resample(d, 3600))
        set_trend_cost(0.5)
        out = out if isinstance(out, list) else out[0]
        return [(int(a), int(b), float(c)) for a, b, c in out]
    return run


def flips(d, state_fn, k_sl=2.0):
    """state_fn(b) → 每根 D1 嘅 +1／−1／0 狀態；由非 s 轉 s（s≠0）入場；狀態離開 s 即平。"""
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); s = state_fn(b); sigs = []
    for i in range(1, len(s) - 1):
        if s[i] == 0 or s[i] == s[i - 1] or np.isnan(a[i]):
            continue
        sigs.append((i, int(s[i]), k_sl * a[i], None, MAXB, (lambda s: lambda k, sg: s[k] != sg)(s)))
    return M.run_m1(cx, sigs)


def st_supertrend(b, n=10, mult=3.0):
    h, l, c = b["h"], b["l"], b["c"]; a = B.atr(b, n); hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a; fu, fl = ub.copy(), lb.copy(); s = np.zeros(len(c))
    for i in range(1, len(c)):
        if np.isnan(a[i]) or np.isnan(a[i - 1]):
            continue
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        prev = s[i - 1] or 1
        s[i] = 1 if (prev < 0 and c[i] > fu[i]) else (-1 if (prev > 0 and c[i] < fl[i]) else prev)
    return s


def st_psar(b, step=0.02, mx=0.2):
    h, l = b["h"], b["l"]; s = np.zeros(len(h))
    if len(h) < 3:
        return s
    up = True; af = step; ep = h[0]; sar = l[0]; s[0] = 1
    for i in range(1, len(h)):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(mx, af + step)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(mx, af + step)
        s[i] = 1 if up else -1
    return s


def st_linreg(b, n=50, r2min=0.3):
    """斜率轉向嗰日 R² ≥ r2min 先入；之後斜率同向就維持，轉向即 0／反向（要再符合 R²）。"""
    c = b["c"]; s = np.zeros(len(c)); x = np.arange(n); xm = x.mean(); sxx = ((x - xm) ** 2).sum(); prev_sign = 0
    for i in range(n - 1, len(c)):
        y = c[i - n + 1:i + 1]; ym = y.mean(); slope = ((x - xm) * (y - ym)).sum() / sxx
        ss = ((y - ym) ** 2).sum(); r2 = (slope ** 2 * sxx / ss) if ss > 0 else 0.0
        cur = 1 if slope > 0 else -1
        if cur == prev_sign:
            s[i] = cur if s[i - 1] == cur else 0
        else:
            s[i] = cur if (prev_sign != 0 and r2 >= r2min) else 0
        prev_sign = cur
    return s


def st_ichimoku(b):
    h, l, c = b["h"], b["l"], b["c"]; n = len(c); s = np.zeros(n)
    mid = lambda k, p: (h[max(0, k - p + 1):k + 1].max() + l[max(0, k - p + 1):k + 1].min()) / 2  # noqa: E731
    for i in range(78, n):
        ten, kij = mid(i, 9), mid(i, 26); j = i - 26
        sa = (mid(j, 9) + mid(j, 26)) / 2; sb = mid(j, 52); top, bot = max(sa, sb), min(sa, sb)
        if c[i] > top:
            s[i] = 1 if ten > kij else (1 if s[i - 1] == 1 else 0)
        elif c[i] < bot:
            s[i] = -1 if ten < kij else (-1 if s[i - 1] == -1 else 0)
        else:
            s[i] = 0
    return s


def st_aroon(b, n=25):
    """上線升穿下線而且上線 ≥ 70 → +1；反向交叉 → 狀態離開。"""
    h, l = b["h"], b["l"]; s = np.zeros(len(h))
    for i in range(n, len(h)):
        up = 100 * (n - int(np.argmax(h[i - n:i + 1][::-1]))) / n
        dn = 100 * (n - int(np.argmin(l[i - n:i + 1][::-1]))) / n
        if s[i - 1] == 1 and up > dn:
            s[i] = 1
        elif s[i - 1] == -1 and dn > up:
            s[i] = -1
        elif up > dn and up >= 70:
            s[i] = 1
        elif dn > up and dn >= 70:
            s[i] = -1
    return s


def st_ema(b):
    c = b["c"]; e1, e2 = F3.ema(c, 10), F3.ema(c, 50)
    return np.where(np.isnan(e2), 0, np.where(e1 > e2, 1, np.where(e1 < e2, -1, 0)))


def st_kama(b, n=10, fast=2, slow=30, ermin=0.3):
    c = b["c"]; k = np.full(len(c), np.nan); s = np.zeros(len(c)); fsc, ssc = 2 / (fast + 1), 2 / (slow + 1)
    if len(c) <= n:
        return s
    k[n] = c[n]; er = np.zeros(len(c))
    for i in range(n + 1, len(c)):
        ch = abs(c[i] - c[i - n]); vol = np.abs(np.diff(c[i - n:i + 1])).sum()
        er[i] = ch / vol if vol > 0 else 0
        sc = (er[i] * (fsc - ssc) + ssc) ** 2; k[i] = k[i - 1] + sc * (c[i] - k[i - 1])
    for i in range(n + 2, len(c)):
        d_ = k[i] - k[i - 1]; cur = 1 if d_ > 0 else (-1 if d_ < 0 else s[i - 1])
        s[i] = cur if (cur == s[i - 1] or er[i] >= ermin) else 0
    return s


OLD = [("#1105", "52 週突破", trend(L5.r1105), "lf"), ("#1107", "上季突破（926 真倉）", trend(H6.r1107), "lf"),
       ("#1113", "低波幅 20 日突破（926 真倉）", trend(H7.r1113), "lf"), ("#1114", "月初三日區間突破（933 真倉）", trend(H8.r1114), "lf"),
       ("#1116", "海龜系統 2", trend(H8.r1116), "lf"), ("#1165", "D1 急動＋SMA50", M3.r1165, "lf"), ("#1174", "D1 寬幅日", M4.r1174, "lf"),
       ("#1178", "D1 Keltner", M5.r1178, "lf")]
NEW = [("#1221", "SuperTrend 轉向", lambda d: flips(d, st_supertrend), "lf"), ("#1222", "拋物線 SAR 轉向", lambda d: flips(d, st_psar), "lf"),
       ("#1223", "50 日線性回歸斜率轉向", lambda d: flips(d, st_linreg), "lf"), ("#1224", "一目均衡表穿雲", lambda d: flips(d, st_ichimoku), "lf"),
       ("#1225", "Aroon(25) 交叉", lambda d: flips(d, st_aroon), "lf"), ("#1226", "EMA10／EMA50 交叉", lambda d: flips(d, st_ema), "lf"),
       ("#1227", "KAMA 轉向", lambda d: flips(d, st_kama), "lf")]


def judge(rules, sets, L):
    passed = []
    for key, name, fn, kind in rules:
        cells, ok_a, ok_b = [], True, True
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT[kind]):
            tr = fn(sets[seg]); r = np.array([x[2] for x in tr], float); n = len(r)
            if not n:
                cells.append("0 張 ❌"); ok_a = ok_b = False; continue
            avg = float(r.mean()); w, ls = r[r > 0].sum(), -r[r < 0].sum(); pf = float(w / ls) if ls else 99.0
            rob = float(np.mean(sorted(r)[:-3])) if n > 3 else -1.0
            t = avg / (r.std(ddof=1) / np.sqrt(n)) if n > 2 and r.std(ddof=1) > 0 else 0.0
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]; extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}，t {t:.2f}"; good = good and yp >= 5
                ok_b = ok_b and t >= 2.0
            ok_b = ok_b and rob > 0
            ok_a = ok_a and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra}；剔 3 {rob:+.3f} {'✅' if good else '❌'}")
        verdict = "✅ B 合格" if (ok_a and ok_b) else ("⚠ 原本合格、B 唔過" if ok_a else "❌")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {verdict} |")
        if ok_a and ok_b:
            passed.append(key)
    return passed


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    hdr = ["| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 |", "|---|---|---|---|---|---|"]
    L = ["# B 門檻（IDEAS #1220–#1227）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；B 門檻＝原本三段標準＋(B2) 三段剔最好 3 張後平均 > 0＋(B3) ① t ≥ 2.0；趨勢 sim 用 #1128 嚴格成本 2.0 美元，M1 版 0.5 美元", "",
         "## #1220 重驗現有 8 條合格規則（只作描述，唔改原本判決）", ""] + hdr
    old_ok = judge(OLD, sets, L)
    L += ["", f"- B 門檻下仍然合格：{'、'.join(old_ok) if old_ok else '冇'}", "", "## #1221–#1227 趨勢指標轉向第一批", ""] + hdr
    new_ok = judge(NEW, sets, L)
    L += ["", f"- B 合格：{'、'.join(new_ok) if new_ok else '冇'}（同批 7 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
