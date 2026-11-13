"""[IDEAS #1470–#1471] 基金層面第三批：兩隻機制唔同嘅非黃金腳。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1470.py → research/strategy_search/FUND_1470.md（要先跑過 fund_1464.py）"""
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
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1470.md")
FXP = [("EUR", "EURUSD=X", 0), ("GBP", "GBPUSD=X", 0), ("AUD", "AUDUSD=X", 0), ("NZD", "NZDUSD=X", 0), ("JPY", "JPY=X", 1), ("CHF", "CHF=X", 1), ("CAD", "CAD=X", 1)]
IDXS = [("NAS100", "America/New_York", 16, 0), ("GER40", "Europe/Berlin", 17, 30), ("UK100", "Europe/London", 16, 30)]


def hv(m, split):
    return F.stats(m[m.index < split]), F.stats(m[m.index >= split])


def judge(L, title, raw, m0, target, solo_ok, solo_txt, split):
    s0, h0 = F.stats(m0), hv(m0, split); leg = raw * (target / raw.std()); m1 = m0 + leg; s1, h1, lh = F.stats(m1), hv(m1, split), hv(leg, split); cr = float(np.corrcoef(leg, m0)[0, 1])
    g = [s1["sh"] >= 1.10 * s0["sh"], s1["rd"] >= 1.10 * s0["rd"], h1[0]["sh"] > h0[0]["sh"] and h1[1]["sh"] > h0[1]["sh"], cr < 0.2, lh[0]["tot"] > 0 and lh[1]["tot"] > 0]; ok = solo_ok and all(g)
    L += [f"## {title}", "", f"- 單獨關：{solo_txt} → {'✓' if solo_ok else '✗'}", "", f"| 版本（{m0.index[0]}–{m0.index[-1]}） | 總損益 $ | 最大回落 | 總÷回落 | Sharpe | 前半 Sharpe | 後半 Sharpe |", "|---|---|---|---|---|---|---|",
          f"| F0 | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | {s0['sh']:.2f} | {h0[0]['sh']:.2f} | {h0[1]['sh']:.2f} |",
          f"| F0＋呢隻腳 | {s1['tot']:+,.0f} | {s1['dd']:,.0f} | {s1['rd']:.2f} | {s1['sh']:.2f} | {h1[0]['sh']:.2f} | {h1[1]['sh']:.2f} |",
          f"| 隻腳本身 | {leg.sum():+,.0f} | {F.stats(leg)['dd']:,.0f} | {F.stats(leg)['rd']:.2f} | {F.stats(leg)['sh']:.2f} | {lh[0]['sh']:.2f} | {lh[1]['sh']:.2f} |", "",
          f"- 同 F0 每月損益相關 {cr:+.2f}；前半／後半本身損益 {lh[0]['tot']:+,.0f}／{lh[1]['tot']:+,.0f}", f"- 基金關 {''.join('✓' if v else '✗' for v in g)}；單獨關 {'✓' if solo_ok else '✗'} → **{'✅ 合格' if ok else '❌ 唔合格'}**", ""]
    return ok


def fx_leg():
    R = pd.DataFrame({n: (1 / PM.series(tk) if inv else PM.series(tk)).pct_change() for n, tk, inv in FXP}).dropna(how="all"); R = R[R.index.dayofweek < 5]
    sp = PM.series("^GSPC"); out = {}; per = {n: [] for n, _, _ in FXP}
    for p, g in R.groupby(R.index.to_period("M")):
        if len(g) < 15:
            continue
        last, prev = g.index[-1], g.index[-2]; a = sp[sp.index <= prev]; b = sp[sp.index.to_period("M") < p]
        if not len(a) or not len(b) or a.index[-1].to_period("M") != p:
            continue
        pos = 1.0 if a.iloc[-1] / b.iloc[-1] - 1 > 0 else -1.0; row = R.loc[last].dropna()
        if len(row) < 5:
            continue
        out[p] = pos * row.mean() - 0.0002
        for n in row.index:
            per[n].append(pos * row[n] - 0.0002)
    return pd.Series(out), {n: float(np.mean(v)) for n, v in per.items() if v}


