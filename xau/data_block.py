"""[R348] 美國高影響數據前 N 小時唔開新倉（使用者 10-28「數據之前4小時不入市」，範圍：所有真倉；RISK_LADDER §6d）。
日曆：GCS `ops/us_data_calendar.json`（scripts/us_data_calendar.py，Cloud Scheduler 每 6 小時更新）：
    {"updated_utc": "...Z", "block_hours": 4, "events": [{"t": "2026-10-28T18:00:00Z", "title": "...", "src": "ff|manual"}, ...]}
規則（同 scripts/us_data_calendar.py is_blocked 一致）：事件 t 前 DATA_BLOCK_HOURS 小時 ≤ now < t → 封鎖：921 唔開新倉、空倉唔叫 AI；932 收到開倉訊號唔跟。
已有倉照原有規則（止蝕／移損／平倉）。日曆讀唔到或 updated_utc 舊過 48 小時：照常交易＋Telegram 提醒（每日最多一次）。DATA_BLOCK_HOURS=0 ＝ 關。"""
import calendar
import time

import config
import storage
from storage import StorageError

CAL_OBJECT = "ops/us_data_calendar.json"
CACHE_SEC = 600            # 10 分鐘（Scheduler 每 6 小時先更新）
STALE_SEC = 48 * 3600
_cache = {"ts": 0.0, "doc": None, "error": None}


def _parse_iso(s):
    """'2026-10-28T18:00:00Z' → epoch。壞格式回 None。"""
    try:
        s = str(s).strip().replace("Z", "+00:00")
        tup = time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        return float(calendar.timegm(tup))
    except (ValueError, TypeError):
        return None


def hours():
    return max(0.0, float(getattr(config, "DATA_BLOCK_HOURS", 0.0) or 0.0))


def load(now, force=False):
    """讀日曆（10 分鐘快取）。讀唔到回 None 並記 error。"""
    if not force and _cache["doc"] is not None and now - _cache["ts"] < CACHE_SEC:
        return _cache["doc"]
    if not force and _cache["doc"] is None and _cache["error"] and now - _cache["ts"] < CACHE_SEC:
        return None
    try:
        doc = storage.read_json(CAL_OBJECT, None)
        _cache.update(ts=now, doc=doc if isinstance(doc, dict) else None, error=None if isinstance(doc, dict) else "not a dict")
    except StorageError as exc:
        _cache.update(ts=now, doc=None, error=f"{type(exc).__name__}")
    return _cache["doc"]


def calendar_ok(doc, now):
    """日曆可用：有 events 列表且 updated_utc 唔舊過 48 小時。"""
    if not isinstance(doc, dict) or not isinstance(doc.get("events"), list):
        return False
    up = _parse_iso(doc.get("updated_utc"))
    return up is not None and now - up <= STALE_SEC


def blocked(doc, now, hrs=None):
    """now 喺某事件前 hrs 小時內（唔含事件時刻）→ 回傳 {"t","title","src","ends_ts","mins_left"}，否則 None。關（0 小時）→ None。"""
    h = hours() if hrs is None else hrs
    if h <= 0 or not isinstance(doc, dict):
        return None
    best = None
    for e in doc.get("events") or []:
        t = _parse_iso((e or {}).get("t"))
        if t is None:
            continue
        if t - h * 3600 <= now < t and (best is None or t < best["ends_ts"]):
            best = {"t": e.get("t"), "title": str(e.get("title") or "")[:80], "src": e.get("src"), "ends_ts": t, "mins_left": int(-(-(t - now) // 60))}
    return best


def upcoming(doc, now, n=3):
    out = []
    for e in (doc or {}).get("events") or [] if isinstance(doc, dict) else []:
        t = _parse_iso((e or {}).get("t"))
        if t is not None and t > now:
            out.append({"t": e.get("t"), "title": str(e.get("title") or "")[:60], "src": e.get("src")})
    return sorted(out, key=lambda x: x["t"])[:n]


def check(state, now, day, log=None, tg=None):
    """每根 K 線／心跳叫一次：回傳 (封鎖事件或 None, 狀態 dict)。日曆唔可用就照常交易，並每日最多提醒一次（state["data_cal_warned_day"]）。"""
    doc = load(now)
    ok = calendar_ok(doc, now)
    ev = blocked(doc, now) if ok else None
    if hours() > 0 and not ok and state is not None and state.get("data_cal_warned_day") != day:
        state["data_cal_warned_day"] = day
        why = "讀唔到" if doc is None else ("舊過 48 小時" if isinstance(doc, dict) and doc.get("updated_utc") else "格式唔對")
        msg = f"📅 數據日曆{why}（{CAL_OBJECT}，{_cache.get('error') or (doc or {}).get('updated_utc')}）：照常交易，請檢查 Scheduler zhuge-us-data-calendar"
        if log:
            log(msg, severity="WARNING", component="data_block")
        if tg:
            try:
                tg(msg)
            except Exception:  # noqa: BLE001
                pass
    return ev, {"on": hours() > 0, "hours": hours(), "calendar_ok": ok, "calendar_updated_utc": (doc or {}).get("updated_utc") if isinstance(doc, dict) else None,
                "blocked": ev, "upcoming": upcoming(doc, now) if ok else []}


def text(ev):
    if not ev:
        return "冇"
    return f"{ev['title']}（{str(ev['t'])[11:16]} UTC，仲有 {ev['mins_left']} 分鐘）"
