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
BARS = [{"code": "US.QQQ", "time_key": f"2026-09-26 15:{m:02d}:00", "open": 700 + m, "high": 701 + m,
         "low": 699 + m, "close": 700.5 + m, "volume": 1000 + m, "turnover": 1.0} for m in (50, 40, 45, 55)]

print("\n=== R94：舊版腳本的封包（原樣重現 push_to_gcp.py）===")
FAKE.clear()
legacy = {"action": "futu_data", "token": "tok", "source": "futu_opend", "symbol": "US.QQQ",
          "timestamp": "2026-09-27 19:45:58", "data": BARS,
          "options_iv": {"US.QQQ261002C500000": 0, "US.QQQ261002P500000": 0}}
r = client.post("/", json=legacy)
body = r.get_json()
check("回 200", r.status_code == 200, r.status_code)
check("status 是 stored，不再是 ignored", body.get("status") == "stored", body)
check("有存進 GCS", main.FUTU_SNAPSHOT_FILE in FAKE)
snap = json.loads(FAKE[main.FUTU_SNAPSHOT_FILE][0])
check("K 線依時間排序", [b["time_key"][-5:] for b in snap["bars"]] == ["40:00", "45:00", "50:00", "55:00"], snap["bars"])
check("最新收盤 = 最晚那一根", body.get("latest_close") == 755.5, body)
check("IV 全是 0 會被點名", body.get("iv_count") == 0 and body.get("warnings"), body)
check("沒有進 MT5 原始封包紀錄", main.WEBHOOK_LOG_FILE not in FAKE)

print("\n=== R94：新版腳本的封包 ===")
new = dict(legacy, kline_type="K_5M", script_version="2",
           options=[{"code": "US.QQQ261002C755000", "option_type": "CALL", "expiry": "2026-10-02",
                     "strike": 755, "iv": 18.4, "delta": 0.51},
                    {"code": "US.QQQ261002P755000", "option_type": "PUT", "expiry": "2026-10-02",
                     "strike": 755, "iv": float("nan"), "delta": -0.49}])
new.pop("options_iv")
r = client.post("/", json=new)
body = r.get_json()
check("status stored", body.get("status") == "stored", body)
check("NaN IV 不算有值", body.get("iv_count") == 1, body)
check("沒有警告", body.get("warnings") == [], body)

print("\n=== R94：錯誤情況 ===")
r = client.post("/", json=dict(new, token="wrong"))
check("壞權杖 → 403", r.status_code == 403, r.status_code)
r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": "US.QQQ", "data": []})
check("沒內容 → 422", r.status_code == 422, r.status_code)
r = client.post("/", json={"action": "futu_data", "token": "tok", "data": BARS})
check("沒 symbol → 422", r.status_code == 422, r.status_code)
orig = main.gcs_write_text
def boom(*a, **k): raise main.StorageError("down")
main.gcs_write_text = boom
r = client.post("/", json=new)
main.gcs_write_text = orig
check("GCS 寫不進 → 503（腳本才會知道失敗）", r.status_code == 503, r.status_code)

print("\n=== R94：讀回 ===")
client.post("/", json=new)
r = client.get("/?view=futu&format=json")
j = r.get_json()
check("JSON 讀回 ok", j.get("status") == "ok" and j.get("symbol") == "US.QQQ", j)
check("剛收到不算過期", j.get("stale") is False, j)
html_text = client.get("/?view=dashboard").get_data(as_text=True)
check("控制台有 Futu 區塊", "Futu 行情（US.QQQ）" in html_text)
check("控制台顯示 IV", "18.40%" in html_text)
FAKE.clear()
r = client.get("/?view=futu&format=json")
check("沒資料 → empty", r.get_json().get("status") == "empty", r.get_json())
check("沒資料時控制台不壞", "尚未收到 Futu 行情" in client.get("/?view=dashboard").get_data(as_text=True))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
