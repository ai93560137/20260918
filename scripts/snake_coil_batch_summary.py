#!/usr/bin/env python3
"""蛇蟠陣外匯批次彙總：每商品 sar N=3 的 t／PF／正年／前 10 筆／回撤、鄰域 N=1/2/5 t、滑點敏感度，以及全體合併 t（逐筆損益 ÷ 進場價 = 百分比）。

    python3 scripts/snake_coil_batch_summary.py --dir forex_research/snake_coil/batch [--md 輸出.md]
"""
import argparse
import csv
import glob
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_forex import INSTRUMENTS  # noqa: E402
from snake_coil_eval import load, summarize, tstat  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=ROOT / "forex_research" / "snake_coil" / "batch")
    ap.add_argument("--md", type=Path)
    args = ap.parse_args()
    files = {}
    for f in glob.glob(str(args.dir / "*_sar_N*_sp*.csv")):
        m = re.match(r"(\w+)_sar_N(\d)_sp([\d.]+)\.csv", Path(f).name)
        files.setdefault(m.group(1), {})[int(m.group(2))] = (f, float(m.group(3)))
    rows, pooled, pooled_by_pair = [], [], {}
    for pair in sorted(files, key=lambda p: list(INSTRUMENTS).index(p)):
        if 3 not in files[pair]:
            continue
        dec = INSTRUMENTS[pair][1]
        pip = 10.0 ** -(dec - 1)
        path, sp = files[pair][3]
        tr = load(path)
        a = summarize(tr)
        L, S = summarize([r for r in tr if r["direction"] > 0]), summarize([r for r in tr if r["direction"] < 0])
        neigh = {}
        for lb in (1, 2, 5):
            if lb in files[pair]:
                z = summarize(load(files[pair][lb][0]))
                neigh[lb] = (z["t"], z["pf"], z["total"])
        sens = {}
        for extra_pips in (0.5, 1.0):
            z = summarize([dict(r, pnl=r["pnl"] - extra_pips * pip) for r in tr])
            sens[extra_pips] = (z["t"], z["pf"])
        pct = [r["pnl"] / float(r["entry"]) * 100 for r in tr if float(r["entry"]) > 0]
        pooled += pct
        pooled_by_pair[pair] = pct
        all_pos = all(v[2] > 0 for v in neigh.values()) and a["total"] > 0
        verdict = "🔍" if (a["t"] >= 2.5 and a["pf"] >= 1.2 and all_pos) else "☠️"
        rows.append(dict(pair=pair, sp=sp / pip, n=a["n"], pips=a["total"] / pip, t=a["t"], pf=a["pf"], wr=a["win_rate"],
                         pos_years=f"{a['pos_years']}/{a['n_years']}", top10=a["top10_share"], dd=a["max_dd"] / pip,
                         lt=L["t"], lpf=L["pf"], st=S["t"], spf=S["pf"], neigh=neigh, sens=sens, verdict=verdict,
                         first=tr[0]["open_time"][:4] if tr else "—"))
    n_pos = sum(r["pips"] > 0 for r in rows)
    pooled_t = tstat(pooled)
    per_pair_t = {p: tstat(v) for p, v in pooled_by_pair.items()}
    # 商品等權合併：每商品先算逐筆百分比的平均 t，再看 23 個 t 的分佈（避免筆數多的商品主導）
    ts = list(per_pair_t.values())
    mean_t = sum(ts) / len(ts) if ts else float("nan")
    lines = [f"| 商品 | 起 | 點差(pips) | 筆數 | 總損益(pips) | t | PF | 勝率 | 正年 | 前10筆 | 最大回撤(pips) | 多頭 t/PF | 空頭 t/PF | N=1 t | N=2 t | N=5 t | +0.5pip t | +1.0pip t | 判定 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        ng = lambda lb: f"{r['neigh'][lb][0]:.2f}" if lb in r["neigh"] else "—"
        lines.append(f"| {r['pair']} | {r['first']} | {r['sp']:.2f} | {r['n']:,} | {r['pips']:+,.0f} | **{r['t']:.2f}** | {r['pf']:.2f} | {r['wr']*100:.0f}% | {r['pos_years']} | "
                     f"{r['top10']*100:.0f}% | {r['dd']:,.0f} | {r['lt']:.2f}/{r['lpf']:.2f} | {r['st']:.2f}/{r['spf']:.2f} | {ng(1)} | {ng(2)} | {ng(5)} | "
                     f"{r['sens'][0.5][0]:.2f} | {r['sens'][1.0][0]:.2f} | {r['verdict']} |")
    summary = [f"- 商品數 {len(rows)}；總損益為正 {n_pos} 個（隨機期望約 {len(rows)/2:.0f}）；達批次門檻（t ≥ 2.5、PF ≥ 1.2、N=1/2/3/5 全正）{sum(r['verdict']=='🔍' for r in rows)} 個",
               f"- **全體合併 t（逐筆損益 % 合併，{len(pooled):,} 筆）= {pooled_t:.2f}**；各商品 t 的平均 = {mean_t:.2f}、中位 = {sorted(ts)[len(ts)//2]:.2f}、t ≥ 2 的商品 {sum(t >= 2 for t in ts)} 個、t ≤ 0 的 {sum(t <= 0 for t in ts)} 個",
               f"- 多頭腿 t 平均 {sum(r['lt'] for r in rows)/len(rows):.2f}、空頭腿 t 平均 {sum(r['st'] for r in rows)/len(rows):.2f}"]
    out = "\n".join(lines) + "\n\n" + "\n".join(summary) + "\n"
    print(out)
    if args.md:
        args.md.write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
