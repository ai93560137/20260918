#!/usr/bin/env python3
"""L1 前向測試（EURUSD 09:00 UTC 賣出 → 12:00 UTC 買回）的每日紙上交易記錄。登記與監測規則：forex_research/FX_EXPLORATORY_SCAN.md 第三部分、FX_L1_FORWARD.md。

    python3 scripts/fx_l1_forward.py [--start 2026-10-12] [--end YYYY-MM-DD]     # 預設到昨天（UTC）；Actions 每天跑（fx_l1_forward.yml）
    python3 scripts/fx_l1_forward.py --local --start 2026-09-14 --end 2026-09-22 --out /tmp/x   # 用本機 data_forex 近期 M1 驗證程式（不連網）

每個平日一列（forex_research/forward/l1_paper.csv，已有的日子不重算）：
- 價格 = 該時刻之前最後一根 M1 的收市（Dukascopy bid 與 ask 各一組）：進場賣在 bid(08:59 收市)、出場買在 ask(11:59 收市)
- l1_mid_bp = −ln(mid12/mid09)×1e4（毛，與回測定義相同）；l1_paper_bp = (bid09 − ask12)/mid09×1e4（含點差的可成交紙上損益）；l1_net_bp = 再扣佣金 0.4 基點
"""
import argparse
import csv
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
COMM_BP = 0.4
COLS = ["date", "bid_0859", "ask_0859", "bid_1159", "ask_1159", "spread_09_bp", "spread_12_bp", "l1_mid_bp", "l1_paper_bp", "l1_net_bp", "status"]


def minutes_remote(d: date, side: str):
    from fetch_forex import Feed
    feed = Feed(2, 1.0)
    rows = feed.candles(f"EURUSD/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5", datetime(d.year, d.month, d.day), 1e5)
    return pd.Series({pd.Timestamp(r[0]): r[4] for r in rows}).sort_index()


def minutes_local(d: date, side: str):
    f = ROOT / "data_forex" / "EURUSD" / ("EURUSD_M1_recent.csv.gz" if side == "BID" else "EURUSD_M1_recent_ask.csv.gz")
    s = pd.read_csv(f, parse_dates=["Time"]).set_index("Time")["Close"]
    return s[(s.index >= pd.Timestamp(d)) & (s.index < pd.Timestamp(d) + pd.Timedelta(days=1))]


def price_before(s: pd.Series, t: pd.Timestamp):
    """t 之前最後一根 M1 的收市（標籤 + 1 分鐘 ≤ t），且不早於 t 之前 10 分鐘。"""
    ok = s[(s.index + pd.Timedelta(minutes=1) <= t) & (s.index + pd.Timedelta(minutes=1) > t - pd.Timedelta(minutes=10))]
    return float(ok.iloc[-1]) if len(ok) else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-10-12")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", type=Path, default=ROOT / "forex_research" / "forward")
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    f = args.out / "l1_paper.csv"
    have = {}
    if f.exists():
        with open(f, encoding="utf-8") as fh:
            have = {r["date"]: r for r in csv.DictReader(fh)}
    end = date.fromisoformat(args.end) if args.end else (datetime.now(timezone.utc).date() - timedelta(days=1))
    days = [d.date() for d in pd.bdate_range(args.start, end)]
    new = 0
    for d in days:
        key = d.isoformat()
        if key in have and have[key]["status"] == "ok":
            continue
        fetch = minutes_local if args.local else minutes_remote
        try:
            bid, ask = fetch(d, "BID"), fetch(d, "ASK")
        except Exception as exc:  # noqa: BLE001
            print(f"{key}：抓取失敗 {exc!r}")
            continue
        t9, t12 = pd.Timestamp(d) + pd.Timedelta(hours=9), pd.Timestamp(d) + pd.Timedelta(hours=12)
        b9, a9, b12, a12 = price_before(bid, t9), price_before(ask, t9), price_before(bid, t12), price_before(ask, t12)
        if any(math.isnan(x) for x in (b9, a9, b12, a12)):
            row = {"date": key, **{c: "" for c in COLS[1:-1]}, "status": "missing"}
            print(f"{key}：缺價（bid/ask 0859={b9}/{a9}, 1159={b12}/{a12}）；status=missing，明天會再試")
        else:
            m9, m12 = (b9 + a9) / 2, (b12 + a12) / 2
            paper = (b9 - a12) / m9 * 1e4
            row = {"date": key, "bid_0859": f"{b9:.5f}", "ask_0859": f"{a9:.5f}", "bid_1159": f"{b12:.5f}", "ask_1159": f"{a12:.5f}",
                   "spread_09_bp": f"{(a9 - b9) / m9 * 1e4:.3f}", "spread_12_bp": f"{(a12 - b12) / m12 * 1e4:.3f}",
                   "l1_mid_bp": f"{-math.log(m12 / m9) * 1e4:.3f}", "l1_paper_bp": f"{paper:.3f}", "l1_net_bp": f"{paper - COMM_BP:.3f}", "status": "ok"}
            print(f"{key}：毛 {row['l1_mid_bp']} 基點、紙上 {row['l1_paper_bp']}、淨 {row['l1_net_bp']}（點差 {row['spread_09_bp']}/{row['spread_12_bp']}）")
        have[key] = row
        new += 1
    with open(f, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for k in sorted(have):
            w.writerow({c: have[k].get(c, "") for c in COLS})
    print(f"l1_paper.csv：新增／更新 {new} 列，共 {len(have)} 列")


if __name__ == "__main__":
    main()
