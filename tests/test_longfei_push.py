"""[R200] 龍飛陣成績上載：longfei_push（要權杖、只存 GCS longfei/latest.json、權杖唔入檔）。"""
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
OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")
client = main.app.test_client()

def post(body):
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

pkt = {"action": "longfei_push", "token": "tok", "sent_utc": "2026-10-16T13:30:00+00:00",
       "state": {"trd_env": "SIMULATE", "product": "HSI", "day_pnl": -500, "pos": None},
       "trades": [{"type": "OPEN", "price": 25000}, {"type": "CLOSE", "points": 12}],
       "decisions": [{"ai_action": "HOLD", "reason": "等"}]}
print("=== 權杖 ===")
code, _ = post({**pkt, "token": "wrong"})
check("錯權杖 403", code == 403, code)
check("錯權杖唔寫檔", "longfei/latest.json" not in FAKE)
print("=== 存檔 ===")
code, body = post(pkt)
check("200 stored", code == 200 and body.get("status") == "stored", (code, body))
doc = json.loads(FAKE["longfei/latest.json"][0])
check("內容齊", doc["status"]["product"] == "HSI" and len(doc["trades"]) == 2 and len(doc["decisions"]) == 1)
check("權杖唔入檔", "tok" not in FAKE["longfei/latest.json"][0].replace("stored", ""))
print("=== 格式錯 ===")
code, _ = post({**pkt, "trades": "x"})
check("trades 唔係 list → 422", code == 422, code)

print("=== 頁面 ?view=longfei ===")
r = client.get("/?view=longfei")
html = r.get_data(as_text=True)
check("冇數據都 200", r.status_code == 200 and "龍飛陣" in html, r.status_code)
tr = [{"type": "OPEN", "code": "HK.HSI2610", "ts": "2026-10-17T10:00:00+08:00", "reason": "突破"},
      {"type": "CLOSE", "code": "HK.HSI2610", "side": 1, "entry": 25000, "price": 25030, "points": 30,
       "ts": "2026-10-17T10:30:00+08:00", "reason": "止賺 25030", "opened_at": "2026-10-17T10:00:05+08:00"},
      {"type": "CLOSE", "code": "HK.HSI2610", "side": -1, "entry": 25100, "price": 25120, "points": -20,
       "ts": "2026-10-18T11:00:00+08:00", "reason": "止蝕 25120"}]
post({**pkt, "state": {"trd_env": "SIMULATE", "pos": None}, "trades": tr,
      "decisions": [{"ts": "2026-10-17T10:00:03+08:00", "final": "OPEN_LONG", "last": 25000, "reason": "<b>突破</b>"}]})
html = client.get("/?view=longfei").get_data(as_text=True)
check("顯示勝率 50%", "50%" in html)
check("盈虧比 1.50", "1.50" in html)
check("理由已轉義", "<b>突破</b>" not in html and "&lt;b&gt;" in html)
check("導覽有龍飛陣", "?view=longfei" in client.get("/?view=canary").get_data(as_text=True))
j = client.get("/?view=longfei&format=json").get_json()
check("json 指標", j["metrics"]["trades"] == 2 and abs(j["metrics"]["profit_factor"] - 1.5) < 1e-9, j.get("metrics"))
check("json 唔含權杖", "tok" not in json.dumps(j))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
