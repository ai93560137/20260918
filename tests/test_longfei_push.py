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
check("錯權杖唔寫檔", not any(k.startswith("longfei/") for k in FAKE))
print("=== 存檔 ===")
code, body = post(pkt)
check("200 stored", code == 200 and body.get("status") == "stored", (code, body))
doc = json.loads(FAKE["longfei/HSI/latest.json"][0])
check("內容齊", doc["status"]["product"] == "HSI" and len(doc["trades"]) == 2 and len(doc["decisions"]) == 1)
check("權杖唔入檔", "tok" not in FAKE["longfei/HSI/latest.json"][0].replace("stored", ""))
print("=== 決策按日存檔（去重） ===")
dpkt = {**pkt, "decisions": [{"ts": "2026-10-17T10:00:03+08:00", "final": "HOLD"},
                             {"ts": "2026-10-17T10:05:03+08:00", "final": "HOLD"}]}
post(dpkt); post(dpkt)
arch = json.loads(FAKE["longfei/HSI/decisions/2026-10-17.json"][0])
check("存檔兩筆、唔重複", len(arch) == 2, len(arch))
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
check("json 指標", j["products"]["HSI"]["metrics"]["trades"] == 2
      and abs(j["products"]["HSI"]["metrics"]["profit_factor"] - 1.5) < 1e-9, j.get("products"))
print("=== 多產品 ===")
code, body = post({**pkt, "state": {"trd_env": "SIMULATE", "product": "SPY", "pos": None},
                   "trades": [{"type": "CLOSE", "code": "US.SPY", "side": 1, "entry": 5000, "price": 5004.5,
                               "points": 4.5, "pnl_hkd_gross": 175.5, "ts": "2026-10-17T22:00:00+08:00"}]})
check("SPY 存 longfei/SPY", code == 200 and "longfei/SPY/latest.json" in FAKE, (code, body))
code, _ = post({**pkt, "state": {"product": "ZZZ"}})
check("未知產品 422", code == 422, code)
html = client.get("/?view=longfei").get_data(as_text=True)
check("總覽有 SPY 同未開始嘅 QQQ", "lf-SPY" in html and "QQQ" in html and "未開始" in html)
check("[R241] 每日／每週／每月總結", all(x in html for x in ("每日總結", "每週總結", "每月總結", "2026-10-17",
                                                         "2026-10-12 起", "2026-10", "SPY HK$+176")), html[-3000:])
check("[R245] 滾動 10 日 KPI 趨勢", "滾動 10 日 KPI 趨勢" in html)
_p = {"X": {"trades": [{"type": "CLOSE", "pnl_hkd_net": v, "ts": f"2026-10-{d:02d}T10:00:00+08:00"}
                       for d, v in ((5, 100), (6, -50), (7, 200), (20, -10))]}}
_r = main.longfei_rolling_rows(_p, window=2, rows=10)
check("[R245] 滾動計法（2 日窗）", [x[0] for x in _r] == ["2026-10-20", "2026-10-07", "2026-10-06", "2026-10-05"]
      and _r[0][5] == 190 and _r[1][5] == 150 and abs(_r[1][4] - 4.0) < 1e-9 and _r[3][1] == 1, _r)
check("[R241] 凌晨 6 點前計前一日", str(main._lf_day("2026-10-18T03:00:00+08:00")) == "2026-10-17"
      and str(main._lf_day("2026-10-18T07:00:00+08:00")) == "2026-10-18")
j = client.get("/?view=longfei&format=json").get_json()
check("合計按 HK$", j["total_hkd"]["trades"] == 1 and abs(j["total_hkd"]["points"] - 175.5) < 1e-9, j.get("total_hkd"))
check("json 唔含權杖", "tok" not in json.dumps(j))
html0 = client.get("/?view=longfei").get_data(as_text=True)
check("未有真倉顯示未開始", "未開始真倉" in html0 and "lf-real-" not in html0)
print("=== 真倉分開（R209）===")
code, body = post({**pkt, "state": {"trd_env": "REAL", "product": "SPY", "pos": None,
                                    "real_preflight": {"ok": True, "can_long": True}},
                   "trades": [{"type": "CLOSE", "code": "US.SPY", "side": -1, "entry": 5000, "price": 4990,
                               "points": 10, "pnl_hkd_gross": 1000, "ts": "2026-10-20T22:00:00+08:00"}],
                   "decisions": [{"ts": "2026-10-20T22:00:00+08:00", "final": "HOLD"}]})
check("真倉存 longfei/real/SPY", code == 200 and body.get("real") is True and "longfei/real/SPY/latest.json" in FAKE, (code, body))
check("真倉決策另外存檔", "longfei/real/SPY/decisions/2026-10-20.json" in FAKE
      and "longfei/SPY/decisions/2026-10-20.json" not in FAKE)
