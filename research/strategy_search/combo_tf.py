"""[IDEAS #174] #173 嘅 A／B／C 三種合法搬去細時框（M1，M5 對照）：指標（Keltner 20／2×ATR、拋物線 SAR、威廉 %R 14、SMA200、ATR20）
全部喺嗰個時框嘅 K 線計，訊號喺收市判、下一根開盤入，TP 4／SL 2 × 該時框 ATR20，時間止蝕 20 根；同一根都掂當 SL、跳空用開盤；一次一張。
數據＝券商 MT5 M1 2022-08→2026-10（細時框冇 22 年數據，所以只係描述，唔可以判合格）。成本 0.5 美元同 0 兩種都列。
用法：python3 research/strategy_search/combo_tf.py → COMBO_TF.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import g7_long as G  # noqa: E402
import m5_indicators as M  # noqa: E402
import robust_long as R  # noqa: E402
import search as S  # noqa: E402

TP, SL, NBARS = 4.0, 2.0, 20


class Bars:
    def __init__(self, d, sec):
        key = d["t"] // sec * sec
        ks, first = np.unique(key, return_index=True)
        last = np.r_[first[1:], len(key)] - 1
        self.t = ks; self.o = d["o"][first]; self.h = np.maximum.reduceat(d["h"], first)
        self.l = np.minimum.reduceat(d["l"], first); self.c = d["c"][last]; self.sec = sec
        h, l, c = self.h, self.l, self.c
        self.dc, self.dfirst = c, np.arange(len(c))
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        self.datr = M.rolling(tr, 20, np.mean)
        self.s200 = M.rolling(c, 200, np.mean)
        e20 = G.ema(c, 20); self.ku, self.kl = e20 + 2 * self.datr, e20 - 2 * self.datr
        self.sar, self.sar_up = Q.psar(h, l)
        hh, ll = M.rolling(h, 14, np.max), M.rolling(l, 14, np.min)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.wr = -100 * (hh - c) / (hh - ll)


def ents(B, b, x):
    mh = NBARS * B.sec / 3600
    return [(d + 1, 1 if b[d] else -1, SL * B.datr[d], TP * B.datr[d], mh)
            for d in np.flatnonzero(b | x) if 210 <= d < len(B.c) - 1 and B.datr[d] > 0]


def combo(B, mode):
    b5, x5 = Q.signals(B, "J5", dict(ex=2)); b7, x7 = Q.signals(B, "J7", dict(filt=True, ex=2)); b8, x8 = Q.signals(B, "J8", dict(th=20, filt=True, ex=2))
    if mode == "A":
        tr = []
        for b, x in ((b5, x5), (b7, x7), (b8, x8)):
            tr += R.simulate(B, ents(B, b, x))
        return sorted(tr)
    if mode == "B":
        tu, td = B.c > B.s200, B.c < B.s200
        return R.simulate(B, ents(B, b5 & B.sar_up & tu, x5 & ~B.sar_up & td))
    win = lambda a: a | np.r_[False, a[:-1]] | np.r_[False, False, a[:-2]]   # noqa: E731
    vb = win(b5).astype(int) + win(b7) + win(b8); vs = win(x5).astype(int) + win(x7) + win(x8)
    return R.simulate(B, ents(B, (vb >= 2) & (b5 | b7 | b8) & (vs < 2), (vs >= 2) & (x5 | x7 | x8) & (vb < 2)))


def desc(tr):
    rs = np.array([x[3] for x in tr]); s = R.summ(rs)
    if not len(rs):
        return "0 張"
    yy = {}
    for x in tr:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    return (f"{s['n']} 張 勝率 {np.mean(rs > 0):.1%} 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {rs.sum():+.0f}；"
            f"逐年 " + "、".join(f"{y} {np.mean(v):+.3f}" for y, v in sorted(yy.items())))


def main():
    m1 = S.load("mt5", "2022-08-03", "2026-10-30")
    out = ["# A／B／C 搬去細時框（IDEAS #174，描述）", "",
           "- 券商 MT5 2022-08→2026-10；指標同 #173 一樣但喺細時框計；TP 4／SL 2 × 該時框 ATR20、20 根時間止蝕", ""]
    for name, sec in (("M1", 60), ("M5", 300)):
        B = Bars(m1, sec)
        out += [f"## {name}（{len(B.c):,} 根）", "", "| 合法 | 成本 0.5 美元 | 成本 0 |", "|---|---|---|"]
        for m, lab in (("A", "A 組合"), ("B", "B 確認"), ("C", "C 投票")):
            R.COST = 0.5; t1 = combo(B, m)
            R.COST = 0.0; t0 = combo(B, m)
            out.append(f"| {lab} | {desc(t1)} | {desc(t0)} |")
            print(name, lab, desc(t1), flush=True)
        out.append("")
    open(os.path.join(HERE, "COMBO_TF.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
