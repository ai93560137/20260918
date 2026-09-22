#!/usr/bin/env python3
"""一次性探勘：找港交所官方「個股收市價 + 公司名」的可用來源，給
scripts/fetch_hkex_equity.py 用。第一版猜的 widget 端點 getequityquote 回 HTML
錯誤頁，這裡不再猜，改成把原始回應存下來人工看：

1. 股票報價頁 HTML + 它引用的 JS，掃出所有 hkexwidget/data/<端點> 名稱
2. 對掃到的端點用幾組常見參數試打 0700，存原始回應
3. 港交所「每日報價表」靜態檔 dayquot/d<YYMMDD>e.htm（全市場代碼、簡稱、收市價），
   往回試最近 7 天，存第一份抓得到的

輸出 research_output/hkex_probe/，由 research_hsi_history.yml 以 script 參數觸發。
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("research_output/hkex_probe")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.hkex.com.hk/",
}
QUOTE_PAGE = "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=700&sc_lang=en"
HKT = timezone(timedelta(hours=8))


def save(name: str, text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def main() -> None:
    s = requests.Session()
    s.headers.update(HEADERS)
    log = []

    page = s.get(QUOTE_PAGE, timeout=20).text
    save("quote_page.html", page)
    token_m = re.search(r'return\s*"(evLts[^"]+)"', page)
    token = token_m.group(1) if token_m else ""
    log.append(f"quote page len={len(page)} token={'yes' if token else 'NO'}")

    endpoints = set(re.findall(r"hkexwidget/data/(\w+)", page))
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', page)
    for src in scripts:
        url = urljoin(QUOTE_PAGE, src)
        if "hkex" not in url:
            continue
        try:
            js = s.get(url, timeout=20).text
        except Exception as exc:
            log.append(f"js {url} ERROR {exc}")
            continue
        found = set(re.findall(r"hkexwidget/data/(\w+)", js)) | set(re.findall(r'["\'/](get\w*quote\w*)["\'?]', js, re.I))
        if found:
            log.append(f"js {url}: {sorted(found)}")
            save("js_" + re.sub(r"\W+", "_", url)[-80:] + ".txt", js[:200000])
        endpoints |= found
    log.append(f"endpoints found: {sorted(endpoints)}")

    for ep in sorted(endpoints):
        for params in ({"sym": "700"}, {"sym": "00700"}, {"sym": "700", "type": "0"}):
            q = {**params, "token": token, "lang": "eng", "qid": int(time.time() * 1000), "callback": "j"}
            try:
                r = s.get(f"https://www1.hkex.com.hk/hkexwidget/data/{ep}", params=q, timeout=10)
                body = r.text
            except Exception as exc:
                body = f"ERROR {exc}"
            ok = body.lstrip().startswith("j(")
            log.append(f"{ep} {params}: jsonp={ok} len={len(body)} head={body[:120]!r}")
            if ok:
                save(f"ep_{ep}_{'_'.join(f'{k}{v}' for k, v in params.items())}.txt", body)
            time.sleep(0.3)

    today = datetime.now(HKT).date()
    for back in range(0, 8):
        d = today - timedelta(days=back)
        url = f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{d:%y%m%d}e.htm"
        try:
            r = s.get(url, timeout=20)
        except Exception as exc:
            log.append(f"dayquot {d}: ERROR {exc}")
            continue
        log.append(f"dayquot {d}: HTTP {r.status_code} len={len(r.content)}")
        if r.status_code == 200 and len(r.content) > 50000:
            save(f"dayquot_{d}.htm", r.content.decode("utf-8", errors="replace"))
            break

    save("probe_log.txt", "\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