check("模擬 SPY 冇被蓋", json.loads(FAKE["longfei/SPY/latest.json"][0])["status"]["trd_env"] == "SIMULATE")
html = client.get("/?view=longfei").get_data(as_text=True)
check("頁面真倉同模擬分開", "lf-real-SPY" in html and "lf-SPY" in html and html.index("lf-real-SPY") < html.index("lf-SPY"))
check("[R250] 真倉／模擬倉分色框", "lf-grp lf-real" in html and "lf-grp lf-sim" in html and "#lf-sim-top" in html and ".lf-real .section" in html)
_k = "longfei/real/SPY/latest.json"
_doc = json.loads(FAKE[_k][0])
_doc["received_ts"] -= 3 * 3600                                   # [R247] 真倉停咗 3 個鐘、冇倉
FAKE[_k] = (json.dumps(_doc),) + tuple(FAKE[_k][1:])
_h = client.get("/?view=longfei").get_data(as_text=True)
_rs = _h[_h.index("lf-real-SPY"):_h.index("lf-SPY")]
check("[R247] 真倉停咗冇倉：顯示已停唔係故障", "真倉已停" in _h and "⏹ 已停（冇倉）" in _h and "程式可能停咗" not in _rs)
FAKE[_k] = (json.dumps({**_doc, "received_ts": _doc["received_ts"] + 3 * 3600}),) + tuple(FAKE[_k][1:])
j = client.get("/?view=longfei&format=json").get_json()
check("真倉合計獨立", j["total_real_hkd"]["trades"] == 1 and abs(j["total_real_hkd"]["points"] - 1000) < 1e-9
      and j["total_hkd"]["trades"] == 1, (j.get("total_real_hkd"), j.get("total_hkd")))
check("戶口檢查唔公開", "real_preflight" not in json.dumps(j) and "real_preflight" not in html)
code, _ = post({**pkt, "state": {"trd_env": "SIMULATE", "product": "QQQ", "pos": None,
                                 "sim_account": {"currency": "USD", "equity": 987654.32, "power": 123456.78},
                                 "real_account": {"currency": "USD", "equity": 555444.33, "power": 111222.33}}})
check("模擬戶口淨值存入 GCS", json.loads(FAKE["longfei/QQQ/latest.json"][0])["status"]["sim_account"]["equity"] == 987654.32)
j = client.get("/?view=longfei&format=json").get_json()
html = client.get("/?view=longfei").get_data(as_text=True)
check("模擬戶口淨值唔公開", "sim_account" not in json.dumps(j) and "987654" not in html and "987,654" not in html)
check("真實戶口淨值存入 GCS 但唔公開", json.loads(FAKE["longfei/QQQ/latest.json"][0])["status"]["real_account"]["equity"] == 555444.33
      and "real_account" not in json.dumps(j) and "555444" not in html and "555,444" not in html)

print("=== [R218] 1 分鐘 K 線存檔 ===")
bars = {"action": "longfei_bars", "token": "tok", "product": "SPY", "date": "2026-10-16",
        "fields": ["t", "o", "h", "l", "c", "v"],
        "bars": [["04:00", 1, 2, 0.5, 1.5, 10], ["bad", 1, 2, 3, 4, 5], ["04:01", "x", 1, 1, 1, 1], ["04:02", 1, 1, 1, 1, 0]]}
code, _ = post({**bars, "token": "wrong"})
check("K 線錯權杖 403", code == 403 and "longfei/bars/SPY/2026-10-16.json" not in FAKE, code)
code, body = post(bars)
doc = json.loads(FAKE.get("longfei/bars/SPY/2026-10-16.json", ("{}",))[0])
check("K 線存入私人 GCS，壞行丟走", code == 200 and body["rows"] == 2 and body["dropped"] == 2
      and doc["bars"][0] == ["04:00", 1.0, 2.0, 0.5, 1.5, 10.0] and "tok" not in json.dumps(doc), (code, body))
code, _ = post({**bars, "bars": [["04:05", 1, 1, 1, 1, 1]]})
check("同日再推會覆蓋", json.loads(FAKE["longfei/bars/SPY/2026-10-16.json"][0])["bars"][0][0] == "04:05")
code, _ = post({**bars, "product": "XXX"})
check("唔識嘅產品 422", code == 422, code)
code, _ = post({**bars, "date": "../x"})
check("日期唔啱 422", code == 422, code)
code, _ = post({**bars, "bars": [["04:00", 1, 1, 1, 1, 1]] * 1501})
check("太多行 413", code == 413, code)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
