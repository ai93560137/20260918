#!/usr/bin/env python3
"""每日增量更新 data_full/<市場>/（HTF 每日訊號用；只在 GitHub Actions 跑，沙盒連不到 Yahoo）。2026-10-12

    python3 scripts/htf_update_data.py --market hk

- 候選池 universes/full/<市場>_pool.txt；已有檔案的股票只抓「最舊最後日 − 7 日」起的日線，接回舊檔
- 重疊日的 Close 差 > 2% = 拆股／合股 → 該股全段重抓；AdjClose 比例變了（除息）→ 舊段 AdjClose 乘同一個比例
- 沒有檔案的新股票交給 fetch_full_market.py（缺的才抓）
- 收市未完成的「今天」那根丟掉（同 fetch_full_market.last_complete_cutoff）
- 只改 runner 本機檔案，不上傳 Release（不覆寫共用數據）
"""
import argparse
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_full_market import last_complete_cutoff  # noqa: E402

BATCH = 100
COLS = ["Open", "High", "Low", "Close", "AdjClose", "Volume"]


def read(p: Path) -> pd.DataFrame:
    df = pd.read_csv(p, compression="gzip")
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df.set_index("Date")


def write(p: Path, df: pd.DataFrame) -> None:
    df.index.name = "Date"
    df[COLS].to_csv(p, float_format="%.6g", compression="gzip")


def norm(sub: pd.DataFrame) -> pd.DataFrame:
    sub = sub.dropna(subset=["Close"]).rename(columns={"Adj Close": "AdjClose"})
    sub = sub[[c for c in COLS if c in sub.columns]]
    sub.index = pd.to_datetime(sub.index).date
    return sub


def main() -> None:
    import yfinance as yf
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", required=True)
    args = a.parse_args()
    mk = args.market
    out = ROOT / "data_full" / mk
    pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{mk}_pool.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    # 1) 新股票：缺的才抓
    subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_full_market.py"), "--market", mk, "--budget-min", "20"], check=False)
    cutoff = last_complete_cutoff(mk)
    have = {}
    for t in pool:
        p = out / f"{t.replace('^', '_')}.csv.gz"
        if p.exists():
            try:
                have[t] = read(p)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN 讀不到 {t}：{exc}", file=sys.stderr)
    recent = cutoff - timedelta(days=120)
    live = {t: df for t, df in have.items() if len(df) and df.index[-1] >= recent}
    if not live:
        print(f"[{mk}] 沒有近 120 日仍有數據的股票", file=sys.stderr)
        return
    start = min(df.index[-1] for df in live.values()) - timedelta(days=7)
    print(f"[{mk}] 增量更新 {len(live)} 檔，由 {start} 抓到 {cutoff}", file=sys.stderr)
    tickers = sorted(live)
    refetch, n_ok, n_div = [], 0, 0
    t0 = time.time()
    for b in range(0, len(tickers), BATCH):
        batch = tickers[b:b + BATCH]
        for attempt in range(3):
            try:
                df = yf.download(batch, start=start.isoformat(), auto_adjust=False, actions=False, group_by="ticker",
                                 threads=True, progress=False)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"WARN 第 {b} 批失敗（{exc}），重試", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                new = norm(df[t] if len(batch) > 1 else df)
            except KeyError:
                continue
            new = new[new.index <= cutoff]
            if new.empty:
                continue
            old = live[t]
            ov = old.index.intersection(new.index)
            if len(ov):
                cr = (new.loc[ov, "Close"] / old.loc[ov, "Close"]).replace([np.inf, -np.inf], np.nan).dropna()
                if len(cr) and (abs(cr.median() - 1) > 0.02):
                    refetch.append(t)
                    continue
                d0 = ov[-1]
                o_adj, n_adj = old.loc[d0, "AdjClose"], new.loc[d0, "AdjClose"]
                if o_adj == o_adj and n_adj == n_adj and o_adj > 0 and abs(n_adj / o_adj - 1) > 1e-6:
                    old = old.copy()
                    old["AdjClose"] = old["AdjClose"] * (n_adj / o_adj)
                    n_div += 1
            merged = pd.concat([old[old.index < new.index[0]], new])
            write(out / f"{t.replace('^', '_')}.csv.gz", merged)
            n_ok += 1
        print(f"  {min(b + BATCH, len(tickers))}/{len(tickers)}，{time.time() - t0:.0f} 秒", flush=True)
        time.sleep(1)
    # 2) 拆股／合股：全段重抓
    for b in range(0, len(refetch), BATCH):
        batch = refetch[b:b + BATCH]
        try:
            df = yf.download(batch, start="1995-01-01", auto_adjust=False, actions=False, group_by="ticker", threads=True, progress=False)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN 全段重抓失敗：{exc}", file=sys.stderr)
            continue
        for t in batch:
            try:
                new = norm(df[t] if len(batch) > 1 else df)
            except KeyError:
                continue
            new = new[new.index <= cutoff]
            if not new.empty:
                write(out / f"{t.replace('^', '_')}.csv.gz", new)
    print(f"[{mk}] 更新 {n_ok} 檔（除息調整 {n_div}）、拆股全段重抓 {len(refetch)} 檔：{', '.join(refetch[:20])}", file=sys.stderr)
    # 3) 品質排除檔重建（結構檢查，同 get_market_data）
    subprocess.run([sys.executable, str(ROOT / "scripts" / "qc_full_market.py"), "--market", mk, "--no-network",
                    "--report-dir", str(ROOT / "analysis" / "htf_daily" / "_qc")], check=False)


if __name__ == "__main__":
    main()
