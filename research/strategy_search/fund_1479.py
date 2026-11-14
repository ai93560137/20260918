"""[IDEAS #1479–#1480] 基金層面第八批：股指日內順勢（每小時版），Dukascopy 長歷史獨立再驗。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，落數據之前 commit）。
用法：python3 research/strategy_search/fund_1479.py → research/strategy_search/FUND_1479.md（要先跑過 fund_1464.py；Dukascopy H1 由 workflow xau_duka_h1.yml 落）"""
import datetime as dt
import math
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import data_cache as DC      # noqa: E402
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1479.md")
COST = 0.00015
LOOK = 14
NY = ZoneInfo("America/New_York")
HOURS = range(10, 17)                       # 10:00（O）…16:00（平）
CUT = pd.Timestamp("2022-08-01")
SPLIT = pd.Period(f"{F.SPLIT}-01", "M")


def duka_h1(sym):
    """GCS xau/sig/duka_h1_<sym>/<YYYY-MM>.json → {utc 秒: 開市價}；每個月檔嘅價格除數可能唔同，用月頭／上月尾比例校返（只差 10 嘅次方）。"""
    import gb_rulesim as gb
    g = gb.Gcs(); out = {}; last = None; months = 0
    for nm in sorted(g.list(f"xau/sig/duka_h1_{sym.lower()}/")):
        rows = [r for r in (g.read_json(nm) or []) if r[2] != r[3]]
        if not rows:
            continue
        k = 1.0 if last is None else 10 ** round(math.log10(rows[0][1] / last))
        for r in rows:
            out[int(r[0])] = r[1] / k
        last = rows[-1][4] / k; months += 1
    return out, months


def grid_duka(px):
    days = sorted({dt.datetime.fromtimestamp(t, NY).date() for t in px}); rows = {}
    for d in days:
        if d.weekday() < 5:
            v = [px.get(int(dt.datetime(d.year, d.month, d.day, h, tzinfo=NY).timestamp())) for h in HOURS]
            if all(x is not None for x in v) and len(set(v)) > 3:
                rows[pd.Timestamp(d)] = v
    return pd.DataFrame.from_dict(rows, orient="index")


def grid_m1(sym):
    parts = [DC.get(f"mt5x/{sym}_m1_{y}.npz") for y in ("2022", "2023", "2024", "2025", "2026p")]
    t = np.concatenate([p["t"] for p in parts if p is not None]); c = np.concatenate([p["c"] for p in parts if p is not None])
    d = dt.datetime.fromtimestamp(int(t[0]), NY).date(); d1 = dt.datetime.fromtimestamp(int(t[-1]), NY).date(); rows = {}
    while d <= d1:
        if d.weekday() < 5:
            v = [F3.close_px(t, c, int(dt.datetime(d.year, d.month, d.day, h, tzinfo=NY).timestamp())) for h in HOURS]
            if all(x is not None for x in v) and len(set(v)) > 3:
                rows[pd.Timestamp(d)] = v
        d += dt.timedelta(days=1)
    return pd.DataFrame.from_dict(rows, orient="index")


def run(g, cost):
    n = g.shape[1] - 1; dev = g.div(g[0], axis=0).sub(1).abs(); sig = dev.rolling(LOOK).mean().shift(1); pc = g[n].shift(1); out = {}; ntr = 0
    for d in g.index[LOOK + 1:]:
        p = g.loc[d].to_numpy(); s = sig.loc[d].to_numpy()
        if np.isnan(s[1:n]).any() or np.isnan(pc[d]) or (d - g.index[g.index.get_loc(d) - 1]).days > 5:
            continue
        hi0, lo0 = max(p[0], pc[d]), min(p[0], pc[d]); pos = 0; r = 0.0
        for k in range(1, n + 1):
            r += pos * (p[k] / p[k - 1] - 1)
            new = 0 if k == n else (1 if p[k] > hi0 * (1 + s[k]) else (-1 if p[k] < lo0 * (1 - s[k]) else 0))
            if new != pos:
                if new != 0:
                    r -= cost; ntr += 1
                pos = new
        out[d] = r
    return pd.Series(out), ntr


def hm(x, cut):
    a, b = x[x.index < cut], x[x.index >= cut]; return float(a.mean()), float(b.mean())


def desc(x, x2, ntr, cut):
    a, b = hm(x, cut)
    return (f"{x.index[0]:%Y-%m}–{x.index[-1]:%Y-%m} {len(x):,} 日、{ntr:,} 次交易；每日淨 {1e4 * x.mean():+.2f}bp（t {PM.tstat(x):+.2f}）、有交易日勝率 {100 * (x[x != 0] > 0).mean():.0f}%、最差日 {100 * x.min():+.2f}%；"
            f"前半／後半 {1e4 * a:+.2f}／{1e4 * b:+.2f}bp；成本加倍 {1e4 * x2.mean():+.2f}bp（t {PM.tstat(x2):+.2f}）")


