#!/usr/bin/env python3
"""蛇蟠陣（八陣圖 Donchian 觸價反手）逐筆明細的統計：t 值、按年、多空腿、集中度、連虧（手冊鐵律 5、7、8）。

    python3 donchian_backtest.py x.csv --mode sar --lookback 3 --spread 0.0001 --trades t.csv
    python3 scripts/snake_coil_eval.py t.csv --label EURUSD --pip 0.0001 [--range 55]

讀 donchian_backtest.py 的 --trades CSV（direction,entry,exit,pnl,open_time,close_time,reason）。
- t = 均值 ÷ (標準差 ÷ √n)；≥ 2 已驗證、1.5–2 有希望、< 1 不看
- 按年：正年數、最差年、最好年佔比；多空拆開；前 5／10 筆佔總獲利；最長連虧；水下時間（以逐筆權益近似）
- --pip 給了就同時以 pips 顯示；--json 輸出機器可讀
"""
import argparse
import csv
import json
import math
from collections import defaultdict


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["pnl"] = float(r["pnl"])
        r["direction"] = int(float(r["direction"]))
        r["year"] = r["close_time"][:4]
    return rows


def tstat(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else float("inf")


def summarize(rows: list[dict]) -> dict:
    p = [r["pnl"] for r in rows]
    n = len(p)
    if not n:
        return {"n": 0}
    wins = [v for v in p if v > 0]
    losses = [-v for v in p if v < 0]
    total = sum(p)
    srt = sorted(p, reverse=True)
    eq, peak, dd, under, worst_run, run = 0.0, 0.0, 0.0, 0, 0, 0
    for v in p:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        under += eq < peak
        run = run + 1 if v < 0 else 0
        worst_run = max(worst_run, run)
    by_year = defaultdict(float)
    for r in rows:
        by_year[r["year"]] += r["pnl"]
    years = dict(sorted(by_year.items()))
    return {"n": n, "total": total, "mean": total / n, "t": tstat(p), "win_rate": len(wins) / n,
            "pf": (sum(wins) / sum(losses)) if losses else float("inf"),
            "avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "top5_share": sum(srt[:5]) / total if total > 0 else float("nan"),
            "top10_share": sum(srt[:10]) / total if total > 0 else float("nan"),
            "max_dd": dd, "underwater_pct": under / n, "longest_losing_run": worst_run,
            "years": years, "pos_years": sum(v > 0 for v in years.values()), "n_years": len(years),
            "worst_year": min(years.items(), key=lambda kv: kv[1]) if years else None,
            "best_year_share": (max(years.values()) / total) if total > 0 and years else float("nan")}


def fmt(s: dict, unit: float = 1.0, u: str = "") -> str:
    if not s.get("n"):
        return "  無交易"
    f = lambda v: f"{v / unit:+,.1f}{u}"
    L = [f"  筆數 {s['n']}、總損益 {f(s['total'])}、均值/筆 {f(s['mean'])}、t = {s['t']:.2f}、勝率 {s['win_rate']*100:.1f}%、PF {s['pf']:.2f}、"
         f"均賺 {f(s['avg_win'])} / 均賠 {f(-s['avg_loss'])}",
         f"  前 5 筆佔 {s['top5_share']*100:.0f}%、前 10 筆佔 {s['top10_share']*100:.0f}%、最大回撤 {f(s['max_dd'])}、"
         f"水下 {s['underwater_pct']*100:.0f}%、最長連虧 {s['longest_losing_run']} 筆",
         f"  按年 {s['pos_years']}/{s['n_years']} 正、最差年 {s['worst_year'][0]} {f(s['worst_year'][1])}、最好一年佔 {s['best_year_share']*100:.0f}%：",
         "  " + "、".join(f"{y} {f(v)}" for y, v in s["years"].items())]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trades")
    ap.add_argument("--label", default="")
    ap.add_argument("--pip", type=float, default=0.0, help="1 pip 的價格單位（給了就以 pips 顯示）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--split", default="", help="YYYY-MM-DD：另外分「此日之前（樣本外）」與「此日起（重疊段）」各算一次")
    args = ap.parse_args()
    rows = load(args.trades)
    unit, u = (args.pip, " pips") if args.pip else (1.0, "")
    out = {"all": summarize(rows), "long": summarize([r for r in rows if r["direction"] > 0]),
           "short": summarize([r for r in rows if r["direction"] < 0])}
    if args.split:
        out[f"before_{args.split}"] = summarize([r for r in rows if r["open_time"][:10] < args.split])
        out[f"from_{args.split}"] = summarize([r for r in rows if r["open_time"][:10] >= args.split])
    if args.json:
        print(json.dumps({"label": args.label} | out, ensure_ascii=False, default=str))
        return
    print(f"== {args.label or args.trades}")
    names = {"all": "全部", "long": "多頭腿", "short": "空頭腿"}
    for k in out:
        print(f"[{names.get(k, k)}]")
        print(fmt(out[k], unit, u))


if __name__ == "__main__":
    main()
