"""[IDEAS #1235–#1239] 新方法（使用者 11-10「用 B2 門檻，揾到 3 個合格先停，唔好用番之前方法」）。規格以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
四關全過先合格：①②③ 黃金三段 B2（原本低頻三段標準＋三段剔最好 3 張後平均 > 0；M1 嚴格版）；
④ 黃金 2005–2009（Duka H1）平均 > 0、PF ≥ 1.05、n ≥ 15；⑤ 白銀 2010–2025（Duka H1；成本 0.03、最低止蝕 0.3×ATR14）平均 > 0、PF ≥ 1.05、n ≥ 30。
註：黃金 2005–09 H1 之前喺 #1087／#1128 驗證過趨勢家族（唔係呢 5 條）；白銀 H1 之前只喺 #1088／#1089 做「黃金訊號輸入」，冇用嚟測試規則。
用法：python3 research/strategy_search/indep_1235.py → research/strategy_search/INDEP_1235.md"""
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
import h1_lab as HL             # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import pullback_1192 as P2      # noqa: E402
import tsmom_1213 as TS         # noqa: E402

OUT = os.path.join(HERE, "INDEP_1235.md")
MAXB = 120


def flips(d, state, k_sl, exit_fn=None):
    """state(b) → 每根 D1 嘅 +1／−1／0（0＝冇訊號）；入場：s[i]≠0 而且 s[i−1]≠s[i]；出場 exit_fn(k, sg) 或者狀態唔再係 sg。"""
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); s, ex = state(b); sigs = []
    for i in range(1, len(s) - 1):
        if s[i] == 0 or s[i] == s[i - 1] or np.isnan(a[i]):
            continue
        sigs.append((i, int(s[i]), k_sl * a[i], None, MAXB, (lambda ex: lambda k, sg: ex(k, sg))(ex)))
    return M.run_m1(cx, sigs)


def r1235(d):
    def state(b):
        c, h, l = b["c"], b["h"], b["l"]; n = len(c)
        m50, m200 = F2.sma(c, 50), F2.sma(c, 200); _, pdi, mdi = P2.adx(b)
        up = np.zeros(n); dn = np.zeros(n)
        for i in range(200, n):
            mid = (h[i - 54:i + 1].max() + l[i - 54:i + 1].min()) / 2
            v = [c[i] - m200[i], m50[i] - m200[i], c[i] - c[i - 63], c[i] - mid,
                 (pdi[i] - mdi[i]) if not (np.isnan(pdi[i]) or np.isnan(mdi[i])) else 0.0]
            up[i] = sum(x > 0 for x in v); dn[i] = sum(x < 0 for x in v)
        s = np.where(up >= 4, 1, np.where(dn >= 4, -1, 0))
        return s, (lambda k, sg: (up[k] if sg > 0 else dn[k]) <= 2)
    return flips(d, state, 3.0)


def r1236(d):
    def state(b):
        t, c = b["t"], b["c"]; keys = np.array([TS.wkey(x) for x in t]); n = len(c)
        ends = [j for j in range(n) if j + 1 == n or keys[j + 1] != keys[j]]
        wc = np.array([c[j] for j in ends]); wh = np.array([b["h"][(ends[k - 1] + 1 if k else 0):ends[k] + 1].max() for k in range(len(ends))])
        wl = np.array([b["l"][(ends[k - 1] + 1 if k else 0):ends[k] + 1].min() for k in range(len(ends))])
        m10, m40 = F2.sma(wc, 10), F2.sma(wc, 40); mac = F3.ema(wc, 12) - F3.ema(wc, 26); sig = F3.ema(np.nan_to_num(mac, nan=0.0), 9)
        wup = np.zeros(len(ends)); wdn = np.zeros(len(ends))
        for k in range(40, len(ends)):
            mid = (wh[k - 25:k + 1].max() + wl[k - 25:k + 1].min()) / 2
            v = [wc[k] - m40[k], m10[k] - m40[k], wc[k] - wc[k - 13], wc[k] - mid, (mac[k] - sig[k]) if k >= 35 else 0.0]
            wup[k] = sum(x > 0 for x in v); wdn[k] = sum(x < 0 for x in v)
        s = np.zeros(n); up = np.zeros(n); dn = np.zeros(n); endset = set(ends)
        for k, j in enumerate(ends):                                          # 只喺週尾嗰根 D1 出訊號／判出場
            up[j], dn[j] = wup[k], wdn[k]
            s[j] = 1 if wup[k] >= 4 else (-1 if wdn[k] >= 4 else 0)
        last = 0
        for j in range(n):                                                    # 週中延續上週狀態（入場只喺週尾轉向嗰根）
            if j in endset:
                last = s[j]
            else:
                s[j] = last
        return s, (lambda k, sg: k in endset and (up[k] if sg > 0 else dn[k]) <= 2)
    return flips(d, state, 3.0)


