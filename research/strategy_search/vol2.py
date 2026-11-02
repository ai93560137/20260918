"""[IDEAS #214] 波幅收縮突破第二輪（#213 之後）：
  W1 TTM 收縮釋放：上一根保力加 (20,2) 完全喺 Keltner (20,2×ATR) 入面、今根已經出返嚟，收市破上一根高 → 買、破低 → 沽
  W2 NR7 內包線突破：上一根係 NR7 兼內包線，今根收市破上一根高／低
  W3 ATR 收縮（放寬）：ATR5 ÷ ATR50 ≤ 過去 120 根第 20 百分位（上一根），今根收市破 10 根唐奇安高／低
  W4 保力加收窄（放寬）：上一根保力加闊度 ≤ 過去 120 根第 20 百分位，今根收市出上軌 → 買、出下軌 → 沽
  D1（480h）／H4（80h）各計＝8 組；網格、引擎、滾動前向、MT5、每組判同 #213。
A+ 部分：除咗「A+＋候選」，另測「A+ 第 7 成份 D1 內包線 → 換做 D1 NR4 內包線（#213 V2）」同「→ 換做每個 D1 候選」，
判「比 A+ 好」同 #213（平均 > +0.101R、PF > 1.30、近 10 年 ≥ 7/10、回撤唔差過 −25.7R、MT5 > 0）。
⚠ 換 NR4 內包線係睇完 #213 先諗（事後揀選），合格都要影子前向先。用法：python3 research/strategy_search/vol2.py → VOL2.md"""
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
import vol_ind as V  # noqa: E402
import xag_lead as XL  # noqa: E402

FAMILIES = {"W1 TTM 收縮釋放": C.GRID, "W2 NR7 內包線突破": C.GRID, "W3 ATR 收縮（放寬）": C.GRID, "W4 保力加收窄（放寬）": C.GRID}
_roll = V._roll


def signals(D, fam, p):
    h, l, c = D.dh, D.dl, D.dc
    rng = h - l; key = fam[:2]
    ph, pl = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        if key == "W1":
            sq = (D.bu < D.ku) & (D.bl > D.kl)
            prev = np.r_[False, sq[:-1]] & ~sq
            b = prev & (c > ph); x = prev & (c < pl)
        elif key == "W2":
            nr7 = rng <= _roll(rng, 7, np.min)
            inside = (h <= ph) & (l >= pl)
            prev = np.r_[False, (nr7 & inside)[:-1]]
            b = prev & (c > ph); x = prev & (c < pl)
        elif key == "W3":
            pc = np.r_[c[0], c[:-1]]
            tr = np.maximum.reduce([rng, np.abs(h - pc), np.abs(l - pc)])
            ratio = _roll(tr, 5, np.mean) / _roll(tr, 50, np.mean)
            q = _roll(ratio, 120, lambda w: np.nanpercentile(w, 20))
            sq = np.r_[False, (ratio <= q)[:-1]]
            dh = np.r_[np.nan, _roll(h, 10, np.max)[:-1]]; dl = np.r_[np.nan, _roll(l, 10, np.min)[:-1]]
            b = sq & (c > dh); x = sq & (c < dl)
        else:
            bw = D.bu - D.bl
            q = _roll(bw, 120, lambda w: np.nanpercentile(w, 20))
            prev = np.r_[False, (bw <= q)[:-1]]
            b = prev & (c > D.bu); x = prev & (c < D.bl)
    if p["filt"]:
        b &= c > D.s200; x &= c < D.s200
    b, x = np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)
    both = b & x
    return b & ~both, x & ~both


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


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    out = ["# 波幅收縮突破第二輪（IDEAS #214）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；正數年只睇最近 10 年；8 組同時測", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 近 10 年正數月 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
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
            name = f"{tf} {fam}"; res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=s, picks=picks, grid=grid, tf=tf)
            v = ("✅" + ("（弱，t < 2.5）" if s["t"] < 2.5 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {p10}/10 | {pm}/{nm} | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {sm['n']} 張 {sm['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), p10, sm["n"], round(sm["avg"], 3), flush=True)
    D1, M1 = Q.DI(*gd), Q.DI(*gm); Q.T_H = 480
    c3_oos, c3_mt, _ = wf_family(D1, M1, "C3 內包線突破", C.GRID, 480, C._orig_signals)
    nr4_oos, nr4_mt, _ = wf_family(D1, M1, "V2 NR4 內包線突破", C.GRID, 480, V.signals)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #214 合格：{'、'.join(passed) if passed else '冇'}", f"- 候選：{'、'.join(cands) if cands else '冇'}", "", "## A+ 變體（單倉）", ""]
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); base6 = [k for k in ds if not k.startswith("7")]
    pool_d = dict(ds); pool_m = {k: [x for x in ms[k] if x[0] >= P.A0] for k in base6}
    pool_d["C3"], pool_m["C3"] = c3_oos, c3_mt
    pool_d["NR4ID"], pool_m["NR4ID"] = nr4_oos, nr4_mt
    for c in cands:
        pool_d[c], pool_m[c] = res[c]["oos"], res[c]["mt"]
    variants = [("A+ 現行", base6 + ["C3"]), ("第 7 成份換做 D1 NR4 內包線", base6 + ["NR4ID"])]
    variants += [(f"A+＋{c}", base6 + ["C3", c]) for c in cands]
    variants += [(f"第 7 成份換做 {c}", base6 + [c]) for c in cands if res[c]["tf"] == "D1"]
    out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 近 10 年正數月 | MT5 | 最大回撤 R | 比 A+ 好？ |", "|---|---|---|---|---|---|---|---|---|---|"]
    for label, kk in variants:
        trs = PS.single(pool_d, kk); mtr = PS.single(pool_m, kk)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs); pm, nm = C.months(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        A = V.APLUS
        better = s["avg"] > A["avg"] and s["pf"] > A["pf"] and p10 >= A["yrs10"] and dd >= A["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pm}/{nm} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{'—' if label == 'A+ 現行' else ('✅ 更好' if better else '❌')} |")
        print(label, s["n"], round(s["avg"], 3), round(s["pf"], 2), p10, round(dd, 1), flush=True)
    out += ["", "- ⚠「換做 NR4 內包線」係睇完 #213 先諗（事後揀選）；就算更好都要影子前向先，唔直接上真倉。", "",
            "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "VOL2.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
