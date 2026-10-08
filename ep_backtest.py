#!/usr/bin/env python3
"""Episodic Pivot（EP，Qullamaggie 式跳空啟動）回測（預先登記：stock_research/EP_BACKTEST.md，寫程式前已 commit；探索性、門檻稍後決定）。

    python3 ep_backtest.py --market hk --inspect 10        # 只印前 N 筆預設格交易機制（不印績效）
    python3 ep_backtest.py --market hk --trades-only       # 逐筆明細 + 內部一致性可疑清單
    python3 ep_backtest.py --market hk --random 200        # 正式：預設格 + 鄰域 + 隨機對照 + 敏感度
    python3 ep_backtest.py --pool

訊號（t 開盤前判斷、t 開盤成交）：t 開盤 ≥ t−1 收市 ×(1+GAP) 且 ≤ ×1.40；被冷落（60 日漲幅 ≤ 20%、t−1 不是 52 週收市新高）；
大市 ETF 10MA > 20MA 雙升；同檔 20 日內只取第一個跳空。出場同 HTF（ADR→當日低點停損、第 3 日減半保本、收市 < MA 次日開市出），
預設 20 日均線。宇宙、成本、組合、統計、台股漲停、基準 ETF 防護全部沿用 htf_backtest.HTF。
"""
import argparse
import bisect
import csv
import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import htf_backtest as hb  # noqa: E402

MARKETS = ("hk", "jp", "us", "tw")
GRID = [(g, ma) for g in (0.08, 0.10, 0.15) for ma in (10, 20, 50)]
DEFAULT = (0.10, 20)
GAP_MAX = 0.40
NEGLECT_R60 = 0.20
DEDUPE = 20
VOL_CONFIRM = 3.0
OUT = ROOT / "research" / "ep"
EVENTS = ROOT / "data" / "news" / "sp500_earnings_events.csv.gz"


