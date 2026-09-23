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
import newhigh_backtest as nb  # noqa: E402
import vcp  # noqa: E402

GRID = [(r, D) for r in (0.7, 0.8, 0.9) for D in (0.08, 0.10, 0.15)]
DEFAULT = (0.8, 0.10)
FULL_TOP_N = {"hk": 500, "jp": 1000, "us": 1500}          # 全市場宇宙：每日 60 日成交額中位數前 N
FULL_COST = {"hk": 0.0025, "jp": 0.0015, "us": 0.0010}   # 全市場成本（每邊）


class VCPData:
    def __init__(self, market: str, version: int = 2, n: int = vcp.FRACTAL_N, full: bool = False,
                 exclude: set | None = None):
        if full:     # 全市場版（VCP_FULLMARKET_BACKTEST.md）：成交額前 N、成本加大
            pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{market}_pool.txt").read_text(
                encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            self.m = m = nb.MarketData(market, pool=pool, loader=nb.load_full(market), top_n=FULL_TOP_N[market],
                                       cost=FULL_COST[market])
        else:
            self.m = m = nb.MarketData(market)
        S, Dn = m.adj.shape
        idx = pd.Index(m.cal)
        self.raw = {}
        partial = np.zeros((S, Dn), dtype=bool)
        volc = np.zeros((S, Dn), dtype=bool)
        r252 = np.full((S, Dn), np.nan)
        for s, t in enumerate(m.tickers):
            df = pd.DataFrame(m.loader(t)).set_index("Date")
            df = df[df["AdjClose"] > 0]
            f = df["AdjClose"] / df["Close"]
            adj, close = df["AdjClose"], df["Close"]
            high = pd.concat([df["High"].fillna(close), close], axis=1).max(axis=1)
            low = pd.concat([df["Low"].where(df["Low"] > 0).fillna(close), close], axis=1).min(axis=1)
            vol = df["Volume"].astype(float)
            tt = vcp.trend_template(adj)
            avg50 = vol.rolling(50).mean().shift(1)
            vb = (vol >= vcp.VOL_BREAK * avg50) & (avg50 > 0)
            partial[s] = tt.reindex(idx).fillna(False).to_numpy(dtype=bool)
            volc[s] = vb.reindex(idx).fillna(False).to_numpy(dtype=bool)
            r252[s] = (adj / adj.shift(252) - 1).reindex(idx).to_numpy()
            self.raw[s] = {"dates": {d: i for i, d in enumerate(df.index)}, "high": high.to_numpy(),
                           "low": low.to_numpy(), "close": close.to_numpy(), "vol": vol.to_numpy(),
                           "open": df["Open"].to_numpy(dtype=float),
                           "alow": (low * f).to_numpy()}
        # 相對強度：當天 PIT 成分股中 252 日報酬的百分位
        rs = np.full((S, Dn), np.nan)
        for j in range(Dn):
            ok = m.member[:, j] & ~np.isnan(r252[:, j])
            if ok.sum() >= 5:
                v = r252[ok, j]
                rs[ok, j] = pd.Series(v).rank(pct=True).to_numpy() * 100
        self.tt = partial & (np.nan_to_num(rs) >= vcp.RS_MIN) & m.member
        cand = self.tt & volc
        cand[:, :m.start_j] = False
        self.info = {}
        for s, j in zip(*np.nonzero(cand)):
            rw = self.raw[s]
            p = rw["dates"].get(m.cal[j])
            if p is None:
                continue
            info = vcp.analyze(rw["high"], rw["low"], rw["close"], rw["vol"], rw["alow"], p, version, n)
            if info and (m.tickers[s], m.cal[j].isoformat()) not in (exclude or set()):
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
    ap.add_argument("--version", type=int, default=2, choices=(1, 2), help="1 = 3%% ZigZag（原登記）、2 = 碎形高點（修訂）")
    ap.add_argument("--n", type=int, default=vcp.FRACTAL_N, help="v2 碎形窗口（預設 5；10 只作敏感度）")
    ap.add_argument("--full", action="store_true", help="全市場版（data_full/、成交額前 N）")
    ap.add_argument("--exclude-signals", type=Path, default=None,
                    help="逐筆核對標為可疑的訊號（JSON：[[ticker, 訊號日], ...]），剔除後重算")
    ap.add_argument("--tag", default="", help="輸出檔名後綴（例：_qc）")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    args.out = args.out or ROOT / "research" / ("vcp_full" if args.full else "vcp")
    excl = {tuple(x) for x in json.loads(args.exclude_signals.read_text())} if args.exclude_signals else None
    v = VCPData(args.market, args.version, args.n, full=args.full, exclude=excl)
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
            # 預設格逐筆（給 scripts/verify_trades.py 核對）
            raw_px = []
            for (s, a, b, op) in v.trades(ev, "xv"):
                t = m.tickers[s]
                j = next(jj for (ss, jj) in ev if ss == s and m.next_px[s, jj + 1] == a)
                rw = v.raw[s]
                p_sig, p_a = rw["dates"][m.cal[j]], rw["dates"].get(m.cal[a])
                p_b = rw["dates"].get(m.cal[b])
                raw_px.append({"ticker": t, "signal": m.cal[j].isoformat(), "entry": m.cal[a].isoformat(),
                               "exit": m.cal[b].isoformat(), "exit_at_open": bool(op),
                               "signal_close": float(rw["close"][p_sig]), "signal_volume": float(rw["vol"][p_sig]),
                               "entry_open": float(rw["open"][p_a]) if p_a is not None else None,
                               "exit_px": (float(rw["open"][p_b]) if op else float(rw["close"][p_b])) if p_b is not None else None,
                               "tv_rank": int(m.tv_rankpos[t][j]) if hasattr(m, "tv_rankpos") else None})
            res["trades_detail"] = raw_px
            if hasattr(m, "tv_rankpos"):
                third = m.top_n / 3
                ranks = [x["tv_rank"] for x in raw_px if x["tv_rank"]]
                res["rank_dist"] = {"大型（前 1/3）": sum(r_ <= third for r_ in ranks),
                                    "中型": sum(third < r_ <= 2 * third for r_ in ranks),
                                    "小型（後 1/3）": sum(r_ > 2 * third for r_ in ranks)}
                print(f"預設格訊號成交額排名分布：{res['rank_dist']}", file=sys.stderr)
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
    (args.out / (f"{args.market}_v{args.version}" + ("" if args.n == vcp.FRACTAL_N else f"_n{args.n}") + args.tag + ".json")).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
