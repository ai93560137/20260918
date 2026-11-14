"""[IDEAS #1477–#1478] 基金層面第七批：股指日內「噪音區」突破順勢。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1477.py → research/strategy_search/FUND_1477.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import data_cache as DC      # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1477.md")
COST = 0.00015
LOOK = 14
MKT = {"NAS100": ("America/New_York", (9, 30), (16, 0)), "GER40": ("Europe/Berlin", (9, 0), (17, 30)), "UK100": ("Europe/London", (8, 0), (16, 30))}
SPLIT = pd.Period("2024-06", "M")


def grid(sym):
    """每個交易日：開市、每 30 分鐘檢查點、收市嘅價（缺任何一個就成日唔要）。"""
    tz, (oh, om), (ch, cm) = MKT[sym]; z = ZoneInfo(tz); n = ((ch * 60 + cm) - (oh * 60 + om)) // 30
    parts = [DC.get(f"mt5x/{sym}_m1_{y}.npz") for y in ("2022", "2023", "2024", "2025", "2026p")]
    t = np.concatenate([p["t"] for p in parts if p is not None]); c = np.concatenate([p["c"] for p in parts if p is not None])
    d = dt.datetime.fromtimestamp(int(t[0]), z).date(); d1 = dt.datetime.fromtimestamp(int(t[-1]), z).date(); rows = {}
    while d <= d1:
        if d.weekday() < 5:
            t0 = int(dt.datetime(d.year, d.month, d.day, oh, om, tzinfo=z).timestamp()); px = [F3.close_px(t, c, t0 + 1800 * k) for k in range(n + 1)]
            if all(v is not None for v in px) and len(set(px)) > 3:
                rows[pd.Timestamp(d)] = px
        d += dt.timedelta(days=1)
    return pd.DataFrame.from_dict(rows, orient="index")


def run(sym, cost):
    g = grid(sym); n = g.shape[1] - 1; dev = g.div(g[0], axis=0).sub(1).abs(); sig = dev.rolling(LOOK).mean().shift(1); pc = g[n].shift(1); out = {}; ntr = 0
    for d in g.index[LOOK + 1:]:
        p = g.loc[d].to_numpy(); s = sig.loc[d].to_numpy()
        if np.isnan(s[1:n]).any() or np.isnan(pc[d]):
            continue
        hi0, lo0 = max(p[0], pc[d]), min(p[0], pc[d]); pos = 0; r = 0.0
        for k in range(1, n + 1):
            r += pos * (p[k] / p[k - 1] - 1)
            new = 0 if k == n else (1 if p[k] > hi0 * (1 + s[k]) else (-1 if p[k] < lo0 * (1 - s[k]) else 0))
            if new != pos:
                if new != 0:
                    r -= cost; ntr += 1                      # 每次開倉連平倉收一次成本（反手＝兩次）
                pos = new
        out[d] = r
    return pd.Series(out), ntr


def main():
    m0, idx, target = G.base(); w = idx[idx >= pd.Period("2022-09", "M")]; res = {}
    L = ["# #1477–#1478：基金層面第七批（股指日內「噪音區」突破順勢，券商 M1）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；樣本內；只讀研究；每次開倉連平倉成本 {100 * COST:.3f}%，另報加倍", ""]

    def hm(x):
        a, b = x[x.index < "2024-06-01"], x[x.index >= "2024-06-01"]; return float(a.mean()), float(b.mean())

    def desc(x, x2, ntr):
        a, b = hm(x); return (f"{x.index[0]:%Y-%m}–{x.index[-1]:%Y-%m} {len(x):,} 日、{ntr:,} 次交易；每日淨 {1e4 * x.mean():+.2f}bp（t {PM.tstat(x):+.2f}）、有交易日勝率 {100 * (x[x != 0] > 0).mean():.0f}%、最差日 {100 * x.min():+.2f}%；"
                             f"前半／後半 {1e4 * a:+.2f}／{1e4 * b:+.2f}bp；成本加倍 {1e4 * x2.mean():+.2f}bp（t {PM.tstat(x2):+.2f}）")

    x, ntr = run("NAS100", COST); x2, _ = run("NAS100", 2 * COST); a, b = hm(x)
    solo = x.mean() > 0 and PM.tstat(x) >= 2.0 and a > 0 and b > 0 and x2.mean() > 0
    mon = x.groupby(x.index.to_period("M")).sum().reindex(w).fillna(0.0)
    res["1477"] = F3.judge(L, "#1477 納指日內噪音區突破順勢（NAS100）", mon, m0.reindex(w), target, solo, desc(x, x2, ntr), SPLIT)
    by = x.groupby(x.index.year).sum(); L += ["- 按年淨回報合計（%）：" + "；".join(f"{y} {100 * v:+.1f}" for y, v in by.items()), ""]
    S = {}; S2 = {}; nt = 0
    for s in ("GER40", "UK100"):
        S[s], k = run(s, COST); S2[s], _ = run(s, 2 * COST); nt += k
    D = pd.DataFrame(S); pool = D.mean(axis=1); p2 = pd.DataFrame(S2).mean(axis=1); a, b = hm(pool)
    solo = pool.mean() > 0 and PM.tstat(pool) >= 2.0 and all(D[s].mean() > 0 for s in D) and a > 0 and b > 0 and p2.mean() > 0
    mon = pool.groupby(pool.index.to_period("M")).sum().reindex(w).fillna(0.0)
    res["1478"] = F3.judge(L, "#1478 歐洲股指日內噪音區突破順勢（GER40＋UK100 等權）", mon, m0.reindex(w), target, solo,
                           desc(pool, p2, nt) + "；" + "、".join(f"{s} {1e4 * D[s].mean():+.2f}bp（t {PM.tstat(D[s].dropna()):+.2f}）" for s in D), SPLIT)
    L += [f"## 總結：合格 {sum(res.values())}／2（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
