"""[R184] CME 延遲報價中轉：cme_watchlist／cme_quotes／cme_quotes_get（要權杖、只收 CME 代碼）。"""
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
import json
OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")
client = main.app.test_client()

def post(body):
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

print("=== 權杖 ===")
check("冇權杖 → 403", post({"action": "cme_quotes_get"})[0] == 403)
check("錯權杖 → 403", post({"action": "cme_watchlist", "token": "x"})[0] == 403)

print("=== cme_watchlist ===")
main.gcs_write_text(main.FUTU_RISK_FILE, json.dumps({"run_hkt": "2026-10-15 01:30", "positions": [
    {"code": "US.EW2610P7750x0", "qty": -1}, {"code": "US.MES2612", "qty": -4}, {"code": "US.EX32610C7830x0", "qty": 0},
    {"code": "HK.MHI2610", "qty": -1}, {"code": "US.SPCX", "qty": 0.08}]}))
st, d = post({"action": "cme_watchlist", "token": "tok"})
check("只列有倉嘅 CME 代碼＋ES2612 標的", st == 200 and d["codes"] == ["US.EW2610P7750x0", "US.MES2612", "US.ES2612"], d)

print("=== cme_quotes 存 → cme_quotes_get 讀 ===")
st, d = post({"action": "cme_quotes", "token": "tok", "fetched_utc": "2026-10-14 17:50:00", "quotes": {
    "US.ES2612": {"bid": 7759.25, "ask": 7759.5, "last": 7759.5, "close": 7855.75, "md_type": 3, "quote_time": "t"},
    "HK.MHI2610": {"bid": 1, "ask": 2}, "US.EW2610P7750x0": {"bid": 80.75, "ask": "81.5", "md_type": 3}}})
check("存兩張 CME、拒非 CME 代碼", st == 200 and d["status"] == "stored" and d["count"] == 2, d)
st, d = post({"action": "cme_quotes", "token": "tok", "quotes": {"HK.MHI2610": {"bid": 1}}})
check("冇有效報價 → 422", st == 422)
st, d = post({"action": "cme_quotes_get", "token": "tok"})
check("讀返報價", st == 200 and d["quotes"]["US.EW2610P7750x0"]["ask"] == 81.5 and "HK.MHI2610" not in d["quotes"], d)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
