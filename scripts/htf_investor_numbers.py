#!/usr/bin/env python3
"""HTF 全期參數 投資人口徑數字（港台日）。2026-10-12

兩個口徑：
  A 回測口徑（全倉輪動）：htf_backtest.daily()——當天所有持倉按單位等分 100% 資金（只有一筆時全壓一隻）。
  B 可執行口徑：每筆基本 10% 資金 × 波幅權重（風險倉位版 w = 0.05/ADR，截在 0.25–4 倍；等權版 w = 1），
    總曝險上限 100%（超過就按比例縮），其餘現金（不計利息）。成本同回測。
輸出 research/htf_curvefit/investor_<mk>.json：年化、累計、最大回撤、按年、ETF 同期、RRR、勝率、期望值、獲利因子、筆數、持有。
    python3 scripts/htf_investor_numbers.py hk
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import htf_curvefit as C  # noqa: E402

BASE = 0.10


def path_stats(daily: np.ndarray, cal, start_j: int) -> dict:
    r = pd.Series(daily[start_j:], index=pd.to_datetime(cal[start_j:]))
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "cum": float(eq.iloc[-1] - 1),
            "mdd": float((eq / eq.cummax() - 1).min()),
            "by_year": {int(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}}


def main(mk: str) -> None:
    best = json.loads((C.OUT / f"{mk}.json").read_text(encoding="utf-8"))["search"]["best"]
    x = C.CF(mk)
    m = x.m
    tr = x.ctrades(best)
    ev = x.evaluate(tr, best["risk"])
    ratio, _, den = x.daily(tr, best["risk"])
    num = ratio * den                                  # 每日 Σ（權重 × 報酬）
    expo = BASE * den                                  # 每日曝險（佔資金）
    scale = np.where(expo > 1.0, 1.0 / np.maximum(expo, 1e-12), 1.0)
    daily_b = BASE * num * scale
    A = path_stats(ratio, m.cal, m.start_j)
    B = path_stats(daily_b, m.cal, m.start_j)
    E = path_stats(m.etf_ret, m.cal, m.start_j)
    out = {"market": mk, "params": best, "period": ev["period"], "trades": ev["trades"], "win": ev["win"], "rrr": ev["rrr"],
           "avg_win": ev["avg_win"], "avg_loss": ev["avg_loss"], "expectancy": ev["expectancy"], "profit_factor": ev["profit_factor"],
           "avg_hold": ev["avg_hold"], "alpha_t": ev["alpha_t"], "top10_share": ev["top10_share"],
           "A_backtest": A, "B_executable": B, "etf": E,
           "B_avg_exposure": float(np.minimum(expo[m.start_j:], 1.0).mean()), "B_max_exposure_capped_days": int((expo[m.start_j:] > 1).sum())}
    import gzip
    ser = {"dates": [d.isoformat() for d in m.cal[m.start_j:]], "num": num[m.start_j:].tolist(), "den": den[m.start_j:].tolist(),
           "a": ratio[m.start_j:].tolist(), "etf": m.etf_ret[m.start_j:].tolist()}
    with gzip.open(C.OUT / f"investor_{mk}_series.json.gz", "wt", encoding="utf-8") as f:
        json.dump(ser, f)
    (C.OUT / f"investor_{mk}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    print(f"[{mk}] A 年化 {A['cagr']:+.1%} MDD {A['mdd']:.0%}｜B 年化 {B['cagr']:+.1%} MDD {B['mdd']:.0%} 平均曝險 {out['B_avg_exposure']:.0%}｜"
          f"ETF {E['cagr']:+.1%} MDD {E['mdd']:.0%}｜RRR {ev['rrr']:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
