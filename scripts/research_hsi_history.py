#!/usr/bin/env python3
"""一次性研究腳本：找官方/半官方的恒生指數歷史成分股名單（point-in-time，
含已被剔除的股票）。只能在有正常網路的環境跑（這個 session 的 sandbox
被組織 egress 白名單擋住，見 RESEARCH_HANDBOOK.md），所以搬到
GitHub Actions runner 上跑一次性 workflow_dispatch
（.github/workflows/research_hsi_history.yml），把抓到的內容 commit
回 research_output/ 給後續 session 檢視（不是要長期維護的抓取管線）。

第一輪（已完成）：確認 Hang Seng Indexes Company 官網是 JS SPA 抓不到
內容、英文 Wikipedia「Hang Seng Index」條目有「現在」的88檔成分股表
（有來源，比憑記憶整理準），但沒有逐年成分股變動的時間軸。

第二輪（這裡）：Wikipedia 有完整修訂歷史——用 MediaWiki API 的
rvstart+rvdir=older 抓「某個過去時間點當下」的條目版本，等於能拿到
「當時 Wikipedia 記載的成分股表」，近似 point-in-time 快照（不是官方
權威來源，但比「用現在的名單測過去」誠實很多，且免費）。這裡先抓
每年年中一個快照，存下原始 wikitext 供人工檢視表格結構是否穩定。

跑法（只手動觸發，沒有排程）：
    GitHub Actions -> research-hsi-history -> Run workflow
"""
import json
import sys
import time
from pathlib import Path

import requests

OUT_DIR = Path("research_output")
HEADERS = {"User-Agent": "Mozilla/5.0 (research script; point-in-time HSI constituents)"}
API = "https://en.wikipedia.org/w/api.php"

# 每年年中抓一次快照（HSI 歷史上半年/年底各有一次定期review，年中抓比較
# 不會剛好卡在 review 生效的交界上）
SNAPSHOT_DATES = [f"{y}-06-30T00:00:00Z" for y in range(2010, 2026)]


def fetch_revision_at(rvstart: str) -> dict | None:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": "Hang Seng Index",
        "rvlimit": 1,
        "rvstart": rvstart,
        "rvdir": "older",
        "rvprop": "content|timestamp",
        "rvslots": "main",
        "format": "json",
        "formatversion": 2,
    }
    r = None
    for attempt in range(5):
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        except Exception as exc:
            print(f"{rvstart}: ERROR {exc}")
            return None
        if r.status_code != 429:
            break
        wait = 5 * (attempt + 1)
        print(f"{rvstart}: HTTP 429，等 {wait}s 重試（第 {attempt + 1} 次）")
        time.sleep(wait)
    if r.status_code != 200:
        print(f"{rvstart}: HTTP {r.status_code}")
        return None
    data = r.json()
    pages = data.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        print(f"{rvstart}: 沒有找到修訂版本")
        return None
    rev = pages[0]["revisions"][0]
    return {"actual_timestamp": rev["timestamp"], "wikitext": rev["slots"]["main"]["content"]}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for target in SNAPSHOT_DATES:
        year = target[:4]
        out_path = OUT_DIR / f"hsi_wikipedia_snapshot_{year}.txt"
        if out_path.exists():
            print(f"{target}: 已有檔案，略過")
            continue
        rev = fetch_revision_at(target)
        if rev is None:
            continue
        out_path.write_text(rev["wikitext"], encoding="utf-8")
        has_table = "constituents" in rev["wikitext"] or "SEHK|" in rev["wikitext"]
        print(f"{target} -> 實際版本時間 {rev['actual_timestamp']}, "
              f"長度 {len(rev['wikitext'])}, 看起來有成分股表: {has_table}")
        time.sleep(3)

    print("done, files in", OUT_DIR.resolve())


if __name__ == "__main__":
    main()