def earnings_days(tickers: list[str]) -> dict[str, list[date]]:
    """美股財報版：每檔 S&P 500 成分股的財報交易日（session=pre → 申報當天；regular／post → 翌日；之後對到下一個有價日）。"""
    if not EVENTS.exists():
        return {}
    want = set(tickers)
    out: dict[str, list[date]] = {}
    with gzip.open(EVENTS, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r.get("price_ticker") or r.get("ticker")
            if t not in want:
                continue
            d = date.fromisoformat(r["filing_date"])
            if r.get("session") != "pre":
                d += timedelta(days=1)
            out.setdefault(t, []).append(d)
    return {t: sorted(set(v)) for t, v in out.items()}


class EP(hb.HTF):
    def scan(self) -> None:
        m = self.m
        S, D = m.adj.shape
        g_min = min(g for g, _ in GRID)
        self.setups = []
        self.neglect_ok = np.zeros((S, D), dtype=bool)
        earn = earnings_days(m.tickers) if self.market == "us" else {}
        n_gap = 0
        for s, rw in self.raw.items():
            jarr, opn, high, low, close, vol, adj = (rw[k] for k in ("jarr", "open", "high", "low", "close", "vol", "adj"))
            n = len(close)
            if n < 260:
                continue
            prev_close = np.r_[np.nan, close[:-1]]
            gap = np.where(prev_close > 0, opn / prev_close - 1, np.nan)
            negl = (rw["r60"] <= NEGLECT_R60) & (adj < rw["hi252prev"])
            # 被冷落矩陣（給隨機對照：用 t−1 的狀態標在 t−1 那一天）
            ok_j = jarr >= 0
            self.neglect_ok[s, jarr[ok_j]] = negl[ok_j]
            cand = np.nonzero((gap >= g_min) & (gap <= GAP_MAX) & (jarr >= m.start_j) & (np.r_[-1, jarr[:-1]] >= 0))[0]
            edays = earn.get(m.tickers[s], [])
            last_p = -10 ** 9
            for p in cand:
                if p < 1 or not m.member[s, jarr[p - 1]]:
                    continue
                n_gap += 1
                if p - last_p < DEDUPE:
                    continue
                last_p = p
                adr = rw["adr"][p - 1]
                if not (adr == adr and adr > 0):
                    continue
                d = rw["dlist"][p]
                is_earn = False
                if edays:
                    k = bisect.bisect_left(edays, d)
                    # 財報交易日 = 事件日對到的下一個有價日：事件日落在 (前一有價日, d] 之內
                    prev_d = rw["dlist"][p - 1]
                    is_earn = k > 0 and prev_d < edays[k - 1] <= d or (k < len(edays) and edays[k] == d)
                self.setups.append({"s": s, "p": p, "j": int(jarr[p]), "gap": float(gap[p]), "open": float(opn[p]),
                                    "neglect": bool(negl[p - 1]), "mkt": bool(self.mkt_ok[jarr[p - 1]]), "adr": float(adr),
                                    "vol_ratio": float(vol[p] / rw["avgvol50"][p]) if rw["avgvol50"][p] == rw["avgvol50"][p] and rw["avgvol50"][p] > 0 else float("nan"),
                                    "close_up": bool(close[p] > opn[p]), "earn": is_earn,
                                    "pivot": float(prev_close[p]), "G": float(gap[p]), "D": float("nan"), "flag_len": 0})
        self.setup_days = {}
        for st in self.setups:
            self.setup_days.setdefault(st["j"], set()).add(st["s"])
        n_mkt = sum(st["mkt"] for st in self.setups)
        n_neg = sum(st["mkt"] and st["neglect"] for st in self.setups)
        print(f"[{self.market}] 跳空 ≥ {g_min:.0%} 候選 {n_gap}、去重後 {len(self.setups)}、大市過濾成立 {n_mkt}、再加被冷落 {n_neg}"
              + (f"、其中財報日 {sum(st['earn'] for st in self.setups)}" if self.market == "us" else ""), file=sys.stderr)

    def trades(self, gap_min: float, ma: int, *, confirm: bool = False, mkt_filter: bool = True, neglect: bool = True,
               adr_min: float = 0.0, earnings_only: bool = False, random_seed: int | None = None, **_) -> list[dict]:
        m = self.m
        trail = f"ma{ma}"
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy = [], {}
        for st in sorted(self.setups, key=lambda x: (x["j"], x["s"])):
            s, p, j = st["s"], st["p"], st["j"]
            if st["gap"] < gap_min or st["adr"] < adr_min:
                continue
            if mkt_filter and not st["mkt"]:
                continue
            if neglect and not st["neglect"]:
                continue
            if earnings_only and not st["earn"]:
                continue
            rw = self.raw[s]
            if rng is None:
                if (m.tickers[s], rw["dlist"][p].isoformat()) in self.exclude:
                    continue
                if confirm:
                    # 敏感度：t 收市 > 開市 且 量 ≥ 3× 才確認，t+1 開盤買（停損用 t 日 ADR）
                    if not (st["close_up"] and st["vol_ratio"] >= VOL_CONFIRM) or p + 1 >= len(rw["close"]):
                        continue
                    pe = p + 1
                    if rw["jarr"][pe] < 0:
                        continue
                    o = rw["open"][pe]
                    fill = o if o == o and o > 0 else rw["close"][pe]
                    adr = rw["adr"][p]
                else:
                    pe, fill, adr = p, st["open"], st["adr"]
                if self.locked[s, rw["jarr"][pe]] or pe <= busy.get(s, -1) or not (adr == adr and adr > 0):
                    continue
                # 初始停損 = min(跳空回補價 = t−1 收市, 成交價×(1−ADR))：EP 取到的是回補價（登記修訂，見 EP_BACKTEST.md 出場）
                legs = self.simulate(s, pe, fill, adr, trail, stop0=min(st["pivot"], fill * (1 - adr)))
                busy[s] = legs[-1][0]
                out.append(self._trade(s, pe, fill, legs, st))
            else:
                # 隨機對照：同日 t 從「宇宙內、t−1 被冷落、當天不是 EP 訊號、t 開盤有價」隨機挑一檔，t 開盤買、同一套出場
                pool = np.nonzero(m.member[:, j - 1] & self.neglect_ok[:, j - 1])[0]
                pool = pool[~np.isin(pool, list(self.setup_days[j]))]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
                rr = self.raw[r]
                pr = rr["dates"].get(m.cal[j])
                if pr is None or pr < 1 or self.locked[r, j]:
                    continue
                o_r, adr_r = rr["open"][pr], rr["adr"][pr - 1]
                if not (o_r == o_r and o_r > 0 and adr_r == adr_r and adr_r > 0):
                    continue
                pc_r = rr["close"][pr - 1]
                legs = self.simulate(r, pr, o_r, adr_r, trail, stop0=min(pc_r, o_r * (1 - adr_r)) if pc_r > 0 else None)
                out.append(self._trade(r, pr, o_r, legs))
        return out


def run_market(mk: str, n_random: int, trades_only: bool, inspect: int) -> None:
    sus_p = OUT / f"{mk}_suspect.json"
    excl = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not trades_only else set()
    h = EP(mk, excl)
    m = h.m
    if inspect:
        for d in h.detail(h.trades(*DEFAULT)[:inspect]):
            d = {k: v for k, v in d.items() if k not in ("flag_depth", "flag_len")}
            print(json.dumps(d, ensure_ascii=False, default=float))
        return
    trs = h.trades(*DEFAULT)
    if trades_only:
        det = h.detail(trs)
        sus = [[d["ticker"], d["entry"]] for d in det if d["suspect"]]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{mk}_trades_detail.json").write_text(json.dumps({"market": mk, "n_total": len(det), "trades_detail": det},
                                                                 ensure_ascii=False, default=float) + "\n", encoding="utf-8")
        (OUT / f"{mk}_suspect.json").write_text(json.dumps(sus, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[{mk}] 預設格 {len(det)} 筆明細已寫出；內部一致性可疑 {len(sus)} 筆（{len(sus) / max(len(det), 1):.1%}）；未算績效", file=sys.stderr)
        return
    res = {"market": mk, "excluded_suspects": sorted(map(list, excl)), "n_setups": len(h.setups), "cells": {}, "abn": {}}
    for g, ma in GRID:
        key = f"GAP{g:.2f}_MA{ma}"
        t_ = trs if (g, ma) == DEFAULT else h.trades(g, ma)
        res["cells"][key] = h.evaluate(t_)
    res["default"] = f"GAP{DEFAULT[0]:.2f}_MA{DEFAULT[1]}"
    st = res["cells"][res["default"]]
    daily, tr, _ = h.daily(trs)
    res["abn"]["EP"] = h.abn(daily)
    top = set(np.argsort(-np.nan_to_num(np.array(tr), nan=-9))[:10])
    res["abn"]["EP_drop10"] = h.abn(h.daily([t for i, t in enumerate(trs) if i not in top])[0])
    sens = {"confirm_next_open": h.evaluate(h.trades(*DEFAULT, confirm=True)),
            "no_market_filter": h.evaluate(h.trades(*DEFAULT, mkt_filter=False)),
            "no_neglect": h.evaluate(h.trades(*DEFAULT, neglect=False)),
            "adr_min_4pct": h.evaluate(h.trades(*DEFAULT, adr_min=0.04)),
            "risk_weight": h.evaluate(trs, risk_weight=True)}
    if mk == "us":
        sens["earnings_only_sp500"] = h.evaluate(h.trades(*DEFAULT, earnings_only=True))
    res["sensitivity"] = {k: {x: v[x] for x in ("trades", "alpha_t", "cagr", "mdd", "win", "avg_hold", "t_pre", "t_post")}
                          for k, v in sens.items()}
    gaps = [t["info"]["gap"] for t in trs]
    res["gap_quartiles"] = [float(x) for x in np.percentile(gaps, [25, 50, 75])] if gaps else []
    if hasattr(m, "tv_rankpos"):
        rk = np.array([m.tv_rankpos[m.tickers[t["s"]]][t["a"]] for t in trs])
        res["tv_rank_dist"] = {"top_third": float((rk <= m.top_n / 3).mean()), "mid_third": float(((rk > m.top_n / 3) & (rk <= 2 * m.top_n / 3)).mean()),
                               "bottom_third": float((rk > 2 * m.top_n / 3).mean())} if len(rk) else {}
    print(f"[{mk}] 預設格 筆數 {st['trades']:5d}  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
          f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}  RRR {st['rrr']:.2f}  "
          f"期望值 {st['expectancy']:+.2%}  持有 {st['avg_hold']:.1f} 日  前10筆佔 {st['top10_share']:.0%}", file=sys.stderr)
    for key, c in res["cells"].items():
        print(f"   {key}  筆數 {c['trades']:5d}  alpha t {c['alpha_t']:5.2f}", file=sys.stderr)
    for key, c in res["sensitivity"].items():
        print(f"   敏感度 {key:24s} 筆數 {c['trades']:5d}  alpha t {c['alpha_t']:5.2f}", file=sys.stderr)
    rnd = [h.abn(h.daily(h.trades(*DEFAULT, random_seed=sd))[0]) for sd in range(n_random)]
    if rnd:
        real = hb.tstat_series(res["abn"]["EP"])
        rt = sorted(hb.tstat_series(x) for x in rnd)
        res["random"] = {"n": len(rt), "pctl": sum(x < real for x in rt) / len(rt), "median": rt[len(rt) // 2],
                         "p95": rt[int(0.95 * len(rt))], "real_resid_t": real}
        print(f"   隨機對照 {len(rt)} 次：真實殘差 t {real:.2f}，第 {res['random']['pctl']:.0%} 百分位（中位 {res['random']['median']:.2f}）", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--trades-only", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        hb.pool_all(MARKETS, OUT, "EP")
        return
    if not args.market:
        a.error("--market 或 --pool")
    run_market(args.market, args.random, args.trades_only, args.inspect)


if __name__ == "__main__":
    main()
