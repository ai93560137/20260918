#!/usr/bin/env python3
"""一次性研究腳本：找官方/半官方的恒生指數歷史成分股名單（point-in-time，
含已被剔除的股票）。只能在有正常網路的環境跑（這個 session 的 sandbox
被組織 egress 白名單擋住，見 RESEARCH_HANDBOOK.md），所以搬到
GitHub Actions runner 上跑一次性 workflow_dispatch
（.github/workflows/research_hsi_history.yml），把抓到的原始內容存成
artifact 讓後續 session 下載檢視，不 commit 進 repo（這只是探勘，
不是要長期維護的抓取管線）。

跑法（只手動觸發，沒有排程）：
    GitHub Actions -> research-hsi-history -> Run workflow
"""
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

OUT_DIR = Path("research_output")
HEADERS = {"User-Agent": "Mozilla/5.0 (research script; point-in-time HSI constituents)"}

CANDIDATES = [
    ("wikipedia_en_api",
     "https://en.wikipedia.org/w/api.php?action=parse&page=Hang_Seng_Index&format=json&prop=wikitext"),
    ("wikipedia_zh_api",
     "https://zh.wikipedia.org/w/api.php?action=parse&page=%E6%81%86%E7%94%9F%E6%8C%87%E6%95%B8&format=json&prop=wikitext"),
    ("hsi_official_root", "https://www.hsi.com.hk/eng"),
    ("hsi_official_hsi_index", "https://www.hsi.com.hk/eng/indexes/all-indexes/hsi"),
    ("hsi_official_hsi_index_zh", "https://www.hsi.com.hk/schi/indexes/all-indexes/hsi"),
    ("hsi_official_announcements", "https://www.hsi.com.hk/eng/media/media-release"),
    ("hkex_news_search", "https://www1.hkex.com.hk/hkexnews/index/news"),
]


def fetch(name: str, url: str) -> None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        print(f"{name}: ERROR {exc}")
        return
    print(f"{name}: HTTP {r.status_code}  len={len(r.content)}  "
          f"content-type={r.headers.get('content-type')}")
    OUT_DIR.mkdir(exist_ok=True)
    ext = ".json" if "json" in r.headers.get("content-type", "") else ".html"
    out_path = OUT_DIR / f"{name}{ext}"
    out_path.write_bytes(r.content)


def main() -> None:
    for name, url in CANDIDATES:
        fetch(name, url)
        time.sleep(1)

    # wikipedia wikitext 通常最快能拿到「成分股變動」的表格，額外抽一次
    # 看有沒有明確的 "constituent change" / "index review" 段落
    wiki_path = OUT_DIR / "wikipedia_en_api.json"
    if wiki_path.exists():
        try:
            data = json.loads(wiki_path.read_text(encoding="utf-8"))
            wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
            (OUT_DIR / "wikipedia_en_wikitext.txt").write_text(wikitext, encoding="utf-8")
            print(f"wikipedia_en wikitext length: {len(wikitext)}")
        except Exception as exc:
            print(f"wikipedia_en parse ERROR: {exc}")

    print("done, files in", OUT_DIR.resolve())


if __name__ == "__main__":
    main()
