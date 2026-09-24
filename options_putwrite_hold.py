#!/usr/bin/env python3
"""全部成分股每月賣價外 put、接貨後永遠持有 vs 同批股票買入持有（預先登記：OPTIONS_EQUITY_BACKTEST.md 第八部分；只跑一次）。

    python3 options_putwrite_hold.py --selftest
    python3 options_putwrite_hold.py --market us      # → research/options_equity/putwrite_hold_us.json
    python3 options_putwrite_hold.py --market hk

- 年度批次：每年 1 月第一個月度到期日，當天成分股（防代碼重用、RV63 有效）各分一格資金，等權
- 每格：未接貨時每月到期日賣 1 個月現金擔保 put（K = kp × F），到期收市 < K 接貨後永遠持有（總回報）；
  剩餘現金計息；股票暫無價格時該月不賣（現金閒置），恢復報價再賣
- 對照：同一批股票批次開始當天等權買入持有
- put IV = ρ × RV63，偏斜 = 指數斜率一半，下限 5%（同第四部分）
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import options_stock as ost  # noqa: E402

OUT = ROOT / "research" / "options_equity"
RHO_C = {"us": 0.95, "hk": 0.93}
STRIKES = [0.95, 0.97, 0.90]          # 預設放第一個
RHO_SENS = [0.8, 1.0, 1.1, 1.2, 1.3]
HORIZONS = {"1y": 12, "3y": 36, "5y": 60, "10y": 120}


class Grid:
    """每檔股票在每個月度到期日的收市、還原收市（前值填補）、RV63、q。"""

    def __init__(self, P: ost.Panel):
        self.P = P
        ex = P.expiries
        self.ex = ex
        self.tk = sorted(P.close)
        n, K = len(self.tk), len(ex)
        self.close = np.full((n, K), np.nan)
        self.adj = np.full((n, K), np.nan)
        self.rv = np.full((n, K), np.nan)
        self.q = np.zeros((n, K))
        for s, t in enumerate(self.tk):
            c, a = P.close[t], P.adj[t]
            for k, i in enumerate(ex):
                ci = P.last_valid(c, i)
                if ci == ci:
                    self.close[s, k] = ci
                    self.adj[s, k] = P.last_valid(a, i)
                    self.rv[s, k] = P.rv63(t, i)
                    self.q[s, k] = P.q_at(t, i) if c[i] == c[i] else 0.0
        # 持股估值用：還原收市前值填補（下市後凍結在最後價）
        self.adj_ff = self.adj.copy()
        for k in range(1, K):
            m = np.isnan(self.adj_ff[:, k])
            self.adj_ff[m, k] = self.adj_ff[m, k - 1]
        self.r = np.array([P.M.r_at(i) for i in ex])
        self.T = np.r_[np.diff(ex) / 252, np.nan]
        self.pos = {t: s for s, t in enumerate(self.tk)}

    def cohorts(self) -> list[tuple[int, int, np.ndarray]]:
        """(開始年份, 到期日序號 k0, 股票列索引)。"""
        P, out, seen = self.P, [], set()
        for k, i in enumerate(self.ex):
            d = P.dates[i]
            if d.month != 1 or d.year in seen:
                continue
            seen.add(d.year)
            elig = P.u.eligible_at(d, P.first)
            rows = [self.pos[t] for t in sorted(elig) if t in self.pos]
            rows = [s for s in rows if self.close[s, k] == self.close[s, k] and self.rv[s, k] == self.rv[s, k]
                    and self.adj[s, k] == self.adj[s, k]]
            if len(rows) >= 5 and k + 12 < len(self.ex):
                out.append((d.year, k, np.array(rows)))
        return out


def simulate(G: Grid, k0: int, rows: np.ndarray, kp: float, rho: float, cv: float, c: float, base: dict) -> dict:
    """一個批次：回傳每個到期日的策略與買入持有組合價值（起始 1），以及每格接貨月份。"""
    K = len(G.ex)
    n = len(rows)
    W = np.full(n, 1.0)                  # 未接貨格的現金（擔保）
    cash_left = np.zeros(n)              # 接貨後剩餘現金
    sh = np.zeros(n)                     # 持股（還原收市單位）
    held = np.zeros(n, dtype=bool)
    assigned_at = np.full(n, -1)
    bh_sh = (1 - c) / G.adj[rows, k0]
    Vs, Vb = [1.0], [float(np.mean(bh_sh * G.adj_ff[rows, k0]))]
    last_rv = G.rv[rows, k0].copy()
    for k in range(k0, K - 1):
        T, r = G.T[k], G.r[k]
        g = math.exp(r * T)
        S0 = G.close[rows, k]
        live = (~held) & ~np.isnan(S0)
        rv = np.where(np.isnan(G.rv[rows, k]), last_rv, G.rv[rows, k])
        last_rv = rv
        S1 = G.close[rows, k + 1]
        if live.any():
            idx = np.nonzero(live)[0]
            s0, q = S0[idx], G.q[rows[idx], k]
            F = s0 * np.exp((r - q) * T)
            Kx = kp * F
            v = ost.iv_vec(rho * rv[idx], F, Kx, T, base["s_put"], base["s_call"])
            px, vg = ost.bs_vec(s0, Kx, T, r, q, v, "p")
            nct = W[idx] / Kx
            tot = (W[idx] + nct * (px - vg * cv)) * g
            s1 = S1[idx]
            asg = (~np.isnan(s1)) & (s1 < Kx)
            # 接貨：付出擔保現金（= nct × K），持有 nct 股
            ai = idx[asg]
            if len(ai):
                sh[ai] = nct[asg] * s1[asg] / G.adj[rows[ai], k + 1]
                cash_left[ai] = tot[asg] - W[ai] - c * W[ai]
                held[ai] = True
                assigned_at[ai] = k + 1 - k0
                W[ai] = 0.0
            ni = idx[~asg]
            W[ni] = tot[~asg]
        # 暫無價格的未接貨格：現金照計息
        idle = (~held) & np.isnan(S0)
        W[idle] *= g
        cash_left[held] *= g
        val = W + cash_left + np.where(held, sh * G.adj_ff[rows, k + 1], 0.0)
        Vs.append(float(val.mean()))
        Vb.append(float(np.mean(bh_sh * G.adj_ff[rows, k + 1])))
    return dict(Vs=np.array(Vs), Vb=np.array(Vb), assigned_at=assigned_at)


def cohort_stats(G: Grid, cohorts, kp, rho, cv, c, base) -> dict:
    per = []
    pooled_s, pooled_b, pooled_rf = [], [], []
    for y, k0, rows in cohorts:
        sim = simulate(G, k0, rows, kp, rho, cv, c, base)
        Vs, Vb = sim["Vs"], sim["Vb"]
        rs, rb = Vs[1:] / Vs[:-1] - 1, Vb[1:] / Vb[:-1] - 1
        rf = np.array([math.exp(G.r[k] * G.T[k]) - 1 for k in range(k0, k0 + len(rs))])
        pooled_s += list(rs)
        pooled_b += list(rb)
        pooled_rf += list(rf)
        row = dict(year=y, n=len(rows))
        for h, m in HORIZONS.items():
            if m < len(Vs):
                row[h] = float(math.log(Vs[m] / Vb[m]))
                row[h + "_s"], row[h + "_b"] = float(Vs[m]), float(Vb[m])
        row["end_months"] = len(Vs) - 1
        row["end_logratio"] = float(math.log(Vs[-1] / Vb[-1]))
        mdd = lambda v: float((v / np.maximum.accumulate(v) - 1).min())  # noqa: E731
        row["mdd_s"], row["mdd_b"] = mdd(Vs), mdd(Vb)
        aa = sim["assigned_at"]
        row["assigned_by"] = {m: float(np.mean((aa > 0) & (aa <= m))) for m in (1, 3, 12, 36)}
        if 60 < len(Vs):
            # 5 年時未接貨 vs 已接貨：各自的買入持有 log 報酬
            bh5 = np.log(G.adj_ff[rows, k0 + 60] / G.adj[rows, k0])
            un = ~((aa > 0) & (aa <= 60))
            row["bh5_unassigned"] = float(np.nanmean(bh5[un])) if un.any() else None
            row["bh5_assigned"] = float(np.nanmean(bh5[~un])) if (~un).any() else None
            row["share_unassigned_5y"] = float(un.mean())
        per.append(row)
    ps, pb, prf = np.array(pooled_s), np.array(pooled_b), np.array(pooled_rf)
    sharpe = lambda r: float((r - prf).mean() / (r - prf).std(ddof=1) * math.sqrt(12))  # noqa: E731
    one = np.array([p["1y"] for p in per if "1y" in p])
    five = [p["5y"] for p in per if "5y" in p]
    res = dict(cohorts=per,
               oney_mean=float(one.mean()), oney_t=float(one.mean() / (one.std(ddof=1) / math.sqrt(len(one)))),
               oney_n=len(one), fivey_median=float(np.median(five)) if five else None, fivey_n=len(five),
               sharpe_s=sharpe(ps), sharpe_b=sharpe(pb))
    for h in HORIZONS:
        v = [p[h] for p in per if h in p]
        if v:
            res[f"{h}_median"], res[f"{h}_mean"], res[f"{h}_share_pos"] = float(np.median(v)), float(np.mean(v)), float(np.mean(np.array(v) > 0))
    return res


def verdict(d: dict, lo: dict, neigh: list[dict]) -> str:
    ok = (d["oney_mean"] > 0 and d["oney_t"] >= 2.0 and (d["fivey_median"] or -1) > 0 and d["sharpe_s"] >= d["sharpe_b"]
          and lo["oney_mean"] > 0 and sum(x["oney_mean"] > 0 for x in neigh) >= 2)
    if ok:
        return "🔍"
    if d["oney_mean"] < 0 and (d["fivey_median"] is not None and d["fivey_median"] < 0):
        return "☠️"
    return "不確定"


def run(market: str) -> dict:
    P = ost.Panel(market)
    G = Grid(P)
    base, cfg = P.base, P.c
    cv, c = cfg["cost"], cfg["stk_cost"]
    rc = RHO_C[market]
    cohorts = G.cohorts()
    out = dict(market=market, rho_center=rc, cohorts=[(y, int(len(r))) for y, _, r in cohorts])
    cells = {kp: cohort_stats(G, cohorts, kp, rc, cv, c, base) for kp in STRIKES}
    lo = cohort_stats(G, cohorts, STRIKES[0], round(rc - 0.1, 2), cv, c, base)
    sens = {rho: cohort_stats(G, cohorts, STRIKES[0], rho, cv, c, base) for rho in RHO_SENS}
    out["cells"] = {str(k): v for k, v in cells.items()}
    out["rho_minus_0.1"] = lo
    out["rho_sens"] = {str(k): {kk: v[kk] for kk in ("oney_mean", "oney_t", "fivey_median", "sharpe_s", "sharpe_b")} for k, v in sens.items()}
    out["verdict"] = verdict(cells[STRIKES[0]], lo, [cells[k] for k in STRIKES])
    return out


def selftest() -> None:
    # 一檔股票、兩期、人工數字：第 1 期不接貨、第 2 期接貨，檢查現金與持股
    class Fake:
        pass
    G = Fake()
    G.ex = [0, 21, 42, 63]
    G.close = np.array([[100.0, 101.0, 90.0, 95.0]])
    G.adj = G.close.copy()
    G.adj_ff = G.close.copy()
    G.rv = np.full((1, 4), 0.3)
    G.q = np.zeros((1, 4))
    G.r = np.zeros(4)
    G.T = np.array([21 / 252] * 3 + [np.nan])
    base = dict(s_put=-0.24, s_call=-0.15)
    sim = simulate(G, 0, np.array([0]), 0.95, 1.0, 0.0, 0.0, base)
    Vs = sim["Vs"]
    px1, _ = ost.bs_vec(np.array([100.0]), np.array([95.0]), 21 / 252, 0, 0,
                        ost.iv_vec(0.3, np.array([100.0]), np.array([95.0]), 21 / 252, -0.24, -0.15), "p")
    W1 = 1 + px1[0] / 95
    assert abs(Vs[1] - W1) < 1e-9, (Vs[1], W1)                      # 第 1 期沒接貨：現金 = 1 + 權利金
    K2 = 0.95 * 101
    px2, _ = ost.bs_vec(np.array([101.0]), np.array([K2]), 21 / 252, 0, 0,
                        ost.iv_vec(0.3, np.array([101.0]), np.array([K2]), 21 / 252, -0.24, -0.15), "p")
    n2 = W1 / K2
    V2 = n2 * 90 + n2 * px2[0]                                     # 接貨：n2 股 × 90 + 權利金現金
    assert abs(Vs[2] - V2) < 1e-9, (Vs[2], V2)
    assert abs(Vs[3] - (n2 * 95 + n2 * px2[0])) < 1e-9             # 之後永遠持有
    assert sim["assigned_at"][0] == 2
    print(f"selftest ok：不接貨期現金 {Vs[1]:.4f}、接貨後價值 {Vs[2]:.4f} → {Vs[3]:.4f}（手算一致）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.market:
        selftest()
        return
    res = run(a.market)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"putwrite_hold_{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{a.market}：{len(res['cohorts'])} 個批次，ρ 中心 {res['rho_center']}，判決 {res['verdict']}")
    for k, d in res["cells"].items():
        print(f"  K={k}F：1 年 log 差 平均 {d['oney_mean']*100:+.2f}%（t {d['oney_t']:+.2f}，{d['oney_n']} 批）"
              f"  3y 中位 {d.get('3y_median', float('nan'))*100:+.2f}%  5y 中位 {(d['fivey_median'] or float('nan'))*100:+.2f}%（{d['fivey_n']} 批）"
              f"  10y 中位 {d.get('10y_median', float('nan'))*100:+.2f}%  夏普 {d['sharpe_s']:.2f} vs {d['sharpe_b']:.2f}")
    lo = res["rho_minus_0.1"]
    print(f"  ρ − 0.1：1 年平均 {lo['oney_mean']*100:+.2f}%（t {lo['oney_t']:+.2f}）")
    print("  ρ 敏感度：" + "  ".join(f"{k}:{v['oney_mean']*100:+.2f}%/5y{(v['fivey_median'] or float('nan'))*100:+.1f}%" for k, v in res["rho_sens"].items()))


if __name__ == "__main__":
    main()
