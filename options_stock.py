#!/usr/bin/env python3
"""個股備兌／輪動的損益平衡 ρ = IV ÷ RV（預先登記：OPTIONS_EQUITY_BACKTEST.md 第四部分；只跑一次）。

    python3 options_stock.py --selftest
    python3 options_stock.py --market us        # ρ 格點掃描 + 指數參考 → research/options_equity/stock_us.json
    python3 options_stock.py --market hk
    python3 options_stock.py --live us|hk       # 今天的真實個股 ρ（讀 data/options_equity/live/）

- 宇宙：S&P 500／恒指 point-in-time 成分股（防代碼重用），每月到期日當天仍在指數且有 ≥ 60 日有效報酬的股票
- 平值 IV = ρ × RV63（入場日前 63 個交易日 AdjClose 對數報酬年化），偏斜 = 第一部分同市場斜率的一半，下限 5%
- 每股每月獨立一期；組合 = 當月股票等權平均；基準 = 同一批股票同月等權持有
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
import options_equity as oe  # noqa: E402
from universe import Universe  # noqa: E402

OUT = ROOT / "research" / "options_equity"
LIVE = ROOT / "data" / "options_equity" / "live"
RHOS = [round(0.8 + 0.1 * i, 1) for i in range(13)]          # 0.8 … 2.0
CFG = {
    "us": dict(index="sp500", start=date(1996, 1, 1), end=date(2026, 8, 31), cost=0.5, stk_cost=0.0005,
               splits=[("2011", date(2011, 1, 1))]),
    "hk": dict(index="hsi", start=date(2010, 7, 1), end=date(2026, 8, 31), cost=1.0, stk_cost=0.0015,
               splits=[("2018-07", date(2018, 7, 1)), ("2022", date(2022, 1, 1))]),
}
STRATS = {"SCC": dict(kc=1.00), "SCC5": dict(kc=1.05), "SWHL": dict(kp=0.97, kc=1.03)}


# ───────────────────────── 向量化 BS ─────────────────────────
def ncdf(x: np.ndarray) -> np.ndarray:
    """標準常態 CDF（Abramowitz–Stegun 7.1.26，誤差 < 1.5e-7）。"""
    z = np.abs(x) / math.sqrt(2)
    t = 1 / (1 + 0.3275911 * z)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-z * z)
    return 0.5 * (1 + np.sign(x) * y)


def bs_vec(S, K, T, r, q, v, cp):
    F = S * np.exp((r - q) * T)
    df = np.exp(-r * T)
    sd = v * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    call = df * (F * ncdf(d1) - K * ncdf(d2))
    px = call if cp == "c" else call - df * (F - K)
    vega = df * F * np.sqrt(T) * np.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / 100
    return px, vega


def iv_vec(atm, F, K, T, s_put, s_call):
    m = np.log(K / F) / np.sqrt(T)
    s = np.where(m < 0, s_put, s_call) * 0.5          # 個股偏斜 = 指數的一半
    return np.maximum(atm + s * m, 0.05)


# ───────────────────────── 數據 ─────────────────────────
class Panel:
    def __init__(self, market: str):
        self.m, self.c = market, CFG[market]
        self.M = oe.Market(market)                    # 日曆、^IRX、指數參數
        self.base = oe.MARKETS[market]
        self.dates = self.M.dates
        self.di = {d: i for i, d in enumerate(self.dates)}
        self.expiries = self._expiries()
        self.u = Universe(self.c["index"])
        tickers = self.u.all_tickers(since=self.c["start"])
        n = len(self.dates)
        self.close, self.adj, self.divs, self.first = {}, {}, {}, {}
        for t in tickers:
            if not md.has_data(t):
                continue
            rows = md.load_ohlcv(t)
            if len(rows) < 80:
                continue
            c = np.full(n, np.nan)
            a = np.full(n, np.nan)
            for r in rows:
                i = self.di.get(r["Date"])
                if i is not None and r["Close"] > 0:
                    c[i], a[i] = r["Close"], r["AdjClose"]
            self.close[t], self.adj[t] = c, a
            self.divs[t] = md.load_actions(t)[0]
            self.first[t] = rows[0]["Date"]

    def _expiries(self) -> list[int]:
        by = {}
        for i, d in enumerate(self.dates):
            by.setdefault((d.year, d.month), []).append(i)
        out = []
        for (y, mth), idx in sorted(by.items()):
            if self.m == "us":
                first = date(y, mth, 1)
                tgt = date(y, mth, 1 + (4 - first.weekday()) % 7 + 14)
                cand = [i for i in idx if self.dates[i] <= tgt]
                if cand:
                    out.append(cand[-1])
            elif len(idx) >= 2:
                out.append(idx[-2])
        return [i for i in out if self.c["start"] <= self.dates[i] <= self.c["end"]]

    def last_valid(self, arr: np.ndarray, i: int) -> float:
        """i 當天或之前最後一個有效價（下市按最後收市）。"""
        seg = arr[max(0, i - 40): i + 1]
        ok = seg[~np.isnan(seg)]
        return float(ok[-1]) if len(ok) else float("nan")

    def rv63(self, t: str, i: int) -> float:
        a = self.adj[t][max(0, i - 63): i + 1]
        a = a[~np.isnan(a)]
        if len(a) < 61:
            return float("nan")
        lr = np.diff(np.log(a))
        return float(lr.std(ddof=1) * math.sqrt(252))

    def q_at(self, t: str, i: int) -> float:
        d = self.dates[i]
        tot = sum(x for e, x in self.divs[t] if 0 < (d - e).days <= 365)
        c = self.close[t][i]
        return tot / c if c > 0 else 0.0

    def month_cross_sections(self):
        """每期：(a, b, tickers, S0, S1, Ru, q, rv, r, T)。"""
        ex = self.expiries
        for a, b in zip(ex[:-1], ex[1:]):
            d = self.dates[a]
            elig = self.u.eligible_at(d, self.first)
            ts, S0, S1, Ru, Q, RV = [], [], [], [], [], []
            for t in sorted(elig):
                if t not in self.close:
                    continue
                c0 = self.close[t][a]
                a0 = self.adj[t][a]
                if not (c0 > 0) or not (a0 > 0):
                    continue
                rv = self.rv63(t, a)
                if not rv == rv or rv <= 0:
                    continue
                c1, a1 = self.last_valid(self.close[t], b), self.last_valid(self.adj[t], b)
                if not (c1 > 0 and a1 > 0):
                    continue
                ts.append(t)
                S0.append(c0)
                S1.append(c1)
                Ru.append(a1 / a0 - 1)
                Q.append(self.q_at(t, a))
                RV.append(rv)
            if len(ts) < 5:
                continue
            yield dict(a=a, b=b, t=ts, S0=np.array(S0), S1=np.array(S1), Ru=np.array(Ru), q=np.array(Q),
                       rv=np.array(RV), r=self.M.r_at(a), T=(b - a) / 252)


# ───────────────────────── 回測 ─────────────────────────
def scan(P: Panel) -> dict:
    base, c = P.base, P.c
    cv = c["cost"]
    months = list(P.month_cross_sections())
    out = {}
    for strat, p in STRATS.items():
        per_rho = {}
        for rho in RHOS:
            state: dict[str, str] = {}
            rs, bs_, rfs, ds, ns = [], [], [], [], []
            for x in months:
                S0, S1, Ru, q, rv, r, T = x["S0"], x["S1"], x["Ru"], x["q"], x["rv"], x["r"], x["T"]
                F = S0 * np.exp((r - q) * T)
                grow = math.exp(r * T)
                atm = rho * rv
                if strat in ("SCC", "SCC5"):
                    K = p["kc"] * F
                    v = iv_vec(atm, F, K, T, base["s_put"], base["s_call"])
                    px, vg = bs_vec(S0, K, T, r, q, v, "c")
                    R = Ru + ((px - vg * cv) * grow - np.maximum(S1 - K, 0)) / S0
                else:
                    stock = np.array([state.get(t) == "stock" for t in x["t"]])
                    Kp, Kc = p["kp"] * F, p["kc"] * F
                    vp = iv_vec(atm, F, Kp, T, base["s_put"], base["s_call"])
                    vc = iv_vec(atm, F, Kc, T, base["s_put"], base["s_call"])
                    pp, vgp = bs_vec(S0, Kp, T, r, q, vp, "p")
                    cc, vgc = bs_vec(S0, Kc, T, r, q, vc, "c")
                    Rcash = (grow - 1) + ((pp - vgp * cv) * grow - np.maximum(Kp - S1, 0)) / Kp
                    Rstk = Ru + ((cc - vgc * cv) * grow - np.maximum(S1 - Kc, 0)) / S0
                    assigned = (~stock) & (S1 < Kp)
                    called = stock & (S1 > Kc)
                    Rcash = Rcash - np.where(assigned, c["stk_cost"] * S1 / Kp, 0)
                    Rstk = Rstk - np.where(called, c["stk_cost"], 0)
                    R = np.where(stock, Rstk, Rcash)
                    new = {}
                    for j, t in enumerate(x["t"]):
                        if stock[j]:
                            new[t] = "cash" if called[j] else "stock"
                        else:
                            new[t] = "stock" if assigned[j] else "cash"
                    state = new                       # 剔出指數的股票不再追蹤
                rs.append(float(R.mean()))
                bs_.append(float(Ru.mean()))
                rfs.append(grow - 1)
                ds.append(P.dates[x["b"]])
                ns.append(len(x["t"]))
            r_, b_, rf_ = np.array(rs), np.array(bs_), np.array(rfs)
            cap = oe.capm(r_, b_, rf_)
            cell = dict(cap, strat=oe.perf(r_, rf_), bench=oe.perf(b_, rf_), n_stocks_median=int(np.median(ns)))
            seg = {}
            for lab, sp in c["splits"]:
                msk = np.array([d < sp for d in ds])
                for nm, mm in ((f"{lab}_pre", msk), (f"{lab}_post", ~msk)):
                    if mm.sum() >= 12:
                        seg[nm] = oe.capm(r_[mm], b_[mm], rf_[mm])["alpha_t"]
            cell["segments"] = seg
            per_rho[rho] = cell
        out[strat] = dict(per_rho=per_rho, **breakevens(per_rho))
    out["_meta"] = dict(months=len(months), start=str(P.dates[months[0]["b"]]), end=str(P.dates[months[-1]["b"]]),
                        stocks_per_month=[int(np.min([len(x["t"]) for x in months])), int(np.median([len(x["t"]) for x in months]))],
                        coverage={str(y): cov for y, cov in coverage(P).items()})
    return out


def breakevens(per_rho: dict) -> dict:
    rhos = sorted(per_rho)
    ts = [per_rho[r]["alpha_t"] for r in rhos]

    def cross(vals, level):
        for i in range(1, len(rhos)):
            if vals[i - 1] < level <= vals[i]:
                return rhos[i - 1] + (level - vals[i - 1]) / (vals[i] - vals[i - 1]) * (rhos[i] - rhos[i - 1])
        return rhos[0] if vals[0] >= level else None

    rho0 = cross(ts, 0.0)
    rho2 = next((r for r in rhos if per_rho[r]["alpha_t"] >= 2.0
                 and per_rho[r]["strat"]["sharpe"] >= per_rho[r]["bench"]["sharpe"]), None)
    segs = {}
    for k in per_rho[rhos[0]]["segments"]:
        segs[k] = cross([per_rho[r]["segments"].get(k, float("nan")) for r in rhos], 0.0)
    return dict(rho0=rho0, rho2=rho2, rho0_segments=segs)


def coverage(P: Panel) -> dict:
    """每年 7 月：名單總數 vs 有數據檔數（倖存者偏差洞）。"""
    out = {}
    for y in range(P.c["start"].year, P.c["end"].year + 1):
        d = date(y, 7, 1)
        mem = P.u.members_at(d)
        if mem:
            out[y] = [len(P.u.eligible_at(d, P.first)), P.u.listed_at(d)]
    return out


def index_reference(P: Panel) -> dict:
    """同一套 IV = ρ × RV63 套 SPY 平值備兌（不扣成本），令模型年化 = 真實 BXM 的 ρ；另報 VIX ÷ RV63 中位數。"""
    M = P.M
    bxm = oe.read_series("BXM")
    vix = oe.read_series("VIX")
    closes = M.close
    tr = M.tr
    ex = [i for i in M.expiries if M.dates[i] >= date(2002, 4, 1)]

    def rv_idx(i):
        a = tr[max(0, i - 63): i + 1]
        return float(np.diff(np.log(a)).std(ddof=1) * math.sqrt(252))

    ratios = [vix[M.dates[i]] / 100 / rv_idx(i) for i in ex if M.dates[i] in vix]
    real = []
    for a, b in zip(ex[:-1], ex[1:]):
        x0, x1 = oe.asof(bxm, sorted(bxm), M.dates[a]), oe.asof(bxm, sorted(bxm), M.dates[b])
        real.append(x1 / x0 - 1)
    yrs = len(real) / 12
    real_cagr = float(np.prod(1 + np.array(real)) ** (1 / yrs) - 1)
    fits = {}
    for rho in [round(0.8 + 0.05 * i, 2) for i in range(17)]:
        rs = []
        for a, b in zip(ex[:-1], ex[1:]):
            S0, S1 = closes[a], closes[b]
            T = (b - a) / 252
            r, q = M.r_at(a), M.q_at(a)
            F = S0 * math.exp((r - q) * T)
            px, _ = oe.bs(S0, F, T, r, q, max(rho * rv_idx(a), 0.05), "c")
            Ru = tr[b] / tr[a] - 1
            rs.append(Ru + (px * math.exp(r * T) - max(S1 - F, 0)) / S0)
        fits[rho] = float(np.prod(1 + np.array(rs)) ** (1 / yrs) - 1)
    ks = sorted(fits)
    match = None
    for i in range(1, len(ks)):
        lo, hi = fits[ks[i - 1]] - real_cagr, fits[ks[i]] - real_cagr
        if lo <= 0 <= hi:
            match = ks[i - 1] + (-lo) / (hi - lo) * (ks[i] - ks[i - 1])
    return dict(bxm_cagr=real_cagr, model_cagr_by_rho=fits, rho_matching_bxm=match,
                vix_over_rv63_median=float(np.median(ratios)), vix_over_rv63_iqr=[float(np.percentile(ratios, 25)),
                                                                                  float(np.percentile(ratios, 75))])


# ───────────────────────── 今天的真實 ρ ─────────────────────────
def implied_vol(F, K, T, df, px, cp):
    lo, hi = 1e-3, 5.0
    intrinsic = df * max((F - K) if cp == "c" else (K - F), 0)
    if px <= intrinsic + 1e-9:
        return None
    for _ in range(80):
        m = (lo + hi) / 2
        sd = m * math.sqrt(T)
        d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
        call = df * (F * oe.ncdf(d1) - K * oe.ncdf(d1 - sd))
        val = call if cp == "c" else call - df * (F - K)
        if val > px:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def live_us() -> dict:
    metas = sorted(LIVE.glob("us_meta_*.csv"))
    if not metas:
        raise SystemExit("沒有 data/options_equity/live/us_meta_*.csv（先跑 fetch_stock_option_iv.yml）")
    meta_p = metas[-1]
    day = meta_p.stem.split("_")[-1]
    chain: dict[str, list] = {}
    with open(LIVE / f"us_chain_{day}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            chain.setdefault(r["ticker"], []).append(r)
    irx = oe.read_series("IRX")
    asof_d = date.fromisoformat(day)
    rate = (oe.asof(irx, sorted(irx), asof_d) or 0) / 100
    rows = []
    with open(meta_p, newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            t = m["ticker"]
            exp = date.fromisoformat(m["expiry"])
            T = max((exp - asof_d).days, 1) / 365
            df = math.exp(-rate * T)
            spot = float(m["spot"])
            by_k: dict[float, dict] = {}
            for r in chain.get(t, []):
                bid, ask = float(r["bid"]), float(r["ask"])
                if bid <= 0 or ask <= 0 or ask < bid:
                    continue
                mid = (bid + ask) / 2
                if (ask - bid) > 0.5 * mid:
                    continue
                by_k.setdefault(float(r["strike"]), {})[r["cp"]] = mid
            both = [k for k, v in by_k.items() if "c" in v and "p" in v]
            if not both:
                continue
            k0 = min(both, key=lambda k: abs(k - spot))
            F = k0 + (by_k[k0]["c"] - by_k[k0]["p"]) / df
            ivs = []
            below = [k for k in by_k if k <= F and "p" in by_k[k]]
            above = [k for k in by_k if k >= F and "c" in by_k[k]]
            if below:
                kb = max(below)
                ivs.append(implied_vol(F, kb, T, df, by_k[kb]["p"], "p"))
            if above:
                ka = min(above)
                ivs.append(implied_vol(F, ka, T, df, by_k[ka]["c"], "c"))
            ivs = [v for v in ivs if v]
            if not ivs or not md.has_data(t):
                continue
            o = md.load_ohlcv(t)
            adj = np.array([x["AdjClose"] for x in o if x["Date"] <= asof_d][-64:])
            if len(adj) < 61:
                continue
            rv = float(np.diff(np.log(adj)).std(ddof=1) * math.sqrt(252))
            earn = m.get("next_earnings") or ""
            soon = False
            if earn:
                try:
                    soon = 0 <= (date.fromisoformat(earn[:10]) - asof_d).days <= (exp - asof_d).days
                except ValueError:
                    pass
            rows.append(dict(ticker=t, iv=float(np.mean(ivs)), rv=rv, rho=float(np.mean(ivs)) / rv, dte=(exp - asof_d).days,
                             earnings_in_window=soon, earnings_known=bool(earn)))
    rho = np.array([r["rho"] for r in rows])
    no_e = np.array([r["rho"] for r in rows if r["earnings_known"] and not r["earnings_in_window"]])
    q = lambda a: [float(np.percentile(a, x)) for x in (25, 50, 75)] if len(a) else None  # noqa: E731
    return dict(asof=day, n=len(rows), rho_q=q(rho), rho_q_no_earnings=q(no_e),
                share_earnings_in_window=float(np.mean([r["earnings_in_window"] for r in rows])) if rows else None,
                iv_median=float(np.median([r["iv"] for r in rows])) if rows else None,
                rv_median=float(np.median([r["rv"] for r in rows])) if rows else None, rows=rows)


def live_hk() -> dict:
    """港交所股票期權每日市場報告：每類別取 20–45 日內最近到期、最接近收市價的行使價，call／put 的 IV%（港交所按結算價計）平均。
    宇宙 = 報告日的恒指成分股；RV63 用我們自己的日線。"""
    import gzip
    import re
    from datetime import datetime
    reps = sorted(LIVE.glob("hk_dqe_*.htm.gz"))
    if not reps:
        raise SystemExit("沒有 data/options_equity/live/hk_dqe_*.htm.gz")
    rp = reps[-1]
    day = date.fromisoformat(rp.name[7:17])
    txt = re.sub(r"<[^>]*>", "", gzip.decompress(rp.read_bytes()).decode("latin-1"))
    code_of = {}
    for m_ in re.finditer(r"^([A-Z0-9]{3}) .{20,40}?\(\s*(\d{5})\)", txt, re.M):
        code_of[m_.group(1)] = f"{int(m_.group(2)):04d}.HK"
    members = set(Universe("hsi").members_at(day))
    rows, seen = [], set()
    for sec in re.split(r"(?=^CLASS [A-Z0-9]{3} - )", txt, flags=re.M):
        h = re.match(r"CLASS ([A-Z0-9]{3}) - .*?CLOSING PRICE HK\$\s*([\d.,]+)", sec)
        if not h or h.group(1) in seen:
            continue
        seen.add(h.group(1))
        tk = code_of.get(h.group(1))
        if tk not in members or not md.has_data(tk) or any(r["ticker"] == tk for r in rows):   # 調整後合約另開類別：每檔只算第一個
            continue
        spot = float(h.group(2).replace(",", ""))
        ser = {}
        for m_ in re.finditer(r"^(\d{2}[A-Z]{3}\d{2})\s+([\d.,]+) ([CP])\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+[-+\d.]+\s+(\d+)", sec, re.M):
            ex = datetime.strptime(m_.group(1), "%d%b%y").date()
            ser.setdefault(ex, {}).setdefault(float(m_.group(2).replace(",", "")), {})[m_.group(3)] = int(m_.group(5))
        cands = sorted(e for e in ser if 20 <= (e - day).days <= 45)
        if not cands:
            continue
        ex = cands[0]
        both = [k for k, v in ser[ex].items() if v.get("C", 0) > 0 and v.get("P", 0) > 0]
        if not both:
            continue
        k0 = min(both, key=lambda k: abs(k - spot))
        iv = (ser[ex][k0]["C"] + ser[ex][k0]["P"]) / 200
        o = md.load_ohlcv(tk)
        adj = np.array([x["AdjClose"] for x in o if x["Date"] <= day][-64:])
        if len(adj) < 61:
            continue
        rv = float(np.diff(np.log(adj)).std(ddof=1) * math.sqrt(252))
        rows.append(dict(ticker=tk, iv=iv, rv=rv, rho=iv / rv, dte=(ex - day).days, strike=k0, spot=spot))
    rho = np.array([r["rho"] for r in rows])
    q = lambda a: [float(np.percentile(a, x)) for x in (25, 50, 75)] if len(a) else None  # noqa: E731
    return dict(asof=str(day), n=len(rows), members=len(members), rho_q=q(rho),
                iv_median=float(np.median([r["iv"] for r in rows])) if rows else None,
                rv_median=float(np.median([r["rv"] for r in rows])) if rows else None, rows=rows,
                note="IV = 港交所報告的結算價 IV%（不是自己由買賣價反推——報告沒有買賣價）；業績日無數據")


# ───────────────────────── 自檢 ─────────────────────────
def selftest() -> None:
    x = np.array([-3, -1, -0.1, 0, 0.5, 2.5])
    exact = np.array([oe.ncdf(v) for v in x])
    assert np.max(np.abs(ncdf(x) - exact)) < 2e-7
    S, K = np.array([100.0, 100.0]), np.array([100.0, 95.0])
    for cp in "cp":
        px, vg = bs_vec(S, K, 0.25, 0.03, 0.01, np.array([0.2, 0.25]), cp)
        for j in range(2):
            p1, v1 = oe.bs(S[j], K[j], 0.25, 0.03, 0.01, [0.2, 0.25][j], cp)
            assert abs(px[j] - p1) < 1e-5 and abs(vg[j] - v1) < 1e-6
    iv = implied_vol(100, 100, 0.25, math.exp(-0.0075), oe.bs(100, 100, 0.25, 0.03, 0.03, 0.3, "c")[0], "c")
    assert abs(iv - 0.3) < 1e-4, iv
    print("selftest ok：向量化常態 CDF、BS 與單值版一致、IV 反推")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"])
    ap.add_argument("--live", choices=["us", "hk"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not (a.market or a.live):
        selftest()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    if a.live:
        res = live_us() if a.live == "us" else live_hk()
        (OUT / f"stock_live_{a.live}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"live {a.live} {res['asof']}：{res['n']} 檔；ρ 四分位 {res['rho_q']}；排除業績窗口 {res.get('rho_q_no_earnings')}；"
              f"業績在窗口內比例 {res.get('share_earnings_in_window')}；IV 中位 {res['iv_median']}、RV 中位 {res['rv_median']}")
        return
    P = Panel(a.market)
    res = scan(P)
    if a.market == "us":
        res["index_reference"] = index_reference(P)
        ir = res["index_reference"]
        print(f"指數參考：真實 BXM 年化 {ir['bxm_cagr']*100:.2f}%，模型相符的 ρ = {ir['rho_matching_bxm']}；"
              f"VIX ÷ RV63 中位 {ir['vix_over_rv63_median']:.2f}（四分位 {ir['vix_over_rv63_iqr'][0]:.2f}–{ir['vix_over_rv63_iqr'][1]:.2f}）")
    meta = res["_meta"]
    print(f"{a.market}：{meta['start']} → {meta['end']}，{meta['months']} 期，每期股票數 最少 {meta['stocks_per_month'][0]}／中位 {meta['stocks_per_month'][1]}")
    for strat in STRATS:
        s = res[strat]
        line = "  ".join(f"{r}:{s['per_rho'][r]['alpha_t']:+.2f}" for r in RHOS)
        print(f"  {strat:5s} ρ₀ {s['rho0']}  ρ₂ {s['rho2']}  分段 ρ₀ {s['rho0_segments']}\n        alpha t：{line}")
    (OUT / f"stock_{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
