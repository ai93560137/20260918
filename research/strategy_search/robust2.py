"""[IDEAS #167] XAUUSD 時間結構／事件類穩健搜尋：Dukascopy H1 2005→2026，六個家族，滾動前向（4 年揀、1 年測）。
成交引擎、扣費、滾動前向同 #166（robust_long.py）一樣；網格寫死喺 FAMILIES（預先登記，跑之前 commit）。
t 值門檻 2.5（六個家族同時測）。用法：python3 research/strategy_search/robust2.py → ROBUST2.md
"""
import datetime as dt
import itertools
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robust_long as R  # noqa: E402

T_MIN = 2.5
NY = ZoneInfo("America/New_York")

FAMILIES = {
    "S1 日內時段": [dict(h=h, H=H, dir=d) for h, H, d in itertools.product(range(24), (1, 2, 4, 8), (1, -1))],
    "S2 星期效應": [dict(w=w, dir=d) for w, d in itertools.product(range(5), (1, -1))],
    "S3 月尾月初": [dict(N=N, K=K, dir=d) for N, K, d in itertools.product((1, 2, 3), (1, 3, 5), (1, -1))],
    "S4 單根大K": [dict(k=k, mode=m, H=H) for k, m, H in itertools.product((2.0, 3.0), ("follow", "fade"), (1, 4, 12))],
    "S5 週末跳空": [dict(g=g, mode=m) for g, m in itertools.product((0.1, 0.2, 0.4), ("fade", "follow"))],
    "S6 多回望動量投票": [dict(thr=th) for th in (2, 4)],
}


class D2(R.Data):
    def __init__(self, *a):
        super().__init__(*a)
        t = self.t
        nyh = np.empty(len(t), int); nywd = np.empty(len(t), int)
        for i, ts in enumerate(t):
            x = dt.datetime.fromtimestamp(int(ts), NY)
            nyh[i] = x.hour; nywd[i] = x.weekday()
        self.nyh, self.nywd = nyh, nywd
        bd = [dt.datetime.fromtimestamp(int(t[f]) + 7200, dt.timezone.utc).date() for f in self.dfirst]   # 券商日（22:00 UTC 日界）
        self.bdate = bd
        self.bwd = np.array([d.weekday() for d in bd])
        tf = t[self.dfirst]; tl = t[self.dlast]
        self.week_first = np.r_[True, tf[1:] - tl[:-1] >= 36 * 3600]


def s1(D, p):
    idx = np.flatnonzero((D.nyh == p["h"]) & (D.nywd <= 4))
    ent = [(int(a), p["dir"], 2.0 * D.atr[a - 1], None, p["H"]) for a in idx if a >= 15]
    return R.simulate(D, ent)


def s2(D, p):
    ent = [(int(D.dfirst[d]), p["dir"], 1.5 * D.datr[d - 1], None, 24) for d in range(21, len(D.dc)) if D.bwd[d] == p["w"]]
    return R.simulate(D, ent)


def s3(D, p):
    months = {}
    for d, x in enumerate(D.bdate):
        if D.bwd[d] <= 4:
            months.setdefault((x.year, x.month), []).append(d)
    keys = sorted(months)
    mask = np.zeros(len(D.t), bool); ent = []
    for a_k, b_k in zip(keys[:-1], keys[1:]):
        cur, nxt = months[a_k], months[b_k]
        if len(cur) < p["N"] or len(nxt) < p["K"]:
            continue
        d0 = cur[-p["N"]]
        if d0 < 21:
            continue
        mask[D.dlast[nxt[p["K"] - 1]]] = True
        ent.append((int(D.dfirst[d0]), p["dir"], 3.0 * D.datr[d0 - 1], None, 1e9))
    return R.simulate(D, ent, mask, mask)


def s4(D, p):
    body = D.c - D.o
    big = np.abs(body) > p["k"] * np.r_[np.nan, D.atr[:-1]]
    ent = []
    for i in np.flatnonzero(big):
        if i < 15 or i + 1 >= len(D.t):
            continue
        s = int(np.sign(body[i])) * (1 if p["mode"] == "follow" else -1)
        ent.append((i + 1, s, 1.5 * D.atr[i], None, p["H"]))
    return R.simulate(D, ent)


def s5(D, p):
    ent = []
    for d in range(21, len(D.dc)):
        if not D.week_first[d]:
            continue
        a = int(D.dfirst[d]); gap = D.o[a] - D.dc[d - 1]
        if abs(gap) <= p["g"] * D.datr[d - 1]:
            continue
        mh = (D.t[D.dlast[d]] + 3600 - D.t[a]) / 3600
        if p["mode"] == "fade":
            ent.append((a, -int(np.sign(gap)), abs(gap), abs(gap), mh))
        else:
            ent.append((a, int(np.sign(gap)), abs(gap), None, mh))
    return R.simulate(D, ent)


