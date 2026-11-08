"""[IDEAS #1125] 兩個戶口揀組合：急動反向家族（933 戶口）同趨勢突破家族（…63 戶口）各揀「最近 10 年最好」嘅組合。
揀法（預先登記，跑之前 commit）：候選＝已合格規則（急動 11 條、趨勢 7 條），組合大小 1–3 條；每張 1R、R 記喺入場時間；
選擇期＝2016-01-01→2026-10-30（Duka 2016–22＋MT5 2023–26）；門檻：選擇期蝕錢年份 ≤ 1；之後按 ΣR／最大回撤排第一。
留出驗證＝2010–2015（Duka；揀嘅時候唔睇）：第一名要平均 ≥ +0.05R、PF ≥ 1.10、ΣR／回撤 > 1，唔過就順延下一名（最多試 5 名）。
呢個係喺同一批數據入面揀最好（事後揀選），回測數字會偏高；只有留出期係乾淨嘅。
用法：python3 research/strategy_search/pick_1125.py → research/strategy_search/PICK_1125.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import shadow_board as SB       # noqa: E402
import asia_sweep as A          # noqa: E402

FADE = ["rev15", "rev60", "spike", "ema60", "rev15d1", "nyopen", "rev240", "stair", "m5spike", "dopen15", "spike2"]
TREND = ["wkbrk", "d10brk", "w52brk", "qbrk", "lvbrk", "mobrk", "turtle2"]
FN = {k: (name, idea, fn) for k, name, idea, fn, _ in SB.STRATS}
SEL0, HOLD = int(dt.datetime(2016, 1, 1, tzinfo=dt.timezone.utc).timestamp()), (2010, 2015)
SETS = [("duka", "2010-01-01", "2015-12-31"), ("duka", "2015-01-01", "2022-12-31"), ("mt5", "2023-01-01", "2026-10-30")]


def yr(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).year


def metr(tr, years):
    tr = sorted(tr)
    r = np.array([x[2] for x in tr], float)
    if not len(r):
        return None
    eq = np.cumsum(r); dd = float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    ys = {y: 0.0 for y in years}
    for ts, _, x in tr:
        ys[yr(ts)] = ys.get(yr(ts), 0.0) + x
    return {"n": len(r), "sum": float(r.sum()), "avg": float(r.mean()), "pf": float(w / ls) if ls else 99.0,
            "dd": dd, "ratio": float(r.sum() / dd) if dd else 99.0, "lose": sum(1 for y in years if ys[y] < 0), "worst": min(ys[y] for y in years)}


def main():
    trades = {k: [] for k in FADE + TREND}
    for i, (src, a, b) in enumerate(SETS):
        d = A.load(src, a, b)
        for k in trades:
            for ts, sg, r in FN[k][2](d):
                y = yr(ts)
                if (i == 0 and y <= 2015) or (i == 1 and 2016 <= y <= 2022) or (i == 2 and y >= 2023):
                    trades[k].append((int(ts), int(sg), float(r)))
        del d
    sel_years, hold_years = list(range(2016, 2027)), list(range(*HOLD)) + [HOLD[1]]
    out = ["# 兩個戶口揀組合（IDEAS #1125）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；選擇期 2016-01→2026-10；留出 2010–2015；每張 1R；組合 1–3 條",
           "- ⚠ 喺同一批數據揀最好（事後揀選），選擇期數字偏高；留出期先乾淨", ""]
    picks = {}
    for fam, keys in (("急動反向（933 戶口）", FADE), ("趨勢突破（…63 戶口）", TREND)):
        rows = []
        for size in (1, 2, 3):
            for sub in itertools.combinations(keys, size):
                sel = [x for k in sub for x in trades[k] if x[0] >= SEL0]
                m = metr(sel, sel_years)
                if m and m["lose"] <= 1:
                    rows.append((m["ratio"], sub, m))
        rows.sort(key=lambda x: -x[0])
        out += [f"## {fam}", "", "| 名次 | 組合 | 選擇期 張／ΣR／回撤／ΣR÷回撤／蝕年 | 留出 2010–15 張／平均／PF／ΣR÷回撤 | 留出判 |", "|---|---|---|---|---|"]
        chosen = None
        for rank, (_, sub, m) in enumerate(rows[:10], 1):
            h = metr([x for k in sub for x in trades[k] if x[0] < SEL0], hold_years)
            ok = bool(h and h["avg"] >= 0.05 and h["pf"] >= 1.10 and h["ratio"] > 1)
            if chosen is None and rank <= 5 and ok:
                chosen = (sub, m, h)
            hs = f"{h['n']}／{h['avg']:+.3f}／{h['pf']:.2f}／{h['ratio']:.1f}" if h else "0"
            out.append(f"| {rank} | {'✅ ' if chosen and chosen[0] == sub else ''}{'＋'.join(sub)} | {m['n']}／{m['sum']:+.1f}／{m['dd']:.1f}／{m['ratio']:.1f}／{m['lose']} | {hs} | {'過' if ok else '唔過'} |")
        picks[fam] = chosen
        out += ["", ("- 揀中：**" + "＋".join(f"{k}（{FN[k][1]}）" for k in chosen[0]) + "**") if chosen else "- 頭 5 名留出都唔過 → 唔揀", ""]
        if chosen:
            ys = {}
            for k in chosen[0]:
                for ts, _, x in trades[k]:
                    ys[yr(ts)] = ys.get(yr(ts), 0.0) + x
            out += ["- 逐年 ΣR：" + "、".join(f"{y} {ys.get(y, 0):+.1f}" for y in range(2010, 2027)), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "PICK_1125.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
