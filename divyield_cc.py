#!/usr/bin/env python3
"""高息股「財息兼收」回測（預先登記：DIVYIELD_CC_BACKTEST.md 第一部分；每市場只跑一次）。

    python3 divyield_cc.py --selftest
    python3 divyield_cc.py --control            # 對照組：同一路徑重跑港股預設格，須重現 +433.6%、alpha t 2.77
    python3 divyield_cc.py --market us          # 項目 2（美股高息 6 格）+ 項目 3（賣 call 疊加）→ research/divyield_cc/us.json
    python3 divyield_cc.py --market hk          # 項目 3（港股高息 + 賣 call）→ research/divyield_cc/hk.json

- 選股與組合報酬：直接呼叫 stock_momentum_backtest.run_backtest(signal="divyield")（港股那次的同一份程式碼）
- 美股成分股：每個月底一份快照 = Universe("sp500") 當天名單，先過防代碼重用（eligible_at）
- 賣 call：每期每檔在建倉日收市賣 call，K = kc × 收市，到下次換倉日開市結算；除淨前按美式提前行使條件判斷
"""
import argparse
import bisect
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
import options_equity as oe  # noqa: E402
import stock_momentum_backtest as eng  # noqa: E402
from universe import Universe  # noqa: E402

OUT = ROOT / "research" / "divyield_cc"
MKT = {
    "hk": dict(bench="2800.HK", cost_bps=15.0, rho=0.93, cv=1.0, splits=[date(2022, 1, 1)]),
    "us": dict(bench="SPY", cost_bps=5.0, rho=0.95, cv=0.5, splits=[date(2013, 1, 1), date(2022, 1, 1)]),
}
GRID = [(w, k) for w in (12, 24) for k in (5, 10, 15)]
DEFAULT = (12, 10)
KC = [1.05, 1.02, 1.10]
RHO_SENS = [0.8, 1.0, 1.1, 1.2, 1.3]
US_TAX = 0.30


# ───────────────────────── 宇宙 ─────────────────────────
def hk_universe():
    snaps = eng.load_pointintime(ROOT / "scripts" / "pointintime")
    members = set().union(*(m for _, m in snaps))
    pool = sorted(t for t in members if t != "2800.HK" and md.has_data(t))
    return pool, snaps


def us_universe():
    u = Universe("sp500")
    spy = sorted(md.load_series("SPY"))
    ends = eng.month_end_dates(spy)
    tickers = [t for t in u.all_tickers(since=date(1995, 1, 1)) if md.has_data(t) and t != "SPY"]
    first = {t: min(md.load_series(t)) for t in tickers}
    snaps = []
    for d in ends:
        if d < date(1995, 12, 1):
            continue
        snaps.append((d, set(u.eligible_at(d, first))))
    pool = sorted({t for _, m in snaps for t in m})
    return pool, snaps


def run(market: str, w: int, k: int, pool, snaps) -> dict:
    return eng.run_backtest(pool, MKT[market]["bench"], 12, 1, k, MKT[market]["cost_bps"], None, True, None,
                            snaps, "divyield", 252, None, False, None, w)


def summary(res: dict) -> dict:
    rs = eng.risk_stats(res)
    mdd = eng.max_drawdown(res["equity_curve"])[0]
    return dict(total=res["final_equity"] - 1, bench_total=res["bench_total_return"], alpha_t=rs["alpha_t"],
                alpha_ann=rs["alpha_ann"], beta=rs["beta"], t_excess=rs["t_excess"], sharpe=rs["sharpe"],
                bench_sharpe=rs["bench_sharpe"], mdd=mdd, bench_mdd=rs["bench_mdd"], n=res["n_periods"],
                start=str(res["bench_start"]), end=str(res["bench_end"]))


def capm(r, b):
    r, b = np.asarray(r), np.asarray(b)
    n = len(r)
    if n < 12:
        return float("nan")
    X = np.column_stack([np.ones(n), b])
    coef, *_ = np.linalg.lstsq(X, r, rcond=None)
    e = r - X @ coef
    se = np.sqrt(np.diag(e @ e / (n - 2) * np.linalg.inv(X.T @ X)))
    return float(coef[0] / se[0])


def split_stats(res: dict, splits: list[date]) -> dict:
    d = [x for x, _ in res["period_returns"]]
    r = [x for _, x in res["period_returns"]]
    b = res["bench_period_returns"]
    out = {}
    for sp in splits:
        pre = [i for i, x in enumerate(d) if x < sp]
        post = [i for i, x in enumerate(d) if x >= sp]
        out[str(sp)] = dict(pre=capm([r[i] for i in pre], [b[i] for i in pre]),
                            post=capm([r[i] for i in post], [b[i] for i in post]))
    return out


