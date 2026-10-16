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

print("\n五、[R207] 未實現、總盈虧、每月／季／年績效")
FAKE[main.OPS_REPORTS_PUBLIC_FILE] = (json.dumps(IDX, ensure_ascii=False), 4)
RISK = {"run_hkt": "2026-10-17 01:37", "metrics": {"futu_equity": 500000},
        "positions": [{"code": "US.EW2610P7750x0", "qty": -1, "open_price": 43, "futu_pl": -2750.0},
                      {"code": "HK.HSI261023P23700000", "qty": -1, "open_price": 59, "futu_pl": -100.0},
                      {"code": "HK.MHI2610", "qty": -1, "open_price": 24300, "bid": 24290, "ask": 24292, "futu_pl": None}]}
un = main.fund_unrealized(RISK)
check("美元折港幣：EW −2,750 × 7.8", abs(un["by_product"]["ES 標普月底期權"] - (-2750 * main.FUTU_USD_HKD)) < 1e-6, un)
check("冇 futu_pl 用中間價計：MHI (24,291 − 24,300) × −1 × 10 = +90", abs(un["by_product"]["MHI 小型恒指期貨"] - 90) < 1e-6, un)
check("合計", abs(un["total"] - (-2750 * main.FUTU_USD_HKD - 100 + 90)) < 1e-6, un)
check("讀唔到持倉 → None", main.fund_unrealized({}) is None and main.fund_unrealized(None) is None)
r = main.futu_pnl_report(json.loads(FAKE[main.FUTU_PNL_FILE][0]))
perf = main.fund_performance(r, un, today=main.date(2026, 10, 17))
m = {x["period"]: x for x in perf["periods"]["month"]}
check("10 月：已實現 1,000＋未實現 → 總盈虧", m["2026-10"]["realized"] == 1000 and abs(m["2026-10"]["total"] - (1000 + un["total"])) < 0.01, m)
check("回報率 ÷ 富途權益 50 萬", m["2026-10"]["return_pct"] == round((1000 + un["total"]) / 500000 * 100, 2), m)
check("勝率 100%（1 筆平倉賺）", m["2026-10"]["closes"] == 1 and m["2026-10"]["win_rate"] == 100.0, m)
check("每季、每年都有", perf["periods"]["quarter"][-1]["period"] == "2026Q4" and perf["periods"]["year"][-1]["period"] == "2026")
check("本金來源 futu_equity", perf["capital_source"] == "futu_equity")
perf2 = main.fund_performance(r, un, today=main.date(2026, 11, 2))
m2 = {x["period"]: x for x in perf2["periods"]["month"]}
check("未實現只計入現時月份（11 月），10 月唔計", m2["2026-10"]["unrealized"] == 0 and "2026-11" in m2 and m2["2026-11"]["realized"] == 0, m2)
FAKE[main.FUTU_RISK_FILE] = (json.dumps(RISK), 1)
html = main.handle_fund_report_get(req())
check("頁面有未實現卡、總盈虧卡", "未實現盈虧（現時持倉" in html and "總盈虧（已實現＋未實現）" in html)
check("頁面有每月／每季／每年績效表", all(f"📈 {z}績效" in html for z in ("每月", "每季", "每年")))
check("頁面有按產品未實現", "未實現盈虧（按產品" in html)
check("權益絕對值唔出現（50 萬）", "500,000" not in html and "500000" not in html)
import flask                                     # noqa: E402
with flask.Flask("t").app_context():
    j = main.handle_fund_report_get(req(format="json"))
    j = j[0] if isinstance(j, tuple) else j
    body = j.get_data(as_text=True)
check("JSON 有 unrealized、performance，冇權益金額", '"unrealized"' in body and '"performance"' in body and "500000" not in body and "500,000" not in body, body[:300])
del FAKE[main.FUTU_RISK_FILE]
html = main.handle_fund_report_get(req())
check("讀唔到持倉：頁面照出、顯示讀唔到", "讀唔到持倉" in html and "已實現淨盈虧" in html)

print(f"\n合計 ✅ {OK}  ❌ {FAIL}")
sys.exit(1 if FAIL else 0)
