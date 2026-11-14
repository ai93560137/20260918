"""使用者 11-14：「我哋要做一啲會賺錢嘅嘢，2021年後消退嘅唔需要要做」——逐本真倉簿睇回測喺 2021 年之後仲賺唔賺（描述性，唔係新假設）。
同 fund_1464.py 同一套回測（0.01 手、美元、已平倉損益喺出場月入賬）；月尾再平衡用現貨指數、成本 0.04%（雙向同只做多）。
用法：python3 research/strategy_search/recent_books.py → research/strategy_search/RECENT_BOOKS.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import fund_1464 as F        # noqa: E402
import paper_1482 as P       # noqa: E402
import premia_1453 as PM     # noqa: E402

NAME = {"926": "926 tdflip（…63）", "942": "942 td（…69）", "940": "940 tdsurge（…69）", "937": "937 spike（…69）", "939": "939 kelt（…69）", "944": "944 h4macd（…63）", "933": "933 mobrk（…69）", "943": "943 白銀 tdsurge（…63）"}


def row(nm, m, unit):
    a, b = m[m.index.year <= 2020], m[m.index.year >= 2021]; n = (b != 0).sum()
    f = (lambda v: f"{v:+,.0f}") if unit == "$" else (lambda v: f"{100 * v:+.1f}%")
    sh = lambda x: (x.mean() / x.std() * np.sqrt(12)) if x.std() > 0 else 0.0  # noqa: E731
    return f"| {nm} | {f(a.sum())} | {sh(a):.2f} | {f(b.sum())} | {sh(b):.2f} | {PM.tstat(b):+.2f} | {int(n)} | " + "、".join(f"{y} {f(v)}" for y, v in b.groupby(b.index.year).sum().items()) + " |"


def main():
    gd, Pp, fl, ex, sd, Ps, fls = pickle.load(open(F.CACHE, "rb"))
    idx = pd.period_range("2010-07", pd.Timestamp(gd[-1][0] * 86400, unit="s").to_period("M"), freq="M")
    g, _ = F.sim_daily(gd, Pp, fl, list(F.GOLD), 1.0, 0.5, extra=ex); tr = g + F.mobrk(gd) + F.sim_daily(sd, Ps, fls, [("943", "tdsurge")], 50.0, 0.06, long_only=True)[0]
    books = sorted({q[0] for q in tr}); zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]
    L = ["# 逐本真倉簿：2021 年之後回測仲賺唔賺（描述性）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；回測 2010-07–2026-10；黃金／白銀簿 0.01 手、美元；只讀研究；回測唔等於實際成交",
         "", "| 簿 | 2010-07–2020 合計 | Sharpe | **2021–2026 合計** | **Sharpe** | **t** | 有損益月數 | 2021 起逐年 |", "|---|---|---|---|---|---|---|---|"]
    tot = pd.Series(0.0, index=idx)
    for b in books:
        m = F.monthly([q for q in tr if q[0] == b], idx); tot += m; L.append(row(NAME.get(b, b), m, "$"))
    L.append(row("**黃金／白銀 8 本合計**", tot, "$")); L += ["", "| 月尾股債再平衡（現貨指數，每月回報 %） | 2010-07–2020 合計 | Sharpe | **2021–2026 合計** | **Sharpe** | **t** | 有損益月數 | 2021 起逐年 |", "|---|---|---|---|---|---|---|---|"]
    for nm, tk in (("945 SP500", "^GSPC"), ("946 UK100", "^FTSE")):
        z, x = P.leg(tk, zn, False, "2010-07", "2026-10"); x = x.reindex(idx).fillna(0.0); lo = pd.Series(np.where(z.rel < 0, z.r - 0.0004, 0.0), index=z.index).reindex(idx).fillna(0.0)
        L.append(row(f"{nm} 雙向", x, "%")); L.append(row(f"{nm} 只做多（現行）", lo, "%"))
    L.append("")
    open(os.path.join(HERE, "RECENT_BOOKS.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
