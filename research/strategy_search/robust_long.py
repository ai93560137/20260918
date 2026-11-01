"""[IDEAS #165] XAUUSD 長期穩健策略搜尋：Dukascopy H1 2005→2026，五個家族，滾動前向（4 年揀、1 年測）。
參數網格寫死喺 FAMILIES（預先登記，跑之前 commit）。成交：訊號 K 收市後下一根 H1 開盤入；SL／TP 用 H1 高低
（同一根都掂當 SL、跳空過 SL 用開盤）；每張扣 0.5 美元；同一組合一次一張。H4／D1 由 H1 合成，日界 22:00 UTC。
用法：python3 research/strategy_search/robust_long.py   → ROBUST_LONG.md
"""
import datetime as dt
import itertools
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G  # noqa: E402

COST = 0.5
SWAP_OZ = 0.15          # −15 美元／手／晚 ＝ 每盎司 0.15
TRAIN_Y, FIRST_TEST, LAST_TEST = 4, 2009, 2026
MIN_TRAIN_N, MIN_TRAIN_PF = 20, 1.1
CACHE = "/tmp/duka_h1.npz"

FAMILIES = {
    "F1 D1 唐奇安突破": [dict(N=N, k=k, dir=d) for N, k, d in itertools.product((20, 55, 100), (2.0, 3.0), ("both", "long"))],
    "F2 H4 斜率＋H1 RSI 回調": [dict(TH=a, E=e, K=k, RR=r) for a, e, k, r in itertools.product((30, 35, 40), (50, 100, 200), (1.5, 2.5), (1.5, 2.0, 3.0))],
    "F3 D1 時間序列動量": [dict(L=L, k=k, dir=d) for L, k, d in itertools.product((20, 60, 120), (3.0, 5.0), ("both", "long"))],
    "F4 亞洲區間突破": [dict(m=m, RR=r, dir=d) for m, r, d in itertools.product((0.5, 1.0), (1.0, 2.0), ("both", "long"))],
    "F5 D1 RSI2 均值回歸": [dict(L=L, f=f, dir=d) for L, f, d in itertools.product((5, 10, 15), (True, False), ("both", "long"))],
}


def yr(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).year


class Data:
    def __init__(self, t, o, h, l, c):
        self.t, self.o, self.h, self.l, self.c = t, o, h, l, c
        n = len(t)
        tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
        cs = np.r_[0, np.cumsum(tr)]
        self.atr = np.full(n, np.nan); self.atr[13:] = (cs[14:] - cs[:-14]) / 14
        self.rsi14 = G.rsi(c, 14)
        # D1（22:00 UTC 日界）
        dkey = (t + 7200) // 86400
        ks, first = np.unique(dkey, return_index=True)
        last = np.r_[first[1:], n] - 1
        self.dfirst, self.dlast = first, last
        self.dh = np.maximum.reduceat(h, first); self.dl = np.minimum.reduceat(l, first); self.dc = c[last]
        dtr = np.r_[self.dh[0] - self.dl[0], np.maximum.reduce([self.dh[1:] - self.dl[1:], np.abs(self.dh[1:] - self.dc[:-1]), np.abs(self.dl[1:] - self.dc[:-1])])]
        dcs = np.r_[0, np.cumsum(dtr)]
        self.datr = np.full(len(ks), np.nan); self.datr[19:] = (dcs[20:] - dcs[:-20]) / 20
        # H4（22:00 對齊）收市
        self.k4, self.c4 = G.h4_from_h1(t, o, h, l, c)
        self.h4j = np.searchsorted(self.k4, t + 3600 - 14400, side="right") - 1
        self._e4 = {}

    def e4slope(self, E):
        if E not in self._e4:
            e = G.ema(self.c4, E)
            j = self.h4j
            self._e4[E] = np.where(j >= E, e[np.clip(j, 0, None)] - e[np.clip(j - 1, 0, None)], 0.0)
        return self._e4[E]


