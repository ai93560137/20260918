#!/usr/bin/env python3
"""VCP Minervini 忠實版回測（預先登記：VCP_FULLMARKET_BACKTEST.md 第四部分，寫程式前已 commit；三地只測一次）。

    python3 vcp_minervini.py --market hk --random 200

- 形態：t−1 收市後 vcp.base_info 成立（r = 0.8、D = 10%）＋趨勢模板（含 RS≥70）＋ t−1 收市 ≤ 樞紐點
- 入場：t 日盤中最高 > 樞紐點 → 成交價 max(開市, 樞紐點)；開市 > 樞紐點 ×(1+不追高上限) 不買
- 大市過濾：t−1 收市指數 ETF 在 50 日線和 200 日線之上
- 出場：初始止損 成交價×(1−止損%)，盤中觸及即出（跳空按開市）；收市 ≥ 成交價×1.15 後止損移到成交價；
  收市跌破 50 日線 → 下一日開市出；252 日上限；下市按最後收市
- 組合：日曆時間等權（成交價、止損價換成還原價計報酬）；統計沿用 newhigh_backtest.MarketData
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import vcp  # noqa: E402
import vcp_backtest as vb  # noqa: E402

GRID = [(stop, chase) for stop in (0.06, 0.075, 0.09) for chase in (0.03, 0.05, 0.08)]
DEFAULT = (0.075, 0.05)
BREAKEVEN_AT = 1.15
MAX_HOLD = 252


class Minervini:
    def __init__(self, market: str, exclude: set | None = None):
        self.v = v = vb.VCPData(market, full=True, exclude=exclude, scan=False)
        self.m = m = v.m
        self.ci = {d: j for j, d in enumerate(m.cal)}
        # 大市過濾：ETF 還原收市 > 50 日線 且 > 200 日線（用 m.etf_ret 重建水平）
        lvl = np.cumprod(1 + m.etf_ret)
        s = pd.Series(lvl)
        self.mkt_ok = ((s > s.rolling(50).mean()) & (s > s.rolling(200).mean())).to_numpy()
        self.setups = []      # (s, p_entry, j_entry, pivot, open, info)
        excl = exclude or set()
        n_eval = 0
        for s_i, rw in v.raw.items():
            dates = list(rw["dates"])
            high, low, close, vol, alow, opn = (rw[k] for k in ("high", "low", "close", "vol", "alow", "open"))
            for p in range(vcp.BASE_LOOKBACK + 1, len(dates)):
                d_prev, d = dates[p - 1], dates[p]
                j_prev, j = self.ci.get(d_prev), self.ci.get(d)
                if j is None or j_prev is None or j < m.start_j:
                    continue
                if not (v.tt[s_i, j_prev] and self.mkt_ok[j_prev]):
                    continue
                if not high[p] > high[p - 5:p].max():            # 樞紐點必 ≥ 前 5 日最高（右側不抬頭 + 最後收縮 ≥5 日）
                    continue
                n_eval += 1
                info = vcp.base_info(high, low, vol, alow, p - 1)
                if not vcp.passes(info) or close[p - 1] > info["pivot"] or not high[p] > info["pivot"]:
                    continue
                if (m.tickers[s_i], d.isoformat()) in excl:
                    continue
                self.setups.append((s_i, p, j, info["pivot"], opn[p] if opn[p] == opn[p] else info["pivot"], info))
        print(f"[{market}] 形態＋大市過濾＋突破前 5 日高 候選 {n_eval}、樞紐點突破 {len(self.setups)}", file=sys.stderr)

    def simulate(self, s_i: int, p: int, fill: float, stop_pct: float) -> tuple[int, float, bool]:
        """回傳 (出場 raw 索引, 出場原始價, 是否收市出場)。"""
        rw = self.v.raw[s_i]
        high, low, close, opn, adj, ma50 = (rw[k] for k in ("high", "low", "close", "open", "adj", "ma50"))
        n = len(close)
        stop = fill * (1 - stop_pct)
        if low[p] <= stop:                               # 入場當日就觸及止損
            return p, stop, False
        exit_next_open = False
        for k in range(p, min(n, p + MAX_HOLD + 1)):
            if k > p:
                o = opn[k] if opn[k] == opn[k] and opn[k] > 0 else close[k]
                if exit_next_open:
                    return k, o, False
                if low[k] <= stop:
                    return k, min(o, stop), False
            if close[k] >= fill * BREAKEVEN_AT:
                stop = max(stop, fill)
            if ma50[k] == ma50[k] and adj[k] < ma50[k]:
                exit_next_open = True
        k = min(n, p + MAX_HOLD + 1) - 1
        return k, close[k], True

    def trades(self, stop_pct: float, chase: float, random_seed: int | None = None) -> list[dict]:
        m, v = self.m, self.v
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy = [], {}
        by_day = {}
        for (s_i, p, j, pivot, o, _) in self.setups:
            by_day.setdefault(j, set()).add(s_i)
        for (s_i, p, j, pivot, o, _) in sorted(self.setups, key=lambda x: (x[2], x[0])):
            if o > pivot * (1 + chase):
                continue                                   # 不追高
            if rng is None:
                if p <= busy.get(s_i, -1):
                    continue
                fill = max(o, pivot)
                k, px, at_close = self.simulate(s_i, p, fill, stop_pct)
                busy[s_i] = k
                out.append(self._trade(s_i, p, fill, k, px, at_close))
            else:
                # 隨機對照：同日 t−1 通過趨勢模板、當天不是 VCP 突破的股票，t 開市買、同一套出場
                j_prev = j - 1
                pool = np.nonzero(v.tt[:, j_prev])[0]
                pool = pool[~np.isin(pool, list(by_day[j]))]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
                pr = v.raw[r]["dates"].get(m.cal[j])
                if pr is None:
                    continue
                o_r = v.raw[r]["open"][pr]
                if not (o_r == o_r and o_r > 0):
                    continue
                k, px, at_close = self.simulate(r, pr, o_r, stop_pct)
                out.append(self._trade(r, pr, o_r, k, px, at_close))
        return out

    def _trade(self, s_i, p, fill, k, px, at_close) -> dict:
        rw = self.v.raw[s_i]
        f_in = rw["adj"][p] / rw["close"][p]
        f_out = rw["adj"][k] / rw["close"][k]
        dates = list(rw["dates"])
        return {"s": s_i, "a": self.ci[dates[p]], "b": self.ci[dates[k]], "in_adj": fill * f_in,
                "out_adj": px * f_out, "at_close": at_close}

    def daily(self, trades: list[dict]) -> tuple[np.ndarray, list[float], np.ndarray]:
        m = self.m
        S, D = m.adj.shape
        cost = m.cfg["cost"]
        diff = np.zeros((S, D + 1), dtype=np.int32)
        extra, cnt = np.zeros(D), np.zeros(D)
        tr = []
        for t in trades:
            s, a, b = t["s"], t["a"], t["b"]
            if a == b:
                extra[a] += t["out_adj"] / t["in_adj"] - 1 - 2 * cost
                cnt[a] += 1
            else:
                extra[a] += m.adj[s, a] / t["in_adj"] - 1 - cost
                cnt[a] += 1
                if b - 1 >= a + 1:
                    diff[s, a + 1] += 1
                    diff[s, b] -= 1
                prev = m.prev_close[s, b]
                extra[b] += (t["out_adj"] / prev - 1 if prev == prev and prev > 0 else 0.0) - cost
                cnt[b] += 1
            tr.append(t["out_adj"] / t["in_adj"] * (1 - cost) ** 2 - 1)
        C = np.cumsum(diff[:, :D], axis=1)
        total = (m.ret * C).sum(0) + extra
        n = C.sum(0) + cnt
        return np.where(n > 0, total / np.maximum(n, 1), 0.0), tr, n

    def evaluate(self, trades: list[dict]) -> dict:
        m = self.m
        daily, tr, n = self.daily(trades)
        mo, me, mw = m.monthly(daily), m.monthly(m.etf_ret), m.monthly(m.ew_ret)
        a, b, t = m.capm(mo, me)
        t_ew = m.capm(mo, mw)[2]
        sp = pd.Timestamp(m.cfg["split"])
        pre = m.capm(mo[mo.index < sp], me[me.index < sp])[2] if (mo.index < sp).sum() > 24 else float("nan")
        post = m.capm(mo[mo.index >= sp], me[me.index >= sp])[2] if (mo.index >= sp).sum() > 24 else float("nan")
        eq = (1 + pd.Series(daily[m.start_j:])).cumprod()
        eqe = (1 + pd.Series(m.etf_ret[m.start_j:])).cumprod()
        yrs = len(eq) / 252
        return {"trades": len(trades), "t": t, "beta": b, "t_ew": t_ew, "t_pre": pre, "t_post": post,
                "cagr": eq.iloc[-1] ** (1 / yrs) - 1, "cagr_etf": eqe.iloc[-1] ** (1 / yrs) - 1,
                "mdd": float((eq / eq.cummax() - 1).min()), "mdd_etf": float((eqe / eqe.cummax() - 1).min()),
                "win": float(np.mean([x > 0 for x in tr])) if tr else math.nan,
                "avg_trade": float(np.mean(tr)) if tr else math.nan,
                "avg_hold": float(np.mean([x["b"] - x["a"] for x in trades])) if trades else math.nan,
                "avg_pos": float(n[m.start_j:].mean()), "stopped_first_day": sum(x["a"] == x["b"] for x in trades)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "vcp_full")
    ap.add_argument("--inspect", type=int, default=0, help="只印前 N 筆預設格交易明細（檢查機制，不印績效）")
    args = ap.parse_args()
    sus_p = ROOT / "research" / "vcp_full" / f"{args.market}_suspect.json"
    excl = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() else set()
    mv = Minervini(args.market, excl)
    m = mv.m
    if args.inspect:
        for t in mv.trades(*DEFAULT)[:args.inspect]:
            print(m.tickers[t["s"]], m.cal[t["a"]], "→", m.cal[t["b"]], f"入 {t['in_adj']:.4g} 出 {t['out_adj']:.4g}",
                  "收市出" if t["at_close"] else "開市/止損出")
        return
    res = {"market": args.market, "cells": {}}
    for stop, chase in GRID:
        e = mv.evaluate(mv.trades(stop, chase))
        key = f"止損{stop:.1%} 不追{chase:.0%}"
        res["cells"][key] = e
        print(f"{key:16} 筆數 {e['trades']:5d}  alpha t {e['t']:5.2f}  vs等權 t {e['t_ew']:5.2f}  beta {e['beta']:.2f}  "
              f"年化 {e['cagr']:+.1%} (ETF {e['cagr_etf']:+.1%})  MDD {e['mdd']:.0%} (ETF {e['mdd_etf']:.0%})  "
              f"勝率 {e['win']:.0%}  每筆 {e['avg_trade']:+.2%}  持有 {e['avg_hold']:.0f} 日  持倉 {e['avg_pos']:.1f}  "
              f"入場當日止損 {e['stopped_first_day']}  前/後 t {e['t_pre']:.2f}/{e['t_post']:.2f}", file=sys.stderr)
    if args.random:
        real = res["cells"][f"止損{DEFAULT[0]:.1%} 不追{DEFAULT[1]:.0%}"]["t"]
        ts = sorted(mv.evaluate(mv.trades(*DEFAULT, random_seed=sd))["t"] for sd in range(args.random))
        pct = sum(x < real for x in ts) / len(ts)
        res["random"] = {"median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))], "real_pctl": pct, "n": len(ts)}
        print(f"隨機對照 {len(ts)} 次：中位數 {ts[len(ts) // 2]:.2f}、第 95 百分位 {ts[int(0.95 * len(ts))]:.2f}；"
              f"預設格 {real:.2f} 在第 {pct:.0%} 百分位", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.market}_minervini.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float)
                                                            + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