# ───────────────────────── 數據（賣 call 用）─────────────────────────
class Px:
    def __init__(self, tickers: list[str]):
        self.s = {}
        self.dates = {}
        self.divs = {}
        for t in set(tickers):
            ser = md.load_series(t)          # {date: (adj_open, adj_close, raw_close)}
            self.s[t] = ser
            self.dates[t] = sorted(ser)
            self.divs[t] = eng.derive_dividends(ser)
        irx = oe.read_series("IRX")
        self.irx, self.irk = irx, sorted(irx)

    def r(self, d: date) -> float:
        return (oe.asof(self.irx, self.irk, d) or 0.0) / 100

    def raw_open(self, t, d):
        ao, ac, c = self.s[t][d]
        return ao * c / ac if ac > 0 else float("nan")

    def rv63(self, t, d):
        ds = self.dates[t]
        i = bisect.bisect_right(ds, d)
        a = [self.s[t][x][1] for x in ds[max(0, i - 64):i]]
        a = [x for x in a if x > 0]
        if len(a) < 61:
            return float("nan")
        lr = np.diff(np.log(a))
        return float(lr.std(ddof=1) * math.sqrt(252))

    def q(self, t, d, S):
        tot = sum(x for e, x in self.divs[t] if 0 < (d - e).days <= 365)
        return tot / S if S > 0 else 0.0

    def ntd(self, t, a, b):
        """a 到 b 之間的交易日數（用該股自己的日曆）。"""
        ds = self.dates[t]
        return max(bisect.bisect_left(ds, b) - bisect.bisect_left(ds, a), 1)


def call_price(S, K, T, r, q, rv, rho, base, cv):
    F = S * math.exp((r - q) * T)
    m = math.log(K / F) / math.sqrt(T)
    s = (base["s_put"] if m < 0 else base["s_call"]) * 0.5
    v = max(rho * rv + s * m, 0.05)
    px, vega = oe.bs(S, K, T, r, q, v, "c")
    return px, vega * cv, v


def stock_period(px: Px, t: str, e0: date, e1: date):
    """同引擎：AdjOpen→AdjOpen；中途下市用最後收市。回傳 (報酬, 結算原始價, 結算日, 是否下市)。"""
    s = px.s[t]
    if e0 not in s:
        return None
    p0 = s[e0][0]
    if e1 in s:
        return s[e1][0] / p0 - 1, px.raw_open(t, e1), e1, False
    last = [d for d in px.dates[t] if e0 <= d < e1]
    if not last:
        return None
    d = max(last)
    return s[d][1] / p0 - 1, s[d][2], d, True


