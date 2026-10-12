#!/usr/bin/env python3
"""HTF 投資人口徑：由 investor_<mk>_series.json.gz 算每筆 10%／20%／33% 與「港台日美共用一筆資金」組合。2026-10-12
輸出 research/htf_curvefit/investor_mix.json。"""
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "research" / "htf_curvefit"
MKS = ["hk", "tw", "jp", "us"]   # 美股 2026-10-12 使用者要求加入


def stats(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = eq / eq.cummax() - 1
    m = r.resample("ME").apply(lambda g: (1 + g).prod() - 1)
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "mdd": float(dd.min()), "cum": float(eq.iloc[-1] - 1),
            "vol": float(r.std() * np.sqrt(252)), "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else None,
            "months_pos": float((m > 0).mean()),
            "by_year": {int(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}, "start": str(r.index[0].date())}


S = {}
for mk in MKS:
    with gzip.open(OUT / f"investor_{mk}_series.json.gz", "rt", encoding="utf-8") as f:
        d = json.load(f)
    idx = pd.to_datetime(d["dates"])
    S[mk] = pd.DataFrame({"num": d["num"], "den": d["den"], "a": d["a"], "etf": d["etf"]}, index=idx)

res = {}
for base in (0.10, 0.20, 0.33):
    key = f"{int(round(base * 100))}%"
    res[key] = {}
    for mk in MKS:
        df = S[mk]
        expo = base * df["den"]
        sc = np.where(expo > 1, 1 / expo.clip(lower=1e-12), 1.0)
        r = base * df["num"] * sc
        st = stats(r)
        st["avg_exposure"] = float(np.minimum(expo, 1).mean())
        res[key][mk] = st
    # 三市場共用一筆資金（2010-07 起，三地都有數據）
    start = max(S[mk].index[0] for mk in MKS)
    allidx = sorted(set().union(*[S[mk].index[S[mk].index >= start] for mk in MKS]))
    num = sum(S[mk]["num"].reindex(allidx).fillna(0) for mk in MKS)
    den = sum(S[mk]["den"].reindex(allidx).fillna(0) for mk in MKS)
    expo = base * den
    sc = np.where(expo > 1, 1 / expo.clip(lower=1e-12), 1.0)
    r = base * num * sc
    st = stats(r)
    st["avg_exposure"] = float(np.minimum(expo, 1).mean())
    res[key]["combined"] = st
res["backtest_A"] = {mk: stats(S[mk]["a"]) for mk in MKS}
res["etf"] = {mk: stats(S[mk]["etf"]) for mk in MKS}
(OUT / "investor_mix.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
for k in ("10%", "20%", "33%"):
    print(k, {mk: f"{v['cagr']:+.1%}/{v['mdd']:.0%}/曝{v['avg_exposure']:.0%}/夏普{v['sharpe']:.2f}" for mk, v in res[k].items()})
print("A", {mk: f"{v['cagr']:+.1%}/{v['mdd']:.0%}" for mk, v in res["backtest_A"].items()})
print("ETF", {mk: f"{v['cagr']:+.1%}/{v['mdd']:.0%}/夏普{v['sharpe']:.2f}" for mk, v in res["etf"].items()})
