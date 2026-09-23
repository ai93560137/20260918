#!/usr/bin/env python3
"""股票期權 + 正股四策略回測（預先登記：OPTIONS_EQUITY_BACKTEST.md；兩地同一規格只測一次）。

    python3 options_equity.py --selftest           # 定價／平價／損益自檢
    python3 options_equity.py --market us          # 對照組檢驗 + 5 策略 × 鄰域 + k 敏感度 → research/options_equity/us.json
    python3 options_equity.py --market hk

- 正股：SPY／2800.HK 原始收市 + 股息 → 自算總回報（2800 股息只從 2013 起 → 港股樣本 2013-11 起，見登記第一部分之二）
- 期權：Black-Scholes，r = ^IRX，q = 過去 12 個月股息 ÷ 價格；平值 IV = k × 波動率指數，
  IV(K) = 平值 + s × ln(K/F)/√T（put 邊 s_put、call 邊 s_call），下限 3%
- 每月到期（美股第三個星期五、港股倒數第二個交易日），到期日收市結算並開下一期；成本 = 波動點 × vega（每腿開倉一次）
- 財富口徑：收到的權利金放現金收 r、付出的權利金從財富扣；CSP／輪動的現金部位 = 行使價
"""
import argparse
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402

DATA = ROOT / "data" / "options_equity"
OUT = ROOT / "research" / "options_equity"

MARKETS = {
    "us": dict(ticker="SPY", vol="VIX", k=0.77, s_put=-0.24, s_call=-0.15, cost=0.10, etf_cost=0.0001,
               start=date(1996, 1, 1), end=date(2026, 8, 31), split=date(2011, 1, 1), extra_split=None),
    "hk": dict(ticker="2800.HK", vol="VHSI", k=0.90, s_put=-0.08, s_call=-0.02, cost=0.20, etf_cost=0.0005,
               start=date(2013, 11, 1), end=date(2026, 8, 31), split=date(2020, 3, 1), extra_split=date(2022, 1, 1)),  # 第一部分之二
}
# 預設格放第一個；鄰域 3 格（含預設）
GRID = {
    "CC": [dict(kc=1.00), dict(kc=1.02), dict(kc=1.05)],
    "CSP": [dict(kp=1.00), dict(kp=0.98), dict(kp=0.95)],
    "PP": [dict(kp=0.95), dict(kp=0.97), dict(kp=0.90)],
    "COL": [dict(kp=0.95, kc=1.10), dict(kp=0.95, kc=1.05), dict(kp=0.95, kc=1.15)],
    "WHL": [dict(kp=0.97, kc=1.03), dict(kp=1.00, kc=1.00), dict(kp=0.95, kc=1.05)],
}
INCOME, PROTECT = ("CC", "CSP", "WHL"), ("PP", "COL")
# 對照組：模型規格（不扣成本）↔ CBOE 指數；數據起點（PUT 在 2001–2004 有三年缺口，從 2004-04 起）
CONTROLS = {
    "BXM": ("CC", dict(kc=1.00), date(2002, 4, 1)),
    "BXY": ("CC", dict(kc=1.02), date(1996, 1, 1)),
    "PUT": ("CSP", dict(kp=1.00), date(2004, 4, 1)),
    "PPUT": ("PP", dict(kp=0.95), date(1996, 1, 1)),
    "CLL": ("COL", dict(kp=0.95, kc=1.10), date(2008, 9, 1)),
}


# ───────────────────────── 定價 ─────────────────────────
def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S: float, K: float, T: float, r: float, q: float, v: float, cp: str) -> tuple[float, float]:
    """歐式期權價格與 vega（每 1 個波動點）。"""
    F = S * math.exp((r - q) * T)
    df = math.exp(-r * T)
    sd = v * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    call = df * (F * ncdf(d1) - K * ncdf(d2))
    px = call if cp == "c" else call - df * (F - K)
    vega = df * F * math.sqrt(T) * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / 100
    return px, vega


def iv_at(cfg: dict, idx: float, F: float, K: float, T: float, k: float) -> float:
    atm = k * idx / 100
    m = math.log(K / F) / math.sqrt(T)
    s = cfg["s_put"] if m < 0 else cfg["s_call"]
    return max(atm + s * m, 0.03)


