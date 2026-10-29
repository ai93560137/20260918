#!/usr/bin/env python3
"""大跌股賣期權——損益平衡分析（stock_research/BIGDROP_OPTIONS_PREREG.md；登記 commit 76009eb6 之後寫）。

    python3 bigdrop_options.py --market us     # → research/bigdrop_options/us.json
    python3 bigdrop_options.py --market hk

事件：PIT 成分股單日（AdjClose）報酬 ≤ 門檻、收市 ≥ 5、之前 ≥ 315 日數據、同股 21 日內只取第一次。
主統計量 RVfwd21 ÷ RV63pre；BS（σ = ρ × RV63pre）賣 21 日期權 → 每腿 ρ*（平均損益由負轉正）、ρ₂（t ≥ 2）。
數據層、日曆、^IRX、股息與 options_stock.Panel 共用。
"""
import argparse
import json
import math
import random
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import options_equity as oe  # noqa: E402
from options_stock import CFG, Panel, bs_vec  # noqa: E402

OUT = ROOT / "research" / "bigdrop_options"
RHOS = [round(0.80 + 0.05 * i, 2) for i in range(25)]        # 0.80 … 2.00
H = 21
SPLITS = {"us": [("2000–2012", date(2000, 1, 1), date(2012, 12, 31)), ("2013–2026", date(2013, 1, 1), date(2026, 12, 31))],
          "hk": [("2010–2017", date(2010, 1, 1), date(2017, 12, 31)), ("2018–2025", date(2018, 1, 1), date(2026, 12, 31))]}
CRISES = [("2008-09→2009-03", date(2008, 9, 1), date(2009, 3, 31)), ("2020-02→04", date(2020, 2, 1), date(2020, 4, 30)),
          ("2022", date(2022, 1, 1), date(2022, 12, 31))]
LEGS = {"put95": [("p", 0.95)], "call105": [("c", 1.05)], "strangle": [("p", 0.95), ("c", 1.05)],
        "put_atm": [("p", 1.00)], "call_atm": [("c", 1.00)], "put90": [("p", 0.90)], "call110": [("c", 1.10)]}


def rv(a: np.ndarray) -> float:
    a = a[~np.isnan(a)]
    if len(a) < 0.95 * 22 and len(a) < 20:
        return float("nan")
    lr = np.diff(np.log(a))
    return float(lr.std(ddof=1) * math.sqrt(252)) if len(lr) > 2 else float("nan")


