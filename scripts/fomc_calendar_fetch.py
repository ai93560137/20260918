#!/usr/bin/env python3
"""FOMC 排定公告日曆 1994→2027：抓聯準會逐年歷史頁＋近年日曆頁，存原始 HTML，解析聲明連結日期，再逐篇抓聲明頁的「For release at …」時間。
登記：forex_research/FOMC_DATA_REQUEST.md 第 2 節。只讀公開網頁。

    python3 scripts/fomc_calendar_fetch.py --out data_forex_ibkr/fomc [--from 1994] [--no-times]
"""
import argparse
import csv
import html
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://www.federalreserve.gov"
UA = {"User-Agent": "Mozilla/5.0 (research calendar fetch; contact via repo)"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
UNSCHED = re.compile(r"unscheduled|conference call|notation vote|intermeeting|emergency", re.I)


def get(url: str, retries: int = 4) -> str:
    for k in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return r.text
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = repr(e)
        time.sleep(3 * (k + 1))
    print(f"  失敗 {url}: {err}")
    return ""


def strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").strip()


def parse_meetings(page: str, default_year: int | None) -> list[dict]:
    """依序掃描標題與連結：遇到含 Statement／Press Release 且 href 有 8 位日期的連結就記一列，標題取最近的一個。"""
    rows, last_head, year = [], "", default_year
    tok = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>|<div[^>]*class=\"[^\"]*fomc-meeting__month[^\"]*\"[^>]*>(.*?)</div>|<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S | re.I)
    for m in tok.finditer(page):
        if m.group(1) is not None or m.group(2) is not None:
            last_head = strip(m.group(1) or m.group(2) or "")
            y = re.search(r"\b(19|20)\d{2}\b", last_head)
            if y:
                year = int(y.group(0))
            continue
        href, text = m.group(3), strip(m.group(4) or "")
        if not re.search(r"statement|press release", text, re.I):
            continue
        d = re.search(r"(19|20)\d{6}", href)
        if not d:
            continue
        rows.append({"date": datetime.strptime(d.group(0), "%Y%m%d").date().isoformat(), "heading": last_head, "href": href if href.startswith("http") else BASE + href})
    # 去重（同日 Statement 與 Implementation Note 兩個連結）
    seen, out = set(), []
    for r in rows:
        if r["date"] not in seen:
            seen.add(r["date"]); out.append(r)
    return out


def parse_future(page: str) -> list[dict]:
    """日曆頁上沒有聲明連結的（未來）會議：以「YYYY FOMC Meetings」區塊內的 月 日-日 文字取公告日＝最後一天。"""
    out = []
    text = strip(page)
    blocks = re.split(r"(?=(?:19|20)\d{2}\s+FOMC\s+Meetings)", text)
    for b in blocks:
        y = re.match(r"((?:19|20)\d{2})\s+FOMC\s+Meetings", b)
        if not y:
            continue
        year = int(y.group(1))
        for mm in re.finditer(rf"({MONTHS})\s+(\d{{1,2}})(?:\s*[-–/]\s*(?:({MONTHS})\s+)?(\d{{1,2}}))?(\*?)\s*(\(unscheduled\))?", b):
            mon2 = mm.group(3) or mm.group(1)
            day = int(mm.group(4) or mm.group(2))
            try:
                d = datetime.strptime(f"{year} {mon2} {day}", "%Y %B %d").date()
            except ValueError:
                continue
            out.append({"date": d.isoformat(), "heading": f"{year} calendar: {mm.group(0).strip()}", "href": ""})
    return out


def release_time(url: str) -> str:
    pg = get(url)
    m = re.search(r"For (?:immediate )?release at\s*([0-9]{1,2}(?::[0-9]{2})?\s*[ap]\.?\s*m\.?\s*E[DS]T)", pg, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1))
    m = re.search(r"release at\s*([^<\n]{0,40})", pg, re.I)
    return ("?" + strip(m.group(1))[:40]) if m else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--from", dest="y0", type=int, default=1994)
    ap.add_argument("--no-times", action="store_true")
    a = ap.parse_args()
    raw = a.out / "raw"; raw.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(a.y0, 2021):
        url = f"{BASE}/monetarypolicy/fomchistorical{y}.htm"
        pg = get(url)
        (raw / f"fomchistorical{y}.htm").write_text(pg, encoding="utf-8")
        got = parse_meetings(pg, y)
        print(f"{y}: {len(got)} 個聲明日期")
        rows += got
        time.sleep(0.7)
    url = f"{BASE}/monetarypolicy/fomccalendars.htm"
    pg = get(url)
    (raw / "fomccalendars.htm").write_text(pg, encoding="utf-8")
    got = parse_meetings(pg, None)
    have = {r["date"] for r in rows} | {r["date"] for r in got}
    fut = [r for r in parse_future(pg) if r["date"] not in have]
    print(f"日曆頁：{len(got)} 個聲明日期、{len(fut)} 個無連結（未來或未解析）會議")
    rows += got + fut
    rows.sort(key=lambda r: r["date"])
    out_rows = []
    for r in rows:
        t = ""
        if r["href"] and not a.no_times:
            t = release_time(r["href"]); time.sleep(0.7)
        out_rows.append({"date": r["date"], "scheduled_guess": 0 if UNSCHED.search(r["heading"]) else 1, "statement_time_et": t,
                         "heading": r["heading"], "source_url": r["href"], "future": 0 if r["href"] else 1})
        print(f"  {r['date']}  {t:>16}  {r['heading'][:50]}")
    with open(a.out / "fomc_announcements.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys())); w.writeheader(); w.writerows(out_rows)
    by = {}
    for r in out_rows:
        by.setdefault(r["date"][:4], [0, 0])[0 if r["scheduled_guess"] else 1] += 1
    chk = [f"{y}: 排定 {v[0]}，非排定 {v[1]}" + ("" if v[0] == 8 else "  ← 不是 8，請核") for y, v in sorted(by.items())]
    (a.out / "fomc_calendar_check.txt").write_text("\n".join(chk) + "\n", encoding="utf-8")
    print("\n".join(chk))


if __name__ == "__main__":
    main()
