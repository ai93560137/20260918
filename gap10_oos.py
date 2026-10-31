#!/usr/bin/env python3
"""跳空 ≥ 10% 大跌——歷史樣本外（stock_research/GAP10_OOS_PREREG.md；登記 commit 83b3ff66 之後寫）。

    python3 scripts/get_market_data.py --market us   # 先下載 data_full/us（Release fullmarket-data）
    python3 gap10_oos.py                             # → research/gap10_oos/us_ex_sp500.json

宇宙＝美股全市場剔除曾經 S&P 500 成分股（連改名新代號）、指數同 SPY；事件、分組、BS 損益同 bigdrop_options／gapdrop_options 一樣。
"""
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import options_equity as oe  # noqa: E402
from bigdrop_options import H, breakeven, pnl, ratio_stats, ret_stats, rv  # noqa: E402
from newhigh_backtest import load_full  # noqa: E402

OUT = ROOT / "research" / "gap10_oos"
START = date(1996, 1, 2)
COST = 0.005            # 0.5 波動點（同美股）
LIQ = {"none": 0.0, "10M": 1e7, "50M": 5e7}
MAIN_LIQ = "10M"
D0 = date(1990, 1, 1).toordinal()


def excluded() -> set[str]:
    ex = {"SPY"}
    with open(ROOT / "universes" / "sp500" / "membership.csv", newline="", encoding="utf-8") as f:
        ex |= {r["ticker"] for r in csv.DictReader(f)}
    p = ROOT / "universes" / "us" / "renames.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ex |= {r["old"], r["new"]}
    return {t.replace(".", "-") for t in ex} | ex


def month_t(ev, x) -> tuple[float, float]:
    by: dict[tuple, list] = {}
    for e, v in zip(ev, x):
        if v == v:
            by.setdefault((e["d"].year, e["d"].month), []).append(v)
    m = np.array([np.mean(v) for v in by.values()])
    if len(m) < 3:
        return float("nan"), float("nan")
    return float(m.mean()), float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def diff_t(a, b, key) -> dict:
    def bym(ev):
        m: dict[tuple, list] = {}
        for e in ev:
            if e[key] == e[key]:
                m.setdefault((e["d"].year, e["d"].month), []).append(e[key])
        return {k: float(np.mean(v)) for k, v in m.items()}
    ma, mb = bym(a), bym(b)
    d = np.array([ma[k] - mb[k] for k in ma if k in mb])
    if len(d) < 3:
        return dict(months=len(d), diff=float("nan"), t=float("nan"))
    return dict(months=len(d), diff=float(d.mean()), t=float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))))


def summ(ev: list[dict]) -> dict:
    if len(ev) < 10:
        return dict(n=len(ev))
    p1 = pnl(ev, [("p", 0.95)], 1.0, COST) * 100
    for e, v in zip(ev, p1):
        e["p1"] = float(v)
    b = breakeven(ev, [("p", 0.95)], COST)
    mu, t = month_t(ev, [e["ex21"] for e in ev])
    return dict(n=len(ev), put_rho_star=b["rho_star"], put_rho2=b["rho2"], put_pnl_rho1_mean=float(p1.mean()),
                put_win_rho1=float((p1 > 0).mean()), ex21_pct=mu * 100 if mu == mu else None, ex21_t=t,
                ratio=ratio_stats(ev), ret21=ret_stats(ev))


def compare(ev: list[dict], gthr: float) -> dict:
    g10 = [e for e in ev if e["gap"] >= gthr]
    g0 = [e for e in ev if e["gap"] < gthr]
    a, b = summ(g10), summ(g0)
    out = dict(G10=a, G0=b)
    if a.get("put_rho_star") is not None and b.get("put_rho_star") is not None:
        out["rho_star_diff"] = a["put_rho_star"] - b["put_rho_star"]
    if len(g10) >= 10 and len(g0) >= 10:
        out["D_pnl_rho1"] = diff_t(g10, g0, "p1")
    return out


