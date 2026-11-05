#!/usr/bin/env python3
"""用 9 國數據補判決矩陣空格（預先登記：stock_research/MATRIX_FILL_BACKTEST.md，寫程式前已 commit；只跑一次）。

    python3 matrix_fill.py --market ca --trades-only        # 各策略預設格筆數＋HTF 內部一致性可疑清單（不算績效）
    python3 matrix_fill.py --market ca --random 200         # 正式：只跑該市場要補的格子（預設格＋隨機對照）
    python3 matrix_fill.py --pool                           # 每個策略把它補的市場合併檢定＋判決

規格全部沿用原判決的預設格，只換宇宙與成本（同 oos_backtest.py）；不跑鄰域格、不跑敏感度。
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import aiba_ppp as ap  # noqa: E402
import htf_backtest as hb  # noqa: E402
import newhigh_backtest as nb  # noqa: E402
import vcp_backtest as vb  # noqa: E402
from oos_backtest import abn, drop_locked, h5a_random, locked_matrix, pooled, summary, tstat  # noqa: E402

OUT = ROOT / "research" / "matrix_fill"
NEW = ("tw", "kr", "au", "ca", "in", "sg")
NH_N = {"tw": 150, "kr": 200, "au": 200, "ca": 150, "in": 200, "sg": 60}     # 新高類成交額前 N（登記第二節）
# 登記第二節：每個策略要補的市場
FILL = {
    "H4": NEW, "H5a": ("ca", "in", "sg"), "H5b": NEW,
    "XV": NEW, "X5": NEW,
    "PPP": ("ca", "in", "sg"), "PPP_ema5": NEW,
    "HTF": ("kr", "au", "ca", "in", "sg"),
}
KEYS = tuple(FILL)


def wanted(mk: str) -> list[str]:
    return [k for k in KEYS if mk in FILL[k]]


def pool_list(mk: str) -> list[str]:
    return [l.strip() for l in (ROOT / "universes" / "full" / f"{mk}_pool.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def vcp_drop_locked(m, ev: dict, locked: np.ndarray) -> dict:
    """VCP 訊號（{(s, 訊號日): info}）：入場日漲停鎖死的剔除。"""
    D = len(m.cal)
    out = {}
    for (s, j), info in ev.items():
        a = m.next_px[s, j + 1] if j + 1 < D else D
        if a < D and locked[s, a]:
            continue
        out[(s, j)] = info
    return out


def run_market(mk: str, n_random: int, trades_only: bool) -> None:
    keys = wanted(mk)
    res = {"market": mk, "cells": {}, "abn": {}, "locked_skipped": {}}
    rnd = {k: [] for k in keys}
    counts = {}
    # ---- 新高類（成交額前 N）----
    nh = [k for k in keys if k in ("H4", "H5a", "H5b")]
    if nh:
        m1 = nb.MarketData(mk, pool=pool_list(mk), loader=nb.load_full(mk), top_n=NH_N[mk], cost=vb.FULL_COST[mk])
        lk1 = locked_matrix(m1, mk)
        for k in nh:
            ev0 = m1.events(k, nb.GRIDS[k]["default"])
            ev = drop_locked(m1, ev0, lk1)
            res["locked_skipped"][k] = int(ev0.sum() - ev.sum())
            trades = m1.trades_from_events(ev, "x2")
            counts[k] = len(trades)
            if trades_only:
                continue
            daily, tr, _ = m1.portfolio(trades)
            res["cells"][k] = summary(m1, daily, tr, [b - a for _, a, b, _ in trades], len(trades))
            res["abn"][k] = abn(m1, daily)
            rnd[k] = [abn(m1, m1.portfolio(h5a_random(m1, ev, lk1, sd))[0]) for sd in range(n_random)]
        del m1
    # ---- VCP 全市場 XV／X5、PPP（全市場前 N）----
    vk = [k for k in keys if k in ("XV", "X5", "PPP", "PPP_ema5")]
    if vk:
        vf = vb.VCPData(mk, full=True, scan=any(k in ("XV", "X5") for k in vk))
        m = vf.m
        lk2 = locked_matrix(m, mk)
        if any(k in ("XV", "X5") for k in vk):
            ev0 = vf.events(*vb.DEFAULT)
            ev = vcp_drop_locked(m, ev0, lk2)
            for k, rule in (("XV", "xv"), ("X5", "x5")):
                if k not in vk:
                    continue
                res["locked_skipped"][k] = len(ev0) - len(ev)
                trades = vf.trades(ev, rule)
                counts[k] = len(trades)
                if trades_only:
                    continue
                daily, tr, _ = m.portfolio(trades)
                res["cells"][k] = summary(m, daily, tr, [b - a for _, a, b, _ in trades], len(trades))
                res["abn"][k] = abn(m, daily)
                rnd[k] = [abn(m, m.portfolio(vf.random_trades(ev, sd, rule))[0]) for sd in range(n_random)]
        pp = ap.AibaPPP(mk, m=m) if any(k.startswith("PPP") for k in vk) else None
        for k, rule in (("PPP", "rev"), ("PPP_ema5", "ema5")):
            if k not in vk:
                continue
            pp.set_exit(rule)                             # 重設 m.exitc／next_exit[ap.RULE]，兩種出場逐一跑
            evp0 = pp.events(*ap.DEFAULT)
            evp = drop_locked(m, evp0, lk2)
            res["locked_skipped"][k] = int(evp0.sum() - evp.sum())
            trp = m.trades_from_events(evp, ap.RULE)
            counts[k] = len(trp)
            if trades_only:
                continue
            daily, tr, _ = m.portfolio(trp)
            res["cells"][k] = summary(m, daily, tr, [b - a for _, a, b, _ in trp], len(trp))
            res["abn"][k] = abn(m, daily)
            rnd[k] = [abn(m, m.portfolio(pp.random_trades(evp, ap.DEFAULT[0], sd))[0]) for sd in range(n_random)]
        del vf, m
    # ---- HTF（全市場前 N；先 --trades-only 產生內部一致性可疑清單，正式跑時剔除，同原流程）----
    if "HTF" in keys:
        sus_p = OUT / f"{mk}_htf_suspect.json"
        excl = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not trades_only else set()
        h = hb.HTF(mk, excl)
        trs = h.trades(*hb.DEFAULT)
        counts["HTF"] = len(trs)
        if trades_only:
            det = h.detail(trs)
            sus = [[d["ticker"], d["entry"]] for d in det if d["suspect"]]
            OUT.mkdir(parents=True, exist_ok=True)
            sus_p.write_text(json.dumps(sus, ensure_ascii=False) + "\n", encoding="utf-8")
            counts["HTF_suspect"] = len(sus)
        else:
            st = h.evaluate(trs)
            daily, _, _ = h.daily(trs)
            res["cells"]["HTF"] = {x: st[x] for x in ("trades", "alpha_t", "cagr", "cagr_etf", "mdd", "win", "avg_hold",
                                                     "t_pre", "t_post", "expectancy", "rrr", "top10_share")}
            res["cells"]["HTF"].update({"cum": float("nan"), "cum_etf": float("nan")})
            res["abn"]["HTF"] = h.abn(daily)
            rnd["HTF"] = [h.abn(h.daily(h.trades(*hb.DEFAULT, random_seed=sd))[0]) for sd in range(n_random)]
    print(f"[{mk}] 預設格筆數 {counts}（漲停鎖死跳過 {res['locked_skipped']}）", file=sys.stderr)
    if trades_only:
        return
    for k, st in res["cells"].items():
        print(f"[{mk}] {k:9} 筆數 {st['trades']:6d}  alpha t {st['alpha_t']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
              f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def pool_all() -> None:
    """登記第三節：每個策略合併它補的市場；t ≥ 2.7 且隨機 ≥ 95 百分位且前後兩半都正 → 🔍，否則原判決不變。"""
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in NEW}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in NEW}
    out = {}
    for k in KEYS:
        mks = FILL[k]
        ser = pooled([R[mk]["abn"][k] for mk in mks])
        real = tstat(ser)
        half = len(ser.dropna()) // 2
        s = ser.dropna()
        t1, t2 = tstat(s.iloc[:half]), tstat(s.iloc[half:])
        n = min(len(RN[mk][k]) for mk in mks)
        rt = sorted(tstat(pooled([RN[mk][k][i] for mk in mks])) for i in range(n))
        pct = sum(x < real for x in rt) / n if n else float("nan")
        if real >= 2.7 and pct >= 0.95 and t1 > 0 and t2 > 0:
            v = "🔍 值得再驗證"
        elif real <= -2:
            v = "原判決不變（新市場也顯著為負）"
        else:
            v = "原判決不變"
        out[k] = {"markets": list(mks), "pooled_t": real, "t_first_half": t1, "t_second_half": t2, "random_pctl": pct,
                  "random_median": rt[n // 2] if n else None, "verdict": v,
                  "per_market": {mk: {x: R[mk]["cells"][k].get(x) for x in ("alpha_t", "cagr", "cagr_etf", "mdd", "trades",
                                                                               "t_pre", "t_post")} for mk in mks}}
        print(f"{k:9} 合併 t {real:5.2f}（前半 {t1:.2f}／後半 {t2:.2f}）  隨機第 {pct:.0%} 百分位  "
              + "  ".join(f"{mk} {R[mk]['cells'][k]['alpha_t']:.2f}" for mk in mks) + f"  → {v}", file=sys.stderr)
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=NEW)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--trades-only", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        pool_all()
        return
    if not args.market:
        a.error("--market 或 --pool")
    run_market(args.market, args.random, args.trades_only)


if __name__ == "__main__":
    main()
