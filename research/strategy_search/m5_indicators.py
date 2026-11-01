"""[IDEAS #169] XAUUSD M5 指標策略：券商 MT5 M1→M5 2022-08→2026-10 滾動前向（12 個月揀、3 個月測），
再用 Dukascopy M1→M5 2015-01→2022-07（未見數據）固定參數核對。網格寫死喺 FAMILIES（預先登記，跑之前 commit）。
訊號喺 M5 收市判斷，下一根 M5 開盤入；SL／TP 用 M5 高低（同一根都掂當 SL、跳空過 SL 用開盤）；每張扣 0.5 美元；同一組合一次一張。
用法：python3 research/strategy_search/m5_indicators.py --stage wf     → M5_IND_WF.md（第一關）
      python3 research/strategy_search/m5_indicators.py --stage duka   → M5_IND_DUKA.md（第二關，要 Dukascopy 2015–2022 M1）
"""
import argparse
import datetime as dt
import itertools
import json
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G  # noqa: E402
import robust_long as R  # noqa: E402
import search as S  # noqa: E402
import search2 as W  # noqa: E402

NY = ZoneInfo("America/New_York")
PICKS = os.path.join(HERE, "m5_ind_picks.json")
WF_FIRST_TEST = (2023, 10)            # 第一個測試季
WF_LAST_TEST = (2026, 7)              # 最後一個測試季（2026-07→10）
MIN_TRAIN_N, MIN_TRAIN_PF = 30, 1.1

FAMILIES = {
    "A 保力加回歸＋ADX": [dict(adx=a, k=k, RR=r) for a, k, r in itertools.product((20, 25), (1.5, 2.5), (1.0, 2.0))],
    "B 擠壓突破（BB 喺 KC 入面）": [dict(sq=s, k=k, RR=r) for s, k, r in itertools.product((12, 24), (1.5, 2.5), (2.0, 3.0))],
    "C MACD 交叉＋H1 EMA200": [dict(k=k, RR=r) for k, r in itertools.product((1.5, 2.5), (1.5, 2.0, 3.0))],
    "D 隨機指標＋H1 斜率": [dict(f=f, k=k, RR=r) for f, k, r in itertools.product((True, False), (1.5, 2.5), (1.5, 2.0))],
    "E 時段均價（TWAP）": [dict(mode="fade", z=z, k=k) for z, k in itertools.product((2.0, 3.0), (1.5, 2.5))] +
                          [dict(mode="pullback", z=0, k=k) for k in (1.5, 2.5)],
    "F 開市區間突破": [dict(sess=s, RR=r) for s, r in itertools.product(("LDN", "NY"), (1.0, 2.0))],
    "G M5 唐奇安＋波幅擴張": [dict(N=N, vf=v, RR=r) for N, v, r in itertools.product((48, 96), (True, False), (2.0, 3.0))],
}
T_H = {"A": 4, "B": 8, "C": 8, "D": 4, "E": 4, "F": 4, "G": 8}


def wilder(x, n):
    return G.ema(np.nan_to_num(x), 2 * n - 1)


def rolling(x, n, fn):
    from numpy.lib.stride_tricks import sliding_window_view as swv
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = fn(swv(x, n), axis=1)
    return out


