"""[IDEAS #204／#205] XAUUSD H8／H12 指標策略：#172 嘅 J1–J8（網格同 #172）改喺 H8（22:00／06:00／14:00 UTC 對齊）同 H12（22:00／10:00）計；
時間止蝕 20 根（H8 160h、H12 240h）；引擎、滾動前向、MT5 對照同 #182。
#204 判（同 #191，正數年只睇最近 10 年）：≥ 200 張、勝率高過基準 ≥ 2pp、平均 ≥ +0.05R、最近 10 年 ≥ 6/10、兩半、隔夜息後、MT5 > 0；16 組，t < 2.5 標弱。
#205 候選（平均 ≥ +0.05R、PF ≥ 1.15、最近 10 年 ≥ 6/10、MT5 > 0）排喺 935 六個成份之後做單倉；判「比 935 好」同 #192。只係提案。
用法：python3 research/strategy_search/h8h12_ind.py → H8H12_IND.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import m5_indicators as M  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def make(period):
    class PD(R.Data):
        def __init__(self, *a):
            super().__init__(*a)
            t, h, l, c = self.t, self.h, self.l, self.c
            _, first = np.unique((t + 7200) // period, return_index=True)
            last = np.r_[first[1:], len(t)] - 1
            self.dfirst, self.dlast = first, last
            self.dh = np.maximum.reduceat(h, first); self.dl = np.minimum.reduceat(l, first); self.dc = c[last]
            pc = np.r_[self.dc[0], self.dc[:-1]]
            tr = np.maximum.reduce([self.dh - self.dl, np.abs(self.dh - pc), np.abs(self.dl - pc)])
            self.datr = M.rolling(tr, 20, np.mean)

    class PI(Q.DI, PD):
        pass
    return PI


TFS = (("H8", 160, make(28800)), ("H12", 240, make(43200)))


def run(D, fam, p, th):
    b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th)
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    return R.simulate(D, ent)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    out = ["# XAUUSD H8／H12 指標策略（IDEAS #204）＋加入 935（#205）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；正數年只睇最近 10 年", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tf, th, cls in TFS:
        D, Mx = cls(*gd), cls(*gm); Q.T_H = th; base = Q.baseline(D)
        for fam, grid in Q.FAMILIES.items():
            T = [run(D, fam, p, th) for p in grid]
            oos, picks = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
            oos = [x for x in oos if R.yr(x[0]) >= 2009]
            bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
            rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
            win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
            p10, _ = XL.pos10(oos)
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
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {p10}/10 | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {sm['n']} 張 {sm['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), p10, sm["n"], round(sm["avg"], 3), flush=True)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #204 合格：{'、'.join(passed) if passed else '冇'}", f"- #205 候選：{'、'.join(cands) if cands else '冇'}", "", "## #205 935 單倉＋候選", ""]
    if cands:
        ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
        out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | MT5 | 最大回撤 R | 每張 1%（30,000） | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|"]
        variants = [("935 現行", []), ("935＋全部候選", cands)] + ([(f"935＋{c}", [c]) for c in cands] if len(cands) > 1 else [])
        for label, add in variants:
            dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
            for c in add:
                dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
            kk = keys + add; trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
            ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs)
            eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
            e1, m1, _, _ = P.equity(trs, 30000, 1.0)
            better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
            out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | "
                       f"{'—' if not add else ('✅ 更好' if better else '❌')} |")
    else:
        out.append("- 冇候選，935 維持現行。")
    out += ["", "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "H8H12_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