def overlay(res: dict, px: Px, market: str, kc: float, rho: float, base: dict) -> dict:
    """同一批持倉：不賣 call vs 賣 call 的每期組合報酬。"""
    cfg = MKT[market]
    cv = cfg["cv"]
    baskets = res["baskets"]
    exits = [d for d, _ in res["period_returns"]]
    prev = set()
    plain, cc, bench = [], [], res["bench_period_returns"]
    stats = dict(n=0, called=0, early=0, lost_div=0.0, no_price=0)
    check = []
    for (e0, basket), e1, eng_ret in zip(baskets, exits, [r for _, r in res["period_returns"]]):
        new = set(basket)
        prev_b = prev
        prev = new
        rp, rc = [], []
        for t in basket:
            sp = stock_period(px, t, e0, e1)
            if sp is None:
                continue
            R, S_end, d_end, delisted = sp
            rp.append(R)
            S = px.s[t][e0][2]
            rv = px.rv63(t, e0)
            n = 1.0 / px.raw_open(t, e0)
            if not (rv == rv) or not (S > 0) or not (n == n):
                rc.append(R)
                stats["no_price"] += 1
                continue
            K = kc * S
            T = px.ntd(t, e0, e1) / 252
            r, q = px.r(e0), px.q(t, e0, S)
            c, ccost, v = call_price(S, K, T, r, q, rv, rho, base, cv)
            prem = n * (c - ccost) * math.exp(r * T)
            stats["n"] += 1
            # 除淨前提前行使
            ex = None
            for dd, D in px.divs[t]:
                if e0 < dd <= e1:
                    ds = px.dates[t]
                    j = bisect.bisect_left(ds, dd) - 1
                    if j < 0 or ds[j] < e0:
                        continue
                    dp = ds[j]
                    Sp = px.s[t][dp][2]
                    tau = max(px.ntd(t, dp, e1), 1) / 252
                    put, _ = oe.bs(Sp, K, tau, r, 0.0, v, "p")
                    if Sp > K and D > put + K * (1 - math.exp(-r * tau)):
                        ex = (dp, D)
                        break
            if ex:
                dp, D = ex
                val = n * K * math.exp(r * px.ntd(t, dp, e1) / 252) + prem
                stats["early"] += 1
                stats["called"] += 1
                stats["lost_div"] += D / S
            else:
                pay = n * max(S_end - K, 0.0)
                if S_end > K:
                    stats["called"] += 1
                val = (1 + R) - pay + prem
            rc.append(val - 1)
        n_changed = len(prev_b - new) + len(new - prev_b)
        # 換手成本：同引擎（weight = 1/top_k）
        top_k = res.get("_top_k", 10)
        cost_frac = n_changed * (1.0 / top_k) * (cfg["cost_bps"] / 10000.0)
        gp = sum(rp) / len(rp) if rp else 0.0
        gc = sum(rc) / len(rc) if rc else 0.0
        plain.append(gp - cost_frac)
        cc.append(gc - cost_frac)
        check.append(abs((gp - cost_frac) - eng_ret))
    plain, cc, bench = np.array(plain), np.array(cc), np.array(bench)
    diff = cc - plain
    t = float(diff.mean() / (diff.std(ddof=1) / math.sqrt(len(diff))))
    eq = np.cumprod(1 + cc)
    out = dict(kc=kc, rho=rho, diff_mean_m=float(diff.mean()), diff_t=t, diff_ann=float(diff.mean() * 12),
               alpha_t_cc=capm(cc, bench), alpha_t_plain=capm(plain, bench),
               total_cc=float(eq[-1] - 1), total_plain=float(np.prod(1 + plain) - 1),
               mdd_cc=float((eq / np.maximum.accumulate(eq) - 1).min()),
               called_share=stats["called"] / max(stats["n"], 1), early_ex=stats["early"],
               lost_div_mean=stats["lost_div"] / max(stats["early"], 1), option_positions=stats["n"],
               no_price=stats["no_price"], max_recon_err=float(max(check) if check else 0))
    dates = exits
    for sp in MKT[market]["splits"]:
        m = np.array([d < sp for d in dates])
        out[f"diff_pre_{sp}"] = float(diff[m].mean()) if m.any() else None
        out[f"diff_post_{sp}"] = float(diff[~m].mean()) if (~m).any() else None
    return out


def verdict_overlay(cells: dict, lo: dict) -> str:
    d0 = cells[str(KC[0])]
    ok = (d0["diff_mean_m"] > 0 and d0["diff_t"] >= 2.0 and d0["alpha_t_cc"] >= d0["alpha_t_plain"]
          and lo["diff_mean_m"] > 0 and sum(c["diff_mean_m"] > 0 for c in cells.values()) >= 2)
    if ok:
        return "🔍"
    return "☠️" if d0["diff_mean_m"] < 0 else "不確定"


def verdict_div(cells: dict) -> str:
    d0 = cells[f"W{DEFAULT[0]}K{DEFAULT[1]}"]
    if d0["alpha_t"] >= 2.0 and sum(c["alpha_t"] >= 1.5 for c in cells.values()) >= 4:
        return "🔍"
    return "☠️" if d0["alpha_t"] < 1.0 else "不確定"


def after_tax(res: dict, px: Px, bench: str) -> dict:
    """稅後（股息預扣 30%）：每檔持倉扣該期股息 × 30% ÷ 建倉原始開市；SPY 同樣扣。"""
    exits = [d for d, _ in res["period_returns"]]
    rs, bs = [], []
    for (e0, basket), e1, (_, r), b in zip(res["baskets"], exits, res["period_returns"], res["bench_period_returns"]):
        drag = []
        for t in basket:
            if e0 not in px.s[t]:
                continue
            o = px.raw_open(t, e0)
            drag.append(sum(D for dd, D in px.divs[t] if e0 < dd <= e1) * US_TAX / o if o > 0 else 0.0)
        rs.append(r - (sum(drag) / len(drag) if drag else 0.0))
        o = px.raw_open(bench, e0)
        bs.append(b - sum(D for dd, D in px.divs[bench] if e0 < dd <= e1) * US_TAX / o)
    return dict(alpha_t=capm(rs, bs), total=float(np.prod(1 + np.array(rs)) - 1), bench_total=float(np.prod(1 + np.array(bs)) - 1))


