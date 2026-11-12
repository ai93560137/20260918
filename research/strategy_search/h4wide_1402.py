"""[IDEAS #1402–#1421] 日線方向＋H4 入場＋放大止賺（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準（跑之前 commit；參數固定）。
用法：python3 research/strategy_search/h4wide_1402.py → research/strategy_search/H4WIDE_1402.md"""
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

OUT = os.path.join(HERE, "H4WIDE_1402.md")
EXITS = (("X1", "TP 5R／120 根", 5.0, 120, False), ("X2", "TP 8R／240 根", 8.0, 240, False), ("X3", "冇 TP，方向變先平", None, None, False),
         ("X4", "冇 TP，穿 20 根低或方向變", None, None, True))
NRAND = 200


class Eng(I.TF):
    def __init__(self, d, st, fl):
        super().__init__(d, 14400, st, fl); t = d["t"]; day = t // 86400
        ud, first = np.unique(day, return_index=True); sd = np.array([st.get(int(x), 0) for x in ud]); n = len(t)
        self.flip = {}
        for sg in (1, -1):                                    # 每日：之後第一個狀態唔係 sg 嘅日子嘅第一根 M1
            f = np.full(len(ud), n); nxt = n
            for k in range(len(ud) - 1, -1, -1):
                f[k] = nxt
                if sd[k] != sg:
                    nxt = first[k]
            self.flip[sg] = f
        self.dix = np.searchsorted(ud, self.b["t"] // 86400)
        c = self.b["c"]; self.trail = {}
        for sg in (1, -1):
            q = sg * c; lo = pd.Series(q).rolling(20).min().shift(1).to_numpy()
            self.trail[sg] = np.flatnonzero(q < lo)             # 收市穿之前 20 根最低收市嘅 K 線

    def go(self, cand, tp_r, mb, trail):
        d, ms, n, t = self.d, self.ms, self.n, self.d["t"]; o, h, l, c = d["o"], d["h"], d["l"], d["c"]; out = []; p = 0
        nxt = ms[np.minimum(cand + 1, n - 1)]
        while p < len(cand):
            i = int(cand[p]); e = i + 1; sg = int(self.st[i]); risk = float(self.risk[i]); s0 = int(ms[e])
            s1 = int(self.flip[sg][self.dix[e]])
            if mb is not None and e + mb < n:
                s1 = min(s1, int(ms[e + mb]))
            if trail:
                j = np.searchsorted(self.trail[sg], e)
                if j < len(self.trail[sg]) and self.trail[sg][j] + 1 < n:
                    s1 = min(s1, int(ms[self.trail[sg][j] + 1]))
            s1 = max(min(s1, len(t)), s0 + 1)
            en = o[s0]; sl = en - sg * risk; tp = None if tp_r is None else en + sg * tp_r * risk
            if sg > 0:
                x = S.first_hit(lambda a, b: (l[a:b] <= sl) | ((h[a:b] >= tp) if tp is not None else False), s0, s1)
            else:
                x = S.first_hit(lambda a, b: (h[a:b] >= sl) | ((l[a:b] <= tp) if tp is not None else False), s0, s1)
            if x is None:
                x = s1 - 1; px = c[x]
            else:
                px = sl if ((l[x] <= sl) if sg > 0 else (h[x] >= sl)) else tp
            out.append((int(t[s0]), int(t[x]), sg, (sg * (px - en) - I.COST) / risk))
            p = int(np.searchsorted(nxt, x, "right"))
        return out


_E = {}


def eng():
    if "e" not in _E:
        d = I.load(); st, fl, bench = I.daily(d); E = Eng(d, st, fl)
        tl = {1: {k: I.trig(k, E.b, E.a) for k in I.KINDS}, -1: {k: I.trig(k, I.neg(E.b), E.a) for k in I.KINDS}}
        _E["e"] = (E, bench, tl)
    return _E["e"]


def work(arg):
    kind, xi = arg; E, bench, tl = eng(); _, _, tp_r, mb, trail = EXITS[xi]; rng = np.random.default_rng(1402 + I.KINDS.index(kind) * 4 + xi)
    cand = np.flatnonzero(E.elig & (((E.st > 0) & tl[1][kind]) | ((E.st < 0) & tl[-1][kind])))
    tr = E.go(cand, tp_r, mb, trail); p = len(cand) / max(int(E.elig.sum()), 1); rm = []
    for _ in range(NRAND):
        rt = E.go(np.flatnonzero(E.elig & (rng.random(E.n) < p)), tp_r, mb, trail); rm.append(float(np.mean([q[3] for q in rt])) if rt else 0.0)
    return kind, xi, tr, rm


def main():
    jobs = [(k, x) for k in I.KINDS for x in range(len(EXITS))]
    with mp.Pool(4) as pool:
        got = pool.map(work, jobs, chunksize=1)
    _, bench, _ = eng(); m0, m1 = I.month(bench[0][0]), I.month(bench[-1][0]); bx = I.monthly(bench, m0, m1); br = bx.sum() / I.dd(bx)
    L = ["# #1402–#1421：日線方向＋H4 入場＋放大止賺", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 Dukascopy M1 2010–2022＋MT5 M1 2023–2026-10；只讀研究，唔改真倉",
         "- **同一批數據喺 #1323–1327 已經睇過 H4 結果（第二次用）→ 合格都只入影子等前向**",
         "- SL＝max(2×ATR14(H4), 3 美元, 0.3×D1 ATR)；每張扣 0.5 美元；逐根 M1 判；一次一張",
         f"- 日線基準（同期）：總 {bx.sum():+.1f}R、每月最大回撤 {I.dd(bx):.1f}R、總 ÷ 回撤 {br:.2f}", "",
         "| # | 入場 | 出場 | 張數 | 勝率 | 平均 R | PF | 2010–14 | 2015–22 | 2023–26 | 多 | 空 | 截距 t | 總 R | 回撤 | 總÷回撤 | 過關 | 隨機平均 | 贏隨機百分位 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    idea = 1402; npass = 0; rows = []
    f = lambda v: float(np.mean(v)) if len(v) else float("nan")  # noqa: E731
    for kind, xi, tr, rm in got:
        r = np.array([q[3] for q in tr]); n = len(r); mean = f(r)
        seg = [f([q[3] for q in tr if I.ts(a) <= q[0] < I.ts(b)]) for _, a, b in I.SEGS]
        lo, sh = f([q[3] for q in tr if q[2] > 0]), f([q[3] for q in tr if q[2] < 0])
        y = I.monthly([(q[1], q[3]) for q in tr], m0, m1); _, beta, t0 = I.alpha_t(y, bx); ratio = y.sum() / I.dd(y) if I.dd(y) > 0 else float("inf")
        g1 = mean > 0 and I.pf(r) >= 1.15 and n >= 100 and all(v > 0 for v in seg); g2 = lo > 0 and sh > 0; g3 = t0 >= 2.0; g4 = ratio > br
        ok = g1 and g2 and g3 and g4; npass += ok; pct = 100.0 * np.mean(np.array(rm) < mean)
        L.append(f"| {idea} | {I.KNAME[kind]} | {EXITS[xi][1]} | {n} | {100 * (r > 0).mean():.0f}% | {mean:+.3f} | {I.pf(r):.2f} | {seg[0]:+.3f} | {seg[1]:+.3f} | {seg[2]:+.3f} | {lo:+.3f} | {sh:+.3f} | "
                 f"{t0:+.2f} | {y.sum():+.1f} | {I.dd(y):.1f} | {ratio:.2f} | {''.join('✓' if g else '✗' for g in (g1, g2, g3, g4))} {'✅' if ok else '❌'} | {np.mean(rm):+.3f} | {pct:.0f} |")
        rows.append((idea, ok, t0, beta)); idea += 1
    L += ["", f"- 過關欄四格＝①賺錢（PF ≥ 1.15、≥ 100 張、三段都正）②多空都正 ③截距 t ≥ 2 ④總÷回撤 > 日線基準。**四關全過：{npass}／20**（關 ③ 單獨撞彩預期約 0.5 條）",
          "- 最後兩欄（隨機入場）只係參考：分清係入場有功定係方向＋出場有功，唔計入合格", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
