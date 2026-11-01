"""[IDEAS #193] 935 改良版（#189 出場交滾動揀）＋白銀 H4 均線交叉（#191 X1）一齊用，單倉（同 #186）。
成份次序：1 D1 Keltner → 2 D1 SAR → 3 D1 威廉 %R → 4 H4 MACD → 5 H4 SAR（1–5 用 #189 出場揀法）→ 6 星期效應 → 7 白銀 H4 均線交叉（#192 排最後）。
判「比 935 好」（同 #192）：平均 > +0.083R、PF > 1.24、最近 10 年正數年 ≥ 7/10、最大回撤唔差過 −26.6R、MT5 2022-10→ > 0。另列 935、改良版、935＋白銀做對照，同埋按月（平倉月）正數月。
合格都只係提案（真倉要改出場程式＋白銀 K 線，使用者經總指揮批）。用法：python3 research/strategy_search/combo_v2.py → COMBO_V2.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import exits_a as X  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)
XFAM = "X1 白銀均線交叉"


def wf_with_mt5(grid, run_d, run_m):
    T = [run_d(p) for p in grid]
    oos, pk = P.wf_stream(lambda p: T[grid.index(p)], grid)
    cache, mt = {}, []
    for Y, g in pk.items():
        if g is None or Y < 2022:
            continue
        if g not in cache:
            cache[g] = run_m(grid[g])
        mt += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
    return [x for x in oos if R.yr(x[0]) >= 2009], mt


def months(trs, a, b):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if a <= t.year <= b:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    v = list(mm.values())
    return sum(r > 0 for r in v), len(v), (float(np.mean(v)) if v else 0.0)


def main():
    R.COST = 0.5
    gd, sd = R.load_duka(), XL.load_xag(); gm, sm = R.load_mt5_spliced(gd), XL.mt5_silver()
    fr = {"D1": (Q.DI(*gd), Q.DI(*gm)), "H4": (H.H4I(*gd), H.H4I(*gm))}
    ds, picksA = P.streams(gd); ms, _ = P.streams(gm, picksA)
    keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    imp_d, imp_m = dict(ds), dict(msA)
    for name, fam, tf, th in X.COMPS:
        D, Mx = fr[tf]
        grid = [dict(p, xm=m) for p in Q.FAMILIES[fam] for m in X.MODES]
        imp_d[name], imp_m[name] = wf_with_mt5(grid, lambda p, D=D, fam=fam, th=th: X.run(D, fam, p, th), lambda p, Mx=Mx, fam=fam, th=th: X.run(Mx, fam, p, th))
        print(name, flush=True)
    PRd = XL.Pair(H.H4I(*gd), H.H4I(*sd), 14400); PRm = XL.Pair(H.H4I(*gm), H.H4I(*sm), 14400)
    xg = XL.FAMILIES[XFAM]
    x_d, x_m = wf_with_mt5(xg, lambda p: XL.run(PRd, XFAM, p, 80), lambda p: XL.run(PRm, XFAM, p, 80))
    vers = [("935 現行", ds, msA, keys), ("935＋白銀（#192）", {**ds, "X1": x_d}, {**msA, "X1": x_m}, keys + ["X1"]),
            ("改良版（#189）", imp_d, imp_m, keys), ("改良版＋白銀（主判）", {**imp_d, "X1": x_d}, {**imp_m, "X1": x_m}, keys + ["X1"])]
    out = ["# 935 改良版＋白銀 H4 均線交叉（IDEAS #193）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；單倉（同時 1 張）；Dukascopy 2009→2026 樣本外；MT5 2022-10→", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 18 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 全期正數月 | 比 935 好？ |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, d_, m_, kk in vers:
        trs = PS.single(d_, kk); mtr = PS.single(m_, kk)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0)
        a10, n10, mr10 = months(trs, 2017, 2026); aa, na, mra = months(trs, 2009, 2026)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {a10}/{n10}（每月 {mr10:+.2f}R） | {aa}/{na}（{mra:+.2f}R） | "
                   f"{'—' if label.startswith('935 現行') else ('✅ 更好' if better else '❌')} |")
        if "主判" in label:
            out.append("|  ↳ 逐年 | " + "、".join(f"{y} {np.sum(v):+.1f}" for y, v in sorted(yy.items())) + " ||||||||||||||")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 只有「主判」計數；其餘係對照。兩樣改動都係睇完樣本外結果先揀（事後揀選偏差）；合格都只係提案。", ""]
    open(os.path.join(HERE, "COMBO_V2.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
