"""[IDEAS #1473] 基金層面第五批：日圓「五十日」定盤前買美元。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1473.py → research/strategy_search/FUND_1473.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import data_cache as DC      # noqa: E402
import direction_1445 as DR  # noqa: E402
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1473.md")
COST = 0.00015


def gotobi(y, m):
    """嗰個月嘅五十日（平日；週末提前到星期五）。"""
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day; out = set()
    for d in (5, 10, 15, 20, 25, last):
        x = dt.date(y, m, d)
        while x.weekday() >= 5:
            x -= dt.timedelta(days=1)
        out.add(x)
    return out


def main():
    parts = [DC.get(f"mt5x/USDJPY_m1_{y}.npz") for y in ("2022", "2023", "2024", "2025", "2026p")]
    t = np.concatenate([p["t"] for p in parts if p is not None]); c = np.concatenate([p["c"] for p in parts if p is not None])
    d0 = dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc).date(); d1 = dt.datetime.fromtimestamp(int(t[-1]), dt.timezone.utc).date(); rows = []; d = d0
    while d <= d1:                                              # d＝東京日期
        if d.weekday() < 5:
            t0 = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()) - 3600   # 東京 08:00＝UTC 前一日 23:00
            a, b = F3.close_px(t, c, t0), F3.close_px(t, c, t0 + 115 * 60)
            if a is not None and b is not None:
                rows.append((pd.Timestamp(d), d in gotobi(d.year, d.month), b / a - 1))
        d += dt.timedelta(days=1)
    z = pd.DataFrame(rows, columns=["d", "g", "r"]).set_index("d"); g, o = z.r[z.g], z.r[~z.g]; net = g - COST; h = len(net) // 2
    dif = float(g.mean() - o.mean()); td = DR.welch(g.to_numpy(), o.to_numpy()); tn = PM.tstat(net)
    solo = net.mean() > 0 and tn >= 2.0 and dif > 0 and td >= 2.0 and net.iloc[:h].mean() > 0 and net.iloc[h:].mean() > 0
    m0, idx, target = G.base(); w = idx[idx >= pd.Period("2022-09", "M")]; mon = net.groupby(net.index.to_period("M")).sum().reindex(w).fillna(0.0)
    L = ["# #1473：日圓「五十日」定盤前買美元（USDJPY，券商 M1）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{z.index[0]:%Y-%m}–{z.index[-1]:%Y-%m}；東京 08:00 → 09:55；樣本內；只讀研究", ""]
    ok = F3.judge(L, "#1473 五十日買美元", mon, m0.reindex(w), target, solo,
                  f"五十日 {len(g)} 次：未扣成本平均 {1e4 * g.mean():+.2f}bp、扣成本 {1e4 * net.mean():+.2f}bp（t {tn:+.2f}）、勝率 {100 * (net > 0).mean():.0f}%；其餘 {len(o)} 日同一時段 {1e4 * o.mean():+.2f}bp；差 {1e4 * dif:+.2f}bp（t {td:+.2f}）；"
                  f"前半／後半淨 {1e4 * net.iloc[:h].mean():+.2f}／{1e4 * net.iloc[h:].mean():+.2f}bp", pd.Period("2024-06", "M"))
    by = z.groupby([z.index.year, z.g]).r.mean().unstack()
    L += ["- 按年（五十日／其餘，bp，未扣成本）：" + "；".join(f"{int(y)} {1e4 * r[True]:+.1f}／{1e4 * r[False]:+.1f}" for y, r in by.iterrows()), "", f"## 總結：{'✅ 合格' if ok else '❌ 唔合格'}", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
