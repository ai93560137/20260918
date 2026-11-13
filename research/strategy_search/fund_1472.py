"""[IDEAS #1472] 基金層面第四批：按基金自己近期波幅調整總注碼。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1472.py → research/strategy_search/FUND_1472.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fund_1464 as F   # noqa: E402
import fund_1467 as G   # noqa: E402

OUT = os.path.join(HERE, "FUND_1472.md")


def mult(m, win, lo=0.5, hi=2.0, warm=24):
    v = m.rolling(win).std(); med = v.expanding().median(); k = (med.shift(1) / v.shift(1)).clip(lo, hi)
    k.iloc[:warm] = 1.0; return k.fillna(1.0)


def main():
    m0, idx, _ = G.base(); s0, h0 = F.stats(m0), F.halves(m0)
    L = ["# #1472：按基金近期波幅調整總注碼", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；樣本內；只讀研究", "",
         "| 版本 | 平均倍數 | 總損益 $ | 最大回落 | 總÷回落 | Sharpe | 前半 Sharpe | 後半 Sharpe |", "|---|---|---|---|---|---|---|---|",
         f"| F0 | 1.00 | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | {s0['sh']:.2f} | {h0[0]['sh']:.2f} | {h0[1]['sh']:.2f} |"]; R = {}
    for tag, k in (("6 個月（判決）", mult(m0, 6)), ("12 個月", mult(m0, 12)), ("6 個月、整數手數（1 或 2）", mult(m0, 6).round().clip(1, 2))):
        m = m0 * k; R[tag] = (F.stats(m), F.halves(m)); s, h = R[tag]
        L.append(f"| {tag} | {k.mean():.2f} | {s['tot']:+,.0f} | {s['dd']:,.0f} | {s['rd']:.2f} | {s['sh']:.2f} | {h[0]['sh']:.2f} | {h[1]['sh']:.2f} |")
    a, ah = R["6 個月（判決）"]; b, _ = R["12 個月"]; c, _ = R["6 個月、整數手數（1 或 2）"]
    g = [a["sh"] >= 1.10 * s0["sh"], a["rd"] >= 1.10 * s0["rd"], ah[0]["sh"] > h0[0]["sh"] and ah[1]["sh"] > h0[1]["sh"], b["sh"] >= s0["sh"] and b["rd"] >= s0["rd"], c["sh"] >= 1.10 * s0["sh"] and c["rd"] >= 1.10 * s0["rd"]]
    v = m0.rolling(6).std(); nx = m0.shift(-1); z = pd.DataFrame({"v": v, "n": nx}).dropna(); hi = z.v > z.v.median()
    L += ["", f"- 描述：過去 6 個月波幅高嗰半之後一個月平均 {z.n[hi].mean():+,.0f} 美元（標準差 {z.n[hi].std():,.0f}），低嗰半之後 {z.n[~hi].mean():+,.0f}（{z.n[~hi].std():,.0f}）；波幅自相關 {float(np.corrcoef(v.dropna()[:-6], v.dropna()[6:])[0, 1]):+.2f}",
          f"- 關卡 {''.join('✓' if x else '✗' for x in g)} → **{'✅ 合格' if all(g) else '❌ 唔合格'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
