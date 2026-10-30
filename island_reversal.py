#!/usr/bin/env python3
"""島狀反轉全網格（stock_research/ISLAND_REVERSAL_PREREG.md；登記 commit 788379f8 之後寫）。樣本內擬合，唔覆蓋任何判決。

    python3 island_reversal.py --market us     # → research/island_reversal/us.json
    python3 island_reversal.py --market hk

確認日 j＝右缺口日、島身 a…b＝j−1；缺口用調整口徑最高／最低價（× AdjClose ÷ Close）。
網格：方向 × 島身最長 N × 最小缺口 g × 嚴格／寬鬆 × 確認日報酬過濾 = 504 組；確認日收市入場，
量度超額 21 日報酬（減全部有數據股票等權平均）、RVfwd21 ÷ RV63pre、賣 95% put／105% call 的 ρ*、ρ₂。
"""
import argparse
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
from bigdrop_options import H, Study, breakeven, ratio_stats, ret_stats, rv  # noqa: E402
from options_stock import CFG  # noqa: E402

OUT = ROOT / "research" / "island_reversal"
NS = [1, 3, 5, 10, 20, 40, 60]
GS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05]
RULES = ["strict", "loose"]
FILT = {"top": [None, -0.05, -0.08], "bot": [None, 0.05, 0.08]}
LEGS2 = {"put95": [("p", 0.95)], "call105": [("c", 1.05)]}
NMAX = max(NS)


def find_islands(hi: np.ndarray, lo: np.ndarray, kind: str) -> list[dict]:
    """回傳候選確認日：dict(j, gR, cand={rule: [(n, gL), …]})。hi／lo 已調整口徑，可含 nan。"""
    out = []
    n = len(hi)
    for j in range(2, n):
        b = j - 1
        if kind == "top":
            if not (hi[j] < lo[b]):
                continue
            gR = lo[b] / hi[j] - 1
        else:
            if not (lo[j] > hi[b]):
                continue
            gR = lo[j] / hi[b] - 1
        cand = {"strict": [], "loose": []}
        body = lo[b] if kind == "top" else hi[b]           # 島身極值（頂部＝最低、底部＝最高）
        strict_alive = True
        for a in range(b, max(b - NMAX, 0), -1):
            if kind == "top":
                body = min(body, lo[a])
                if body != body:
                    break
                if strict_alive and not (body > hi[j]):
                    strict_alive = False
                if lo[a] > hi[a - 1]:
                    gL = lo[a] / hi[a - 1] - 1
                    cand["loose"].append((b - a + 1, gL))
                    if strict_alive and body > hi[a - 1]:
                        cand["strict"].append((b - a + 1, gL))
            else:
                body = max(body, hi[a])
                if body != body:
                    break
                if strict_alive and not (body < lo[j]):
                    strict_alive = False
                if hi[a] < lo[a - 1]:
                    gL = lo[a - 1] / hi[a] - 1
                    cand["loose"].append((b - a + 1, gL))
                    if strict_alive and body < lo[a - 1]:
                        cand["strict"].append((b - a + 1, gL))
        if cand["loose"]:
            out.append(dict(j=j, gR=gR, cand=cand))
    return out


def tstat_month(ev, x) -> tuple[float, float]:
    by: dict[tuple, list] = {}
    for e, v in zip(ev, x):
        by.setdefault((e["d"].year, e["d"].month), []).append(v)
    m = np.array([np.mean(v) for v in by.values()])
    if len(m) < 3 or m.std(ddof=1) == 0:
        return float(np.mean(x)) if len(x) else float("nan"), float("nan")
    return float(np.mean(x)), float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


class Islands:
    def __init__(self, market: str):
        self.m = market
        self.S = Study(market)
        P = self.P = self.S.P
        n = len(P.dates)
        self.hi, self.lo = {}, {}
        for t in P.close:
            h, l = np.full(n, np.nan), np.full(n, np.nan)
            for r in md.load_ohlcv(t):
                i = P.di.get(r["Date"])
                if i is not None and r["Close"] and r["Close"] > 0 and r["High"] and r["Low"]:
                    f = r["AdjClose"] / r["Close"]
                    h[i], l[i] = r["High"] * f, r["Low"] * f
            self.hi[t], self.lo[t] = h, l
        # 基準：同日 PIT 成分股（有數據者）等權平均前向報酬（登記第 5 部分；v1 誤用全部有數據股票，見報告）
        names = list(P.close)
        A = np.array([P.adj[t] for t in names])
        M = np.zeros(A.shape, dtype=bool)
        col = {t: r for r, t in enumerate(names)}
        for i, d in enumerate(P.dates):
            if d >= CFG[market]["start"]:
                for t in self.S.members(d):
                    if t in col:
                        M[col[t], i] = True
        self.bench = {}
        for k in (5, H, 63):
            fw = np.full_like(A, np.nan)
            fw[:, :-k] = A[:, k:] / A[:, :-k] - 1
            fw[~M] = np.nan
            with np.errstate(all="ignore"):
                self.bench[k] = np.nanmean(fw, axis=0)

    def fwd(self, adj, i, k):
        a1 = self.P.last_valid(adj, min(i + k, len(adj) - 1))
        return a1 / adj[i] - 1 if adj[i] == adj[i] and a1 == a1 else float("nan")

    def raw_events(self) -> dict[str, list[dict]]:
        """每個方向全部候選（未按網格過濾），已做資格檢查、算好結果。"""
        P, S, out = self.P, self.S, {"top": [], "bot": []}
        n = len(P.dates)
        for t in P.close:
            adj, c = P.adj[t], P.close[t]
            for kind in ("top", "bot"):
                for x in find_islands(self.hi[t], self.lo[t], kind):
                    j = x["j"]
                    d = P.dates[j]
                    if d < CFG[self.m]["start"] or j + 63 >= n:
                        continue
                    if np.count_nonzero(~np.isnan(adj[:j])) < 315 or not (c[j] >= 5) or t not in S.members(d):
                        continue
                    rv63 = rv(adj[j - 64:j])
                    rvf = rv(adj[j:j + H + 1])
                    r21 = self.fwd(adj, j, H)
                    if not (rv63 > 0) or math.isnan(rvf) or math.isnan(r21) or adj[j - 1] != adj[j - 1]:
                        continue
                    rate = (oe.asof(P.M.rf, P.M.rk, d) or 0) / 100
                    out[kind].append(dict(t=t, i=j, d=d, gR=x["gR"], cand=x["cand"], day=float(adj[j] / adj[j - 1] - 1),
                                          S0=float(c[j]), S1=float(c[j] * (1 + r21)), ret=float(r21), rv63=rv63, rvf=rvf,
                                          r=rate, q=P.q_at(t, j),
                                          ex5=self.fwd(adj, j, 5) - self.bench[5][j], ex21=r21 - self.bench[H][j],
                                          ex63=self.fwd(adj, j, 63) - self.bench[63][j]))
        return out

    def add_excess(self, ev: list[dict]) -> list[dict]:
        for e in ev:
            j = self.P.di[e["d"]]
            adj = self.P.adj[e["t"]]
            e["ex5"] = self.fwd(adj, j, 5) - self.bench[5][j]
            e["ex21"] = e["ret"] - self.bench[H][j]
            e["ex63"] = self.fwd(adj, j, 63) - self.bench[63][j] if j + 63 < len(adj) else float("nan")
        return ev