def main_market(market: str) -> dict:
    pool, snaps = hk_universe() if market == "hk" else us_universe()
    base = oe.MARKETS[market]
    out = dict(market=market, pool=len(pool), snapshots=len(snaps))
    cells, res_default = {}, None
    grid = GRID if market == "us" else [DEFAULT]
    for w, k in grid:
        res = run(market, w, k, pool, snaps)
        res["_top_k"] = k
        s = summary(res)
        s["splits"] = split_stats(res, MKT[market]["splits"])
        cells[f"W{w}K{k}"] = s
        if (w, k) == DEFAULT:
            res_default = res
        print(f"  {market} W{w}K{k}：總報酬 {s['total']:+.1%} vs {s['bench_total']:+.1%}  alpha t {s['alpha_t']:+.2f}"
              f"（年化 {s['alpha_ann']:+.1%}）beta {s['beta']:.2f}  夏普 {s['sharpe']:.2f}/{s['bench_sharpe']:.2f}"
              f"  MDD {s['mdd']:.0%}/{s['bench_mdd']:.0%}  分段 {s['splits']}", flush=True)
    out["div_cells"] = cells
    if market == "us":
        out["div_verdict"] = verdict_div(cells)
    # 持倉統計
    from collections import Counter
    cnt = Counter(t for _, b in res_default["baskets"] for t in b)
    out["most_held"] = cnt.most_common(15)
    px = Px(pool + [MKT[market]["bench"]])
    if market == "us":
        out["after_tax"] = after_tax(res_default, px, "SPY")
    # 項目 3：賣 call 疊加
    ov = {}
    for kc in KC:
        ov[str(kc)] = overlay(res_default, px, market, kc, MKT[market]["rho"], base)
    lo = overlay(res_default, px, market, KC[0], round(MKT[market]["rho"] - 0.1, 2), base)
    sens = {str(r): overlay(res_default, px, market, KC[0], r, base) for r in RHO_SENS}
    out["cc_cells"], out["cc_rho_minus_0.1"], out["cc_rho_sens"] = ov, lo, sens
    out["cc_verdict"] = verdict_overlay(ov, lo)
    return out


def control() -> None:
    pool, snaps = hk_universe()
    res = run("hk", 12, 10, pool, snaps)
    s = summary(res)
    ok = abs(s["total"] - 4.336) < 0.0015 and abs(s["alpha_t"] - 2.77) < 0.005
    print(f"對照組（港股預設格）：總報酬 {s['total']:+.2%}、alpha t {s['alpha_t']:.3f} → {'✅ 重現' if ok else '❌ 不一致'}"
          f"（登記值 +433.6%、2.77；數據期間 {s['start']} → {s['end']}）")
    sys.exit(0 if ok else 1)


def selftest() -> None:
    base = oe.MARKETS["us"]
    c0, cc0, _ = call_price(100, 105, 21 / 252, 0.04, 0.03, 0.2, 1.0, base, 0.0)
    c1, cc1, _ = call_price(100, 105, 21 / 252, 0.04, 0.03, 0.2, 1.0, base, 0.5)
    assert 0 < c0 < 1.0 and cc0 == 0 and cc1 > 0, (c0, cc1)
    # 提前行使條件：深價內、股息大 → 行使；價外 → 不行使
    put, _ = oe.bs(120, 105, 10 / 252, 0.04, 0.0, 0.2, "p")
    assert 2.0 > put + 105 * (1 - math.exp(-0.04 * 10 / 252))
    print(f"selftest ok：5% 價外 1 個月 call（σ 20%）{c0:.3f}、成本 {cc1:.3f}；深價內＋股息 2 元 → 提前行使條件成立")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["hk", "us"])
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if a.control:
        control()
        return
    if not a.market:
        ap.error("需要 --market / --control / --selftest")
    out = main_market(a.market)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.market}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if "div_verdict" in out:
        print(f"項目 2 美股高息判決：{out['div_verdict']}；稅後 {out['after_tax']}")
    for kc, c in out["cc_cells"].items():
        print(f"  賣 call K={kc}：差 {c['diff_mean_m']*100:+.3f}%/月（t {c['diff_t']:+.2f}，年化 {c['diff_ann']*100:+.2f}%）"
              f"  alpha t {c['alpha_t_cc']:+.2f} vs {c['alpha_t_plain']:+.2f}  被行使 {c['called_share']:.0%}"
              f"  提前行使 {c['early_ex']}  對帳誤差 {c['max_recon_err']:.1e}")
    lo = out["cc_rho_minus_0.1"]
    print(f"  ρ−0.1：差 {lo['diff_mean_m']*100:+.3f}%/月（t {lo['diff_t']:+.2f}）")
    print("  ρ 敏感度：" + "  ".join(f"{k}:{v['diff_mean_m']*100:+.3f}%/t{v['diff_t']:+.1f}" for k, v in out["cc_rho_sens"].items()))
    print(f"項目 3 {a.market} 賣 call 判決：{out['cc_verdict']}")


if __name__ == "__main__":
    main()
