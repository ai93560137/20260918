"""[IDEAS #198] 黃金對白銀 β 對沖一長一短：同 #197（pair_multi.py）一模一樣嘅 Q1 價差回歸／Q2 價差趨勢／Q3 對沖黃金趨勢、網格、成本做法、
滾動前向同判斷，只係對手換成 XAGUSD（Dukascopy H1；MT5 對照＝券商黃金＋券商白銀，同 #176）。白銀每腳成本 0.03 美元（同 #176）。
#176 用固定 1:1 名義（ln 金 − ln 銀），今次用過去 250 日 OLS β。用法：python3 research/strategy_search/pair_xag_beta.py → PAIR_XAG_BETA.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pair_multi as PM  # noqa: E402
import pair_xau_xag as PX  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402


def main():
    gd = R.load_duka(); sd = XL.load_xag(); gm = R.load_mt5_spliced(gd); sm = XL.mt5_silver()
    a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
    D = PM.prep(*PX.align(gd, sd)); Dm = PM.prep(*PX.align(gm, sm))
    bp = 0.03 / float(np.nanmedian(D["om"])) * 1e4             # 白銀 0.03 美元 → 按中位價折 bp
    out = ["# 黃金對白銀 β 對沖（IDEAS #198）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；β 中位 {np.nanmedian(D['beta']):+.2f}；白銀成本約 {bp:.1f}bp；正數年只睇最近 10 年", "",
           "| 家族 | 樣本外 | 近 10 年正 | 兩半 | 扣隔夜後 | MT5 | 判 |", "|---|---|---|---|---|---|---|"]
    passed = []
    for fam, grid in PM.FAMILIES.items():
        T = [PM.trades(D, fam, p, bp) for p in grid]; oos, pk = PM.wf(T)
        s = PX.summ([x[2] for x in oos]); sw = PX.summ([x[2] - PM.SWAP_DAY * x[3] for x in oos])
        yy = {}
        for x in oos:
            yy.setdefault(R.yr(x[0]), []).append(x[2])
        p10 = sum(1 for y in PM.Y10 if y in yy and np.sum(yy[y]) > 0)
        h1 = PX.summ([x[2] for x in oos if R.yr(x[0]) <= 2017]); h2 = PX.summ([x[2] for x in oos if R.yr(x[0]) >= 2018])
        rs = []
        for Y in range(2022, 2027):
            g = pk.get(Y)
            if g is not None:
                rs += [x[2] for x in PM.trades(Dm, fam, grid[g], bp) if R.yr(x[0]) == Y and x[0] >= a0]
        smt = PX.summ(rs)
        ok = dict(n=s["n"] >= 80, avg=s["avg"] > 0, pf=s["pf"] >= 1.2, yrs10=p10 >= 6, halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=smt["n"] > 0 and smt["avg"] > 0)
        if all(ok.values()):
            passed.append(fam)
        out.append(f"| {fam} | {PX.fmt(s)} | {p10}/10 | {h1['avg'] * 100:+.2f}%／{h2['avg'] * 100:+.2f}% | {sw['avg'] * 100:+.2f}% | {PX.fmt(smt)} | "
                   f"{'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, PX.fmt(s), p10, PX.fmt(smt), flush=True)
    out += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}；合格只開影子前向，真倉要兩腳落單程式＋使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PAIR_XAG_BETA.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
