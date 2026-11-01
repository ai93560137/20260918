"""[IDEAS #179] XAUUSD M30 指標策略：同 #169 七個家族（去咗 F 開市區間，M30 一根已經係成個區間），指標喺 M30 K 線計；
時間止蝕按時框放大（A／D／E 12 小時、B／C／G 24 小時）。第一關＝券商 MT5 M1→M30 2022-08→2026-10 滾動前向（12 個月揀、3 個月測、t ≥ 3.0）；
第二關＝最常揀嗰組固定參數，Dukascopy M1→M30 2015-01→2022-07（未見）。引擎同 #169（m5_indicators.run）。
用法：python3 research/strategy_search/m30_indicators.py --stage wf｜duka"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import m5_indicators as M  # noqa: E402
import robust_long as R  # noqa: E402
import search as S  # noqa: E402
import search2 as W  # noqa: E402

BAR = 1800
W.BASE = BAR                                   # H1 已收市判斷用 M30 收市時間
M.T_H.update({"A": 12, "B": 24, "C": 24, "D": 12, "E": 12, "G": 24})
FAMILIES = {k: v for k, v in M.FAMILIES.items() if not k.startswith("F")}
PICKS = os.path.join(HERE, "m30_ind_picks.json")


def to_bars(d):
    key = d["t"] // BAR * BAR
    ks, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(key)] - 1
    return {"t": ks, "o": d["o"][first], "h": np.maximum.reduceat(d["h"], first), "l": np.minimum.reduceat(d["l"], first), "c": d["c"][last]}


def stage_wf():
    D = M.M5(to_bars(S.load("mt5", "2022-08-03", "2026-10-30")))
    qs = []; q = M.WF_FIRST_TEST
    while q <= M.WF_LAST_TEST:
        qs.append(q); q = M.add_months(q, 3)
    out = ["# XAUUSD M30 指標策略（IDEAS #179）第一關：券商 MT5 滾動前向", "",
           f"- M30 {len(D.t):,} 根；12 個月揀（≥ {M.MIN_TRAIN_N} 張、PF ≥ {M.MIN_TRAIN_PF}）、測 3 個月；每張扣 {R.COST} 美元", "",
           "| 家族 | 樣本外 | 正數季 | 最常揀 | 第一關 |", "|---|---|---|---|---|"]
    picks = {}; full = []
    for fam, grid in FAMILIES.items():
        trs = [M.run(D, fam, p) for p in grid]
        oos, qpos, sel = [], 0, []
        for q in qs:
            a, b, e = M.ts_ym(M.add_months(q, -12)), M.ts_ym(q), M.ts_ym(M.add_months(q, 3))
            best = None
            for gi, tr in enumerate(trs):
                s = R.summ([x[3] for x in tr if a <= x[0] < b])
                if s["n"] >= M.MIN_TRAIN_N and s["pf"] >= M.MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                    best = (gi, s["avg"])
            yt = [] if best is None else [x[3] for x in trs[best[0]] if b <= x[0] < e]
            if best is not None:
                sel.append(best[0])
            qpos += 1 if yt and np.mean(yt) > 0 else 0
            oos += yt
        s = R.summ(oos)
        ok = dict(n=s["n"] >= 300, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, t=s["t"] >= 3.0, q=qpos >= 8)
        top = max(set(sel), key=sel.count) if sel else None
        picks[fam] = {"pass1": all(ok.values()), "param": None if top is None else grid[top]}
        out.append(f"| {fam} | {R.fmt(s)} | {qpos}/{len(qs)} | {'—' if top is None else grid[top]} | "
                   f"{'✅ 入第二關' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        b_ = max(range(len(grid)), key=lambda g: R.summ([x[3] for x in trs[g]])["avg"])
        full.append(f"- {fam} 全期最好 {grid[b_]}：{R.fmt(R.summ([x[3] for x in trs[b_]]))}")
        print(fam, R.fmt(s), flush=True)
    json.dump(picks, open(PICKS, "w"), ensure_ascii=False, indent=1)
    out += ["", "## 全期描述（唔算數）", "", *full, "", f"- 入第二關：{'、'.join(f for f, v in picks.items() if v['pass1']) or '冇'}", ""]
    open(os.path.join(HERE, "M30_IND_WF.md"), "w").write("\n".join(out))


def stage_duka():
    picks = json.load(open(PICKS)); todo = {f: v for f, v in picks.items() if v["pass1"]}
    out = ["# XAUUSD M30 指標策略（IDEAS #179）第二關：Dukascopy 2015-01→2022-07 固定參數", ""]
    if not todo:
        out.append("- 第一關冇家族過，第二關唔使跑。")
    else:
        D = M.M5(to_bars(S.load("duka", "2015-01-01", "2022-07-31")))
        for fam, v in todo.items():
            tr = M.run(D, fam, v["param"]); s = R.summ([x[3] for x in tr]); yy = {}
            for x in tr:
                yy.setdefault(R.yr(x[0]), []).append(x[3])
            pos = sum(1 for r in yy.values() if np.mean(r) > 0)
            h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2018]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2019])
            ok = dict(n=s["n"] >= 300, avg=s["avg"] >= 0.03, pf=s["pf"] >= 1.1, yrs=pos >= 5, halves=h1["avg"] > 0 and h2["avg"] > 0)
            out += [f"## {fam} {v['param']}", "", f"- {R.fmt(s)}；{pos}/{len(yy)} 年正；2015–18 {h1['avg']:+.3f}、2019–22 {h2['avg']:+.3f}",
                    f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, x in ok.items() if not x)}", ""]
    open(os.path.join(HERE, "M30_IND_DUKA.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", choices=("wf", "duka"), required=True)
    stage_wf() if ap.parse_args().stage == "wf" else stage_duka()
