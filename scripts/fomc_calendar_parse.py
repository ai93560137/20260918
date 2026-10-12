#!/usr/bin/env python3
"""離線解析聯準會 FOMC 頁面（原始 HTML 由 scripts/fomc_calendar_fetch.py 抓回）→ 排定公告日曆 CSV。
登記：forex_research/FOMC_DATA_REQUEST.md 第 2 節。

    python3 scripts/fomc_calendar_parse.py --raw <raw_dir> --vm-csv <fetch 產生的 csv，用其 statement_time_et> --out data_forex_rates/fomc

歷史頁（1994–2020）：每個 <h5> 標題一列，例如「January 30-31 Meeting - 1996」「March 15 (unscheduled) Meeting - 2020」「July 24 Conference Call - 2008」；公告日＝最後一天；
面板內 Statement 連結的 URL 日期若存在則以它為公告日。日曆頁（2021–2027）：每個 fomc-meeting 列（月份＋日期＋年份面板），Statement 的 HTML 連結同上。
聲明時間：VM 逐篇抓到的「For release at」優先（2016 起才有；之前新聞稿寫 For immediate release）；否則用時代規則：
1994–2011-03 14:15；2011-04 → 2012：有記者會 12:30、無 14:15；2013 起 14:00。非排定會議不套規則。
"""
import argparse
import csv
import html
import re
from datetime import date, datetime
from pathlib import Path

MON = "January|February|March|April|May|June|July|August|September|October|November|December"
HEAD = re.compile(rf"({MON})\s+(\d{{1,2}})(?:\s*[-–]\s*(?:({MON})\s+)?(\d{{1,2}}))?\s*(\([^)]*\))?\s*(Meeting|Conference Call|Notation Vote|Teleconference)?[^-]*-\s*((?:19|20)\d{{2}})", re.I)
HEAD2 = re.compile(r"([A-Za-z]{3,9})/([A-Za-z]{3,9})\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(\([^)]*\))?\s*(Meeting|Conference Call)?[^-]*-\s*((?:19|20)\d{2})", re.I)   # 「Jan/Feb 31-1 Meeting - 2017」


def strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")


def classify(label: str) -> tuple[int, str]:
    t = label.lower()
    if "cancel" in t:
        return 0, "cancelled"
    if "unscheduled" in t or "conference call" in t or "notation" in t or "teleconference" in t or "emergency" in t:
        return 0, "unscheduled"
    return 1, ""


def panel_links(seg: str) -> tuple[str, int]:
    """面板片段裡的聲明 URL（優先 .htm 的 Statement／HTML 連結）與是否有記者會。"""
    url = ""
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', seg, re.S | re.I):
        tx = strip(text).strip().lower()
        if re.search(r"(?:19|20)\d{6}", href) and re.search(r"monetary\d{8}[a-c]\.htm|/press/monetary/\d{8}[a-c]\.htm|/fomc/\d{8}default\.htm|/boarddocs/press/(?:general|monetary)/\d{4}/\d{8}", href, re.I) and tx in ("statement", "html", "press release"):
            url = href if href.startswith("http") else "https://www.federalreserve.gov" + href
            break
    pc = 1 if re.search(r"press conference", seg, re.I) else 0
    return url, pc


def parse_historical(h: str) -> list[dict]:
    rows = []
    parts = re.split(r"(<h5[^>]*>.*?</h5>)", h, flags=re.S | re.I)
    for i in range(1, len(parts) - 1, 2):
        title = strip(parts[i]).strip()
        m = HEAD.search(title)
        if m:
            mon1, d1, mon2, d2, label, kind, yr = m.groups()
            mon, day = (mon2 or mon1), int(d2 or d1)
        else:
            m = HEAD2.search(title)
            if not m:
                continue
            _, mon, _, d2, label, kind, yr = m.groups()
            day = int(d2)
        try:
            dt = datetime.strptime(f"{yr} {mon[:3]} {day}", "%Y %b %d").date()
        except ValueError:
            continue
        sched, note = classify(f"{label or ''} {kind or ''}")
        url, pc = panel_links(parts[i + 1])
        u = re.search(r"(?:19|20)\d{6}", url or "")
        if u and sched:                                            # 排定會議以聲明 URL 日期為公告日（兩天會議的第二天）
            dt = datetime.strptime(u.group(0), "%Y%m%d").date()
        if sched and not url and dt.year >= 2000:                 # 1999-05 起每次排定會議都有聲明；沒有連結的「Meeting」是附屬場次（如 2003-09-15）
            sched, note = 0, "no_statement_link"
        rows.append({"date": dt.isoformat(), "scheduled": sched, "press_conference": pc, "heading": title, "source_url": url, "note": note})
    return rows


