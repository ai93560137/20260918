"""[R144] 🧭 策略總表：各策略現時持倉方向、方向相反提示、頁面與 JSON、數據不足時不出錯。"""
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
SYM = main.DIZAI_SYMBOL

print("=== 1. 沒有任何狀態檔 ===")
FAKE.clear()
d = main.strategies_data()
check("全部列出、方向不知道、沒有方向相反", len(d["rows"]) >= 12 and d["summary"]["unknown"] >= 1 and not d["conflicts"], d["summary"])
r = client.get("/?view=strategies")
check("頁面 200、有總表與導覽", r.status_code == 200 and "策略總表" in r.get_data(as_text=True) and "錦囊 v4" in r.get_data(as_text=True))

print("=== 2. 有持倉：蛇蟠陣做多、地載・衡做空、黃金做多 ===")
main.gcs_write_text(main.ACCOUNT_FILE, json.dumps({"net_lots": 0.03, "buy_lots": 0.03, "sell_lots": 0, "received_utc": "2026-10-12 02:00:00"}))
main.gcs_write_text(main.futu_paper_file(SYM), json.dumps({"version": main.PAPER_VERSION, "snake": {"pos": 1, "lots": 1, "upper": 25000, "lower": 24000,
    "entry_time": "2026-10-12 09:20:00"}, "open": {"B_S_R3": {"side": 1, "entry_price": 24500, "stop": 24100, "target": 25700, "lots": 2,
    "entry_time": "2026-10-12 10:00:00"}}, "trades": [], "notices": []}))
main.gcs_write_text(main.dizai_heng_file(SYM), json.dumps({"version": main.DIZAI_HENG_VERSION, "pos": {"side": -1, "lots": 1, "entry": 24900,
    "entry_tk": "2026-10-12 10:27:00"}}))
main.gcs_write_text(main.dizai_que_file(SYM), json.dumps({"version": main.DIZAI_QUE_VERSION, "pos": None}))
d = main.strategies_data()
by = {r["key"]: r for r in d["rows"]}
check("黃金：淨 0.03 手做多", by["jinnang"]["pos"]["side"] == 1 and "0.03" in by["jinnang"]["pos"]["detail"], by["jinnang"]["pos"])
check("蛇蟠陣（真錢）只列訊號方向：做多", by["snake_real"]["pos"]["side"] == 1 and by["snake_real"].get("signal_only"))
check("風揚陣 B＋跟蛇 3R 做多 2 張；A 空手", by["fy_B_S_R3_恒指"]["pos"]["side"] == 1 and by["fy_B_S_R3_恒指"]["pos"]["lots"] == 2
      and by["fy_A_S_R2_恒指"]["pos"]["side"] == 0)
check("地載・衡做空、地載・缺空手、地載陣四組未開始", by["heng"]["pos"]["side"] == -1 and by["que"]["pos"]["side"] == 0
      and by["dz_steady"]["pos"]["side"] is None)
c = d["conflicts"]
check("恒指方向相反：做多含蛇蟠陣、做空含地載・衡，並標有真錢", len(c) == 1 and c[0]["market"] == "恒指" and "地載・衡" in c[0]["short"]
      and any("蛇蟠陣" in x for x in c[0]["long"]) and c[0]["real"], c)
html = client.get("/?view=strategies").get_data(as_text=True)
check("頁面：⚠️ 方向相反、真錢標記、每 60 秒更新", "⚠️ 方向相反" in html and "🔴 真錢" in html and "content='60'" in html)
j = client.get("/?view=strategies&format=json").get_json()
check("JSON 一致", j["summary"] == d["summary"] and len(j["rows"]) == len(d["rows"]))

print("=== 3. 導覽列 ===")
check("PAGE_LINKS 有策略總表", ("strategies", "🧭 策略總表") in main.PAGE_LINKS)
for f in ("gates.html", "order.html", "jinnang_sheet.html", "jinnang_tracker.html", "bazhentu.html"):
    check(f"{f} 連到策略總表", "strategies" in open("/home/user/20260918/" + f, encoding="utf-8").read())

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
