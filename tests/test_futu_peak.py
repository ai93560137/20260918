"""[R101] 今日／本週／本月高低位是否已出現：A 耗盡回落、B 機率法、C 時間點，通知紀錄與報告。"""
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



print("\n=== 剩餘變異比例 ===")
check("09:00 → 幾乎全部（比例四捨五入，加起來約 1）", abs(main.peak_remaining_share("2026-10-05 09:00:00") - 1.0) < 1e-3)
check("03:00 → 0", main.peak_remaining_share("2026-10-06 03:00:00") == 0)
mid = main.peak_remaining_share("2026-10-05 16:30:00")
check("16:30 → 只剩夜市（約四成）", 0.3 < mid < 0.5, mid)
check("越晚越少", main.peak_remaining_share("2026-10-05 12:00:00") > mid > main.peak_remaining_share("2026-10-05 23:00:00"))

print("\n=== 今日：高位在早上，之後一路跌 ===")
FAKE.clear()
put(main.futu_daily_file(SYM), sessions(300))              # 到 10-02（週五）
ref = json.loads(FAKE[main.futu_daily_file(SYM)][0])[-1]["close"]
put(main.FUTU_CALENDAR_FILE, {"from": "2026-10-05", "to": "2026-11-13",
                              "days": ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]})
rng = main.futu_peak_status(SYM, now=hk("2026-10-05 08:00"))
check("開市前：今日還沒有 K 線 → 不列今日", rng is not None and "day" not in rng["periods"], rng and list(rng["periods"]))
day_bars = [bar("2026-10-05 09:20:00", ref, ref + 300, ref - 20, ref + 250)]
p = ref + 250
for i, t in enumerate(["10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "16:30"]):
    p -= 60
    day_bars.append(bar(f"2026-10-05 {t}:00", p + 60, p + 70, p - 10, p))
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-05"), day_bars)
st = main.futu_peak_status(SYM, now=hk("2026-10-05 16:35"))
d = st["periods"]["day"]
check("今日高位 = 早上的高", d["high"]["ext"] == ref + 300 and d["high"]["dist"] == ref + 300 - p, d["high"])
check("回落大：A 觸發", d["high"]["A"] is True, (d["R"], d["high"]))
check("16:30 回落 ≥ 0.4R̂：C 觸發", d["high"]["C"] is True)
check("B 機率很小", d["high"]["prob"] < 0.05 and d["high"]["B"] is True, d["high"]["prob"])
check("低位在最後：都不觸發", not d["low"]["A"] and not d["low"]["B"] and d["low"]["dist"] == 10, d["low"])
st_early = main.futu_peak_status(SYM, now=hk("2026-10-05 12:05"))
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-05"), [b for b in day_bars if b["time_key"] <= "2026-10-05 12:00:00"])
st_noon = main.futu_peak_status(SYM, now=hk("2026-10-05 12:05"))
check("12:00 時 C 未到", st_noon["periods"]["day"]["high"]["C"] is None)
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-05"), day_bars)

print("\n=== 通知紀錄 ===")
main.futu_peak_update(SYM, now=hk("2026-10-05 16:35"))
sig = json.loads(FAKE[main.futu_signal_file(SYM)][0])
ids = {e["id"] for e in sig}
check("今日高位 A、B、C 各一則", {"day:2026-10-05:high:A", "day:2026-10-05:high:B", "day:2026-10-05:high:C"} <= ids, ids)
check("[R102] 通知開頭有陣名", sig[0]["text"].startswith("⚠️【風揚陣】"), sig[0]["text"][:20])
check("訊息含高位、現價、機率、回測準確率", all(k in sig[0]["text"] for k in ("高位可能已出現", "現價", "機率", "回測", "不是交易建議")), sig[0]["text"])
main.futu_peak_update(SYM, now=hk("2026-10-05 16:40"))
check("同一段同一邊同一策略只記一次", len(json.loads(FAKE[main.futu_signal_file(SYM)][0])) == len(sig))
rep = client.get("/?view=futu_range&report=signals").get_json()
check("排程取得未發通知", rep["status"] == "ok" and {s["id"] for s in rep["signals"]} == ids)
first = rep["signals"][0]["id"]
client.get(f"/?view=futu_range&report=signals&ack={first}")
rep2 = client.get("/?view=futu_range&report=signals").get_json()
check("ack 後不再出現", first not in {s["id"] for s in rep2["signals"]} and len(rep2["signals"]) == len(ids) - 1)

print("\n=== 收市後與週末 ===")
st_end = main.futu_peak_status(SYM, now=hk("2026-10-06 03:30"))
check("翌日 03:00 後今日已結束，不再發今日通知", st_end["periods"]["day"]["over"] is True)
before = len(json.loads(FAKE[main.futu_signal_file(SYM)][0]))
main.futu_peak_update(SYM, now=hk("2026-10-06 03:30"))
after = json.loads(FAKE[main.futu_signal_file(SYM)][0])
check("已結束的今日沒有新通知", not any(e["id"].startswith("day:2026-10-05:low") for e in after))
check("本週還有 4 個交易日：沒結束", st_end["periods"]["week"]["over"] is False and st_end["periods"]["week"]["sessions"] == 5,
      st_end["periods"]["week"])

print("\n=== 本週 C：第 4 個交易日收市 ===")
FAKE.clear()
put(main.FUTU_CALENDAR_FILE, {"from": "2026-09-28", "to": "2026-11-13",
                              "days": ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-02", "2026-10-05"]})
ser = sessions(300, end="2026-09-30")
ref = ser[-1]["close"]
put(main.futu_daily_file(SYM), ser)
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-02"), [bar("2026-10-02 09:20:00", ref, ref + 10, ref - 900, ref - 880)])
st_w = main.futu_peak_status(SYM, now=hk("2026-10-02 12:00"))
w = st_w["periods"]["week"]
check("本週（09-28 至 10-02，國慶 10-01 休市）共 4 個交易日、已完結 3 個", w["sessions"] == 4 and w["sessions_done"] == 3, w)
check("第 4 個交易日（今天）未收市 → C 未到", w["high"]["C"] is None)
st_w2 = main.futu_peak_status(SYM, now=hk("2026-10-03 03:30"))
check("週五夜市收市後：本週已結束，不發通知", st_w2["periods"]["week"]["over"] is True)

print("\n=== 報告與頁面 ===")
FAKE.clear()
put(main.futu_daily_file(SYM), sessions(300))
ref = json.loads(FAKE[main.futu_daily_file(SYM)][0])[-1]["close"]
put(main.archive_blob_name("futu_k_5m", SYM, "2026-10-05"), [bar("2026-10-05 09:20:00", ref, ref + 300, ref - 20, ref + 250)]
    + [bar(f"2026-10-05 {t}:00", ref + 200, ref + 210, ref - 10, ref) for t in ("11:00", "12:00")])
noon = main.futu_report(SYM, "noon", now=hk("2026-10-05 12:07"))
check("午市檢討附三個策略現況", "高低位是否已出現" in noon["text"] and "今日" in noon["text"] and "本週" in noon["text"], noon["text"])
pre = main.futu_report(SYM, "preopen", now=hk("2026-10-06 07:53"))
check("開市前預測附本週／本月現況", "本週" in pre["text"] and "本月" in pre["text"], pre["text"])
page = client.get("/?view=futu_range").get_data(as_text=True)
check("頁面有高低位是否已出現區塊", "高低位是否已出現" in page)
check("[R102] 訊息與頁面都有陣名", noon["text"].startswith("🕛【風揚陣】") and pre["text"].startswith("📏【風揚陣】")
      and "風揚陣・即月期貨波幅" in page)
calls = []
orig = main.futu_peak_update
main.futu_peak_update = lambda symbol, now=None: calls.append(symbol) or []
client.post("/", json={"action": "futu_data", "token": "tok", "symbol": SYM, "kline_type": "K_5M", "source": "futu_opend:HK.HSI2610",
                       "data": [bar("2026-10-05 12:00:00", 1, 2, 0.5, 1.5)], "options": []})
client.post("/", json={"action": "futu_data", "token": "tok", "symbol": SYM, "kline_type": "K_SESSION", "source": "x",
                       "data": [bar("2026-10-05 00:00:00", 1, 2, 0.5, 1.5)], "options": []})
client.post("/", json={"action": "futu_data", "token": "tok", "symbol": "US.QQQ", "kline_type": "K_5M", "source": "x",
                       "data": [bar("2026-10-05 12:00:00", 1, 2, 0.5, 1.5)], "options": []})
main.futu_peak_update = orig
check("只有即月期貨的 5 分 K 會觸發重算", calls == [SYM], calls)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