def s6(D, p):
    dc = D.dc; ent = []
    for d in range(252, len(dc)):
        if not D.week_first[d]:
            continue
        v = sum(np.sign(dc[d - 1] - dc[d - 1 - L]) for L in (20, 60, 120, 250))
        if abs(v) >= p["thr"]:
            ent.append((int(D.dfirst[d]), int(np.sign(v)), 3.0 * D.datr[d - 1], None, 168))
    return R.simulate(D, ent)


RUN = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6}


def main():
    duka = R.load_duka()
    D = D2(*duka)
    Y0, Y1 = R.FIRST_TEST, R.LAST_TEST
    out = ["# XAUUSD 時間結構／事件類穩健搜尋（IDEAS #167）", "",
           f"- 數據：Dukascopy H1 {len(D.t):,} 根；成交同 #166；每張扣 {R.COST} 美元；t 值門檻 {T_MIN}",
           f"- 滾動前向：前 {R.TRAIN_Y} 年揀（≥ {R.MIN_TRAIN_N} 張、PF ≥ {R.MIN_TRAIN_PF}），測下一年；樣本外 {Y0}→{Y1}", "",
           "## 1. 各家族滾動前向（樣本外接駁）", "",
           "| 家族 | 樣本外 | 正數年 | 2009–17 | 2018–26 | 隔夜息 −15 後 | 判 |", "|---|---|---|---|---|---|---|"]
    trades, picks, verdict, detail = {}, {}, {}, []
    for fam, grid in FAMILIES.items():
        for gi, p in enumerate(grid):
            trades[(fam, gi)] = RUN[fam[:2]](D, p)
        print(fam, "done", flush=True)
        oos, yrs, pk = [], {}, {}
        for Y in range(Y0, Y1 + 1):
            best = None
            for gi in range(len(grid)):
                s = R.summ([x[3] for x in trades[(fam, gi)] if Y - R.TRAIN_Y <= R.yr(x[0]) < Y])
                if s["n"] >= R.MIN_TRAIN_N and s["pf"] >= R.MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                    best = (gi, s["avg"])
            pk[Y] = None if best is None else best[0]
            yt = [] if best is None else [x for x in trades[(fam, best[0])] if R.yr(x[0]) == Y]
            oos += yt; yrs[Y] = R.summ([x[3] for x in yt])
        picks[fam] = pk
        s = R.summ([x[3] for x in oos]); sw = R.summ(R.swap_r(oos))
        h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
        pos = sum(1 for v in yrs.values() if v["n"] and v["avg"] > 0)
        ok = dict(n=s["n"] >= 200, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, t=s["t"] >= T_MIN, yrs=pos >= 11,
                  halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = ok
        out.append(f"| {fam} | {R.fmt(s)} | {pos}/18 | {h1['avg']:+.3f} | {h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        detail += ["", f"### {fam}", "", "| 年 | 揀咗 | 樣本外 |", "|---|---|---|"]
        for Y in range(Y0, Y1 + 1):
            g = pk[Y]
            detail.append(f"| {Y} | {'唔做' if g is None else grid[g]} | {R.fmt(yrs[Y]) if yrs[Y]['n'] else '—'} |")
        sel = [g for g in pk.values() if g is not None]
        if sel:
            g = max(set(sel), key=sel.count); tr = trades[(fam, g)]; yy = {}
            for x in tr:
                yy.setdefault(R.yr(x[0]), []).append(x[3])
            detail.append(f"\n- 最常被揀：{grid[g]}（{sel.count(g)} 年）；全期固定用佢：{R.fmt(R.summ([x[3] for x in tr]))}，"
                          f"{sum(1 for v in yy.values() if np.mean(v) > 0)}/{len(yy)} 年正數（事後，唔算數）")
    out += ["", "## 2. 券商 MT5 對照（2022-10→2026-10，用滾動前向嗰幾年揀出嘅組合）", ""]
    try:
        M = D2(*R.load_mt5_spliced(duka))
        a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
        cache = {}
        for fam, grid in FAMILIES.items():
            rm, rd = [], []
            for Y in range(2022, Y1 + 1):
                g = picks[fam][Y]
                if g is None:
                    continue
                if (fam, g) not in cache:
                    cache[(fam, g)] = RUN[fam[:2]](M, grid[g])
                rm += [x[3] for x in cache[(fam, g)] if R.yr(x[0]) == Y and x[0] >= a0]
                rd += [x[3] for x in trades[(fam, g)] if R.yr(x[0]) == Y and x[0] >= a0]
            sm = R.summ(rm); verdict[fam]["mt5"] = sm["n"] > 0 and sm["avg"] > 0
            out.append(f"- {fam}：MT5 {R.fmt(sm)}；Dukascopy 同期 {R.fmt(R.summ(rd))}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}（呢項當未過）")
        for fam in FAMILIES:
            verdict[fam]["mt5"] = False
    passed = [f for f, ok in verdict.items() if all(ok.values())]
    out += ["", "## 3. 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}",
            "- 合格只代表可以開影子前向；934 唔改。", "", "## 4. 每年揀咗邊組", *detail, ""]
    open(os.path.join(HERE, "ROBUST2.md"), "w").write("\n".join(out))
    print("\n".join(out[:30]))


if __name__ == "__main__":
    main()
