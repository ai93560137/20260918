#!/usr/bin/env python3
"""VCP 回測（預先登記見 VCP_BACKTEST.md，跑數前已 commit）。組合、成本、統計沿用 newhigh_backtest.MarketData。

    python3 vcp_backtest.py --market hk --random 200
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
import newhigh_backtest as nb  # noqa: E402
import vcp  # noqa: E402

GRID = [(r, D) for r in (0.7, 0.8, 0.9) for D in (0.08, 0.10, 0.15)]
DEFAULT = (0.8, 0.10)


class VCPData:
    def __init__(self, market: str):
        self.m = m = nb.MarketData(market)
        S, Dn = m.adj.shape
        idx = pd.Index(m.cal)
        self.raw = {}
        partial = np.zeros((S, Dn), dtype=bool)
        volc = np.zeros((S, Dn), dtype=bool)
        r252 = np.full((S, Dn), np.nan)
        for s, t in enumerate(m.tickers):
            df = pd.DataFrame(md.load_ohlcv(t)).set_index("Date")
            df = df[df["AdjClose"] > 0]
            f = df["AdjClose"] / df["Close"]
            adj, close = df["AdjClose"], df["Close"]
            high = pd.concat([df["High"].fillna(close), close], axis=1).max(axis=1)
            low = pd.concat([df["Low"].where(df["Low"] > 0).fillna(close), close], axis=1).min(axis=1)
            vol = df["Volume"].astype(float)
            ma50, ma150, ma200 = (adj.rolling(n).mean() for n in (50, 150, 200))
            tt = ((adj > ma50) & (ma50 > ma150) & (ma150 > ma200) & (ma200 > ma200.shift(21))
                  & (adj >= adj.rolling(252).min() * 1.30) & (adj >= adj.rolling(252).max() * 0.75))
            avg50 = vol.rolling(50).mean().shift(1)
            vb = (vol >= vcp.VOL_BREAK * avg50) & (avg50 > 0)
            partial[s] = tt.reindex(idx).fillna(False).to_numpy(dtype=bool)
            volc[s] = vb.reindex(idx).fillna(False).to_numpy(dtype=bool)
            r252[s] = (adj / adj.shift(252) - 1).reindex(idx).to_numpy()
            self.raw[s] = {"dates": {d: i for i, d in enumerate(df.index)}, "high": high.to_numpy(),
                           "low": low.to_numpy(), "close": close.to_numpy(), "vol": vol.to_numpy(),
                           "alow": (low * f).to_numpy()}
        # 相對強度：當天 PIT 成分股中 252 日報酬的百分位
        rs = np.full((S, Dn), np.nan)
        for j in range(Dn):
            ok = m.member[:, j] & ~np.isnan(r252[:, j])
            if ok.sum() >= 5:
                v = r252[ok, j]
                rs[ok, j] = pd.Series(v).rank(pct=True).to_numpy() * 100
        self.tt = partial & (np.nan_to_num(rs) >= 70) & m.member
        cand = self.tt & volc
        cand[:, :m.start_j] = False
        self.info = {}
        for s, j in zip(*np.nonzero(cand)):
            rw = self.raw[s]
            p = rw["dates"].get(m.cal[j])
            if p is None:
                continue
            info = vcp.analyze(rw["high"], rw["low"], rw["close"], rw["vol"], rw["alow"], p)
            if info:
                self.info[(int(s), int(j))] = info
        print(f"[{market}] 趨勢模板+放量候選 {int(cand.sum())} 個、形態成立（未判 r/D）{len(self.info)} 個", file=sys.stderr)

    def events(self, r: float, D: float) -> dict:
        return {k: v for k, v in self.info.items() if vcp.passes(v, r, D)}

    def xv_exit(self, s: int, entry: int, stop: float) -> tuple[int, bool]:
        """收市跌破 max(停損位, 20 日低點) → 下一個交易日開盤出場。"""
        m = self.m
        Dn = len(m.cal)
        cap = min(entry + nb.MAX_HOLD, Dn - 1)
        seg = m.adj[s, entry:cap + 1]
        hit = np.nonzero(np.nan_to_num(seg, nan=np.inf) < stop)[0]
        sig = min(entry + int(hit[0]) if len(hit) else Dn, int(m.next_exit["x2"][s, entry]))
        j = m.next_px[s, sig + 1] if sig + 1 < Dn else Dn
        if j > cap:
            j = m.next_px[s, cap] if cap < Dn else Dn
        if j >= Dn:
            last = m.last_px[s]
            return (last, False) if last < Dn - 5 else (Dn - 1, False)
        return int(j), True

    def trades(self, ev: dict, rule: str) -> list:
        m = self.m
        Dn = len(m.cal)
        out, busy = [], {}
        for (s, j), info in sorted(ev.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if j + 1 >= Dn:
                continue
            entry = m.next_px[s, j + 1]
            if entry >= Dn or entry <= busy.get(s, -1):
                continue
            if rule == "xv":
                ex, op = self.xv_exit(s, entry, info["stop_adj"])
            else:
                ex, op = m.exit_index(s, entry, rule)
            if ex < entry:
                continue
            out.append((s, int(entry), ex, op))
            busy[s] = ex
        return out

    def random_trades(self, ev: dict, seed: int) -> list:
        m = self.m
        rng = np.random.default_rng(seed)
        Dn = len(m.cal)
        by_day = {}
        for (s, j) in ev:
            by_day.setdefault(j, set()).add(s)
        out = []
        for (s, j), info in ev.items():
            if j + 1 >= Dn:
                continue
            pool = np.nonzero(self.tt[:, j])[0]
            pool = pool[~np.isin(pool, list(by_day[j]))]
            if len(pool) == 0:
                continue
            r = int(pool[rng.integers(len(pool))])
            entry = m.next_px[r, j + 1]
            if entry >= Dn or np.isnan(m.adj[r, j]):
                continue
            stop = m.adj[r, j] * info["stop_adj"] / m.adj[s, j]
            ex, op = self.xv_exit(r, entry, stop)
            if ex >= entry:
                out.append((r, int(entry), ex, op))
        return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=list(nb.MARKETS))
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "vcp")
    args = ap.parse_args()
    v = VCPData(args.market)
    m = v.m
    res = {"market": args.market, "cells": {}, "random": {}}
    for r, D in GRID:
        ev = v.events(r, D)
        rules = ("xv", "x2", "x1", "x3") if (r, D) == DEFAULT else ("xv",)
        for rule in rules:
            tr = v.trades(ev, rule)
            if not tr:
                print(f"r={r} D={D:.0%} {rule}: 0 筆", file=sys.stderr)
                res["cells"][f"r={r} D={D:.0%}|{rule}"] = {"trades": 0}
                continue
            e = m.evaluate(tr)
            key = f"r={r} D={D:.0%}|{rule}"
            stops = [1 - ev[(s, j)]["stop_adj"] / m.adj[s, j] for (s, j) in ev] if rule == "xv" else []
            res["cells"][key] = {k: val for k, val in e.items() if k != "tr"}
            if stops:
                res["cells"][key]["avg_stop"] = float(np.mean(stops))
            print(f"{key:22} 訊號 {len(ev):5d} 筆數 {e['trades']:5d}  alpha t {e['t']:5.2f}  vs等權 t {e['t_ew']:5.2f}  "
                  f"beta {e['beta']:.2f}  年化 {e['cagr']:+.1%} (ETF {e['cagr_etf']:+.1%})  MDD {e['mdd']:.0%} "
                  f"(ETF {e['mdd_etf']:.0%})  勝率 {e['win']:.0%}  每筆 {e['avg_trade']:+.2%}  持有 {e['avg_hold']:.0f} 日  "
                  f"持倉 {e['avg_pos']:.1f}  前/後 t {e['t_pre']:.2f}/{e['t_post']:.2f}"
                  + (f"  平均停損距離 {np.mean(stops):.1%}" if stops else ""), file=sys.stderr)
        if (r, D) == DEFAULT:
            res["n_t"] = dict(Counter(info["n_t"] for info in ev.values()))
            print(f"預設格收縮次數分布：{dict(sorted(res['n_t'].items()))}", file=sys.stderr)
    if args.random:
        ev = v.events(*DEFAULT)
        real = res["cells"][f"r={DEFAULT[0]} D={DEFAULT[1]:.0%}|xv"].get("t")
        ts = sorted(m.evaluate(v.random_trades(ev, sd))["t"] for sd in range(args.random))
        pct = sum(x < real for x in ts) / len(ts) if real is not None else float("nan")
        res["random"] = {"median": ts[len(ts) // 2], "p90": ts[int(0.9 * len(ts))], "real_pctl": pct, "n": len(ts)}
        print(f"隨機對照 {len(ts)} 次：中位數 {ts[len(ts) // 2]:.2f}、第 90 百分位 {ts[int(0.9 * len(ts))]:.2f}；"
              f"預設格 {real:.2f} 在第 {pct:.0%} 百分位", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
