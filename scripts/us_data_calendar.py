"""us_data_calendar.py — 美國高影響數據日曆（R348，使用者 10-28「數據之前4小時不入市」，範圍：所有真倉）。

來源：ForexFactory 公開 JSON（本週＋下週，country=USD、impact=High）＋ ops/us_data_manual.json（FOMC 等預先知道嘅）。
輸出：GCS ops/us_data_calendar.json（只准寫 ops/），各陣真倉程式讀呢個檔決定「數據前 N 小時唔開新倉」：

    {"updated_utc": "...", "block_hours": 4, "sources": {...},
     "events": [{"t": "2026-10-28T18:00:00Z", "title": "...", "src": "ff|manual"}, ...]}

規則（各陣實作要一致，見 is_blocked()）：
  - 事件時間 t 前 block_hours 小時至 t（唔含 t）之間：唔開新倉；已有倉照原有規則管理（止蝕／移損／平倉照做）。
  - 日曆讀唔到或者 updated_utc 舊過 48 小時：照常交易，但要發 Telegram 提醒（唔好靜靜雞停晒）。
  - ForexFactory 冇時間嘅事件（All Day／Tentative）唔計，靠 manual 補。

用法：
    python3 scripts/us_data_calendar.py [--dry-run]     # 抓取、合併、寫 GCS（dry-run 只印）
排程：Cloud Scheduler zhuge-us-data-calendar（ops/scheduler_jobs.json）→ workflow us_data_calendar.yml。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FF_URLS = {"ff_thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
           "ff_nextweek": "https://nfs.faireconomy.media/ff_calendar_nextweek.json"}
MANUAL_PATH = ROOT / "ops" / "us_data_manual.json"
GCS_OBJECT = "ops/us_data_calendar.json"
BLOCK_HOURS = 4
KEEP_PAST = timedelta(days=2)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ff(items: list) -> list[dict]:
    """ForexFactory 清單 → USD High 事件（UTC）。午夜 00:00 當地時間＝All Day／Tentative，唔計。"""
    out = []
    for it in items or []:
        if it.get("country") != "USD" or str(it.get("impact", "")).lower() != "high":
            continue
        try:
            dt = datetime.fromisoformat(str(it["date"]))
        except (KeyError, ValueError):
            continue
        if dt.tzinfo is None or (dt.hour == 0 and dt.minute == 0):
            continue
        out.append({"t": _iso(dt), "title": str(it.get("title", ""))[:80], "src": "ff"})
    return out


def merge(ff: list[dict], manual: list[dict], now: datetime) -> list[dict]:
    """合併去重（同一分鐘同一來源類型當一件），刪走 KEEP_PAST 之前嘅，按時間排。"""
    seen, out = set(), []
    for e in ff + [dict(m, src="manual") for m in manual]:
        try:
            t = datetime.fromisoformat(e["t"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if t < now - KEEP_PAST:
            continue
        key = (_iso(t), e.get("title", "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"t": _iso(t), "title": e.get("title", ""), "src": e.get("src", "ff")})
    return sorted(out, key=lambda e: e["t"])


def is_blocked(doc: dict | None, now: datetime, hours: float | None = None) -> dict | None:
    """參考實作：now 喺某事件前 hours 小時內（唔含事件時刻）→ 回傳該事件，否則 None。"""
    if not doc:
        return None
    h = timedelta(hours=hours if hours is not None else doc.get("block_hours", BLOCK_HOURS))
    for e in doc.get("events", []):
        t = datetime.fromisoformat(e["t"].replace("Z", "+00:00"))
        if t - h <= now < t:
            return e
    return None


def fetch_ff() -> tuple[list[dict], dict]:
    import requests
    events, status = [], {}
    for name, url in FF_URLS.items():
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "zhuge-calendar/1.0"})
            if r.status_code != 200:
                status[name] = f"HTTP {r.status_code}"
                continue
            got = parse_ff(r.json())
            events += got
            status[name] = f"ok {len(got)}"
        except Exception as exc:  # noqa: BLE001 — 下週檔週初常常未出，唔好令成個 job 失敗
            status[name] = f"error {type(exc).__name__}"
    return events, status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    ff, status = fetch_ff()
    manual = json.loads(MANUAL_PATH.read_text(encoding="utf-8")).get("events", [])
    events = merge(ff, manual, now)
    doc = {"updated_utc": _iso(now), "block_hours": BLOCK_HOURS, "sources": status, "events": events}
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    print(text)
    if not status.get("ff_thisweek", "").startswith("ok"):
        print("⚠ ForexFactory 本週讀唔到，只用 manual", file=sys.stderr)
    if not a.dry_run:
        from ops_notify import gcs_put
        gcs_put(GCS_OBJECT, text)
        print(f"已寫 GCS {GCS_OBJECT}（{len(events)} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
