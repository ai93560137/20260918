"""[IDEAS #213] XAUUSD 波幅收縮突破（D1／H4）＋加入 A+ 單倉：
  V1 NR7 突破：上一根係 7 根入面波幅最窄，今根收市破上一根高 → 買、破低 → 沽
  V2 NR4 內包線突破：上一根係 NR4 兼內包線，今根收市破上一根高／低
  V3 ATR 收縮：ATR5 ÷ ATR50 喺過去 250 根最低 10%（上一根），今根收市破 20 根唐奇安（唔計今根）高／低
  V4 保力加收窄：上一根保力加 (20,2) 闊度係 120 根最低，今根收市出上軌 → 買、出下軌 → 沽
  網格同 #206：filt（SMA200 同向）× ex（EXITS 三組）＝ 6；引擎、時間止蝕（D1 480h／H4 80h）、滾動前向 4 年揀 1 年測、MT5 2022-10→ 同 #206。
判（預先登記）：每組同 #206（≥ 200 張、勝率高過基準 ≥ 2pp、平均 ≥ +0.05R、最近 10 年 ≥ 6/10、兩半、隔夜息後、MT5 > 0；8 組同時測，t < 2.5 標弱）；
候選（平均 ≥ +0.05、PF ≥ 1.15、近 10 年 ≥ 6/10、MT5 > 0）排喺 A+ 七個成份之後做單倉，「比 A+ 好」＝平均 > +0.101R、PF > 1.30、近 10 年正 ≥ 7/10、回撤唔差過 −25.7R、MT5 > 0。只係提案。
用法：python3 research/strategy_search/vol_ind.py → VOL_IND.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candle_ind as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

FAMILIES = {"V1 NR7 突破": C.GRID, "V2 NR4 內包線突破": C.GRID, "V3 ATR 收縮突破": C.GRID, "V4 保力加收窄突破": C.GRID}
APLUS = dict(avg=0.101, pf=1.30, yrs10=7, dd=-25.7)


def _roll(a, n, f):
    out = np.full(len(a), np.nan)
    for i in range(n - 1, len(a)):
        out[i] = f(a[i - n + 1:i + 1])
    return out


def signals(D, fam, p):
    h, l, c = D.dh, D.dl, D.dc
    rng = h - l; key = fam[:2]
    ph, pl = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        if key == "V1":
            nr = rng <= _roll(rng, 7, np.min)
            prev = np.r_[False, nr[:-1]]
            b = prev & (c > ph); x = prev & (c < pl)
        elif key == "V2":
            nr4 = rng <= _roll(rng, 4, np.min)
            inside = (h <= ph) & (l >= pl)
            prev = np.r_[False, (nr4 & inside)[:-1]]
            b = prev & (c > ph); x = prev & (c < pl)
        elif key == "V3":
            pc = np.r_[c[0], c[:-1]]
            tr = np.maximum.reduce([rng, np.abs(h - pc), np.abs(l - pc)])
            ratio = _roll(tr, 5, np.mean) / _roll(tr, 50, np.mean)
            q10 = _roll(ratio, 250, lambda w: np.nanpercentile(w, 10))
            sq = np.r_[False, (ratio <= q10)[:-1]]
            dh20 = np.r_[np.nan, _roll(h, 20, np.max)[:-1]]; dl20 = np.r_[np.nan, _roll(l, 20, np.min)[:-1]]
            b = sq & (c > dh20); x = sq & (c < dl20)
        else:
            bw = (D.bu - D.bl)
            low = bw <= _roll(bw, 120, np.min)
            prev = np.r_[False, low[:-1]]
            b = prev & (c > D.bu); x = prev & (c < D.bl)
    if p["filt"]:
        b &= c > D.s200; x &= c < D.s200
    b, x = np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)
    both = b & x
    return b & ~both, x & ~both


def main():
    C.FAMILIES = FAMILIES; C.signals = signals
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    out = ["# XAUUSD 波幅收縮突破（IDEAS #213）＋加入 A+", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；正數年只睇最近 10 年；8 組同時測", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 近 10 年正數月 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}

    def wf_family(D, Mx, fam, grid, th, sig):
        C.signals = sig
        T = [C.run(D, fam, p, th) for p in grid]
        oos, picks = P.wf_stream(lambda p, T=T: T[grid.index(p)], grid)
        oos = [x for x in oos if R.yr(x[0]) >= 2009]
        mtr, cache = [], {}
        for Y, g in picks.items():
            if g is None or Y < 2022:
                continue
            if g not in cache:
                cache[g] = C.run(Mx, fam, grid[g], th)
            mtr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
        return oos, mtr, picks

    for tf, th, cls in C.TFS:
        D, Mx = cls(*gd), cls(*gm); Q.T_H = th; base = Q.baseline(D)
        for fam, grid in FAMILIES.items():
            oos, mtr, picks = wf_family(D, Mx, fam, grid, th, signals)
            bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
            rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
            win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
            p10, _ = XL.pos10(oos); pm, nm = C.months(oos)
            h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
            sm = R.summ([x[3] for x in mtr])
            ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs10=p10 >= 6,
                      halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=sm["n"] > 0 and sm["avg"] > 0)
            near = s["n"] > 0 and s["avg"] >= 0.05 and s["pf"] >= 1.15 and p10 >= 6 and sm["n"] > 0 and sm["avg"] > 0
            name = f"{tf} {fam}"; res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=s, picks=picks, grid=grid)
            v = ("✅" + ("（弱，t < 2.5）" if s["t"] < 2.5 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {p10}/10 | {pm}/{nm} | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {sm['n']} 張 {sm['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), p10, sm["n"], round(sm["avg"], 3), flush=True)
    # A+ 第 7 成份：D1 內包線突破（#207，同真倉一樣滾動揀）
    D1, M1 = Q.DI(*gd), Q.DI(*gm); Q.T_H = 480
    c3_oos, c3_mt, _ = wf_family(D1, M1, "C3 內包線突破", C.GRID, 480, C.__dict__["_orig_signals"])
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #213 合格：{'、'.join(passed) if passed else '冇'}", f"- 候選：{'、'.join(cands) if cands else '冇'}", "", "## A+ 單倉＋候選", ""]
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    ds["C3"] = c3_oos; ms["C3"] = c3_mt; keys = keys + ["C3"]
    out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 近 10 年正數月 | MT5 | 最大回撤 R | 比 A+ 好？ |", "|---|---|---|---|---|---|---|---|---|---|"]
    variants = [("A+ 現行", [])] + ([("A+＋全部候選", cands)] if cands else []) + ([(f"A+＋{c}", [c]) for c in cands] if len(cands) > 1 else [])
    for label, add in variants:
        dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
        for c in add:
            dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
        kk = keys + add; trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs); pm, nm = C.months(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        better = s["avg"] > APLUS["avg"] and s["pf"] > APLUS["pf"] and p10 >= APLUS["yrs10"] and dd >= APLUS["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pm}/{nm} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{'—' if not add else ('✅ 更好' if better else '❌')} |")
        print(label, s["n"], round(s["avg"], 3), round(s["pf"], 2), p10, round(dd, 1), flush=True)
    out += ["", "- A+ 現行應該約等於 #207（981 張 +0.101R PF 1.30、回撤 −25.7R）；有差距係重算誤差，判斷照預先登記數字。", "",
            "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "VOL_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


C._orig_signals = C.signals
if __name__ == "__main__":
    main()
