#!/usr/bin/env python3
"""已判決策略的期望值／RRR 描述性覆核（不改任何判決；使用者 2026-09-24 要求）。

    python3 scripts/expectancy_report.py --market hk      # → research/expectancy/hk.json

每個策略只取**已登記的預設格**（規格、成本、可疑剔除都跟原判決那一輪完全相同），重算逐筆與組合數字：
- 逐筆淨報酬（已扣來回成本）：勝率、平均賺、平均虧、RRR（平均賺 ÷ 平均虧）、期望值（每筆平均淨報酬）、
  獲利因子（總賺 ÷ 總虧）、平均持有日數
- 組合（日曆時間等權）：累計、年化、最大回撤；同期指數 ETF 累計／年化（參考）
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import aiba_ppp as ap  # noqa: E402
import newhigh_backtest as nb  # noqa: E402
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402


def load_sus(p: Path) -> set:
    return {tuple(x) for x in json.loads(p.read_text())} if p.exists() else set()


def stats(m, daily: np.ndarray, tr: list[float], holds: list[int]) -> dict:
    tr = np.array([x for x in tr if x == x])
    w, l_ = tr[tr > 0], tr[tr <= 0]
    d = daily[m.start_j:]
    eq = np.cumprod(1 + d)
    eqe = np.cumprod(1 + m.etf_ret[m.start_j:])
    yrs = len(d) / 252
    return {
        "trades": int(len(tr)), "win": float(len(w) / len(tr)) if len(tr) else math.nan,
        "avg_win": float(w.mean()) if len(w) else math.nan, "avg_loss": float(l_.mean()) if len(l_) else math.nan,
        "rrr": float(w.mean() / -l_.mean()) if len(w) and len(l_) and l_.mean() < 0 else math.nan,
        "expectancy": float(tr.mean()) if len(tr) else math.nan,
        "median_trade": float(np.median(tr)) if len(tr) else math.nan,
        "profit_factor": float(w.sum() / -l_.sum()) if len(l_) and l_.sum() < 0 else math.nan,
        "avg_hold": float(np.mean(holds)) if holds else math.nan,
        "cum": float(eq[-1] - 1), "cagr": float(eq[-1] ** (1 / yrs) - 1), "mdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
        "cum_etf": float(eqe[-1] - 1), "cagr_etf": float(eqe[-1] ** (1 / yrs) - 1),
        "period": f"{m.cal[m.start_j]}~{m.cal[-1]}",
    }


def from_trades(m, trades) -> dict:
    daily, tr, _ = m.portfolio(trades)
    return stats(m, daily, tr, [b - a for _, a, b, _ in trades])


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    mk = a.parse_args().market
    out = {}

    def put(name, st):
        out[name] = st
        print(f"{name:34} 筆數 {st['trades']:6d}  勝率 {st['win']:.0%}  平均賺 {st['avg_win']:+.2%}  平均虧 {st['avg_loss']:+.2%}  "
              f"RRR {st['rrr']:.2f}  期望值 {st['expectancy']:+.2%}  獲利因子 {st['profit_factor']:.2f}  持有 {st['avg_hold']:.0f} 日  "
              f"累計 {st['cum']:+.0%}（ETF {st['cum_etf']:+.0%}）  年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  "
              f"MDD {st['mdd']:.0%}", file=sys.stderr, flush=True)

    # 1. 新高連續天數（指數成分股；stock_research/NEWHIGH_BACKTEST.md 預設格，X2 反向突破出場）
    mi = nb.MarketData(mk)
    for kind in ("H4", "H5a", "H5b"):
        g = nb.GRIDS[kind]
        put(f"新高 {kind} {nb.label(kind, g['default'])}", from_trades(mi, mi.trades_from_events(mi.events(kind, g["default"]), "x2")))
    del mi
    # 2. VCP 指數成分股版 v2（stock_research/VCP_BACKTEST.md，XV 出場）
    vi = vb.VCPData(mk)
    put("VCP 指數版 v2 XV", from_trades(vi.m, vi.trades(vi.events(*vb.DEFAULT), "xv")))
    del vi
    # 3. 全市場：VCP XV／X5（剔除 vcp_full 可疑）、Minervini、PPP 下半身（剔除 aiba_ppp 可疑）
    sus_v = load_sus(ROOT / "research" / "vcp_full" / f"{mk}_suspect.json")
    vf = vb.VCPData(mk, full=True, exclude=sus_v)
    ev = vf.events(*vb.DEFAULT)
    put("VCP 全市場 XV", from_trades(vf.m, vf.trades(ev, "xv")))
    put("VCP 全市場 X5（五日 EMA）", from_trades(vf.m, vf.trades(ev, "x5")))
    mv = vm.Minervini(mk, sus_v, v=vf)
    trs = mv.trades(*vm.DEFAULT)
    daily, tr, _ = mv.daily(trs)
    put("VCP Minervini 忠實版", stats(vf.m, daily, tr, [x["b"] - x["a"] for x in trs]))
    pp = ap.AibaPPP(mk, m=vf.m)
    evp = pp.events(*ap.DEFAULT, load_sus(ROOT / "research" / "aiba_ppp" / f"{mk}_suspect.json"))
    put("PPP 下半身＋逆下半身出場", from_trades(vf.m, vf.m.trades_from_events(evp, ap.RULE)))
    pp.set_exit("ema5")
    put("PPP 下半身＋五日 EMA 出場", from_trades(vf.m, vf.m.trades_from_events(evp, ap.RULE)))
    p = ROOT / "research" / "expectancy"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{mk}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
