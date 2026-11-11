"""[IDEAS #1267] 方法 E 補充：#1263／#1264／#1266（舊黃金 1975–2004「方向一致」但 t 未夠）放落 2010–2026 黃金 M1 嚴格版確認。
使用者 11-11「同意，跑 #1263、#1264、#1266 確認」——明知跳過第一關顯著度，改用「方向一致」標準。規格以 IDEAS #1267 預先登記為準（跑之前 commit；規則同參數同 oldgold2_1261 一模一樣）。
合格：三段（Duka 2015–22、MT5 2023–26、Duka 2010–14）每段每筆平均 > 0（每段 ≥ 5 筆）而且三段合併 PF ≥ 1.15。成本 0.5 美元、最低止蝕 max(3 美元, 0.3×ATR)（同之前 M1 嚴格版）。
用法：python3 research/strategy_search/confirm_1267.py → research/strategy_search/CONFIRM_1267.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import oldgold2_1261 as O2      # noqa: E402

OUT = os.path.join(HERE, "CONFIRM_1267.md")
RULES = [("#1263", "均線交叉合成", O2.r1263, 3), ("#1264", "12 個月動量（每月換倉）", O2.r1264, 1), ("#1266", "週線 4／2 突破", O2.r1266, 1)]
SEGS = [("① Duka 2015–22", "duka", "2015-01-01", "2022-12-31"), ("② MT5 2023–26", "mt5", "2023-01-01", "2026-10-30"), ("③ Duka 2010–14", "duka", "2010-01-01", "2014-12-31")]


def main():
    data = [(nm, A.load(src, a, b)) for nm, src, a, b in SEGS]
    L = ["# #1263／#1264／#1266 喺 2010–2026 黃金確認（IDEAS #1267）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；M1 嚴格版（下一日開市入、M1 逐根判止蝕、成本 0.5 美元）；規則同 `oldgold2_1261.py` 一樣",
         "- 合格：三段每段每筆平均 > 0（≥ 5 筆）而且合併 PF ≥ 1.15。「筆」＝子規則一次交易；合成規則每筆 R 已除以子規則數目，下表平均同 ΣR 都係乘返之後（每個子倉 1R）嘅數", "",
         "| IDEAS | 規則 | " + " | ".join(s[0] for s in SEGS) + " | 合併 | 多／空 每筆 | 判 |", "|---|---|---|---|---|---|---|---|"]
    passed = []
    for key, nm, fn, k in RULES:
        cells, ok, allr, allsg = [], True, [], []
        for _, d in data:
            tr = fn(d); r = np.array([x[2] for x in tr]) * k; good = len(r) >= 5 and r.mean() > 0; ok = ok and good
            allr += list(r); allsg += [x[1] for x in tr]
            cells.append(f"{len(r)} 筆 {r.mean() if len(r) else 0:+.3f}R（ΣR {r.sum():+.1f}）{'✅' if good else '❌'}")
        r = np.array(allr); sg = np.array(allsg); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()); ok = ok and pf >= 1.15
        lo = r[sg > 0].mean() if (sg > 0).any() else 0.0; sh = r[sg < 0].mean() if (sg < 0).any() else 0.0
        L.append(f"| {key} | {nm} | " + " | ".join(cells) + f" | {len(r)} 筆 {r.mean():+.3f}R PF {pf:.2f} {'✅' if pf >= 1.15 else '❌'} | {lo:+.3f}／{sh:+.3f} | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- **合格：{'、'.join(passed) if passed else '冇'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
