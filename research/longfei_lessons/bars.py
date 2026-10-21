"""[R268] 龍飛陣教學研究：讀 15 分鐘 K 線（HSI 富途存檔、標普／納指 Dukascopy），統一成「每日一串 K 線」。

輸出格式：{日期: [(開始時間, 開, 高, 低, 收), …]}，時間係交易所當地時間（HSI 香港、美股美東），只留正常交易時段：
- HSI 日市 09:15–12:00、13:00–16:30（香港）
- 美股 09:30–16:00（美東）
"""
import gzip
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def load_hsi(path):
    """富途存檔：{日期: [{time_key（K 線完結時間，香港）, open, high, low, close}, …]}。"""
    raw = json.load(open(path))
    out = {}
    for day, bars in raw.items():
        rows = []
        for b in bars:
            end = datetime.strptime(b["time_key"], "%Y-%m-%d %H:%M:%S")
            start = end - timedelta(minutes=15)
            t = start.time()
            if time(9, 15) <= t < time(12, 0) or time(13, 0) <= t < time(16, 30):
                rows.append((start, b["open"], b["high"], b["low"], b["close"]))
        if len(rows) >= 20:
            out[day] = sorted(rows)
    return out


def load_dukascopy(path):
    """Dukascopy CSV（UTC，K 線開始時間）→ 美東正常時段。"""
    out = {}
    with gzip.open(path, "rt") as f:
        next(f)
        for line in f:
            ts, o, h, lo, c, _ = line.rstrip().split(",")
            start = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)
            if time(9, 30) <= start.time() < time(16, 0) and start.weekday() < 5:
                out.setdefault(start.date().isoformat(), []).append((start, float(o), float(h), float(lo), float(c)))
    return {d: sorted(v) for d, v in out.items() if len(v) >= 20}
