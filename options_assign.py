#!/usr/bin/env python3
"""short put 接貨 vs 直接買 vs 限價買（預先登記：OPTIONS_EQUITY_BACKTEST.md 第六部分；只跑一次）。

    python3 options_assign.py --selftest
    python3 options_assign.py --market us       # → research/options_equity/assign_us.json
    python3 options_assign.py --market hk

- 事件：newhigh_backtest.MarketData 的 streak_window(W) == K（預設 12 個月新高第一天）；隨機對照 = 同日在 200 日線上的非事件成分股
- A 直接買 t+1 開市；B 限價 K = 0.97 × t+1 收市、21 日內最低價觸及即成交（價 = min(開市, K)），否則 E 收市買；
  C 賣 1 個月 put（同 K）到期收市 < K 接貨、否則 E 收市買；C2 最多滾 3 期；全部持有到 t+1 後第 126 日收市
- put IV = ρ × RV63，偏斜 = 指數斜率一半（同第四部分）；現金與權利金按 ^IRX 計息；股票按 AdjClose 總回報
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
import newhigh_backtest as nb  # noqa: E402
import options_equity as oe  # noqa: E402

OUT = ROOT / "research" / "options_equity"
CFG = {
    "us": dict(rho=0.95, cv=0.5, c=0.0005, split=date(2013, 1, 1)),
    "hk": dict(rho=0.93, cv=1.0, c=0.0015, split=date(2018, 7, 1)),
}
RHOS = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
EVENTS = {"W12K1": (12, 1), "W6K1": (6, 1), "W12K3": (12, 3)}
DEFAULT_EV = "W12K1"
KR, TE, TH, NROLL = 0.97, 21, 126, 3


def put_price(S, K, T, r, q, rv, rho, base, cv):
    """單一 put：回傳 (價格 − 成本)。偏斜 = 指數斜率一半。"""
    F = S * math.exp((r - q) * T)
    atm = rho * rv
    m = math.log(K / F) / math.sqrt(T)
    s = (base["s_put"] if m < 0 else base["s_call"]) * 0.5
    v = max(atm + s * m, 0.05)
    px, vega = oe.bs(S, K, T, r, q, v, "p")
    return px - vega * cv


class Prices:
    """原始（按拆股調整）開、低、收與 AdjClose，對齊 MarketData 日曆。"""

    def __init__(self, mkd: nb.MarketData):
        D = len(mkd.cal)
        di = {d: j for j, d in enumerate(mkd.cal)}
        S = len(mkd.tickers)
        self.o, self.lo, self.c, self.a = (np.full((S, D), np.nan) for _ in range(4))
        self.divs = []
        for s, t in enumerate(mkd.tickers):
            for r in md.load_ohlcv(t):
                j = di.get(r["Date"])
                if j is not None and r["Close"] > 0:
                    self.o[s, j] = r["Open"] if r["Open"] > 0 else np.nan
                    self.lo[s, j] = r["Low"] if r["Low"] > 0 else np.nan
                    self.c[s, j], self.a[s, j] = r["Close"], r["AdjClose"]
            self.divs.append(md.load_actions(t)[0])
        self.cal = mkd.cal
        # 最後一個有效價的索引（含當天）
        idx = np.where(~np.isnan(self.c), np.arange(D)[None, :], -1)
        self.lastv = np.maximum.accumulate(idx, axis=1)
        irx = oe.read_series("IRX")
        keys = sorted(irx)
        r = np.array([(oe.asof(irx, keys, d) or 0.0) / 100 for d in mkd.cal])
        self.r = r
        self.cumr = np.r_[0.0, np.cumsum(r[1:] / 252)]           # 由第 0 日起的累積對數利息

    def g(self, a: int, b: int) -> float:
        return math.exp(self.cumr[b] - self.cumr[a])

    def lv(self, s: int, j: int) -> int:
        return int(self.lastv[s, j])

    def rv63(self, s: int, j: int) -> float:
        a = self.a[s, max(0, j - 63): j + 1]
        a = a[~np.isnan(a)]
        if len(a) < 61:
            return float("nan")
        return float(np.diff(np.log(a)).std(ddof=1) * math.sqrt(252))

    def q(self, s: int, j: int) -> float:
        d = self.cal[j]
        tot = sum(x for e, x in self.divs[s] if 0 < (d - e).days <= 365)
        return tot / self.c[s, j] if self.c[s, j] > 0 else 0.0

    def hold(self, s: int, jb: int, jh: int) -> float:
        """在 jb 收市持有的 1 元股票，到 jh 收市的價值（總回報；下市按最後價）。"""
        a0, a1 = self.a[s, self.lv(s, jb)], self.a[s, self.lv(s, jh)]
        return a1 / a0


def one_event(P: Prices, s: int, t: int, base: dict, cfg: dict, rhos: list[float]) -> dict | None:
    D = len(P.cal)
    j1 = t + 1
    E, H = j1 + TE, j1 + TH
    if H >= D or np.isnan(P.o[s, j1]) or np.isnan(P.c[s, j1]):
        return None
    rv = P.rv63(s, j1)
    if not rv == rv or rv <= 0:
        return None
    c = cfg["c"]
    S1 = P.c[s, j1]
    K = KR * S1
    # A：t+1 開市
    A = (1 - c) * (S1 / P.o[s, j1]) * P.hold(s, j1, H)
    # B：限價
    fill = None
    for j in range(j1 + 1, E + 1):
        lo = P.lo[s, j]
        if lo == lo and lo <= K:
            op = P.o[s, j]
            fill = (j, min(op, K) if op == op else K)
            break
    if fill:
        j, px = fill
        B = P.g(j1, j) * (1 - c) * (P.c[s, j] / px) * P.hold(s, j, H)
    else:
        B = P.g(j1, E) * (1 - c) * P.hold(s, E, H)
    cE = P.c[s, P.lv(s, E)]
    out = dict(A=A, B=B, filled_B=fill is not None, C={}, C2={})
    r, q, T = P.r[j1], P.q(s, j1), TE / 252
    for rho in rhos:
        prem = put_price(S1, K, T, r, q, rv, rho, base, cfg["cv"]) / K     # 每 1 元擔保
        cash = (1 + prem) * P.g(j1, E)
        if cE < K:
            Cv = (1 - c) * (cE / K) * P.hold(s, E, H) + (cash - 1) * P.g(E, H)
        else:
            Cv = cash * (1 - c) * P.hold(s, E, H)
        out["C"][rho] = Cv
        # C2：最多滾 3 期
        w, j0, done = 1.0, j1, None
        for k in range(NROLL):
            e = j0 + TE
            S0 = P.c[s, P.lv(s, j0)]
            Kk = KR * S0
            rv0 = P.rv63(s, j0) if k else rv
            if not rv0 == rv0:
                rv0 = rv
            pr = put_price(S0, Kk, T, P.r[j0], P.q(s, j0), rv0, rho, base, cfg["cv"]) / Kk
            cash = w * (1 + pr) * P.g(j0, e)
            ce = P.c[s, P.lv(s, e)]
            if ce < Kk:
                done = (1 - c) * w * (ce / Kk) * P.hold(s, e, H) + (cash - w) * P.g(e, H)
                break
            w, j0 = cash, e
        if done is None:
            done = w * (1 - c) * P.hold(s, j0, H)
        out["C2"][rho] = done
        if rho == cfg["rho"]:
            out["assigned_C"] = bool(cE < K)
            out["assigned_C2_period"] = k + 1 if done is not None and ce < Kk else 0
            out["missed_rally"] = bool(cE >= K * 1.10)
            if cE < K:
                seg = P.c[s, E:min(E + 22, D)]
                seg = seg[~np.isnan(seg)]
                out["drop_after"] = bool(len(seg) and seg.min() < 0.9 * K)
    # 63 日結算（只報 A 與中心 ρ 的 C）
    H63 = j1 + 63
    out["A63"] = (1 - c) * (S1 / P.o[s, j1]) * P.hold(s, j1, H63)
    prem = put_price(S1, K, T, r, q, rv, cfg["rho"], base, cfg["cv"]) / K
    cash = (1 + prem) * P.g(j1, E)
    out["C63"] = ((1 - c) * (cE / K) * P.hold(s, E, H63) + (cash - 1) * P.g(E, H63)) if cE < K \
        else cash * (1 - c) * P.hold(s, E, H63)
    out["date"] = P.cal[t]
    return out


def clustered(diffs: list[tuple[date, float]]) -> dict:
    """按訊號月份平均後，對月份序列算 t。"""
    by = defaultdict(list)
    for d, x in diffs:
        by[(d.year, d.month)].append(x)
    m = np.array([np.mean(v) for v in by.values()])
    n = len(m)
    t = float(m.mean() / (m.std(ddof=1) / math.sqrt(n))) if n > 2 and m.std(ddof=1) > 0 else float("nan")
    return dict(mean_event=float(np.mean([x for _, x in diffs])), mean_month=float(m.mean()), t=t, months=n,
                events=len(diffs))


def analyse(rows: list[dict], cfg: dict) -> dict:
    rc = cfg["rho"]
    pair = lambda f: [(r["date"], f(r)) for r in rows]  # noqa: E731
    res = {"n": len(rows)}
    res["C_minus_A"] = {str(rho): clustered(pair(lambda r, x=rho: r["C"][x] - r["A"])) for rho in RHOS + [rc]}
    res["C_minus_B"] = {str(rho): clustered(pair(lambda r, x=rho: r["C"][x] - r["B"])) for rho in RHOS + [rc]}
    res["C2_minus_A"] = {str(rho): clustered(pair(lambda r, x=rho: r["C2"][x] - r["A"])) for rho in RHOS + [rc]}
    res["B_minus_A"] = clustered(pair(lambda r: r["B"] - r["A"]))
    res["C_minus_A_63d"] = clustered(pair(lambda r: r["C63"] - r["A63"]))
    sp = cfg["split"]
    res["segments"] = {
        "pre": clustered([(r["date"], r["C"][rc] - r["A"]) for r in rows if r["date"] < sp]),
        "post": clustered([(r["date"], r["C"][rc] - r["A"]) for r in rows if r["date"] >= sp]),
    }
    res["rates"] = dict(
        B_fill=float(np.mean([r["filled_B"] for r in rows])),
        C_assigned=float(np.mean([r["assigned_C"] for r in rows])),
        C2_assigned_by_period={k: float(np.mean([0 < r["assigned_C2_period"] <= k for r in rows])) for k in (1, 2, 3)},
        missed_rally=float(np.mean([r["missed_rally"] for r in rows])),
        drop_after_assign=float(np.mean([r["drop_after"] for r in rows if "drop_after" in r])) if any("drop_after" in r for r in rows) else None,
        mean_A=float(np.mean([r["A"] for r in rows])), mean_B=float(np.mean([r["B"] for r in rows])),
        mean_C=float(np.mean([r["C"][rc] for r in rows])), mean_C2=float(np.mean([r["C2"][rc] for r in rows])),
    )
    years = defaultdict(list)
    for r in rows:
        years[r["date"].year].append(r["C"][rc] - r["A"])
    res["by_year"] = {y: [float(np.mean(v)), len(v)] for y, v in sorted(years.items())}
    crisis = {}
    for lab, a, b in (("2008-09→2009-03", date(2008, 9, 1), date(2009, 3, 31)),
                      ("2020-02→2020-04", date(2020, 2, 1), date(2020, 4, 30)), ("2022", date(2022, 1, 1), date(2022, 12, 31))):
        v = [r["C"][rc] - r["A"] for r in rows if a <= r["date"] <= b]
        if v:
            crisis[lab] = [float(np.mean(v)), len(v)]
    res["crisis"] = crisis
    return res


def verdict(res: dict, cfg: dict) -> str:
    rc = str(cfg["rho"])
    lo = str(round(cfg["rho"] - 0.1, 2))
    ca, cb = res["C_minus_A"][rc], res["C_minus_B"][rc]
    lo_ca = res["C_minus_A"].get(lo) or clustered_placeholder()
    ok = (ca["mean_month"] > 0 and ca["t"] >= 2.0 and lo_ca["mean_month"] > 0 and cb["mean_month"] > 0 and cb["t"] >= 2.0
          and res["segments"]["pre"]["mean_month"] > 0 and res["segments"]["post"]["mean_month"] > 0)
    if ok:
        return "🔍"
    return "☠️" if ca["mean_month"] < 0 else "不確定"


def clustered_placeholder():
    return dict(mean_month=float("nan"))


def run_market(market: str) -> dict:
    cfg = CFG[market]
    base = oe.MARKETS[market]
    mkd = nb.MarketData(market)
    P = Prices(mkd)
    rhos = sorted(set(RHOS + [cfg["rho"], round(cfg["rho"] - 0.1, 2)]))
    out = {"market": market, "cfg": {k: str(v) for k, v in cfg.items()}}
    for name, (w, k) in EVENTS.items():
        ev = mkd.events("H4", (w, k))
        rows = []
        for s, t in zip(*np.nonzero(ev)):
            r = one_event(P, int(s), int(t), base, cfg, rhos)
            if r:
                rows.append(r)
        res = analyse(rows, cfg)
        if name == DEFAULT_EV:
            lo = str(round(cfg["rho"] - 0.1, 2))
            res["C_minus_A"][lo] = clustered([(r["date"], r["C"][round(cfg["rho"] - 0.1, 2)] - r["A"]) for r in rows])
            res["verdict"] = verdict(res, cfg)
            # 隨機對照：同一天、在 200 日線上的非事件成分股
            rng = np.random.default_rng(0)
            rrows = []
            for s, t in zip(*np.nonzero(ev)):
                pool = np.nonzero(mkd.member[:, t] & mkd.above[:, t] & ~ev[:, t])[0]
                if len(pool) == 0:
                    continue
                rr = one_event(P, int(pool[rng.integers(len(pool))]), int(t), base, cfg, [cfg["rho"]])
                if rr:
                    rrows.append(rr)
            rres = {"n": len(rrows),
                    "C_minus_A": clustered([(r["date"], r["C"][cfg["rho"]] - r["A"]) for r in rrows]),
                    "C_minus_B": clustered([(r["date"], r["C"][cfg["rho"]] - r["B"]) for r in rrows]),
                    "B_minus_A": clustered([(r["date"], r["B"] - r["A"]) for r in rrows]),
                    "C_assigned": float(np.mean([r["assigned_C"] for r in rrows])),
                    "mean_A": float(np.mean([r["A"] for r in rrows]))}
            res["random_control"] = rres
        out[name] = res
    return out


def selftest() -> None:
    # 平價：put 價 − 成本 < 無成本價
    base = oe.MARKETS["us"]
    p0 = put_price(100, 97, 21 / 252, 0.04, 0.01, 0.3, 1.0, base, 0.0)
    p1 = put_price(100, 97, 21 / 252, 0.04, 0.01, 0.3, 1.0, base, 0.5)
    assert 0 < p1 < p0 < 3, (p0, p1)
    # 平值附近 1 個月 30% 波動的 3% 價外 put 約 2% 左右（量級）
    assert 1.0 < p0 < 2.5, p0
    print(f"selftest ok：3% 價外 1 個月 put（σ 30%）{p0:.3f}，扣 0.5 波動點成本後 {p1:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=list(CFG))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.market:
        selftest()
        return
    res = run_market(a.market)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"assign_{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    cfg = CFG[a.market]
    rc = str(cfg["rho"])
    for name in EVENTS:
        r = res[name]
        ca, cb, c2 = r["C_minus_A"][rc], r["C_minus_B"][rc], r["C2_minus_A"][rc]
        print(f"{a.market} {name}：{r['n']} 事件  C−A {ca['mean_month']*100:+.2f}%（t {ca['t']:+.2f}）  "
              f"C−B {cb['mean_month']*100:+.2f}%（t {cb['t']:+.2f}）  C2−A {c2['mean_month']*100:+.2f}%（t {c2['t']:+.2f}）  "
              f"B−A {r['B_minus_A']['mean_month']*100:+.2f}%（t {r['B_minus_A']['t']:+.2f}）"
              + (f"  判決 {r['verdict']}" if "verdict" in r else ""))
    d = res[DEFAULT_EV]
    print("  ρ 敏感度 C−A：" + "  ".join(f"{k}:{v['mean_month']*100:+.2f}%/t{v['t']:+.1f}" for k, v in sorted(d["C_minus_A"].items())))
    print("  分段：", {k: f"{v['mean_month']*100:+.2f}%/t{v['t']:+.2f}" for k, v in d["segments"].items()})
    print("  比率：", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d["rates"].items()})
    rc_ = d["random_control"]
    print(f"  隨機對照：{rc_['n']} 事件 C−A {rc_['C_minus_A']['mean_month']*100:+.2f}%（t {rc_['C_minus_A']['t']:+.2f}）"
          f" C−B {rc_['C_minus_B']['mean_month']*100:+.2f}%（t {rc_['C_minus_B']['t']:+.2f}）接貨率 {rc_['C_assigned']:.2f}")


if __name__ == "__main__":
    main()
