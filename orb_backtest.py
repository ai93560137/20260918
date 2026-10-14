#!/usr/bin/env python3
"""動能股開盤區間突破紀律（預先登記：stock_research/MOMENTUM_ORB_BACKTEST.md，寫程式前已 commit；探索性、無門檻）。

    python3 orb_backtest.py --market hk --inspect 8     # 只印前 N 筆機制（不印績效）
    python3 orb_backtest.py --market hk                 # 正式：動能清單 + 非動能對照，日線版 vs 盤中版（預設格＋變體）

股票日來自 analysis/orb/ibkr_request_<mk>[_nonmom].csv（seed 1，每個大市過濾成立日隨機 1 檔）。
盤中執行沿用 htf_intraday.Intraday（同一套 5 分 K 核對、OR 突破、LOD、第 3 日減半保本、均線收市出場），只換股票日來源：
- 日線版：t 開盤買、停損 ADR→當日低點（htf_backtest.HTF.simulate）
- 盤中版：第 1 根 5 分 K 高點被突破才成交（無樞紐）；預設停損 = 成交前 LOD、不用 ADR 鐵律放棄
"""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import htf_backtest as hb  # noqa: E402
import htf_intraday as hi  # noqa: E402

LISTS = ROOT / "analysis" / "orb"
OUT = ROOT / "research" / "orb"
MARKETS = ("hk", "us")


class ORB(hi.Intraday):
    def __init__(self, mk: str, h: "hb.HTF", which: str):
        """which: mom（動能清單）／nonmom（非動能對照）。h 共用，免得每份清單重算一次宇宙。"""
        self.mk, self.control, self.which, self.h = mk, True, which, h
        self.trail = "ma10"
        name = f"ibkr_request_{mk}{'' if which == 'mom' else '_nonmom'}.csv"
        rows = list(csv.DictReader(open(LISTS / name, newline="", encoding="utf-8")))
        tix = {t: s for s, t in enumerate(h.m.tickers)}
        self.n_request = len(rows)
        self.daily_trades, self.miss = [], {"no_ticker": 0, "no_date": 0, "no_adr": 0}
        busy = {}
        for r in sorted(rows, key=lambda r: (r["entry_date"], r["ticker"])):
            s = tix.get(r["ticker"])
            if s is None:
                self.miss["no_ticker"] += 1
                continue
            rw = h.raw[s]
            p = rw["dates"].get(date.fromisoformat(r["entry_date"]))
            if p is None or p < 1:
                self.miss["no_date"] += 1
                continue
            o, adr = rw["open"][p], rw["adr"][p - 1]
            if not (o == o and o > 0 and adr == adr and adr > 0):
                self.miss["no_adr"] += 1
                continue
            if p <= busy.get(s, -1):
                continue
            legs = h.simulate(s, p, float(o), float(adr), self.trail)
            busy[s] = legs[-1][0]
            t = h._trade(s, p, float(o), legs, {"pivot": None, "adr": float(adr), "open": float(o)})
            self.daily_trades.append(t)
        self._build_subset()

    def _build_subset(self) -> None:
        """與 htf_intraday.Intraday.__init__ 的子集核對完全相同（零量根不算、尺度核對、≥20 根）。"""
        h, mk = self.h, self.mk
        self.subset, self.why = [], {"no_file": 0, "bad_file": 0, "few_bars": 0, "mismatch": 0}
        for t in self.daily_trades:
            rw = h.raw[t["s"]]
            p = t["p"]
            day = rw["dlist"][p]
            tk = h.m.tickers[t["s"]]
            bars = hi.load_bars(mk, tk, day)
            if bars is None:
                self.why["no_file" if not (hi.BARS / f"{mk}_{tk}_{day.isoformat()}.csv").exists() else "bad_file"] += 1
                continue
            live = [b for b in bars if b["v"] > 0]
            if len(live) < hi.MIN_BARS:
                self.why["few_bars"] += 1
                continue
            o_d, c_d, h_d, l_d = rw["open"][p], rw["close"][p], rw["high"][p], rw["low"][p]
            o_i, c_i = live[0]["o"], live[-1]["c"]
            h_i, l_i = max(b["h"] for b in live), min(b["l"] for b in live)
            if not (o_d > 0 and c_d > 0) or abs(o_i / o_d - 1) > hi.TOL_OC or abs(c_i / c_d - 1) > hi.TOL_OC \
                    or abs(h_i / h_d - 1) > hi.TOL_HL or abs(l_i / l_d - 1) > hi.TOL_HL:
                self.why["mismatch"] += 1
                continue
            self.subset.append((t, live))
        print(f"[{mk}/{self.which}] 請求 {self.n_request} → 日線可模擬 {len(self.daily_trades)}（{self.miss}）"
              f" → 有 5 分 K 且通過核對 {len(self.subset)}；剔除 {self.why}", file=sys.stderr)

    def simulate_rest(self, s: int, p: int, fill: float, stop: float) -> list:
        """同 Intraday.simulate_rest，但均線可換（ma10／ma20 變體）。"""
        rw = self.h.raw[s]
        low, close, opn, adj, ma = (rw[k] for k in ("low", "close", "open", "adj", self.trail))
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

    def orb_trades(self, or_bars: int = 1, adr_rule: str = "none", trail: str = "ma10") -> tuple[list[dict], dict]:
        """adr_rule: none（預設：停損一律 LOD）／skip（Q 鐵律：LOD 距離 > ADR 放棄）。"""
        self.trail = trail
        if adr_rule == "skip":
            out = self.intraday_trades(or_bars, "skip", "lod")
            self.trail = "ma10"
            return out
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
            fill, stop = e["fill"], e["lod"]
            rest = live[e["bar_idx"] + 1:]
            if any(b["l"] <= stop for b in rest):
                legs = [(p, stop, False, 1.0)]
                tally["stopped_day0"] += 1
            else:
                legs = self.simulate_rest(s, p, fill, max(stop, min(b["l"] for b in live)))
                tally["filled"] += 1
            busy[s] = legs[-1][0]
            tr = h._trade(s, p, fill, legs, t["info"])
            tr["intraday"] = {"fill": fill, "lod": e["lod"], "bar": e["bar_idx"], "daily_fill": t["fill"]}
            out.append(tr)
        self.trail = "ma10"
        return out, tally


