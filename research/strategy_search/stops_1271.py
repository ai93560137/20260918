"""[IDEAS #1271] 停條件研究（描述，唔自動改設定）：現行「每本累計 ≤ −5R／≥ 12 張後 PF < 0.8／連蝕 6 張就停」喺歷史上幾常觸發？停咗之後規則係繼續蝕定係反彈？
另加 #1263 均線交叉合成嘅鄰近組合穩健度（同 #1270 對 #1268／#1269 做嘅一樣）。使用者 11-11「繼續研究」。規格以 IDEAS #1271 預先登記為準（跑之前 commit）。
數據同成交模擬同 #1270：stooq 日線黃金 1975–2026、成本 0.05%。張按入場時間排（冇平倉時間，所以累計係按入場次序，近似）。
用法：python3 research/strategy_search/stops_1271.py → research/strategy_search/STOPS_1271.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import h1_lab8 as H8            # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402
import oldgold2_1261 as O2      # noqa: E402
import oldgold_1260 as OG       # noqa: E402
import robust_1270 as RB        # noqa: E402

OUT = os.path.join(HERE, "STOPS_1271.md")
YEAR = 365.25 * 86400
VARIANTS = [("現行（−5R／PF／連蝕 6）", 5, True), ("只用 −5R", 5, False), ("只用 −8R", 8, False), ("只用 −12R", 12, False), ("只用 −15R", 15, False)]


def trigger(tr, t0, thr, extra):
    """由 t0 起開一本新簿；回傳（觸發時間, None）或者（None）——5 年內冇觸發。"""
    cum = w = ls = 0.0; n = streak = 0
    for t_, _, r in tr:
        if t_ < t0:
            continue
        if t_ > t0 + 5 * YEAR:
            return None
        cum += r; n += 1
        if r > 0:
            w += r; streak = 0
        else:
            ls -= r; streak += 1
        if cum <= -thr or (extra and ((n >= 12 and ls > 0 and w / ls < 0.8) or streak >= 6)):
            return t_
    return None


def after(tr, t_, years):
    return sum(r for x, _, r in tr if t_ < x <= t_ + years * YEAR)


def main():
    d = RB.load(); restore = OG.patch("gold")
    try:
        members = [("#1114（933）", OG.tup(H8.r1114)(d)), ("#1165（937）", OG.tup(MS3.r1165)(d)), ("#1178（939）", OG.tup(MS5.r1178)(d)),
                   ("#1263", [(a, b, r * 3) for a, b, r in O2.r1263(d)]), ("#1268", RB.topdown(d, "pb", 200, 20)), ("#1269", RB.topdown(d, "bo", 200, 20))]
        pairs = [(5, 20), (10, 50), (20, 100), (30, 150), (50, 200), (100, 300)]
        single = {p: [(int(a), int(b), float(r)) for a, b, r in O2.state_rule(d, O2.cross(*p)(O2.M3.d1ctx(d).b))] for p in pairs}
    finally:
        restore()
    starts = [OG.ts(f"{y}-01-01") for y in range(1975, 2022)]
    L = ["# 停條件研究＋#1263 鄰近組合（IDEAS #1271；描述）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；stooq 日線黃金 1975–2026；每年 1 月 1 日當做「新開一本簿」（1975–2021，共 {len(starts)} 個起點；起點重疊，唔係獨立樣本）",
         "- 「停後 3 年」＝觸發之後 3 年如果繼續行會有幾多 R；正數＝停咗反而蝕咗後面嘅利潤", ""]
    for nm, thr, extra in VARIANTS:
        L += [f"## {nm}", "", "| 規則 | 1 年內觸發 | 3 年內觸發 | 5 年內觸發 | 觸發時間中位（年） | 停後 3 年平均 R | 停後 3 年係正嘅比例 |", "|---|---|---|---|---|---|---|"]
        tot_aft = []
        for k, tr in members:
            hits = [trigger(tr, s, thr, extra) for s in starts]
            ys = [(h - s) / YEAR for h, s in zip(hits, starts) if h is not None]
            aft = [after(tr, h, 3) for h in hits if h is not None]; tot_aft += aft
            f = lambda lim: f"{sum(1 for y in ys if y <= lim) / len(starts):.0%}"  # noqa: E731
            L.append(f"| {k} | {f(1)} | {f(3)} | {f(5)} | {np.median(ys):.1f} | {np.mean(aft):+.1f} | {np.mean(np.array(aft) > 0):.0%} |" if ys else f"| {k} | 0% | 0% | 0% | — | — | — |")
        L += ["", f"- 六條合計：觸發之後 3 年平均 {np.mean(tot_aft):+.1f}R，{np.mean(np.array(tot_aft) > 0):.0%} 係正" if tot_aft else "- 冇觸發", ""]
    L += ["## #1263 鄰近組合：單一均線對（每張平均 R／PF（張數））", "", "| 均線對 | 舊黃金 1975–2004 | 新黃金 2005–2026 |", "|---|---|---|"]
    for p in pairs:
        L.append(f"| {'**' if p in ((10, 50), (20, 100), (50, 200)) else ''}SMA {p[0]}／{p[1]}{'**' if p in ((10, 50), (20, 100), (50, 200)) else ''} | {RB.cell(RB.seg(single[p], 1975, 2004))} | {RB.cell(RB.seg(single[p], 2005, 2026))} |")
    both = sum(1 for p in pairs if OG.stats(RB.seg(single[p], 1975, 2004))[1] > 0 and OG.stats(RB.seg(single[p], 2005, 2026))[1] > 0)
    L += ["", f"- 6 組均線對入面兩段每張平均都 > 0：**{both}／6**（粗體＝#1263 用嘅三組）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