def run() -> dict:
    base = ROOT / "data_full" / "us"
    if not base.exists():
        raise SystemExit("冇 data_full/us：先跑 python3 scripts/get_market_data.py --market us")
    loader = load_full("us")
    ex = excluded()
    tickers = sorted(p.name[:-7] for p in base.glob("*.csv.gz") if not p.name.startswith("_"))
    irx = oe.read_series("IRX")
    irk = sorted(irx)
    nd = date(2027, 1, 1).toordinal() - D0
    bsum = {k: np.zeros(nd) for k in LIQ}
    bcnt = {k: np.zeros(nd) for k in LIQ}
    events, used, skipped = [], 0, 0
    for t in tickers:
        if t in ex or t.startswith("_"):
            skipped += 1
            continue
        try:
            rows = loader(t)
        except FileNotFoundError:
            continue
        if len(rows) < 400:
            continue
        df = pd.DataFrame(rows)
        df = df[(df["AdjClose"] > 0) & (df["Close"] > 0)]
        f = (df["AdjClose"] / df["Close"]).to_numpy()
        adj = df["AdjClose"].to_numpy(float)
        cl = df["Close"].to_numpy(float)
        op = df["Open"].to_numpy(float) * f
        lo = df["Low"].to_numpy(float) * f
        dv = (df["Close"] * df["Volume"]).rolling(63, min_periods=40).median().shift(1).to_numpy()
        dates = list(df["Date"])
        ords = np.array([d.toordinal() - D0 for d in dates])
        n = len(adj)
        used += 1
        # 基準：同日宇宙等權 21 日前向報酬（同樣過濾）
        fw = np.full(n, np.nan)
        fw[:-H] = adj[H:] / adj[:-H] - 1
        r1 = np.full(n, np.nan)
        r1[1:] = adj[1:] / adj[:-1] - 1
        base_ok = (cl >= 5) & ~np.isnan(fw) & (np.array([d >= START for d in dates]))
        for k, thr in LIQ.items():
            ok = base_ok & ((dv >= thr) if thr > 0 else True) & ~(np.isnan(dv) & (thr > 0))
            np.add.at(bsum[k], ords[ok], fw[ok])
            np.add.at(bcnt[k], ords[ok], 1)
        last = -10 ** 9
        for i in np.nonzero(r1 <= -0.08)[0]:
            if i - last < H or i < 315 or i + H >= n or dates[i] < START:
                continue
            if r1[i] < -0.60 or not (cl[i] >= 5):
                continue
            if np.isnan(op[i]) or np.isnan(lo[i - 1]) or op[i] <= 0:
                continue
            rv63, rvf = rv(adj[i - 64:i]), rv(adj[i:i + H + 1])
            if not (rv63 > 0) or math.isnan(rvf):
                continue
            ret = adj[i + H] / adj[i] - 1
            gap = lo[i - 1] / op[i] - 1 if op[i] < lo[i - 1] else 0.0
            events.append(dict(t=t, d=dates[i], o=int(ords[i]), drop=float(r1[i]), gap=float(gap), liq=float(dv[i]) if dv[i] == dv[i] else 0.0,
                               S0=float(cl[i]), S1=float(cl[i] * (1 + ret)), ret=float(ret), rv63=rv63, rvf=rvf,
                               r=(oe.asof(irx, irk, dates[i]) or 0) / 100, q=0.0))
            last = i
    res = dict(prereg_commit="83b3ff66", tickers_files=len(tickers), excluded_sp500_or_index=skipped, used=used,
               raw_events=len(events), grid={})

    def with_ex(evs, k):
        out = []
        for e in evs:
            c = bcnt[k][e["o"]]
            e2 = dict(e)
            e2["ex21"] = e["ret"] - bsum[k][e["o"]] / c if c > 0 else float("nan")
            out.append(e2)
        return out

    def subset(k, thr=-0.08):
        return with_ex([e for e in events if e["liq"] >= LIQ[k] and e["drop"] <= thr], k)

    main = subset(MAIN_LIQ)
    res["main"] = compare(main, 0.10)
    res["main"]["n"] = len(main)
    res["splits"] = {lab: compare([e for e in main if a <= e["d"] <= b], 0.10)
                     for lab, a, b in (("1996–2012", date(1996, 1, 1), date(2012, 12, 31)),
                                       ("2013–2026", date(2013, 1, 1), date(2026, 12, 31)))}
    res["sens"] = {f"liq_{k}": compare(subset(k), 0.10) for k in ("none", "50M")}
    res["sens"].update({f"gap{int(g * 100)}": compare(main, g) for g in (0.05, 0.15)})
    res["sens"]["drop-10"] = compare(subset(MAIN_LIQ, -0.10), 0.10)
    d = res["main"]
    rd, Dt = d.get("rho_star_diff"), (d.get("D_pnl_rho1") or {}).get("t")
    if rd is not None and Dt is not None and rd >= 0.07 and Dt <= -2:
        v = "✅ 樣本外重現"
    elif rd is not None and rd <= 0:
        v = "☠️ 唔重現"
    else:
        v = "不確定"
    res["verdict"] = dict(verdict=v, rho_star_diff=rd, D_t=Dt)
    return res


def show(res: dict) -> None:
    f = lambda x, n=2: "—" if x is None or x != x else f"{x:.{n}f}"  # noqa: E731
    print(f"檔 {res['tickers_files']}、剔除 S&P／指數 {res['excluded_sp500_or_index']}、用 {res['used']}、原始事件 {res['raw_events']}")

    def line(lab, c):
        a, b = c["G10"], c["G0"]
        D = c.get("D_pnl_rho1") or {}
        print(f"{lab:>12}: G10 n={a.get('n')} ρ*={f(a.get('put_rho_star'))} ρ₂={a.get('put_rho2')} p@1={f(a.get('put_pnl_rho1_mean'))}% "
              f"RVrms={f((a.get('ratio') or {}).get('rms_ratio'))} ex21={f(a.get('ex21_pct'))} | G0 n={b.get('n')} ρ*={f(b.get('put_rho_star'))} "
              f"ρ₂={b.get('put_rho2')} p@1={f(b.get('put_pnl_rho1_mean'))}% RVrms={f((b.get('ratio') or {}).get('rms_ratio'))} ex21={f(b.get('ex21_pct'))} "
              f"| Δρ*={f(c.get('rho_star_diff'))} D={f(D.get('diff'))} t={f(D.get('t'))}")
    line("主（10M）", res["main"])
    for k, c in res["splits"].items():
        line(k, c)
    for k, c in res["sens"].items():
        line(k, c)
    print("判決：", res["verdict"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res = run()
    (OUT / "us_ex_sp500.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    show(res)


if __name__ == "__main__":
    main()
