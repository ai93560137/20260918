"""[R368] 921 逆 H4 唔做多（使用者 11-02「A，逆 H4 唔做多，寫程式」；依據 REVIEW_921_1102、IDEAS #211）。
H4 EMA50 斜率＝最後一根已收市 H4（22:00 UTC 對齊）嘅 EMA50 減上一根；同 research filter_921.H4Slope／g7_live.signal 一樣。
M1 來源（逐日合併，同一分鐘只留一根）：本服務 xau/bars/、訊號書 xau/sig/bars/、券商 MT5 歷史 xau/sig/mt5m1/；讀 XAU_H4_LOOKBACK_DAYS 日。
每根 H4 只計一次（同一個實例快取）；數據唔夠回 None（呼叫方照開，唔擋）。"""
import datetime as dt

import config
import g7_live
import storage
from storage import StorageError

_CACHE = {"h4": None, "slope": None, "n": 0}
_DAY = {}


def _prefixes():
    return [config.PREFIX + "bars/", config.MAIN_PREFIX + "sig/bars/"], config.MAIN_PREFIX + "sig/mt5m1/"


def _day_rows(day, today):
    if day in _DAY and day < today:
        return _DAY[day]
    bars_prefixes, mt5 = _prefixes()
    by = {}
    try:
        doc = storage.read_json(f"{mt5}{day}.json", None)
    except StorageError:
        doc = None
    if isinstance(doc, list):
        for x in doc:
            if isinstance(x, (list, tuple)) and len(x) >= 5:
                by[int(x[0])] = (int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]))
    for pre in bars_prefixes:
        try:
            doc = storage.read_json(f"{pre}{day}.jsonl", None)
        except StorageError:
            doc = None
        if isinstance(doc, list):
            for b in doc:
                if isinstance(b, dict) and (b.get("time") is not None or b.get("utc") is not None):
                    try:
                        u = g7_live.broker_utc(b["time"]) if b.get("time") is not None else int(b["utc"])
                        by[u] = (u, float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
                    except (KeyError, TypeError, ValueError):
                        continue
    rows = [by[k] for k in sorted(by)]
    if day < today:
        _DAY[day] = rows
    return rows


def load_m1(now, days=None):
    days = config.H4_LOOKBACK_DAYS if days is None else days
    d1 = dt.datetime.fromtimestamp(now, dt.timezone.utc).date(); today = d1.isoformat()
    by = {}
    for k in range(days + 1, -2, -1):
        for b in _day_rows((d1 - dt.timedelta(days=k)).isoformat(), today):
            by[b[0]] = b
    return g7_live.drop_flat([by[t] for t in sorted(by) if t + 60 <= now])


def slope_from_m1(m1, now):
    """回傳 (斜率 或 None, 最後已收市 H4 開盤 key, 已收市 H4 根數)。"""
    rows = [b for b in m1 if b[0] + 60 <= now]
    h4 = [b for b in g7_live.aggregate(rows, 4 * 3600, g7_live.H4_SHIFT) if b[0] + 4 * 3600 <= now]
    if len(h4) < 51:
        return None, (h4[-1][0] if h4 else None), len(h4)
    e = g7_live.ema([b[4] for b in h4], 50)
    return e[-1] - e[-2], h4[-1][0], len(h4)


def current_h4_key(now):
    s = 4 * 3600
    return (int(now) - g7_live.H4_SHIFT) // s * s + g7_live.H4_SHIFT - s      # 最後一根已收市 H4 嘅開盤


def slope(now):
    """有快取：同一根已收市 H4 只計一次。"""
    key = current_h4_key(now)
    if _CACHE["h4"] == key and _CACHE["slope"] is not None:
        return _CACHE["slope"]
    s, k, n = slope_from_m1(load_m1(now), now)
    _CACHE.update(h4=k if s is not None else None, slope=s, n=n)
    return s


def block_reason(action, now, mode=None, slope_fn=None):
    """mode：off／long（逆 H4 唔做多）／both（再加逆 H4 唔做空）。回傳擋單原因或 None；斜率計唔到唔擋。"""
    mode = (config.H4_TREND_FILTER if mode is None else mode).lower()
    if mode not in ("long", "both") or config.SIGNAL_BOOK or action not in ("OPEN_LONG", "OPEN_SHORT"):
        return None
    s = (slope_fn or slope)(now)
    if s is None:
        return None
    if action == "OPEN_LONG" and s < 0:
        return f"逆 H4 唔做多：H4 EMA50 斜率 {s:+.3f}（向下）"
    if action == "OPEN_SHORT" and mode == "both" and s > 0:
        return f"逆 H4 唔做空：H4 EMA50 斜率 {s:+.3f}（向上）"
    return None


def status():
    return {"mode": config.H4_TREND_FILTER, "slope": None if _CACHE["slope"] is None else round(_CACHE["slope"], 4),
            "h4_utc": _CACHE["h4"], "h4_bars": _CACHE["n"]}
