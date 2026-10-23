"""[R193] 保證金急升預警（auto_risk.mm_jump）＋每日壓力情景（risk_report M['stress'] → Cloud Run ops/risk/stress_latest.json）。"""
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

import main                                      # noqa: E402
from datetime import date, datetime, timedelta   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")


import tempfile                                  # noqa: E402
from pathlib import Path                         # noqa: E402
sys.path.insert(0, "/home/user/20260918/gcp_ib")
sys.path.insert(0, "/home/user/20260918/tradingview")
import auto_risk                                 # noqa: E402
import risk_report                               # noqa: E402

print("\n=== risk_report 風控階梯分級（RISK_LADDER 日盤／夜盤 ×1.5）===")
L = risk_report.ladder_level
check("日盤 40k → A", L(40_000) == "A")
check("日盤 30k → B", L(30_000) == "B")
check("日盤 20k → C", L(20_000) == "C")
check("日盤 10k → D", L(10_000) == "D")
check("夜盤 50k → B（56.25k 線）", L(50_000, True) == "B")
N = lambda h, m: risk_report.ladder_night(datetime(2026, 10, 15, h, m, tzinfo=risk_report.HKT_TZ))
check("17:14 日盤", not N(17, 14))
check("17:15 夜盤", N(17, 15))
check("02:59 夜盤", N(2, 59))
check("03:00 日盤", not N(3, 0))
check("同 daily_books LADDER 一致", risk_report.LADDER_CUSHION == {"B": 37_500, "C": 25_000, "D": 15_000})

print("\n=== risk_report.build 出 M['stress']（只得標普倉）===")
tmp = Path(tempfile.mkdtemp())
book = json.loads(Path("/home/user/20260918/tradingview/data_external/risk_book.json").read_text(encoding="utf-8"))
(tmp / "risk_book.json").write_text(json.dumps(book), encoding="utf-8")
q = {"positions": [
        {"code": "US.EW2610P7750x0", "qty": -1, "bid": 88.0, "ask": 89.0, "last": 88.5},
        {"code": "US.ES2612", "qty": -1, "bid": 7746.5, "ask": 7746.75, "last": 7746.5},
        {"code": "US.MES2612", "qty": -4, "bid": 7746.5, "ask": 7747.0, "last": 7747.0}],
     "accounts": [{"currency": "HKD", "total_assets": 520_000, "maintenance_margin": 310_000}]}
(tmp / "q.json").write_text(json.dumps(q), encoding="utf-8")
txt, M = risk_report.build(str(tmp / "risk_book.json"), str(tmp / "q.json"), 7_800_000)
st = M.get("stress") or {}
sc = {r["name"]: r for r in st.get("scenarios", [])}
check("有 8 個情景", len(sc) == 8, list(sc))
check("冇恒指倉：HSI −5% 緩衝不變", sc.get("HSI −5%", {}).get("cushion_after") == round(M["cushion"]), (sc.get("HSI −5%"), M["cushion"]))
check("偏淡：ES +5% 緩衝低過 ES −5%", sc["ES +5%"]["cushion_after"] < sc["ES −5%"]["cushion_after"])
check("每個情景有 A–D 級", all(r["ladder"] in "ABCD" for r in sc.values()))
check("lines 跟日夜盤", st["lines"]["B"] in (37_500, 56_250))

print("\n=== R196：富途恒指期權（book 冇）自動入模型 ===")
q2 = dict(q, positions=q["positions"] + [
    {"code": "HK.HSI261023P23550000", "qty": -1, "bid": 66.0, "ask": 68.0, "last": 67.0, "open_price": 67.0},
    {"code": "HK.HSI261023C24700000", "qty": -1, "bid": 43.0, "ask": 45.0, "last": 44.0, "open_price": 44.0}])
(tmp / "q2.json").write_text(json.dumps(q2), encoding="utf-8")
txt2, M2 = risk_report.build(str(tmp / "risk_book.json"), str(tmp / "q2.json"), 7_800_000)
check("報告有兩條自動 HSI 腿", "HSI 10/23 P23550（富途實際 -1）" in txt2 and "HSI 10/23 C24700（富途實際 -1）" in txt2)
check("用賣價做平倉價（68／45）", "| 68.00 |" in txt2 and "| 45.00 |" in txt2)
check("恒指 Δ 有出（delta_parts.hsi_all）", isinstance((M2.get("delta_parts") or {}).get("hsi_all"), float), M2.get("delta_parts"))
sc2 = {r["name"]: r for r in M2["stress"]["scenarios"]}
check("HSI ±5% 情景而家會郁緩衝", sc2["HSI −5%"]["cushion_after"] < round(M2["cushion"]) and sc2["HSI +5%"]["cushion_after"] < round(M2["cushion"]),
      (sc2["HSI −5%"], sc2["HSI +5%"], M2["cushion"]))
