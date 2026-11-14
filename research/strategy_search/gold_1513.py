"""[IDEAS #1513–#1515] 已合格未上真倉嘅 H4 黃金規則（#1404／#1408／#1420）加入基金嘅邊際貢獻。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/gold_1513.py → research/strategy_search/GOLD_1513.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import fund_1464 as F        # noqa: E402
import h4wide_1402 as H      # noqa: E402

OUT = os.path.join(HERE, "GOLD_1513.md")
CAND = [("1513", "#1404 H4 重拾 SMA20", "PB"), ("1514", "#1408 H4 破 20 根高位", "BO"), ("1515", "#1420 H4 MACD 柱轉向（方向變先平）", "MACD")]


def book(E, tl, kind, tag):
    """同 944 一樣嘅做法：逐個候選訊號用引擎行到出場（X3：冇 TP、日線方向變先平）；一次只揸一張。回傳 fund_1464 格式嘅成交。"""
    cand = np.flatnonzero(E.elig & (((E.st > 0) & tl[1][kind]) | ((E.st < 0) & tl[-1][kind]))); out = []; free = -1
    for i in cand:
        t0, t1, sg, R = E.go(np.array([int(i)]), None, None, False)[0]
        if int(t0) < free:
            continue
        out.append((tag, int(t0), int(t1), int(sg), float(R * E.risk[i]), float(E.risk[i]))); free = int(t1)
    return out


def sh(m):
    return float(m.mean() / m.std() * np.sqrt(12)) if m.std() > 0 else 0.0


def main():
    gd, P, fl, ex, sd, Ps, fls = pickle.load(open(F.CACHE, "rb")); idx = pd.period_range("2010-07", pd.Timestamp(gd[-1][0] * 86400, unit="s").to_period("M"), freq="M")
    g, _ = F.sim_daily(gd, P, fl, list(F.GOLD), 1.0, 0.5, extra=ex); f0 = g + F.mobrk(gd) + F.sim_daily(sd, Ps, fls, [("943", "tdsurge")], 50.0, 0.06, long_only=True)[0]
    m0 = F.monthly(f0, idx); s0, h0 = F.stats(m0), F.halves(m0); m944 = F.monthly([q for q in f0 if q[0] == "944"], idx)
    E, _, tl = H.eng(); res = {}; legs = {}
    L = ["# #1513–#1515：已合格未上真倉嘅 H4 黃金規則，加入基金嘅邊際貢獻", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；0.01 手、美元；已平倉損益喺出場月入賬；只讀研究",
         f"- F0（現有 8 本）：總 {s0['tot']:+,.0f}、最大回落 {s0['dd']:,.0f}、總÷回落 {s0['rd']:.2f}、Sharpe {s0['sh']:.2f}（前半 {h0[0]['sh']:.2f}／後半 {h0[1]['sh']:.2f}）", "",
         "| 編號 | 規則 | 張數 | 隻腳合計 $ | 前半／後半 $ | 2021–26 $ | 同 944 相關 | 同 F0 相關 | 加入後 Sharpe | 加入後 總÷回落 | 前半／後半 Sharpe | 關卡 ①②③④⑤ | 判決 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for tag, nm, kind in CAND:
        tr = book(E, tl, kind, tag); m = F.monthly(tr, idx); legs[tag] = m; m1 = m0 + m; s1, h1, lh = F.stats(m1), F.halves(m1), F.halves(m); rec = float(m[m.index.year >= 2021].sum())
        c9, c0 = float(np.corrcoef(m, m944)[0, 1]), float(np.corrcoef(m, m0)[0, 1])
        gts = [s1["sh"] >= 1.05 * s0["sh"], s1["rd"] >= 1.05 * s0["rd"], h1[0]["sh"] >= h0[0]["sh"] and h1[1]["sh"] >= h0[1]["sh"], lh[0]["tot"] > 0 and lh[1]["tot"] > 0 and rec > 0, c9 < 0.8]; res[tag] = all(gts)
        L.append(f"| #{tag} | {nm} | {len(tr)} | {m.sum():+,.0f} | {lh[0]['tot']:+,.0f}／{lh[1]['tot']:+,.0f} | {rec:+,.0f} | {c9:+.2f} | {c0:+.2f} | {s1['sh']:.2f}（{100 * (s1['sh'] / s0['sh'] - 1):+.0f}%） | {s1['rd']:.2f}（{100 * (s1['rd'] / s0['rd'] - 1):+.0f}%） | {h1[0]['sh']:.2f}／{h1[1]['sh']:.2f} | {''.join('✓' if v else '✗' for v in gts)} | {'✅' if res[tag] else '❌'} |")
    ma = m0 + sum(legs.values()); sa, ha = F.stats(ma), F.halves(ma)
    L += ["", f"- 三條一齊加（只作描述）：總 {sa['tot']:+,.0f}、最大回落 {sa['dd']:,.0f}、總÷回落 {sa['rd']:.2f}、Sharpe {sa['sh']:.2f}（前半 {ha[0]['sh']:.2f}／後半 {ha[1]['sh']:.2f}）",
          "- 三條之間每月相關：" + "、".join(f"#{a}–#{b} {np.corrcoef(legs[a], legs[b])[0, 1]:+.2f}" for i, a in enumerate(legs) for b in list(legs)[i + 1:]), "",
          f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
