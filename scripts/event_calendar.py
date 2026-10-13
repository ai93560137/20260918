"""event_calendar.py — 事件日曆（FUND_SOP 缺口 4）：把散在各處的「會影響持倉的日子」合成一張表。

每日 07:00 HKT，GitHub Actions `event_calendar.yml` 跑，產出（全是公開資訊，進 repo）：
  calendar/events.csv   date,time_hkt,market,category,event,impact,affects,event_week,source
  calendar/WEEK.md      本週與下週一覽（人讀），每週標「事件週」與否

來源：
  * 財經數據：GCS cache/ff_calendar_thisweek.json（Cloud Run 新聞鎖的快取）＋ 下週檔（Actions 直接抓，抓不到就略過）
  * FOMC：外匯分支 data_forex_rates/fomc/fomc_announcements.csv（scheduled=1，14:00 ET 聲明）
  * 假期：蛇蟠分支 universes/calendars/{hk,us,jp}.csv
  * 恒指月結算：GCS futu/calendar/HK.json 的港股交易日 → 每月倒數第二個交易日（扣假期）；沒有就用假期表推
  * 美股期權：每月第三個週五（月度）、每月最後一個美股交易日（EOM）
  * 持倉到期：repo POSITIONS.md「完結」欄
規則（影響哪個陣、事件週定義）在 calendar/rules.json，由風揚陣擁有。

用法：python3 scripts/event_calendar.py [--dry-run] [--now "2026-10-14 07:00"] [--nextweek-json PATH]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops_notify import HKT, gcs_cat, parse_hkt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
PAST_DAYS, AHEAD_DAYS = 7, 35
COLS = ["date", "time_hkt", "market", "category", "event", "impact", "affects", "event_week", "source"]
GC, FX = "claude/gifted-carson-v2tvhw", "claude/forex-data-testing-w4q3m2"


def git_show(branch: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/{branch}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def ev(d: date, time_hkt: str, market: str, category: str, event: str, impact: str, source: str) -> dict:
    return {"date": d.isoformat(), "time_hkt": time_hkt, "market": market, "category": category,
            "event": event, "impact": impact, "affects": "", "event_week": "", "source": source}


# ---------------------------------------------------------------- 來源
def from_forexfactory(docs: list[dict | None], rules: dict) -> list[dict]:
    keep = rules.get("ff_keep") or {}
    out, seen = [], set()
    for doc in docs:
        for e in (doc or {}).get("events") or []:
            imp, cty = e.get("impact"), e.get("country")
            allow = keep.get(imp) or []
            if not ("*" in allow or cty in allow):
                continue
            try:
                t = datetime.fromisoformat(e["date"]).astimezone(HKT)
            except (KeyError, ValueError):
                continue
            key = (t.isoformat(), cty, e.get("title"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ev(t.date(), f"{t:%H:%M}", cty, "數據", e.get("title", ""), imp, "ForexFactory"))
    return out


def from_fomc(csv_text: str | None) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(csv_text or "")):
        if r.get("scheduled") != "1":
            continue
        hhmm = (r.get("statement_time_rule") or "14:00").strip() or "14:00"
        try:
            et = datetime.strptime(f"{r['date']} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        except ValueError:
            continue
        t = et.astimezone(HKT)
        press = "（記者會）" if r.get("press_conference") == "1" or "*" in (r.get("heading") or "") else ""
        out.append(ev(t.date(), f"{t:%H:%M}", "USD", "FOMC", f"FOMC 利率聲明{press}", "High", "外匯分支 fomc_announcements.csv"))
    return out


def holidays(csv_text: str | None) -> dict[date, str]:
    out = {}
    for r in csv.DictReader(io.StringIO(csv_text or "")):
        try:
            out[date.fromisoformat(r["date"])] = r.get("name_zh") or r.get("name") or "假期"
        except (KeyError, ValueError):
            pass
    return out


def from_holidays(h: dict[date, str], market: str) -> list[dict]:
    return [ev(d, "全日", market, f"{market} 假期", f"{market} 休市：{n}", "Holiday", f"{GC} universes/calendars")
            for d, n in h.items()]


def biz_days(year: int, month: int, hol: dict[date, str], trading: set[date] | None) -> list[date]:
    d = date(year, month, 1)
    out = []
    while d.month == month:
        if trading is not None and d in trading:
            out.append(d)
        elif trading is None and d.weekday() < 5 and d not in hol:
            out.append(d)
        d += timedelta(days=1)
    return out


def from_hk_settlement(months: list[tuple[int, int]], hk_hol: dict, hk_trading: set[date] | None) -> list[dict]:
    out = []
    for y, m in months:
        # 富途交易日表只涵蓋約 6 週；該月不完整就退回用假期表推
        tr = hk_trading if hk_trading and any(d.year == y and d.month == m for d in hk_trading) \
            and max(d for d in hk_trading if d.year == y and d.month == m) >= _last_weekday(y, m) - timedelta(days=3) else None
        days = biz_days(y, m, hk_hol, tr)
        if len(days) >= 2:
            out.append(ev(days[-2], "16:00", "HK", "HK 結算", f"恒指／小型恒指 {m} 月期貨及月度期權結算（倒數第二個交易日）",
                          "High", "futu/calendar/HK.json" if tr else "假期表推算"))
    return out


def _last_weekday(y: int, m: int) -> date:
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def from_us_options(months: list[tuple[int, int]], us_hol: dict) -> list[dict]:
    out = []
    for y, m in months:
        d = date(y, m, 1)
        fridays = [d + timedelta(days=i) for i in range(31) if (d + timedelta(days=i)).month == m and (d + timedelta(days=i)).weekday() == 4]
        third = fridays[2]
        if third in us_hol:
            third -= timedelta(days=1)
        quarter = "（季度期貨同日到期）" if m in (3, 6, 9, 12) else ""
        out.append(ev(third, "04:00+1", "US", "US 期權到期", f"美股月度期權到期（第三個週五）{quarter}", "Medium", "規則推算"))
        eom = biz_days(y, m, us_hol, None)[-1]
        out.append(ev(eom, "04:00+1", "US", "US 期權到期", "ES／MES EOM 期權到期（月末交易日）", "Medium", "規則推算"))
    return out


def from_positions(md: str | None) -> list[dict]:
    out = []
    for ln in (md or "").splitlines():
        if not ln.startswith("| ") or ln.startswith("| 陣") or "---" in ln:
            continue
        c = [x.strip() for x in ln.strip("|").split("|")]
        if len(c) < 7 or "持倉" not in c[6]:
            continue
        m = re.search(r"\d{4}-\d{2}-\d{2}", c[5])
        if m:
            hold = c[2].split("（")[0].strip()[:60]
            out.append(ev(date.fromisoformat(m.group(0)), "", "持倉", "持倉到期", f"{c[0]}：{hold}", "High", "POSITIONS.md"))
    return out


# ---------------------------------------------------------------- 規則
def apply_rules(events: list[dict], rules: dict) -> dict:
    for e in events:
        teams = []
        for r in rules.get("affects") or []:
            mt = r.get("match") or {}
            if all((e["market"] if k == "country" else e.get(k)) == v for k, v in mt.items()):
                teams.append(r["teams"])
        e["affects"] = "；".join(dict.fromkeys(teams))
    ew = rules.get("event_week") or {}
    flagged: dict[tuple[int, int], list[str]] = {}
    for e in events:
        d = date.fromisoformat(e["date"])
        if d.weekday() >= 5:
            continue
        hit = e["category"] in (ew.get("categories") or []) or (
            e["category"] == "數據" and e["impact"] == ew.get("ff_min_impact", "High")
            and any(k.lower() in e["event"].lower() for k in ew.get("ff_title_contains") or []))
        if hit:
            flagged.setdefault(d.isocalendar()[:2], []).append(e["event"][:30])
    for e in events:
        wk = date.fromisoformat(e["date"]).isocalendar()[:2]
        e["event_week"] = "Y" if wk in flagged else ""
    return flagged


def build(now: datetime, src: dict, rules: dict) -> tuple[list[dict], dict]:
    today = now.date()
    lo, hi = today - timedelta(days=PAST_DAYS), today + timedelta(days=AHEAD_DAYS)
    months = sorted({(d.year, d.month) for d in (lo + timedelta(days=i) for i in range((hi - lo).days + 1))})
    hk_hol, us_hol, jp_hol = holidays(src.get("hk_hol")), holidays(src.get("us_hol")), holidays(src.get("jp_hol"))
    hk_trading = None
    cal = src.get("hk_trading")
    if isinstance(cal, dict) and cal.get("days"):
        hk_trading = {date.fromisoformat(x) for x in cal["days"]}
    evs = (from_forexfactory([src.get("ff_this"), src.get("ff_next")], rules) + from_fomc(src.get("fomc"))
           + from_holidays(hk_hol, "HK") + from_holidays(us_hol, "US") + from_holidays(jp_hol, "JP")
           + from_hk_settlement(months, hk_hol, hk_trading) + from_us_options(months, us_hol)
           + from_positions(src.get("positions")))
    evs = [e for e in evs if lo <= date.fromisoformat(e["date"]) <= hi]
    evs.sort(key=lambda e: (e["date"], e["time_hkt"] if e["time_hkt"][:1].isdigit() else "00:00", e["market"]))
    flagged = apply_rules(evs, rules)
    return evs, flagged


def to_csv(events: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(events)
    return buf.getvalue()


def week_md(events: list[dict], flagged: dict, now: datetime) -> str:
    today = now.date()
    mon = today - timedelta(days=today.weekday())
    L = [f"# 事件日曆：本週與下週（更新 {now:%Y-%m-%d %H:%M} HKT）", "",
         "> 由 `scripts/event_calendar.py` 每日產生；完整表 `calendar/events.csv`（過去 7 天到未來 35 天）。",
         "> 影響哪個陣、事件週定義在 `calendar/rules.json`（風揚陣擁有）。時間為香港時間；「04:00+1」= 翌日 04:00。", ""]
    for wk_start in (mon, mon + timedelta(days=7)):
        wk = wk_start.isocalendar()[:2]
        title = "本週" if wk_start == mon else "下週"
        tag = f"⚠ 事件週（{'、'.join(dict.fromkeys(flagged[wk]))[:120]}）" if wk in flagged else "非事件週"
        L += [f"## {title} {wk_start:%m-%d}～{wk_start + timedelta(days=6):%m-%d}：{tag}", "",
              "| 日期 | 時間 | 市場 | 類別 | 事件 | 影響 | 影響陣 |", "|---|---|---|---|---|---|---|"]
        in_week = [e for e in events if wk_start <= date.fromisoformat(e["date"]) < wk_start + timedelta(days=7)]
        rows = [e for e in in_week if e["impact"] in ("High", "Holiday") or e["category"] in ("US 期權到期", "持倉到期")]
        for e in rows:
            d = date.fromisoformat(e["date"])
            L.append(f"| {d:%m-%d}（{'一二三四五六日'[d.weekday()]}） | {e['time_hkt']} | {e['market']} | {e['category']} | "
                     f"{e['event']} | {e['impact']} | {e['affects']} |")
        if not rows:
            L.append("| — | | | | 無重要事件 | | |")
        L.append("")
    return "\n".join(L)


def load_sources(nextweek_path: str | None) -> dict:
    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ {a}: {exc}", file=sys.stderr)
            return None
    ff_next = None
    if nextweek_path and Path(nextweek_path).exists():
        try:
            raw = json.loads(Path(nextweek_path).read_text(encoding="utf-8"))
            ff_next = {"events": raw} if isinstance(raw, list) else raw
        except json.JSONDecodeError:
            pass
    pos = ROOT / "POSITIONS.md"
    return {"ff_this": safe(gcs_cat, "cache/ff_calendar_thisweek.json"), "ff_next": ff_next,
            "fomc": git_show(FX, "data_forex_rates/fomc/fomc_announcements.csv"),
            "hk_hol": git_show(GC, "universes/calendars/hk.csv"), "us_hol": git_show(GC, "universes/calendars/us.csv"),
            "jp_hol": git_show(GC, "universes/calendars/jp.csv"),
            "hk_trading": safe(gcs_cat, "futu/calendar/HK.json"),
            "positions": pos.read_text(encoding="utf-8") if pos.exists() else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--nextweek-json", help="ForexFactory 下週檔（Actions 先 curl 下來）")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    rules = json.loads((ROOT / "calendar" / "rules.json").read_text(encoding="utf-8"))
    events, flagged = build(now, load_sources(a.nextweek_json), rules)
    md = week_md(events, flagged, now)
    print(md)
    print(f"\n共 {len(events)} 個事件")
    if not a.dry_run:
        (ROOT / "calendar" / "events.csv").write_text(to_csv(events), encoding="utf-8")
        (ROOT / "calendar" / "WEEK.md").write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
