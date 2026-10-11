#!/usr/bin/env python3
"""蛇蟠陣 USDJPY：把既有逐筆交易（1.0 pip 零佣金 CFD）重算成 IBKR 成本。登記：forex_research/SNAKE_COIL_USDJPY_IBKR.md。

    python3 scripts/snake_recost_ibkr.py --out forex_research/snake_coil/ibkr_recost

新損益（JPY）= 原損益 + 0.010 − spread_y × 0.01 − 進場價 × 2 × commission_bp × 1e-4 + swap_JPY
swap_JPY = 進場價 × [dir × (r_usd − r_jpy) − markup] / 100 / 365 × 持倉日曆日；利率 FRED 三個月同業拆息，延後一個月。
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from fx_basket_backtest import load_rates  # noqa: E402
from snake_coil_eval import load, summarize  # noqa: E402

PIP = 0.01
SPREAD_Y = {2003: 2.0, 2004: 2.0, 2005: 2.0, 2006: 2.0, 2007: 1.5, 2008: 1.0, 2009: 1.0, 2010: 1.0, 2011: 1.2, 2012: 0.7, 2013: 0.6, 2014: 0.3,
            2015: 0.4, 2016: 0.4, 2017: 0.3, 2018: 0.3, 2019: 0.3, 2020: 0.3, 2021: 0.3, 2022: 0.7, 2023: 0.6, 2024: 0.6, 2025: 0.6, 2026: 0.5}


def spread_of(year: int, flat: float | None) -> float:
    if flat is not None:
        return flat
    return SPREAD_Y[max(year, 2003)]


def recost(rows: list[dict], rates: pd.DataFrame, flat: float | None, comm_bp: float, markup: float | None, slip: float = 0.0):
    out = []
    parts = {"spread": 0.0, "commission": 0.0, "swap": 0.0, "slip": 0.0}
    for r in rows:
        ot = pd.Timestamp(r["open_time"][:19])
        ct = pd.Timestamp(r["close_time"][:19])
        entry = float(r["entry"])
        sp = spread_of(ct.year, flat) * PIP
        comm = entry * 2 * comm_bp * 1e-4
        d_sp = 0.010 - sp
        sw = 0.0
        if markup is not None:
            ref = ot.to_period("M").start_time - pd.Timedelta(days=1)          # 進場月的前一個月底（延後一個月）
            ru, rj = float(rates["USD"].asof(ref)), float(rates["JPY"].asof(ref))
            days = (ct - ot).total_seconds() / 86400.0
            sw = entry * (r["direction"] * (ru - rj) - markup) / 100.0 / 365.0 * days
        new = dict(r)
        new["pnl"] = r["pnl"] + d_sp - comm + sw - slip * PIP
        out.append(new)
        parts["spread"] += d_sp
        parts["commission"] -= comm
        parts["swap"] += sw
        parts["slip"] -= slip * PIP
    return out, {k: round(v / PIP, 0) for k, v in parts.items()}


def stat_line(rows: list[dict]) -> dict:
    s = summarize(rows)
    a = summarize([r for r in rows if r["open_time"][:10] < "2013-01-01"])
    b = summarize([r for r in rows if r["open_time"][:10] >= "2013-01-01"])
    lg = summarize([r for r in rows if r["direction"] > 0])
    sh = summarize([r for r in rows if r["direction"] < 0])
    return {"n": s["n"], "total_pips": round(s["total"] / PIP), "t": round(s["t"], 2), "pf": round(s["pf"], 2), "win": round(s["win_rate"], 3),
            "top10": round(s["top10_share"], 2), "max_dd_pips": round(s["max_dd"] / PIP), "pos_years": f"{s['pos_years']}/{s['n_years']}",
            "t_to2012": round(a["t"], 2), "pips_to2012": round(a["total"] / PIP), "t_from2013": round(b["t"], 2), "pips_from2013": round(b["total"] / PIP),
            "t_long": round(lg["t"], 2), "pips_long": round(lg["total"] / PIP), "t_short": round(sh["t"], 2), "pips_short": round(sh["total"] / PIP),
            "worst_year": (s["worst_year"][0], round(s["worst_year"][1] / PIP)), "years": {k: round(v / PIP) for k, v in s["years"].items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    rates = load_rates(ROOT / "data_forex_rates", ["USD", "JPY"])
    res = {}
    scen = {  # 名稱: (flat 點差 或 None=逐年, 佣金每邊 bp, swap 加價 % 或 None=不計 swap, 滑點 pip)
        "MAIN": (None, 0.20, 1.25, 0.0),
        "A_flat0.65": (0.65, 0.20, 1.25, 0.0),
        "comm0.10": (None, 0.10, 1.25, 0.0), "comm0": (None, 0.0, 1.25, 0.0),
        "swap0.75": (None, 0.20, 0.75, 0.0), "swap0": (None, 0.20, 0.0, 0.0), "noswap": (None, 0.20, None, 0.0),
        "slip0.2": (None, 0.20, 1.25, 0.2), "slip0.4": (None, 0.20, 1.25, 0.4),
        "CFD_style(flat0.65,comm0,noswap)": (0.65, 0.0, None, 0.0),
    }
    for N in (3, 1, 2, 5):
        rows = load(str(ROOT / "forex_research" / "snake_coil" / f"USDJPY_sar_N{N}_sp0.01.csv"))
        res[f"N{N}"] = {"ORIGINAL_1.0pip": stat_line(rows)}
        for name, (flat, cb, mk, sl) in scen.items():
            if N != 3 and name not in ("MAIN", "A_flat0.65", "noswap"):
                continue
            new, parts = recost(rows, rates, flat, cb, mk, sl)
            st = stat_line(new)
            st["cost_effect_pips"] = parts
            res[f"N{N}"][name] = st
    args.out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{args.out}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for N, d in res.items():
        print(f"## {N}")
        for name, st in d.items():
            ce = f"  成本影響 pips {st['cost_effect_pips']}" if "cost_effect_pips" in st else ""
            print(f"  {name:34} n={st['n']} 總 {st['total_pips']:+,} pips t={st['t']} PF={st['pf']} 勝率 {st['win']} 前10 {st['top10']} 回撤 {st['max_dd_pips']} 正年 {st['pos_years']} "
                  f"｜≤2012 t {st['t_to2012']} ({st['pips_to2012']:+,}) ｜≥2013 t {st['t_from2013']} ({st['pips_from2013']:+,}) ｜多 t {st['t_long']} ({st['pips_long']:+,}) 空 t {st['t_short']} ({st['pips_short']:+,}){ce}")
    print("MAIN N=3 按年 pips：", res["N3"]["MAIN"]["years"])
    print("ORIGINAL N=3 按年 pips：", res["N3"]["ORIGINAL_1.0pip"]["years"])


if __name__ == "__main__":
    main()
