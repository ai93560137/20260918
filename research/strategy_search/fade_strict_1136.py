"""[IDEAS #1136–#1142] 急動反向家族 嚴格執行版 第二批：順大趨勢、逆短線急動。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行同 #1129（fade_strict_1129.trade／run）：下一根開市市價入場；SL 由入場嗰根開始查；同根 SL／TP 都掂當 SL；到期收市平；每張扣 0.5 美元；一次一張。
趨勢過濾只用訊號 K 線收市前已知嘅日線（前一日收市對 SMA）。
用法：python3 research/strategy_search/fade_strict_1136.py → research/strategy_search/FADE_STRICT_1136.md"""
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

OUT = os.path.join(HERE, "FADE_STRICT_1136.md")


def sma(x, n):
    out = np.full(len(x), np.nan); cs = np.cumsum(np.r_[0, x])
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def d1_trend(d, n):
    """回傳 dict：UTC 日 → +1／−1（前一日收市對 SMA n；用嚟過濾當日訊號，冇偷睇）。"""
    b = B.resample(d, 86400); m = sma(b["c"], n); out = {}
    for k in range(1, len(b["c"])):
        if np.isnan(m[k - 1]):
            continue
        out[int(b["t"][k]) // 86400] = 1 if b["c"][k - 1] > m[k - 1] else -1
    return out


def r1136(d):
    b = B.resample(d, 3600); a = B.atr(b); tr = d1_trend(d, 50); sigs = []
    for i in range(15, len(b["c"]) - 1):
        ap = a[i - 1]
        if np.isnan(ap) or ap <= 0 or (b["h"][i] - b["l"][i]) < 2 * ap or b["c"][i] == b["o"][i]:
            continue
        sg = 1 if b["c"][i] < b["o"][i] else -1
        if tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        en = b["o"][i + 1]; risk = 1.5 * ap
        sigs.append((i, sg, en - sg * risk, en + sg * risk, 24, None))
    return F.run(b, sigs)


def r1137(d):
    b = B.resample(d, 86400); a = B.atr(b); m = sma(b["c"], 200); c, h, l = b["c"], b["h"], b["l"]; sigs = []
    for i in range(203, len(c) - 1):
        if np.isnan(m[i]) or np.isnan(a[i]):
            continue
        dn3 = c[i] < c[i - 1] < c[i - 2] < c[i - 3]; up3 = c[i] > c[i - 1] > c[i - 2] > c[i - 3]
        if c[i] > m[i] and dn3:
            sg = 1
        elif c[i] < m[i] and up3:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]
        ex = (lambda k: c[k] > h[k - 1]) if sg > 0 else (lambda k: c[k] < l[k - 1])
        sigs.append((i, sg, en - sg * 2 * a[i], None, 5, ex))
    return F.run(b, sigs)


def r1138(d):
    b = B.resample(d, 86400); a = B.atr(b); m = sma(b["c"], 200); r = F.rsi(b["c"], 2); c = b["c"]; sigs = []
    for i in range(203, len(c) - 1):
        if np.isnan(m[i]) or np.isnan(a[i]) or np.isnan(r[i]):
            continue
        if c[i] > m[i] and r[i] < 10:
            sg = 1
        elif c[i] < m[i] and r[i] > 90:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]
        ex = (lambda k: r[k] > 70) if sg > 0 else (lambda k: r[k] < 30)
        sigs.append((i, sg, en - sg * 2.5 * a[i], None, 5, ex))
    return F.run(b, sigs)


def r1139(d):
    b = B.resample(d, 4 * 3600); a = B.atr(b); r = F.rsi(b["c"], 2); tr = d1_trend(d, 50); sigs = []
    for i in range(20, len(b["c"]) - 1):
        if np.isnan(a[i]) or np.isnan(r[i]):
            continue
        t = tr.get(int(b["t"][i]) // 86400)
        if t == 1 and r[i] < 5:
            sg = 1
        elif t == -1 and r[i] > 95:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]
        ex = (lambda k: r[k] > 50) if sg > 0 else (lambda k: r[k] < 50)
        sigs.append((i, sg, en - sg * 2 * a[i], None, 12, ex))
    return F.run(b, sigs)


