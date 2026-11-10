"""[IDEAS #1157–#1163] 急動順勢家族 嚴格執行 M1 版 第二批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行：訊號 K 線收市後下一根開市市價入場；出場逐根 M1 判（同一根 M1 SL／TP 都掂當 SL）；到期用大 K 線收市平；每張扣 0.5 美元；一次一張；
最低止蝕距離＝max(3 美元, 0.3×前一日 ATR14(D1))；訊號只喺 07:00–20:00 UTC。
用法：python3 research/strategy_search/momo_strict_1157.py → research/strategy_search/MOMO_STRICT_1157.md"""
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

COST = 0.5
H = 3600
OUT = os.path.join(HERE, "MOMO_STRICT_1157.md")


class Ctx:
    def __init__(self, d, sec):
        self.d = d; self.b = B.resample(d, sec) if sec != 7 * 86400 else None
        self.sec = sec; self.atr_d = F3.d1_atr_by_day(d)

    def floor(self, ts):
        a = self.atr_d.get(int(ts) // 86400)
        return None if a is None else max(3.0, 0.3 * a)


def liquid(ts):
    s = int(ts) % 86400
    return 7 * H <= s + 0 < 20 * H


def trade_m1(cx, i, sg, risk, tp_r, mb, ex=None):
    d, b = cx.d, cx.b; t = d["t"]; e = i + 1
    if e >= len(b["c"]):
        return None
    fl = cx.floor(b["t"][i])
    if fl is None:
        return None
    risk = max(risk, fl); en = b["o"][e]; sl = en - sg * risk; tp = None if tp_r is None else en + sg * tp_r * risk
    last = min(len(b["c"]) - 1, e + mb - 1)
    for k in range(e, last + 1):
        s0 = np.searchsorted(t, b["t"][k]); s1 = np.searchsorted(t, b["t"][k + 1]) if k + 1 < len(b["t"]) else len(t)
        hh, ll = d["h"][s0:s1], d["l"][s0:s1]
        slh = (ll <= sl) if sg > 0 else (hh >= sl)
        tph = ((hh >= tp) if sg > 0 else (ll <= tp)) if tp is not None else np.zeros(len(hh), bool)
        si = int(np.argmax(slh)) if slh.any() else 10**9; ti = int(np.argmax(tph)) if tph.any() else 10**9
        if si < 10**9 or ti < 10**9:
            px = sl if si <= ti else tp
            return int(b["t"][e]), sg, (sg * (px - en) - COST) / risk, k
        if ex is not None and ex(k, sg):
            return int(b["t"][e]), sg, (sg * (b["c"][k] - en) - COST) / risk, k
    return int(b["t"][e]), sg, (sg * (b["c"][last] - en) - COST) / risk, last


def run_m1(cx, sigs):
    out, busy = [], -1
    for i, sg, risk, tp_r, mb, ex in sigs:
        if i <= busy:
            continue
        x = trade_m1(cx, i, sg, risk, tp_r, mb, ex)
        if x:
            out.append(x[:3]); busy = x[3]
    return out


def r1157(d):
    cx = Ctx(d, H); b = cx.b; a = B.atr(b); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]; ad = cx.atr_d.get(int(b["t"][i]) // 86400); rng = b["h"][i] - b["l"][i]
        if np.isnan(ap) or ap <= 0 or ad is None or not liquid(b["t"][i] + H) or rng < 2 * ap or rng < 0.5 * ad or b["c"][i] == b["o"][i]:
            continue
        sigs.append((i, 1 if b["c"][i] > b["o"][i] else -1, 1.5 * ap, 2.0, 24, None))
    return run_m1(cx, sigs)


def r1158(d):
    cx = Ctx(d, 4 * H); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a[i]) or not liquid(b["t"][i] + 4 * H):
            continue
        if c[i] > h[i - 20:i].max():
            sg = 1
        elif c[i] < l[i - 20:i].min():
            sg = -1
        else:
            continue
        ex = (lambda k, sg: (c[k] < l[max(0, k - 10):k].min()) if sg > 0 else (c[k] > h[max(0, k - 10):k].max()))
        sigs.append((i, sg, 2 * a[i], None, 30, ex))
    return run_m1(cx, sigs)


