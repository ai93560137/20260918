"""[IDEAS #175] B 確認（Keltner 突破＋拋物線 SAR 同方向＋收市喺 SMA200 同邊）原封不動搬去 H4／H8／H12（由 H1 合成，22:00 UTC 對齊），
TP 4／SL 2 × 該時框 ATR20、20 根時間止蝕、下一根開盤入、同一根都掂當 SL、一次一張。主判＝白銀 Dukascopy 2005→2026（扣 0.03 美元）；
黃金（扣 0.5 美元）只作描述；另列日線黃金＋白銀合併。用法：python3 research/strategy_search/b_tf.py → B_TF.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import combo_tf as CT  # noqa: E402
import d1_combo as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import robust_long as R  # noqa: E402
import silver_friday as F  # noqa: E402

TFS = (("H4", 4), ("H8", 8), ("H12", 12))


class TFBars(CT.Bars):
    def __init__(self, arr, hours):
        t, o, h, l, c = arr
        sec = hours * 3600
        t2 = (t + 7200) // sec * sec - 7200                    # 22:00 UTC 對齊
        super().__init__({"t": t2, "o": o, "h": h, "l": l, "c": c}, 1)
        self.sec = sec
        # 執行用返 H1（SL／TP 喺 H1 高低判）
        self.t, self.o, self.h, self.l, self.c = t, o, h, l, c
        ks, first = np.unique(t2, return_index=True)
        self.bar_first = first


def b_trades(Bx):
    b5, x5 = Q.signals(Bx, "J5", dict(ex=2))
    tu, td = Bx.dc > Bx.s200, Bx.dc < Bx.s200
    b, x = b5 & Bx.sar_up & tu, x5 & ~Bx.sar_up & td
    mh = CT.NBARS * Bx.sec / 3600
    nb = len(Bx.dc)
    ent = [(int(Bx.bar_first[d + 1]), 1 if b[d] else -1, CT.SL * Bx.datr[d], CT.TP * Bx.datr[d], mh)
           for d in np.flatnonzero(b | x) if 210 <= d < nb - 1 and Bx.datr[d] > 0]
    return R.simulate(Bx, ent), mh


def base_win(Bx, mh):
    yy = {}; nb = len(Bx.dc)
    for s in (1, -1):
        ent = [(int(Bx.bar_first[d + 1]), s, CT.SL * Bx.datr[d], CT.TP * Bx.datr[d], mh) for d in range(210, nb - 1) if Bx.datr[d] > 0]
        for t_ in R.simulate(Bx, ent):
            yy.setdefault(R.yr(t_[0]), []).append(t_[3] > 0)
    return {y: float(np.mean(v)) for y, v in yy.items()}


def judge(tr, bw):
    ok, txt, yy = C.judge(tr, bw)
    ok["n"] = len(tr) >= 200
    return ok, txt


def main():
    out = ["# B 確認搬去 H4／H8／H12（IDEAS #175）", "",
           "- 規則同 #173 B 一樣，只係改時框；TP 4／SL 2 × 該時框 ATR20、20 根時間止蝕；主判白銀（未見）、黃金描述", ""]
    silver = F.load("xau/sig/duka_h1_xagusd/"); gold = R.load_duka()
    out += ["## 白銀（主判，扣 0.03 美元）", "", "| 時框 | 結果 | 判 |", "|---|---|---|"]
    passed = []
    for name, hrs in TFS:
        R.COST = 0.03
        Bx = TFBars(silver, hrs); tr, mh = b_trades(Bx); ok, txt = judge(tr, base_win(Bx, mh))
        if all(ok.values()):
            passed.append(name)
        out.append(f"| {name} | {txt} | {'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print("白銀", name, txt, flush=True)
    out += ["", "## 黃金（描述，扣 0.5 美元）", ""]
    for name, hrs in TFS:
        R.COST = 0.5
        Bx = TFBars(gold, hrs); tr, mh = b_trades(Bx); _, txt = judge(tr, base_win(Bx, mh))
        out.append(f"- {name}：{txt}")
        print("黃金", name, txt, flush=True)
    # 日線黃金＋白銀合併
    R.COST = 0.5; tg = C.combo(Q.DI(*gold), "B")
    R.COST = 0.03; ts = C.combo(Q.DI(*silver), "B")
    allr = [x[3] for x in tg] + [x[3] for x in ts]
    out += ["", "## 日線 B：黃金＋白銀一齊做（描述）", "", f"- {R.fmt(R.summ(allr))}，約每年 {len(allr) / 21.8:.1f} 張", "",
            "## 判", "", f"- 白銀合格嘅時框：{'、'.join(passed) if passed else '冇'}",
            "- 合格只升做影子前向候選；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "B_TF.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