class M5:
    def __init__(self, d):
        self.t, self.o, self.h, self.l, self.c = d["t"], d["o"], d["h"], d["l"], d["c"]
        t, o, h, l, c = self.t, self.o, self.h, self.l, self.c
        n = len(t)
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        self.atr = rolling(tr, 14, np.mean)
        self.atr100 = rolling(tr, 100, np.mean)
        # ADX
        up, dn = h - np.r_[h[0], h[:-1]], np.r_[l[0], l[:-1]] - l
        pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atw = wilder(tr, 14)
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = 100 * wilder(pdm, 14) / atw; ndi = 100 * wilder(ndm, 14) / atw
            dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
        self.adx = wilder(np.nan_to_num(dx), 14)
        # 保力加／KC
        self.mid = rolling(c, 20, np.mean); sd = rolling(c, 20, np.std)
        self.bu, self.bl = self.mid + 2 * sd, self.mid - 2 * sd
        e20 = G.ema(c, 20); a20 = rolling(tr, 20, np.mean)
        self.ku, self.kl = e20 + 1.5 * a20, e20 - 1.5 * a20
        # MACD
        self.macd = G.ema(c, 12) - G.ema(c, 26); self.sig = G.ema(self.macd, 9)
        # 隨機
        ll, hh = rolling(l, 14, np.min), rolling(h, 14, np.max)
        with np.errstate(divide="ignore", invalid="ignore"):
            k = 100 * (c - ll) / (hh - ll)
        self.sk = rolling(np.nan_to_num(k, nan=50.0), 3, np.mean); self.sd = rolling(np.nan_to_num(self.sk, nan=50.0), 3, np.mean)
        # H1（已收市）
        h1 = W.TF(d, 3600)
        e200 = G.ema(h1.c, 200); e50 = G.ema(h1.c, 50)
        j = h1.j; ok = j >= 200
        jj = np.clip(j, 1, None)
        self.h1_up200 = np.where(ok, h1.c[jj] > e200[jj], False); self.h1_dn200 = np.where(ok, h1.c[jj] < e200[jj], False)
        sl50 = np.where(j >= 51, e50[jj] - e50[jj - 1], 0.0)
        self.h1_s50 = sl50
        # 時段 TWAP（22:00 UTC 起）
        sess = (t + 7200) // 86400
        tp = (h + l + c) / 3
        _, first, cnt = np.unique(sess, return_index=True, return_counts=True)
        grp = np.repeat(np.arange(len(first)), cnt)
        cs = np.cumsum(tp); cs2 = np.cumsum(tp * tp)
        base = np.r_[0, cs][first][grp]; base2 = np.r_[0, cs2][first][grp]
        m = np.arange(n) - first[grp] + 1
        self.twap = (cs - base) / m
        self.tsd = np.sqrt(np.maximum((cs2 - base2) / m - self.twap ** 2, 0))
        self.sess_n = m
        self.sess_last = np.r_[first[1:], n][grp] - 1
        # 紐約時間（開市區間）
        loc = [dt.datetime.fromtimestamp(int(x), NY) for x in t]
        self.ny_min = np.array([x.hour * 60 + x.minute for x in loc])
        self.utc_min = (t // 60) % 1440
        self.day = t // 86400


def cross_up(a, b):
    return (a > b) & (np.r_[np.nan, a[:-1]] <= np.r_[np.nan, b[:-1]])


def cross_dn(a, b):
    return (a < b) & (np.r_[np.nan, a[:-1]] >= np.r_[np.nan, b[:-1]])


def run(D, fam, p):
    c, atr = D.c, D.atr
    n = len(c); key = fam[0]; T = T_H[key]
    ent = []

    def add(mask_b, mask_s, k, rr):
        for i in np.flatnonzero(mask_b | mask_s):
            if i + 1 >= n or np.isnan(atr[i]) or atr[i] <= 0:
                continue
            s = 1 if mask_b[i] else -1
            d = k * atr[i]
            ent.append((i + 1, s, d, None if rr is None else rr * d, T))

    if key == "A":
        lo = D.adx < p["adx"]
        b = lo & (c > D.bl) & (np.r_[np.nan, c[:-1]] < np.r_[np.nan, D.bl[:-1]])
        s = lo & (c < D.bu) & (np.r_[np.nan, c[:-1]] > np.r_[np.nan, D.bu[:-1]])
        add(b, s, p["k"], p["RR"])
    elif key == "B":
        inside = (D.bu < D.ku) & (D.bl > D.kl)
        run_len = np.zeros(n, int)
        for i in range(1, n):
            run_len[i] = run_len[i - 1] + 1 if inside[i] else 0
        prev = np.r_[0, run_len[:-1]]
        rel = (~inside) & (prev >= p["sq"])
        add(rel & (c > D.bu), rel & (c < D.bl), p["k"], p["RR"])
    elif key == "C":
        b = cross_up(D.macd, D.sig) & (D.macd < 0) & D.h1_up200
        s = cross_dn(D.macd, D.sig) & (D.macd > 0) & D.h1_dn200
        add(b, s, p["k"], p["RR"])
    elif key == "D":
        b = cross_up(D.sk, D.sd) & (np.r_[np.nan, D.sk[:-1]] < 20)
        s = cross_dn(D.sk, D.sd) & (np.r_[np.nan, D.sk[:-1]] > 80)
        if p["f"]:
            b &= D.h1_s50 > 0; s &= D.h1_s50 < 0
        add(b, s, p["k"], p["RR"])
    elif key == "E":
        ok = D.sess_n >= 12
        if p["mode"] == "fade":
            b = ok & (c < D.twap - p["z"] * D.tsd) & (np.r_[np.nan, c[:-1]] >= np.r_[np.nan, (D.twap - p["z"] * D.tsd)[:-1]])
            s = ok & (c > D.twap + p["z"] * D.tsd) & (np.r_[np.nan, c[:-1]] <= np.r_[np.nan, (D.twap + p["z"] * D.tsd)[:-1]])
            for i in np.flatnonzero(b | s):
                if i + 1 >= n or np.isnan(atr[i]) or atr[i] <= 0:
                    continue
                sd = 1 if b[i] else -1
                ent.append((i + 1, sd, p["k"] * atr[i], abs(D.twap[i] - c[i]), T))
        else:
            b = ok & (D.h1_s50 > 0) & (D.l <= D.twap) & (c > D.twap) & (np.r_[np.nan, c[:-1]] > np.r_[np.nan, D.twap[:-1]])
            s = ok & (D.h1_s50 < 0) & (D.h >= D.twap) & (c < D.twap) & (np.r_[np.nan, c[:-1]] < np.r_[np.nan, D.twap[:-1]])
            add(b, s, p["k"], 2.0)
    elif key == "F":
        if p["sess"] == "LDN":
            in_rng = (D.utc_min >= 420) & (D.utc_min < 450); after = (D.utc_min >= 450) & (D.utc_min < 570); clock = D.utc_min
            end_min = 450 + 240
        else:
            in_rng = (D.ny_min >= 500) & (D.ny_min < 530); after = (D.ny_min >= 530) & (D.ny_min < 650); clock = D.ny_min
            end_min = 530 + 240
        days = D.day
        i = 0; idx = np.flatnonzero(in_rng)
        groups = np.split(idx, np.flatnonzero(np.diff(days[idx]) != 0) + 1) if len(idx) else []
        for g in groups:
            if len(g) < 5:
                continue
            rh, rl = D.h[g].max(), D.l[g].min(); w = rh - rl
            if w <= 0:
                continue
            j = g[-1] + 1
            while j < n - 1 and days[j] == days[g[0]] and after[j]:
                sd = 1 if c[j] > rh else (-1 if c[j] < rl else 0)
                if sd:
                    mh = max((end_min - clock[j + 1]) / 60, 0.25)
                    ent.append((j + 1, sd, w, p["RR"] * w, mh))
                    break
                j += 1
    elif key == "G":
        N = p["N"]
        hh = np.r_[np.nan, rolling(D.h, N, np.max)[:-1]]; ll = np.r_[np.nan, rolling(D.l, N, np.min)[:-1]]
        b = (c > hh) & (np.r_[np.nan, c[:-1]] <= np.r_[np.nan, hh[:-1]])
        s = (c < ll) & (np.r_[np.nan, c[:-1]] >= np.r_[np.nan, ll[:-1]])
        if p["vf"]:
            v = D.atr / D.atr100 > 1.2
            b &= v; s &= v
        add(b, s, 2.0, p["RR"])
    ent.sort(key=lambda x: x[0])
    return R.simulate(D, ent)


def q_of(ts):
    x = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    return (x.year, (x.month - 1) // 3 * 3 + 1)


def add_months(ym, k):
    y, m = ym; m += k
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return (y, m)


def ts_ym(ym):
    return int(dt.datetime(ym[0], ym[1], 1, tzinfo=dt.timezone.utc).timestamp())


def stage_wf():
    m1 = S.load("mt5", "2022-08-03", "2026-10-30")
    D = M5(W.to_m5(m1))
    out = ["# M5 指標策略（IDEAS #169）第一關：券商 MT5 滾動前向", "",
           f"- M5 {len(D.t):,} 根；12 個月揀（≥ {MIN_TRAIN_N} 張、PF ≥ {MIN_TRAIN_PF}）、測下 3 個月；每張扣 {R.COST} 美元", "",
           "| 家族 | 樣本外 | 正數季 | 最常揀 | 第一關 |", "|---|---|---|---|---|"]
    picks = {}
    quarters = []
    q = WF_FIRST_TEST
    while q <= WF_LAST_TEST:
        quarters.append(q); q = add_months(q, 3)
    for fam, grid in FAMILIES.items():
        trs = [run(D, fam, p) for p in grid]
        oos, qs, sel = [], [], []
        for q in quarters:
            a, b = ts_ym(add_months(q, -12)), ts_ym(q)
            e = ts_ym(add_months(q, 3))
            best = None
            for gi, tr in enumerate(trs):
                s = R.summ([x[3] for x in tr if a <= x[0] < b])
                if s["n"] >= MIN_TRAIN_N and s["pf"] >= MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                    best = (gi, s["avg"])
            yt = [] if best is None else [x for x in trs[best[0]] if b <= x[0] < e]
            if best is not None:
                sel.append(best[0])
            oos += yt; qs.append(R.summ([x[3] for x in yt]))
        s = R.summ([x[3] for x in oos])
        pos = sum(1 for v in qs if v["n"] and v["avg"] > 0)
        ok = dict(n=s["n"] >= 300, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, t=s["t"] >= 3.0, q=pos >= 8)
        top = max(set(sel), key=sel.count) if sel else None
        picks[fam] = {"pass1": all(ok.values()), "param": None if top is None else grid[top], "oos": s}
        out.append(f"| {fam} | {R.fmt(s)} | {pos}/{len(quarters)} | {'—' if top is None else grid[top]} | "
                   f"{'✅ 入第二關' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, R.fmt(s), flush=True)
    json.dump(picks, open(PICKS, "w"), ensure_ascii=False, indent=1, default=float)
    out += ["", f"- 入第二關：{'、'.join(f for f, v in picks.items() if v['pass1']) or '冇'}",
            "- 第二關（必過）：最常揀嗰組固定參數，Dukascopy 2015-01→2022-07：≥ 300 張、平均 ≥ +0.03R、PF ≥ 1.1、≥ 5/8 年正、2015–18 同 2019–22 兩半都正。", ""]
    open(os.path.join(HERE, "M5_IND_WF.md"), "w").write("\n".join(out))


def stage_duka():
    picks = json.load(open(PICKS))
    todo = {f: v for f, v in picks.items() if v["pass1"]}
    out = ["# M5 指標策略（IDEAS #169）第二關：Dukascopy 2015-01→2022-07 固定參數", ""]
    if not todo:
        out.append("- 第一關冇家族過，第二關唔使跑。")
    else:
        m1 = S.load("duka", "2015-01-01", "2022-07-31")
        yrs_have = sorted({dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year for x in m1["t"][:: 50000]})
        out.append(f"- Dukascopy M1 {len(m1['t']):,} 根，年份 {yrs_have}")
        D = M5(W.to_m5(m1))
        for fam, v in todo.items():
            tr = run(D, fam, v["param"])
            s = R.summ([x[3] for x in tr]); yy = {}
            for x in tr:
                yy.setdefault(R.yr(x[0]), []).append(x[3])
            pos = sum(1 for r in yy.values() if np.mean(r) > 0)
            h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2018]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2019])
            ok = dict(n=s["n"] >= 300, avg=s["avg"] >= 0.03, pf=s["pf"] >= 1.1, yrs=pos >= 5, halves=h1["avg"] > 0 and h2["avg"] > 0)
            out += [f"## {fam} {v['param']}", "", f"- {R.fmt(s)}；{pos}/{len(yy)} 年正；2015–18 {h1['avg']:+.3f}、2019–22 {h2['avg']:+.3f}",
                    f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, x in ok.items() if not x)}", ""]
    open(os.path.join(HERE, "M5_IND_DUKA.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("wf", "duka"), required=True)
    a = ap.parse_args()
    stage_wf() if a.stage == "wf" else stage_duka()