def main():
    m0, idx, target = G.base(); res = {}
    L = ["# #1479–#1480：基金層面第八批（股指日內順勢每小時版，Dukascopy H1 長歷史）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只讀研究；每次開倉連平倉成本 {100 * COST:.3f}%，另報加倍", ""]
    # ---- 1479 NAS100
    px, nm = duka_h1("USATECHIDXUSD"); gd = grid_duka(px); xd, nd = run(gd, COST); xd2, _ = run(gd, 2 * COST)
    oos, oos2 = xd[xd.index < CUT], xd2[xd2.index < CUT]; mid = oos.index[len(oos) // 2]; a, b = hm(oos, mid)
    ga = oos.mean() > 0 and PM.tstat(oos) >= 2.0 and a > 0 and b > 0 and oos2.mean() > 0
    gm = grid_m1("NAS100"); xm, nmm = run(gm, COST); xm2, _ = run(gm, 2 * COST); xm = xm[xm.index >= CUT]; gb_ = xm.mean() > 0
    ov = pd.concat([xd, xm], axis=1).dropna(); full = pd.concat([oos, xm]).sort_index()
    L += [f"- Dukascopy USATECHIDXUSD：{nm} 個月檔、{len(gd):,} 個完整交易日（{gd.index[0]:%Y-%m-%d}–{gd.index[-1]:%Y-%m-%d}）",
          f"- (a) 樣本外（–2022-07）：{desc(oos, oos2, nd, mid)} → {'✓' if ga else '✗'}",
          f"- (b) 券商 M1 2022-08 起同一規則：{len(xm):,} 日每日淨 {1e4 * xm.mean():+.2f}bp（t {PM.tstat(xm):+.2f}）；成本加倍 {1e4 * xm2[xm2.index >= CUT].mean():+.2f}bp → {'✓' if gb_ else '✗'}",
          f"- 重疊期 Dukascopy 對券商每日損益相關 {ov.corr().iloc[0, 1]:+.2f}（{len(ov)} 日）", ""]
    w = idx[idx >= full.index[0].to_period("M") + 1]; mon9 = full.groupby(full.index.to_period("M")).sum().reindex(w).fillna(0.0)
    res["1479"] = F3.judge(L, "#1479 納指日內順勢每小時版（Dukascopy ＋ 2022-08 起券商）", mon9, m0.reindex(w), target, ga and gb_, "見上 (a)(b)", SPLIT)
    by = full.groupby(full.index.year).sum(); L += ["- 按年淨回報合計（%）：" + "；".join(f"{y} {100 * v:+.1f}" for y, v in by.items()), ""]
    # ---- 1480 SP500
    px, nm = duka_h1("USA500IDXUSD"); gs = grid_duka(px); xs, ns = run(gs, COST); xs2, _ = run(gs, 2 * COST); a, b = hm(xs, f"{F.SPLIT}-01-01")
    solo = xs.mean() > 0 and PM.tstat(xs) >= 2.0 and a > 0 and b > 0 and xs2.mean() > 0
    L += [f"- Dukascopy USA500IDXUSD：{nm} 個月檔、{len(gs):,} 個完整交易日（{gs.index[0]:%Y-%m-%d}–{gs.index[-1]:%Y-%m-%d}）", ""]
    w2 = idx[idx >= xs.index[0].to_period("M") + 1]; mon0 = xs.groupby(xs.index.to_period("M")).sum().reindex(w2).fillna(0.0)
    ok = F3.judge(L, "#1480 標普日內順勢每小時版（Dukascopy）", mon0, m0.reindex(w2), target, solo, desc(xs, xs2, ns, f"{F.SPLIT}-01-01"), SPLIT)
    cw = w.intersection(w2); cr = float(np.corrcoef(mon9.reindex(cw), mon0.reindex(cw))[0, 1])
    L[-1:-1] = [f"- 同 #1479 每月相關 {cr:+.2f}（> 0.7 當同一條，只計一條）"]; res["1480"] = ok
    by = xs.groupby(xs.index.year).sum(); L += ["- 按年淨回報合計（%）：" + "；".join(f"{y} {100 * v:+.1f}" for y, v in by.items()), ""]
    n_ok = sum(res.values()) - (1 if all(res.values()) and cr > 0.7 else 0)
    L += [f"## 總結：合格 {n_ok}／2（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + ("；兩條相關 > 0.7 只計一條" if all(res.values()) and cr > 0.7 else "") + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
