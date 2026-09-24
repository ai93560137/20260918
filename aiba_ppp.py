#!/usr/bin/env python3
"""相場師朗「PPP 中的下半身」全市場回測（預先登記：AIBA_PPP_BACKTEST.md，寫程式前已 commit；三地只測一次）。

    python3 aiba_ppp.py --market hk --trades-only        # 只寫預設格逐筆明細（給 verify_trades 抽樣核對，不印績效）
    python3 aiba_ppp.py --market hk --random 200         # 正式一次：鄰域 9 格 + 隨機對照
    python3 aiba_ppp.py --market hk --hl-repair --tag _hlrepair   # 港股敏感度（只作參考）
    python3 aiba_ppp.py --market hk --exit ema5 --random 200      # 第三部分：五日 EMA 出場、絕對回報判決

- 形態用還原 K 線（開市、收市 × AdjClose/Close），均線 = 還原收市 SMA，「向上」= 今天 > 昨天
- 訊號（t 收市）：PPP（預設 M5>M10>M20>M60 且 M10/M20/M60 向上）＋ 下半身（陽燭、O < M5 < C、
  (C−M5) ≥ 0.5(C−O)）＋ M5 向上；t+1 開市買
- 出場（觸發日下一個交易日開市）：逆下半身（陰燭、O > M5 > C、(M5−C) ≥ 0.5(O−C)、M5 向下）或收市 < M60；
  252 日上限；下市按最後收市
- 組合、成本、統計沿用 newhigh_backtest.MarketData（全市場成交額前 N 宇宙、品質檢查排除）
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
import vcp_backtest as vb  # noqa: E402

DEPTHS = (20, 60, 100)
HALVES = (0.0, 0.5, 0.75)
GRID = [(d, h) for d in DEPTHS for h in HALVES]
DEFAULT = (60, 0.5)
RULE = "pp"


def features(df: pd.DataFrame) -> dict[str, pd.Series]:
    """一檔股票（自己的交易日序列）的 PPP、下半身、出場條件。"""
    f = df["AdjClose"] / df["Close"]
    C = df["AdjClose"]
    O = df["Open"].where(df["Open"] > 0) * f
    M = {k: C.rolling(k).mean() for k in (5, 10, 20, 60, 100)}
    up = {k: M[k] > M[k].shift(1) for k in M}
    out = {}
    p20 = (M[5] > M[10]) & (M[10] > M[20]) & up[10] & up[20]
    p60 = p20 & (M[20] > M[60]) & up[60]
    p100 = p60 & (M[60] > M[100]) & up[100]
    out["ppp20"], out["ppp60"], out["ppp100"] = p20, p60, p100
    cross = (C > O) & (O < M[5]) & (M[5] < C) & up[5]
    for h in HALVES:
        out[f"kh{h}"] = cross & ((C - M[5]) >= h * (C - O))
    rev = (C < O) & (O > M[5]) & (M[5] > C) & ((M[5] - C) >= 0.5 * (O - C)) & (M[5] < M[5].shift(1))
    out["rev"] = rev
    out["below60"] = C < M[60]
    out["x5"] = C < C.ewm(span=5, adjust=False).mean()      # 第三部分：收市跌破五日 EMA
    return out


class AibaPPP:
    def __init__(self, market: str, repair_hl: bool = False, exit_rule: str = "rev", m=None):
        self.exit_rule = exit_rule
        if m is None:      # m：可傳入現成的全市場 MarketData（同宇宙、同成本），省得重建
            pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{market}_pool.txt").read_text(
                encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            m = nb.MarketData(market, pool=pool, loader=nb.load_full(market, repair_hl),
                              top_n=vb.FULL_TOP_N[market], cost=vb.FULL_COST[market])
        self.m = m
        S, D = m.adj.shape
        idx = pd.Index(m.cal)
        keys = [f"ppp{d}" for d in DEPTHS] + [f"kh{h}" for h in HALVES] + ["rev", "below60", "x5"]
        self.mat = {k: np.zeros((S, D), dtype=bool) for k in keys}
        for s, t in enumerate(m.tickers):
            df = pd.DataFrame(m.loader(t)).set_index("Date")
            df = df[(df["AdjClose"] > 0) & (df["Close"] > 0)]
            for k, ser in features(df).items():
                self.mat[k][s] = ser.reindex(idx).fillna(False).to_numpy(dtype=bool)
        self.set_exit(exit_rule)

    def set_exit(self, exit_rule: str) -> None:
        m, D = self.m, len(self.m.cal)
        self.exit_rule = exit_rule
        m.exitc[RULE] = self.mat["x5"] if exit_rule == "ema5" else self.mat["rev"] | self.mat["below60"]
        ii = np.where(m.exitc[RULE], np.arange(D)[None, :], D)
        m.next_exit[RULE] = np.minimum.accumulate(ii[:, ::-1], axis=1)[:, ::-1]

    def events(self, depth: int, half: float, exclude: set | None = None) -> np.ndarray:
        m = self.m
        ev = self.mat[f"ppp{depth}"] & self.mat[f"kh{half}"] & m.member & m.has
        ev[:, :m.start_j] = False
        for t, d in (exclude or set()):
            s = m.tickers.index(t) if t in m.tickers else None
            j = m.ci.get(pd.Timestamp(d).date())
            if s is not None and j is not None:
                ev[s, j] = False
        return ev

    def signal_of(self, ev: np.ndarray, trades: list) -> list[int]:
        """每筆交易對應的訊號日（入場前最後一個訊號日）。"""
        out = []
        for s, a, _, _ in trades:
            js = np.nonzero(ev[s, :a])[0]
            out.append(int(js[-1]))
        return out

    def random_trades(self, ev: np.ndarray, depth: int, seed: int) -> list:
        """同日從「宇宙內、同一深度 PPP、當天不是下半身訊號」的股票隨機挑一檔，t+1 開市買、同一套出場。"""
        m = self.m
        rng = np.random.default_rng(seed)
        D = len(m.cal)
        pp = self.mat[f"ppp{depth}"]
        out, cache = [], {}
        for s, e in zip(*np.nonzero(ev)):
            if e + 1 >= D:
                continue
            if e not in cache:
                cache[e] = np.nonzero(m.member[:, e] & m.has[:, e] & pp[:, e] & ~ev[:, e])[0]
            pool = cache[e]
            if len(pool) == 0:
                continue
            r = int(pool[rng.integers(len(pool))])
            entry = m.next_px[r, e + 1]
            if entry >= D:
                continue
            ex, op = m.exit_index(r, entry, RULE)
            if ex >= entry:
                out.append((r, int(entry), ex, op))
        return out

    def exit_reasons(self, trades: list) -> dict:
        m = self.m
        D = len(m.cal)
        c = Counter()
        for s, a, b, op in trades:
            if not op:
                c["下市／樣本末仍持有"] += 1
                continue
            sig = int(m.next_exit[RULE][s, a])
            if sig + 1 >= D or m.next_px[s, sig + 1] != b:
                c["252 日上限"] += 1
            elif self.exit_rule == "ema5":
                c["跌破五日 EMA"] += 1
            elif self.mat["rev"][s, sig]:
                c["逆下半身"] += 1
            else:
                c["跌破 60 日線"] += 1
        return dict(c)

    def detail(self, ev: np.ndarray, trades: list) -> list[dict]:
        """逐筆原始價（給 scripts/verify_trades.py 對第二來源）。"""
        m = self.m
        sigs = self.signal_of(ev, trades)
        rows_cache = {}
        out = []
        for (s, a, b, op), j in zip(trades, sigs):
            t = m.tickers[s]
            if t not in rows_cache:
                rows_cache[t] = {r["Date"]: r for r in m.loader(t)}
            R = rows_cache[t]
            rs, ra, rb = R.get(m.cal[j]), R.get(m.cal[a]), R.get(m.cal[b])
            out.append({"ticker": t, "signal": m.cal[j].isoformat(), "entry": m.cal[a].isoformat(),
                        "exit": m.cal[b].isoformat(), "exit_at_open": bool(op),
                        "signal_close": float(rs["Close"]) if rs else None,
                        "signal_volume": float(rs["Volume"]) if rs else None,
                        "entry_open": float(ra["Open"]) if ra and ra["Open"] == ra["Open"] else None,
                        "exit_px": (float(rb["Open"] if op else rb["Close"]) if rb else None),
                        "tv_rank": int(m.tv_rankpos[t][j])})
        return out


def abs_t(m, trades) -> dict:
    """絕對回報 t（第三部分主指標）：組合每月淨報酬平均 ÷ (標準差 ÷ √月數)；前後段同樣算。"""
    mo = m.monthly(m.portfolio(trades)[0])
    sp = pd.Timestamp(m.cfg["split"])

    def t(x):
        return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 24 and x.std() > 0 else float("nan")
    return {"t_abs": t(mo), "t_abs_pre": t(mo[mo.index < sp]), "t_abs_post": t(mo[mo.index >= sp]),
            "mean_month": float(mo.mean())}


def summarize(e: dict) -> dict:
    # 逐筆統計去掉 NaN（樣本末仍持有、最後一個日曆日停牌的股票沒有收市價；組合日報酬不受影響）
    tr = [x for x in e.pop("tr") if x == x]
    e["win"] = float(np.mean([x > 0 for x in tr])) if tr else float("nan")
    e["avg_trade"] = float(np.mean(tr)) if tr else float("nan")
    pos = sorted(tr, reverse=True)
    tot = sum(tr)
    e["top10_share"] = float(sum(pos[:10]) / tot) if tot > 0 else float("nan")
    by = e["by_year"]
    e["pos_years"] = f"{sum(v > 0 for v in by.values())}/{len(by)}"
    e["worst_year"] = min(by.items(), key=lambda kv: kv[1]) if by else None
    return e


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--trades-only", action="store_true", help="只寫預設格逐筆明細，不算績效")
    ap.add_argument("--hl-repair", action="store_true", help="港股敏感度：只因高低價矛盾被排除的股票放回來")
    ap.add_argument("--tag", default="")
    ap.add_argument("--exit", default="rev", choices=["rev", "ema5"], help="rev = 第二部分；ema5 = 第三部分")
    args = ap.parse_args()
    mk = args.market
    out_dir = ROOT / "research" / "aiba_ppp"
    out_dir.mkdir(parents=True, exist_ok=True)
    ap_ = AibaPPP(mk, repair_hl=args.hl_repair, exit_rule=args.exit)
    ema = args.exit == "ema5"
    tag = args.tag + ("_ema5" if ema else "")
    m = ap_.m
    if args.trades_only:
        ev = ap_.events(*DEFAULT)
        tr = m.trades_from_events(ev, RULE)
        det = ap_.detail(ev, tr)
        (out_dir / f"{mk}_trades.json").write_text(json.dumps({"market": mk, "trades_detail": det}, ensure_ascii=False)
                                                   + "\n", encoding="utf-8")
        print(f"[{mk}] 預設格 {len(det)} 筆明細已寫出（未算績效）", file=sys.stderr)
        return
    sus_p = out_dir / f"{mk}_suspect.json"
    excl = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not args.tag else set()
    tkey = "t_abs" if ema else "t"
    res = {"market": mk, "excluded_suspects": sorted(map(list, excl)), "cells": {}}
    cells = [DEFAULT] if args.tag else GRID
    for d, h in cells:
        ev = ap_.events(d, h, excl)
        trades = m.trades_from_events(ev, RULE)
        e = summarize(m.evaluate(trades))
        if ema:
            e.update(abs_t(m, trades))
        e["n_signals"] = int(ev.sum())
        e["exit_reasons"] = ap_.exit_reasons(trades)
        key = f"PPP{d} 下半身{h}"
        res["cells"][key] = e
        print(f"{key:16} 訊號 {e['n_signals']:6d} 筆數 {e['trades']:6d}  alpha t {e['t']:5.2f}  vs等權 t {e['t_ew']:5.2f}  "
              f"beta {e['beta']:.2f}  年化 {e['cagr']:+.1%} (ETF {e['cagr_etf']:+.1%})  MDD {e['mdd']:.0%} "
              f"(ETF {e['mdd_etf']:.0%})  勝率 {e['win']:.0%}  每筆 {e['avg_trade']:+.2%}  持有 {e['avg_hold']:.0f} 日  "
              f"持倉 {e['avg_pos']:.1f}  前/後 t {e['t_pre']:.2f}/{e['t_post']:.2f}", file=sys.stderr)
        if ema:
            print(f"{'':16} 【絕對】t {e['t_abs']:5.2f}  前/後 {e['t_abs_pre']:.2f}/{e['t_abs_post']:.2f}  "
                  f"每月平均 {e['mean_month']:+.2%}", file=sys.stderr)
        if (d, h) == DEFAULT:
            print(f"  出場原因 {e['exit_reasons']}；正年數 {e['pos_years']}、最差年 {e['worst_year']}；"
                  f"前 10 筆佔總獲利 {e['top10_share']:.0%}", file=sys.stderr)
            sigs = ap_.signal_of(ev, trades)
            third = m.top_n / 3
            ranks = [int(m.tv_rankpos[m.tickers[s]][j]) for (s, *_), j in zip(trades, sigs)]
            res["rank_dist"] = {"大型（前 1/3）": sum(r <= third for r in ranks),
                                "中型": sum(third < r <= 2 * third for r in ranks),
                                "小型（後 1/3）": sum(r > 2 * third for r in ranks)}
            print(f"  訊號成交額排名分布：{res['rank_dist']}", file=sys.stderr)
            if excl:     # 登記：可疑剔除前後取較保守
                tr0 = m.trades_from_events(ap_.events(*DEFAULT), RULE)
                e0 = summarize(m.evaluate(tr0))
                if ema:
                    e0.update(abs_t(m, tr0))
                res["default_no_exclusion"] = {k: e0[k] for k in ("trades", "t", "t_ew", "t_pre", "t_post", "t_abs") if k in e0}
                print(f"  不剔除可疑：筆數 {e0['trades']}  alpha t {e0['t']:.2f}  vs等權 t {e0['t_ew']:.2f}"
                      + (f"  絕對 t {e0['t_abs']:.2f}" if ema else ""), file=sys.stderr)
    if args.random:
        ev = ap_.events(*DEFAULT, excl)
        real = res["cells"][f"PPP{DEFAULT[0]} 下半身{DEFAULT[1]}"][tkey]

        def metric(tr):
            return abs_t(m, tr)["t_abs"] if ema else m.evaluate(tr)["t"]
        ts = sorted(metric(ap_.random_trades(ev, DEFAULT[0], sd)) for sd in range(args.random))
        pct = sum(x < real for x in ts) / len(ts)
        res["random"] = {"metric": tkey, "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))], "real_pctl": pct, "n": len(ts)}
        print(f"隨機對照 {len(ts)} 次：中位數 {ts[len(ts) // 2]:.2f}、第 95 百分位 {ts[int(0.95 * len(ts))]:.2f}；"
              f"預設格 {real:.2f} 在第 {pct:.0%} 百分位", file=sys.stderr)
    (out_dir / f"{mk}{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
