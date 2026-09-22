#!/usr/bin/env python3
"""一次性探勘第二輪（Actions 上跑）：日股第二收市源與官方名字/業種來源。

- 日經新聞「日経平均採用銘柄 株価一覧」（nikkei.com/markets/kabu/nidxprice）：
  225 檔收市價分頁列出——若可抓，一個來源就涵蓋整個日經225
- JPX「東証上場銘柄一覧」：上一輪固定網址 404，改從索引頁找當前 xls 連結
- Yahoo!ファイナンス個股頁完整 HTML（上一輪截斷在 300k，看有沒有結構化 JSON）
"""
import re
import time
from pathlib import Path

import requests

OUT = Path("research_output/multimarket/probe2")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ja,en-US;q=0.8"}
LOG = []


def get(name: str, url: str, save: bool = True, binary: bool = False, keep: int = 2_000_000):
    try:
        r = requests.get(url, headers=UA, timeout=45)
    except Exception as exc:
        LOG.append(f"{name}: ERROR {exc}")
        return None
    LOG.append(f"{name}: HTTP {r.status_code} {r.headers.get('content-type', '')} {len(r.content)} bytes  {url}")
    if save:
        OUT.mkdir(parents=True, exist_ok=True)
        if binary:
            (OUT / f"{name}.bin").write_bytes(r.content[:keep])
        else:
            (OUT / f"{name}.txt").write_text(r.text[:keep], encoding="utf-8")
    return r


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for page in (1, 2, 5):
        get(f"nikkei_nidxprice_p{page}",
            f"https://www.nikkei.com/markets/kabu/nidxprice/?StockIndex=N225&Gcode=00&hm={page}")
        time.sleep(1)
    r = get("jpx_misc_index", "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html")
    if r is not None and r.status_code == 200:
        links = sorted(set(re.findall(r'href="([^"]+\.xlsx?)"', r.text)))
        LOG.append(f"jpx xls links: {links}")
        for i, href in enumerate(links[:2]):
            url = href if href.startswith("http") else "https://www.jpx.co.jp" + href
            get(f"jpx_listed_{i}", url, binary=True, keep=10_000_000)
    get("yahoojp_7203_full", "https://finance.yahoo.co.jp/quote/7203.T", keep=1_000_000)
    (OUT / "probe_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print("\n".join(LOG))


if __name__ == "__main__":
    main()
