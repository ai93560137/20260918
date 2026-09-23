#!/usr/bin/env python3
"""由各指數 PIT 成分股區間檔產生每個市場的抓取清單 universes/<market>/fetch_list.txt
（universe.py 的全部指數；2008 後仍在榜的代碼 + 基準）。成分股檔更新後重跑。

    python3 scripts/build_fetch_lists.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from universe import INDICES, Universe  # noqa: E402

FETCH_SINCE = date(2008, 1, 1)   # 輪動檢測/策略 2010 起，多留暖身
BENCHMARKS = {"us": ["SPY", "QQQ", "DIA", "^GSPC", "^NDX", "^DJI", "RSP", "EWJ"], "jp": ["1321.T", "^N225"]}


def main() -> None:
    for market, bench in BENCHMARKS.items():
        tickers = set()
        used = []
        for key, cfg in INDICES.items():
            if cfg["market"] != market or not (ROOT / cfg.get("file", "")).is_file():
                continue
            used.append(key)
            tickers |= set(Universe(key).all_tickers(since=FETCH_SINCE))
        out = ROOT / "universes" / market / "fetch_list.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# 自動產生（scripts/build_fetch_lists.py）：{'/'.join(used)} PIT 成分股聯集（{FETCH_SINCE} 後仍在榜）+ 基準\n"
                       + "\n".join(bench + sorted(tickers - set(bench))) + "\n", encoding="utf-8")
        print(f"{market}: {'/'.join(used)} -> {len(tickers)} 檔 + {len(bench)} 基準 -> {out}")


if __name__ == "__main__":
    main()
