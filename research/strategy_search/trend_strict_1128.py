"""[IDEAS #1128] 趨勢突破家族 7 條嚴格版重新回測（預先登記，跑之前 commit；冇網格）。
規則、入場、出場同原版一樣，只改每張成本（美元）：原版 0.5；S1 嚴格版 2.0（止損單入場滑價 1.0＋止蝕出場滑價 0.5＋點差 0.5）；S2 壓力版 4.0（只描述）。
數據 Duka H1：A＝2005–2014、B＝2015–2026-10。判：S1 喺 A、B 都 平均 R > 0 且 PF ≥ 1.10 → 維持合格。
用法：python3 research/strategy_search/trend_strict_1128.py → research/strategy_search/TREND_STRICT_1128.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402
import h1_lab3 as L3            # noqa: E402
import h1_lab4 as L4            # noqa: E402
import h1_lab5 as L5            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402

MODS = (L3, L4, L5, H6, H7, H8)
RULES = [("#1096", "週頭突破（一至三）", L3.r1096), ("#1102", "10 日突破", L4.r1102), ("#1105", "52 週突破", L5.r1105),
         ("#1107", "上季突破（真倉 qbrk）", H6.r1107), ("#1113", "低波幅 20 日突破（真倉 lvbrk）", H7.r1113),
         ("#1114", "月頭 3 日區間突破", H8.r1114), ("#1116", "55 日突破＋20 日出場", H8.r1116)]
COSTS = (("原版", 0.5), ("S1 嚴格", 2.0), ("S2 壓力", 4.0))
OUT = os.path.join(HERE, "TREND_STRICT_1128.md")


def set_cost(c):
    for m in MODS:
        if hasattr(m, "COST"):
            m.COST = c


def st(tr):
    r = np.array([x[2] for x in sorted(tr)], float)
    if not len(r):
        return {"n": 0, "avg": 0.0, "pf": 0.0, "sum": 0.0, "dd": 0.0}
    eq = np.cumsum(r); dd = float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(r), "avg": float(r.mean()), "pf": float(w / ls) if ls else 99.0, "sum": float(r.sum()), "dd": dd}


def main():
    segs = {"A": L.h1("xau/sig/duka_h1/", 2005, 2014), "B": L.h1("xau/sig/duka_h1/", 2015, 2026)}
    res = {}
    for cname, c in COSTS:
        set_cost(c)
        for seg, g in segs.items():
            for key, _, fn in RULES:
                out = fn(g)
                res[(cname, seg, key)] = out if isinstance(out, list) else out[0]
    set_cost(0.5)
    f = lambda s: f"{s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.1f} 回撤 {s['dd']:.1f}"
    L_ = ["# IDEAS #1128 趨勢突破家族嚴格版重新回測", "",
          f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Duka H1 A＝2005–2014、B＝2015–2026-10；規則同原版一樣，只改每張成本（原版 0.5／S1 2.0／S2 4.0 美元）", "",
          "| 規則 | 成本 | A 2005–2014 | B 2015–2026 |", "|---|---|---|---|"]
    verdict = []
    for key, name, _ in RULES:
        for cname, _ in COSTS:
            L_.append(f"| {key} {name} | {cname} | {f(st(res[(cname, 'A', key)]))} | {f(st(res[(cname, 'B', key)]))} |")
        a, b = st(res[("S1 嚴格", "A", key)]), st(res[("S1 嚴格", "B", key)])
        ok = a["avg"] > 0 and b["avg"] > 0 and a["pf"] >= 1.10 and b["pf"] >= 1.10
        verdict.append(f"- {key} {name}：{'✅ 維持合格' if ok else '❌ 嚴格版唔合格'}（S1：A {a['avg']:+.3f}R PF {a['pf']:.2f}；B {b['avg']:+.3f}R PF {b['pf']:.2f}）")
    L_ += ["", "## 真倉組合（#1107＋#1113 合併）", "", "| 成本 | A | B |", "|---|---|---|"]
    for cname, _ in COSTS:
        L_.append(f"| {cname} | {f(st(res[(cname, 'A', '#1107')] + res[(cname, 'A', '#1113')]))} | {f(st(res[(cname, 'B', '#1107')] + res[(cname, 'B', '#1113')]))} |")
    L_ += ["", "## 判（預先登記 IDEAS #1128：S1 喺 A、B 都 平均 R > 0 且 PF ≥ 1.10）", ""] + verdict + [""]
    open(OUT, "w").write("\n".join(L_) + "\n")
    print("\n".join(L_))


if __name__ == "__main__":
    main()
