"""[IDEAS #1129–#1135] 急動反向家族（嚴格執行版）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
嚴格執行：訊號 K 線收市後，下一根開市價市價入場；SL 由入場嗰根開始查，同一根 SL／TP 都掂當 SL；到期用收市價平；每張扣 0.5 美元；每條規則一次一張。
三段：① Duka 2015–2022 ② MT5 2023-01→2026-10 ③ Duka 2010–2014。
用法：python3 research/strategy_search/fade_strict_1129.py → research/strategy_search/FADE_STRICT_1129.md"""
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

COST = 0.5
OUT = os.path.join(HERE, "FADE_STRICT_1129.md")


def trade(b, i, sg, sl, tp, max_bars, exit_fn=None):
    """訊號喺第 i 根收市；第 i+1 根開市入場。回傳 (入場時間, sg, R, 出場根 index) 或 None。"""
    o, h, l, c, t = b["o"], b["h"], b["l"], b["c"], b["t"]
    e = i + 1
    if e >= len(c):
        return None
    en = o[e]; risk = abs(en - sl)
    if risk <= 0 or (sl - en) * sg >= 0:
        return None
    if tp is not None and (tp - en) * sg <= 0:
        return None
    last = min(len(c) - 1, e + max_bars - 1)
    for k in range(e, last + 1):
        if (l[k] <= sl) if sg > 0 else (h[k] >= sl):
            return int(t[e]), sg, (sg * (sl - en) - COST) / risk, k
        if tp is not None and ((h[k] >= tp) if sg > 0 else (l[k] <= tp)):
            return int(t[e]), sg, (sg * (tp - en) - COST) / risk, k
        if exit_fn is not None and exit_fn(k):
            return int(t[e]), sg, (sg * (c[k] - en) - COST) / risk, k
    return int(t[e]), sg, (sg * (c[last] - en) - COST) / risk, last


def run(b, sigs, cd_sec=0):
    """sigs：[(i, sg, sl, tp, max_bars, exit_fn)]，按 i 排序；一次一張＋冷卻。"""
    out, busy, last_t = [], -1, -10**12
    for i, sg, sl, tp, mb, ex in sigs:
        if i <= busy or b["t"][i] - last_t < cd_sec:
            continue
        x = trade(b, i, sg, sl, tp, mb, ex)
        if x:
            out.append(x[:3]); busy = x[3]; last_t = b["t"][i]
    return out


def bar_spike(b, mult, atr_n=14, pad=0.25, tp_r=1.0, mb=24):
    a = B.atr(b, atr_n); sigs = []
    for i in range(atr_n + 1, len(b["c"]) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or (b["h"][i] - b["l"][i]) < mult * ap or b["c"][i] == b["o"][i]:
            continue
        sg = 1 if b["c"][i] < b["o"][i] else -1
        sl = b["l"][i] - pad * ap if sg > 0 else b["h"][i] + pad * ap
        en = b["o"][i + 1]; risk = abs(en - sl)
        sigs.append((i, sg, sl, en + sg * tp_r * risk, mb, None))
    return sigs


def r1129(d):
    b = B.resample(d, 3600)
    return run(b, bar_spike(b, 2.5, mb=24))


def r1135(d):
    b = B.resample(d, 4 * 3600)
    return run(b, bar_spike(b, 2.0, mb=12))


def r1130(d):
    b = B.resample(d, 86400); a = B.atr(b); c = b["c"]; sigs = []
    for i in range(15, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0:
            continue
        mv = c[i] - c[i - 1]
        if abs(mv) < 2 * ap:
            continue
        sg = -1 if mv > 0 else 1; en = b["o"][i + 1]; sl = en - sg * 1.5 * ap
        sigs.append((i, sg, sl, en + sg * 1.5 * ap, 5, None))
    return run(b, sigs)


def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(c), np.nan); ad = au.copy()
    if len(c) <= n:
        return au
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    rs = au / np.where(ad == 0, np.nan, ad)
    out = 100 - 100 / (1 + rs)
    return np.where(ad == 0, 100.0, out)


def r1131(d):
    b = B.resample(d, 3600); a = B.atr(b); r = rsi(b["c"], 2); sigs = []
    for i in range(20, len(b["c"]) - 1):
        if np.isnan(a[i]) or a[i] <= 0 or np.isnan(r[i]):
            continue
        if r[i] < 5:
            sg = 1
        elif r[i] > 95:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]; sl = en - sg * 2 * a[i]
        ex = (lambda k, sg=sg: (r[k] > 50) if sg > 0 else (r[k] < 50))
        sigs.append((i, sg, sl, None, 10, ex))
    return run(b, sigs)


