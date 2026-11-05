#!/usr/bin/env python3
"""「紀律本身」回測（預先登記：stock_research/DISCIPLINE_BACKTEST.md，寫程式前已 commit；9 國只測一次）。

    python3 discipline_backtest.py --market hk --inspect 5     # 手算用：前 5 筆交易明細（不算績效）
    python3 discipline_backtest.py --market hk --random 200    # 正式
    python3 discipline_backtest.py --pool                      # 9 市場合併檢定＋判決

訊號：t−1 新進入趨勢模板（含 RS≥70；之前 20 日都不在）＋大市 ETF > 50／200 日線；t 開市買；
出場與 Minervini 忠實版完全相同（vcp_minervini.Minervini.simulate：7.5% 止損、1.15 倍保本、跌破 50 日線、252 日上限）。
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402
from oos_backtest import abn, locked_matrix, pooled, summary, tstat  # noqa: E402

OUT = ROOT / "research" / "discipline"
MARKETS = ("hk", "jp", "us", "tw", "kr", "au", "ca", "in", "sg")
FRESH = 20                  # 之前 20 個交易日都不在趨勢模板
STOP = vm.DEFAULT[0]        # 7.5%
DIAG_HOLD = 63              # 描述性診斷：固定持有 63 日、無止損


class Discipline(vm.Minervini):
    def __init__(self, market: str):     # 不呼叫 Minervini.__init__（那裏會掃 VCP 形態）
        self.v = v = vb.VCPData(market, full=True, scan=False)
        self.m = m = v.m
        self.ci = {d: j for j, d in enumerate(m.cal)}
        lvl = pd.Series(np.cumprod(1 + m.etf_ret))
        self.mkt_ok = ((lvl > lvl.rolling(50).mean()) & (lvl > lvl.rolling(200).mean())).to_numpy()
        tt = v.tt.astype(bool)
        S, D = tt.shape
        cs = np.concatenate([np.zeros((S, 1), dtype=np.int32), np.cumsum(tt, axis=1, dtype=np.int32)], axis=1)
        prev = np.zeros((S, D), dtype=np.int32)
        prev[:, FRESH:] = cs[:, FRESH:D] - cs[:, :D - FRESH]          # 第 j 日之前 FRESH 日內在模板的日數
        fresh = tt & (prev == 0)
        fresh[:, :FRESH] = False
        self.tt = tt
        self.locked = locked_matrix(m, market)
        self.pool_ok = m.member & (m.has if hasattr(m, "has") else True)
        self.signals = sorted((int(j), int(s)) for s, j in zip(*np.nonzero(fresh))
                              if self.mkt_ok[j] and m.start_j <= j + 1 < D)
        print(f"[{market}] 新進入趨勢模板＋大市過濾 訊號 {len(self.signals)}", file=sys.stderr)

    def trades(self, random_seed: int | None = None, hold: int | None = None) -> list[dict]:
        m, v = self.m, self.v
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy = [], {}
        for jp, s in self.signals:
            j = jp + 1
            if rng is not None:       # 隨機對照：同日宇宙內、t−1 不在趨勢模板的股票
                pool = np.nonzero(self.pool_ok[:, jp] & ~self.tt[:, jp])[0]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
            else:
                r = s
            p = v.raw[r]["dates"].get(m.cal[j]) if r in v.raw else None
            if p is None or self.locked[r, j]:
                continue
            if rng is None and p <= busy.get(r, -1):
                continue
            o = v.raw[r]["open"][p]
            if not (o == o and o > 0):
                continue
            if hold is None:
                k, px, at_close = self.simulate(r, p, o, STOP)
            else:
                k = min(p + hold, len(v.raw[r]["close"]) - 1)
                px, at_close = v.raw[r]["close"][k], True
            if rng is None:
                busy[r] = k
            out.append(self._trade(r, p, o, k, px, at_close))
        return out


def run_market(mk: str, n_random: int, inspect: int) -> None:
    d = Discipline(mk)
    m = d.m
    trs = d.trades()
    if inspect:
        for t in trs[:inspect]:
            rw = d.v.raw[t["s"]]
            print(json.dumps({"ticker": m.tickers[t["s"]], "entry": m.cal[t["a"]].isoformat(), "exit": m.cal[t["b"]].isoformat(),
                              "in_adj": t["in_adj"], "out_adj": t["out_adj"], "ret": t["out_adj"] / t["in_adj"] - 1,
                              "exit_at_close": t["at_close"]}, ensure_ascii=False))
        print(f"[{mk}] 筆數 {len(trs)}（未算績效）", file=sys.stderr)
        return
    daily, tr, _ = d.daily(trs)
    st = summary(m, daily, tr, [x["b"] - x["a"] for x in trs], len(trs))
    tot = sum(x for x in tr if x == x)
    st["top10_share"] = float(sum(sorted((x for x in tr if x == x), reverse=True)[:10]) / tot) if tot > 0 else float("nan")
    res = {"market": mk, "n_signals": len(d.signals), "cells": {"discipline": st}, "abn": {"discipline": abn(m, daily)}}
    dg = d.trades(hold=DIAG_HOLD)
    dd, dtr, _ = d.daily(dg)
    res["cells"]["diag_hold63"] = summary(m, dd, dtr, [x["b"] - x["a"] for x in dg], len(dg))
    res["abn"]["diag_hold63"] = abn(m, dd)
    rnd = [abn(m, d.daily(d.trades(random_seed=sd))[0]) for sd in range(n_random)]
    for k, c in res["cells"].items():
        print(f"[{mk}] {k:12} 筆數 {c['trades']:6d}  alpha t {c['alpha_t']:5.2f}  前/後 {c['t_pre']:.2f}/{c['t_post']:.2f}  "
              f"年化 {c['cagr']:+.1%}（ETF {c['cagr_etf']:+.1%}）  MDD {c['mdd']:.0%}  勝率 {c['win']:.0%}  "
              f"RRR {c['rrr']:.2f}  持有 {c['avg_hold']:.0f} 日", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def pool_all() -> None:
    """登記第四節。"""
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}
    out = {}
    for k in ("discipline", "diag_hold63"):
        ser = pooled([R[mk]["abn"][k] for mk in MARKETS]).dropna()
        real = tstat(ser)
        h = len(ser) // 2
        t1, t2 = tstat(ser.iloc[:h]), tstat(ser.iloc[h:])
        pos = sum(R[mk]["cells"][k]["alpha_t"] > 0 for mk in MARKETS)
        o = {"pooled_t": real, "t_first_half": t1, "t_second_half": t2, "pos_markets": pos,
             "per_market": {mk: R[mk]["cells"][k]["alpha_t"] for mk in MARKETS}}
        if k == "discipline":
            n = min(len(RN[mk]) for mk in MARKETS)
            rt = sorted(tstat(pooled([RN[mk][i] for mk in MARKETS])) for i in range(n))
            pct = sum(x < real for x in rt) / n
            o.update({"random_pctl": pct, "random_median": rt[n // 2]})
            if real >= 2.7 and t1 > 0 and t2 > 0 and pos >= 6:
                v = ("🔍 值得再驗證：趨勢模板＋紀律本身有效" if pct >= 0.95
                     else "🔍 效果來自大市過濾＋出場紀律，趨勢模板沒有額外資訊")
            else:
                v = "☠️「紀律本身」假設不成立"
            o["verdict"] = v
        out[k] = o
        print(f"{k:12} 合併 t {real:5.2f}（前半 {t1:.2f}／後半 {t2:.2f}）  alpha>0 市場 {pos}/9"
              + (f"  隨機第 {o['random_pctl']:.0%} 百分位（中位 {o['random_median']:.2f}）  → {o['verdict']}" if k == "discipline" else "（描述性）"),
              file=sys.stderr)
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        pool_all()
        return
    if not args.market:
        a.error("--market 或 --pool")
    run_market(args.market, args.random, args.inspect)


if __name__ == "__main__":
    main()
