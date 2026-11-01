"""[IDEAS #172] XAUUSD D1 指標策略＋隨機基準：Dukascopy H1 2005→2026（D1 由 H1 合成，日界 22:00 UTC），滾動前向 4 年揀、1 年測。
訊號喺 D1 收市判，下一日第一根 H1 開盤入；SL／TP 用 H1 高低（同一根都掂當 SL、跳空用開盤）；每張扣 0.5 美元；一次一張；時間止蝕 20 日。
每組出場都計隨機基準（每日開盤都入，多空各一次）。網格寫死喺 FAMILIES（預先登記，跑之前 commit）。
用法：python3 research/strategy_search/d1_indicators.py → D1_IND.md
"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G  # noqa: E402
import m5_indicators as M  # noqa: E402
import robust_long as R  # noqa: E402

EXITS = [(1.0, 2.0), (2.0, 2.0), (4.0, 2.0)]          # (TP, SL) × D1 ATR(20)
T_H = 20 * 24
FAMILIES = {
    "J1 均線交叉": [dict(f=f, s=s, ex=e) for (f, s), e in itertools.product(((20, 50), (50, 200)), range(3))],
    "J2 MACD 交叉": [dict(filt=fl, ex=e) for fl, e in itertools.product((False, True), range(3))],
    "J3 DMI 交叉＋ADX": [dict(adx=a, ex=e) for a, e in itertools.product((20, 25), range(3))],
    "J4 保力加回歸": [dict(filt=fl, ex=e) for fl, e in itertools.product((False, True), range(3))],
    "J5 Keltner 突破": [dict(ex=e) for e in range(3)],
    "J6 一目均衡表破雲": [dict(ex=e) for e in range(3)],
    "J7 拋物線 SAR 轉向": [dict(filt=fl, ex=e) for fl, e in itertools.product((False, True), range(3))],
    "J8 威廉 %R 極端回歸": [dict(th=t, filt=fl, ex=e) for t, fl, e in itertools.product((10, 20), (False, True), range(3))],
}


def psar(h, l, af0=0.02, step=0.02, amax=0.2):
    n = len(h); sar = np.full(n, np.nan); up = np.zeros(n, bool)
    if n < 3:
        return sar, up
    bull = True; s = l[0]; ep = h[0]; af = af0
    for i in range(1, n):
        s = s + af * (ep - s)
        if bull:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                bull, s, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, amax)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                bull, s, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + step, amax)
        sar[i] = s; up[i] = bull
    return sar, up


class DI(R.Data):
    def __init__(self, *a):
        super().__init__(*a)
        h, l, c = self.dh, self.dl, self.dc
        self.do = self.o[self.dfirst]
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        self.s200 = M.rolling(c, 200, np.mean)
        self.ma = {k: M.rolling(c, k, np.mean) for k in (20, 50, 200)}
        macd = G.ema(c, 12) - G.ema(c, 26); self.macd, self.msig = macd, G.ema(macd, 9)
        up, dn = h - np.r_[h[0], h[:-1]], np.r_[l[0], l[:-1]] - l
        pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atw = M.wilder(tr, 14)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.pdi = 100 * M.wilder(pdm, 14) / atw; self.ndi = 100 * M.wilder(ndm, 14) / atw
            self.adx = M.wilder(np.nan_to_num(100 * np.abs(self.pdi - self.ndi) / (self.pdi + self.ndi)), 14)
        mid = M.rolling(c, 20, np.mean); sd = M.rolling(c, 20, np.std)
        self.bu, self.bl = mid + 2 * sd, mid - 2 * sd
        e20 = G.ema(c, 20); a20 = M.rolling(tr, 20, np.mean)
        self.ku, self.kl = e20 + 2 * a20, e20 - 2 * a20
        hh = lambda n: M.rolling(h, n, np.max)   # noqa: E731
        ll = lambda n: M.rolling(l, n, np.min)   # noqa: E731
        ten = (hh(9) + ll(9)) / 2; kij = (hh(26) + ll(26)) / 2
        sa = (ten + kij) / 2; sb = (hh(52) + ll(52)) / 2
        self.ten, self.kij = ten, kij
        self.ctop = np.r_[np.full(26, np.nan), np.fmax(sa, sb)[:-26]]
        self.cbot = np.r_[np.full(26, np.nan), np.fmin(sa, sb)[:-26]]
        self.sar, self.sar_up = psar(h, l)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.wr = -100 * (hh(14) - c) / (hh(14) - ll(14))


def prev(x):
    return np.r_[np.nan, x[:-1]]


def signals(D, fam, p):
    c = D.dc; key = fam[:2]
    tu, td = c > D.s200, c < D.s200
    if key == "J1":
        f, s = D.ma[p["f"]], D.ma[p["s"]]
        b, x = (f > s) & (prev(f) <= prev(s)), (f < s) & (prev(f) >= prev(s))
    elif key == "J2":
        b, x = (D.macd > D.msig) & (prev(D.macd) <= prev(D.msig)), (D.macd < D.msig) & (prev(D.macd) >= prev(D.msig))
        if p["filt"]:
            b &= tu; x &= td
    elif key == "J3":
        st = D.adx > p["adx"]
        b, x = st & (D.pdi > D.ndi) & (prev(D.pdi) <= prev(D.ndi)), st & (D.pdi < D.ndi) & (prev(D.pdi) >= prev(D.ndi))
    elif key == "J4":
        b, x = (c > D.bl) & (prev(c) < prev(D.bl)), (c < D.bu) & (prev(c) > prev(D.bu))
        if p["filt"]:
            b &= tu; x &= td
    elif key == "J5":
        b, x = (c > D.ku) & (prev(c) <= prev(D.ku)), (c < D.kl) & (prev(c) >= prev(D.kl))
    elif key == "J6":
        b = (c > D.ctop) & (prev(c) <= prev(D.ctop)) & (D.ten > D.kij)
        x = (c < D.cbot) & (prev(c) >= prev(D.cbot)) & (D.ten < D.kij)
    elif key == "J7":
        b, x = D.sar_up & ~np.r_[True, D.sar_up[:-1]], ~D.sar_up & np.r_[False, D.sar_up[:-1]]
        if p["filt"]:
            b &= tu; x &= td
    else:
        lo, hi = -100 + p["th"], -p["th"]
        b, x = (D.wr > lo) & (prev(D.wr) <= lo), (D.wr < hi) & (prev(D.wr) >= hi)
        if p["filt"]:
            b &= tu; x &= td
    return np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)


def run(D, fam, p):
    b, x = signals(D, fam, p); tp, sl = EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], T_H)
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    return R.simulate(D, ent)


def baseline(D):
    out = {}
    for e, (tp, sl) in enumerate(EXITS):
        yy = {}
        for s in (1, -1):
            ent = [(int(D.dfirst[d + 1]), s, sl * D.datr[d], tp * D.datr[d], T_H) for d in range(210, len(D.dc) - 1) if D.datr[d] > 0]
            for t_ in R.simulate(D, ent):
                yy.setdefault(R.yr(t_[0]), []).append(t_[3])
        out[e] = {y: (float(np.mean(np.asarray(v) > 0)), float(np.mean(v))) for y, v in yy.items()}
    return out


def main():
    duka = R.load_duka(); D = DI(*duka); base = baseline(D)
    Y0, Y1 = R.FIRST_TEST, R.LAST_TEST
    out = ["# XAUUSD D1 指標策略＋隨機基準（IDEAS #172）", "",
           f"- Dukascopy H1→D1 {len(D.dc):,} 日；滾動前向 4 年揀（≥ 20 張、PF ≥ 1.1，揀平均 R 最高）、測 1 年，{Y0}→{Y1}；每張扣 {R.COST} 美元；時間止蝕 20 日",
           "", "## 隨機基準（每日開盤都入、多空各一次）", "", "| 出場（TP／SL × D1 ATR） | 基準勝率 | 基準平均 R |", "|---|---|---|"]
    for e, (tp, sl) in enumerate(EXITS):
        out.append(f"| {tp}／{sl} | {np.mean([v[0] for v in base[e].values()]):.1%} | {np.mean([v[1] for v in base[e].values()]):+.3f} |")
    out += ["", "## 各家族滾動前向（樣本外）", "",
            "| 家族 | 樣本外 | 勝率 | 基準勝率 | 差 | 正數年 | 兩半 | 隔夜息後 | 判 |", "|---|---|---|---|---|---|---|---|---|"]
    trades, picks, verdict = {}, {}, {}
    for fam, grid in FAMILIES.items():
        for gi, p in enumerate(grid):
            trades[(fam, gi)] = run(D, fam, p)
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
        ok = dict(n=s["n"] >= 100, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs=pos >= 11,
                  halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = ok
        out.append(f"| {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {pos}/18 | "
                   f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, s["n"], round(s["avg"], 3), flush=True)
    out += ["", "## 全期描述（每家族最好嗰組，唔算數）", ""]
    for fam, grid in FAMILIES.items():
        best = max(range(len(grid)), key=lambda g: R.summ([x[3] for x in trades[(fam, g)]])["avg"])
        rs = [x[3] for x in trades[(fam, best)]]
        out.append(f"- {fam} {grid[best]}：{R.fmt(R.summ(rs))}，勝率 {np.mean(np.asarray(rs) > 0):.1%}")
    out += ["", "## 券商 MT5 對照（2022-10→2026-10）", ""]
    try:
        Mx = DI(*R.load_mt5_spliced(duka))
        a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp()); cache = {}
        for fam, grid in FAMILIES.items():
            rm = []
            for Y in range(2022, Y1 + 1):
                g = picks[fam][Y]
                if g is None:
                    continue
                if (fam, g) not in cache:
                    cache[(fam, g)] = run(Mx, fam, grid[g])
                rm += [x[3] for x in cache[(fam, g)] if R.yr(x[0]) == Y and x[0] >= a0]
            sm = R.summ(rm); verdict[fam]["mt5"] = sm["n"] > 0 and sm["avg"] > 0
            out.append(f"- {fam}：MT5 {R.fmt(sm)}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}（當未過）")
        for fam in FAMILIES:
            verdict[fam]["mt5"] = False
    passed = [f for f, ok in verdict.items() if all(ok.values())]
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}", "- 合格只開影子前向；934 唔改。", ""]
    open(os.path.join(HERE, "D1_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:45]))


if __name__ == "__main__":
    main()