def run(mk: str, inspect: int) -> None:
    h = hb.HTF(mk, set())
    groups = {w: ORB(mk, h, w) for w in ("mom", "nonmom")}
    if inspect:
        g = groups["mom"]
        for t, live in g.subset[:inspect]:
            e = g.intraday_entry(t, live, 1)
            print(json.dumps({"ticker": h.m.tickers[t["s"]], "entry": h.raw[t["s"]]["dlist"][t["p"]].isoformat(),
                              "day_open": live[0]["o"], "or_high": live[0]["h"], "adr": t["info"]["adr"], "bars": len(live),
                              "daily_legs": [(h.raw[t["s"]]["dlist"][lg["k"]].isoformat(), lg["u"], lg["at_close"]) for lg in t["legs"]],
                              "intraday": e}, ensure_ascii=False, default=float))
        return
    variants = {"orb_OR1": (1, "none", "ma10"), "orb_OR3": (3, "none", "ma10"), "orb_OR12": (12, "none", "ma10"),
                "orb_OR1_ma20": (1, "none", "ma20"), "orb_OR1_adrskip": (1, "skip", "ma10")}
    res = {"market": mk}
    for w, g in groups.items():
        r = {"n_request": g.n_request, "n_daily": len(g.daily_trades), "miss": g.miss, "n_subset": len(g.subset), "excluded": g.why,
             "daily_all": g.summarize(g.daily_trades), "daily_subset": g.summarize(g.daily_on_subset()), "variants": {}}
        for name, (orb, rule, trail) in variants.items():
            trs, tally = g.orb_trades(orb, rule, trail)
            r["variants"][name] = {"tally": tally, **g.summarize(trs)}
        res[w] = r
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")

    def f(x, spec):
        return format(x, spec) if isinstance(x, (int, float)) and x == x else "—"

    def line(name, d):
        return (f"  {name:20s} 筆數 {d['trades'] or 0:5d}  alpha t {f(d['alpha_t'], '6.2f')}  vs等權 {f(d['t_ew'], '5.2f')}  "
                f"前/後 {f(d['t_pre'], '.2f')}/{f(d['t_post'], '.2f')}  年化 {f(d['cagr'], '+.1%')}（ETF {f(d['cagr_etf'], '+.1%')}）  "
                f"MDD {f(d['mdd'], '.0%')}  勝率 {f(d['win'], '.0%')}  期望值 {f(d['expectancy'], '+.2%')}  "
                f"入場日停損 {f(d['day0_stop_pct'], '.0%')}  前10筆佔 {f(d['top10_share'], '.0%')}")
    for w in ("mom", "nonmom"):
        r = res[w]
        print(f"[{mk}/{w}] 請求 {r['n_request']} → 日線 {r['n_daily']} → 子集 {r['n_subset']}", file=sys.stderr)
        print(line("daily_all", r["daily_all"]), file=sys.stderr)
        print(line("daily_subset", r["daily_subset"]), file=sys.stderr)
        for k, v in r["variants"].items():
            print(line(k, v) + f"  {v['tally']}", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", required=True, choices=MARKETS)
    a.add_argument("--inspect", type=int, default=0)
    args = a.parse_args()
    run(args.market, args.inspect)


if __name__ == "__main__":
    main()