def weekly(d):
    t = d["t"]; wk = (t // 86400 + 3) // 7                                   # 星期一開始
    st = np.r_[0, np.nonzero(np.diff(wk))[0] + 1]; en = np.r_[st[1:], len(t)]
    return {"t": t[st], "o": d["o"][st], "h": np.maximum.reduceat(d["h"], st), "l": np.minimum.reduceat(d["l"], st), "c": d["c"][en - 1]}


def r1140(d):
    b = weekly(d); a = B.atr(b); m = sma(b["c"], 40); c = b["c"]; sigs = []
    for i in range(41, len(c) - 1):
        if np.isnan(m[i]) or np.isnan(a[i]):
            continue
        mv = c[i] - c[i - 1]
        if c[i] > m[i] and mv <= -a[i]:
            sg = 1
        elif c[i] < m[i] and mv >= a[i]:
            sg = -1
        else:
            continue
        en = b["o"][i + 1]
        sigs.append((i, sg, en - sg * 1.5 * a[i], None, 1, None))
    return F.run(b, sigs)


def r1141(d):
    b = B.resample(d, 86400); a = B.atr(b); m = sma(b["c"], 200); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; sigs = []
    for i in range(203, len(c) - 1):
        ap = a[i - 1]
        if np.isnan(m[i]) or np.isnan(ap) or ap <= 0:
            continue
        rng = h[i] - l[i]
        if rng < 1.5 * ap:
            continue
        pos = (c[i] - l[i]) / rng
        if c[i] > m[i] and pos >= 0.7 and l[i] < l[i - 1]:
            sg = 1; sl = l[i] - 0.25 * ap
        elif c[i] < m[i] and pos <= 0.3 and h[i] > h[i - 1]:
            sg = -1; sl = h[i] + 0.25 * ap
        else:
            continue
        sigs.append((i, sg, sl, None, 3, None))
    return F.run(b, sigs)


def r1142(d):
    b = B.resample(d, 3600); a = B.atr(b); tr = d1_trend(d, 50); o, c = b["o"], b["c"]; sigs = []
    for i in range(18, len(c) - 1):
        ap = a[i - 4]
        if np.isnan(ap) or ap <= 0:
            continue
        body = c[i - 3:i + 1] - o[i - 3:i + 1]; mv = c[i] - o[i - 3]
        t = tr.get(int(b["t"][i]) // 86400)
        if t == 1 and (body < 0).all() and mv <= -1.5 * ap:
            sg = 1
        elif t == -1 and (body > 0).all() and mv >= 1.5 * ap:
            sg = -1
        else:
            continue
        en = o[i + 1]; risk = 1.5 * ap
        sigs.append((i, sg, en - sg * risk, en + sg * risk, 12, None))
    return F.run(b, sigs)


RULES = [("#1136", "H1 急動逆回調（D1 SMA50）", r1136, "hf"), ("#1137", "D1 連跌三日接（SMA200）", r1137, "lf"),
         ("#1138", "D1 RSI(2) 回調（SMA200）", r1138, "lf"), ("#1139", "H4 RSI(2) 回調（D1 SMA50）", r1139, "hf"),
         ("#1140", "週線急跌接（SMA40 週）", r1140, "lf"), ("#1141", "D1 假跌破長下影（SMA200）", r1141, "lf"),
         ("#1142", "H1 連跌 4 根接（D1 SMA50）", r1142, "hf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 急動反向家族 嚴格執行版 第二批（IDEAS #1136–#1142）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；順大趨勢、逆短線急動；下一根開市市價入場、SL 先查、每張扣 0.5 美元、一次一張", "",
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
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過；加第一批共試 14 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
