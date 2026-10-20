"""純邏輯：K 線驗證／累積、ATR、黃金交易時段、紐約交易日。冇 I/O。"""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config

NY = ZoneInfo("America/New_York")
HK = ZoneInfo("Asia/Hong_Kong")


def now_ts():
    import time
    return time.time()


def to_float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_bar(ohlc):
    """EA 送嘅 K 線（is_new_bar 時係剛收盤嗰根）。無效回 None。"""
    if not isinstance(ohlc, dict):
        return None
    t = to_float(ohlc.get("time"))
    v = {k: to_float(ohlc.get(k)) for k in ("open", "high", "low", "close")}
    if t is None or t <= 0 or any(x is None or x <= 0 for x in v.values()):
        return None
    if v["high"] < max(v["open"], v["close"]) - 1e-6 or v["low"] > min(v["open"], v["close"]) + 1e-6:
        return None
    return {"time": int(t), **v}


def ingest(history, bar, max_len, gap_reset_sec):
    """回傳 (新歷史, 係咪新 K 線)。亂序忽略；同一根內容變咗就覆蓋（唔算新）；缺口太大就重新累積。"""
    history = [b for b in (history or []) if isinstance(b, dict) and "time" in b]
    if history:
        last = history[-1]["time"]
        if bar["time"] < last:
            return history, False
        if bar["time"] == last:
            if history[-1] == bar:
                return history, False
            history[-1] = bar
            return history, False
        if bar["time"] - last > gap_reset_sec:
            history = []
    history.append(bar)
    return history[-max_len:], True


def merge_bars(history, bars, max_len):
    """合併歷史（EA 回填／由 M1 砌出嚟嘅 M15）：按 time 去重，後者覆蓋，排序後只留最近 max_len 根。"""
    by_time = {b["time"]: b for b in (history or []) if isinstance(b, dict) and "time" in b}
    for b in bars or []:
        if isinstance(b, dict) and "time" in b:
            by_time[b["time"]] = b
    return [by_time[t] for t in sorted(by_time)][-max_len:]


def m15_from_m1(m1):
    """由 M1 砌 M15：只用完整嘅 15 根（同一個 15 分鐘格、時間連續）；唔夠 15 根嗰格唔要。"""
    groups = {}
    for b in m1 or []:
        if not isinstance(b, dict) or "time" not in b:
            continue
        groups.setdefault(int(b["time"]) // 900 * 900, []).append(b)
    out = []
    for t0 in sorted(groups):
        g = sorted(groups[t0], key=lambda x: x["time"])
        if len(g) != 15 or [x["time"] for x in g] != [t0 + 60 * k for k in range(15)]:
            continue
        out.append({"time": t0, "open": g[0]["open"], "high": max(x["high"] for x in g),
                    "low": min(x["low"] for x in g), "close": g[-1]["close"]})
    return out


def parse_hist(rows):
    """EA 回填 [[time,open,high,low,close],…] → 乾淨 K 線列表（壞嘅跳過）。"""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, (list, tuple)) and len(r) >= 5:
            r = {"time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]}
        b = parse_bar(r)
        if b:
            out.append(b)
    return out


def wilder_atr(bars, length=14):
    if len(bars) < length + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:length]) / length
    for tr in trs[length:]:
        atr = (atr * (length - 1) + tr) / length
    return round(atr, 4)


def is_gold_market_open(now_ts):
    """CME／券商黃金：週日 18:00 紐約開，週五 17:00 收；平日 17:00–18:00 休市。假期未處理。"""
    ny = datetime.fromtimestamp(now_ts, NY)
    wd, h = ny.weekday(), ny.hour
    if wd == 5:
        return False
    if wd == 4 and h >= 17:
        return False
    if wd == 6 and h < 18:
        return False
    if wd in (0, 1, 2, 3) and h == 17:
        return False
    return True


def ny_date(now_ts):
    """紐約交易日（17:00 換日，同 CME 一致）。"""
    ny = datetime.fromtimestamp(now_ts, NY)
    if ny.hour >= 17:
        from datetime import timedelta
        ny = ny + timedelta(days=1)
    return ny.strftime("%Y-%m-%d")


def ny_day_start_ts(now_ts):
    """今個紐約交易日嘅開始（前一日 17:00 ET）。"""
    from datetime import timedelta
    ny = datetime.fromtimestamp(now_ts, NY)
    start = ny.replace(hour=17, minute=0, second=0, microsecond=0)
    if ny.hour < 17:
        start -= timedelta(days=1)
    return start.timestamp()


def is_night(now_ts):
    """夜盤（亞洲時段薄）：紐約 18:00–02:00 ET。"""
    h = datetime.fromtimestamp(now_ts, NY).hour
    return h >= 18 or h < 2


def key_expiry(now_ts, text=None):
    """API key 到期：回傳 (到期 ts, 剩餘日數) 或 (None, None)。格式 YYYY-MM-DD[ HH:MM]（UTC）。"""
    text = (config.KEY_EXPIRES_UTC if text is None else text).strip()
    if not text:
        return None, None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            ts = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
            return ts, (ts - now_ts) / 86400
        except ValueError:
            continue
    return None, None


def fmt_utc(ts, fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt)


def fmt_hkt(ts, fmt="%m-%d %H:%M"):
    return datetime.fromtimestamp(ts, HK).strftime(fmt)


def session_text(now_ts):
    ny = datetime.fromtimestamp(now_ts, NY)
    hk = datetime.fromtimestamp(now_ts, HK)
    h = ny.hour
    if 8 <= h < 12:
        sess = "New York morning (London overlap until 11:00 ET, most liquid)"
    elif 12 <= h < 17:
        sess = "New York afternoon (thinner after 13:30 ET)"
    elif 2 <= h < 8:
        sess = "London session"
    elif 18 <= h or h < 2:
        sess = "Asia session (thin, range-bound tendency)"
    else:
        sess = "daily break 17:00-18:00 ET"
    return f"{ny.strftime('%a %Y-%m-%d %H:%M')} ET / {hk.strftime('%H:%M')} HKT — {sess}"
