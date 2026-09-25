#!/usr/bin/env python3
"""蛇蟠陣外匯批次：逐個商品 下載 Release → 合併成券商時間 M1 → sar N=1/2/3/5（點差 = 該商品 Dukascopy 近 3 年中位）→ 逐筆明細 + JSON 統計。

    python3 scripts/snake_coil_batch.py --pairs GBPUSD USDCHF ... --out forex_research/snake_coil/batch

每個商品跑完就刪掉合併檔與 data_forex/<PAIR>（沙盒磁碟有限）；點差來自 forex_research/snake_coil/cost_gate.csv 的 sp3（pips）。
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_forex import INSTRUMENTS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "forex_research" / "snake_coil" / "batch")
    ap.add_argument("--work", type=Path, required=True, help="暫存資料夾（下載與合併檔）")
    ap.add_argument("--lookbacks", nargs="+", type=int, default=[1, 2, 3, 5])
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    gate = {r["pair"]: r for r in csv.DictReader(open(ROOT / "forex_research" / "snake_coil" / "cost_gate.csv", encoding="utf-8"))}
    for pair in args.pairs:
        t0 = time.time()
        dec = INSTRUMENTS[pair][1]
        pip = 10.0 ** -(dec - 1)
        spread = round(float(gate[pair]["sp3"]) * pip, dec)
        print(f"== {pair}：點差 {spread:g}（{gate[pair]['sp3']} pips，日均波幅÷點差 {float(gate[pair]['ratio_spread_only']):.0f} 倍）", flush=True)
        merged = args.work / f"{pair}_bt.csv"
        try:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "get_forex_data.py"), "--pair", pair, "--root", str(args.work),
                            "--merge-m1", str(merged), "--broker-time"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable, str(ROOT / "scripts" / "snake_coil_run.py"), str(merged), str(args.out), "--label", pair,
                            "--spreads", f"{spread:g}", "--lookbacks", *map(str, args.lookbacks)], check=True)
            for lb in args.lookbacks:
                tr = args.out / f"{pair}_sar_N{lb}_sp{spread:g}.csv"
                js = subprocess.run([sys.executable, str(ROOT / "scripts" / "snake_coil_eval.py"), str(tr), "--label", f"{pair} N={lb}",
                                     "--pip", str(pip), "--json"], check=True, capture_output=True, text=True).stdout
                (args.out / f"{pair}_sar_N{lb}.json").write_text(js, encoding="utf-8")
        except subprocess.CalledProcessError as exc:
            print(f"  {pair} 失敗：{exc}", flush=True)
        finally:
            merged.unlink(missing_ok=True)
            shutil.rmtree(args.work / "data_forex" / pair, ignore_errors=True)
        print(f"  {pair} 完成，{time.time() - t0:.0f} 秒", flush=True)


if __name__ == "__main__":
    main()
