"""[R99] 開市前預測（波幅＋高位／低位）與 12:00、16:30、03:00 三次檢討、交易日曆、報告網址。"""
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
import random
from datetime import date, datetime, timedelta, timezone

random.seed(11)
SYM = "HK.HSI_FRONT"
UTC = timezone.utc


def sessions(n, end="2026-10-02"):
    days, d = [], date.fromisoformat(end)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    out, c = [], 24000.0
    for d in reversed(days):
        rng = abs(random.gauss(420, 120)) + 60
        lo = c - rng * random.random()
        out.append({"time_key": f"{d} 00:00:00", "open": c, "high": round(lo + rng), "low": round(lo),
                    "close": round(lo + rng * random.random()), "volume": 1, "source": "futu_opend:HK.HSImain"})
        c = out[-1]["close"]
    return out


def put(name, obj):
    FAKE[name] = (json.dumps(obj, ensure_ascii=False), FAKE.get(name, (None, 0))[1] + 1)


def hk(s):   # '2026-10-05 08:30' 香港時間 → UTC datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=8))).astimezone(UTC)


def bar(t, o, h, l, c, v=10):
    return {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


FAKE.clear()
put(main.futu_daily_file(SYM), sessions(300))
ref = json.loads(FAKE[main.futu_daily_file(SYM)][0])[-1]["close"]

print("\n=== 開市前預測 ===")
r = main.futu_report(SYM, "preopen", now=hk("2026-10-05 08:30"))
fc = r.get("forecast") or {}
check("08:30 開市前：有波幅與高低位預測", r["status"] == "ok" and fc.get("date") == "2026-10-05"
      and fc["lo"] < fc["range"] < fc["hi"] and fc["low_lo"] <= fc["low"] < ref < fc["high"] <= fc["high_hi"], fc)
check("訊息文字齊全", all(k in r["text"] for k in ("開市前預測", "全日波幅", "高位", "低位", "不是交易建議")), r["text"])
logged = json.loads(FAKE[main.futu_forecast_file(SYM)][0])
check("開市前時段內寫入預測紀錄", len(logged) == 1 and logged[0]["high"] == fc["high"])
r2 = main.futu_report(SYM, "preopen", now=hk("2026-10-05 08:45"))
check("同一天再叫不重寫", json.loads(FAKE[main.futu_forecast_file(SYM)][0]) == logged and r2["forecast"]["made_utc"] == logged[0]["made_utc"])
main.futu_report(SYM, "preopen", now=hk("2026-10-06 01:00"))
check("時段外（前一天夜市未收）只預覽、不記錄", all(e["date"] != "2026-10-06" for e in json.loads(FAKE[main.futu_forecast_file(SYM)][0])))
check("週六沒日曆 → 跳過", main.futu_report(SYM, "preopen", now=hk("2026-10-10 08:30"))["status"] == "skip")
client.post("/", json={"action": "futu_data", "token": "tok", "symbol": SYM, "kline_type": "K_5M", "source": "futu_opend:HK.HSI2610",
                       "data": [bar("2026-10-03 02:55:00", 1, 2, 0.5, 1.5)], "options": [],
                       "trading_calendar": {"from": "2026-10-05", "to": "2026-11-13",
                                            "days": ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]}})
cal = json.loads(FAKE[main.FUTU_CALENDAR_FILE][0])
check("推送封包帶的交易日曆會存下", cal["from"] == "2026-10-05" and "2026-10-06" in cal["days"], cal)
check("日曆上的假期 → 跳過（10-19 重陽補假）",
      main.futu_report(SYM, "preopen", now=hk("2026-10-19 08:30"))["status"] == "skip")
check("日曆上的交易日 → 照做", main.futu_report(SYM, "preopen", now=hk("2026-10-07 08:30"))["status"] == "ok")

