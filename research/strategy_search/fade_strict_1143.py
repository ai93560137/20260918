"""[IDEAS #1143–#1149] 急動反向家族 嚴格執行版 第三批：假突破、跳空回補、時段反轉、通道均值回歸。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行同 #1129（fade_strict_1129.trade／run）：下一根開市市價入場；SL 由入場嗰根開始查；同根 SL／TP 都掂當 SL；到期收市平；每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/fade_strict_1143.py → research/strategy_search/FADE_STRICT_1143.md"""
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

OUT = os.path.join(HERE, "FADE_STRICT_1143.md")
H = 3600


def d1_atr_by_day(d):
    """UTC 日 → 前一日為止嘅 ATR14（D1），冇偷睇。"""
    b = B.resample(d, 86400); a = B.atr(b)
    return {int(b["t"][k]) // 86400: a[k - 1] for k in range(1, len(a)) if not np.isnan(a[k - 1])}


def sod(t):
    return np.asarray(t) % 86400


def r1143(d):
    b = B.resample(d, 900); t = b["t"]; day = t // 86400; s = sod(t); sigs = []
    m1d, m1s = d["t"] // 86400, sod(d["t"])
    asia = {}
    for dk in np.unique(day):
        m = (m1d == dk) & (m1s < 7 * H)
        if m.sum() >= 300:
            asia[int(dk)] = (d["h"][m].max(), d["l"][m].min())
    done = set()
    for i in range(len(t) - 1):
        dk = int(day[i])
        if dk in done or dk not in asia or not (7 * H <= s[i] < 10 * H):
            continue
        hi, lo = asia[dk]; mid = (hi + lo) / 2; en = b["o"][i + 1]
        if b["h"][i] > hi and b["c"][i] < hi:
            sg, sl = -1, b["h"][i] + 0.5
        elif b["l"][i] < lo and b["c"][i] > lo:
            sg, sl = 1, b["l"][i] - 0.5
        else:
            continue
        risk = abs(en - sl)
        if (mid - en) * sg < 0.5 * risk:
            continue
        sigs.append((i, sg, sl, mid, 16, None)); done.add(dk)
    return F.run(b, sigs)


def r1144(d):
    b = B.resample(d, 900); t = b["t"]; day = t // 86400; s = sod(t)
    dd = B.resample(d, 86400); prev = {int(dd["t"][k]) // 86400: (dd["h"][k - 1], dd["l"][k - 1]) for k in range(1, len(dd["t"]))}
    sigs, done = [], set()
    for i in range(len(t) - 1):
        dk = int(day[i])
        if dk in done or dk not in prev or not (7 * H <= s[i] < 20 * H):
            continue
        ph, pl = prev[dk]; en = b["o"][i + 1]
        if b["h"][i] > ph and b["c"][i] < ph:
            sg, sl = -1, b["h"][i] + 0.5
        elif b["l"][i] < pl and b["c"][i] > pl:
            sg, sl = 1, b["l"][i] - 0.5
        else:
            continue
        risk = abs(en - sl)
        sigs.append((i, sg, sl, en + sg * 1.5 * risk, 16, None)); done.add(dk)
    return F.run(b, sigs)


def r1145(d):
    b = B.resample(d, H); t = b["t"]; atr = d1_atr_by_day(d); sigs = []
    for i in range(len(t) - 1):
        if t[i + 1] - t[i] < 24 * H:                                   # 週末缺口：下一根係新一週第一根
            continue
        a = atr.get(int(t[i + 1]) // 86400)
        if a is None:
            continue
        gap = b["o"][i + 1] - b["c"][i]
        if abs(gap) < 0.3 * a:
            continue
        sg = -1 if gap > 0 else 1; en = b["o"][i + 1]; dist = max(abs(gap), 0.3 * a)
        sigs.append((i, sg, en - sg * dist, b["c"][i], 24, None))
    return F.run(b, sigs)


def r1146(d):
    b = B.resample(d, H); t = b["t"]; s = sod(t); day = t // 86400; atr = d1_atr_by_day(d); sigs = []
    ny = {}
    for i in range(len(t)):
        dk = int(day[i])
        if 13 * H <= s[i] < 20 * H:
            o0, c0 = ny.get(dk, (b["o"][i], b["c"][i]))
            ny[dk] = (o0, b["c"][i])
    for i in range(len(t) - 1):
        if not (s[i + 1] >= 23 * H and t[i + 1] - t[i] >= H):          # 下一根係 23:00 後第一根（亞洲開市）
            continue
        if s[i] >= 23 * H:
            continue
        dk = int(day[i]); a = atr.get(dk)
        if dk not in ny or a is None:
            continue
        mv = ny[dk][1] - ny[dk][0]
        if abs(mv) < 0.8 * a:
            continue
        sg = -1 if mv > 0 else 1; en = b["o"][i + 1]
        sigs.append((i, sg, en - sg * 0.8 * a, None, 8, None))
    return F.run(b, sigs)


def ema(x, n):
    out = np.full(len(x), np.nan); k = 2 / (n + 1)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def r1147(d):
    b = B.resample(d, 4 * H); c = b["c"]; a = B.atr(b); e = ema(c, 20); sigs = []
    for i in range(21, len(c) - 1):
        if np.isnan(a[i]) or np.isnan(e[i]):
            continue
        if c[i] > e[i] + 3 * a[i]:
            sg = -1
        elif c[i] < e[i] - 3 * a[i]:
            sg = 1
        else:
            continue
        en = b["o"][i + 1]
        if (e[i] - en) * sg < 0.5 * a[i]:
            continue
        sigs.append((i, sg, en - sg * 1.5 * a[i], e[i], 12, None))
    return F.run(b, sigs)


def r1148(d):
    b = B.resample(d, 900); a = B.atr(b); s = sod(b["t"]); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]
        if not (s[i] < 6 * H) or np.isnan(ap) or ap <= 0 or (b["h"][i] - b["l"][i]) < 2.5 * ap or b["c"][i] == b["o"][i]:
            continue
        sg = 1 if b["c"][i] < b["o"][i] else -1; en = b["o"][i + 1]; risk = 2 * ap
        sigs.append((i, sg, en - sg * risk, en + sg * risk, 8, None))
    return F.run(b, sigs)


def r1149(d):
    b = B.resample(d, 86400); a = B.atr(b); c = b["c"]; sigs = []
    wd = [dt.datetime.fromtimestamp(int(x), dt.timezone.utc).weekday() for x in b["t"]]
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if wd[i] != 4 or np.isnan(ap) or ap <= 0:
            continue
        mv = c[i] - c[i - 1]
        if abs(mv) < 1.5 * ap:
            continue
        sg = -1 if mv > 0 else 1; en = b["o"][i + 1]
        sigs.append((i, sg, en - sg * 1.5 * ap, None, 2, None))
    return F.run(b, sigs)


RULES = [("#1143", "亞洲區間假突破（倫敦）", r1143, "hf"), ("#1144", "前日高低假突破", r1144, "hf"), ("#1145", "週一跳空回補", r1145, "lf"),
         ("#1146", "紐約大走勢隔夜反轉", r1146, "lf"), ("#1147", "H4 Keltner 3×ATR 均值回歸", r1147, "hf"),
         ("#1148", "亞洲時段 M15 急動反向", r1148, "hf"), ("#1149", "週五大走勢週一反向", r1149, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動反向家族 嚴格執行版 第三批（IDEAS #1143–#1149）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；假突破／跳空回補／時段反轉／通道均值回歸；下一根開市市價入場、SL 先查、每張扣 0.5 美元、一次一張", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 |", "|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn, kind in RULES:
        cells, ok = [], True
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT[kind]):
            tr = fn(sets[seg]); s = A.stats([x[2] for x in tr])
            n = s["n"]; avg = s.get("avg", 0.0); pf = s.get("pf", 0.0)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]
            extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra} {'✅' if good else '❌'}" if n else "0 張 ❌")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；三批共試 21 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
