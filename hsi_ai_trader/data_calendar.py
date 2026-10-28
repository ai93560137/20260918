"""[R348] 美國高影響數據日曆：使用者 10-28「數據之前4小時不入市」（範圍：所有真倉，RISK_LADDER §6d）。

VM 冇直接讀 GCS 嘅權限，所以喺部機自己砌同 GCS ops/us_data_calendar.json 一樣嘅日曆：
  - ops/us_data_manual.json（repo 入面，部機每 10 分鐘 git 拉；FOMC 等預先知道嘅）
  - ForexFactory 本週／下週 USD High（每 FF_REFRESH_H 小時抓一次，結果 cache 喺 AI_DATA_DIR/us_data_ff.json）
解析、合併、封鎖判斷全部用 scripts/us_data_calendar.py 嘅 parse_ff／merge／is_blocked，規則同總指揮一致。
FF 讀唔到就用 cache；cache 舊過 STALE_H 小時（或者 manual 都讀唔到）→ warn，照常交易（唔好靜靜雞停晒）。
"""
import importlib.util
import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("data_calendar")

REPO = Path(__file__).resolve().parent.parent
FF_REFRESH_H = 6
STALE_H = 48
RELOAD_MIN = 10


def _ref():
    spec = importlib.util.spec_from_file_location("us_data_calendar", REPO / "scripts" / "us_data_calendar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REF = _ref()


def fetch_ff():
    """回傳 USD High 事件清單；本週讀唔到就 raise（下週檔週初常常未出，唔計失敗）。"""
    events = []
    for name, url in REF.FF_URLS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "zhuge-calendar/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                events += REF.parse_ff(json.loads(r.read().decode("utf-8")))
        except Exception:  # noqa: BLE001
            if name == "ff_thisweek":
                raise
    return events


class DataCalendar:
    def __init__(self, cache_file: Path, manual_file: Path = REF.MANUAL_PATH, fetch=fetch_ff):
        self.cache_file, self.manual_file, self.fetch = cache_file, manual_file, fetch
        self.doc, self.warn, self.loaded = None, None, None

    def _cache(self):
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def refresh(self, now):
        cache = self._cache()
        ok_t = cache.get("ok_utc")
        last_try = cache.get("try_utc")
        due = not last_try or now - datetime.fromisoformat(last_try) >= timedelta(hours=FF_REFRESH_H)
        if due:
            cache["try_utc"] = now.isoformat()
            try:
                cache.update(events=self.fetch(), ok_utc=now.isoformat())
                ok_t = cache["ok_utc"]
            except Exception as e:  # noqa: BLE001
                log.warning("ForexFactory 讀唔到：%s", e.__class__.__name__)
            try:
                self.cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            except OSError:
                log.exception("寫日曆 cache 失敗")
        warn = []
        try:
            manual = json.loads(self.manual_file.read_text(encoding="utf-8")).get("events", [])
        except (OSError, ValueError):
            manual = []
            warn.append("讀唔到 ops/us_data_manual.json")
        if not ok_t:
            warn.append("ForexFactory 從未讀到")
        elif now - datetime.fromisoformat(ok_t) > timedelta(hours=STALE_H):
            warn.append(f"ForexFactory 上次讀到係 {ok_t[:16]}Z（超過 {STALE_H} 小時）")
        self.doc = {"updated_utc": ok_t, "events": REF.merge(cache.get("events", []), manual, now)}
        self.warn = "；".join(warn) or None
        self.loaded = now

    def blocked(self, now, hours):
        """封鎖中就回傳 {"t","title"}；hours=0 唔封鎖。每 RELOAD_MIN 分鐘重讀一次。"""
        if not hours:
            return None
        if self.loaded is None or now - self.loaded >= timedelta(minutes=RELOAD_MIN):
            try:
                self.refresh(now.astimezone(timezone.utc))
            except Exception as e:  # noqa: BLE001
                log.exception("數據日曆出錯")
                self.warn, self.loaded = f"日曆出錯：{e.__class__.__name__}", now
        return REF.is_blocked(self.doc, now.astimezone(timezone.utc), hours)
