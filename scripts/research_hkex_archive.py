#!/usr/bin/env python3
"""一次性探勘：港交所每日報價表（dayquot）能回溯多久——決定港股能不能做全量歷史比對。"""
import time
from pathlib import Path

import requests

OUT = Path("research_output/hkex_archive")
URL = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{d}e.htm"
DATES = ["260831", "260105", "250630", "250102", "240628", "230630", "220630", "200630",
         "180629", "150630", "120629", "100630", "050630", "020628", "000630"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = []
    for d in DATES:
        try:
            r = requests.get(URL.format(d=d), headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            ok = 'name = "quotations"' in r.text or 'name="quotations"' in r.text
            log.append(f"{d}: HTTP {r.status_code} {len(r.content)} bytes quotations={ok}")
        except Exception as exc:
            log.append(f"{d}: ERROR {exc}")
        time.sleep(1)
    (OUT / "probe_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