check("週權說明有印", "風揚陣「方向一」" in txt2)
exp_days = (date(2026, 10, 23) - datetime.now(risk_report.HKT_TZ).date()).days
check("R197：到期日數用今日（唔係 book 10/10）", f"2026-10-23（{max(exp_days, 0)} 天）" in txt2 or exp_days <= 0, exp_days)
q3 = dict(q, positions=q["positions"] + [{"code": "HK.HSI261023P23550000", "qty": 0, "last": 67.0}])
(tmp / "q3.json").write_text(json.dumps(q3), encoding="utf-8")
txt3, _ = risk_report.build(str(tmp / "risk_book.json"), str(tmp / "q3.json"), 7_800_000)
check("手數 0 唔加腿", "富途實際" not in txt3.split("HSI 10/23")[0] or "HSI 10/23 P23550（富途實際" not in txt3)

print("\n=== R260：收市後買賣差離譜唔當平倉價（10-24 04:45 MES 跨式誤報）===")
q4 = dict(q, positions=q["positions"] + [
    {"code": "US.EX32611P7700x0", "qty": -1, "bid": 122.0, "ask": 1500.0, "last": 144.0, "open_price": 148.5},
    {"code": "US.EX32611C7700x0", "qty": -1, "ask": 131.0, "last": 109.0, "open_price": 146.5}])
(tmp / "q4.json").write_text(json.dumps(q4), encoding="utf-8")
txt4, M4 = risk_report.build(str(tmp / "risk_book.json"), str(tmp / "q4.json"), 7_800_000)
use4 = M4["stop_use"].get("MES 跨式")
check("P7700 用最後成交 144（唔用賣價 1,500）→ 用量 (131+144)/590 ≈ 47%", use4 is not None and abs(use4 - 275 / 590) < 0.01, use4)
check("報告寫明買賣差太闊", "買賣差太闊" in txt4)
det = M4.get("stop_detail", {}).get("MES 跨式", "")
check("stop_detail 列兩隻腿同價", "MES 11/20 P7700 144.0" in det and "MES 11/20 C7700 131.0" in det and "止損 590" in det, det)
a4 = auto_risk.alerts({"stop_use": {"MES 跨式": 1.2}, "stop_detail": {"MES 跨式": det}}, 0, 0.8)
check("警報附腿同價", "↳" in a4["stop:MES 跨式"] and "P7700" in a4["stop:MES 跨式"], a4)
q5 = dict(q, positions=q["positions"] + [
    {"code": "US.EX32611P7700x0", "qty": -1, "bid": 300.0, "ask": 310.0, "last": 305.0, "open_price": 148.5},
    {"code": "US.EX32611C7700x0", "qty": -1, "bid": 300.0, "ask": 310.0, "last": 305.0, "open_price": 146.5}])
(tmp / "q5.json").write_text(json.dumps(q5), encoding="utf-8")
_, M5 = risk_report.build(str(tmp / "risk_book.json"), str(tmp / "q5.json"), 7_800_000)
check("正常報價照用賣價：(310+310)/590 > 100% 照觸止損", M5["stop_use"]["MES 跨式"] > 1, M5["stop_use"])

print("\n=== auto_risk.mm_jump 維持保證金單日急升 ===")
sf = tmp / "margin_base.json"
T = lambda d, h: datetime(2026, 10, d, h, 0, tzinfo=auto_risk.HKT)
check("第一個讀數做基準、唔報", auto_risk.mm_jump(T(14, 9), {"maintenance_margin": 200_000}, sf, 0.3) is None)
check("升 20% 唔報", auto_risk.mm_jump(T(14, 12), {"maintenance_margin": 240_000}, sf, 0.3) is None)
msg = auto_risk.mm_jump(T(14, 15), {"maintenance_margin": 400_000, "cushion": 50_000}, sf, 0.3)
check("翻倍 → 報 100%", msg and "100%" in msg, msg)
check("03:51 仍屬前一個交易日（06:00 為界）", auto_risk.mm_jump(T(15, 3), {"maintenance_margin": 400_000}, sf, 0.3) is not None)
check("新一日 06:00 起重設基準 → 解除", auto_risk.mm_jump(T(15, 7), {"maintenance_margin": 400_000}, sf, 0.3) is None)
check("冇維持保證金唔報", auto_risk.mm_jump(T(15, 8), {}, sf, 0.3) is None)
check("SCRIPT_VERSION R213", auto_risk.SCRIPT_VERSION == "R213")

