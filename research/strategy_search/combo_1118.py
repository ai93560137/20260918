"""[IDEAS #1118] 代表組合：急動反向揀 rev15（933）＋#1011 整數關口；趨勢突破揀 #1096 上週高低突破＋#1116 海龜系統 2。
每張固定 1R、規則同各自回測完全一樣（冇改參數）；R 記喺入場時間；逐月 ΣR；最大回撤用按入場時間排序嘅累計 R。
**主判（預先登記）**：4 條全部一齊（R4）對 rev15 單獨；其餘 10 個組合只作描述。
成功（每段數據都要全部達到）：① R4 ΣR／最大回撤 ≥ rev15 單獨；② R4 最大回撤 ≤ rev15 單獨；③ rev15 對（#1096＋#1116）逐月 ΣR 相關 ≤ 0.2；④ R4 蝕錢月份比例 ≤ rev15 單獨。
數據：Dukascopy M1 2015–2022、MT5 M1 2023-01→2026-10；另外 2010–2014 M1 到咗再跑一次做確認（同一標準）。
用法：python3 research/strategy_search/combo_1118.py [--oos] → research/strategy_search/COMBO_1118.md（--oos 加跑 2010–2014）"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import round_e6s4 as RD         # noqa: E402
import combo_1027 as C          # noqa: E402
import h1_lab3 as H3            # noqa: E402
import h1_lab8 as H8            # noqa: E402

FNS = {"rev15": C.rev15, "round": RD.run, "wkbrk": H3.r1096, "turtle2": H8.r1116}
NAMES = {"rev15": "rev15", "round": "整數關口", "wkbrk": "上週突破", "turtle2": "海龜2"}


def section(name, d):
    tr = {k: f(d) for k, f in FNS.items()}
    allm = sorted({C.month(x[0]) for v in tr.values() for x in v})
    m = {k: C.monthly(v, allm) for k, v in tr.items()}
    corr = float(np.corrcoef(m["rev15"], m["wkbrk"] + m["turtle2"])[0, 1])
    s15, d15 = C.mdd(tr["rev15"]); neg15 = float((m["rev15"] < 0).mean())
    rows = []; res = None
    for size in range(1, 5):
        for sub in itertools.combinations(list(FNS), size):
            x = [t for k in sub for t in tr[k]]; s, dd = C.mdd(x)
            mm = sum(m[k] for k in sub); neg = float((mm < 0).mean())
            rows.append((sub, len(x), s, dd, s / dd if dd else float("inf"), neg))
            if size == 4:
                res = (s, dd, neg)
    out = [f"## {name}", "", "| 組合 | 張 | ΣR | 最大回撤 R | ΣR／回撤 | 蝕錢月 |", "|---|---|---|---|---|---|"]
    out += [f"| {'⭐ ' if len(sub) == 4 else ''}{'＋'.join(NAMES[k] for k in sub)} | {n} | {s:+.1f} | {dd:.1f} | {r:.1f} | {neg:.0%} |" for sub, n, s, dd, r, neg in rows]
    s4, d4, neg4 = res
    ok = {"①R4 ΣR／回撤 ≥ rev15": s4 / d4 >= s15 / d15, "②R4 回撤 ≤ rev15": d4 <= d15,
          "③rev15 對趨勢兩條逐月相關 ≤ 0.2": corr <= 0.2, "④R4 蝕錢月 ≤ rev15": neg4 <= neg15}
    out += ["", f"- rev15 對（上週突破＋海龜2）逐月相關 {corr:+.2f}（{len(allm)} 個月）", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], ""]
    return out, ok


def main():
    sets = [("Dukascopy 2015–2022", A.load("duka", "2015-01-01", "2022-12-31")), ("MT5 2023-01→2026-10", A.load("mt5", "2023-01-01", "2026-10-30"))]
    if "--oos" in ARGV:
        sets.append(("Dukascopy 2010–2014（未見數據確認）", A.load("duka", "2010-01-01", "2014-12-31")))
    out = ["# 代表組合（IDEAS #1118）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張 1R；⭐＝主判（4 條全部）", ""]
    allok = {}
    for name, d in sets:
        sec, ok = section(name, d); out += sec
        allok.update({f"{name} {k}": v for k, v in ok.items()})
    out += ["## 判（預先登記 IDEAS #1118；主判 4 條全部）", "", "- " + ("✅ 達標 → 只提案：4 條代表一齊影子前向，各自達標先逐條提案上實倉" if all(allok.values())
                                                       else "❌ 唔達：" + "、".join(k for k, v in allok.items() if not v)), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "COMBO_1118.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