def simulate(D, entries, exitL=None, exitS=None):
    """entries：按入場 index 排好嘅 (a, s, sl_dist, tp_dist|None, max_h)。回傳 [(入場 ts, s, d, R, 出場 ts)]。"""
    t, o, h, l, c = D.t, D.o, D.h, D.l, D.c
    n = len(t); out = []; busy = -1
    for a, s, d, tpd, mh in entries:
        if a <= busy or a >= n or not d or d <= 0 or math.isnan(d):
            continue
        px = o[a]; sl = px - s * d; tp = None if tpd is None else px + s * tpd
        ex = None; ex_mask = exitL if s > 0 else exitS
        for j in range(a, n):
            if t[j] - t[a] >= mh * 3600:
                ex, xi = o[j], j - 1; break
            if j > a and (o[j] - sl) * s <= 0:
                ex, xi = o[j], j; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex, xi = sl, j; break
            if tp is not None and ((h[j] >= tp) if s > 0 else (l[j] <= tp)):
                ex, xi = tp, j; break
            if ex_mask is not None and ex_mask[j] and j + 1 < n:
                ex, xi = o[j + 1], j; break
        if ex is None:
            break
        out.append((int(t[a]), s, float(d), float((s * (ex - px) - COST) / d), int(t[min(xi + 1, n - 1)])))
        busy = xi
    return out


def day_mask(D, dmask):
    m = np.zeros(len(D.t), bool); m[D.dlast[dmask]] = True
    return m


def fam_F1(D, p):
    N, k = p["N"], p["k"]; dh, dl, dc = D.dh, D.dl, D.dc; nd = len(dc)
    hiN = np.full(nd, np.nan); loN = np.full(nd, np.nan); hiH = np.full(nd, np.nan); loH = np.full(nd, np.nan)
    for d in range(N, nd):
        hiN[d] = dh[d - N:d].max(); loN[d] = dl[d - N:d].min()
    M = N // 2
    for d in range(M, nd):
        hiH[d] = dh[d - M:d].max(); loH[d] = dl[d - M:d].min()
    ent = []
    for d in range(N, nd - 1):
        s = 1 if dc[d] > hiN[d] else (-1 if dc[d] < loN[d] else 0)
        if s == 0 or (s < 0 and p["dir"] == "long"):
            continue
        ent.append((int(D.dfirst[d + 1]), s, k * D.datr[d], None, 60 * 24))
    return simulate(D, ent, day_mask(D, dc < loH), day_mask(D, dc > hiH))


def fam_F2(D, p):
    sl = D.e4slope(p["E"]); r = D.rsi14; TH = p["TH"]
    below = r <= TH; above = r >= 100 - TH
    buy = below & ~np.r_[False, below[:-1]] & (sl > 0)
    sell = above & ~np.r_[False, above[:-1]] & (sl < 0)
    ent = [(i + 1, 1 if buy[i] else -1, p["K"] * D.atr[i], p["RR"] * p["K"] * D.atr[i], 72)
           for i in np.flatnonzero(buy | sell) if i >= 20]
    return simulate(D, ent)


def fam_F3(D, p):
    L = p["L"]; dc = D.dc; nd = len(dc)
    sg = np.zeros(nd, int); sg[L:] = np.sign(dc[L:] - dc[:-L])
    ent = []
    for d in range(L + 1, nd - 1):
        if sg[d] != 0 and sg[d] != sg[d - 1] and not (sg[d] < 0 and p["dir"] == "long"):
            ent.append((int(D.dfirst[d + 1]), int(sg[d]), p["k"] * D.datr[d], None, 1e9))
    return simulate(D, ent, day_mask(D, sg < 0), day_mask(D, sg > 0))


