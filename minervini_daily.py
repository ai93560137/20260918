#!/usr/bin/env python3
"""Minervini 忠實版每日觀察名單（全市場前 N；stock_research/FULLMARKET_DAILY_PIPELINE.md）。描述性，不是買入建議。

    python3 minervini_daily.py --market hk          # → analysis/minervini/<收市日>_hk.csv

名單 = 最新收市日（t−1）：趨勢模板（含 RS≥70）＋ VCP 形態成立（r=0.8、D=10%）＋ 收市未過樞紐點 ＋ 大市 ETF > 50／200 日線。
按規格明日（t）：盤中最高 > 樞紐點才買，成交價 max(開市, 樞紐點)；開市 > 樞紐點 × 1.05 不買；
止損 成交價 × 0.925；收市 ≥ 成交價 × 1.15 後止損移到成本；收市跌破 50 日線下一日開市出（vcp_minervini.py）。
"""
import argparse
import csv
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import vcp  # noqa: E402
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402

OUT = ROOT / "analysis" / "minervini"
FIELDS = ["date", "market", "ticker", "close", "pivot", "pct_to_pivot", "buy_limit", "stop_at_pivot",
          "n_contractions", "depths_pct", "market_filter"]


def scan(mk: str) -> tuple[list[dict], str, bool]:
    v = vb.VCPData(mk, full=True, scan=False)
    m = v.m
    lvl = pd.Series(np.cumprod(1 + m.etf_ret))
    mkt_ok = ((lvl > lvl.rolling(50).mean()) & (lvl > lvl.rolling(200).mean())).to_numpy()
    j = len(m.cal) - 1
    d = m.cal[j]
    rows = []
    for s_i, rw in v.raw.items():
        p = rw["dates"].get(d)
        if p is None or p < vcp.BASE_LOOKBACK + 1 or not v.tt[s_i, j]:
            continue
        info = vcp.base_info(rw["high"], rw["low"], rw["vol"], rw["alow"], p)
        if not vcp.passes(info) or rw["close"][p] > info["pivot"]:
            continue
        pv, c = info["pivot"], rw["close"][p]
        rows.append({"date": d.isoformat(), "market": mk, "ticker": m.tickers[s_i], "close": f"{c:.6g}",
                     "pivot": f"{pv:.6g}", "pct_to_pivot": f"{(pv / c - 1) * 100:.1f}",
                     "buy_limit": f"{pv * (1 + vm.DEFAULT[1]):.6g}", "stop_at_pivot": f"{pv * (1 - vm.DEFAULT[0]):.6g}",
                     "n_contractions": info["n_t"], "depths_pct": "/".join(f"{x * 100:.0f}" for x in info["depths"]),
                     "market_filter": "成立" if mkt_ok[j] else "不成立"})
    rows.sort(key=lambda r: float(r["pct_to_pivot"]))
    return rows, d.isoformat(), bool(mkt_ok[j])


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", required=True, choices=list(vb.FULL_TOP_N))
    args = a.parse_args()
    rows, d, ok = scan(args.market)
    OUT.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (OUT / f"{d}_{args.market}.csv").write_text(buf.getvalue(), encoding="utf-8")
    print(f"[{args.market}] {d} 收市：觀察名單 {len(rows)} 檔；大市過濾 {'成立' if ok else '不成立（按規格明日不買）'}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