class Study:
    def __init__(self, market: str):
        self.m = market
        self.P = Panel(market)
        self.cost = CFG[market]["cost"] / 100          # 每腿波動點
        self._mem: dict[date, set] = {}
        n_all = len(self.P.u.all_tickers(since=CFG[market]["start"]))
        self.coverage = dict(constituents_since_start=n_all, with_data=len(self.P.close))

    def members(self, d: date) -> set:
        if d not in self._mem:
            self._mem[d] = set(self.P.u.members_at(d))
        return self._mem[d]

    def events(self, thr: float, lag: int = 0, random_ctrl: bool = False, seed: int = 7) -> list[dict]:
        P, out, rng = self.P, [], random.Random(seed)
        n = len(P.dates)
        for t, adj in P.adj.items():
            c = P.close[t]
            r = adj[1:] / adj[:-1] - 1
            last = -10 ** 9
            idx = np.nonzero(r <= thr)[0] + 1 if not random_ctrl else None
            if random_ctrl:
                valid = np.nonzero(~np.isnan(r))[0] + 1
                idx = sorted(rng.sample(list(valid), min(len(valid), max(1, len(valid) // 250)))) if len(valid) else []
            for i in idx:
                if i - last < H:
                    continue
                d = P.dates[i]
                if not (CFG[self.m]["start"] <= d) or i + lag + H >= n:
                    continue
                if np.count_nonzero(~np.isnan(adj[:i])) < 315 or not (c[i] >= 5):
                    continue
                if t not in self.members(d):
                    continue
                e = i + lag
                S0 = c[e]
                if not (S0 > 0) or np.isnan(adj[e]):
                    continue
                rv63 = rv(adj[i - 64:i])                    # 不含大跌日
                rvf = rv(adj[e:e + H + 1])
                a1 = P.last_valid(adj, e + H)
                if not (rv63 > 0) or math.isnan(rvf) or math.isnan(a1):
                    continue
                ret = a1 / adj[e] - 1                         # 含息報酬
                S1 = S0 * (1 + ret)                          # 價格口徑近似（股息另以 q 入 BS）
                rate = (oe.asof(P.M.rf, P.M.rk, P.dates[e]) or 0) / 100
                out.append(dict(t=t, d=P.dates[e], drop=float(r[i - 1]), S0=float(S0), S1=float(S1), ret=float(ret),
                                rv63=rv63, rvf=rvf, r=rate, q=P.q_at(t, e)))
                last = i
        return out


def pnl(ev: list[dict], legs, rho: float, cost: float) -> np.ndarray:
    S0 = np.array([e["S0"] for e in ev]); S1 = np.array([e["S1"] for e in ev])
    rv63 = np.array([e["rv63"] for e in ev]); r = np.array([e["r"] for e in ev]); q = np.array([e["q"] for e in ev])
    T = H / 252
    tot = np.zeros(len(ev))
    for cp, k in legs:
        K = S0 * k
        px, vega = bs_vec(S0, K, T, r, q, rho * rv63, cp)
        prem = px - vega * cost * 100                 # vega 是每 1 波動點；成本 = cost(小數)×100 點
        pay = np.maximum(K - S1, 0) if cp == "p" else np.maximum(S1 - K, 0)
        tot += (prem - pay) / (K if (cp == "p" and len(legs) == 1) else S0)
    return tot


def tstat_by_month(ev, x) -> tuple[float, float]:
    by: dict[tuple, list] = {}
    for e, v in zip(ev, x):
        by.setdefault((e["d"].year, e["d"].month), []).append(v)
    m = np.array([np.mean(v) for v in by.values()])
    if len(m) < 3:
        return float(np.mean(x)), float("nan")
    return float(np.mean(x)), float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def breakeven(ev, legs, cost) -> dict:
    curve = []
    for rho in RHOS:
        mu, t = tstat_by_month(ev, pnl(ev, legs, rho, cost))
        curve.append((rho, mu, t))
    star = None
    for (r0, m0, _), (r1, m1, _) in zip(curve, curve[1:]):
        if m0 < 0 <= m1:
            star = r0 + (r1 - r0) * (-m0) / (m1 - m0)
            break
    if star is None and curve and curve[0][1] >= 0:
        star = RHOS[0]
    rho2 = next((rr for rr, _, t in curve if t == t and t >= 2), None)
    return dict(rho_star=star, rho2=rho2, curve=[dict(rho=a, mean_pct=b * 100, t=c) for a, b, c in curve])


def ratio_stats(ev) -> dict:
    if not ev:
        return {}
    x = np.array([e["rvf"] / e["rv63"] for e in ev])
    rms = math.sqrt(np.mean([e["rvf"] ** 2 for e in ev]) / np.mean([e["rv63"] ** 2 for e in ev]))
    return dict(n=len(ev), median=float(np.median(x)), p25=float(np.percentile(x, 25)), p75=float(np.percentile(x, 75)),
                rms_ratio=rms)


def ret_stats(ev) -> dict:
    if not ev:
        return {}
    r = np.array([e["ret"] for e in ev])
    return dict(n=len(ev), mean=float(r.mean()), median=float(np.median(r)), le_m10=float(np.mean(r <= -0.10)),
                ge_p10=float(np.mean(r >= 0.10)))


def run(market: str) -> dict:
    S = Study(market)
    res = dict(market=market, prereg_commit="76009eb6", coverage=S.coverage, grid={})
    base = None
    for thr in (-0.06, -0.08, -0.10, -0.15):
        for lag in (0, 1):
            ev = S.events(thr, lag)
            key = f"thr{int(thr * 100)}_lag{lag}"
            g = dict(n=len(ev), ratio=ratio_stats(ev), ret21=ret_stats(ev),
                     legs={k: breakeven(ev, v, S.cost) for k, v in LEGS.items()} if ev else {})
            if thr == -0.08 and lag == 0:
                base = ev
                g["by_year"] = {}
                for e in ev:
                    g["by_year"][e["d"].year] = g["by_year"].get(e["d"].year, 0) + 1
                g["splits"] = {}
                for name, a, b in SPLITS[market]:
                    sub = [e for e in ev if a <= e["d"] <= b]
                    g["splits"][name] = dict(n=len(sub), ratio=ratio_stats(sub), ret21=ret_stats(sub),
                                             legs={k: breakeven(sub, LEGS[k], S.cost) for k in ("put95", "call105", "strangle")}
                                             if len(sub) > 20 else {})
                g["crises"] = {name: dict(ratio=ratio_stats([e for e in ev if a <= e["d"] <= b]),
                                          ret21=ret_stats([e for e in ev if a <= e["d"] <= b])) for name, a, b in CRISES}
            res["grid"][key] = g
            print(f"{market} {key}: n={len(ev)} ratio={g['ratio'].get('median', float('nan')):.2f} "
                  + " ".join(f"{k} ρ*={v['rho_star']} ρ₂={v['rho2']}" for k, v in g["legs"].items() if k in ("put95", "call105", "strangle")))
    ctrl = S.events(-1.0, 0, random_ctrl=True)
    res["random_control"] = dict(ratio=ratio_stats(ctrl), legs={k: breakeven(ctrl, LEGS[k], S.cost)
                                                                for k in ("put95", "call105", "strangle")} if ctrl else {})
    res["earnings_tagging"] = "無歷史業績日數據 → 100% 標不到（登記第 5 部分第 5 項照報）"
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"], required=True)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    res = run(a.market)
    (OUT / f"{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"→ {OUT / (a.market + '.json')}")


if __name__ == "__main__":
    main()