def close_px(t, c, x):
    """x（UTC 秒）嗰刻嘅價＝最後一根喺 x 之前開始嘅 M1 收市；相隔超過 5 分鐘當冇。"""
    i = int(np.searchsorted(t, x, "left")) - 1
    return float(c[i]) if i >= 0 and x - int(t[i]) <= 360 else None


def idx_leg(sym, tz, hh, mm):
    parts = [DC.get(f"mt5x/{sym}_m1_{y}.npz") for y in ("2022", "2023", "2024", "2025", "2026p")]
    t = np.concatenate([p["t"] for p in parts if p is not None]); c = np.concatenate([p["c"] for p in parts if p is not None]); z = ZoneInfo(tz)
    d0 = dt.datetime.fromtimestamp(int(t[0]), z).date(); d1 = dt.datetime.fromtimestamp(int(t[-1]), z).date(); out = {}; prev = None; d = d0
    while d <= d1:
        if d.weekday() < 5:
            tc = int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=z).timestamp()); pc = close_px(t, c, tc); ps = close_px(t, c, tc - 1800)
            if pc is not None and ps is not None:
                if prev is not None and ps != prev:
                    out[pd.Timestamp(d)] = (1.0 if ps > prev else -1.0) * (pc / ps - 1) - 0.00015
                prev = pc
            else:
                prev = None
        d += dt.timedelta(days=1)
    return pd.Series(out)


def main():
    m0, idx, target = G.base(); res = {}
    L = ["# #1470–#1471：基金層面第三批（機制唔同嘅非黃金腳）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；樣本內；只讀研究", ""]
    # 1470
    x, per = fx_leg(); t_ = PM.tstat(x); h = len(x) // 2; solo = x.mean() > 0 and t_ >= 2.0 and x.iloc[:h].mean() > 0 and x.iloc[h:].mean() > 0 and sum(v > 0 for v in per.values()) >= 5
    res["1470"] = judge(L, "#1470 月尾美元對沖再平衡（7 對外匯，最後一個交易日）", x.reindex(idx).fillna(0.0), m0, target, solo,
                        f"{x.index[0]} 起 {len(x)} 個月，最後一日淨回報平均 {1e4 * x.mean():+.1f}bp、t {t_:+.2f}；前半 {1e4 * x.iloc[:h].mean():+.1f}bp、後半 {1e4 * x.iloc[h:].mean():+.1f}bp；單獨為正 {sum(v > 0 for v in per.values())}／{len(per)}（"
                        + "、".join(f"{n} {1e4 * v:+.1f}" for n, v in per.items()) + "）", pd.Period(f"{F.SPLIT}-01", "M"))
    # 1471
    S = {s: idx_leg(s, tz, hh, mm) for s, tz, hh, mm in IDXS}; D = pd.DataFrame(S); pool = D.mean(axis=1).dropna(); t_ = PM.tstat(pool); h = len(pool) // 2
    solo = pool.mean() > 0 and t_ >= 2.0 and all(D[s].mean() > 0 for s in D) and pool.iloc[:h].mean() > 0 and pool.iloc[h:].mean() > 0
    mon = pool.groupby(pool.index.to_period("M")).sum(); w = idx[idx >= pd.Period("2022-09", "M")]
    res["1471"] = judge(L, "#1471 收市前半小時動量（NAS100／GER40／UK100，券商 M1）", mon.reindex(w).fillna(0.0), m0.reindex(w), target, solo,
                        f"{pool.index[0]:%Y-%m} 起 {len(pool):,} 日，合併每日淨回報 {1e4 * pool.mean():+.2f}bp、t {t_:+.2f}；" + "、".join(f"{s} {1e4 * D[s].mean():+.2f}bp（{D[s].count()} 日，勝率 {100 * (D[s] > 0).mean():.0f}%）" for s in D)
                        + f"；前半 {1e4 * pool.iloc[:h].mean():+.2f}bp、後半 {1e4 * pool.iloc[h:].mean():+.2f}bp；未扣成本合併 {1e4 * (pool.mean() + 0.00015):+.2f}bp", pd.Period("2024-06", "M"))
    L += [f"## 總結：合格 {sum(res.values())}／2（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
