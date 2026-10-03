"""[R97] 即月期貨日線序列 futu/daily/<代號>.json 與 ?view=futu_range 波幅頁。"""
import json, os, sys, types

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")

import functions_framework                      # noqa: E402  真的載入，別被假模組蓋掉
import google, google.cloud                      # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def exists(self): return self.name in FAKE
    def download_as_text(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0]
    def download_as_bytes(self, *a, **k): return self.download_as_text().encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1
        FAKE[self.name] = (data, gen); self.generation = gen
    def reload(self): self.generation = FAKE.get(self.name, (None, 0))[1]
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
genai = types.ModuleType("google.genai"); genai.Client = lambda *a, **k: None
genai.types = types.SimpleNamespace(); sys.modules["google.genai"] = genai
exc_mod = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
exc_mod.PreconditionFailed = _PC; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod

import main


OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = main.app.test_client()
from datetime import date, timedelta


def day_bars(start, n, base=24000.0, step=10.0, rng=200.0):
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            c = base + step * len(out)
            out.append({"time_key": f"{d} 00:00:00", "open": c - 20, "high": c + rng / 2, "low": c - rng / 2,
                        "close": c, "volume": 1000})
        d += timedelta(days=1)
    return out


def packet(bars, source="futu_opend:HK.HSI2610", symbol="HK.HSI_FRONT", kline="K_SESSION"):
    return {"action": "futu_data", "token": "tok", "source": source, "script_version": "7",
            "symbol": symbol, "kline_type": kline, "timestamp": "2026-10-04 01:00:00", "data": bars, "options": []}


print("\n=== R97：交易日 K（K_SESSION）合併成一條序列 ===")
FAKE.clear()
series = main.futu_daily_file("HK.HSI_FRONT")
r = client.post("/", json=packet(day_bars("2026-09-01", 15)))
check("交易日 K 封包 stored", r.get_json().get("status") == "stored", r.get_json())
check("按日封存在 futu_k_session", any(k.startswith("archive/futu_k_session/HK.HSI_FRONT/") for k in FAKE))
rows = json.loads(FAKE[series][0])
check("寫進 futu/daily/HK.HSI_FRONT.json，日期只留年月日", len(rows) == 15 and rows[0]["time_key"] == "2026-09-01", rows[:1])
check("每列記下合約來源", rows[0]["source"] == "futu_opend:HK.HSI2610")
check("交易日 K 不蓋即時快照", main.FUTU_SNAPSHOT_FILE not in FAKE)
upd = day_bars("2026-09-15", 3, base=99999)
client.post("/", json=packet(upd, source="futu_opend:HK.HSI2611"))
rows = json.loads(FAKE[series][0])
by = {r["time_key"]: r for r in rows}
check("同一天後到的蓋掉、不重複", len(rows) == 15 and by["2026-09-15"]["close"] == 99999
      and by["2026-09-15"]["source"].endswith("2611"), len(rows))
check("依日期排序", [r["time_key"] for r in rows] == sorted(r["time_key"] for r in rows))
client.post("/", json=packet(day_bars("2026-09-01", 3), symbol="US.AAPL"))
check("非 _FRONT 代號不建序列", main.futu_daily_file("US.AAPL") not in FAKE)
client.post("/", json=packet(day_bars("2026-10-01", 2, base=11111), kline="K_DAY"))
check("Futu 自己的日 K（前一晚夜市算今天）不進序列", all(r["close"] != 11111 for r in json.loads(FAKE[series][0])))
client.post("/", json=packet(day_bars("2026-09-01", 3), kline="K_5M"))
check("5 分 K 不進日線序列", len(json.loads(FAKE[series][0])) == 15)