def r1132(d):
    b = B.resample(d, 900); c = b["c"]; a = B.atr(b); sigs = []
    n = len(c); m = np.full(n, np.nan); s = m.copy()
    cs = np.cumsum(np.r_[0, c]); cs2 = np.cumsum(np.r_[0, c * c])
    for i in range(19, n):
        mu = (cs[i + 1] - cs[i - 19]) / 20; m[i] = mu; s[i] = np.sqrt(max(0.0, (cs2[i + 1] - cs2[i - 19]) / 20 - mu * mu))
    for i in range(20, n - 1):
        if np.isnan(a[i]) or a[i] <= 0 or np.isnan(s[i]) or s[i] <= 0:
            continue
        if c[i] > m[i] + 2.5 * s[i]:
            sg = -1
        elif c[i] < m[i] - 2.5 * s[i]:
            sg = 1
        else:
            continue
        en = b["o"][i + 1]; tp = m[i]
        if (tp - en) * sg < 0.5 * a[i]:
            continue
        sigs.append((i, sg, en - sg * a[i], tp, 16, None))
    return run(b, sigs)


def r1133(d):
    t, o, c = d["t"], d["o"], d["c"]; n = len(c); sigs = []
    for i in range(16, n - 1):
        mv = c[i] - o[i - 15]
        if abs(mv) < 5.0:
            continue
        sg = -1 if mv > 0 else 1; en = o[i + 1]
        sigs.append((i, sg, en - sg * 5.0, en + sg * 5.0, 60, None))
    return run(d, sigs, cd_sec=3600)


def r1134(d):
    b5 = B.resample(d, 300); t = d["t"]; sigs = []
    idx = np.searchsorted(t, b5["t"] + 300) - 1                       # 嗰根 M5 最後一根 M1
    for j in range(len(b5["c"])):
        i = int(idx[j])
        if i < 30 or i >= len(t) - 1 or t[i] // 300 != b5["t"][j] // 300:
            continue
        hi, lo = b5["h"][j], b5["l"][j]
        if hi - lo < 6.0 or b5["c"][j] == b5["o"][j]:
            continue
        sg = 1 if b5["c"][j] < b5["o"][j] else -1
        en = d["o"][i + 1]; sl = lo - 1.0 if sg > 0 else hi + 1.0; risk = abs(en - sl)
        if risk < 2.0 or risk > 15.0:
            continue
        sigs.append((i, sg, sl, en + sg * risk, 60, None))
    return run(d, sigs, cd_sec=3600)


RULES = [("#1129", "H1 急動反向", r1129, "hf"), ("#1130", "D1 急動反向", r1130, "lf"), ("#1131", "H1 RSI(2) 極端", r1131, "hf"),
         ("#1132", "M15 布林 2.5σ", r1132, "hf"), ("#1133", "rev15 市價版", r1133, "hf"), ("#1134", "M5 急動 市價版", r1134, "hf"),
         ("#1135", "H4 急動反向", r1135, "lf")]
CRIT = {"hf": ((200, 0.10, 1.15), (100, 0.05, 1.10), (100, 0.05, 1.10)), "lf": ((60, 0.10, 1.15), (30, 0.05, 1.10), (40, 0.05, 1.10))}


def yearly_pos(tr):
    ys = {}
    for ts, _, r in tr:
        ys.setdefault(dt.datetime.fromtimestamp(ts, dt.timezone.utc).year, []).append(r)
    return sum(1 for v in ys.values() if np.mean(v) > 0), len(ys)


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動反向家族 嚴格執行版（IDEAS #1129–#1135）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、SL 先查、每張扣 0.5 美元、一次一張", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 |", "|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn, kind in RULES:
        cells, ok = [], True
        for (seg, crit) in zip(("d15", "m23", "d10"), CRIT[kind]):
            tr = fn(sets[seg]); s = A.stats([x[2] for x in tr])
            n = s["n"]; avg = s.get("avg", 0.0); pf = s.get("pf", 0.0)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]
            extra = ""
            if seg == "d15":
                yp, yn = yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
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
