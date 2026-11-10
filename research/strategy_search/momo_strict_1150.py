"""[IDEAS #1150–#1156] 急動順勢家族（嚴格執行版）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行同 #1129（fade_strict_1129.trade／run）：下一根開市市價入場；SL 由入場嗰根開始查；同根 SL／TP 都掂當 SL；到期收市平；每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/momo_strict_1150.py → research/strategy_search/MOMO_STRICT_1150.md"""
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

OUT = os.path.join(HERE, "MOMO_STRICT_1150.md")
H = 3600


def spike_follow(b, mult, sl_atr, tp_r, mb, trend=None):
    a = B.atr(b); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or (b["h"][i] - b["l"][i]) < mult * ap or b["c"][i] == b["o"][i]:
            continue
        sg = 1 if b["c"][i] > b["o"][i] else -1
        if trend is not None and trend.get(int(b["t"][i]) // 86400) != sg:
            continue
        en = b["o"][i + 1]; risk = sl_atr * ap
        sigs.append((i, sg, en - sg * risk, en + sg * tp_r * risk, mb, None))
    return sigs


def r1150(d):
    b = B.resample(d, H)
    return F.run(b, spike_follow(b, 2.5, 1.5, 2.0, 24))


def r1151(d):
    b = B.resample(d, 4 * H)
    return F.run(b, spike_follow(b, 2.0, 1.5, 2.0, 12))


def r1152(d):
    b = B.resample(d, 86400); a = B.atr(b); c = b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0:
            continue
        mv = c[i] - c[i - 1]
        if abs(mv) < 2 * ap:
            continue
        sg = 1 if mv > 0 else -1; en = b["o"][i + 1]
        sigs.append((i, sg, en - sg * 1.5 * ap, None, 5, None))
    return F.run(b, sigs)


def r1153(d):
    b = B.resample(d, H)
    return F.run(b, spike_follow(b, 2.5, 1.5, 2.0, 24, trend=F2.d1_trend(d, 50)))


def r1154(d):
    b = B.resample(d, 900); c = b["c"]; a = B.atr(b); n = len(c); sigs = []
    cs = np.cumsum(np.r_[0, c]); cs2 = np.cumsum(np.r_[0, c * c]); m = np.full(n, np.nan); s = m.copy()
    for i in range(19, n):
        mu = (cs[i + 1] - cs[i - 19]) / 20; m[i] = mu; s[i] = np.sqrt(max(0.0, (cs2[i + 1] - cs2[i - 19]) / 20 - mu * mu))
    for i in range(20, n - 1):
        if np.isnan(a[i]) or a[i] <= 0 or np.isnan(s[i]) or s[i] <= 0:
            continue
        if c[i] > m[i] + 2.5 * s[i]:
            sg = 1
        elif c[i] < m[i] - 2.5 * s[i]:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]; risk = 1.5 * a[i]
        sigs.append((i, sg, en - sg * risk, en + sg * 2 * risk, 16, None))
    return F.run(b, sigs)


def r1155(d):
    b = B.resample(d, 900); t = b["t"]; day = t // 86400; s = F3.sod(t); sigs = []
    m1d, m1s = d["t"] // 86400, F3.sod(d["t"]); asia = {}
    for dk in np.unique(day):
        mm = (m1d == dk) & (m1s < 7 * H)
        if mm.sum() >= 300:
            asia[int(dk)] = (d["h"][mm].max(), d["l"][mm].min())
    done = set()
    for i in range(len(t) - 1):
        dk = int(day[i])
        if dk in done or dk not in asia or not (7 * H <= s[i] < 10 * H):
            continue
        hi, lo = asia[dk]; mid = (hi + lo) / 2
        if b["c"][i] > hi:
            sg = 1
        elif b["c"][i] < lo:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]; risk = abs(en - mid)
        if (en - mid) * sg <= 0 or risk < 2.0 or risk > 25.0:
            continue
        sigs.append((i, sg, mid, en + sg * 1.5 * risk, 32, None)); done.add(dk)
    return F.run(b, sigs)


def r1156(d):
    b = B.resample(d, 900); t = b["t"]; day = t // 86400; s = F3.sod(t); atr = F3.d1_atr_by_day(d)
    dd = B.resample(d, 86400); prev = {int(dd["t"][k]) // 86400: (dd["h"][k - 1], dd["l"][k - 1]) for k in range(1, len(dd["t"]))}
    sigs, done = [], set()
    for i in range(len(t) - 1):
        dk = int(day[i])
        if dk in done or dk not in prev or dk not in atr or not (7 * H <= s[i] < 20 * H):
            continue
        ph, pl = prev[dk]
        if b["c"][i] > ph:
            sg = 1
        elif b["c"][i] < pl:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]; risk = 0.5 * atr[dk]
        sigs.append((i, sg, en - sg * risk, en + sg * 1.5 * risk, 32, None)); done.add(dk)
    return F.run(b, sigs)


RULES = [("#1150", "H1 急動順勢", r1150, "hf"), ("#1151", "H4 急動順勢", r1151, "lf"), ("#1152", "D1 急動順勢", r1152, "lf"),
         ("#1153", "H1 急動順勢＋D1 同向", r1153, "hf"), ("#1154", "M15 布林 2.5σ 突破順勢", r1154, "hf"),
         ("#1155", "亞洲區間突破順勢（倫敦）", r1155, "hf"), ("#1156", "前日高低突破順勢", r1156, "hf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動順勢家族 嚴格執行版（IDEAS #1150–#1156）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、SL 先查、每張扣 0.5 美元、一次一張", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
