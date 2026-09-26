#!/usr/bin/env python3
"""鳥翔 × 烽燧：只記燈色、不改行為（第一期登記，見 RESEARCH_HANDBOOK.md §五 鳥翔 與 stock_research/TT_ALL_MONTHLY_RUNBOOK.md 第 3d 步）。2026-09-26

烽燧（金絲雀，雲垂分支 CANARY_PLAYBOOK.md §2）燈色定義：
  🔴 紅   = VIX9D − VIX > 0        🟣 深紅 = VIX − VIX3M > 0
  🟡 黃   = VVIX／MOVE／AXVI 任一 > 自身滾動 252 日第 90 百分位（不含當日）
  ⚪ 走平 = −0.5 < VIX9D−VIX ≤ 0    🟢 綠   = 以上皆無
口徑：lag=1，用「訊號日收盤」的燈（下一交易日開市執行前已知）。閾值固定，不調參。

用法：python3 scripts/tt_all_beacon.py [--date YYYY-MM-DD]（預設：各市場 *_latest.json 的訊號日，逐一記錄）
數據：tradingview/data_external/<bird>_daily.csv（本機有就用；沒有就 git show origin/claude/dazzling-curie-f3xzb8:...）
輸出：analysis/tt_all/beacon_log.csv（date,vix9d,vix,vix3m,vvix,move,axvi,red,deep_red,yellow,lamp,recorded_at）＋ 一行摘要到 stdout。
"""
import argparse
import csv
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "tt_all"
BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move", "axvi"]
REMOTE = "origin/claude/dazzling-curie-f3xzb8"
FIELDS = ["date", "vix9d", "vix", "vix3m", "vvix", "move", "axvi", "red", "deep_red", "yellow", "lamp", "recorded_at"]


def load_bird(name: str) -> dict[str, float]:
    p = ROOT / "tradingview" / "data_external" / f"{name}_daily.csv"
    if p.exists():
        txt = p.read_text(encoding="utf-8")
    else:
        txt = subprocess.run(["git", "show", f"{REMOTE}:tradingview/data_external/{name}_daily.csv"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    out = {}
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            out[r["Date"][:10]] = float(r["Close"])
        except (KeyError, ValueError):
            continue
    return out


def last_on_or_before(series: dict[str, float], d: str) -> tuple[str, float] | None:
    ks = [k for k in series if k <= d]
    if not ks:
        return None
    k = max(ks)
    return k, series[k]


def p90_before(series: dict[str, float], d: str, n: int = 252) -> float | None:
    ks = sorted(k for k in series if k < d)[-n:]
    if len(ks) < n // 2:
        return None
    v = sorted(series[k] for k in ks)
    return v[int(round(0.9 * (len(v) - 1)))]


def lamp_for(d: str, birds: dict[str, dict[str, float]]) -> dict:
    row = {"date": d}
    vals = {}
    for b in BIRDS:
        x = last_on_or_before(birds[b], d)
        vals[b] = x[1] if x and (datetime.fromisoformat(d) - datetime.fromisoformat(x[0])).days <= 5 else None
        row[b] = f"{vals[b]:.2f}" if vals[b] is not None else ""
    red = deep = None
    if vals["vix9d"] is not None and vals["vix"] is not None:
        red = vals["vix9d"] - vals["vix"]
    if vals["vix"] is not None and vals["vix3m"] is not None:
        deep = vals["vix"] - vals["vix3m"]
    yellow = []
    for b in ("vvix", "move", "axvi"):
        p = p90_before(birds[b], d)
        if vals[b] is not None and p is not None and vals[b] > p:
            yellow.append(b.upper())
    row["red"] = "1" if red is not None and red > 0 else "0" if red is not None else ""
    row["deep_red"] = "1" if deep is not None and deep > 0 else "0" if deep is not None else ""
    row["yellow"] = "+".join(yellow)
    if deep is not None and deep > 0:
        lamp = "🟣 深紅"
    elif red is not None and red > 0:
        lamp = "🔴 紅"
    elif yellow:
        lamp = "🟡 黃"
    elif red is not None and red > -0.5:
        lamp = "⚪ 走平"
    elif red is not None:
        lamp = "🟢 綠"
    else:
        lamp = "無數據"
    row["lamp"] = lamp
    row["recorded_at"] = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}"
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", nargs="*", default=None)
    args = ap.parse_args()
    dates = args.date or sorted({json.loads(p.read_text(encoding="utf-8"))["date"] for p in OUT.glob("*_latest.json")})
    birds = {b: load_bird(b) for b in BIRDS}
    logp = OUT / "beacon_log.csv"
    rows = {}
    if logp.exists():
        with open(logp, newline="", encoding="utf-8") as f:
            rows = {r["date"]: r for r in csv.DictReader(f)}
    for d in dates:
        r = lamp_for(d, birds)
        rows[d] = r
        y = f"；黃鳥 {r['yellow']}" if r["yellow"] else ""
        print(f"烽燧 {d} 收盤：{r['lamp']}（VIX9D−VIX {float(r['vix9d']) - float(r['vix']):+.2f}，VIX−VIX3M {float(r['vix']) - float(r['vix3m']):+.2f}{y}）→ 鳥翔只記錄、不行動"
              if r["vix9d"] and r["vix"] and r["vix3m"] else f"烽燧 {d}：{r['lamp']}")
    with open(logp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k, "") for k in FIELDS})


if __name__ == "__main__":
    main()
