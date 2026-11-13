"""[IDEAS #1463／#1466／#1469] 真倉口徑驗證：月尾股債再平衡用真倉模組 xau/trend_merebal.py（規則日曆＋方向）喺 Yahoo 日線重算。
① 規則日曆對實際交易日；② 真倉口徑（現貨指數、ZN 同日收市、扣成本同隔夜息、SP500 0.2 手＋UK100 0.1 手）嘅損益。
用法：python3 research/strategy_search/parity_merebal.py → research/strategy_search/PARITY_MEREBAL.md"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import batch6_1462 as B6     # noqa: E402
import premia_1453 as PM     # noqa: E402
import trend_merebal as M    # noqa: E402

LEGS = (("SP500", "US", "^GSPC", 0.2, 1.0, -0.000215, 0.000042), ("UK100", "UK", "^FTSE", 0.1, 1.31, -0.000204, 0.000038))   # 名、日曆、Yahoo、手數、報價貨幣兌美元、買／賣每晚隔夜息（佔價格）


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]
    L = ["# 真倉口徑驗證：月尾股債再平衡（#1463）", "", "- 數據 Yahoo 日線 2010-07 起；規則同真倉模組 `xau/trend_merebal.py` 一樣；來回成本 0.04%；隔夜息按 11-13 券商規格、每次 7 晚；只讀研究", "",
         "## ① 規則日曆對實際交易日", "", "| 日曆 | 月數 | 交易日完全一致 | 訊號日／月尾日唔一致 | 唔一致月份（突發休市） |", "|---|---|---|---|---|"]
    nets = {}; rows2 = []
    for nm, cal, tk, lots, fx, sl_, ss_ in LEGS:
        s = B6.ohlc(tk).c; s = s[s.index >= "2010-01-01"]; bad = []; kb = 0; n = 0; rows = []
        for p, g in s.groupby(s.index.to_period("M")):
            if p == s.index[-1].to_period("M"):
                continue
            act = [d.date() for d in g.index]; n += 1
            if act != M.trading_days(cal, p.year, p.month):
                bad.append(str(p))
            sig, last = M.key_days(cal, p.year, p.month); kb += (act[-6], act[-1]) != (sig, last)
            sig, last = pd.Timestamp(sig), pd.Timestamp(last); prev_s = s[s.index.to_period("M") < p]; prev_b = zn[zn.index.to_period("M") < p]
            if p < pd.Period("2010-07", "M") or sig not in s.index or last not in s.index or not len(prev_s) or not len(prev_b):
                continue
            sg = M.side(s[sig] / prev_s.iloc[-1] - 1, zn[zn.index <= sig].iloc[-1] / prev_b.iloc[-1] - 1)
            path = s[(s.index > sig) & (s.index <= last)]
            rows.append((p, sg, sg * (s[last] / s[sig] - 1) - 0.0004 + (sl_ if sg > 0 else ss_) * 7, float(((path / s[sig] - 1) * sg).min())))
        L.append(f"| {cal} | {n} | {n - len(bad)} | {kb} | {'、'.join(bad)} |")
        z = pd.DataFrame(rows, columns=["m", "sg", "r", "worst"]).set_index("m"); nets[nm] = z.r * float(s.iloc[-1]) * lots * fx
        rows2.append(f"| {nm} | {lots} | {len(z)} | {int((z.sg > 0).sum())}／{int((z.sg < 0).sum())} | {100 * z.r.mean():+.3f}% | {PM.tstat(z.r):+.2f} | {100 * z.r[z.sg > 0].mean():+.2f}%／{100 * z.r[z.sg < 0].mean():+.2f}% | {100 * z.r.min():+.1f}% | {100 * z.worst.min():+.1f}% | {int((z.worst <= -0.10).sum())} |")
    m = sum(nets.values()).dropna(); yr = m.groupby(m.index.year).sum()
    L += ["", "## ② 真倉口徑損益（扣成本同隔夜息）", "", "| 腳 | 手數 | 月數 | 做多／做空月數 | 每月淨回報 | t | 做多／做空平均 | 最差一個月 | 持倉期收市計最深 | 收市跌穿 −10% 次數 |", "|---|---|---|---|---|---|---|---|---|---|"] + rows2
    L += ["", f"- 兩隻腳合計（按而家指數水平折美元）：每月平均 {m.mean():+,.1f} 美元、標準差 {m.std():,.0f}、最差月 {m.min():+,.0f}、最好月 {m.max():+,.0f}、t {PM.tstat(m):+.2f}、正數月 {100 * (m > 0).mean():.0f}%",
          "- 按年（美元）：" + "、".join(f"{int(k)} {v:+,.0f}" for k, v in yr.items()),
          f"- 2021 年起合計 {m[m.index.year >= 2021].sum():+,.0f} 美元——近年接近打和，已照實話畀使用者知（11-13 使用者：「照行」）。", ""]
    open(os.path.join(HERE, "PARITY_MEREBAL.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
