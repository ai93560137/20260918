"""[IDEAS #171] XAUUSD H1 指標策略＋隨機基準：Dukascopy H1 2005→2026 滾動前向（4 年揀、1 年測），同 #166 引擎。
每組出場（TP a×H1 ATR、SL b×H1 ATR、48 小時）都計「隨機基準」：每根 H1 開盤都入（多空各一次、一次一張），同樣出場，
得出嗰年嘅基準勝率；策略要勝率高過基準先算有優勢。網格寫死喺 FAMILIES（預先登記，跑之前 commit）。
用法：python3 research/strategy_search/h1_indicators.py → H1_IND.md
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

EXITS = [(0.5, 3.0), (0.5, 6.0), (1.0, 1.0), (2.0, 1.0)]
T_H = 48
FAMILIES = {
    "I1 保力加觸帶回歸＋ADX": [dict(adx=a, ex=e) for a, e in itertools.product((20, 25), range(4))],
    "I2 RSI 極端＋D1 趨勢": [dict(th=t, f=f, ex=e) for t, f, e in itertools.product((25, 30), (True, False), range(4))],
    "I3 隨機交叉＋D1 趨勢": [dict(f=f, ex=e) for f, e in itertools.product((True, False), range(4))],
    "I4 MACD 柱轉向順 D1 趨勢": [dict(ex=e) for e in range(4)],
    "I5 CCI 極端回歸": [dict(th=t, ex=e) for t, e in itertools.product((150, 200), range(4))],
    "I6 Keltner 觸邊回歸": [dict(ex=e) for e in range(4)],
}


class HI(R.Data):
    def __init__(self, *a):
        super().__init__(*a)
        t, o, h, l, c = self.t, self.o, self.h, self.l, self.c
        n = len(t)
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        up, dn = h - np.r_[h[0], h[:-1]], np.r_[l[0], l[:-1]] - l
        pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atw = M.wilder(tr, 14)
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = 100 * M.wilder(pdm, 14) / atw; ndi = 100 * M.wilder(ndm, 14) / atw
            self.adx = M.wilder(np.nan_to_num(100 * np.abs(pdi - ndi) / (pdi + ndi)), 14)
        self.mid = M.rolling(c, 20, np.mean); sd = M.rolling(c, 20, np.std)
        self.bu, self.bl = self.mid + 2 * sd, self.mid - 2 * sd
        e20 = G.ema(c, 20); a20 = M.rolling(tr, 20, np.mean)
        self.ku, self.kl = e20 + 2 * a20, e20 - 2 * a20
        ll, hh = M.rolling(l, 14, np.min), M.rolling(h, 14, np.max)
        with np.errstate(divide="ignore", invalid="ignore"):
            k = 100 * (c - ll) / (hh - ll)
        self.sk = M.rolling(np.nan_to_num(k, nan=50.0), 3, np.mean); self.sdd = M.rolling(np.nan_to_num(self.sk, nan=50.0), 3, np.mean)
        macd = G.ema(c, 12) - G.ema(c, 26); self.hist = macd - G.ema(macd, 9)
        tp = (h + l + c) / 3; m20 = M.rolling(tp, 20, np.mean)
        md = M.rolling(tp, 20, lambda w, axis: np.mean(np.abs(w - w.mean(axis=axis, keepdims=True)), axis=axis))
        with np.errstate(divide="ignore", invalid="ignore"):
            self.cci = (tp - m20) / (0.015 * md)
        # D1 SMA200（已收市嗰日）
        cs = np.r_[0, np.cumsum(self.dc)]
        s200 = np.full(len(self.dc), np.nan); s200[199:] = (cs[200:] - cs[:-200]) / 200
        d_cur = np.searchsorted(self.dfirst, np.arange(n), side="right") - 1
        dj = d_cur - 1; ok = dj >= 199
        self.d_up = np.where(ok, self.dc[np.clip(dj, 0, None)] > s200[np.clip(dj, 0, None)], False)
        self.d_dn = np.where(ok, self.dc[np.clip(dj, 0, None)] < s200[np.clip(dj, 0, None)], False)


def prev(x):
    return np.r_[np.nan, x[:-1]]


def run(D, fam, p):
    c, atr = D.c, D.atr; n = len(c); key = fam[:2]
    a, b = EXITS[p["ex"]]
    if key == "I1":
        lo = D.adx < p["adx"]
        mb, ms = lo & (D.l <= D.bl) & (c > D.bl), lo & (D.h >= D.bu) & (c < D.bu)
    elif key == "I2":
        r = D.rsi14
        mb, ms = (r < p["th"]) & (prev(r) >= p["th"]), (r > 100 - p["th"]) & (prev(r) <= 100 - p["th"])
        if p["f"]:
            mb &= D.d_up; ms &= D.d_dn
    elif key == "I3":
        mb = (D.sk > D.sdd) & (prev(D.sk) <= prev(D.sdd)) & (prev(D.sk) < 20)
        ms = (D.sk < D.sdd) & (prev(D.sk) >= prev(D.sdd)) & (prev(D.sk) > 80)
        if p["f"]:
            mb &= D.d_up; ms &= D.d_dn
    elif key == "I4":
        hh = D.hist
        mb = D.d_up & (hh < 0) & (hh > prev(hh)) & (prev(hh) <= np.r_[np.nan, np.nan, hh[:-2]])
        ms = D.d_dn & (hh > 0) & (hh < prev(hh)) & (prev(hh) >= np.r_[np.nan, np.nan, hh[:-2]])
    elif key == "I5":
        mb, ms = (D.cci < -p["th"]) & (prev(D.cci) >= -p["th"]), (D.cci > p["th"]) & (prev(D.cci) <= p["th"])
    else:
        mb, ms = (D.l <= D.kl) & (c > D.kl), (D.h >= D.ku) & (c < D.ku)
    ent = [(i + 1, 1 if mb[i] else -1, b * atr[i], a * atr[i], T_H)
           for i in np.flatnonzero(mb | ms) if i >= 220 and i + 1 < n and atr[i] > 0]
    return R.simulate(D, ent)


def baseline(D):
    """每組出場、每年：隨機基準勝率同平均 R（每根 H1 都入，多空各一次，一次一張）。"""
    out = {}
    n = len(D.t)
    for e, (a, b) in enumerate(EXITS):
        yy = {}
        for s in (1, -1):
            ent = [(i + 1, s, b * D.atr[i], a * D.atr[i], T_H) for i in range(220, n - 1) if D.atr[i] > 0]
            for x in R.simulate(D, ent):
                yy.setdefault(R.yr(x[0]), []).append(x[3])
        out[e] = {y: (float(np.mean(np.asarray(v) > 0)), float(np.mean(v))) for y, v in yy.items()}
        print("基準", EXITS[e], flush=True)
    return out


def main():
    duka = R.load_duka()
    D = HI(*duka)
    base = baseline(D)
    Y0, Y1 = R.FIRST_TEST, R.LAST_TEST
    out = ["# XAUUSD H1 指標策略＋隨機基準（IDEAS #171）", "",
           f"- Dukascopy H1 {len(D.t):,} 根；滾動前向 4 年揀（≥ 20 張、PF ≥ 1.1，揀平均 R 最高）、測 1 年，{Y0}→{Y1}；每張扣 {R.COST} 美元；時間止蝕 {T_H} 小時",
           "", "## 隨機基準（每根 H1 都入、多空各一次）", "", "| 出場（TP／SL × H1 ATR） | 全期基準勝率 | 全期基準平均 R |", "|---|---|---|"]
    for e, (a, b) in enumerate(EXITS):
        ws = [v[0] for v in base[e].values()]; rs = [v[1] for v in base[e].values()]
        out.append(f"| {a}／{b} | {np.mean(ws):.1%} | {np.mean(rs):+.3f} |")
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
        ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.03, yrs=pos >= 11,
                  halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = ok
        out.append(f"| {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {pos}/18 | "
                   f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, s["n"], round(s["avg"], 3), flush=True)
    out += ["", "## 券商 MT5 對照（2022-10→2026-10）", ""]
    try:
        Mx = HI(*R.load_mt5_spliced(duka))
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
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}", "- 合格只開影子前向；934 唔改。", "",
            "## 每年揀咗邊組", ""]
    for fam, grid in FAMILIES.items():
        out.append(f"- {fam}：" + "；".join(f"{Y} {'唔做' if picks[fam][Y] is None else grid[picks[fam][Y]]}" for Y in range(Y0, Y1 + 1)))
    open(os.path.join(HERE, "H1_IND.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:40]))


if __name__ == "__main__":
    main()
