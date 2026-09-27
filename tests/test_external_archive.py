"""[R84] `gunicorn main:app` 這條路也要能跑（buildpack 沒拿到 entry point 時的退路）。"""
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
    def list_blobs(self, prefix="", match_glob=None):
        import fnmatch
        return [_Blob(n) for n in sorted(FAKE) if n.startswith(prefix)
                and (match_glob is None or fnmatch.fnmatch(n, match_glob))]
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
from datetime import datetime, timezone

main.macro_news_session.status = lambda now=None: {"locked": False, "known": True, "reason": "test",
                                                   "events": [], "warnings": [], "warning": None}
OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = main.app.test_client()
def rows(name): return json.loads(FAKE[name][0])

print("\n=== R95：MT5 M1 按日封存（券商伺服器日期）===")
FAKE.clear()
t0 = int(datetime(2026, 9, 25, 23, 58, tzinfo=timezone.utc).timestamp())   # 伺服器時間 23:58
for i in range(4):                                                          # 23:58, 23:59, 00:00, 00:01
    main.archive_mt5_bar({"time": t0 + 60 * i, "open": 3700 + i, "high": 3701 + i, "low": 3699 + i, "close": 3700.5 + i})
main.archive_mt5_bar({"time": t0, "open": 3700, "high": 3701, "low": 3699, "close": 3700.5})   # 重送同一根
d1 = main.archive_blob_name("mt5_m1", "XAUUSD", "2026-09-25")
d2 = main.archive_blob_name("mt5_m1", "XAUUSD", "2026-09-26")
check("跨日切成兩個檔", d1 in FAKE and d2 in FAKE, sorted(FAKE))
check("前一日 2 根、重送不重複", len(rows(d1)) == 2, rows(d1))
check("後一日 2 根", len(rows(d2)) == 2)
r0 = rows(d1)[0]
check("伺服器時間與 UTC 都記下", r0["time_server"] == "2026-09-25 23:58:00" and r0["time_utc"].startswith("2026-09-25 2"), r0)
gen = FAKE[d1][1]
main.archive_mt5_bar({"time": t0, "open": 3700, "high": 3701, "low": 3699, "close": 3700.5})
check("內容沒變就不寫入", FAKE[d1][1] == gen)

print("\n=== R95：封存失敗不能擋交易 ===")
orig = main.gcs_update
def boom(*a, **k): raise main.StorageError("down")
main.gcs_update = boom
try:
    main.archive_mt5_bar({"time": t0, "open": 1, "high": 1, "low": 1, "close": 1}); ok = True
except Exception as exc:
    ok = False
main.gcs_update = orig
check("GCS 掛了也不丟例外", ok)

print("\n=== R95：process_m1_bar 真的會封存 ===")
FAKE.clear()
called = []
orig_arch = main.archive_mt5_bar
main.archive_mt5_bar = lambda bar, symbol="XAUUSD": called.append(bar["time"])
try:
    main.gold_indicator_session.process_m1_bar({"time": t0, "open": 1, "high": 2, "low": 0.5, "close": 1.5}, False)
except Exception as exc:
    print("   (process_m1_bar 後段例外，不影響本檢查)", type(exc).__name__, exc)
main.archive_mt5_bar = orig_arch
check("每根 M1 都呼叫封存", called == [t0], called)

print("\n=== R95：Futu 多代號＋按日封存 ===")
FAKE.clear()
def bars(day, n): return [{"time_key": f"{day} 15:{m:02d}:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5 + m, "volume": 10} for m in range(0, 5 * n, 5)]
def pkt(sym, b, iv):
    return {"action": "futu_data", "token": "tok", "symbol": sym, "kline_type": "K_5M", "data": b,
            "options": [{"code": f"{sym}C1", "option_type": "CALL", "expiry": "2026-10-02", "strike": 1, "iv": iv}]}
client.post("/", json=pkt("US.QQQ", bars("2026-09-24", 2) + bars("2026-09-25", 3), 18.0))
client.post("/", json=pkt("US.QQQ", bars("2026-09-25", 4), 19.0))
r = client.post("/", json=pkt("US.SPY", bars("2026-09-25", 2), 12.0))
check("第二個代號也 stored", r.get_json().get("status") == "stored", r.get_json())
q24 = main.archive_blob_name("futu_k_5m", "US.QQQ", "2026-09-24")
q25 = main.archive_blob_name("futu_k_5m", "US.QQQ", "2026-09-25")
check("K 線按美東日期分檔", len(rows(q24)) == 2 and len(rows(q25)) == 4, (len(rows(q24)), len(rows(q25))))
opt = rows(main.archive_blob_name("futu_options", "US.QQQ", "2026-09-25"))
check("期權每次推送各記一列", len(opt) == 2 and {o["iv"] for o in opt} == {18.0, 19.0}, opt)
check("期權列帶現價", opt[-1]["spot"] == 16.5, opt[-1])
j = client.get("/?view=futu&format=json&symbol=US.QQQ").get_json()
check("指定代號讀回 QQQ", j.get("symbol") == "US.QQQ", j.get("symbol"))
check("不指定＝最後收到的 SPY", client.get("/?view=futu&format=json").get_json().get("symbol") == "US.SPY")

print("\n=== R95：?view=archive 讀回某一天 ===")
main.archive_mt5_bar({"time": int(datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc).timestamp()), "open": 1, "high": 2, "low": 0.5, "close": 1.5})
j = client.get("/?view=archive&format=json&date=2026-09-25").get_json()
check("status ok", j.get("status") == "ok", j)
check("三種來源都在", set(j["series"]) == {"mt5_m1/XAUUSD", "futu_k_5m/US.QQQ", "futu_k_5m/US.SPY", "futu_options/US.QQQ", "futu_options/US.SPY"}, j["series"])
check("不含別天的檔", "2026-09-24" not in json.dumps(j["data"]["futu_k_5m/US.QQQ"]))
check("壞日期 → 400", client.get("/?view=archive&format=json&date=../x").status_code == 400)
check("沒資料的日子 → 空", client.get("/?view=archive&format=json&date=2020-01-01").get_json()["series"] == {})

print("\n=== R96：日線抽樣（K_DAY）只封存，不蓋掉控制台快照 ===")
before_latest = FAKE.get(main.FUTU_SNAPSHOT_FILE, (None,))[0]
before_qqq = FAKE.get(main.futu_symbol_file("US.QQQ"), (None,))[0]
r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": "US.QQQ", "kline_type": "K_DAY",
                           "data": [{"time_key": "2026-09-24 00:00:00", "open": 735.29, "high": 742.66, "low": 734.62,
                                     "close": 741.1, "volume": 29000900}], "options": []})
check("K_DAY 回 stored", r.get_json().get("status") == "stored", r.get_json())
check("控制台最新快照沒被蓋掉", FAKE.get(main.FUTU_SNAPSHOT_FILE, (None,))[0] == before_latest)
check("代號快照沒被蓋掉", FAKE.get(main.futu_symbol_file("US.QQQ"), (None,))[0] == before_qqq)
kd = main.archive_blob_name("futu_k_day", "US.QQQ", "2026-09-24")
check("日線按日期封存到 futu_k_day", kd in FAKE and rows(kd)[0]["close"] == 741.1, sorted(k for k in FAKE if "k_day" in k))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
