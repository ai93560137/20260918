#!/usr/bin/env python3
"""日線 B 規則放落股票：ATR 止蝕／止賺網格重測（stock_research/B_STOCKS_ATR_GRID_PREREG.md；登記 commit 91bc4ea11 之後寫）。

入場同天覆陣 IDEAS #181 一字不改（重用佢 research/strategy_search 模組：combo_tf.Bars、b_stocks 嘅訊號／成分股／讀價，
預設分支 3e540bb19，唯讀抽到 --ss）；只改出場 SL／TP × ATR20。

    git archive origin/claude/gifted-carson-v2tvhw data/equities universes scripts/pointintime scripts/universe_hsi_live.txt | tar -x -C /tmp/eq
    git archive 3e540bb19 research/strategy_search | tar -x -C /tmp/ss
    python3 stock_research/b_stocks_atr_grid.py --src /tmp/eq --ss /tmp/ss/research/strategy_search
輸出 research/b_stocks_atr_grid/grid.json、grid.md。
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "b_stocks_atr_grid"
SLS = [1.0, 1.5, 2.0, 2.5, 3.0]
TPS = [1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
COST_MAIN = {"us": 0.001, "jp": 0.0015, "hk": 0.003}
COST_ALT = 0.001
UNIVERSES = (("標普 500", "sp500", "us"), ("納指 100", "ndx", "us"), ("道指", "djia", "us"), ("日經 225", "n225", "jp"), ("恒指", "hsi", "hk"))
LEGS = ("long", "both", "base_long", "base_both")
SCEN = ("main", "alt")
G = {}


def init(ss, src):
    sys.path.insert(0, ss)
    import b_stocks as BS  # noqa: E402
    import combo_tf as CT  # noqa: E402
    import robust_long as R  # noqa: E402
    R.COST = 0.0
    G.update(BS=BS, CT=CT, R=R, src=src)


def year(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).year


def new_acc():
    return dict(n=0, s=0.0, ss=0.0, pos=0.0, neg=0.0, win=0, pct=0.0, yr={}, h1=[0, 0.0], h2=[0, 0.0])


def add(acc, r, pct, y):
    acc["n"] += 1; acc["s"] += r; acc["ss"] += r * r; acc["pct"] += pct
    if r > 0:
        acc["pos"] += r; acc["win"] += 1
    else:
        acc["neg"] -= r
    a = acc["yr"].setdefault(y, [0, 0.0]); a[0] += 1; a[1] += r
    h = acc["h1"] if y <= 2015 else acc["h2"]; h[0] += 1; h[1] += r


def merge(a, b):
    for k in ("n", "s", "ss", "pos", "neg", "win", "pct"):
        a[k] += b[k]
    for y, (n, s) in b["yr"].items():
        x = a["yr"].setdefault(y, [0, 0.0]); x[0] += n; x[1] += s
    for k in ("h1", "h2"):
        a[k][0] += b[k][0]; a[k][1] += b[k][1]


def run_ticker(job):
    """一隻股票、一個宇宙：回傳 {(sl,tp,leg,scen): acc}，另加 per-ticker 平均（只做多主口徑）。"""
    mkt, tk, spans, key = job
    BS, CT, R = G["BS"], G["CT"], G["R"]
    d = BS.load_prices(os.path.join(G["src"], "data", "equities", mkt, tk))
    if d is None:
        return None
    B = CT.Bars(d, 86400)
    b, x = BS.b_signals(B)
    ok = np.array([BS.member(spans, int(t)) and year(t) >= BS.FIRST_YEAR for t in B.t])
    b, x = b & ok, x & ok
    mh = CT.NBARS * 86400 / 3600
    idx = {int(t): i for i, t in enumerate(B.t)}
    sig_long = [i for i in np.flatnonzero(b) if 210 <= i < len(B.c) - 1 and B.datr[i] > 0]
    sig_both = [(i, 1 if b[i] else -1) for i in np.flatnonzero(b | x) if 210 <= i < len(B.c) - 1 and B.datr[i] > 0]
    base_i = [i for i in range(210, len(B.c) - 1, 10) if ok[i] and B.datr[i] > 0]
    out, tick = {}, {}
    for sl in SLS:
        for tp in TPS:
            ent = {
                "long": [(i + 1, 1, sl * B.datr[i], tp * B.datr[i], mh) for i in sig_long],
                "both": [(i + 1, s, sl * B.datr[i], tp * B.datr[i], mh) for i, s in sig_both],
                "base_long": [(i + 1, 1, sl * B.datr[i], tp * B.datr[i], mh) for i in base_i],
            }
            trs = {k: R.simulate(B, v) for k, v in ent.items()}
            trs["base_both"] = trs["base_long"] + R.simulate(B, [(i + 1, -1, sl * B.datr[i], tp * B.datr[i], mh) for i in base_i])
            for leg, tr in trs.items():
                for scen in SCEN:
                    c = COST_MAIN[mkt] if scen == "main" else COST_ALT
                    acc = new_acc()
                    rs = []
                    for ts, s, dd, r, _ in tr:
                        px = B.o[idx[ts]]
                        rn = r - c * px / dd
                        add(acc, rn, rn * dd / px, year(ts))
                        rs.append(rn)
                    out[(sl, tp, leg, scen)] = acc
                    if leg == "long" and scen == "main" and rs:
                        tick[(sl, tp)] = float(np.mean(rs))
    return key, out, tick


def stats(a):
    n = a["n"]
    if not n:
        return dict(n=0)
    m = a["s"] / n
    var = (a["ss"] - n * m * m) / (n - 1) if n > 1 else 0
    yrs = {y: s / k for y, (k, s) in sorted(a["yr"].items())}
    return dict(n=n, avg=m, pct=a["pct"] / n * 100, pf=a["pos"] / a["neg"] if a["neg"] else float("inf"),
                t=m / math.sqrt(var) * math.sqrt(n) if var > 0 else 0.0, win=a["win"] / n,
                pos_years=sum(1 for v in yrs.values() if v > 0), years=len(yrs),
                h1=a["h1"][1] / a["h1"][0] if a["h1"][0] else None, h2=a["h2"][1] / a["h2"][0] if a["h2"][0] else None,
                by_year={str(y): round(v, 4) for y, v in yrs.items()})


def qualifies(st, base):
    if not st.get("n"):
        return False, ["n"]
    fail = []
    if st["n"] < 300: fail.append("n")
    if st["avg"] < 0.05: fail.append("avg")
    if st["pf"] < 1.15: fail.append("pf")
    if st["t"] < 2: fail.append("t")
    if not base.get("n") or st["avg"] - base["avg"] < 0.03: fail.append("R優於隨機")
    if not base.get("n") or st["win"] - base["win"] < 0.02: fail.append("勝率優於隨機")
    if st["pos_years"] < 0.6 * st["years"]: fail.append("正年")
    if not (st["h1"] and st["h1"] > 0 and st["h2"] and st["h2"] > 0): fail.append("前後半")
    return not fail, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/eq")
    ap.add_argument("--ss", default="/tmp/ss/research/strategy_search")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--only", nargs="*", help="只跑某些宇宙（測試用；正式結果要全部一次跑）")
    a = ap.parse_args()
    global UNIVERSES
    if a.only:
        UNIVERSES = tuple(u for u in UNIVERSES if u[1] in a.only)
    init(a.ss, a.src)
    BS = G["BS"]
    jobs, have = [], {}
    for name, key, mkt in UNIVERSES:
        mem = BS.membership(a.src, key)
        have[key] = [0, len(mem)]
        for tk, spans in mem.items():
            if os.path.isdir(os.path.join(a.src, "data", "equities", mkt, tk)):
                jobs.append((mkt, tk, spans, key))
    agg = {key: {} for _, key, _ in UNIVERSES}
    ticks = {key: {} for _, key, _ in UNIVERSES}
    with ProcessPoolExecutor(a.workers, initializer=init, initargs=(a.ss, a.src)) as ex:
        for k, res in enumerate(ex.map(run_ticker, jobs, chunksize=4), 1):
            if res is None:
                continue
            key, out, tick = res
            have[key][0] += 1
            for kk, acc in out.items():
                if kk not in agg[key]:
                    agg[key][kk] = new_acc()
                merge(agg[key][kk], acc)
            for cell, v in tick.items():
                ticks[key].setdefault(cell, []).append(v)
            if k % 200 == 0:
                print(f"{k}/{len(jobs)}", flush=True)
    res = dict(prereg_commit="91bc4ea11", ss_commit="3e540bb19", sls=SLS, tps=TPS, universes={})
    for name, key, mkt in UNIVERSES:
        u = dict(name=name, have=have[key][0], listed=have[key][1], cells={})
        for sl in SLS:
            for tp in TPS:
                c = {f"{leg}_{scen}": stats(agg[key].get((sl, tp, leg, scen), new_acc())) for leg in LEGS for scen in SCEN}
                tv = ticks[key].get((sl, tp), [])
                c["ticker_pos"] = [sum(1 for v in tv if v > 0), len(tv)]
                ok, fail = qualifies(c["long_main"], c["base_long_main"])
                c["qual"], c["fail"] = ok, fail
                u["cells"][f"{sl}/{tp}"] = c
        # 平原：上下左右相鄰格平均 > 0
        for i, sl in enumerate(SLS):
            for j, tp in enumerate(TPS):
                nb = [(i + di, j + dj) for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)) if 0 <= i + di < len(SLS) and 0 <= j + dj < len(TPS)]
                plateau = all(u["cells"][f"{SLS[p]}/{TPS[q]}"]["long_main"].get("avg", -1) > 0 for p, q in nb)
                c = u["cells"][f"{sl}/{tp}"]
                c["plateau"] = plateau
                c["pass"] = c["qual"] and plateau
        res["universes"][key] = u
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "grid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(res)


def write_md(res):
    L = ["# 日線 B 規則股票 ATR 網格（只做多主口徑；平均 R／t）", ""]
    for key, u in res["universes"].items():
        L += [f"## {u['name']}（有數據 {u['have']}／名單 {u['listed']}）", "", "| SL＼TP | " + " | ".join(str(t) for t in res["tps"]) + " |",
              "|---|" + "---|" * len(res["tps"])]
        for sl in res["sls"]:
            row = []
            for tp in res["tps"]:
                c = u["cells"][f"{sl}/{tp}"]; s = c["long_main"]
                mark = "✅" if c["pass"] else ("◐" if c["qual"] else "")
                row.append(f"{s.get('avg', 0):+.3f}／{s.get('t', 0):.1f}{mark}" if s.get("n") else "—")
            L.append(f"| {sl} | " + " | ".join(row) + " |")
        L.append("")
    (OUT / "grid.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
