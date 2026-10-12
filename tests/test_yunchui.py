"""[R158] ☁️ 雲垂陣頁：公開 JSON（快取／後備）、即時 Δ 優先、更正紀錄原文顯示、列印按鈕、導覽、策略總表連結、唔顯示權益／保證金。"""
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

PUB = {"updated_hkt": "2026-10-12 17:53",
       "strategy": {"name": "雲垂陣", "icon": "☁️", "summary": "賣跨式＋期貨對沖", "rules": ["規則一<b>", "規則二"], "disclaimer": "只作資訊"},
       "positions": [{"id": "HSI 月跨式", "instrument": "MHI", "expiry": "2026-10-29", "strike": 25000, "qty": 1, "entry_date": "2026-09-22",
                      "credit_pts": 1108, "credit_hkd": 11080, "stop_buyback_pts": 2216, "entry_atm_iv": 17.3},
                     {"id": "MHI 期貨對沖", "instrument": "MHI2610", "net_lots": -1, "open_price": 24200.0, "opened_hkt": "2026-10-09 19:49"},
                     {"id": "MES 跨式", "instrument": "MES", "expiry": "2026-10-16", "strike": 7830, "qty": 1, "credit_pts": 178.5, "credit_usd": 892.5, "stop_buyback_pts": 357}],
       "status": {"hsi": {"straddle_delta": 0.62, "hedge_lots": -1.0, "net_delta": -0.38, "band": 0.5, "hedge_verified_hkt": "2026-10-12 15:46"},
                  "mes": {"es": 7883.0, "straddle_delta": -0.44, "band": 0.5}},
       "events": [{"date": "2026-10-09", "text": "重新對沖"}],
       "corrections": [{"date": "2026-10-11", "text": "更正：第一行\n第二行 原因：對沖狀態只靠記錄，冇向券商核實。" + "尾" * 300}]}
LIVE = {"run_hkt": "2026-10-12 17:31", "alerts": {},
        "metrics": {"delta_parts": {"straddle": 0.61, "net_with_hedge": -0.39, "hsi_all": 4.93}, "delta": {"x": [-0.39, 0.5]},
                    "stop_use": {"HSI 月跨式": 0.42, "MES 跨式": 0.26}, "equity": 2520339, "cushion": 332833, "maintenance_margin": 328471},
        "positions": [{"code": "HK.MHI2610", "name": "MHI", "qty": -1, "open_price": 24200}]}

main._yunchui_cache.update(ts=main.now_ts(), data=(PUB, "github"))
store = {"risk": LIVE}
main.gcs_read_json = lambda f, d=None: store["risk"] if "risk/latest" in f else d
d = main.yunchui_data()
check("有即時值就用即時（source=live）", d["delta"]["source"] == "live" and d["delta"]["net"] == -0.39, d["delta"])
check("即時時間標明", d["delta"]["time_hkt"] == "2026-10-12 17:31")
check("對沖 Δ ＝ 含對沖淨 − 月跨式", abs(d["delta"]["hedge"] + 1.0) < 1e-9, d["delta"])
check("預算：再加 0.89／再減 0.11", abs(d["delta"]["room_up"] - 0.89) < 1e-9 and abs(d["delta"]["room_down"] - 0.11) < 1e-9, d["delta"])
check("即時對沖手數 −1、止損用量帶入", d["hedge_lots_live"] == -1 and d["stop_use"].get("HSI 月跨式") == 0.42, d)
h = main.build_yunchui_page(d)
check("頁面有列印按鈕", "列印成 PDF" in h and "@media print" in h)
check("導覽列有雲垂陣（當前頁）", "nav-current'>☁️ 雲垂陣" in h)
check("更正紀錄原文全部顯示（含尾段）", "原因：對沖狀態只靠記錄，冇向券商核實。" in h and "尾" * 300 in h)
check("文字有轉義（規則含 <b>）", "規則一&lt;b&gt;" in h and "規則一<b>" not in h)
check("唔顯示權益／保證金", "2,520,339" not in h and "332,833" not in h and "328,471" not in h and "保證金緩衝" not in h)
check("持倉卡有行使價、到期、權利金、止損線", all(x in h for x in ("25,000", "2026-10-29", "1,108.0", "2,216.0", "7,830", "357.0")))
check("MES 日報 Δ 標明日報時點", "日報時點 2026-10-12 17:53" in h)
check("事件時間線", "重新對沖" in h)

store["risk"] = {}
d2 = main.yunchui_data()
check("冇即時值先退回 JSON（source=json、日報時間）", d2["delta"]["source"] == "json" and d2["delta"]["net"] == -0.38 and d2["delta"]["time_hkt"] == "2026-10-12 15:46", d2["delta"])
check("退回時頁面標明非即時", "非即時" in main.build_yunchui_page(d2))

# 抓不到公開 JSON：GCS 後備
main._yunchui_cache.update(ts=0.0, data=None)
class R:  ok = False
main.requests.get = lambda *a, **k: R()
main.gcs_read_json = lambda f, d=None: PUB if "yunchui" in f else store["risk"]
pub = main.yunchui_public_json()
check("GitHub 抓唔到就用 GCS 後備", pub is not None and "gcs" in pub[1], pub)
main._yunchui_cache.update(ts=0.0, data=None)
main.gcs_read_json = lambda f, d=None: d
check("連後備都冇：status=error", main.yunchui_data()["status"] == "error")

# 路由、JSON、策略總表連結、導覽
main._yunchui_cache.update(ts=main.now_ts(), data=(PUB, "github"))
main.gcs_read_json = lambda f, d=None: store["risk"] if "risk/latest" in f else d
store["risk"] = LIVE
client = main.app.test_client()
r = client.get("/?view=yunchui")
check("?view=yunchui 回 200 且係雲垂陣頁", r.status_code == 200 and "雲垂陣" in r.get_data(as_text=True) and "Δ 預算" in r.get_data(as_text=True), r.status_code)
j = client.get("/?view=yunchui&format=json")
jd = j.get_json()
check("&format=json 回 ok 且有 delta、corrections", j.status_code == 200 and jd["status"] == "ok" and jd["delta"]["net"] == -0.39 and jd["corrections"], jd and list(jd))
check("JSON 唔含權益／保證金", "equity" not in json.dumps(jd) and "cushion" not in json.dumps(jd) and "maintenance" not in json.dumps(jd))
check("PAGE_LINKS 有 yunchui", any(v == "yunchui" for v, _ in main.PAGE_LINKS))
check("雲垂陣隊伍帶連結 ?view=yunchui", main.FUTU_TEAMS["雲垂陣"].get("link") == "?view=yunchui")
fr = main.futu_real_view()
html = main.build_futu_real_section(fr)
check("策略總表雲垂陣一格有連去 ?view=yunchui", "href='?view=yunchui'" in html, html[:300])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
