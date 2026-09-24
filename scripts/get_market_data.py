#!/usr/bin/env python3
"""一鍵取得全市場日線（9 個市場；不進 git，存在 GitHub Release）→ data_full/<m>/，並重建品質排除檔。

    python3 scripts/get_market_data.py                  # 全部 9 個市場（約 1.2 GB）
    python3 scripts/get_market_data.py --market hk us   # 只拿幾個
    python3 scripts/get_market_data.py --list           # 只列出有甚麼

目錄與每個市場的注意事項見 stock_research/MARKET_DATA_CATALOG.md。
- 港日美在 Release `fullmarket-data`（vcp_fullmarket.yml 更新）；台韓澳加印新在 Release `oos-data`（oos_fullmarket.yml 更新）
- tar 裡沒有品質排除檔 → 下載後自動跑 `qc_full_market.py --no-network`（結構檢查，不用外網；結果與原版逐字相同），
  報告寫到暫存資料夾，不會改動倉庫裡已 commit 的品質報告
"""
import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = "ai93560137/20260918"
RELEASE = {"hk": "fullmarket-data", "jp": "fullmarket-data", "us": "fullmarket-data",
           "tw": "oos-data", "kr": "oos-data", "au": "oos-data", "ca": "oos-data", "in": "oos-data", "sg": "oos-data"}
NAME = {"hk": "港股", "jp": "日股", "us": "美股", "tw": "台灣", "kr": "韓國", "au": "澳洲", "ca": "加拿大", "in": "印度",
        "sg": "新加坡"}


def fetch(m: str, root: Path, qc: bool) -> None:
    url = f"https://github.com/{REPO}/releases/download/{RELEASE[m]}/{m}.tar"
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                tmp.write(chunk)
        tmp.flush()
        with tarfile.open(tmp.name) as tf:
            tf.extractall(root, filter="data") if sys.version_info >= (3, 12) else tf.extractall(root)
    n = len(list((root / "data_full" / m).glob("*.csv.gz")))
    print(f"{m}（{NAME[m]}）：{n} 檔 → {root / 'data_full' / m}")
    if qc:
        with tempfile.TemporaryDirectory() as rep:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "qc_full_market.py"), "--market", m, "--no-network",
                            "--report-dir", rep], cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ex = root / "data_full" / m / "_qc_exclude.txt"
        print(f"   品質排除檔已重建：整檔排除 {len(ex.read_text().split()) if ex.exists() else '?'} 檔")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", nargs="*", default=list(RELEASE), choices=list(RELEASE))
    ap.add_argument("--no-qc", action="store_true", help="不重建品質排除檔（不建議）")
    ap.add_argument("--root", type=Path, default=ROOT, help="解壓到哪裡（預設倉庫根目錄 → data_full/<m>/）")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for m in RELEASE:
            print(f"{m:3} {NAME[m]:4} Release {RELEASE[m]:16} https://github.com/{REPO}/releases/download/{RELEASE[m]}/{m}.tar")
        return
    same = args.root.resolve() == ROOT.resolve()
    if not same and not args.no_qc:
        print("註：--root 不是倉庫根目錄時不自動重建品質排除檔（qc_full_market.py 只讀倉庫的 data_full/）", file=sys.stderr)
    for m in args.market:
        fetch(m, args.root, same and not args.no_qc)


if __name__ == "__main__":
    main()
