"""[IDEAS #1362–#1381] 日線方向＋細止賺大止蝕：換入場點（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準（跑之前 commit；參數固定）。
出場固定：TP 0.20×D1 ATR、SL 2×D1 ATR、方向變就平（#1358 嗰組）。對照：同窗口隨機入場 200 次＋日線基準。
用法：python3 research/strategy_search/entry_1362.py → research/strategy_search/ENTRY_1362.md"""
import datetime as dt
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intraday_1323 as I  # noqa: E402
import scalp_1353 as S     # noqa: E402

B = I.B
OUT = os.path.join(HERE, "ENTRY_1362.md")
TP_K, SL_K, NRAND = 0.20, 2.0, 200


class Eng:
    def __init__(self, d, st, fl):
        self.d = d; t = d["t"]; day = t // 86400
        self.ud, self.first = np.unique(day, return_index=True)
        self.sd = np.array([st.get(int(x), 0) for x in self.ud]); self.ad = np.array([fl.get(int(x), np.nan) for x in self.ud])
        self.di = np.searchsorted(self.ud, day); sod = t % 86400
        self.sm = self.sd[self.di]; self.am = self.ad[self.di]
        self.elig = (self.sm != 0) & ~np.isnan(self.am) & (sod >= 7 * 3600) & (sod < 20 * 3600)
        self.bars = {}

    def tf(self, sec):
        if sec not in self.bars:
            b = B.resample(self.d, sec); ms = np.searchsorted(self.d["t"], b["t"]); nx = np.r_[ms[1:], len(self.d["t"]) - 1]
            self.bars[sec] = (b, nx)
        return self.bars[sec]

    def cands(self, sec, fn):
        """fn(q, A)＝做多視角觸發（布林陣列）；回傳合資格嘅入場 M1 位置。"""
        b, nx = self.tf(sec); A = self.ad[np.searchsorted(self.ud, b["t"] // 86400)]
        out = []
        for sg, q in ((1, b), (-1, I.neg(b))):
            e = nx[np.flatnonzero(fn(q, A))]; out.append(e[self.elig[e] & (self.sm[e] == sg)])
        return np.unique(np.concatenate(out))

    def run(self, cand, tp_k=TP_K, sl_k=SL_K):
        d = self.d; t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]; n = len(t); out = []; p = 0
        while p < len(cand):
            s0 = int(cand[p]); di = int(self.di[s0]); sg = int(self.sd[di]); a = self.ad[di]; k = di + 1
            while k < len(self.ud) and self.sd[k] == sg:
                k += 1
            s1 = int(self.first[k]) if k < len(self.ud) else n
            en = o[s0]; tp = en + sg * tp_k * a; sl = en - sg * sl_k * a
            if sg > 0:
                x = S.first_hit(lambda i, j: (h[i:j] >= tp) | (l[i:j] <= sl), s0, s1)
            else:
                x = S.first_hit(lambda i, j: (l[i:j] <= tp) | (h[i:j] >= sl), s0, s1)
            if x is None:
                x = min(s1, n - 1); px = o[x] if s1 < n else c[x]
            else:
                px = sl if ((l[x] <= sl) if sg > 0 else (h[x] >= sl)) else tp
            out.append((int(t[s0]), int(t[x]), sg, (sg * (px - en) - I.COST) / a))
            p = int(np.searchsorted(cand, x, "right"))
        return out


def cdown(x, y):
    return I.crossup(-np.asarray(x, float), -np.asarray(y, float))


def dayfeat(q):
    day = pd.Series(q["t"] // 86400); h = pd.Series(q["h"]); sod = q["t"] % 86400
    hi = h.groupby(day).cummax().to_numpy(); op = pd.Series(q["o"]).groupby(day).transform("first").to_numpy()
    dl = pd.Series(q["l"]).groupby(day).min(); dh = h.groupby(day).max()
    pl = day.map(dl.shift(1)).to_numpy(); ph = day.map(dh.shift(1)).to_numpy()
    ah = day.map(h[sod < 7 * 3600].groupby(day[sod < 7 * 3600]).max()).to_numpy()
    return hi, op, pl, ph, ah, sod


def hour(hh):
    return lambda q, A: (q["t"] % 86400 == hh * 3600 - 60)          # 喺 M1 上：前一根 M1 收市 → 正點嗰根開市入


def pull(k):
    return lambda q, A: cdown(q["c"], dayfeat(q)[0] - k * A)


def bb_low(q, A):
    c = pd.Series(q["c"]); return cdown(q["c"], (c.rolling(20).mean() - 2 * c.rolling(20).std(ddof=0)).to_numpy())


def down3(q, A):
    c = q["c"]; dn = np.r_[False, np.diff(c) < 0]; out = np.zeros(len(c), bool); out[3:] = dn[3:] & dn[2:-1] & dn[1:-2] & ~dn[:-3]
    return out


def surge(k):
    def f(q, A):
        a = I.atr(q); out = np.zeros(len(a), bool); out[1:] = (q["c"][1:] - q["c"][:-1]) >= k * a[:-1]; return out
    return f


def asia(q, A):
    f = dayfeat(q); return I.crossup(q["c"], f[4]) & (f[5] >= 7 * 3600)


RULES = [
    (1362, "時段", "07:00 UTC 入", 60, hour(7)), (1363, "時段", "09:00 UTC 入", 60, hour(9)), (1364, "時段", "13:00 UTC 入", 60, hour(13)),
    (1365, "時段", "15:00 UTC 入", 60, hour(15)), (1366, "時段", "19:00 UTC 入", 60, hour(19)),
    (1367, "回調", "由當日高位回落 ≥ 0.3A（M5）", 300, pull(0.3)), (1368, "回調", "由當日高位回落 ≥ 0.5A（M5）", 300, pull(0.5)),
    (1369, "回調", "由當日高位回落 ≥ 1.0A（M5）", 300, pull(1.0)),
    (1370, "回調", "收市跌穿前一日低位（M5）", 300, lambda q, A: cdown(q["c"], dayfeat(q)[2])),
    (1371, "回調", "收市跌穿當日開市 − 0.5A（M5）", 300, lambda q, A: cdown(q["c"], dayfeat(q)[1] - 0.5 * A)),
    (1372, "超賣", "M5 RSI(2) 跌穿 5", 300, lambda q, A: cdown(I.rsi(q["c"], 2), np.full(len(q["c"]), 5.0))),
    (1373, "超賣", "H1 RSI(2) 跌穿 10", 3600, lambda q, A: cdown(I.rsi(q["c"], 2), np.full(len(q["c"]), 10.0))),
    (1374, "超賣", "H1 連跌三根", 3600, down3), (1375, "超賣", "M15 跌穿布林下軌", 900, bb_low),
    (1376, "超賣", "H1 跌穿 SMA20 − 1×ATR", 3600, lambda q, A: cdown(q["c"], I.sma(q["c"], 20) - I.atr(q))),
    (1377, "動力", "H1 升穿 24 根高位", 3600, lambda q, A: I.crossup(q["c"], pd.Series(q["h"]).rolling(24).max().shift(1).to_numpy())),
    (1378, "動力", "M15 單根升 ≥ 2×ATR", 900, surge(2.0)),
    (1379, "動力", "收市升穿前一日高位（M5）", 300, lambda q, A: I.crossup(q["c"], dayfeat(q)[3])),
    (1380, "動力", "收市升穿亞洲時段高位（M5）", 300, asia),
    (1381, "動力", "H4 升穿 SMA20", 14400, lambda q, A: I.crossup(q["c"], I.sma(q["c"], 20))),
]
_E = {}


def eng():
    if "e" not in _E:
        d = I.load(); st, fl, bench = I.daily(d); _E["e"] = (Eng(d, st, fl), bench)
    return _E["e"]


def work(k):
    E, bench = eng(); idea, cat, name, sec, fn = RULES[k]; rng = np.random.default_rng(idea)
    cand = E.cands(sec, fn); tr = E.run(cand); n = len(tr); mean = float(np.mean([q[3] for q in tr])) if tr else 0.0
    pool = np.flatnonzero(E.elig & (E.d["t"] % 300 == 0)); rm = []
    for _ in range(NRAND):
        rt = E.run(np.sort(rng.choice(pool, size=min(max(n, 1), len(pool)), replace=False)))
        rm.append(float(np.mean([q[3] for q in rt])))
    print(idea, name, n, f"{mean:+.4f}", f"rand {np.mean(rm):+.4f}", flush=True)
    return idea, cat, name, tr, rm, len(cand)


def main(rules=None, out=OUT, title="# #1362–#1381：日線方向＋細止賺大止蝕——換入場點"):
    global RULES
    if rules is not None:
        RULES = rules
    with mp.Pool(4) as pool:
        got = pool.map(work, range(len(RULES)), chunksize=1)
    _, bench = eng(); m0, m1 = I.month(bench[0][0]), I.month(bench[-1][0]); bx = I.monthly(bench, m0, m1) * 3; br = bx.sum() / I.dd(bx)
    L = [title, "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 Dukascopy M1 2010–2022＋MT5 M1 2023–2026-10；只讀研究，唔改真倉",
         f"- 出場固定：TP {TP_K}×D1 ATR、SL {SL_K:.0f}×D1 ATR、方向變就平；每張扣 0.5 美元；損益單位＝D1 ATR 倍數。**呢組出場係 #1353–1361 九組入面最唔差嗰個（事後揀）**",
         f"- 日線基準（同期）：總 {bx.sum():+.1f} ATR、每月最大回撤 {I.dd(bx):.1f} ATR、總 ÷ 回撤 {br:.2f}", "",
         "| # | 類 | 入場 | 張數 | 勝率 | 每張平均 | 2010–14 | 2015–22 | 2023–26 | 多 | 空 | 隨機平均 | 贏隨機百分位 | 截距 t | 總 | 回撤 | 總÷回撤 | 過關 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    npass = n2 = 0
    for idea, cat, name, tr, rm, nc in got:
        r = np.array([q[3] for q in tr]); n = len(r)
        f = lambda v: float(np.mean(v)) if len(v) else float("nan")  # noqa: E731
        seg = [f([q[3] for q in tr if I.ts(a) <= q[0] < I.ts(b)]) for _, a, b in I.SEGS]
        lo, sh = f([q[3] for q in tr if q[2] > 0]), f([q[3] for q in tr if q[2] < 0]); mean = f(r)
        pct = 100.0 * np.mean(np.array(rm) < mean); y = I.monthly([(q[1], q[3]) for q in tr], m0, m1); _, _, t0 = I.alpha_t(y, bx)
        ratio = y.sum() / I.dd(y) if I.dd(y) > 0 else float("inf")
        g1 = mean > 0 and n >= 100 and all(v > 0 for v in seg) and lo > 0 and sh > 0; g2 = pct >= 95; g3 = t0 >= 2.0; g4 = ratio > br
        ok = g1 and g2 and g3 and g4; npass += ok; n2 += g2
        L.append(f"| {idea} | {cat} | {name} | {n} | {100 * (r > 0).mean():.1f}% | {mean:+.4f} | {seg[0]:+.4f} | {seg[1]:+.4f} | {seg[2]:+.4f} | {lo:+.4f} | {sh:+.4f} | {np.mean(rm):+.4f} | {pct:.0f} | "
                 f"{t0:+.2f} | {y.sum():+.1f} | {I.dd(y):.1f} | {ratio:.2f} | {''.join('✓' if g else '✗' for g in (g1, g2, g3, g4))} {'✅' if ok else '❌'} |")
    L += ["", f"- 過關欄四格＝①平均、三段、多空全部正（≥ 100 張）②贏隨機 ≥ 95 ③截距 t ≥ 2 ④總÷回撤 > 日線基準。**四關全過：{npass}／{len(RULES)}**；單睇關 ② 過 {n2} 條（撞彩預期約 {len(RULES) * 0.05:.0f} 條）", ""]
    open(out, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
