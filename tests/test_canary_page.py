"""[R160] 🐤 金絲雀頁：頂部日期、三軸數值、黃鳥距門檻、試用層標「無警報權」、最近 30 列、T−1 回驗原文、讀取失敗用快取／後備、未更新黃字、format=json、導覽；全程假抓取，唔連網。"""
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
from datetime import datetime

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

FX = "/home/user/20260918/tests/fixtures_canary/"
FILES = {n: open(FX + n, encoding="utf-8").read() for n in main.CANARY_FILES}
HK = main.HK_TZ

class Resp:
    def __init__(self, text, ok=True): self.text, self.ok = text, ok

calls = []
def fake_get_ok(url, **k):
    calls.append(url)
    return Resp(FILES[url.rsplit("/", 1)[1]])
def fake_get_fail(url, **k):
    raise RuntimeError("no network")

store = {}
main.gcs_write_text = lambda name, text: store.__setitem__(name, text)
main.gcs_read_text = lambda name: store.get(name)

def reset():
    main._canary_cache.update(ts=0.0, data=None)

reset(); main.requests.get = fake_get_ok
d = main.canary_data(datetime(2026, 10, 12, 10, 0, tzinfo=HK))
top = d["top"]
check("頂部：報告日、燈色日 D、適用日", top["report_date"] == "2026-10-12" and top["light_date"] == "2026-10-09" and top["apply_date"] == "2026-10-12", top)
check("日期格式 MM-DD(星期)", main.canary_date("2026-10-12") == "10-12(一)" and main.canary_date("2026-10-09") == "10-09(五)")
check("發出時間用香港時間", top["generated_hkt"] == "10-12(一) 06:38 HKT", top["generated_hkt"])
s, dz = d["axes"]
check("短期軸：VIX9D 11.07 − VIX 14.78 = -3.71，綠，連續 17 日", (s["a"], s["b"], s["diff"], s["light"], s["streak_days"]) == (11.07, 14.78, -3.71, "綠", "17"), s)
check("災難軸：VIX 14.78 − VIX3M 17.72 = -2.94，連續 129 日", (dz["a"], dz["b"], dz["diff"], dz["streak_days"]) == (14.78, 17.72, -2.94, "129"), dz)
check("軸附前一列對照（10-08 → 10-09）", s["prev_date"] == "2026-10-08" and s["prev_diff"] == -3.2, s)
b = {x["name"]: x for x in d["birds"]}
check("VVIX 距門檻 -27.2%（同 tg_daily 一致）、滅", round(b["VVIX"]["gap_pct"], 1) == -27.2 and b["VVIX"]["lit"] is False, b["VVIX"])
check("MOVE +15.5% 亮", round(b["MOVE"]["gap_pct"], 1) == 15.5 and b["MOVE"]["lit"] is True, b["MOVE"])
check("AXVI -26.2%", round(b["AXVI"]["gap_pct"], 1) == -26.2)
check("VHSI D 列冇值：不計入，並列最近值日", b["VHSI（試用）"]["counted"] is False and b["VHSI（試用）"]["last_date"] == "2026-10-08", b["VHSI（試用）"])
check("最近 30 列、最新在最上", len(d["rows30"]) == 30 and d["rows30"][0]["date"] == "2026-10-09", len(d["rows30"]))
check("T−1 回驗引用原文", d["cite"] and d["cite"][0].startswith("🔁") and "10-11(日) 06:37 香港 發出" in d["cite"][0])
check("發送紀錄最近 10 列", len(d["sent_log"]) == 10 and d["sent_log"][0]["report_date"] == "2026-10-12")
h = main.build_canary_page(d)
check("頁面：試用層標「無警報權，只記錄」", "無警報權，只記錄" in h)
check("頁面：亞洲鳥冇值要寫「不計入 D 燈色」", "不計入 D 燈色" in h)
check("頁面：lag=1 說明、頁尾免責", "lag=1" in h and main.CANARY_FOOTER in h)
check("頁面：tg_daily 全文展開（pre）", "<pre" in h and "金絲雀每日總結" in h)
check("頁面：列印按鈕、導覽列有金絲雀", "列印成 PDF" in h and "nav-current'>🐤 金絲雀" in h)
check("07:30 前、報告日＝今日：冇「未更新」", "今日金絲雀未更新" not in h)
check("文字有轉義", "<script>alert" not in main.build_canary_page({**d, "tg_daily": "<script>alert(1)</script>"}))

d_late = main.canary_data(datetime(2026, 10, 13, 8, 0, tzinfo=HK))
check("過香港 07:30 而最後報告日≠今日：黃字「今日金絲雀未更新」", d_late["top"]["outdated"] and "今日金絲雀未更新" in main.build_canary_page(d_late))
d_early = main.canary_data(datetime(2026, 10, 13, 7, 0, tzinfo=HK))
check("07:30 前唔報未更新", not d_early["top"]["outdated"])

# 快取：30 分鐘內唔再抓
n = len(calls); main.canary_data(); main.canary_data()
check("30 分鐘內用記憶體快取（冇再抓）", len(calls) == n, (n, len(calls)))
check("成功抓取寫 GCS 後備，canary_daily 只存最後 40 列", "canary/tg_daily.txt" in store and len(store["canary/canary_daily.csv"].splitlines()) <= main.CANARY_KEEP_ROWS + 1)

# 讀取失敗：用上次成功版本（記憶體）
main._canary_cache["ts"] = 0.0
main.requests.get = fake_get_fail
d_fail = main.canary_data(datetime(2026, 10, 12, 10, 0, tzinfo=HK))
check("讀取失敗用上次成功版本、標明讀取時間", d_fail["status"] == "ok" and len(d_fail["stale_files"]) == 4 and d_fail["fetched_utc"], d_fail.get("stale_files"))
check("頁面標明暫時讀唔到最新", "暫時讀唔到最新檔案" in main.build_canary_page(d_fail))
# 冇記憶體：用 GCS 後備
reset()
d_gcs = main.canary_data(datetime(2026, 10, 12, 10, 0, tzinfo=HK))
check("冇記憶體就用 GCS 後備", d_gcs["status"] == "ok" and d_gcs["axes"][0]["diff"] == -3.71)
# 全部冇：error，唔白頁
reset(); store.clear()
d_none = main.canary_data()
check("完全冇數據：status=error 有訊息", d_none["status"] == "error" and d_none.get("message"))
check("error 頁面唔白頁", "金絲雀數據讀不到" in main.build_canary_page(d_none))

# 路由與 JSON
reset(); main.requests.get = fake_get_ok
client = main.app.test_client()
r = client.get("/?view=canary")
check("?view=canary 回 200", r.status_code == 200 and "金絲雀" in r.get_data(as_text=True), r.status_code)
j = client.get("/?view=canary&format=json")
jd = j.get_json()
check("&format=json：頂部卡、三軸、黃鳥、最近 30 列", j.status_code == 200 and all(k in jd for k in ("top", "axes", "birds", "rows30")) and len(jd["rows30"]) == 30, list(jd))
check("PAGE_LINKS 有 canary", ("canary", "🐤 金絲雀") in main.PAGE_LINKS)
reset(); store.clear(); main.requests.get = fake_get_fail
check("全失敗 JSON 回 503", client.get("/?view=canary&format=json").status_code == 503)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
