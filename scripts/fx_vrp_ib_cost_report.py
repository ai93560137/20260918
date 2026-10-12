#!/usr/bin/env python3
"""A 階段報告：6E ATM 跨式半價差（波動點）。登記：forex_research/FX_EUR_VRP_IBKR.md。

    python3 scripts/fx_vrp_ib_cost_report.py [data_forex_ibkr/vrp_snapshots.csv] [--out forex_research/fx_eur_vrp/IBKR_A_STATUS.md]

判讀（寫死）：樣本 ≥ 15 個有效快照日，中位數 ĉ ≤ 0.35 成立；0.35–0.60 邊際；> 0.60 成本否決；無報價日 > 30% 同樣否決。
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def verdict(c_med: float, n_valid: int, missing_share: float) -> str:
    if n_valid < 15:
        return f"樣本不足（{n_valid}/15 個有效快照日），尚無判讀"
    if missing_share > 0.30:
        return f"**成本否決**（無報價日 {missing_share:.0%} > 30%，流動性不足）"
    if c_med <= 0.35:
        return "成本假設成立（c=0.5 含對沖成本）→ 可進 B 階段"
    if c_med <= 0.60:
        return "邊際 → 進 B 階段，B 的目標改為淨損益 > 0.2 波動點／期"
    return "**成本否決**（ĉ > 0.60）→ 路線改判 ☠️（執行面），B 階段不開"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=str(ROOT / "data_forex_ibkr" / "vrp_snapshots.csv"))
    ap.add_argument("--out", default=str(ROOT / "forex_research" / "fx_eur_vrp" / "IBKR_A_STATUS.md"))
    args = ap.parse_args()
    f = Path(args.csv)
    if not f.exists():
        print("尚無快照檔", f)
        sys.exit(0)
    d = pd.read_csv(f)
    d = d[d["kind"] == "scan"].copy()
    d["date"] = d["utc_time"].str[:10]
    d["half"] = pd.to_numeric(d["half_spread_vol"], errors="coerce")
    d["iv_half"] = (pd.to_numeric(d["c_ask_iv"], errors="coerce") - pd.to_numeric(d["c_bid_iv"], errors="coerce") +
                    pd.to_numeric(d["p_ask_iv"], errors="coerce") - pd.to_numeric(d["p_bid_iv"], errors="coerce")) / 4 * 100
    d["fut_half_tick"] = (pd.to_numeric(d["fut_ask"], errors="coerce") - pd.to_numeric(d["fut_bid"], errors="coerce")) / 2 / 0.00005
    day = d.groupby("date").agg(half=("half", "median"), iv_half=("iv_half", "median"), fut_half_tick=("fut_half_tick", "median"),
                                dte=("dte", "first"), strike=("strike", "first"))
    n_all, n_ok = len(day), int(day["half"].notna().sum())
    miss = 1 - n_ok / n_all if n_all else 1.0
    c_med = float(day["half"].median()) if n_ok else float("nan")
    lines = ["# IBKR 6E 期權 A 階段狀態（自動產生，scripts/fx_vrp_ib_cost_report.py）", "",
             f"- 快照日 {n_all}，有完整報價 {n_ok}（缺 {miss:.0%}）；{day.index.min() if n_all else ''} → {day.index.max() if n_all else ''}",
             f"- 跨式半價差 ĉ：中位數 **{c_med:.3f}** 波動點，平均 {day['half'].mean():.3f}，第 25／75 百分位 {day['half'].quantile(.25):.3f}／{day['half'].quantile(.75):.3f}，最大 {day['half'].max():.3f}",
             f"- 由 bid／ask 隱含波動對照的半價差（中位）：{day['iv_half'].median():.3f}",
             f"- 標的期貨半價差（中位）：{day['fut_half_tick'].median():.2f} tick（1 tick = 0.00005）",
             f"- **判讀**：{verdict(c_med, n_ok, miss)}", "",
             "## 逐日", "", "| 日期 | DTE | 行使價 | 半價差（波動點） | IV 對照 | 期貨半價差（tick） |", "|---|---:|---:|---:|---:|---:|"]
    for dt, r in day.tail(30).iterrows():
        lines.append(f"| {dt} | {r['dte']} | {r['strike']} | {r['half']:.3f} | {r['iv_half']:.3f} | {r['fut_half_tick']:.1f} |")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:9]))


if __name__ == "__main__":
    main()
