"""[R172] 每日成交紀錄：futu_deals_build（當日逐筆、彙總、FIFO 平倉）、handle_futu_pnl 寫 futu/deals/<日期>.json、
auto_risk.pnl_slot 匯出時段。"""
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


def utc(hkt):      # [R256] 期貨戶口成交時間本身係香港時間（FUTU_DEAL_TZ_HOURS 預設 0）
    return (datetime.strptime(hkt, "%Y-%m-%d %H:%M:%S") - timedelta(hours=main.FUTU_DEAL_TZ_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def deal(hkt, code, side, qty, px, oid="o"):
    return {"time": utc(hkt), "code": code, "side": side, "qty": qty, "price": px, "order_id": oid}


print("\n=== futu_deals_build：FIFO 平倉（雲垂 self-test 同款）===")
D = date(2026, 10, 13)
doc = {"since": "2026-09-01", "fetched_hkt": "2026-10-13 16:36", "deals": [
    deal("2026-10-09 19:49:00", "HK.MHI2610", "SELL", 1, 24200.0, "a"),   # 開空
    deal("2026-10-13 12:00:00", "HK.MHI2610", "BUY", 1, 24168.0, "b"),    # 平空 +32 點
    deal("2026-10-13 15:07:00", "HK.MHI2610", "SELL", 1, 24305.0, "c"),   # 再開空
]}
r = main.futu_deals_build(doc, D)
check("date", r["date"] == "2026-10-13")
check("當日成交 2 筆、時間已換香港", [d["time_hkt"] for d in r["deals"]] == ["2026-10-13 12:00:00", "2026-10-13 15:07:00"], r["deals"])
check("買／賣標示", [d["side"] for d in r["deals"]] == ["買", "賣"])
check("只有一筆平倉", len(r["closed"]) == 1, r["closed"])
c = r["closed"][0]
check("平空 24,200→24,168 = +32 點", c["side"] == "平空" and c["open_price"] == 24200.0 and c["close_price"] == 24168.0 and c["realized_pts"] == 32)
check("MHI ×10 = +320 HKD", c["realized_ccy"] == 320 and c["ccy"] == "HKD", c)
check("彙總淨手數 0", r["summary"][0]["net_qty"] == 0 and r["summary"][0]["buy_avg"] == 24168.0 and r["summary"][0]["sell_avg"] == 24305.0, r["summary"])
check("前一日冇平倉", main.futu_deals_build(doc, date(2026, 10, 9))["closed"] == [])
check("前一日只有開倉一筆", len(main.futu_deals_build(doc, date(2026, 10, 9))["deals"]) == 1)

print("\n=== 多頭部分平倉、HSI ×50、美期權 USD ===")
doc2 = {"deals": [
    deal("2026-10-13 10:00:00", "HK.MHI2610", "BUY", 3, 100.0, "a"),
    deal("2026-10-13 11:00:00", "HK.MHI2610", "SELL", 2, 110.0, "b"),
    deal("2026-10-12 15:09:57", "HK.HSI2610", "BUY", 1, 24254.0, "c"),
    deal("2026-10-13 09:30:00", "HK.HSI2610", "SELL", 2, 24300.0, "d"),    # 平多 1（+46 點）＋ 開空 1
    deal("2026-10-13 21:40:00", "US.EX32610C7830x0", "SELL", 1, 88.75, "e"),
    deal("2026-10-13 22:10:00", "US.EX32610C7830x0", "BUY", 1, 60.25, "f"),   # 平空 +28.5 點 ×5 USD
]}
r2 = main.futu_deals_build(doc2, D)
cl = {(c["code"], c["side"]): c for c in r2["closed"]}
check("MHI 平多 2 手 +10 點 = +200 HKD", cl[("HK.MHI2610", "平多")]["qty"] == 2 and cl[("HK.MHI2610", "平多")]["realized_ccy"] == 200)
check("HSI 平多 1 手 +46 點 = +2,300 HKD", cl[("HK.HSI2610", "平多")]["qty"] == 1 and cl[("HK.HSI2610", "平多")]["realized_ccy"] == 2300)
check("HSI 剩 1 手新開空（彙總淨 −2）", [x for x in r2["summary"] if x["code"] == "HK.HSI2610"][0]["net_qty"] == -2)
check("MES 週權平空 +28.5 點 = +142.5 USD", cl[("US.EX32610C7830x0", "平空")]["realized_ccy"] == 142.5 and cl[("US.EX32610C7830x0", "平空")]["ccy"] == "USD")
check("壞資料被略過", main.futu_deals_build({"deals": [{"time": "x", "code": "HK.MHI2610"}, {"time": utc("2026-10-13 10:00:00"), "code": "HK.MHI2610", "side": "BUY", "qty": 0, "price": 1}]}, D)["deals"] == [])

print("\n=== handle_futu_pnl 寫 futu/deals/<今日>.json 同前一日 ===")
client = main.app.test_client()
today = datetime.now(main.HK_TZ).date()
body = {"action": "futu_pnl", "token": "tok", "since": "2026-09-01", "fetched_hkt": "now",
        "deals": [deal(f"{today - timedelta(days=1)} 19:49:00", "HK.MHI2610", "SELL", 1, 24200.0, "a"),
                  deal(f"{today} 12:00:00", "HK.MHI2610", "BUY", 1, 24168.0, "b")]}
res = client.post("/", data=json.dumps(body), content_type="application/json")
js = res.get_json()
check("futu_pnl 回 stored", res.status_code == 200 and js.get("status") == "stored", js)
check("回傳寫咗兩個日期", js.get("daily") == [today.isoformat(), (today - timedelta(days=1)).isoformat()], js)
check("futu/pnl/latest.json 照舊", main.FUTU_PNL_FILE in FAKE)
f_today = f"futu/deals/{today.isoformat()}.json"
check("今日檔存在", f_today in FAKE)
dd = json.loads(FAKE[f_today][0])
check("今日檔有平倉 +320 HKD", dd["closed"] and dd["closed"][0]["realized_ccy"] == 320, dd.get("closed"))
dy = json.loads(FAKE[f"futu/deals/{(today - timedelta(days=1)).isoformat()}.json"][0])
check("前一日檔只有開倉", len(dy["deals"]) == 1 and dy["closed"] == [])
check("冇成交照舊 422", client.post("/", data=json.dumps({"action": "futu_pnl", "token": "tok", "deals": []}),
                                 content_type="application/json").status_code == 422)

print("\n=== auto_risk.pnl_slot 匯出時段 ===")
sys.path.insert(0, "/home/user/20260918/gcp_ib")
import auto_risk                                 # noqa: E402
t = lambda h, m: datetime(2026, 10, 13, h, m, tzinfo=auto_risk.HKT)
check("03:04 未到任何時段", auto_risk.pnl_slot(t(3, 4)) is None)
check("03:05 → 03:05", auto_risk.pnl_slot(t(3, 5)) == "2026-10-13|03:05")
check("05:29 仍係 03:05", auto_risk.pnl_slot(t(5, 29)) == "2026-10-13|03:05")
check("05:30 → 05:30", auto_risk.pnl_slot(t(5, 30)) == "2026-10-13|05:30")
check("16:34 仍係 05:30", auto_risk.pnl_slot(t(16, 34)) == "2026-10-13|05:30")
check("16:35 → 16:35", auto_risk.pnl_slot(t(16, 35)) == "2026-10-13|16:35")
check("23:59 仍係 16:35", auto_risk.pnl_slot(t(23, 59)) == "2026-10-13|16:35")
check("SCRIPT_VERSION R213（碎股有維持保證金都當冇倉）", auto_risk.SCRIPT_VERSION == "R213" and callable(auto_risk.fetch_cme))

print("\n=== [R175] 保證金警報附補倉建議 ===")
W, C, F, CL = main.FUTU_MARGIN_WARN, main.FUTU_MARGIN_CRIT, main.FUTU_MARGIN_FLATTEN, main.FUTU_MARGIN_CLEAR
main.FUTU_MARGIN_WARN, main.FUTU_MARGIN_CRIT, main.FUTU_MARGIN_FLATTEN, main.FUTU_MARGIN_CLEAR = 150000, 100000, 60000, 180000
check("緩衝 140k warn → 入金 4 萬", "入金 HK$40,000" in main.futu_topup_line(140000, "warn"))
check("緩衝 95k critical → 30 分鐘內 9 萬代替減半", "30 分鐘內入金 HK$90,000" in main.futu_topup_line(95000, "critical"))
check("緩衝 55k → 唔接受補倉代替全平", "唔接受補倉代替全平" in main.futu_topup_line(55000, "critical"))
check("緩衝 160k → 冇補倉建議", main.futu_topup_line(160000, "warn") is None)
txt = main.futu_margin_text("start", "warn", "now", {"cushion": 140000})
check("警報文字有補倉一行", "💰 補倉" in txt and "唔會落單" in txt, txt)
check("解除訊息冇補倉", "💰" not in main.futu_margin_text("clear", None, "now", {"cushion": 190000}))
main.FUTU_MARGIN_WARN, main.FUTU_MARGIN_CRIT, main.FUTU_MARGIN_FLATTEN, main.FUTU_MARGIN_CLEAR = W, C, F, CL

print("\n=== 配對：MHI2611 全部歸人手，MHI2610 1 手係雲垂對沖 ===")
a = main.futu_team_assign([{"code": "HK.MHI2611", "qty": -10}, {"code": "HK.MHI2610", "qty": -1}])
check("MHI2611 −10 → 使用者人手", [(x["team"], x["qty"]) for x in a if x["code"] == "HK.MHI2611"] == [(main.FUTU_TEAM_MANUAL, -10)], a)
check("MHI2610 −1 → 雲垂對沖", [(x["team"], x["qty"]) for x in a if x["code"] == "HK.MHI2610"] == [("雲垂陣", -1)], a)

print("\n=== [R237] 龍飛陣美股真倉配對 ===")
a = main.futu_team_assign([{"code": "US.SPY", "qty": 15}, {"code": "US.QQQ", "qty": -10}, {"code": "US.DIA", "qty": 5}])
check("SPY／QQQ → 龍飛陣", {x["code"]: x["team"] for x in a if x["code"] in ("US.SPY", "US.QQQ")} == {"US.SPY": "龍飛陣", "US.QQQ": "龍飛陣"}, a)
check("[R238] DIA（候選）→ 龍飛陣", [x["team"] for x in a if x["code"] == "US.DIA"] == ["龍飛陣"], a)
b2 = main.futu_team_assign([{"code": "US.NVDA", "qty": 3}, {"code": "US.EWZ", "qty": -2}, {"code": "US.ARKK", "qty": 1}])
check("[R238] 七雄／ETF 候選歸龍飛陣、名單外 ARKK 仍未配對", [x["team"] for x in b2] == ["龍飛陣", "龍飛陣", main.FUTU_TEAM_UNMATCHED], b2)
check("龍飛陣喺 FUTU_TEAMS（策略總表有卡）", "龍飛陣" in main.FUTU_TEAMS)

a3 = main.futu_team_assign([{"code": "US.MNQ2612", "qty": -2}])
check("[R239] MNQ2612 → 使用者人手", [x["team"] for x in a3] == [main.FUTU_TEAM_MANUAL], a3)

print("\n=== [R256] 富途成交時區 ===")
check("期貨戶口預設唔加鐘（本身係香港時間）", main.FUTU_DEAL_TZ_HOURS == 0)
check("期貨戶口 HSI 夜市 22:36 照當香港時間", main.futu_deal_hkt({"time": "2026-10-21 22:36:00.123", "code": "HK.HSI2612", "account": "期貨帳戶"}) == datetime(2026, 10, 21, 22, 36))
check("證券戶口美股：美東 09:50（夏令）→ 香港 21:50", main.futu_deal_hkt({"time": "2026-10-19 09:50:00", "code": "US.SPY", "account": "證券帳戶-HK"}) == datetime(2026, 10, 19, 21, 50))
check("證券戶口美股：美東 09:50（冬令）→ 香港 22:50", main.futu_deal_hkt({"time": "2026-12-01 09:50:00", "code": "US.SPY", "account": "證券帳戶-HK"}) == datetime(2026, 12, 1, 22, 50))

print("\n=== [R284] 人手守則①：蝕緊嘅方向加注 ===")
import tempfile                                     # noqa: E402
from pathlib import Path as _P                      # noqa: E402
_sf = _P(tempfile.mkdtemp()) / "manual_rules_state.json"
_r = lambda code, q, pl: {"source": "positions", "code": code, "qty": q, "futu_pl": pl}
check("第一次冇基準 → 冇警報", auto_risk.add_to_loser([_r("US.ES2612", -1, -500)], _sf) == {})
a = auto_risk.add_to_loser([_r("US.ES2612", -2, -900)], _sf)
check("淡倉蝕緊由 −1 加到 −2 → 警報", list(a) == ["rule1:US.ES2612"] and "−1" not in a["rule1:US.ES2612"] and "-1 → -2" in a["rule1:US.ES2612"], a)
check("照舊 −2 蝕緊 → 警報保持", list(auto_risk.add_to_loser([_r("US.ES2612", -2, -1200)], _sf)) == ["rule1:US.ES2612"])
check("減返 −1 → 解除", auto_risk.add_to_loser([_r("US.ES2612", -1, -600)], _sf) == {})
check("有浮賺時加注 → 冇警報", auto_risk.add_to_loser([_r("US.ES2612", -3, 400)], _sf) == {})
check("期權唔計", auto_risk.add_to_loser([_r("HK.HSI261023P23700000", -2, -9000)], _sf) == {}
      and auto_risk.add_to_loser([_r("HK.HSI261023P23700000", -3, -9000)], _sf) == {})
auto_risk.add_to_loser([_r("HK.HSI2610", 1, -100)], _sf)
check("HSI 期貨蝕緊加注 → 警報", "rule1:HK.HSI2610" in auto_risk.add_to_loser([_r("HK.HSI2610", 2, -800)], _sf))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
