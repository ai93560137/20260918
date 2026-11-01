"""[IDEAS #182] XAUUSD H4 指標策略＋隨機基準：#172 嘅八個家族（48 組網格一樣）改喺 H4 K 線計（由 H1 合成、22:00 UTC 對齊），
訊號 H4 收市判、下一根 H4 第一根 H1 開盤入；SL／TP 用 H1 高低（同一根都掂當 SL、跳空用開盤）；TP／SL × H4 ATR20；時間止蝕 20 根 H4（80 小時）；
扣 0.5 美元；一次一張。Dukascopy H1 2005→2026，滾動前向 4 年揀、1 年測（2009→2026）；MT5 2022-10→2026-10 對照。
用法：python3 research/strategy_search/h4_indicators.py → H4_IND.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import m5_indicators as M  # noqa: E402
import robust_long as R  # noqa: E402

Q.T_H = 80


class H4Data(R.Data):
    def __init__(self, *a):
        super().__init__(*a)
        t, h, l, c = self.t, self.h, self.l, self.c
        key = (t + 7200) // 14400
        _, first = np.unique(key, return_index=True)
        last = np.r_[first[1:], len(t)] - 1
        self.dfirst, self.dlast = first, last
        self.dh = np.maximum.reduceat(h, first); self.dl = np.minimum.reduceat(l, first); self.dc = c[last]
        pc = np.r_[self.dc[0], self.dc[:-1]]
        tr = np.maximum.reduce([self.dh - self.dl, np.abs(self.dh - pc), np.abs(self.dl - pc)])
        self.datr = M.rolling(tr, 20, np.mean)


class H4I(Q.DI, H4Data):
    """MRO：H4I → DI → H4Data → Data；DI 嘅指標就喺 H4 K 線上計。"""


def main():
    duka = R.load_duka(); D = H4I(*duka); base = Q.baseline(D)
    Y0, Y1 = R.FIRST_TEST, R.LAST_TEST
    out = ["# XAUUSD H4 指標策略＋隨機基準（IDEAS #182）", "",
           f"- Dukascopy H1→H4 {len(D.dc):,} 根；滾動前向 4 年揀（≥ 20 張、PF ≥ 1.1，揀平均 R 最高）、測 1 年，{Y0}→{Y1}；扣 {R.COST} 美元；時間止蝕 80 小時",
           "", "## 隨機基準（每根 H4 都入、多空各一次）", "", "| 出場（TP／SL × H4 ATR） | 基準勝率 | 基準平均 R |", "|---|---|---|"]
    for e, (tp, sl) in enumerate(Q.EXITS):
        out.append(f"| {tp}／{sl} | {np.mean([v[0] for v in base[e].values()]):.1%} | {np.mean([v[1] for v in base[e].values()]):+.3f} |")
    out += ["", "## 各家族滾動前向（樣本外）", "",
            "| 家族 | 樣本外 | 勝率 | 基準勝率 | 差 | 正數年 | 兩半 | 隔夜息後 | 判 |", "|---|---|---|---|---|---|---|---|---|"]
    trades, picks, verdict = {}, {}, {}
    for fam, grid in Q.FAMILIES.items():
        for gi, p in enumerate(grid):
            trades[(fam, gi)] = Q.run(D, fam, p)
        oos, bw, yrs, pk = [], [], {}, {}
        for Y in range(Y0, Y1 + 1):
            best = None
            for gi in range(len(grid)):
                s = R.summ([x[3] for x in trades[(fam, gi)] if Y - R.TRAIN_Y <= R.yr(x[0]) < Y])
                if s["n"] >= R.MIN_TRAIN_N and s["pf"] >= R.MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                    best = (gi, s["avg"])
            pk[Y] = None if best is None else best[0]
            yt = [] if best is None else [x for x in trades[(fam, best[0])] if R.yr(x[0]) == Y]
            if yt:
                bw += [base[grid[best[0]]["ex"]].get(Y, (np.nan, 0))[0]] * len(yt)
            oos += yt; yrs[Y] = R.summ([x[3] for x in yt])
        picks[fam] = pk
        rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
        win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
        h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
        pos = sum(1 for v in yrs.values() if v["n"] and v["avg"] > 0)
        ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs=pos >= 11,
                  halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = ok
        out.append(f"| {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {pos}/18 | "
                   f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, s["n"], round(s["avg"], 3), flush=True)
    out += ["", "## 全期描述（每家族最好嗰組，唔算數）", ""]
    for fam, grid in Q.FAMILIES.items():
        b_ = max(range(len(grid)), key=lambda g: R.summ([x[3] for x in trades[(fam, g)]])["avg"])
        rs = [x[3] for x in trades[(fam, b_)]]
        out.append(f"- {fam} {grid[b_]}：{R.fmt(R.summ(rs))}，勝率 {np.mean(np.asarray(rs) > 0):.1%}")
    out += ["", "## 券商 MT5 對照（2022-10→2026-10）", ""]
    try:
        Mx = H4I(*R.load_mt5_spliced(duka)); a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp()); cache = {}
        for fam, grid in Q.FAMILIES.items():
            rm = []
            for Y in range(2022, Y1 + 1):
                g = picks[fam][Y]
                if g is None:
                    continue
                if (fam, g) not in cache:
                    cache[(fam, g)] = Q.run(Mx, fam, grid[g])
                rm += [x[3] for x in cache[(fam, g)] if R.yr(x[0]) == Y and x[0] >= a0]
            sm = R.summ(rm); verdict[fam]["mt5"] = sm["n"] > 0 and sm["avg"] > 0
            out.append(f"- {fam}：MT5 {R.fmt(sm)}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}（當未過）")
        for fam in Q.FAMILIES:
            verdict[fam]["mt5"] = False
    passed = [f for f, ok in verdict.items() if all(ok.values())]
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}", "- 合格只開影子前向；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "H4_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:40]))


if __name__ == "__main__":
    main()
