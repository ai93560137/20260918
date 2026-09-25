#!/usr/bin/env python3
"""蛇蟠陣多設定一次跑（載入一次 M1，依序跑多個設定，逐筆明細寫 CSV）——給大檔（900 萬根）用，避免每個設定重新載入。

    python3 scripts/snake_coil_run.py <m1.csv> <輸出目錄> --label USDJPY --spreads 0.010 0.017 --lookbacks 1 2 3 5
"""
import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import donchian_backtest as db  # noqa: E402
from zgl_backtest import load_any  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--label", default="X")
    ap.add_argument("--spreads", nargs="+", type=float, required=True, help="第一個是主口徑（跑全部 N），其餘只跑 N=3")
    ap.add_argument("--lookbacks", nargs="+", type=int, default=[1, 2, 3, 5])
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bars = load_any(args.data, 0.0)
    print(f"{args.label}: 載入 {len(bars):,} 根（{db.day_key(bars[0]['time'])} → {db.day_key(bars[-1]['time'])}），{time.time()-t0:.0f} 秒", flush=True)
    print(db.HEADER, flush=True)
    for i, sp in enumerate(args.spreads):
        for lb in (args.lookbacks if i == 0 else [3]):
            t1 = time.time()
            r = db.run(bars, lookback=lb, mode="sar", trade_mode="both", spread=sp, equity=10000.0, atr_len=14, collect_trades=True)
            tag = f"{args.label}_sar_N{lb}_sp{sp:g}"
            with open(args.outdir / f"{tag}.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["direction", "entry", "exit", "pnl", "open_time", "close_time", "reason"])
                w.writerows(r["trade_rows"])
            print(db.fmt_row(f"sar N={lb} spread={sp:g}", r) + f"   ({time.time()-t1:.0f} 秒)", flush=True)


if __name__ == "__main__":
    main()
