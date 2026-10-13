"""[R174] 基金報告頁的週報／月報區：讀 GCS ops/reports/public.json，讀唔到唔影響頁面。

執行：python3 tests/test_fund_report_reports.py
"""
import json, os, sys, types
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
import functions_framework, google, google.cloud  # noqa: F401  實際套件在，只替換 GCS 與 genai
FAKE = {}
class _Blob:
    def __init__(s, n): s.name = n; s.generation = FAKE.get(n, (None, 0))[1]
    def exists(s): return s.name in FAKE
    def download_as_text(s, *a, **k):
        if s.name not in FAKE: raise KeyError(s.name)
        return FAKE[s.name][0]
    def download_as_bytes(s, *a, **k): return s.download_as_text().encode()
    def upload_from_string(s, d, *a, **k):
        g = FAKE.get(s.name, (None, 0))[1] + 1; FAKE[s.name] = (d, g); s.generation = g
    def reload(s): s.generation = FAKE.get(s.name, (None, 0))[1]
class _Bucket:
    def blob(s, n): return _Blob(n)
    def get_blob(s, n): return _Blob(n) if n in FAKE else None
class _Client:
    def __init__(s, *a, **k): pass
    def bucket(s, n): return _Bucket()
m = types.ModuleType("google.cloud.storage"); m.Client = _Client
sys.modules["google.cloud.storage"] = m; google.cloud.storage = m
g = types.ModuleType("google.genai"); g.Client = lambda *a, **k: None
g.types = types.SimpleNamespace(); sys.modules["google.genai"] = g
e = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
e.PreconditionFailed = _PC; e.NotFound = KeyError
ac = types.ModuleType("google.api_core"); ac.exceptions = e
sys.modules["google.api_core"] = ac; sys.modules["google.api_core.exceptions"] = e
import main  # noqa: E402
from types import SimpleNamespace  # noqa: E402

OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} {x}")

req = lambda **a: SimpleNamespace(args=a)
IDX = {"weekly": [{"key": "2026-10-18", "text": "🗓 週報 <b>10-12</b>\n合計權益報酬 +2.00%", "generated_hkt": "2026-10-18 09:01"},
                  {"key": "2026-10-11", "text": "舊週報", "generated_hkt": "2026-10-11 09:01"}],
       "monthly": []}

print("\n一、沒有富途成交、沒有報告")
FAKE.clear()
html = main.handle_fund_report_get(req())
check("頁面照出", "未有富途成交數據" in html)
check("週報區顯示「未有」", "🗓 週報" in html and "未有" in html)

print("\n二、有報告、沒有成交")
FAKE[main.OPS_REPORTS_PUBLIC_FILE] = (json.dumps(IDX, ensure_ascii=False), 1)
html = main.handle_fund_report_get(req())
check("最新週報展開", "🗓 週報・2026-10-18" in html and "合計權益報酬 +2.00%" in html)
check("內容有 escape", "&lt;b&gt;10-12&lt;/b&gt;" in html and "<b>10-12</b>" not in html)
check("舊份摺疊", "<details" in html and "舊週報" in html)
check("月報未有", "📘 月報" in html)

print("\n三、有成交：報告放最頂")
FAKE[main.FUTU_PNL_FILE] = (json.dumps({"fetched_hkt": "2026-10-13 17:08", "since": "2026-09-01", "positions": [],
                                        "deals": [{"time": "2026-10-02 10:00:00", "code": "HK.MHI2610", "side": "BUY", "qty": 1, "price": 26000, "order_id": "1"},
                                                  {"time": "2026-10-03 10:00:00", "code": "HK.MHI2610", "side": "SELL", "qty": 1, "price": 26100, "order_id": "2"}]}), 1)
html = main.handle_fund_report_get(req())
check("週報在已實現表之前", 0 < html.find("🗓 週報・2026-10-18") < html.find("已實現淨盈虧"))
r = main.futu_pnl_report(json.loads(FAKE[main.FUTU_PNL_FILE][0]))
check("原有計算不變（MHI +100 點 × 10）", r["periods"]["month"]["2026-10"]["合計"]["gross"] == 1000.0, r["periods"])

print("\n四、索引壞咗唔影響頁面")
FAKE[main.OPS_REPORTS_PUBLIC_FILE] = ("{壞", 2)
html = main.handle_fund_report_get(req())
check("頁面照出已實現表", "已實現淨盈虧" in html)
FAKE[main.OPS_REPORTS_PUBLIC_FILE] = ("[1,2]", 3)
check("非 dict 當空", main.ops_reports_public() == {})

print(f"\n合計 ✅ {OK}  ❌ {FAIL}")
sys.exit(1 if FAIL else 0)
