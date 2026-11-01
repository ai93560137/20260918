"""[IDEAS #206／#207] XAUUSD K 線形態（D1／H4）：
  C1 吞噬：今根實體完全包住上一根相反顏色實體 → 陽吞噬買、陰吞噬沽
  C2 錘頭／射擊之星：下影線 ≥ 全長 2/3 且收市喺上 1/3 → 買；上影線 ≥ 2/3 且收市喺下 1/3 → 沽（全長 ≥ 0.5 × ATR）
  C3 內包線突破：上一根係內包線（高低都喺母線入面），今根收市破母線高 → 買、破低 → 沽
  C4 外包反轉：今根高過上根高、低過上根低，收市喺全長頂 1/4 → 買、底 1/4 → 沽
  網格：filt（SMA200 同向先做）× ex（EXITS 三組）＝ 6；引擎、時間止蝕（D1 480h／H4 80h）、滾動前向、MT5 同 #172／#182。
#206 判同 #191（最近 10 年 ≥ 6/10 等）；8 組，t < 2.5 標弱。#207 候選排喺 935 之後做單倉，判「比 935 好」同 #192；另列近 10 年正數月。只係提案。
用法：python3 research/strategy_search/candle_ind.py → CANDLE_IND.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

GRID = [dict(filt=f, ex=e) for f, e in itertools.product((False, True), range(3))]
FAMILIES = {"C1 吞噬": GRID, "C2 錘頭／射擊之星": GRID, "C3 內包線突破": GRID, "C4 外包反轉": GRID}
TFS = (("D1", 480, Q.DI), ("H4", 80, H.H4I))
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def signals(D, fam, p):
    o, h, l, c = D.do, D.dh, D.dl, D.dc
    po, ph, pl, pc = (np.r_[np.nan, a[:-1]] for a in (o, h, l, c))
    rng = h - l; key = fam[:2]
    with np.errstate(invalid="ignore", divide="ignore"):
        if key == "C1":
            b = (c > o) & (pc < po) & (c >= po) & (o <= pc)
            x = (c < o) & (pc > po) & (c <= po) & (o >= pc)
        elif key == "C2":
            lw = np.minimum(o, c) - l; uw = h - np.maximum(o, c); big = rng >= 0.5 * D.datr
            b = big & (lw >= 2 / 3 * rng) & (c >= l + 2 / 3 * rng)
            x = big & (uw >= 2 / 3 * rng) & (c <= l + 1 / 3 * rng)
        elif key == "C3":
            inside = (h <= np.r_[np.nan, h[:-1]]) & (l >= np.r_[np.nan, l[:-1]])
            ins_prev = np.r_[False, inside[:-1]]
            mh, ml = np.r_[np.nan, np.nan, h[:-2]], np.r_[np.nan, np.nan, l[:-2]]
            b = ins_prev & (c > mh); x = ins_prev & (c < ml)
        else:
            out = (h > ph) & (l < pl)
            b = out & (c >= h - 0.25 * rng); x = out & (c <= l + 0.25 * rng)
    if p["filt"]:
        b &= c > D.s200; x &= c < D.s200
    return np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)


def run(D, fam, p, th):
    b, x = signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th)
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    return R.simulate(D, ent)


def months(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if 2017 <= t.year <= 2026:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return sum(v > 0 for v in mm.values()), len(mm)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    out = ["# XAUUSD K 線形態（IDEAS #206）＋加入 935（#207）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；正數年只睇最近 10 年", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 近 10 年正數月 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tf, th, cls in TFS:
        D, Mx = cls(*gd), cls(*gm); Q.T_H = th; base = Q.baseline(D)
        for fam, grid in FAMILIES.items():
            T = [run(D, fam, p, th) for p in grid]
            oos, picks = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
            oos = [x for x in oos if R.yr(x[0]) >= 2009]
            bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
            rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
            win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
            p10, _ = XL.pos10(oos); pm, nm = months(oos)
            h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
            mtr, cache = [], {}
            for Y, g in picks.items():
                if g is None or Y < 2022:
                    continue
                if g not in cache:
                    cache[g] = run(Mx, fam, grid[g], th)
                mtr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
            sm = R.summ([x[3] for x in mtr])
            ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs10=p10 >= 6,
                      halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=sm["n"] > 0 and sm["avg"] > 0)
            near = s["avg"] >= 0.05 and s["pf"] >= 1.15 and p10 >= 6 and sm["n"] > 0 and sm["avg"] > 0
            name = f"{tf} {fam}"; res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=s, picks=picks, grid=grid)
            v = ("✅" + ("（弱，t < 2.5）" if s["t"] < 2.5 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {p10}/10 | {pm}/{nm} | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {sm['n']} 張 {sm['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), p10, sm["n"], round(sm["avg"], 3), flush=True)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #206 合格：{'、'.join(passed) if passed else '冇'}", f"- #207 候選：{'、'.join(cands) if cands else '冇'}", "", "## #207 935 單倉＋候選", ""]
    if cands:
        ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
        out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 近 10 年正數月 | MT5 | 最大回撤 R | 每張 1%（30,000） | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        variants = [("935 現行", []), ("935＋全部候選", cands)] + ([(f"935＋{c}", [c]) for c in cands] if len(cands) > 1 else [])
        for label, add in variants:
            dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
            for c in add:
                dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
            kk = keys + add; trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
            ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs); pm, nm = months(trs)
            eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
            e1, m1, _, _ = P.equity(trs, 30000, 1.0)
            better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
            out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pm}/{nm} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | "
                       f"{'—' if not add else ('✅ 更好' if better else '❌')} |")
    else:
        out.append("- 冇候選，935 維持現行。")
    out += ["", "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "CANDLE_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
