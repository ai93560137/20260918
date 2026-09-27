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

main.macro_news_session.status = lambda now=None: {"locked": False, "known": True, "reason": "test",
                                                   "events": [], "warning": None}
main.ai_review_session.review = lambda meta: (True, "test")

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

print("\n=== R84：main:app 這個 WSGI 入口 ===")

# gunicorn 只認這兩件事：模組裡有 app，而且它可以被 WSGI 呼叫。
check("main 模組有 app", hasattr(main, "app"))
check("app 可被 WSGI 呼叫", callable(main.app))
check("app 是 Flask 實例", main.app.__class__.__name__ == "Flask")

client = main.app.test_client()

# 1) GET / ——儀表板。走 functions-framework 時是同一個函式，所以回應必須一致。
r = client.get("/")
direct_html = None
from flask import request as flask_request
with main.app.test_request_context("/", method="GET"):
    d = main.receive_tradingview_signal(flask_request)
    d = d[0] if isinstance(d, tuple) else d
    direct_html = d if isinstance(d, str) else d.get_data(as_text=True)
check("GET / 不是 404/500", r.status_code < 400, r.status_code)
check("GET / 和直接呼叫同一份內容", r.get_data(as_text=True) == direct_html)

# 2) OPTIONS —— CORS preflight 要照樣被接走，不能被 Flask 自動處理掉。
r = client.open("/", method="OPTIONS")
check("OPTIONS 有 CORS 標頭", "Access-Control-Allow-Origin" in r.headers, dict(r.headers))

# 3) POST —— 錯誤權杖要拿到 403，代表封包真的進了原本那條路，不是被 Flask 擋在外面。
r = client.post("/", json={"action": "update_levels", "token": "wrong-token"})
check("POST 壞權杖 → 403", r.status_code == 403, r.status_code)

# 4) 子路徑也要落到同一個函式（EA / TradingView 的 URL 可能帶路徑）。
r = client.post("/anything/deep", json={"action": "update_levels", "token": "wrong-token"})
check("子路徑 → 同樣 403（不是 404）", r.status_code == 403, r.status_code)

# 5) 正確權杖的 update_levels 要 200，確認不是每條都被擋。
r = client.post("/", json={"action": "update_levels", "token": os.environ["WEBHOOK_SECRET_TOKEN"]})
check("POST 正確權杖 → 200", r.status_code == 200, r.status_code)

# 6) functions-framework 的註冊沒有被破壞（正常那條路仍然是主路）。
from functions_framework import _function_registry as _reg
reg = getattr(_reg, "REGISTRY_MAP", {})
check("receive_tradingview_signal 仍註冊為 http", reg.get("receive_tradingview_signal") == "http", reg)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
