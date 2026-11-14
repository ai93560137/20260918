"""[IDEAS #1482–#1493 附錄] 月尾股債再平衡穩健度（唔係合格門檻，只係論文附錄）：美債改用前一個交易日（排除時差偷睇）、剔走 2020、剔走最好 3 個月、分段。
用法：python3 research/strategy_search/paper_robust.py → research/strategy_search/PAPER_ROBUST.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import paper_1482 as P       # noqa: E402
import premia_1453 as PM     # noqa: E402

MK = [("美國", "^GSPC", False), ("德國", "^GDAXI", False), ("英國", "^FTSE", False), ("日本", "^N225", True), ("澳洲", "^AXJO", True), ("加拿大", "^GSPTSE", False), ("瑞士", "^SSMI", False), ("法國", "^FCHI", False),
      ("香港", "^HSI", True), ("韓國", "^KS11", True), ("印度", "^BSESN", True), ("台灣", "^TWII", True), ("新加坡", "^STI", True), ("巴西", "^BVSP", False)]


def stat(z):
    lo, hi = z.r[z.rel < 0].to_numpy(), z.r[z.rel >= 0].to_numpy(); return 100 * (lo.mean() - hi.mean()), DR.welch(lo, hi)


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]
    L = ["# 月尾股債再平衡：穩健度附錄（2010-07–2026-10，14 個市場）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；唔係合格門檻；「差」＝股票跑輸債券月份 − 跑贏月份 嘅最後 5 日指數回報", "",
         "| 市場 | 基準 差（t） | 美債一律用前一日 差（t） | 剔走 2020 差（t） | 策略每月淨（t） | 剔走最好 3 個月後每月淨 | 2010–17／2018–26 每月淨 | 做多月份淨／做空月份淨 |", "|---|---|---|---|---|---|---|---|"]
    for nm, tk, lag in MK:
        z, x = P.leg(tk, zn, lag, "2010-07", "2026-10"); zl, _ = P.leg(tk, zn, True, "2010-07", "2026-10"); z20 = z[z.index.year != 2020]
        d, t = stat(z); dl, tl = stat(zl); d2, t2 = stat(z20); xs = np.sort(x.to_numpy())[:-3]; a, b = x[x.index.year < 2018], x[x.index.year >= 2018]
        L.append(f"| {nm} {tk} | {d:+.3f}%（{t:+.2f}） | {dl:+.3f}%（{tl:+.2f}） | {d2:+.3f}%（{t2:+.2f}） | {100 * x.mean():+.3f}%（{PM.tstat(x):+.2f}） | {100 * xs.mean():+.3f}% | {100 * a.mean():+.3f}%／{100 * b.mean():+.3f}% | "
                 f"{100 * x[z.rel < 0].mean():+.3f}%／{100 * x[z.rel >= 0].mean():+.3f}% |")
    L.append("")
    open(os.path.join(HERE, "PAPER_ROBUST.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
