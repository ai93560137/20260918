"""[IDEAS #1028 描述] 6 條回測合格規則嘅 63 個組合（單條 6＋組合 57；11-08 加入 #1067 M1 急動）喺 Dukascopy 2015–2022 同 MT5 2023-01→2026-10 嘅回測。
每張固定 1R、規則同各自回測一樣；R 記喺入場時間；最大回撤用按入場時間排序嘅累計 R。**只作描述，唔判**（喺 31 個入面事後揀最好嗰個係過度擬合）；
預先登記過嘅只有 #1027（rev15＋round＋d1brk）。使用者 11-08「31 個組合 回測結果」→「63 個組合回測同影子都做」。
用法：python3 research/strategy_search/combos_31_bt.py → research/strategy_search/COMBOS_63_BT.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import round_e6s4 as RD         # noqa: E402
import batch_1015 as B15        # noqa: E402
import batch_1019 as B19        # noqa: E402
import batch_1023 as B23        # noqa: E402
import combo_1027 as C          # noqa: E402
import batch_1067 as B67        # noqa: E402

FNS = {"rev15": C.rev15, "round": RD.run, "rev60": B15.r1017, "d1brk": B19.r1022, "mend": B23.r1026, "spike": B67.r1067}
NAMES = {"rev15": "rev15", "round": "整數關口", "rev60": "rev60", "d1brk": "D1突破", "mend": "月尾", "spike": "M1急動"}


def st(tr):
    tr = sorted(tr); r = np.array([x[2] for x in tr], float)
    if not len(r):
        return None
    eq = np.cumsum(r); mdd = float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    mon = {}
    for ts, _, x in tr:
        u = dt.datetime.fromtimestamp(ts, dt.timezone.utc); mon[(u.year, u.month)] = mon.get((u.year, u.month), 0) + x
    neg = np.mean([v < 0 for v in mon.values()])
    return {"n": len(r), "sum": r.sum(), "avg": r.mean(), "pf": w / ls if ls else float("inf"), "mdd": mdd, "rdd": r.sum() / mdd if mdd else float("inf"), "neg": neg}


def main():
    sets = [("Dukascopy 2015–2022", A.load("duka", "2015-01-01", "2022-12-31")), ("MT5 2023-01→2026-10", A.load("mt5", "2023-01-01", "2026-10-30"))]
    trades = {nm: {k: f(d) for k, f in FNS.items()} for nm, d in sets}
    keys = list(FNS)
    out = ["# 63 個組合回測（描述，唔判；IDEAS #1028）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張 1R 相加；⭐＝#1027 預先登記；⚠＝含 rev15／rev60／M1 急動任何兩條（高度重疊，等於同一訊號落多倍注）",
           "- ΣR／回撤＝賺幅除以最大回撤（越高越好）；蝕錢月＝逐月 ΣR 為負嘅比例", "",
           "| # | 組合 | Duka 張 | Duka ΣR | Duka 平均 | Duka 回撤 | Duka ΣR／回撤 | Duka 蝕錢月 | MT5 張 | MT5 ΣR | MT5 平均 | MT5 回撤 | MT5 ΣR／回撤 | MT5 蝕錢月 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    k = 0
    for size in range(1, len(keys) + 1):
        for sub in itertools.combinations(keys, size):
            k += 1
            tag = ("⭐ " if sub == ("rev15", "round", "d1brk") else "") + ("⚠ " if any(a in sub and b in sub for a, b in (("rev15", "rev60"), ("rev15", "spike"), ("rev60", "spike"))) else "")
            cells = []
            for nm, _ in sets:
                s = st([x for key in sub for x in trades[nm][key]])
                cells += [str(s["n"]), f"{s['sum']:+.1f}", f"{s['avg']:+.3f}", f"{s['mdd']:.1f}", f"{s['rdd']:.1f}", f"{s['neg']:.0%}"]
            out.append(f"| {k} | {tag}{'＋'.join(NAMES[x] for x in sub)} | " + " | ".join(cells) + " |")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "COMBOS_63_BT.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
