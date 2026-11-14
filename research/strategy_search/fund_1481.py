"""[IDEAS #1481] 基金層面第九批：月尾股債再平衡喺亞洲指數（日經＋ASX200）。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1481.py → research/strategy_search/FUND_1481.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402

OUT = os.path.join(HERE, "FUND_1481.md")
COST = 0.0004


def leg(tk, zn, lag, idx):
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]
    b = (zn.shift(1) if lag else zn).reindex(s.index, method="ffill")           # 亞洲：只用前一個交易日嘅美債收市
    z = B6.rebal(s, b); z = z[z.index >= idx[0]]
    return z, pd.Series(np.where(z.rel < 0, 1.0, -1.0) * z.r.to_numpy() - COST, index=z.index)


def main():
    m0, idx, target = G.base(); zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]
    Z = {}; lo_all, hi_all, each = [], [], []
    for nm, tk in (("日經", "^N225"), ("ASX200", "^AXJO")):
        z, x = leg(tk, zn, True, idx); lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; lo_all += list(lo); hi_all += list(hi)
        each.append((nm, float(lo.mean() - hi.mean()), len(lo), len(hi), float(x.mean()))); Z[nm] = x
    st = pd.DataFrame(Z).mean(axis=1).reindex(idx).fillna(0.0); d0 = float(np.mean(lo_all) - np.mean(hi_all)); t_ = DR.welch(np.array(lo_all), np.array(hi_all))
    solo = d0 > 0 and t_ >= 2.0 and all(v[1] > 0 for v in each) and st.mean() > 0
    us = leg("^GSPC", zn, False, idx)[1].reindex(idx).fillna(0.0); eu = pd.DataFrame({k: leg(tk, zn, False, idx)[1] for k, tk in (("d", "^GDAXI"), ("f", "^FTSE"))}).mean(axis=1).reindex(idx).fillna(0.0)
    cu, ce = float(np.corrcoef(st, us)[0, 1]), float(np.corrcoef(st, eu)[0, 1])
    L = ["# #1481：基金層面第九批（月尾股債再平衡喺亞洲指數：日經＋ASX200）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；美債期貨用前一個交易日收市；來回成本 {100 * COST:.2f}%；樣本內；只讀研究", ""]
    ok = F3.judge(L, "#1481 月尾股債再平衡喺亞洲指數", st, m0, target, solo,
                  f"跑輸月份 − 跑贏月份 最後 5 日回報差 {100 * d0:+.3f}%（Welch t {t_:+.2f}）；" + "、".join(f"{n} 差 {100 * d:+.3f}%（跑輸 {a}／跑贏 {b} 個月，策略每月淨 {100 * m:+.3f}%）" for n, d, a, b, m in each)
                  + f"；合併策略每月淨 {100 * st.mean():+.3f}%", pd.Period(f"{F.SPLIT}-01", "M"))
    same = max(cu, ce) > 0.7
    L += [f"- 同 #1466（美國，現貨標普版）每月相關 {cu:+.2f}、同 #1469（歐洲）{ce:+.2f}（任何一個 > 0.7 當同一條）→ {'同一條，唔另計' if same else '可以另計'}", "",
          "- 按年策略淨回報合計（%）：" + "；".join(f"{y} {100 * v:+.1f}" for y, v in st.groupby(st.index.year).sum().items()), "",
          f"## 總結：{'✅ 合格' if ok and not same else '❌ 唔合格'}", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
