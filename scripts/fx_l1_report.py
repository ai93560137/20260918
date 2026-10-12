#!/usr/bin/env python3
"""L1 前向測試狀態報告：讀 forex_research/forward/l1_paper.csv → L1_STATUS.md。規則：FX_L1_FORWARD.md。"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST_MEAN, HIST_SD = 1.88, 20.4          # 2003-08 → 2026-08 毛均值與日標準差（基點）
HIST_P5_500 = 0.11                       # 歷史滾動 500 日毛均值第 5 百分位（基點）
HIST_P5_250 = -0.33                      # 歷史滾動 250 日毛均值第 5 百分位


def main() -> None:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "forex_research" / "forward"
    df = pd.read_csv(d / "l1_paper.csv", parse_dates=["date"])
    ok = df[df.status == "ok"].copy()
    n = len(ok)
    L = ["# L1 前向測試狀態（自動產生，scripts/fx_l1_report.py）", "",
         "規則：EURUSD 每個平日 09:00 UTC 賣出、12:00 UTC 買回。記錄 = Dukascopy M1 bid／ask 紙上成交（賣 bid、買 ask）。監測規則見 `FX_L1_FORWARD.md`。", ""]
    if n == 0:
        L += ["尚無有效記錄。"]
        (d / "L1_STATUS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        print("尚無有效記錄")
        return
    g, p, net = ok.l1_mid_bp.astype(float), ok.l1_paper_bp.astype(float), ok.l1_net_bp.astype(float)
    t = lambda x: float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")
    z = (g.mean() - HIST_MEAN) / (HIST_SD / math.sqrt(n))
    miss = int((df.status != "ok").sum())
    L += [f"- 起 {ok.date.min().date()}、到 {ok.date.max().date()}；有效 **{n}** 個交易日（缺價 {miss} 日）",
          f"- 毛均值（中價）**{g.mean():+.2f}** 基點／日（歷史 +{HIST_MEAN}）、t {t(g):+.2f}、勝率 {(g > 0).mean() * 100:.0f}%",
          f"- 紙上成交（賣 bid、買 ask）{p.mean():+.2f} 基點／日；扣佣金 0.4 基點後 **淨 {net.mean():+.2f}** 基點／日、淨 t {t(net):+.2f}；累計淨 {net.sum():+.1f} 基點",
          f"- 實測點差：09:00 平均 {ok.spread_09_bp.astype(float).mean():.2f} 基點、12:00 平均 {ok.spread_12_bp.astype(float).mean():.2f} 基點（回測假設各端約 0.17–0.3 基點）",
          f"- 與歷史一致性：前向均值相對歷史均值的 z = {z:+.2f}（|z| < 2 視為與歷史一致；樣本天數少時該指標很寬）",
          f"- 單日最差 {g.min():+.1f} 基點、最好 {g.max():+.1f} 基點", ""]
    L += ["## 監測規則進度", "",
          "| 里程碑 | 條件 | 現況 |", "|---|---|---|"]
    st250 = "未到" if n < 250 else (f"滾動 250 日毛均值 {g.tail(250).mean():+.2f}；{'✔ ≥ ' + str(HIST_P5_250) if g.tail(250).mean() >= HIST_P5_250 else '✘ 低於歷史第 5 百分位，需檢討'}")
    st500 = "未到" if n < 500 else (f"滾動 500 日毛均值 {g.tail(500).mean():+.2f}、淨 {net.tail(500).mean():+.2f}；{'繼續' if g.tail(500).mean() >= HIST_P5_500 and net.tail(500).mean() > 0 else '停止（衰退）'}")
    st1000 = "未到" if n < 1000 else (f"毛 t {t(g):+.2f}；{'✔ 前向確認' if t(g) >= 2 else '✘ 未達 2'}")
    L += [f"| 250 日 | 滾動 250 日毛均值 ≥ {HIST_P5_250}（歷史第 5 百分位）| 目前 {n}/250 日：{st250} |",
          f"| 500 日 | 滾動 500 日毛均值 ≥ {HIST_P5_500} 且淨 > 0，否則停 | 目前 {n}/500 日：{st500} |",
          f"| 1,000 日 | 毛 t ≥ 2 才稱前向確認 | 目前 {n}/1000 日：{st1000} |", ""]
    if n >= 20:
        L += [f"- 滾動 20 日毛均值 {g.tail(20).mean():+.2f}、滾動 60 日 {g.tail(60).mean():+.2f}（60 日不足則取全部）", ""]
    L += ["## 最近 10 個交易日", "", "| 日期 | 毛（基點） | 紙上 | 淨 | 點差 09/12 |", "|---|---:|---:|---:|---|"]
    for r in ok.tail(10).itertuples():
        L.append(f"| {r.date.date()} | {float(r.l1_mid_bp):+.2f} | {float(r.l1_paper_bp):+.2f} | {float(r.l1_net_bp):+.2f} | {float(r.spread_09_bp):.2f}/{float(r.spread_12_bp):.2f} |")
    (d / "L1_STATUS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