def fam_F4(D, p):
    t, h, l, c = D.t, D.h, D.l, D.c
    hr = (t // 3600) % 24
    sess = (t + 3600) // 86400                      # 23:00 UTC 起計新一日
    ent = []
    ks, first = np.unique(sess, return_index=True)
    bounds = np.r_[first, len(t)]
    for q in range(len(ks)):
        a, b = bounds[q], bounds[q + 1]
        idx = np.arange(a, b)
        rng = idx[(hr[idx] == 23) | (hr[idx] <= 6)]
        if len(rng) < 6:
            continue
        rh, rl = h[rng].max(), l[rng].min(); w = rh - rl
        if w <= 0:
            continue
        for i in idx[(hr[idx] >= 7) & (hr[idx] <= 11)]:
            s = 1 if c[i] > rh else (-1 if c[i] < rl else 0)
            if s == 0:
                continue
            if not (s < 0 and p["dir"] == "long") and i + 1 < len(t):
                mh = 20 - (hr[i] + 1)
                ent.append((i + 1, s, p["m"] * w, p["RR"] * p["m"] * w, mh))
            break
    return simulate(D, ent)


def fam_F5(D, p):
    dc = D.dc; nd = len(dc); r2 = G.rsi(dc, 2)
    cs = np.r_[0, np.cumsum(dc)]
    sma = lambda n: np.r_[np.full(n - 1, np.nan), (cs[n:] - cs[:-n]) / n]   # noqa: E731
    s200, s5 = sma(200), sma(5)
    ent = []
    for d in range(200, nd - 1):
        s = 1 if r2[d] < p["L"] else (-1 if r2[d] > 100 - p["L"] else 0)
        if s == 0 or (s < 0 and p["dir"] == "long"):
            continue
        if p["f"] and not ((dc[d] > s200[d]) if s > 0 else (dc[d] < s200[d])):
            continue
        ent.append((int(D.dfirst[d + 1]), s, 3.0 * D.datr[d], None, 240))
    return simulate(D, ent, day_mask(D, dc > s5), day_mask(D, dc < s5))


RUN = {"F1": fam_F1, "F2": fam_F2, "F3": fam_F3, "F4": fam_F4, "F5": fam_F5}


def summ(rs):
    rs = np.asarray(rs, float)
    if not len(rs):
        return dict(n=0, avg=0.0, pf=0.0, t=0.0, sum=0.0)
    w, ls = rs[rs > 0].sum(), -rs[rs < 0].sum()
    sd = rs.std(ddof=1) if len(rs) > 1 else 0
    return dict(n=len(rs), avg=float(rs.mean()), pf=float(w / ls) if ls else float("inf"),
                t=float(rs.mean() / sd * math.sqrt(len(rs))) if sd else 0.0, sum=float(rs.sum()))


def swap_r(tr):
    return [r - SWAP_OZ * G.nights(ts, te) / d for ts, s, d, r, te in tr]


def load_duka():
    if os.path.exists(CACHE):
        z = np.load(CACHE)
        return z["t"], z["o"], z["h"], z["l"], z["c"]
    t, o, h, l, c = G.load_h1_duka()
    np.savez(CACHE, t=t, o=o, h=h, l=l, c=c)
    return t, o, h, l, c


def load_mt5_spliced(duka):
    import search as S
    m1 = S.load("mt5", "2022-08-03", "2026-10-30")
    mt = G.h1_from_m1(m1)
    ok = (mt[2] > mt[3]) | (np.r_[np.nan, mt[4][:-1]] != mt[4])
    mt = [x[ok] for x in mt]
    cut = mt[0][0]
    pre = [x[duka[0] < cut] for x in duka]          # Dukascopy 只用嚟熱身指標
    return [np.r_[a, b] for a, b in zip(pre, mt)]


def fmt(s):
    return f"{s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} t {s['t']:.2f}"


def main():
    duka = load_duka()
    D = Data(*duka)
    out = ["# XAUUSD 長期穩健策略搜尋（IDEAS #165）", "",
           f"- 數據：Dukascopy H1 {dt.datetime.fromtimestamp(int(D.t[0]), dt.timezone.utc):%Y-%m}→{dt.datetime.fromtimestamp(int(D.t[-1]), dt.timezone.utc):%Y-%m}（{len(D.t):,} 根）；每張扣 {COST} 美元；同一組合一次一張",
           f"- 滾動前向：前 {TRAIN_Y} 年揀（≥ {MIN_TRAIN_N} 張、PF ≥ {MIN_TRAIN_PF}），測下一年；樣本外 {FIRST_TEST}→{LAST_TEST}", ""]
    trades = {}
    for fam, grid in FAMILIES.items():
        f = RUN[fam[:2]]
        for gi, p in enumerate(grid):
            trades[(fam, gi)] = f(D, p)
        print(fam, "done", flush=True)
    picks, verdict = {}, {}
    out += ["## 1. 各家族滾動前向（樣本外接駁）", "",
            "| 家族 | 樣本外 | 正數年 | 2009–17 | 2018–26 | 隔夜息 −15 後 | 判 |", "|---|---|---|---|---|---|---|"]
    detail = []
    for fam, grid in FAMILIES.items():
        oos, yrs, pk = [], {}, {}
        for Y in range(FIRST_TEST, LAST_TEST + 1):
            best = None
            for gi in range(len(grid)):
                tr = [x for x in trades[(fam, gi)] if Y - TRAIN_Y <= yr(x[0]) < Y]
                s = summ([x[3] for x in tr])
                if s["n"] >= MIN_TRAIN_N and s["pf"] >= MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                    best = (gi, s["avg"])
            pk[Y] = None if best is None else best[0]
            yt = [] if best is None else [x for x in trades[(fam, best[0])] if yr(x[0]) == Y]
            oos += yt; yrs[Y] = summ([x[3] for x in yt])
        picks[fam] = pk
        s = summ([x[3] for x in oos]); sw = summ(swap_r(oos))
        h1 = summ([x[3] for x in oos if yr(x[0]) <= 2017]); h2 = summ([x[3] for x in oos if yr(x[0]) >= 2018])
        pos = sum(1 for v in yrs.values() if v["n"] and v["avg"] > 0)
        ok = dict(n=s["n"] >= 200, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, t=s["t"] >= 2.0, yrs=pos >= 11,
                  halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = (ok, oos)
        out.append(f"| {fam} | {fmt(s)} | {pos}/18 | {h1['avg']:+.3f} | {h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        detail += ["", f"### {fam}", "", "| 年 | 揀咗 | 樣本外 |", "|---|---|---|"]
        for Y in range(FIRST_TEST, LAST_TEST + 1):
            g = pk[Y]
            detail.append(f"| {Y} | {'唔做' if g is None else grid[g]} | {fmt(yrs[Y]) if yrs[Y]['n'] else '—'} |")
        # 全期固定參數：最常被揀嗰組
        sel = [g for g in pk.values() if g is not None]
        if sel:
            g = max(set(sel), key=sel.count)
            tr = trades[(fam, g)]
            yy = {}
            for x in tr:
                yy.setdefault(yr(x[0]), []).append(x[3])
            pos_fixed = sum(1 for v in yy.values() if np.mean(v) > 0)
            detail.append(f"\n- 最常被揀：{grid[g]}（{sel.count(g)} 年）；全期固定用佢：{fmt(summ([x[3] for x in tr]))}，{pos_fixed}/{len(yy)} 年正數")
    # MT5 對照
    out += ["", "## 2. 券商 MT5 對照（2022-10→2026-10，用滾動前向嗰幾年揀出嘅組合）", ""]
    try:
        M = Data(*load_mt5_spliced(duka))
        a0 = G.ts_of("2022-10-01") if hasattr(G, "ts_of") else int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
        cache = {}
        for fam, grid in FAMILIES.items():
            rs_m, rs_d = [], []
            for Y in range(2022, LAST_TEST + 1):
                g = picks[fam][Y]
                if g is None:
                    continue
                if (fam, g) not in cache:
                    cache[(fam, g)] = RUN[fam[:2]](M, grid[g])
                rs_m += [x[3] for x in cache[(fam, g)] if yr(x[0]) == Y and x[0] >= a0]
                rs_d += [x[3] for x in trades[(fam, g)] if yr(x[0]) == Y and x[0] >= a0]
            sm = summ(rs_m)
            verdict[fam][0]["mt5"] = sm["n"] > 0 and sm["avg"] > 0
            out.append(f"- {fam}：MT5 {fmt(sm)}；Dukascopy 同期 {fmt(summ(rs_d))}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}（呢項當未過）")
        for fam in FAMILIES:
            verdict[fam][0]["mt5"] = False
    passed = [f for f, (ok, _) in verdict.items() if all(ok.values())]
    out += ["", "## 3. 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}",
            "- 合格只代表可以開影子前向；934 唔改。", "", "## 4. 每年揀咗邊組", *detail, ""]
    open(os.path.join(HERE, "ROBUST_LONG.md"), "w").write("\n".join(out))
    print("\n".join(out[:40]))


if __name__ == "__main__":
    main()