print("\n=== Cloud Run：metrics.stress 保留＋另存 ops/risk/stress_latest.json ===")
client = main.app.test_client()
body = {"action": "futu_risk", "token": "tok", "run_hkt": "2026-10-15 16:30", "script_version": "R193",
        "metrics": {"equity": 7_800_000, "cushion": 210_000, "delta": {}, "stop_use": {},
                    "stress": {"night": False, "lines": {"B": 37500, "C": 25000, "D": 15000},
                               "scenarios": [{"name": "ES +5%", "cushion_after": 60_000, "ladder": "A", "junk": 1}]}},
        "alerts": {"mm_jump": "⚠ 富途維持保證金今日升 100%"}, "positions": [], "report": "x"}
res = client.post("/", data=json.dumps(body), content_type="application/json")
check("futu_risk 回 stored", res.status_code == 200 and res.get_json().get("status") == "stored", res.get_json())
check("stress_latest.json 已寫", main.FUTU_STRESS_FILE in FAKE)
sd = json.loads(FAKE[main.FUTU_STRESS_FILE][0])
check("stress 檔有 asof／cushion／scenarios", sd["asof_hkt"] == "2026-10-15 16:30" and sd["cushion"] == 210_000
      and sd["scenarios"][0] == {"name": "ES +5%", "cushion_after": 60_000, "ladder": "A"}, sd)
lat = json.loads(FAKE[main.FUTU_RISK_FILE][0])
check("latest.json metrics 保留 stress", lat["metrics"].get("stress", {}).get("lines", {}).get("B") == 37500)
check("mm_jump 歸總指揮", main.futu_alert_team("mm_jump") == "總指揮")
FAKE.clear()
client.post("/", data=json.dumps({**body, "metrics": {"equity": 1, "delta": {}, "stop_use": {}}}), content_type="application/json")
check("冇 stress 就唔寫 stress 檔", main.FUTU_STRESS_FILE not in FAKE)

print("\n=== [R206] 證券戶口：碎股／空戶口當 A；沽空市值負數取絕對值 ===")
def _sec(accs):
    qf = {"fetched_hkt": "2026-10-17 01:00:00", "positions": [], "quotes": {}, "accounts": accs}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(qf, fh)
    return risk_report.build("/home/user/20260918/tradingview/data_external/risk_book.json", fh.name, None)[1].get("sec")
FUT0 = {"account": "期貨帳戶", "currency": "HKD", "total_assets": 500_000, "maintenance_margin": 400_000}
s0 = _sec([FUT0, {"account": "證券帳戶-HK", "currency": "HKD", "total_assets": 120, "maintenance_margin": 0, "market_val": 97}])
check("碎股 HK$97（未入錢）→ 唔算有倉、級別 A", s0 and not s0["exposed"] and s0["ladder"] == "A", s0)
s0b = _sec([FUT0, {"account": "證券帳戶-HK", "currency": "HKD", "total_assets": 66, "maintenance_margin": 39, "market_val": 95}])
check("[R213] 碎股有 HK$39 維持保證金（10-17 實例）→ 都當冇倉、唔警報", s0b and not s0b["exposed"] and s0b["ladder"] == "A", s0b)
s0c = _sec([FUT0, {"account": "證券帳戶-HK", "currency": "HKD", "total_assets": 50_000, "maintenance_margin": 20_000, "market_val": 0}])
check("[R213] 維持保證金 2 萬（大過門檻）→ 算有倉", s0c and s0c["exposed"], s0c)
s1 = _sec([FUT0, {"account": "證券帳戶-HK", "currency": "HKD", "total_assets": 25_000, "maintenance_margin": 0, "market_val": -19_156}])
check("沽空市值 −19,156 → 有倉、緩衝 25k → B", s1 and s1["exposed"] and s1["ladder"] == "B", s1)
s2 = _sec([FUT0, {"account": "證券帳戶-HK", "currency": "N/A", "total_assets": 1, "maintenance_margin": 0}])
check("幣種 N/A（SIMULATE 式）→ 唔計、唔出錯", s2 is None, s2)

print("\n=== [R205] 證券戶口監察（龍飛陣 ETF 轉真倉前）===")
SL = risk_report.sec_ladder_level
check("證券 35k → A", SL(35_000) == "A")
check("證券 25k → B", SL(25_000) == "B")
check("證券 15k → C", SL(15_000) == "C")
check("證券 5k → D", SL(5_000) == "D")
FUT = {"account": "期貨帳戶", "currency": "HKD", "total_assets": 500_000, "maintenance_margin": 400_000}
SEC = {"account": "證券帳戶-HK", "currency": "HKD", "total_assets": 300_000, "maintenance_margin": 0, "market_val": 0}
f_, s_ = risk_report.pick_accounts([SEC, FUT])
check("按標籤揀：證券戶口排前都唔會當期貨", f_ is FUT and s_ is SEC)
f_, s_ = risk_report.pick_accounts([{"currency": "HKD", "total_assets": 1}])
check("舊檔冇標籤：照舊揀第一個港幣戶口、冇證券", f_ is not None and s_ is None)
f_, s_ = risk_report.pick_accounts([FUT])
check("冇證券戶口 → None", f_ is FUT and s_ is None)

