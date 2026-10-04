"""投資人堅持用期貨（2026-10-04）：把有證據的期貨策略併成一個組合，看合計的期望值、t 值、回撤、相關性。

四條（都是之前測過、有逐筆紀錄或可重算的）：
  SNAKE   🐍 蛇蟠陣（Donchian 3 蛇日觸價反手，永遠在場；snake_band.snake_run 重算，成本 3 點）
  B_S_R3  🅱️＋跟蛇＋3R（r_sweep/futu/trades/B_S_R3.csv）
  A_S_R2  🅰️＋跟蛇＋2R（r_sweep/futu/trades/A_S_R2.csv）
  USFADE  逆隔夜美股日內：標普昨晚升就在 09:30 第一根 15 分 K 開市沽、跌就買，16:30 收市平；只做美股升跌 > 0.5% 的日子；成本 3 點
每條 1 張；逐日盈虧按出場日歸入；組合 = 四條相加（最多同時 4 張）。
用法：python3 research/hsi_futures_range/futures_portfolio.py --json 15 分 K 快取 --spx spx.csv
輸出：research/hsi_futures_range/futures_portfolio/REPORT.md、daily.csv
"""
import argparse, csv, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_band as sb                                  # noqa: E402

OUT = HERE / "futures_portfolio"
COST = 3.0
US_MIN = 0.005


def ledger(path):
    out = defaultdict(float)
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[r["exit_date"]] += float(r["net"])
    return out


def snake_daily(days):
    _, _, trades = sb.snake_run(sb.snake_days(days), COST)
    out = defaultdict(float)
    for d, side, pnl in trades:
        out[d] += pnl
    return out, len(trades)


def usfade_daily(days, spx_path):
    spx = {r["Date"]: float(r["Close"]) for r in csv.DictReader(open(spx_path, encoding="utf-8"))}
    sd = sorted(spx)
    out = defaultdict(float); n = 0
    prev = None
    for d in days:
        bars = [b for b in d["bars"] if b["time_key"][:10] == d["date"] and "09:30" <= b["time_key"][11:16] <= "16:30"]
        if prev and len(bars) >= 10:
            us = [x for x in sd if prev <= x < d["date"]]        # 上個交易日收市後到今天開市前完成的美股交易日
            if us:
                i = sd.index(us[-1]); r = math.log(spx[us[-1]] / spx[sd[i - 1]]) if i > 0 else 0.0
                if abs(r) > US_MIN:
                    sign = -1 if r > 0 else 1
                    out[d["date"]] += sign * (bars[-1]["close"] - bars[0]["open"]) - COST; n += 1
        prev = d["date"]
    return out, n


def stats(series, dates):
    x = np.array([series.get(d, 0.0) for d in dates])
    eq = np.cumsum(x); dd = float((np.maximum.accumulate(eq) - eq).max())
    # 以週為單位算 t（日盈虧有很多 0）
    wk = defaultdict(float)
    for d, v in zip(dates, x):
        from datetime import date
        y, w, _ = date.fromisoformat(d).isocalendar(); wk[f"{y}-W{w:02d}"] += v
    w = np.array(list(wk.values()))
    yrs = len(dates) / 250
    return {"total": x.sum(), "per_year": x.sum() / yrs, "dd": dd, "t_week": w.mean() / w.std(ddof=1) * math.sqrt(len(w)),
            "win_week": (w > 0).mean(), "worst_day": x.min(), "sharpe": w.mean() / w.std(ddof=1) * math.sqrt(52), "x": x}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json", required=True); ap.add_argument("--spx", required=True)
    a = ap.parse_args()
    cache = json.load(open(a.json))
    days = hl.build_days(cache["bars"], cache["daily"])
    b3 = ledger(HERE / "r_sweep" / "futu" / "trades" / "B_S_R3.csv"); a2 = ledger(HERE / "r_sweep" / "futu" / "trades" / "A_S_R2.csv")
    start = min(min(b3), min(a2))
    days = [d for d in days if d["date"] >= start]
    dates = [d["date"] for d in days]
    sn, n_sn = snake_daily(days)
    us, n_us = usfade_daily(days, a.spx)
    series = {"🐍 蛇蟠陣": sn, "🅱️＋跟蛇＋3R": b3, "🅰️＋跟蛇＋2R": a2, "逆隔夜美股日內": us}
    counts = {"🐍 蛇蟠陣": n_sn, "🅱️＋跟蛇＋3R": sum(1 for _ in csv.DictReader(open(HERE / "r_sweep" / "futu" / "trades" / "B_S_R3.csv"))),
              "🅰️＋跟蛇＋2R": sum(1 for _ in csv.DictReader(open(HERE / "r_sweep" / "futu" / "trades" / "A_S_R2.csv"))), "逆隔夜美股日內": n_us}
    S = {k: stats(v, dates) for k, v in series.items()}
    combo = defaultdict(float)
    for v in series.values():
        for d, p in v.items():
            combo[d] += p
    S["組合（四條各 1 張）"] = stats(combo, dates)
    three = defaultdict(float)
    for k in ("🐍 蛇蟠陣", "🅱️＋跟蛇＋3R", "逆隔夜美股日內"):
        for d, p in series[k].items():
            three[d] += p
    S["組合（蛇＋🅱️＋美股，不含 🅰️）"] = stats(three, dates)
    yrs = len(dates) / 250
    L = [f"# 期貨策略組合（futures_portfolio.py）", "", f"- {dates[0]} 至 {dates[-1]}，{len(dates)} 個交易日（{yrs:.1f} 年）；每條 1 張大合約；成本每筆 3 點；逐日盈虧按出場日歸入", "",
         "| 策略 | 交易數 | 每年點數 | 每年 HK$（×50） | 週勝率 | 週 t 值 | 年化夏普（週） | 最大回撤（點） | 最差一日 |", "|---|---|---|---|---|---|---|---|---|"]
    for k, s in S.items():
        L.append(f"| {k} | {counts.get(k, '—')} | **{s['per_year']:+,.0f}** | {s['per_year'] * 50:+,.0f} | {s['win_week']:.0%} | {s['t_week']:+.2f} | {s['sharpe']:.2f} | {s['dd']:,.0f} | {s['worst_day']:+,.0f} |")
    L += ["", "## 逐年（點）", "", "| 策略 | " + " | ".join(sorted({d[:4] for d in dates})) + " |", "|---|" + "---|" * len({d[:4] for d in dates})]
    for k, s in S.items():
        cells = []
        for y in sorted({d[:4] for d in dates}):
            cells.append(f"{sum(v for d, v in zip(dates, s['x']) if d[:4] == y):+,.0f}")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    names = list(series)
    M = np.corrcoef(np.array([S[k]["x"] for k in names]))
    L += ["", "## 四條策略逐日盈虧的相關係數", "", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for i, k in enumerate(names):
        L.append(f"| {k} | " + " | ".join(f"{M[i, j]:+.2f}" for j in range(len(names))) + " |")
    with open(OUT / "daily.csv" if OUT.exists() else OUT.mkdir() or OUT / "daily.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["date"] + names + ["combo"])
        for i, d in enumerate(dates):
            w.writerow([d] + [f"{S[k]['x'][i]:.1f}" for k in names] + [f"{S['組合（四條各 1 張）']['x'][i]:.1f}"])
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