# ───────────────────────── 數據 ─────────────────────────
def read_series(name: str) -> dict[date, float]:
    out = {}
    with open(DATA / f"{name}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[date.fromisoformat(r["Date"])] = float(r["Close"])
            except (ValueError, KeyError):
                pass
    return out


def asof(series: dict[date, float], keys: list[date], d: date) -> float | None:
    """d 當天或之前最近一筆（5 個曆日內）。"""
    import bisect
    i = bisect.bisect_right(keys, d) - 1
    if i < 0 or (d - keys[i]).days > 5:
        return None
    return series[keys[i]]


class Market:
    def __init__(self, market: str):
        self.m, self.cfg = market, MARKETS[market]
        ohlcv = md.load_ohlcv(self.cfg["ticker"])
        self.dates = [r["Date"] for r in ohlcv]
        self.close = np.array([r["Close"] for r in ohlcv], dtype=float)
        divs, _ = md.load_actions(self.cfg["ticker"])
        dv = {d: a for d, a in divs}
        extra = DATA / "DIV_2800.csv"
        if market == "hk" and extra.exists():
            with open(extra, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    d = date.fromisoformat(r["Date"])
                    if d not in dv and not any(abs((d - x).days) <= 7 for x in dv):
                        dv[d] = float(r["Dividend"])
        self.divs = sorted(dv.items())
        # 每日總回報指數（除淨日把股息再投資）
        import bisect
        div_on = {}
        for d, a in self.divs:
            j = bisect.bisect_left(self.dates, d)
            if 0 < j < len(self.dates):
                div_on[j] = div_on.get(j, 0.0) + a
        tr = np.ones(len(self.dates))
        for i in range(1, len(self.dates)):
            tr[i] = tr[i - 1] * (self.close[i] + div_on.get(i, 0.0)) / self.close[i - 1]
        self.tr = tr
        self.vol = read_series(self.cfg["vol"])
        self.vk = sorted(self.vol)
        self.rf = read_series("IRX")
        self.rk = sorted(self.rf)
        self.expiries = self._expiries()

    def _expiries(self) -> list[int]:
        """每月到期日在交易日曆中的索引。"""
        by_month: dict[tuple[int, int], list[int]] = {}
        for i, d in enumerate(self.dates):
            by_month.setdefault((d.year, d.month), []).append(i)
        out = []
        for (y, mth), idx in sorted(by_month.items()):
            if self.m == "us":
                # 第三個星期五；休市則取之前最近的交易日
                first = date(y, mth, 1)
                fri = 1 + (4 - first.weekday()) % 7 + 14
                tgt = date(y, mth, fri)
                cand = [i for i in idx if self.dates[i] <= tgt]
                if cand:
                    out.append(cand[-1])
            else:
                if len(idx) >= 2:
                    out.append(idx[-2])
        c = self.cfg
        return [i for i in out if c["start"] <= self.dates[i] <= c["end"]]

    def q_at(self, i: int) -> float:
        d = self.dates[i]
        tot = sum(a for x, a in self.divs if 0 < (d - x).days <= 365)
        return tot / self.close[i] if self.close[i] > 0 else 0.0

    def r_at(self, i: int) -> float:
        v = asof(self.rf, self.rk, self.dates[i])
        return (v or 0.0) / 100

    def v_at(self, i: int) -> float | None:
        return asof(self.vol, self.vk, self.dates[i])


# ───────────────────────── 策略 ─────────────────────────
def run(M: Market, strat: str, p: dict, k: float | None = None, with_cost: bool = True) -> dict:
    """回傳每期 (日期, 策略報酬, 基準報酬, 無風險報酬)。"""
    cfg = M.cfg
    k = cfg["k"] if k is None else k
    cv = cfg["cost"] if with_cost else 0.0
    ec = cfg["etf_cost"] if with_cost else 0.0
    ex = M.expiries
    out_d, rs, rb, rr = [], [], [], []
    state = "cash"          # 輪動用
    put3 = None             # 領口：(行使價, 到期索引)
    for a, b in zip(ex[:-1], ex[1:]):
        S0, S1 = M.close[a], M.close[b]
        idx = M.v_at(a)
        if idx is None:
            continue
        T = (b - a) / 252
        r, q = M.r_at(a), M.q_at(a)
        F = S0 * math.exp((r - q) * T)
        grow = math.exp(r * T)
        Ru = M.tr[b] / M.tr[a] - 1
        rf = grow - 1

        def opt(K, cp, TT=T):
            v = iv_at(cfg, idx, F if TT == T else S0 * math.exp((r - q) * TT), K, TT, k)
            px, vg = bs(S0, K, TT, r, q, v, cp)
            return px, vg * cv

        if strat == "CC":
            K = p["kc"] * F
            c, cost = opt(K, "c")
            R = Ru + ((c - cost) * grow - max(S1 - K, 0)) / S0
        elif strat == "CSP":
            K = p["kp"] * F
            pp, cost = opt(K, "p")
            R = rf + ((pp - cost) * grow - max(K - S1, 0)) / K
        elif strat == "PP":
            K = p["kp"] * F
            pp, cost = opt(K, "p")
            R = Ru + (max(K - S1, 0) - (pp + cost) * grow) / S0
        elif strat == "COL":
            Kc = p["kc"] * F
            c, cost_c = opt(Kc, "c")
            new_q = put3 is None or put3[1] <= a
            if new_q:
                # 每季（3、6、9、12 月到期日）買 3 個月 put；第一期若不在季月也先買，到下個季月到期
                j = ex.index(a)
                nxt = [e for e in ex[j + 1:] if M.dates[e].month in (3, 6, 9, 12)]
                end = nxt[0] if nxt else ex[-1]
                T3 = (end - a) / 252
                F3 = S0 * math.exp((r - q) * T3)
                Kp = p["kp"] * F3
                v = iv_at(cfg, idx, F3, Kp, T3, k)
                p0, vg = bs(S0, Kp, T3, r, q, v, "p")
                put3 = (Kp, end)
                pay0 = p0 + vg * cv
                val0 = p0
            else:
                Kp, end = put3
                T3 = (end - a) / 252
                F3 = S0 * math.exp((r - q) * T3)
                v = iv_at(cfg, idx, F3, Kp, T3, k)
                val0 = bs(S0, Kp, T3, r, q, v, "p")[0]
                pay0 = val0
            Kp, end = put3
            if end == b:
                val1 = max(Kp - S1, 0)
            else:
                idx1 = M.v_at(b) or idx
                T3b = (end - b) / 252
                r1, q1 = M.r_at(b), M.q_at(b)
                F3b = S1 * math.exp((r1 - q1) * T3b)
                v1 = iv_at(cfg, idx1, F3b, Kp, T3b, k)
                val1 = bs(S1, Kp, T3b, r1, q1, v1, "p")[0]
            # 財富 = 正股 + put 市值 − 空 call；新買 put 的成本（含價差）從財富扣
            W0 = S0 + val0
            W1 = S0 * (1 + Ru) + val1 - max(S1 - Kc, 0) + (c - cost_c) * grow - (pay0 - val0) * grow
            R = W1 / W0 - 1
        elif strat == "WHL":
            if state == "cash":
                K = p["kp"] * F
                pp, cost = opt(K, "p")
                R = rf + ((pp - cost) * grow - max(K - S1, 0)) / K
                if S1 < K:
                    state = "stock"
                    R -= ec * S1 / K
            else:
                K = p["kc"] * F
                c, cost = opt(K, "c")
                R = Ru + ((c - cost) * grow - max(S1 - K, 0)) / S0
                if S1 > K:
                    state = "cash"
                    R -= ec
        else:
            raise ValueError(strat)
        out_d.append(M.dates[b])
        rs.append(R)
        rb.append(Ru)
        rr.append(rf)
    return dict(dates=out_d, r=np.array(rs), b=np.array(rb), rf=np.array(rr))


# ───────────────────────── 統計 ─────────────────────────
def capm(r: np.ndarray, b: np.ndarray, rf: np.ndarray) -> dict:
    y, x = r - rf, b - rf
    n = len(y)
    if n < 12:
        return dict(n=n, alpha_t=float("nan"), alpha_ann=float("nan"), beta=float("nan"))
    X = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    s2 = resid @ resid / (n - 2)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return dict(n=n, alpha_t=float(coef[0] / se[0]), alpha_ann=float(coef[0] * 12), beta=float(coef[1]))


def perf(r: np.ndarray, rf: np.ndarray) -> dict:
    ex = r - rf
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    years = len(r) / 12
    return dict(cagr=float(eq[-1] ** (1 / years) - 1), vol=float(r.std(ddof=1) * math.sqrt(12)),
                sharpe=float(ex.mean() / ex.std(ddof=1) * math.sqrt(12)), mdd=float((eq / peak - 1).min()),
                worst_month=float(r.min()))


def summarize(res: dict, cfg: dict) -> dict:
    r, b, rf, d = res["r"], res["b"], res["rf"], res["dates"]
    out = dict(capm(r, b, rf), strat=perf(r, rf), bench=perf(b, rf),
               start=str(d[0]), end=str(d[-1]))
    down = b < 0
    out["down_capture"] = float(r[down].mean() / b[down].mean()) if down.any() else float("nan")
    out["up_capture"] = float(r[~down].mean() / b[~down].mean()) if (~down).any() else float("nan")
    halves = {}
    splits = [("split", cfg["split"])] + ([("split2", cfg["extra_split"])] if cfg["extra_split"] else [])
    for name, sp in splits:
        m = np.array([x < sp for x in d])
        for lab, mask in ((f"{name}_pre", m), (f"{name}_post", ~m)):
            if mask.sum() >= 12:
                h = capm(r[mask], b[mask], rf[mask])
                h["sharpe_diff"] = perf(r[mask], rf[mask])["sharpe"] - perf(b[mask], rf[mask])["sharpe"]
                halves[lab] = h
    out["halves"] = halves
    years = {}
    for y in sorted({x.year for x in d}):
        m = np.array([x.year == y for x in d])
        years[y] = [float(np.prod(1 + r[m]) - 1), float(np.prod(1 + b[m]) - 1)]
    out["years"] = years
    crisis = {}
    for lab, a0, a1 in (("2008-09→2009-03", date(2008, 9, 1), date(2009, 3, 31)),
                        ("2020-02→2020-04", date(2020, 2, 1), date(2020, 4, 30)),
                        ("2022", date(2022, 1, 1), date(2022, 12, 31))):
        m = np.array([a0 <= x <= a1 for x in d])
        if m.any():
            crisis[lab] = [float(np.prod(1 + r[m]) - 1), float(np.prod(1 + b[m]) - 1)]
    out["crisis"] = crisis
    return out


def verdict(strat: str, cells: list[dict]) -> str:
    d0 = cells[0]
    t = d0["alpha_t"]
    halves = [v for k, v in d0["halves"].items() if k.startswith("split_")]
    sh_ok = d0["strat"]["sharpe"] >= d0["bench"]["sharpe"]
    if strat in INCOME:
        nb = sum(c["alpha_t"] >= 1.5 for c in cells)
        ok = t >= 2.0 and nb >= 2 and all(h["alpha_t"] > 0 for h in halves) and sh_ok
        return "🔍" if ok else ("☠️" if t < 1.0 else "不確定")
    mdd_ok = d0["strat"]["mdd"] >= d0["bench"]["mdd"] * (2 / 3)
    half_ok = all(h["sharpe_diff"] >= -0.05 for h in halves)
    if mdd_ok and sh_ok and t > -1.0 and half_ok:
        return "🔍"
    if t <= -2.0 or d0["strat"]["sharpe"] < d0["bench"]["sharpe"] - 0.10:
        return "☠️"
    return "不確定"


def control(M: Market) -> dict:
    out = {}
    for sym, (strat, p, st) in CONTROLS.items():
        s = read_series(sym)
        keys = sorted(s)
        res = run(M, strat, p, with_cost=False)
        ex = [M.dates[i] for i in M.expiries]
        lv = {d: asof(s, keys, d) for d in ex}
        mr, cr = [], []
        for d0, d1, r in zip([None] + res["dates"][:-1], res["dates"], res["r"]):
            if d0 is None or d0 < st:
                continue
            a, b = lv.get(d0), lv.get(d1)
            if a and b:
                mr.append(r)
                cr.append(b / a - 1)
        mr, cr = np.array(mr), np.array(cr)
        yrs = len(mr) / 12
        am = np.prod(1 + mr) ** (1 / yrs) - 1
        ac = np.prod(1 + cr) ** (1 / yrs) - 1
        corr = float(np.corrcoef(mr, cr)[0, 1])
        out[sym] = dict(n=len(mr), start=str(st), corr=corr, model_cagr=float(am), cboe_cagr=float(ac),
                        diff=float(am - ac), passed=bool(corr >= 0.95 and abs(am - ac) <= 0.015))
    return out


def cboe_real(M: Market) -> dict:
    """對照組不過時：直接用 CBOE 真實指數（扣同一套成本）判預設格。成本近似 = 模型扣成本與不扣成本的月差。"""
    out = {}
    for sym, (strat, p, st) in CONTROLS.items():
        if sym == "BXY":
            continue
        s = read_series(sym)
        keys = sorted(s)
        gross = run(M, strat, p, with_cost=False)
        net = run(M, strat, p, with_cost=True)
        drag = gross["r"] - net["r"]
        rs, bs_, rfs, ds = [], [], [], []
        for i, (d0, d1) in enumerate(zip([None] + gross["dates"][:-1], gross["dates"])):
            if d0 is None or d0 < st:
                continue
            a, b = asof(s, keys, d0), asof(s, keys, d1)
            if a and b:
                rs.append(b / a - 1 - drag[i])
                bs_.append(gross["b"][i])
                rfs.append(gross["rf"][i])
                ds.append(d1)
        res = dict(dates=ds, r=np.array(rs), b=np.array(bs_), rf=np.array(rfs))
        out[sym] = summarize(res, M.cfg)
    return out


def selftest() -> None:
    S, K, T, r, q, v = 100, 100, 0.25, 0.03, 0.01, 0.2
    c, vg = bs(S, K, T, r, q, v, "c")
    p, _ = bs(S, K, T, r, q, v, "p")
    parity = c - p - (S * math.exp(-q * T) - K * math.exp(-r * T))
    assert abs(parity) < 1e-9, parity
    assert abs(c - 4.2219) < 0.001, c          # 手算：d1 = 0.1、d2 = 0 → 99.7503×N(0.1) − 99.2528×0.5
    up, _ = bs(S, K, T, r, q, v + 0.01, "c")
    assert abs((up - c) - vg) < 0.01, (up - c, vg)
    cfg = MARKETS["us"]
    assert iv_at(cfg, 20, 100, 95, 1 / 12, 0.77) > iv_at(cfg, 20, 100, 100, 1 / 12, 0.77) > iv_at(cfg, 20, 100, 105, 1 / 12, 0.77)
    print("selftest ok：BS 價格、平價、vega、偏斜方向")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=list(MARKETS))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.market:
        selftest()
        return
    M = Market(a.market)
    cfg = M.cfg
    print(f"{a.market}：{cfg['ticker']} {M.dates[M.expiries[0]]} → {M.dates[M.expiries[-1]]}，{len(M.expiries) - 1} 期；"
          f"股息 {len(M.divs)} 筆（首筆 {M.divs[0][0]}）")
    result = dict(market=a.market, cfg={k: str(v) for k, v in cfg.items()})
    if a.market == "us":
        ctl = control(M)
        result["control"] = ctl
        result["control_passed"] = all(v["passed"] for v in ctl.values())
        for sym, c in ctl.items():
            print(f"  對照 {sym:5s} {c['start']} 起 {c['n']:3d} 期：相關 {c['corr']:.3f}  模型 {c['model_cagr']*100:+.2f}%  "
                  f"CBOE {c['cboe_cagr']*100:+.2f}%  差 {c['diff']*100:+.2f}%  {'✅' if c['passed'] else '❌'}")
        if not result["control_passed"]:
            result["cboe_real"] = cboe_real(M)
    strat_out = {}
    for strat, cells in GRID.items():
        sums = [summarize(run(M, strat, p), cfg) for p in cells]
        v = verdict(strat, sums)
        sens = {}
        for dk in (-0.1, 0.1):
            s_ = summarize(run(M, strat, cells[0], k=cfg["k"] + dk), cfg)
            sens[f"k{cfg['k'] + dk:.2f}"] = dict(alpha_t=s_["alpha_t"], sharpe=s_["strat"]["sharpe"])
        strat_out[strat] = dict(cells=[dict(params=p, **s) for p, s in zip(cells, sums)], verdict=v, k_sens=sens)
        d0 = sums[0]
        print(f"  {strat:3s} {v:4s} 預設 {cells[0]}：alpha t {d0['alpha_t']:+.2f}（年化 {d0['alpha_ann']*100:+.2f}%）beta {d0['beta']:.2f}  "
              f"夏普 {d0['strat']['sharpe']:.2f} vs {d0['bench']['sharpe']:.2f}  回撤 {d0['strat']['mdd']*100:.1f}% vs {d0['bench']['mdd']*100:.1f}%  "
              f"年化 {d0['strat']['cagr']*100:+.2f}% vs {d0['bench']['cagr']*100:+.2f}%  鄰域 t "
              + "／".join(f"{s['alpha_t']:+.2f}" for s in sums)
              + "  分段 t " + "／".join(f"{k_}:{h['alpha_t']:+.2f}" for k_, h in d0["halves"].items()))
    result["strategies"] = strat_out
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.market}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"→ {OUT / (a.market + '.json')}")


if __name__ == "__main__":
    main()
