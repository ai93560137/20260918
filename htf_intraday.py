#!/usr/bin/env python3
"""HTF 盤中執行版（預先登記：stock_research/HTF_INTRADAY_BACKTEST.md，寫程式前已 commit；探索性）。

    python3 htf_intraday.py --market hk --inspect 8      # 只印前 N 筆的日線版 vs 盤中版機制（不印績效）
    python3 htf_intraday.py --market hk                  # 正式：子集上 日線版 vs 盤中版（預設格＋變體）

同一批日線訊號（htf_backtest.HTF 預設格），入場日換成雲垂抓的 5 分 K（data_stock_ibkr/htf_5m/，本機、不進 git）：
開盤區間（預設第 1 根）高點與樞紐點取大者為 L，之後第一根最高 > L 成交；LOD 停損；ADR 鐵律（停損距離 > ADR → 放棄）。
之後各日與日線版相同。
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import htf_backtest as hb  # noqa: E402

BARS = ROOT / "data_stock_ibkr" / "htf_5m"
OUT = ROOT / "research" / "htf_intraday"
MARKETS = ("hk", "us", "tw")
BAD_FILES = {"us_GURE_2009-12-28.csv"}
MIN_BARS = 20
TOL_OC, TOL_HL = 0.020, 0.010   # 登記修訂：開收市 2%（港交所開市競價、2016 前收市中位數定義差），高低 1% 作尺度核對


def load_bars(mk: str, ticker: str, day) -> list[dict] | None:
    name = f"{mk}_{ticker}_{day.isoformat()}.csv"
    if name in BAD_FILES:
        return None
    p = BARS / name
    if not p.exists():
        return None
    rows = []
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            o, h, l, c, v = (float(r[k]) for k in ("open", "high", "low", "close", "volume"))
            rows.append({"t": r["time"], "o": o, "h": h, "l": l, "c": c, "v": v})
    return rows


class Intraday:
    def __init__(self, mk: str):
        sus = hb.OUT / f"{mk}_suspect.json"
        excl = {tuple(x) for x in json.loads(sus.read_text())} if sus.exists() else set()
        self.mk = mk
        self.h = h = hb.HTF(mk, excl)
        self.daily_trades = h.trades(*hb.DEFAULT)           # 日線版預設格（已剔除可疑）
        # 子集：有 5 分 K、通過核對
        self.subset, self.why = [], {"no_file": 0, "bad_file": 0, "few_bars": 0, "mismatch": 0}
        for t in self.daily_trades:
            rw = h.raw[t["s"]]
            p = t["p"]
            day = rw["dlist"][p]
            bars = load_bars(mk, h.m.tickers[t["s"]], day)
            if bars is None:
                self.why["no_file" if not (BARS / f"{mk}_{h.m.tickers[t['s']]}_{day.isoformat()}.csv").exists() else "bad_file"] += 1
                continue
            live = [b for b in bars if b["v"] > 0]
            if len(live) < MIN_BARS:
                self.why["few_bars"] += 1
                continue
            # 拆股／尺度核對：首根開市、末根收市 vs 日線 Open／Close（0.5%）；日內高低 vs 日線 High／Low（1%）
            o_d, c_d, h_d, l_d = rw["open"][p], rw["close"][p], rw["high"][p], rw["low"][p]
            o_i, c_i = live[0]["o"], live[-1]["c"]
            h_i, l_i = max(b["h"] for b in live), min(b["l"] for b in live)
            if not (o_d > 0 and c_d > 0) or abs(o_i / o_d - 1) > TOL_OC or abs(c_i / c_d - 1) > TOL_OC \
                    or abs(h_i / h_d - 1) > TOL_HL or abs(l_i / l_d - 1) > TOL_HL:
                self.why["mismatch"] += 1
                continue
            self.subset.append((t, live))
        print(f"[{mk}] 日線版 {len(self.daily_trades)} 筆 → 有 5 分 K 且通過核對 {len(self.subset)} 筆；剔除 {self.why}", file=sys.stderr)

    # ---------- 盤中入場 ----------
    def intraday_entry(self, t: dict, live: list[dict], or_bars: int) -> dict:
        """回傳 {status, fill, lod, bar_idx}。status: no_break／chase／filled。"""
        P, adr = t["info"]["pivot"], t["info"]["adr"]
        o_day = live[0]["o"]
        if o_day > P * (1 + hb.CHASE):
            return {"status": "chase"}
        orh = max(b["h"] for b in live[:or_bars])
        L = max(orh, P)
        lod = min(b["l"] for b in live[:or_bars])
        for i in range(or_bars, len(live)):
            b = live[i]
            lod = min(lod, b["l"])          # 成交前（含成交那根）的最低
            if b["h"] > L:
                fill = b["o"] if b["o"] > L else L
                return {"status": "filled", "fill": fill, "lod": lod, "bar_idx": i}
        return {"status": "no_break"}

    def simulate_rest(self, s: int, p: int, fill: float, stop: float) -> list:
        """入場日之後各日，與 htf_backtest.HTF.simulate 的 k > p 部分完全相同。"""
        rw = self.h.raw[s]
        low, close, opn, adj, ma = (rw[k] for k in ("low", "close", "open", "adj", "ma10"))
        n = len(close)
        legs, units, exit_next_open = [], 1.0, False
        last = min(n, p + hb.MAX_HOLD + 1)
        for k in range(p + 1, last):
            o = opn[k] if opn[k] == opn[k] and opn[k] > 0 else close[k]
            if exit_next_open:
                legs.append((k, o, False, units))
                return legs
            if low[k] <= stop:
                legs.append((k, min(o, stop), False, units))
                return legs
            if k == p + hb.PARTIAL_DAY:
                legs.append((k, close[k], True, 0.5))
                units = 0.5
                stop = max(stop, fill)
            if k >= p + hb.PARTIAL_DAY and ma[k] == ma[k] and adj[k] < ma[k]:
                exit_next_open = True
        k = last - 1
        legs.append((k, close[k], True, units))
        return legs

    def intraday_trades(self, or_bars: int = 1, adr_rule: str = "skip", stop_mode: str = "lod") -> tuple[list[dict], dict]:
        """adr_rule: skip（Q 鐵律：停損距離 > ADR 放棄）／adr（不放棄、停損改 ADR）。stop_mode: lod／daily（盤中成交 + 日線版停損）。"""
        h = self.h
        out, busy = [], {}
        tally = {"no_break": 0, "chase": 0, "adr_skip": 0, "stopped_day0": 0, "filled": 0, "busy": 0}
        for t, live in sorted(self.subset, key=lambda x: (x[0]["a"], x[0]["s"])):
            s, p = t["s"], t["p"]
            if p <= busy.get(s, -1):
                tally["busy"] += 1
                continue
            e = self.intraday_entry(t, live, or_bars)
            if e["status"] != "filled":
                tally[e["status"]] += 1
                continue
            fill, lod, adr = e["fill"], e["lod"], t["info"]["adr"]
            if stop_mode == "daily":
                stop = fill * (1 - adr)
            else:
                dist = (fill - lod) / fill
                if dist > adr:
                    if adr_rule == "skip":
                        tally["adr_skip"] += 1
                        continue
                    stop = fill * (1 - adr)
                else:
                    stop = lod
            # 成交之後同一天：任何一根最低 ≤ 停損 → 當日出場（價 = 停損）
            rest = live[e["bar_idx"] + 1:]
            if any(b["l"] <= stop for b in rest):
                legs = [(p, stop, False, 1.0)]
                tally["stopped_day0"] += 1
            else:
                day_low = min(b["l"] for b in live)
                legs = self.simulate_rest(s, p, fill, max(stop, day_low))
                tally["filled"] += 1
            busy[s] = legs[-1][0]
            tr = h._trade(s, p, fill, legs, t["info"])
            tr["intraday"] = {"fill": fill, "lod": lod, "bar": e["bar_idx"], "daily_fill": t["fill"]}
            out.append(tr)
        return out, tally

    def daily_on_subset(self) -> list[dict]:
        return [t for t, _ in self.subset]

    @staticmethod
    def day0_stats(trades: list[dict]) -> dict:
        n = len(trades)
        d0 = [t for t in trades if len(t["legs"]) == 1 and t["legs"][0]["b"] == t["a"]]
        net = lambda t: sum(lg["u"] * lg["out_adj"] for lg in t["legs"]) / t["in_adj"] - 1
        return {"n": n, "day0_stop": len(d0), "day0_stop_pct": len(d0) / n if n else math.nan,
                "day0_stop_avg_net": float(np.mean([net(t) for t in d0])) if d0 else math.nan,
                "rest_avg_net": float(np.mean([net(t) for t in trades if t not in d0])) if n - len(d0) else math.nan}

    def summarize(self, trades: list[dict]) -> dict:
        e = self.h.evaluate(trades) if trades else {}
        keys = ("trades", "alpha_t", "t_ew", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "mdd", "win", "rrr", "expectancy",
                "profit_factor", "avg_hold", "top10_share", "partial_reached")
        out = {k: e.get(k) for k in keys}
        out.update(self.day0_stats(trades))
        return out


def run(mk: str, inspect: int) -> None:
    it = Intraday(mk)
    if inspect:
        for t, live in it.subset[:inspect]:
            e = it.intraday_entry(t, live, 1)
            print(json.dumps({"ticker": it.h.m.tickers[t["s"]], "entry": it.h.raw[t["s"]]["dlist"][t["p"]].isoformat(),
                              "pivot": t["info"]["pivot"], "day_open": live[0]["o"], "or_high": live[0]["h"], "adr": t["info"]["adr"],
                              "daily_fill": t["fill"], "daily_legs": [(it.h.raw[t["s"]]["dlist"][lg["k"]].isoformat(), lg["u"], lg["at_close"]) for lg in t["legs"]],
                              "intraday": e, "bars": len(live)}, ensure_ascii=False, default=float))
        return
    res = {"market": mk, "n_daily_all": len(it.daily_trades), "n_subset": len(it.subset), "excluded": it.why}
    res["daily_subset"] = it.summarize(it.daily_on_subset())
    variants = {"intraday_OR1_adrskip": (1, "skip", "lod"), "intraday_OR3_adrskip": (3, "skip", "lod"), "intraday_OR12_adrskip": (12, "skip", "lod"),
                "intraday_OR1_adrstop": (1, "adr", "lod"), "intraday_OR1_dailystop": (1, "skip", "daily")}
    res["variants"] = {}
    for name, (orb, rule, mode) in variants.items():
        trs, tally = it.intraday_trades(orb, rule, mode)
        res["variants"][name] = {"tally": tally, **it.summarize(trs)}
    # 日線版入場日停損且開市 < 樞紐那批，在盤中預設格的歸宿
    trs, _ = it.intraday_trades(1, "skip", "lod")
    by_key = {(t["s"], t["p"]): t for t in trs}
    fate = {"no_entry_or_skip": 0, "stopped_day0": 0, "survived": 0}
    sick = [t for t, _ in it.subset if len(t["legs"]) == 1 and t["legs"][0]["b"] == t["a"] and t["info"]["open"] < t["info"]["pivot"]]
    for t in sick:
        u = by_key.get((t["s"], t["p"]))
        if u is None:
            fate["no_entry_or_skip"] += 1
        elif len(u["legs"]) == 1 and u["legs"][0]["b"] == u["a"]:
            fate["stopped_day0"] += 1
        else:
            fate["survived"] += 1
    res["sick_daily_fate"] = {"n": len(sick), **fate}
    if mk == "hk":   # 第三部分那格（看過結果後選的；只報告）
        sub_ids = {(t["s"], t["p"]) for t in it.h.trades(1.0, 0.20, adr_min=0.06)}
        it_sub = Intraday.__new__(Intraday)
        it_sub.__dict__.update(it.__dict__)
        it_sub.subset = [(t, l) for t, l in it.subset if (t["s"], t["p"]) in sub_ids]
        trs_g, tally_g = it_sub.intraday_trades(1, "skip", "lod")
        res["hk_G100_ADR6"] = {"daily_subset": it_sub.summarize(it_sub.daily_on_subset()), "intraday": {"tally": tally_g, **it_sub.summarize(trs_g)}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")

    def line(name, d):
        return (f"  {name:26s} 筆數 {d['trades'] or 0:5d}  alpha t {d['alpha_t'] if d['alpha_t'] is not None else float('nan'):6.2f}  "
                f"年化 {d['cagr'] if d['cagr'] is not None else float('nan'):+.1%}  MDD {d['mdd'] if d['mdd'] is not None else float('nan'):.0%}  "
                f"勝率 {d['win'] if d['win'] is not None else float('nan'):.0%}  期望值 {d['expectancy'] if d['expectancy'] is not None else float('nan'):+.2%}  "
                f"入場日停損 {d['day0_stop_pct']:.0%}（{d['day0_stop_avg_net']:+.1%}）  其餘 {d['rest_avg_net']:+.1%}")
    print(f"[{mk}] 子集 {res['n_subset']}／日線版 {res['n_daily_all']}；剔除 {res['excluded']}", file=sys.stderr)
    print(line("daily_subset", res["daily_subset"]), file=sys.stderr)
    for k, v in res["variants"].items():
        print(line(k, v) + f"  {v['tally']}", file=sys.stderr)
    print(f"  日線版病灶交易 {res['sick_daily_fate']}", file=sys.stderr)
    if "hk_G100_ADR6" in res:
        print(line("G100_ADR6 daily", res["hk_G100_ADR6"]["daily_subset"]), file=sys.stderr)
        print(line("G100_ADR6 intraday", res["hk_G100_ADR6"]["intraday"]), file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", required=True, choices=MARKETS)
    a.add_argument("--inspect", type=int, default=0)
    args = a.parse_args()
    run(args.market, args.inspect)


if __name__ == "__main__":
    main()
