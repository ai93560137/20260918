"""[IDEAS #187／#188] XAUUSD 新指標家族（未試過嘅八個）喺 D1 同 H4 計，＋ 合格／接近合格嘅加入組合 A 單倉版（935）睇會唔會更好。
#187：K1 Supertrend 轉向、K2 CCI 極端回歸、K3 隨機指標（KD）極端交叉、K4 Aroon 交叉、K5 平均 K 線（Heikin-Ashi）轉色、
      K6 RSI14 極端回歸、K7 TRIX 零軸交叉、K8 唐奇安 20 突破。每個家族喺 D1（時間止蝕 480 小時）同 H4（80 小時）各計一次（16 組）。
      成交引擎同 #172／#182：收市判、下一根第一根 H1 開盤入；SL／TP × 該時框 ATR20（EXITS 三組）；同一根掂 SL＋TP 當 SL；跳空用開盤；扣 0.5 美元；一次一張。
      Dukascopy H1 2005→2026，滾動前向 4 年揀（≥ 20 張、PF ≥ 1.1，揀平均 R 最高）、測 1 年，2009→2026；MT5 2022-10→2026-10 用返每年揀法對照。
      判（同 #172／#182）：樣本外 ≥ 200 張、勝率高過隨機基準 ≥ 2pp、平均 ≥ +0.05R、≥ 11/18 年正、兩半都正、隔夜息後 > 0、MT5 > 0。
      多重比較：16 組同時測，另列 t 值；t < 2.5 嘅合格都標「弱」。
#188：候選＝#187 入面「樣本外平均 ≥ +0.05R、PF ≥ 1.15、≥ 11/18 年正、MT5 > 0」嘅（唔計張數同勝率差；同 #183 揀成份一樣），
      排喺組合 A 六個成份之後（次序按 #187 樣本外平均 R 由高到低），做單倉版（同 #186：同一時間 1 張，同時出訊號按次序揀）。
      判「比 935 好」：單倉版平均 > +0.083R、PF > 1.24、≥ 14/18 年正、最大回撤唔差過 −26.6R、MT5 > 0，且照過 #183 六條。
      合格都只係提案；改 935 要使用者經總指揮批。
用法：python3 research/strategy_search/new_ind.py → NEW_IND.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import g7_long as G  # noqa: E402
import h4_indicators as H  # noqa: E402
import m5_indicators as M  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402

EX = range(3)
FL = (False, True)
FAMILIES = {
    "K1 Supertrend 轉向": [dict(m=m, filt=f, ex=e) for m, f, e in itertools.product((2.0, 3.0), FL, EX)],
    "K2 CCI 極端回歸": [dict(th=t, filt=f, ex=e) for t, f, e in itertools.product((100, 200), FL, EX)],
    "K3 KD 極端交叉": [dict(filt=f, ex=e) for f, e in itertools.product(FL, EX)],
    "K4 Aroon 交叉": [dict(filt=f, ex=e) for f, e in itertools.product(FL, EX)],
    "K5 平均 K 線轉色": [dict(N=n, filt=f, ex=e) for n, f, e in itertools.product((2, 3), FL, EX)],
    "K6 RSI14 極端回歸": [dict(th=t, filt=f, ex=e) for t, f, e in itertools.product((30, 25), FL, EX)],
    "K7 TRIX 零軸交叉": [dict(filt=f, ex=e) for f, e in itertools.product(FL, EX)],
    "K8 唐奇安 20 突破": [dict(filt=f, ex=e) for f, e in itertools.product(FL, EX)],
}
TFS = (("D1", 480), ("H4", 80))
A_TS = P.A0
A_SINGLE = dict(avg=0.083, pf=1.24, yrs=14, dd=-26.6)


def prev(x):
    return np.r_[np.nan, x[:-1]]


def supertrend(h, l, c, n, m):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = M.wilder(tr, n); mid = (h + l) / 2
    ub, lb = mid + m * atr, mid - m * atr
    fu, fl = ub.copy(), lb.copy(); up = np.ones(len(c), bool)
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        up[i] = (c[i] > fu[i - 1]) if not up[i - 1] else not (c[i] < fl[i - 1])
    up[:n] = True
    return up


def add_k(D):
    h, l, c, o = D.dh, D.dl, D.dc, D.do
    D.st = {m: supertrend(h, l, c, 10, m) for m in (2.0, 3.0)}
    tp = (h + l + c) / 3; sma = M.rolling(tp, 20, np.mean)
    md = M.rolling(tp, 20, lambda w, axis: np.mean(np.abs(w - w.mean(axis=axis, keepdims=True)), axis=axis))
    with np.errstate(divide="ignore", invalid="ignore"):
        D.cci = (tp - sma) / (0.015 * md)
        hh, ll = M.rolling(h, 14, np.max), M.rolling(l, 14, np.min)
        rk = 100 * (c - ll) / (hh - ll)
    D.sk = M.rolling(np.nan_to_num(rk, nan=50), 3, np.mean); D.sd = M.rolling(np.nan_to_num(D.sk, nan=50), 3, np.mean)
    from numpy.lib.stride_tricks import sliding_window_view as swv
    au = np.full(len(c), np.nan); ad = np.full(len(c), np.nan)
    if len(c) > 26:
        wh, wl = swv(h, 26), swv(l, 26)
        au[25:] = 100 * np.argmax(wh, axis=1) / 25; ad[25:] = 100 * np.argmin(wl, axis=1) / 25
    D.aru, D.ard = au, ad
    hc = (o + h + l + c) / 4; ho = np.empty(len(c)); ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(c)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    D.ha_g = hc > ho
    D.rsi = G.rsi(c, 14)
    e3 = G.ema(G.ema(G.ema(c, 15), 15), 15); D.trix = np.r_[0, np.diff(e3) / e3[:-1]]
    D.dch = prev(M.rolling(h, 20, np.max)); D.dcl = prev(M.rolling(l, 20, np.min))
    return D


class KD1(Q.DI):
    def __init__(self, *a):
        super().__init__(*a); add_k(self)


class KH4(H.H4I):
    def __init__(self, *a):
        super().__init__(*a); add_k(self)


def signals(D, fam, p):
    c = D.dc; key = fam[:2]
    if key == "K1":
        u = D.st[p["m"]]; pu = np.r_[True, u[:-1]]
        b, x = u & ~pu, ~u & pu
    elif key == "K2":
        t = p["th"]; b, x = (D.cci > -t) & (prev(D.cci) <= -t), (D.cci < t) & (prev(D.cci) >= t)
    elif key == "K3":
        cu, cd = (D.sk > D.sd) & (prev(D.sk) <= prev(D.sd)), (D.sk < D.sd) & (prev(D.sk) >= prev(D.sd))
        b, x = cu & (prev(D.sk) < 20), cd & (prev(D.sk) > 80)
    elif key == "K4":
        b, x = (D.aru > D.ard) & (prev(D.aru) <= prev(D.ard)), (D.aru < D.ard) & (prev(D.aru) >= prev(D.ard))
    elif key == "K5":
        g = D.ha_g; n = p["N"]
        red_run = np.ones(len(g), bool); grn_run = np.ones(len(g), bool)
        for k in range(1, n + 1):
            sh = np.r_[np.full(k, False), g[:-k]]; shr = np.r_[np.full(k, True), g[:-k]]
            red_run &= ~shr; grn_run &= sh
        b, x = g & red_run, ~g & grn_run
    elif key == "K6":
        lo, hi = p["th"], 100 - p["th"]
        b, x = (D.rsi > lo) & (prev(D.rsi) <= lo), (D.rsi < hi) & (prev(D.rsi) >= hi)
    elif key == "K7":
        b, x = (D.trix > 0) & (prev(D.trix) <= 0), (D.trix < 0) & (prev(D.trix) >= 0)
    else:
        b, x = (c > D.dch) & (prev(c) <= prev(D.dch)), (c < D.dcl) & (prev(c) >= prev(D.dcl))
    if p["filt"]:
        b &= c > D.s200; x &= c < D.s200
    return np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)


def run(D, fam, p, th):
    b, x = signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th)
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    return R.simulate(D, ent)


def mt5_trades(Mx, fam, grid, picks, th):
    tr, cache = [], {}
    for Y, g in picks.items():
        if g is None or Y < 2022:
            continue
        if g not in cache:
            cache[g] = run(Mx, fam, grid[g], th)
        tr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= A_TS]
    return tr


def main():
    R.COST = 0.5
    duka = R.load_duka(); mt = R.load_mt5_spliced(duka)
    frames = {"D1": (KD1(*duka), KD1(*mt)), "H4": (KH4(*duka), KH4(*mt))}
    out = ["# XAUUSD 新指標家族 D1／H4（IDEAS #187）＋加入組合 A 單倉（#188）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy H1 2005→2026；滾動前向 4 年揀、1 年測（2009→2026）；扣 0.5 美元；MT5 2022-10→2026-10 對照",
           "", "## #187 各家族（樣本外）", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 正數年 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tf, th in TFS:
        D, Mx = frames[tf]
        Q.T_H = th; base = Q.baseline(D)
        for fam, grid in FAMILIES.items():
            T = [run(D, fam, p, th) for p in grid]
            oos, picks = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
            oos = [x for x in oos if R.yr(x[0]) >= 2009]
            bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
            rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
            win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
            yy = {}
            for x in oos:
                yy.setdefault(R.yr(x[0]), []).append(x[3])
            pos = sum(1 for v in yy.values() if np.sum(v) > 0)
            h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
            mtr = mt5_trades(Mx, fam, grid, picks, th); sm = R.summ([x[3] for x in mtr])
            ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs=pos >= 11,
                      halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=sm["n"] > 0 and sm["avg"] > 0)
            near = s["avg"] >= 0.05 and s["pf"] >= 1.15 and pos >= 11 and sm["n"] > 0 and sm["avg"] > 0
            name = f"{tf} {fam}"
            res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=s, picks=picks, grid=grid)
            v = ("✅" + ("（弱，t < 2.5）" if s["t"] < 2.5 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {pos}/18 | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {sm['n']} 張 {sm['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), round(s["pf"], 2), pos, sm["n"], round(sm["avg"], 3), flush=True)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #187 合格：{'、'.join(passed) if passed else '冇'}", f"- #188 候選（平均 ≥ +0.05R、PF ≥ 1.15、≥ 11/18 年、MT5 > 0）：{'、'.join(cands) if cands else '冇'}", ""]
    # #188
    out += ["## #188 組合 A 單倉＋候選", ""]
    ds, picksA = P.streams(duka); ms, _ = P.streams(mt, picksA)
    keys = [k for k in ds if not k.startswith("7")]
    rows = ["| 版本 | 張數 | 平均 R | PF | 合計 R | 正數年 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 判 #183 | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    variants = [("935 現行（A 單倉）", [])]
    if cands:
        variants.append(("A＋全部候選", cands))
        variants += [(f"A＋{c}", [c]) for c in cands] if len(cands) > 1 else []
    for label, add in variants:
        dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= A_TS] for k in keys}
        for c in add:
            dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
        kk = keys + add
        trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and pos >= A_SINGLE["yrs"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0 and all(ok.values())
        rows.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                    f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, b in ok.items() if not b)} | "
                    f"{'—' if not add else ('✅ 更好' if better else '❌')} |")
        if add:
            rows.append(f"|  ↳ 逐年 | " + "、".join(f"{y} {np.sum(v):+.1f}" for y, v in sorted(yy.items())) + " |||||||||||||")
        print(label, s, pos, dd, flush=True)
    out += rows if cands else ["- 冇候選，935 維持現行。"]
    if cands:
        out += ["", "- 候選本身係睇完 #187 樣本外結果先揀（同 #183 一樣有事後揀選偏差）；「更好」都只係提案，改 935 要使用者經總指揮批。"]
    out += ["", "## 每家族每年揀法（2026）", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "NEW_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
