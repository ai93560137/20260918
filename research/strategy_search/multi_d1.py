"""[IDEAS #180] 其他市場搵策略：#172 八個日線指標家族（48 組，網格同 d1_indicators.FAMILIES 一樣）放落 14 個市場（黃金、白銀以外），
券商 MT5 H1→D1（使用者上載 MAX.zip，2022-08→2026-10，BTC 2020 起）。數據短，所以用「一刀切」：
訓練＝2024-12-31 或之前入場嘅成交（14 個市場合計），每家族揀合計平均 R 最高嗰組（≥ 30 張、PF ≥ 1.1）；測試＝2025-01-01 之後（14 個市場合計）。
引擎同 #172（d1_indicators.run）；每個品種成本同 #178（b_multi.COSTS）；隨機基準同 #172。
用法：python3 research/strategy_search/multi_d1.py → MULTI_D1.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_multi as BM  # noqa: E402
import d1_indicators as Q  # noqa: E402
import robust_long as R  # noqa: E402

CUT = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp())


def main():
    z = BM.load_zip()
    syms = sorted({f.filename.split("/")[-1].rsplit("_", 2)[0] for f in z.infolist() if f.filename.endswith("_H1_MAX.csv")} - BM.SEEN)
    data = {}
    for s in syms:
        R.COST = BM.COSTS.get(s, 0.0)
        D = Q.DI(*BM.h1_of(z, s)); data[s] = (D, Q.baseline(D))
        print("載入", s, flush=True)
    out = ["# 其他市場日線指標策略（IDEAS #180）", "",
           f"- 14 個市場：{'、'.join(syms)}；券商 MT5 2022-08→2026-10；訓練＝2024 年底前入場、測試＝2025-01 起；八個家族同 #172", "",
           "| 家族 | 揀咗（訓練） | 訓練 | 測試 | 測試勝率／基準 | 測試正數市場 | 2025／2026 | 判 |", "|---|---|---|---|---|---|---|---|"]
    passed = []
    for fam, grid in Q.FAMILIES.items():
        trs = {}
        for gi, p in enumerate(grid):
            allt = []
            for s in syms:
                R.COST = BM.COSTS.get(s, 0.0)
                allt += [(x, s) for x in Q.run(data[s][0], fam, p)]
            trs[gi] = allt
        best = None
        for gi, allt in trs.items():
            st = R.summ([x[3] for x, _ in allt if x[0] < CUT])
            if st["n"] >= 30 and st["pf"] >= 1.1 and (best is None or st["avg"] > best[1]):
                best = (gi, st["avg"])
        if best is None:
            out.append(f"| {fam} | 冇一組過訓練門檻 | — | — | — | — | — | ❌ 冇得揀 |")
            continue
        g = best[0]; p = grid[g]
        tr_in = [x for x, _ in trs[g] if x[0] < CUT]; te = [(x, s) for x, s in trs[g] if x[0] >= CUT]
        rs = np.array([x[3] for x, _ in te]); st = R.summ(rs)
        win = float((rs > 0).mean()) if len(rs) else 0.0
        bw = [data[s][1][p["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x, s in te]
        bwin = float(np.nanmean(bw)) if bw else 0.0
        per = {}
        for x, s in te:
            per.setdefault(s, []).append(x[3])
        act = {s: v for s, v in per.items() if len(v) >= 3}
        pos = sum(1 for v in act.values() if np.mean(v) > 0)
        y25 = R.summ([x[3] for x, _ in te if R.yr(x[0]) == 2025]); y26 = R.summ([x[3] for x, _ in te if R.yr(x[0]) == 2026])
        ok = dict(n=st["n"] >= 100, avg=st["avg"] >= 0.05, pf=st["pf"] >= 1.15, edge=win - bwin >= 0.02,
                  mkts=len(act) > 0 and pos >= 0.6 * len(act), yrs=y25["avg"] > 0 and y26["avg"] > 0)
        if all(ok.values()):
            passed.append(fam)
        out.append(f"| {fam} | {p} | {R.summ([x[3] for x in tr_in])['n']} 張 {best[1]:+.3f}R | {st['n']} 張 {st['avg']:+.3f}R PF {st['pf']:.2f} | "
                   f"{win:.0%}／{bwin:.0%} | {pos}/{len(act)} | {y25['avg']:+.3f}／{y26['avg']:+.3f} | "
                   f"{'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, p, R.fmt(st), flush=True)
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}",
            "- 數據得四年、測試期得 22 個月，合格都只係影子前向候選；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "MULTI_D1.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