def session_mom(d, start_h, signal_h, hold):
    cx = Ctx(d, H); b = cx.b; t = b["t"]; sigs = []
    for i in range(1, len(t) - 1):
        if int(t[i + 1]) % 86400 != signal_h * H or t[i + 1] - t[i] != H:
            continue
        dk = int(t[i]) // 86400; ad = cx.atr_d.get(dk)
        j0 = np.searchsorted(t, dk * 86400 + start_h * H)
        if ad is None or j0 >= i or int(t[j0]) != dk * 86400 + start_h * H:
            continue
        mv = b["c"][i] - b["o"][j0]
        if abs(mv) < 0.4 * ad:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 0.4 * ad, None, hold, None))
    return run_m1(cx, sigs)


def r1159(d):
    return session_mom(d, 7, 9, 7)


def r1160(d):
    return session_mom(d, 13, 15, 5)


def r1161(d):
    cx = Ctx(d, 4 * H); b = cx.b; a = B.atr(b); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]; rng = b["h"][i] - b["l"][i]
        if np.isnan(ap) or ap <= 0 or rng < 1.5 * ap or not liquid(b["t"][i] + 4 * H):
            continue
        pos = (b["c"][i] - b["l"][i]) / rng
        if pos >= 0.9:
            sg = 1; risk = b["o"][i + 1] - b["l"][i]
        elif pos <= 0.1:
            sg = -1; risk = b["h"][i] - b["o"][i + 1]
        else:
            continue
        sigs.append((i, sg, max(risk, 0.0), 1.5, 6, None))
    return run_m1(cx, sigs)


def r1162(d):
    cx = Ctx(d, 86400); b = cx.b; a = B.atr(b); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]; rng = b["h"][i] - b["l"][i]
        if np.isnan(ap) or ap <= 0 or rng < ap:
            continue
        pos = (b["c"][i] - b["l"][i]) / rng
        if pos >= 0.9:
            sg = 1
        elif pos <= 0.1:
            sg = -1
        else:
            continue
        sigs.append((i, sg, 0.5 * ap, None, 1, None))
    return run_m1(cx, sigs)


def r1163(d):
    cx = Ctx(d, H); b = cx.b; a = B.atr(b); o, c = b["o"], b["c"]; sigs = []
    for i in range(18, len(c) - 1):
        ap = a[i - 3]; ad = cx.atr_d.get(int(b["t"][i]) // 86400)
        if np.isnan(ap) or ap <= 0 or ad is None or not liquid(b["t"][i] + H):
            continue
        body = c[i - 2:i + 1] - o[i - 2:i + 1]; mv = c[i] - o[i - 2]
        if (body > 0).all() and mv >= max(1.5 * ap, 0.4 * ad):
            sg = 1
        elif (body < 0).all() and -mv >= max(1.5 * ap, 0.4 * ad):
            sg = -1
        else:
            continue
        sigs.append((i, sg, 1.5 * ap, 1.5, 12, None))
    return run_m1(cx, sigs)


RULES = [("#1157", "H1 急動順勢（流動＋下限）", r1157, "hf"), ("#1158", "H4 唐奇安 20 突破順勢", r1158, "hf"),
         ("#1159", "倫敦早段動量", r1159, "hf"), ("#1160", "紐約早段動量", r1160, "hf"), ("#1161", "H4 強收市延續", r1161, "hf"),
         ("#1162", "日線強收市隔日延續", r1162, "lf"), ("#1163", "H1 連續三根動量", r1163, "hf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動順勢家族 嚴格 M1 版 第二批（IDEAS #1157–#1163）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、M1 逐根判出場、最低止蝕 max(3 美元, 0.3×ATR D1)、07–20 UTC、每張扣 0.5 美元、一次一張", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；順勢共試 14 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
