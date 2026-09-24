#!/usr/bin/env python3
"""一鍵取得外匯歷史數據（HistData M1 + Dukascopy D1／H1 買賣價與近期 M1 + Yahoo／FRED 第二來源；不進 git，存 GitHub Release「forex-data」）→ data_forex/<PAIR>/。

    python3 scripts/get_forex_data.py                       # 全部商品（七大 + 交叉盤 + 亞洲 + 貴金屬）
    python3 scripts/get_forex_data.py --group majors        # 只拿七大主要貨幣對
    python3 scripts/get_forex_data.py --pair EURUSD XAUUSD  # 指定幾個
    python3 scripts/get_forex_data.py --list                # 看下載網址
    python3 scripts/get_forex_data.py --pair EURUSD --merge-m1 /tmp/eurusd_m1.csv   # 順便合併 M1 成單一檔給回測引擎

目錄、每個商品的注意事項、回測用法見 forex_research/FOREX_DATA_CATALOG.md；品質報告已 commit 在 forex_research/data_qc/。
數據由 .github/workflows/fetch_forex.yml 在 GitHub Actions 抓（沙盒連不到 Dukascopy／Yahoo／FRED），要更新就手動觸發那個工作流程。
"""
import argparse
import gzip
import re
import sys
import tarfile
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = "ai93560137/20260918"
TAG = "forex-data"
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_forex import GROUPS, INSTRUMENTS  # noqa: E402


def fetch(pair: str, root: Path) -> bool:
    url = f"https://github.com/{REPO}/releases/download/{TAG}/{pair}.tar"
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        with requests.get(url, stream=True, timeout=600) as r:
            if r.status_code == 404:
                print(f"{pair}：Release 還沒有這個商品（先在 Actions 跑 fetch_forex.yml）")
                return False
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                tmp.write(chunk)
        tmp.flush()
        with tarfile.open(tmp.name) as tf:
            tf.extractall(root, filter="data") if sys.version_info >= (3, 12) else tf.extractall(root)
    d = root / "data_forex" / pair
    m1 = sorted(p for p in d.glob(f"{pair}_M1_*.csv.gz") if re.fullmatch(rf"{pair}_M1_\d{{4}}\.csv\.gz", p.name))
    status = (d / "_status.txt").read_text().strip() if (d / "_status.txt").exists() else ""
    print(f"{pair}：M1 年檔 {len(m1)}（{m1[0].stem.split('_')[-1] if m1 else '—'} → {m1[-1].stem.split('_')[-1] if m1 else '—'}）"
          f"、{sum(p.stat().st_size for p in d.iterdir()) / 1e6:.0f} MB；{status}")
    return True


def merge_m1(pair: str, root: Path, out: Path) -> None:
    """把 <PAIR>_M1_<YYYY>.csv.gz 合併成一個 CSV（UTC；donchian_backtest.py／zgl_backtest.py 用 --broker-offset 0）。"""
    d = root / "data_forex" / pair
    files = sorted(p for p in d.glob(f"{pair}_M1_*.csv.gz") if re.fullmatch(rf"{pair}_M1_\d{{4}}\.csv\.gz", p.name))
    rows = {}
    for p in [d / f"{pair}_M1_recent.csv.gz"] + files:              # HistData 年檔優先、Dukascopy 近期檔補尾
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            next(f)
            for line in f:
                rows[line.split(",", 1)[0]] = line
    with open(out, "w", encoding="utf-8") as w:
        w.write("Time,Open,High,Low,Close,Volume\n")
        for k in sorted(rows):
            w.write(rows[k])
    print(f"{pair}：M1 合併 {len(files)} 個 HistData 年檔 + Dukascopy 近期檔、{len(rows):,} 根 → {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", nargs="*", choices=GROUPS, default=[])
    ap.add_argument("--pair", nargs="*", choices=list(INSTRUMENTS), default=[])
    ap.add_argument("--root", type=Path, default=ROOT, help="解壓到哪裡（預設倉庫根目錄 → data_forex/<PAIR>/）")
    ap.add_argument("--merge-m1", type=Path, help="下載後把 M1 合併成這個 CSV（只在指定單一商品時）")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    pairs = [p for p, v in INSTRUMENTS.items() if (not args.group and not args.pair) or v[2] in args.group or p in args.pair]
    if args.list:
        for p in pairs:
            print(f"{p:7} {INSTRUMENTS[p][2]:8} https://github.com/{REPO}/releases/download/{TAG}/{p}.tar")
        return
    ok = [p for p in pairs if fetch(p, args.root)]
    if args.merge_m1:
        if len(ok) != 1:
            sys.exit("--merge-m1 只能配一個商品（--pair XXX）")
        merge_m1(ok[0], args.root, args.merge_m1)


if __name__ == "__main__":
    main()
