"""[IDEAS #1245] 現行真倉＋影子 8 條等權組合測試（預先登記，跑之前 commit）。
成員：#1114、#1116（h1_lab 趨勢 sim；黃金嚴格成本 2.0，白銀 0.06）；#1165、#1174、#1178、#1224、#1232、#1234（M1 嚴格版；黃金 0.5，白銀 0.03＋最低止蝕 0.3×ATR）。
組合＝每月（按入場月，冇交易嘅月當 0）所有成員 R 加總。合格：(a) 白銀 2010–25 每月平均 > 0 而且 t ≥ 2.0；(b) 黃金 2010–2026 三段合併每月 t ≥ 2.0、三段每段每月平均 > 0；(c) 黃金 2005–09 每月平均 > 0。
用法：python3 research/strategy_search/portfolio_1245.py → research/strategy_search/PORTFOLIO_1245.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import h1_lab as HL             # noqa: E402
import h1_lab8 as H8            # noqa: E402
import indep_1235 as I1         # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1171 as MS4  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402
import strict_b_1220 as SB      # noqa: E402
import strict_b_1228 as SB2     # noqa: E402

OUT = os.path.join(HERE, "PORTFOLIO_1245.md")


def trend(fn):
    def run(d, silver=False):
        SB.set_trend_cost(0.06 if silver else 2.0)
        try:
            out = fn(B.resample(d, 3600))
        finally:
            SB.set_trend_cost(0.5)
        out = out if isinstance(out, list) else out[0]
        return [(int(a), int(b), float(c)) for a, b, c in out]
    return run


def m1(fn):
    def run(d, silver=False):
        if silver:
            I1.silver_mode(True)
        try:
            return [(int(a), int(b), float(c)) for a, b, c in fn(d)]
        finally:
            if silver:
                I1.silver_mode(False)
    return run


MEMBERS = [("#1114", trend(H8.r1114)), ("#1116", trend(H8.r1116)), ("#1165", m1(MS3.r1165)), ("#1174", m1(MS4.r1174)),
           ("#1178", m1(MS5.r1178)), ("#1224", m1(lambda d: SB.flips(d, SB.st_ichimoku))), ("#1232", m1(SB2.RULES[4][2])), ("#1234", m1(SB2.RULES[6][2]))]


def mkey(ts):
    x = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    return x.year * 12 + x.month - 1


def monthly(d, silver=False):
    t = d["t"]; k0, k1 = mkey(t[0]), mkey(t[-1]); per = {}; tot = np.zeros(k1 - k0 + 1)
    for name, fn in MEMBERS:
        tr = fn(d, silver); per[name] = (len(tr), float(np.mean([x[2] for x in tr])) if tr else 0.0)
        for ts, _, r in tr:
            k = mkey(ts)
            if k0 <= k <= k1:
                tot[k - k0] += r
    return tot, per


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def main():
    segs = [("黃金 Duka 2015–22", A.load("duka", "2015-01-01", "2022-12-31"), False), ("黃金 MT5 2023–26", A.load("mt5", "2023-01-01", "2026-10-30"), False),
            ("黃金 Duka 2010–14", A.load("duka", "2010-01-01", "2014-12-31"), False),
            ("黃金 2005–09（H1）", HL.h1("xau/sig/duka_h1/", 2005, 2009), False), ("白銀 2010–25（H1，獨立）", HL.h1("xau/sig/duka_h1_xagusd/", 2010, 2025), True)]
    L = ["# 現行真倉＋影子 8 條等權組合（IDEAS #1245）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；成員 #1114、#1116、#1165、#1174、#1178、#1224、#1232、#1234；每月 R 加總（冇交易當 0）", "",
         "| 樣本 | 月數 | 每月平均 R | 每月 t | 正數月比例 | 最差月 | 各成員（張數／每張平均 R） |", "|---|---|---|---|---|---|---|"]
    res = {}
    for name, d, silver in segs:
        tot, per = monthly(d, silver); res[name] = tot
        L.append(f"| {name} | {len(tot)} | {tot.mean():+.3f} | {tstat(tot):.2f} | {np.mean(tot > 0):.0%} | {tot.min():+.2f} | "
                 + "；".join(f"{k} {n}／{a:+.2f}" for k, (n, a) in per.items()) + " |")
    gold3 = np.concatenate([res[s[0]] for s in segs[:3]])
    a_ok = res[segs[4][0]].mean() > 0 and tstat(res[segs[4][0]]) >= 2.0
    b_ok = tstat(gold3) >= 2.0 and all(res[s[0]].mean() > 0 for s in segs[:3])
    c_ok = res[segs[3][0]].mean() > 0
    L += ["", f"- 黃金 2010–2026 三段合併：{len(gold3)} 個月，每月平均 {gold3.mean():+.3f}R，t {tstat(gold3):.2f}",
          f"- (a) 白銀獨立樣本 t ≥ 2 而且平均 > 0：{'✅' if a_ok else '❌'}；(b) 黃金合併 t ≥ 2、三段平均 > 0：{'✅' if b_ok else '❌'}；(c) 黃金 2005–09 平均 > 0：{'✅' if c_ok else '❌'}",
          f"- **判：{'✅ 組合合格' if (a_ok and b_ok and c_ok) else '❌ 組合唔合格'}**（⚠ 成員用黃金數據揀，黃金結果有選擇偏差；白銀先係主要證據）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