def select(raw: list[dict], kind: str, N: int, g: float, rule: str, filt) -> list[dict]:
    ev = []
    for e in raw:
        if e["gR"] < g or not any(n <= N and gL >= g for n, gL in e["cand"][rule]):
            continue
        if filt is not None and ((kind == "top" and e["day"] > filt) or (kind == "bot" and e["day"] < filt)):
            continue
        ev.append(e)
    ev.sort(key=lambda e: (e["t"], e["i"]))
    keep, last = [], {}
    for e in ev:
        if e["i"] - last.get(e["t"], -10 ** 9) >= H:
            keep.append(e)
            last[e["t"]] = e["i"]
    return keep


def summarize(ev: list[dict], cost: float, legs=True) -> dict:
    if not ev:
        return dict(n=0)
    out = dict(n=len(ev))
    for k in ("ex5", "ex21", "ex63"):
        x = np.array([e[k] for e in ev if e[k] == e[k]])
        mu, t = tstat_month([e for e in ev if e[k] == e[k]], x)
        out[k] = dict(mean_pct=mu * 100, t=t)
    out["ret21"] = ret_stats(ev)
    out["ratio"] = ratio_stats(ev)
    if legs and len(ev) >= 10:
        for k, v in LEGS2.items():
            b = breakeven(ev, v, cost)
            out[k] = dict(rho_star=b["rho_star"], rho2=b["rho2"])
    return out


def run(market: str) -> dict:
    I = Islands(market)
    cost = I.S.cost
    raw = I.raw_events()
    res = dict(market=market, prereg_commit="788379f8", coverage=I.S.coverage, note="樣本內網格擬合；唔覆蓋任何判決",
               raw_candidates={k: len(v) for k, v in raw.items()}, grid={})
    for kind in ("top", "bot"):
        for N in NS:
            for g in GS:
                for rule in RULES:
                    for f in FILT[kind]:
                        key = f"{kind}_N{N}_g{g * 100:g}_{rule}_f{'none' if f is None else f'{f * 100:+g}'}"
                        ev = select(raw[kind], kind, N, g, rule, f)
                        res["grid"][key] = summarize(ev, cost)
        print(f"{market} {kind}: 候選 {len(raw[kind])}，網格完成")
    big = I.add_excess(I.S.events(-0.08, 0))
    res["control_bigdrop_m8"] = summarize(big, cost)
    ctrl = I.add_excess(I.S.events(-1.0, 0, random_ctrl=True))
    res["control_random"] = summarize(ctrl, cost)
    return res


def selftest() -> None:
    # 頂部：0–4 低位、5–7 島（跳空升）、8 跳空跌
    hi = np.array([10, 10, 10, 10, 10, 13, 14, 13, 9, 9.0])
    lo = np.array([9, 9, 9, 9, 9, 12, 12.5, 12, 8, 8.0])
    x = find_islands(hi, lo, "top")
    assert len(x) == 1 and x[0]["j"] == 8 and x[0]["cand"]["strict"] == [(3, 12 / 10 - 1)], x
    assert abs(x[0]["gR"] - (12 / 9 - 1)) < 1e-12
    # 島身回補左缺口 → 寬鬆有、嚴格冇
    lo2 = lo.copy(); lo2[6] = 9.5
    x = find_islands(hi, lo2, "top")
    assert x and x[0]["cand"]["strict"] == [] and x[0]["cand"]["loose"], x
    # 底部鏡像
    x = find_islands(-lo[::-1] + 30, -hi[::-1] + 30, "bot")
    assert len(x) == 1 and x[0]["cand"]["strict"], x
    print("selftest ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.market:
        selftest()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    res = run(a.market)
    (OUT / f"{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"→ {OUT / (a.market + '.json')}")


if __name__ == "__main__":
    main()