def parse_calendar(h: str) -> list[dict]:
    rows, year = [], None
    tok = re.compile(r'<h4[^>]*>\s*(?:<a[^>]*>)?\s*((?:19|20)\d{2})\s+FOMC\s+Meetings|<div class="[^"]*row fomc-meeting[^"]*"[^>]*>(.*?)(?=<div class="[^"]*row fomc-meeting|<h4|</div>\s*</div>\s*</div>)', re.S | re.I)
    for m in tok.finditer(h):
        if m.group(1):
            year = int(m.group(1)); continue
        seg = m.group(2)
        mm = re.search(r'fomc-meeting__month[^>]*>(.*?)</div>', seg, re.S | re.I)
        dd = re.search(r'fomc-meeting__date[^>]*>(.*?)</div>', seg, re.S | re.I)
        if not (mm and dd and year):
            continue
        mon_txt, day_txt = strip(mm.group(1)).strip(), strip(dd.group(1)).strip()
        label = " ".join(re.findall(r"\(([^)]*)\)", day_txt))
        mon_m = re.findall(MON, mon_txt + " " + day_txt, re.I)
        mon = mon_m[-1] if mon_m else mon_txt.split("/")[-1].strip()
        days = re.findall(r"\d{1,2}", day_txt)
        if not days:
            continue
        try:
            dt = datetime.strptime(f"{year} {mon[:3]} {int(days[-1])}", "%Y %b %d").date()
        except ValueError:
            continue
        sched, note = classify(label)
        url, pc = panel_links(seg)
        u = re.search(r"(?:19|20)\d{6}", url or "")
        if u and sched:
            dt = datetime.strptime(u.group(0), "%Y%m%d").date()
        rows.append({"date": dt.isoformat(), "scheduled": sched, "press_conference": pc, "heading": f"{year} {mon_txt} {day_txt}", "source_url": url, "note": note or ("future" if not url else "")})
    return rows


def rule_time(d: date, pc: int) -> str:
    if d < date(2011, 4, 1):
        return "14:15"
    if d < date(2013, 1, 1):
        return "12:30" if pc else "14:15"
    return "14:00"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--vm-csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rows = []
    for f in sorted(a.raw.glob("fomchistorical*.htm")):
        rows += parse_historical(f.read_text(encoding="utf-8", errors="ignore"))
    cal = a.raw / "fomccalendars.htm"
    if cal.exists():
        have = {r["date"] for r in rows}
        rows += [r for r in parse_calendar(cal.read_text(encoding="utf-8", errors="ignore")) if r["date"] not in have]
    times = {}
    if a.vm_csv and a.vm_csv.exists():
        for r in csv.DictReader(open(a.vm_csv, encoding="utf-8")):
            if r.get("statement_time_et"):
                times[r["date"]] = r["statement_time_et"]
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["date"]):
        if r["date"] in seen:
            continue
        seen.add(r["date"])
        d = date.fromisoformat(r["date"])
        cap = times.get(r["date"], "")
        r["statement_time_et"] = cap
        r["statement_time_rule"] = rule_time(d, r["press_conference"]) if r["scheduled"] else ""
        out.append(r)
    a.out.mkdir(parents=True, exist_ok=True)
    cols = ["date", "scheduled", "statement_time_et", "statement_time_rule", "press_conference", "heading", "source_url", "note"]
    with open(a.out / "fomc_announcements.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(out)
    by = {}
    for r in out:
        by.setdefault(r["date"][:4], [0, 0])[0 if r["scheduled"] else 1] += 1
    chk = [f"{y}: 排定 {v[0]}，非排定／取消 {v[1]}" + ("" if v[0] == 8 else "  ←") for y, v in sorted(by.items())]
    (a.out / "fomc_calendar_check.txt").write_text("\n".join(chk) + "\n", encoding="utf-8")
    print("\n".join(chk)); print(f"共 {len(out)} 列 → {a.out}")


if __name__ == "__main__":
    main()