print("\n=== R97：波幅統計 ===")
bars = day_bars("2025-09-01", 300)
stats = main.futu_range_stats(bars, "2026-10-04")
rows, s = stats["rows"], stats["summary"]
check("只留過去一年", rows[0]["date"] >= "2025-10-04" and all(r["date"] >= "2025-10-04" for r in rows), rows[0]["date"])
check("波幅 = 高 − 低", all(abs(r["range"] - 200) < 1e-9 for r in rows))
check("真實波幅含昨收跳空", rows[1]["true_range"] == 200.0)
check("波幅% = 波幅 ÷ 昨收", abs(rows[1]["range_pct"] - round(200 / rows[0]["close"] * 100, 3)) < 1e-9)
check("一年平均、20 日、ATR14", s["avg_range"] == 200 and s["avg_range_20"] == 200 and s["atr_14"] == 200, s)
gap = [dict(b) for b in day_bars("2026-09-01", 3)]
gap[2].update(open=25000, high=25100, low=24950, close=25050)          # 跳空高開
g = main.futu_range_stats(gap, "2026-10-04")["rows"]
check("跳空：真實波幅 > 波幅", g[2]["true_range"] == 25100 - gap[1]["close"] and g[2]["range"] == 150, g[2])
part = main.futu_range_stats(day_bars("2026-09-28", 6), "2026-10-04")      # 最後一根 10-05 > 今天
check("目前交易日以後的一根算交易中、不進平均", part["partial"] and part["summary"]["last_date"] == "2026-10-02"
      and part["rows"][-1]["date"] == "2026-10-05", part["summary"])
check("百分位在 0–100", 0 <= part["summary"]["last_range_percentile"] <= 100)
check("沒有數據不會壞", main.futu_range_stats([], "2026-10-04")["summary"]["avg_range"] is None)
bad = main.futu_range_stats([{"time_key": "x", "open": 1}, *day_bars("2026-09-01", 2)], "2026-10-04")
check("壞列略過", len(bad["rows"]) == 2)

print("\n=== R97：頁面與 JSON ===")
FAKE.clear()
r = client.get("/?view=futu_range")
check("沒數據時頁面 200 並說明怎麼補", r.status_code == 200 and "--backfill" in r.get_data(as_text=True))
client.post("/", json=packet(day_bars("2025-10-01", 260)))
client.post("/", json=packet([{"time_key": "2026-10-03 02:55:00", "open": 1, "high": 2, "low": 0.5,
                                "close": 23845, "volume": 5}], kline="K_5M"))
r = client.get("/?view=futu_range")
html_text = r.get_data(as_text=True)
check("頁面 200", r.status_code == 200, r.status_code)
check("有最新 OHLC、圖、表", "最新交易日" in html_text and "<svg" in html_text and "每日 OHLC 與波幅" in html_text)
check("顯示合約與最新 5 分 K", "HK.HSI2610" in html_text and "23,845" in html_text)
check("hsi_range 是同一頁", client.get("/?view=hsi_range").status_code == 200)
j = client.get("/?view=futu_range&format=json").get_json()
check("JSON 有 rows 與 summary", j["status"] == "ok" and j["rows"] and j["summary"]["avg_range"] == 200, j.get("summary"))
check("JSON 帶合約與最新 5 分 K", j["contract"] == "HK.HSI2610" and j["latest_5m"]["close"] == 23845)
check("控制台的 Futu 區塊連到波幅頁", "?view=futu_range" in main.futu_dashboard_html())
check("八頁導覽列不變（站內頁另有一致性檢查）", "futu_range" not in str(main.PAGE_LINKS))
e = client.get("/?view=futu_range&symbol=<script>").get_data(as_text=True)
check("代號會跳脫", "<script>" not in e)

from datetime import datetime as _dt, timezone as _tz
check("交易日：香港 08:59 算前一天、09:00 起算當天",
      main.futu_session_today(_dt(2026, 10, 6, 0, 59, tzinfo=_tz.utc)) == "2026-10-05"     # 香港 08:59
      and main.futu_session_today(_dt(2026, 10, 6, 1, 0, tzinfo=_tz.utc)) == "2026-10-06"  # 香港 09:00
      and main.futu_session_today(_dt(2026, 10, 5, 18, 30, tzinfo=_tz.utc)) == "2026-10-05")  # 香港 02:30 夜市

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
