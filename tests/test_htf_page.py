"""[R165] 📈 HTF 每日掛單頁：四市場摘要、掛單排序、持倉動作顏色、已平倉統計、參數行、大市過濾、讀取失敗後備、format=json、策略總表四行、導覽；假抓取唔連網。"""
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

FX = "/home/user/20260918/tests/fixtures_htf/"
class Resp:
    def __init__(self, text, ok=True): self.text, self.ok = text, ok
calls = []
def fake_get(url, **k):
    name = url.rsplit("/", 1)[1]; calls.append(name)
    try:
        return Resp(open(FX + name, encoding="utf-8").read())
    except FileNotFoundError:
        return Resp("", ok=False)
def fake_fail(url, **k):
    raise RuntimeError("no network")
store = {}
main.gcs_write_text = lambda name, text: store.__setitem__(name, text)
main.gcs_read_text = lambda name: store.get(name)
main._htf_cache.clear(); main.requests.get = fake_get

d = main.htf_data()
check("status ok、最新數據日 2026-10-12", d["status"] == "ok" and d["latest_date"] == "2026-10-12", d.get("latest_date"))
mk = {m["key"]: m for m in d["markets"]}
check("四個市場齊", [m["key"] for m in d["markets"]] == ["hk", "tw", "jp", "us"])
tw = mk["tw"]
check("台股掛單 9 隻、按距觸發價由近到遠", tw["n_orders"] == 9 and tw["orders"][0]["ticker"] == "2305.TW" and tw["orders"][-1]["ticker"] == "2221.TWO"
      and all(tw["orders"][i]["dist_pct"] <= tw["orders"][i + 1]["dist_pct"] for i in range(8)), [o["ticker"] for o in tw["orders"]])
check("掛單帶名稱（names.json）", tw["orders"][0]["name"] == "MICROTEK INTERNATIONAL INC")
check("台股持倉 2 筆：持有／賣一半 分類", tw["n_open"] == 2 and tw["positions"][0]["action_kind"] == "hold" and tw["positions"][1]["action_kind"] == "half", tw["positions"])
check("台股已平倉 2 筆：平均、賺錢筆數", tw["closed"]["n"] == 2 and abs(tw["closed"]["avg"] - (-0.086 + 0.0761) / 2) < 1e-9 and tw["closed"]["win"] == 1)
check("港股：不用大市過濾、掛單 1、無持倉", mk["hk"]["mkt_filter"] is False and mk["hk"]["n_orders"] == 1 and mk["hk"]["n_open"] == 0)
check("美股：用大市過濾、今日通過、掛單 0", mk["us"]["mkt_filter"] is True and mk["us"]["mkt_ok"] is True and mk["us"]["n_orders"] == 0)
check("日股參數行：最長 252 日、賣一半第 3 日", "最長 252 日" in mk["jp"]["spec"] and "第 3 日收市賣一半" in mk["jp"]["spec"], mk["jp"]["spec"])
check("美股參數行：不賣一半、停損 1.0", "不賣一半" in mk["us"]["spec"] and "停損 1.0" in mk["us"]["spec"], mk["us"]["spec"])
check("美股 alpha t 1.48 孤峰", mk["us"]["fit_t"] == 1.48)
h = main.build_htf_page(d)
check("頁面：標題帶數據日、四個摘要卡", "HTF 每日掛單　2026-10-12" in h and h.count("掛單 ") >= 4)
check("頁面：大市過濾三種狀態文字", "不用大市過濾" in h and "大市過濾 ✓ 可開新倉" in h)
check("頁面：賣一半黃、持有灰", "#fff3cd" in h and "#e9ecef" in h)
check("頁面：美股孤峰註", "alpha t 1.48（低於 1.5，屬孤峰）" in h)
check("頁面：怎樣照做五點、證偽、POSITIONS.md 登記", "怎樣照做" in h and "回撤超過 −33%" in h and "POSITIONS.md 登記" in h and "合計曝險不超過 100%" in h)
check("頁面：列印按鈕、表頭每頁重印、長區塊可跨頁", "列印成 PDF" in h and "table-header-group" in h and "print-flow" in h)
check("頁面：導覽當前頁係 HTF", "nav-current'>📈 HTF 掛單" in h)
check("頁面：日股／美股數據日 10-09 原樣顯示", "數據至 2026-10-09（JPY）" in h and "數據至 2026-10-09（USD）" in h)
check("頁面：轉義", "<script>alert" not in main.build_htf_page({**d, "latest_date": "<script>alert(1)</script>"}))

# 快取與後備
n = len(calls); main.htf_data(); check("30 分鐘內用快取（冇再抓）", len(calls) == n)
check("成功抓取寫 GCS 後備（orders 用固定 key）", "htf/tw_orders.csv" in store and "htf/names.json" in store)
for k in main._htf_cache.values(): k["ts"] = 0.0
main.requests.get = fake_fail
d2 = main.htf_data()
check("讀取失敗用上次成功版本並標 stale", d2["status"] == "ok" and d2["stale"] and "顯示上次成功版本" in main.build_htf_page(d2))
main._htf_cache.clear()
d3 = main.htf_data()
check("冇記憶體就用 GCS 後備", d3["status"] == "ok" and d3["markets"][1]["n_orders"] == 9)
main._htf_cache.clear(); store.clear()
d4 = main.htf_data()
check("完全冇數據：error 唔白頁", d4["status"] == "error" and "HTF 數據讀不到" in main.build_htf_page(d4))

# 策略總表四行
main._htf_cache.clear(); main.requests.get = fake_get
sd = main.strategies_data()
rows = {r["key"]: r for r in sd["rows"]}
check("策略總表有 htf_hk／tw／jp／us 四行", all(f"htf_{m}" in rows for m in ("hk", "tw", "jp", "us")))
check("台股：持倉 2 → side 1、lots 2、文字", rows["htf_tw"]["pos"]["side"] == 1 and rows["htf_tw"]["pos"]["lots"] == 2 and "持倉 2 筆・明日掛單 9 隻" in rows["htf_tw"]["pos"]["detail"], rows["htf_tw"]["pos"])
check("港股：持倉 0 → side 0", rows["htf_hk"]["pos"]["side"] == 0)
check("行屬性：紙上、link ?view=htf、market 港股", rows["htf_hk"]["group"] == "紙上" and rows["htf_hk"]["real"] is False and rows["htf_hk"]["link"] == "?view=htf" and rows["htf_hk"]["market"] == "港股")
main._htf_cache.clear(); store.clear(); main.requests.get = fake_fail
rows2 = {r["key"]: r for r in main.strategies_data()["rows"]}
check("讀不到 → side None", rows2["htf_hk"]["pos"]["side"] is None)

main._htf_cache.clear(); main.requests.get = fake_get
client = main.app.test_client()
r = client.get("/?view=htf")
check("?view=htf 回 200", r.status_code == 200 and "HTF 每日掛單" in r.get_data(as_text=True))
j = client.get("/?view=htf&format=json").get_json()
check("&format=json：markets、latest_date", j["status"] == "ok" and len(j["markets"]) == 4 and j["latest_date"] == "2026-10-12")
check("PAGE_LINKS 有 htf", ("htf", "📈 HTF 掛單") in main.PAGE_LINKS)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