base = {"gap": 1, "stop_use": {}, "delta": {}}
a = auto_risk.alerts({**base, "sec": {"cushion": 25_000, "ladder": "B", "exposed": True}}, 60_000, 0.8)
check("證券有倉、Ⓑ → sec_margin 警報", "sec_margin" in a and "→ B" in a["sec_margin"], a)
a = auto_risk.alerts({**base, "sec": {"cushion": 0, "ladder": "D", "exposed": False}}, 60_000, 0.8)
check("證券冇倉冇孖展（未入錢）→ 唔警報", "sec_margin" not in a, a)
a = auto_risk.alerts({**base, "sec": {"cushion": 90_000, "ladder": "A", "exposed": True}}, 60_000, 0.8)
check("證券 Ⓐ → 唔警報", "sec_margin" not in a, a)

with tempfile.TemporaryDirectory() as td:
    fl, sl = Path(td) / "ladder_level", Path(td) / "ladder_level_sec"
    os.environ["ZHUGE_LADDER_FILE"], os.environ["ZHUGE_SEC_LADDER_FILE"] = str(fl), str(sl)
    t = datetime(2026, 10, 19, 10, 0)
    auto_risk.write_ladder(t, {"gap": 1, "cushion": 90_000, "sec": {"ladder": "B"}})
    check("期貨級別檔照寫", fl.read_text(encoding="utf-8").startswith("A day 2026-10-19 10:00"), fl.read_text(encoding="utf-8"))
    check("證券級別檔寫 B sec", sl.read_text(encoding="utf-8").startswith("B sec 2026-10-19 10:00"), sl.read_text(encoding="utf-8"))
    auto_risk.write_ladder(t, {"gap": -1, "cushion": 90_000, "sec": {"ladder": "A"}})
    check("硬止損 → 證券都寫 D hard_stop", sl.read_text(encoding="utf-8").startswith("D sec") and "hard_stop" in sl.read_text(encoding="utf-8"))
    sl.unlink()
    auto_risk.write_ladder(t, {"gap": 1, "cushion": 90_000})
    check("冇 sec 數據 → 唔寫證券檔", not sl.exists())
    del os.environ["ZHUGE_LADDER_FILE"], os.environ["ZHUGE_SEC_LADDER_FILE"]

    os.environ["LONGFEI_EXTRA_PRODUCTS"], os.environ["AI_DATA_DIR"] = "SPY,QQQ", str(Path(td) / "ai")
    sys.path.insert(0, "/home/user/20260918/gcp_ib/vm_futu")
    import importlib, longfei_guard as g                # noqa: E402
    g = importlib.reload(g)
    names = lambda ds: sorted(d.name for d in ds)
    check("未開 ETF_SEC：期貨級別管全部產品", names(g.dirs_for("fut", False)) == ["ai", "ai_QQQ", "ai_SPY"])
    check("開 ETF_SEC：期貨只管 HSI", names(g.dirs_for("fut", True)) == ["ai"])
    check("開 ETF_SEC：證券管 SPY／QQQ", names(g.dirs_for("sec", True)) == ["ai_QQQ", "ai_SPY"])
    os.environ["LONGFEI_REAL_PRODUCTS"] = "SPY,HSI"     # [R209] 真倉程式
    g = importlib.reload(g)
    check("真倉資料夾入 guard", [l for l, _ in g.DIRS][-2:] == ["SPY真倉", "HSI真倉"])
    check("真倉：期貨級別管 HSI 同 HSI 真倉", names(g.dirs_for("fut", True)) == ["ai", "ai_real_HSI"])
    check("真倉：證券級別管 ETF 同 ETF 真倉", names(g.dirs_for("sec", True)) == ["ai_QQQ", "ai_SPY", "ai_real_SPY"])
    del os.environ["LONGFEI_REAL_PRODUCTS"]
    g = importlib.reload(g)
    sl.write_text("B sec 2026-10-19 10:00\n", encoding="utf-8")
    from datetime import timezone as _tz             # noqa: E402
    now = datetime(2026, 10, 19, 10, 5, tzinfo=g.HKT)
    act, why, alarm = g.desired(now, sl)
    check("guard 讀證券級別 B → PAUSE、唔警報", act == "PAUSE" and not alarm and "sec" in why, (act, why, alarm))
    sl.write_text("D sec 2026-10-19 10:00\n", encoding="utf-8")
    act, why, alarm = g.desired(now, sl)
    check("guard 讀證券級別 D → 只警報唔停", act is None and alarm, (act, why, alarm))
    del os.environ["LONGFEI_EXTRA_PRODUCTS"], os.environ["AI_DATA_DIR"]

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
