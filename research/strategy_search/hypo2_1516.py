"""[IDEAS #1516–#1519] 假設 H2「月尾再平衡效應消退之後喺其他地方補返」嘅四個測試。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/hypo2_1516.py → research/strategy_search/HYPO2_1516.md"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import fund_1479 as F9       # noqa: E402
import hypo_1509 as H1       # noqa: E402
import paper_robust as PR    # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "HYPO2_1516.md")
NY = ZoneInfo("America/New_York")
PERIODS = H1.PERIODS
W0, W1 = "2010-07-01", "2026-10-31"


def per(x, a, b):
    return x[(x.index.year >= a) & (x.index.year <= b)]


def daily_leg(tk, zn, lag):
    """平日按偏離：S＝20 日 指數−美債；最低五分一做多、最高五分一做空，翌日回報；剔走翌日屬於月尾最後 5 個／月頭 3 個交易日。回傳每月加總。"""
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; b = (zn.shift(1) if lag else zn).reindex(s.index, method="ffill")
    z = pd.DataFrame({"s": s, "b": b}).dropna(); z = z[(z.index >= "2010-05-01") & (z.index <= W1)]
    z["S"] = (z.s / z.s.shift(20) - 1) - (z.b / z.b.shift(20) - 1); z["nx"] = z.s.shift(-1) / z.s - 1; z["nd"] = z.index.to_series().shift(-1)
    per_m = z.index.to_period("M"); z["pos"] = z.groupby(per_m).cumcount(); z["rev"] = z.groupby(per_m).cumcount(ascending=False)
    z["npos"] = z.pos.shift(-1); z["nrev"] = z.rev.shift(-1); z = z.dropna(subset=["S", "nx", "npos"]); z = z[z.index >= W0]
    q1, q5 = z.S.quantile(0.2), z.S.quantile(0.8); ok = (z.nrev >= 5) & (z.npos >= 3)
    x = pd.Series(np.where(z.S <= q1, z.nx, np.where(z.S >= q5, -z.nx, 0.0)), index=z.index)[ok]
    return x.groupby(pd.DatetimeIndex(z.nd[ok]).to_period("M")).sum()


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; T = {tk: H1.table(tk, zn, lag) for _, tk, lag in PR.MK}
    L = ["# #1516–#1519：假設 H2 測試（月尾再平衡效應消退之後，喺其他地方補返？）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；14 個市場；2010-07–2026-10；唔扣成本；只讀研究", ""]
    # ---- 1516
    D = pd.DataFrame({tk: daily_leg(tk, zn, lag) for _, tk, lag in PR.MK}).mean(axis=1); D = D[(D.index >= pd.Period("2010-07", "M")) & (D.index <= pd.Period("2026-10", "M"))]
    a, c = per(D, 2010, 2015), per(D, 2021, 2026); d = float(c.mean() - a.mean()); t = DR.welch(c.to_numpy(), a.to_numpy()); v = "✅ 支持" if d > 0 and t >= 2.0 else ("❌ 證偽" if d <= 0 else "未能判斷（方向啱但唔顯著）")
    L += ["## #1516 平日按偏離即時調（剔走月尾月頭）", "", "- 面板每月方向回報：" + "、".join(f"{nm} {100 * per(D, y0, y1).mean():+.3f}%（t {PM.tstat(per(D, y0, y1)):+.2f}）" for nm, y0, y1 in PERIODS) + f"；全期 {100 * D.mean():+.3f}%（t {PM.tstat(D):+.2f}）",
          f"- 2021–26 − 2010–15＝{100 * d:+.3f}%，Welch t {t:+.2f} → **{v}**", ""]
    # ---- 1517
    q_c, n_c, q_a, n_a = [], [], [], []
    for tk in T:
        z = T[tk].late; isq = z.index.month % 3 == 0; q_c += list(per(z[isq], 2021, 2026)); n_c += list(per(z[~isq], 2021, 2026)); q_a += list(per(z[isq], 2010, 2015)); n_a += list(per(z[~isq], 2010, 2015))
    d7 = float(np.mean(q_c) - np.mean(n_c)); t7 = DR.welch(np.array(q_c), np.array(n_c)); v7 = "✅ 支持" if d7 > 0 and t7 >= 2.0 else ("❌ 證偽" if d7 <= 0 else "未能判斷（方向啱但唔顯著）")
    L += ["## #1517 集中返去季尾", "", f"- 2021–26：季尾月 {100 * np.mean(q_c):+.3f}%（{len(q_c)} 個市場月）、其他月 {100 * np.mean(n_c):+.3f}%（{len(n_c)}）；差 {100 * d7:+.3f}%，Welch t {t7:+.2f} → **{v7}**",
          f"- 2010–15：季尾月 {100 * np.mean(q_a):+.3f}%、其他月 {100 * np.mean(n_a):+.3f}%；跌幅：季尾月 {100 * (np.mean(q_a) - np.mean(q_c)):+.3f}%、其他月 {100 * (np.mean(n_a) - np.mean(n_c)):+.3f}%", ""]
    # ---- 1518
    px, nm_ = F9.duka_h1("USA500IDXUSD"); s = B6.ohlc("^GSPC").c; s = s[(s > 0) & (s.index.dayofweek < 5)]; zz = T["^GSPC"]; rows = {}
    for p, g in s.groupby(s.index.to_period("M")):
        if p not in zz.index or len(g) < 16:
            continue
        side = 1.0 if zz.rel6[p] < 0 else -1.0; lh = 0.0; n = 0
        for dday in g.index[-5:]:
            a15 = px.get(int(dt.datetime(dday.year, dday.month, dday.day, 15, tzinfo=NY).timestamp())); a16 = px.get(int(dt.datetime(dday.year, dday.month, dday.day, 16, tzinfo=NY).timestamp()))
            if a15 and a16:
                lh += side * (a16 / a15 - 1); n += 1
        if n >= 4:
            rows[p] = (lh, zz.late[p] - lh)
    R = pd.DataFrame.from_dict(rows, orient="index", columns=["lh", "rest"]); ra, rc = per(R, 2012, 2015), per(R, 2021, 2026); d8 = float(rc.lh.mean() - ra.lh.mean()); t8 = DR.welch(rc.lh.to_numpy(), ra.lh.to_numpy())
    v8 = "✅ 支持" if d8 > 0 and t8 >= 2.0 else ("❌ 證偽" if d8 <= 0 else "未能判斷（方向啱但唔顯著）")
    L += ["## #1518 集中返去收市前（標普，Dukascopy 小時線）", "", f"- 有數據嘅月份 {len(R)}（{R.index[0]}–{R.index[-1]}）",
          "- 月尾 5 日「最後一個鐘」方向回報合計：" + "、".join(f"{nm} {100 * per(R, y0, y1).lh.mean():+.3f}%（{len(per(R, y0, y1))} 個月）" for nm, y0, y1 in (("2012–15", 2012, 2015), ("2016–20", 2016, 2020), ("2021–26", 2021, 2026))),
          "- 其餘時段：" + "、".join(f"{nm} {100 * per(R, y0, y1).rest.mean():+.3f}%" for nm, y0, y1 in (("2012–15", 2012, 2015), ("2016–20", 2016, 2020), ("2021–26", 2021, 2026))),
          f"- 最後一個鐘 2021–26 − 2012–15＝{100 * d8:+.3f}%，Welch t {t8:+.2f} → **{v8}**", ""]
    # ---- 1519
    nxt = {}
    for _, tk, lag in PR.MK:
        s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; gs = [(p, g) for p, g in s.groupby(s.index.to_period("M"))]; z = T[tk]; o = {}
        for i in range(len(gs) - 1):
            p, g = gs[i]; g2 = gs[i + 1][1]
            if p in z.index and len(g2) >= 5:
                o[p] = (1.0 if z.rel6[p] < 0 else -1.0) * (g2.iloc[4] / g.iloc[-1] - 1)
        nxt[tk] = pd.Series(o)
    N = pd.DataFrame(nxt).mean(axis=1); zb = pd.DataFrame({"s": B6.ohlc("^GSPC").c, "b": zn}).dropna(); rb = {}
    gs = [(p, g) for p, g in zb.groupby(zb.index.to_period("M"))]
    for i in range(1, len(gs)):
        p, g = gs[i]
        if p in T["^GSPC"].index and len(g) >= 12:
            rb[p] = (T["^GSPC"].rel6[p], g.b.iloc[-1] / g.b.iloc[-6] - 1)
    RB = pd.DataFrame.from_dict(rb, orient="index", columns=["rel", "r"])
    L += ["## #1519 描述性：延後到下個月頭、債券一邊", "", "- (a) 下個月頭 5 個交易日方向回報（14 個市場平均）：" + "、".join(f"{nm} {100 * per(N, y0, y1).mean():+.3f}%（t {PM.tstat(per(N, y0, y1)):+.2f}）" for nm, y0, y1 in PERIODS),
          "- (b) 美債月尾最後 5 日，股票跑贏月份 − 跑輸月份：" + "、".join(f"{nm} {100 * (per(RB, y0, y1).r[per(RB, y0, y1).rel >= 0].mean() - per(RB, y0, y1).r[per(RB, y0, y1).rel < 0].mean()):+.3f}%" for nm, y0, y1 in PERIODS) + "（機制預測為正）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
