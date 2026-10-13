#!/usr/bin/env python3
# =============================================================================
# 金絲雀 📐 後驗的歷史期望值 — 給每週偏離監控(research/divergence/)當「回測期望」
# -----------------------------------------------------------------------------
# 口徑與 daily_report.py 的 📐 後驗逐字相同(spx_fwd5):
#   ratio = 燈色日 D 之後 5 個 SPX 交易日的實現波動(5 個對數報酬的樣本標準差 ×√252×100)
#           ÷ D 之前 252 個「完全在 D 以前結束」的 5 日 RV 的中位數
#   down2 = 其後 5 個交易日有無 −2% 單日
# 分組(按燈色日 D 的正式燈,先到先得):
#   深紅 = 災難軸深紅;紅 = 短期軸紅;黃 = 兩軸不紅、黃燈亮;綠 = 兩軸綠或走平、黃燈滅;其餘(空白列)不計
# 樣本:VIX9D 起(2011-01-03)到 D+5 齊的最後一天。輸出 canary/POSTHOC_EXPECT.md 與 --json 指定的檔。
#
# 用法:
#   python3 canary/posthoc_expect.py                       # 印表並寫 POSTHOC_EXPECT.md
#   python3 canary/posthoc_expect.py --json out.json       # 另寫 JSON(登記到 expectations.json 用)
# =============================================================================
import argparse
import csv
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from daily_report import fwd5_from_series, load_close, SPX_FILE  # noqa: E402

TABLE = os.path.join(HERE, "canary_daily.csv")
OUT_MD = os.path.join(HERE, "POSTHOC_EXPECT.md")
START = "2011-01-03"
STATES = ["綠", "黃", "紅", "深紅"]


def state_of(row):
    """燈色日的正式燈 → 分組;空白列回 None。"""
    a_s, a_d, y = row.get("axis_short", ""), row.get("axis_disaster", ""), row.get("yellow", "")
    if a_d == "深紅":
        return "深紅"
    if a_s == "紅":
        return "紅"
    if a_s == "" or a_d == "":
        return None
    if y == "1":
        return "黃"
    if y == "0":
        return "綠"
    return None


def compute(table=TABLE, spx=SPX_FILE, start=START):
    ser = load_close(spx)
    ds = [d.isoformat() for d, _ in ser]
    px = [v for _, v in ser]
    rows = [r for r in csv.DictReader(open(table, encoding="utf-8")) if r["date"] >= start]
    groups = {s: [] for s in STATES}
    first = last = None
    for r in rows:
        st = state_of(r)
        if st is None:
            continue
        ph = fwd5_from_series(ds, px, r["date"])
        if ph is None or not ph["median"]:
            continue
        groups[st].append((ph["rv"] / ph["median"], ph["down2"]))
        first = first or r["date"]
        last = r["date"]
    out = {"sample": f"{first} → {last}", "groups": {}}
    for s in STATES:
        g = groups[s]
        ratios = [x for x, _ in g]
        if len(ratios) < 2:
            out["groups"][s] = {"n": len(ratios)}
            continue
        out["groups"][s] = {
            "n": len(ratios),
            "mean": round(statistics.fmean(ratios), 4),
            "std": round(statistics.stdev(ratios), 4),
            "median": round(statistics.median(ratios), 4),
            "down2_rate": round(sum(1 for _, d in g if d) / len(g), 4),
        }
    return out


def main():
    ap = argparse.ArgumentParser(description="金絲雀 📐 後驗的歷史期望值")
    ap.add_argument("--json", default=None, help="另寫 JSON 到此路徑")
    a = ap.parse_args()
    res = compute()
    md = ["# 金絲雀 📐 後驗的歷史期望值", "",
          f"樣本 {res['sample']}(每個燈色日一列,按當日正式燈分組)。口徑與每日 📐 後驗相同:",
          "其後 5 個 SPX 交易日實現波動 ÷ 燈色日之前 252 個(完全在燈色日以前結束的)5 日 RV 中位;"
          "−2% 單日 = 其後 5 日有無單日跌 2% 以上。", "",
          "| 燈 | 日數 | 倍率平均 | 標準差 | 倍率中位 | −2% 單日比例 |", "|---|---:|---:|---:|---:|---:|"]
    for s in STATES:
        g = res["groups"][s]
        if "mean" not in g:
            md.append(f"| {s} | {g['n']} | — | — | — | — |")
            continue
        md.append(f"| {s} | {g['n']} | {g['mean']:.2f} | {g['std']:.2f} | {g['median']:.2f} | {g['down2_rate']:.1%} |")
    md += ["", "每週偏離監控(`research/divergence/DIVERGENCE.md`)拿 `canary/posthoc_log.csv` 的前向紀錄逐組對比這張表;"
           "門檻與燈號規則寫在 `scripts/strategy_divergence.py` 的金絲雀段。", ""]
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print("\n".join(md))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