print("\n=== 三次檢討 ===")
B = fc["high"]
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-05"), [
    bar("2026-10-05 09:15:00", 0, 0, 0, 0, 0),                                   # 開市前佔位，不算
    bar("2026-10-05 09:20:00", ref, ref + 50, ref - 30, ref + 20),
    bar("2026-10-05 11:55:00", ref + 20, B + 10, ref, ref + 40),                    # 上午越過預測高位
    bar("2026-10-05 12:00:00", ref + 40, ref + 60, ref + 10, ref + 30),
    bar("2026-10-05 14:00:00", ref + 30, ref + 40, fc["low"] - 5, ref - 100),         # 下午跌穿預測低位
    bar("2026-10-05 16:30:00", ref - 100, ref - 50, ref - 120, ref - 60),
    bar("2026-10-05 23:00:00", ref - 60, ref, fc["low_lo"] - 50, ref - 200)])          # 夜市再跌，超出區間
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-06"), [
    bar("2026-10-06 02:55:00", ref - 200, ref - 150, ref - 210, ref - 180),         # 凌晨夜市，仍屬 10-05
    bar("2026-10-06 09:20:00", 1, 99999, 0.5, 1)])                                    # 下一個交易日，不能算進來
noon = main.futu_report(SYM, "noon", now=hk("2026-10-05 13:40"))                     # 排程晚到也只看 12:00 前
check("午市：只算 12:00 前（排程晚到也一樣）", noon["status"] == "ok" and noon["low"] == ref - 30 and noon["high"] == B + 10, noon)
check("午市：寫出已走百分比與越過預測高位", "已走全日預測" in noon["text"] and "已越過預測" in noon["text"], noon["text"])
close = main.futu_report(SYM, "close", now=hk("2026-10-05 16:40"))
check("日市：算到 16:30，跌穿預測低位", close["low"] == fc["low"] - 5 and "已跌穿預測" in close["text"], close["text"])
night = main.futu_report(SYM, "night", now=hk("2026-10-06 03:13"))
check("全日：03:13 算前一個交易日，含凌晨夜市、不含翌日", night["date"] == "2026-10-05" and night["low"] == fc["low_lo"] - 50
      and night["close"] == ref - 180 and night["high"] < 99999, night)
check("全日：報波幅誤差、高低位誤差與是否在區間", "誤差" in night["text"] and "❌ 不在" in night["text"]
      and night["range_in_band"] in (True, False) and "low_error" in night, night["text"])
check("全日：分列日市與夜市高低", "日市 高" in night["text"] and "夜市 高" in night["text"])
rv = json.loads(FAKE[main.futu_review_file(SYM)][0])
check("三次檢討都存下", [e["kind"] for e in rv] == ["noon", "close", "night"], [e["kind"] for e in rv])
main.futu_report(SYM, "night", now=hk("2026-10-06 03:30"))
check("重叫同一次檢討只覆蓋、不重複", len(json.loads(FAKE[main.futu_review_file(SYM)][0])) == 3)
check("沒有 K 線的日子（休市）→ 跳過", main.futu_report(SYM, "noon", now=hk("2026-10-08 12:07"))["status"] == "skip")
check("錯的種類 → error", main.futu_report(SYM, "lunch")["status"] == "error")

print("\n=== 網址與頁面 ===")
t = client.get("/?view=futu_range&report=noon&format=text")
check("format=text 回純文字", t.status_code == 200 and t.headers["Content-Type"].startswith("text/plain"))
j = client.get("/?view=futu_range&report=preopen").get_json()
check("JSON 回狀態", j["status"] in ("ok", "skip"), j)
put(main.futu_daily_file(SYM), json.loads(FAKE[main.futu_daily_file(SYM)][0]) +
    [{"time_key": "2026-10-05 00:00:00", "open": ref, "high": B + 10, "low": fc["low_lo"] - 50, "close": ref - 180, "volume": 1}])
page = client.get("/?view=futu_range").get_data(as_text=True)
check("頁面顯示高低位預測", "高位約" in page and "低位約" in page)
check("頁面顯示最新一天的檢討", "的檢討（12:00／16:30／03:00）" in page and "午市收市檢討" in page and "全日收市檢討" in page)
check("交易日歸屬：凌晨 02:55 屬前一天、09:20 屬當天",
      main.futu_session_of("2026-10-06 02:55:00") == "2026-10-05" and main.futu_session_of("2026-10-06 09:20:00") == "2026-10-06")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