def r1237(d):
    def state(b):
        c = b["c"]; n = len(c); r = np.r_[0, np.diff(np.log(c))]; sc = np.zeros(n)
        for i in range(61, n):
            sd = r[i - 59:i + 1].std()
            sc[i] = (np.log(c[i] / c[i - 60])) / (sd * np.sqrt(60)) if sd > 0 else 0
        s = np.where(sc > 1.0, 1, np.where(sc < -1.0, -1, 0))
        return s, (lambda k, sg: sc[k] * sg < 0.25)
    return flips(d, state, 3.0)


def r1238(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); h, l, c = b["h"], b["l"], b["c"]; sigs = []
    for i in range(61, len(c) - 1):
        if np.isnan(a[i]):
            continue
        sg = 1 if c[i] > c[i - 60:i].max() else (-1 if c[i] < c[i - 60:i].min() else 0)
        if not sg:
            continue
        def ex(k, sg, i=i):
            if sg > 0:
                return c[k] < h[i + 1:k + 1].max() - 3 * a[k]
            return c[k] > l[i + 1:k + 1].min() + 3 * a[k]
        sigs.append((i, sg, 3 * a[i], None, MAXB, ex))
    return M.run_m1(cx, sigs)


def r1239(d):
    def state(b):
        c = b["c"]; n = len(c); er = np.zeros(n); net = np.zeros(n)
        for i in range(20, n):
            net[i] = c[i] - c[i - 20]; vol = np.abs(np.diff(c[i - 20:i + 1])).sum()
            er[i] = abs(net[i]) / vol if vol > 0 else 0
        s = np.zeros(n)
        for i in range(21, n):
            if er[i] >= 0.5 and er[i - 1] < 0.5 and net[i] != 0:
                s[i] = np.sign(net[i])                                        # 只喺效率比由 < 0.5 升上 ≥ 0.5 嗰日出訊號
        return s, (lambda k, sg: er[k] < 0.2 or np.sign(net[k]) != sg)
    return flips(d, state, 2.0)


RULES = [("#1235", "D1 五指標共識", r1235), ("#1236", "週線五指標共識", r1236), ("#1237", "風險調整動量（60 日）", r1237),
         ("#1238", "60 日收市新高＋吊燈式移動止蝕", r1238), ("#1239", "效率比趨勢（20 日）", r1239)]


def stats(tr):
    r = np.array([x[2] for x in tr], float); n = len(r)
    if not n:
        return n, 0.0, 0.0, -1.0
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return n, float(r.mean()), float(w / ls) if ls else 99.0, float(np.mean(sorted(r)[:-3])) if n > 3 else -1.0


def silver_mode(on):
    """白銀：成本 0.03、最低止蝕 0.3×ATR（冇 3 美元下限）。"""
    if on:
        silver_mode.saved = (M.COST, M.Ctx.floor)
        M.COST = 0.03
        M.Ctx.floor = lambda self, ts: (None if self.atr_d.get(int(ts) // 86400) is None else 0.3 * self.atr_d[int(ts) // 86400])
    else:
        M.COST, M.Ctx.floor = silver_mode.saved


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    g05 = HL.h1("xau/sig/duka_h1/", 2005, 2009); s10 = HL.h1("xau/sig/duka_h1_xagusd/", 2010, 2025)
    L = ["# 新方法第一批：B2＋兩個獨立樣本（IDEAS #1235–#1239）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；四關：①②③ 黃金三段 B2；④ 黃金 2005–09（H1）平均 > 0、PF ≥ 1.05、n ≥ 15；⑤ 白銀 2010–25（H1，成本 0.03、最低止蝕 0.3×ATR）平均 > 0、PF ≥ 1.05、n ≥ 30", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | ④ 黃金 2005–09 | ⑤ 白銀 2010–25 | 判 |", "|---|---|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn in RULES:
        cells, ok = [], True
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT["lf"]):
            tr = fn(sets[seg]); n, avg, pf, rob = stats(tr)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2] and rob > 0; extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra}；剔 3 {rob:+.3f} {'✅' if good else '❌'}")
        tr = fn(g05); n, avg, pf, rob = stats(tr); good = n >= 15 and avg > 0 and pf >= 1.05; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        silver_mode(True)
        try:
            tr = fn(s10)
        finally:
            silver_mode(False)
        n, avg, pf, rob = stats(tr); good = n >= 30 and avg > 0 and pf >= 1.05; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- 合格（四關全過）：{'、'.join(passed) if passed else '冇'}（同批 5 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
