"""[R291] 🌌 天覆陣（xau/）：心跳權杖、K 線累積去重、電閘 LOCK 唔問 AI、篩選、硬性規則、紙上止損／止賺／最長持倉、
實倉指令佇列同回報、頁面。Claude 用假 brain，GCS 用假 bucket。"""
import json, os, sys, time, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", GATE_MODEL="claude-haiku-5-5",
                  XAU_MAX_SL_USD="30", XAU_MIN_SL_USD="2", XAU_MAX_HOLD_MIN="120", XAU_MAX_TRADES_PER_DAY="3",
                  ANTHROPIC_API_KEY="x")
sys.path.insert(0, "/home/user/20260918/xau")

import google, google.cloud                      # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def download_as_bytes(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0].encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1
        FAKE[self.name] = (data, gen); self.generation = gen
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
exc_mod = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
exc_mod.PreconditionFailed = _PC; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod

import main as xau, config, rules, paper, market   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [1792600000.0]              # 2026-10-21 週三 ~ 20:26 UTC = 16:26 ET，開市
xau.now_ts = lambda: NOW[0]
paper.rules.hold_expired = rules.hold_expired

class FakeBrain:
    def __init__(self): self.screen_look = True; self.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}; self.calls = []
    def screen(self, ctx): self.calls.append("screen"); return {"look": self.screen_look, "reason": "睇下", "_usage": {"in": 100, "out": 10, "model": "claude-haiku-5-5"}, "_ms": 300}
    def decide(self, ctx): self.calls.append("decide"); self.ctx = ctx; return {**self.decision, "_usage": {"in": 5000, "out": 300, "cache_read": 4000, "model": "claude-opus-5-5"}, "_ms": 2500, "_lessons": None}
FB = FakeBrain(); xau._brain = FB

def set_gate(open_):
    FAKE["zhuge_gate_state.json"] = (json.dumps({"armed": open_, "hard_lock": None, "news_lock": False, "risk": {"reason": "六關全過"}}), 1)

T0 = 1792599000
def hb(i, close, high=None, low=None, new=True, token="tok"):
    """第 i 根 M1（每根 60 秒），同時帶一根 M15。"""
    t = T0 + i * 60
    o = close - 0.5
    body = {"action": "check_gate", "status": "MONITORING", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000,
            "credit": 5000, "floating": 0, "daily_pnl": 0, "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
            "m1_ohlc": {"symbol": "XAUUSD", "time": t, "open": o, "high": high if high is not None else max(o, close) + 0.3,
                        "low": low if low is not None else min(o, close) - 0.3, "close": close, "volume": 10, "is_new_bar": new},
            "m15_ohlc": {"time": T0 + (i // 15) * 900, "open": o, "high": close + 1, "low": close - 1, "close": close,
                         "atr_m1": 0.4, "atr_m5": 0.9, "atr_m15": 2.1}}
    if token is not None:
        body["token"] = token
    NOW[0] = t + 5
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

FAKE["xau/m15.json"] = (json.dumps([{"time": T0 - 900 * (30 - k), "open": 3999.0, "high": 4001.0, "low": 3998.0, "close": 4000.0} for k in range(30)]), 1)
print("=== 權杖 ===")
check("冇權杖 → 403", hb(0, 4000, token=None)[0] == 403)
check("錯權杖 → 403", hb(0, 4000, token="bad")[0] == 403)
check("GET 頁面唔使權杖", client.get("/").status_code == 200)

print("=== 累積歷史 ===")
set_gate(False)
for i in range(29):
    st, d = hb(i, 4000 + i * 0.1)
check("前 29 根：M1 歷史不足，冇問 AI", st == 200 and FB.calls == [] and "歷史不足" in d["message"], (d, FB.calls))
for i in range(29, 40):
    st, d = hb(i, 4000 + i * 0.1)
check("第 30 根起：照問（舊電閘 LOCK 唔係硬閘）", FB.calls and d["decision"] is not None, (d, FB.calls))
FB.calls.clear()
st, d = hb(39, 4000 + 39 * 0.1)
check("同一根重送 → duplicate", d.get("message") == "duplicate M1 bar", d)
st, d = hb(39, 4000, new=False)
check("is_new_bar=false 只存快照", d.get("message") is None and d["status"] == "monitoring", d)
m1 = json.loads(FAKE["xau/m1.json"][0]); check("M1 歷史 40 根、M15 ≥ 32 根", len(m1) == 40 and len(json.loads(FAKE["xau/m15.json"][0])) >= 32, len(json.loads(FAKE["xau/m15.json"][0])))

print("=== 舊電閘只係參考：LOCK 都照問 ===")
FB.screen_look = False
st, d = hb(40, 4004)
check("LOCK 且空倉 → 照篩選（唔係硬閘）", FB.calls == ["screen"] and "篩選" in d["message"], (FB.calls, d))
FB.calls.clear()

print("=== 篩選 ===")
set_gate(True); FB.screen_look = False
st, d = hb(41, 4004.5)
check("篩選 look=false → 只篩、唔決策", FB.calls == ["screen"] and d["decision"]["final"] == "HOLD", (FB.calls, d))
FB.calls.clear(); FB.screen_look = True

print("=== 硬性規則（純函數）===")
pos0 = None
check("冇止損 → HOLD", rules.validate_decision({"action": "OPEN_LONG", "confidence": 0.9}, position=pos0, last=4000, can_open=True, trades_today=0)[0] == "HOLD")
check("止損錯邊 → HOLD", rules.validate_decision({"action": "OPEN_LONG", "stop_price": 4005, "confidence": 0.9}, position=pos0, last=4000, can_open=True, trades_today=0)[3] == "止損喺錯邊")
check("止損太遠 → HOLD", "超過上限" in rules.validate_decision({"action": "OPEN_LONG", "stop_price": 3900, "confidence": 0.9}, position=pos0, last=4000, can_open=True, trades_today=0)[3])
a, s_, t_, w = rules.validate_decision({"action": "OPEN_LONG", "stop_price": 3999.5, "target_price": 3990, "confidence": 0.9}, position=pos0, last=4000, can_open=True, trades_today=0)
check("止損太近 → 推到下限 2；止賺錯邊 → 唔送", a == "OPEN_LONG" and s_ == 3998.0 and t_ is None, (a, s_, t_))
check("信心不足 → HOLD", "信心" in rules.validate_decision({"action": "OPEN_SHORT", "stop_price": 4010, "confidence": 0.3}, position=pos0, last=4000, can_open=True, trades_today=0)[3])
check("can_open=False → HOLD", "唔准開" in rules.validate_decision({"action": "OPEN_SHORT", "stop_price": 4010, "confidence": 0.9}, position=pos0, last=4000, can_open=False, trades_today=0)[3])
print("=== 風控階梯（純函數，龍飛陣做法：冇硬鎖）===")
L = lambda **k: rules.ladder(**{"principal_hkd": 20000, "own_equity": 20000, "peak_equity": 20000, "daily_pnl_hkd": 0, "margin_level": None, "night": False, **k})
check("正常 → 唔停", not L()["pause"] and not L()["stop"] and not L()["alerts"])
check("日蝕 −3% → PAUSE（daily）", L(daily_pnl_hkd=-600)["pause"] and L(daily_pnl_hkd=-600)["pause_kind"] == "daily" and not L(daily_pnl_hkd=-600)["stop"])
check("日蝕 −6% → STOP", L(daily_pnl_hkd=-1200)["stop"])
check("夜盤 ×1.5：−3% 唔停、−4.5% 先 PAUSE", not L(daily_pnl_hkd=-600, night=True)["pause"] and L(daily_pnl_hkd=-900, night=True)["pause"])
check("累計 −25% → cum_loss 旗（由 apply_ladder 做當日事件 PAUSE）", L(own_equity=15000)["cum_loss"] and not L(own_equity=15000)["pause"] and "cum_loss" not in L(own_equity=15000)["alerts"])
check("回撤 10%／20% → 只提示", "dd1" in L(own_equity=18000)["alerts"] and "dd2" in L(own_equity=16000)["alerts"] and not L(own_equity=16000)["pause"])
check("保證金 250% → PAUSE（margin）；180% 另加提示；140% 兩個提示，唔 STOP", L(margin_level=250)["pause_kind"] == "margin" and "margin1" in L(margin_level=180)["alerts"] and "margin2" in L(margin_level=140)["alerts"] and not L(margin_level=140)["stop"])
check("冇本金：日蝕唔計", not L(principal_hkd=None, daily_pnl_hkd=-5000)["pause"])

print("=== 影子：開倉 → 止損 ===")
FB.decision = {"action": "OPEN_LONG", "stop_price": 3996.0, "target_price": 4020.0, "confidence": 0.8, "reason": "突破"}
st, d = hb(42, 4005)
check("開倉：紙上持倉、cmd_text 空", d["decision"]["final"] == "OPEN_LONG" and d["cmd_text"] == "" and json.loads(FAKE["xau/state.json"][0])["position"]["entry"] == 4005, d)
check("context 有 M15／M1／風控／舊電閘參考／階梯", FB.ctx["legacy_gate"]["status"] == "OPEN" and len(FB.ctx["bars_m1"]) >= 30 and FB.ctx["risk"]["lots"] == 0.01 and FB.ctx["position"] is None and FB.ctx["risk"]["ladder"]["level"] == "A")
FB.decision = {"action": "OPEN_LONG", "stop_price": 3996.0, "target_price": None, "confidence": 0.8, "reason": "再開"}
st, d = hb(43, 4006)
check("有倉時 AI 再開 → 擋", d["decision"]["final"] == "HOLD" and "已有倉位" in d["decision"]["rejected"], d)
check("有倉唔篩選、直接決策", FB.calls[-1] == "decide" and FB.calls[-2] == "decide", FB.calls[-3:])
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
st, d = hb(44, 3997, low=3995.0)
state = json.loads(FAKE["xau/state.json"][0])
check("低位穿止損 → 紙上平倉 @3996，虧損", state["position"] is None and state["trades"][-1]["exit"] == 3996.0 and state["trades"][-1]["pnl_usd"] < 0, state["trades"][-1])
check("成績：1 筆 0 勝", state["stats"]["n"] == 1 and state["stats"]["wins"] == 0)
check("決策紀錄有 paper_exit", json.loads(FAKE["xau/decisions/" + market.ny_date(NOW[0]) + ".jsonl"][0])[-1].get("paper_exit", {}).get("reason") == "止損")

print("=== 影子：開空 → 止賺；UPDATE_STOP；最長持倉 ===")
FB.decision = {"action": "OPEN_SHORT", "stop_price": 4010.0, "target_price": 3990.0, "confidence": 0.9, "reason": "跌穿"}
hb(45, 4000)
FB.decision = {"action": "UPDATE_STOP", "stop_price": 4003.0, "target_price": None, "confidence": 0.9, "reason": "收緊"}
st, d = hb(46, 3998)
state = json.loads(FAKE["xau/state.json"][0])
check("UPDATE_STOP：止損 4010→4003，止賺保留 3990", state["position"]["stop"] == 4003.0 and state["position"]["target"] == 3990.0, state["position"])
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
st, d = hb(47, 3992, low=3989.0)
state = json.loads(FAKE["xau/state.json"][0])
check("低位到止賺 → 紙上平倉 @3990 獲利", state["position"] is None and state["trades"][-1]["reason"] == "止賺" and state["trades"][-1]["pnl_usd"] > 0, state["trades"][-1])
FB.decision = {"action": "OPEN_LONG", "stop_price": 3980.0, "target_price": None, "confidence": 0.9, "reason": "買"}
hb(48, 3992)
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
for i in range(49, 171):                 # 122 根 HOLD，持倉超過 120 分鐘
    st, d = hb(i, 3993 + (i % 3) * 0.1)
state = json.loads(FAKE["xau/state.json"][0])
check("超過 XAU_MAX_HOLD_MIN → 強制平倉", state["position"] is None and "最長持倉" in state["trades"][-1]["reason"], state["trades"][-1]["reason"])
check("強制平倉喺第 120 分鐘", state["trades"][-1]["hold_min"] == 120, state["trades"][-1]["hold_min"])
check("今日開倉計數 3", paper.trades_today(state, market.ny_date(NOW[0])) == 3)
FB.decision = {"action": "OPEN_LONG", "stop_price": 3985.0, "target_price": None, "confidence": 0.9, "reason": "買"}
st, d = hb(171, 3994)
check("第 4 次開倉 → 擋（每日上限 3）", d["decision"]["final"] == "HOLD" and "上限" in d["decision"]["rejected"], d["decision"])
check("用量：有決策次數同費用", json.loads(FAKE["xau/state.json"][0])["usage_today"]["decide"] >= 5 and json.loads(FAKE["xau/state.json"][0])["usage_today"]["cost_usd"] > 0)

print("=== 模式開關（control.json）：使用者 PAUSE／STOP、日蝕自動 PAUSE→STOP→換日重開、保證金 PAUSE 回升自動解 ===")
TG = []
xau.notify.tg_send = lambda text: TG.append(text) or True
ctl0 = {"mode": "PAUSE", "reason": "使用者暫停", "set_by": "user", "principal_hkd": 20000, "equity_peak": 0, "alerts_sent": {}}
FAKE["xau/control.json"] = (json.dumps(ctl0), 1)
FB.decision = {"action": "OPEN_LONG", "stop_price": 3985.0, "target_price": None, "confidence": 0.9, "reason": "買"}
st, d = hb(172, 3995)
check("使用者 PAUSE → AI 開倉被擋", d["decision"]["final"] == "HOLD" and "PAUSE" in d["decision"]["rejected"], d["decision"])
FAKE["xau/control.json"] = (json.dumps({**ctl0, "mode": "STOP", "reason": "使用者停機"}), 2)
n_calls = len(FB.calls)
st, d = hb(173, 3995)
check("使用者 STOP → 唔問 Claude、程式唔會自己改", len(FB.calls) == n_calls and d["message"].startswith("STOP") and json.loads(FAKE["xau/control.json"][0])["mode"] == "STOP", d)
FAKE["xau/control.json"] = (json.dumps({**ctl0, "mode": "RUN", "reason": ""}), 3)
state = json.loads(FAKE["xau/state.json"][0]); state["trades_today"] = {"date": "", "count": 0}; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
hb(174, 3995)                                                  # 開倉（AI OPEN_LONG）
state = json.loads(FAKE["xau/state.json"][0]); check("開咗紙上倉", state["position"] is not None)
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
st, d = hb(175, 3990, low=3989.0)
state = json.loads(FAKE["xau/state.json"][0])
expected = round(paper.daily_pnl_usd(state, market.ny_day_start_ts(NOW[0]), 3990) * 7.8, 2)
check("階梯用今日自己嘅盈虧（港幣，含浮動）、唔用戶口淨值", abs(state["ladder"]["daily_pnl_hkd"] - expected) < 0.01 and state["ladder"]["level"] == "A", (state["ladder"], expected))
check("自己嘅權益 = 本金＋累計", abs(state["ladder"]["own_equity_hkd"] - (20000 + state["ladder"]["cum_pnl_usd"] * 7.8)) < 0.1)
# 戶口淨值大跌（手動單）唔影響
body = {"token": "tok", "action": "check_gate", "equity": 5000, "credit": 0, "balance": 5000, "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
        "m1_ohlc": {"time": T0 + 176 * 60, "open": 3990, "high": 3991, "low": 3989.5, "close": 3990.5, "is_new_bar": True},
        "m15_ohlc": {"time": T0 + (176 // 15) * 900, "open": 3990, "high": 3991, "low": 3989, "close": 3990}}
NOW[0] = T0 + 176 * 60 + 5
client.post("/", data=json.dumps(body), content_type="application/json")
state = json.loads(FAKE["xau/state.json"][0])
check("戶口淨值大跌（手動單）唔觸發（只計自己嘅單）", state["ladder"]["level"] == "A" and state["position"] is not None, state["ladder"])
# 自己嘅倉浮虧 −3.5%（700 港幣 ≈ 90 美元）→ PAUSE；再跌到 −6% → STOP 平倉；Telegram
state["position"]["entry"] = 3990.5 + 90; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
body["m1_ohlc"]["time"] = T0 + 177 * 60; body["m15_ohlc"]["time"] = T0 + (177 // 15) * 900; NOW[0] = T0 + 177 * 60 + 5
r = client.post("/", data=json.dumps(body), content_type="application/json"); d = r.get_json()
ctl = json.loads(FAKE["xau/control.json"][0]); state = json.loads(FAKE["xau/state.json"][0])
check("日蝕 −3% → PAUSE（ladder，auto_reset_day = 下一交易日）、倉照管、Telegram", ctl["mode"] == "PAUSE" and ctl["set_by"] == "ladder" and ctl["auto_reset_day"] > market.ny_date(NOW[0]) and state["position"] is not None and any("⏸" in t for t in TG), (ctl, TG[-1:] ))
state["position"]["entry"] = 3990.5 + 170; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
body["m1_ohlc"]["time"] = T0 + 178 * 60; NOW[0] = T0 + 178 * 60 + 5
r = client.post("/", data=json.dumps(body), content_type="application/json"); d = r.get_json()
ctl = json.loads(FAKE["xau/control.json"][0]); state = json.loads(FAKE["xau/state.json"][0])
check("日蝕 −6% → STOP：紙上平倉、auto_reset_day、紀錄 CLOSE、Telegram 🛑", ctl["mode"] == "STOP" and state["position"] is None and d["decision"]["final"] == "CLOSE" and "平倉停機" in state["trades"][-1]["reason"] and any("🛑" in t for t in TG), (ctl, d))
n_calls = len(FB.calls)
st, d = hb(179, 3990)
check("STOP 期間唔問 Claude", len(FB.calls) == n_calls and d["message"].startswith("STOP"), d)
# 換日：跳到下一個紐約交易日 → 自動返 RUN
reset_day = ctl["auto_reset_day"]
NOW_RESET = market.ny_day_start_ts(NOW[0]) + 86400 + 3600 * 2     # 下一交易日開始後 2 小時（紐約 19:00 ET，開市）
FAKE["xau/m1.json"] = (json.dumps([{"time": int(NOW_RESET) - (40 - k) * 60, "open": 3999.5, "high": 4000.5, "low": 3999.0, "close": 4000.0} for k in range(40)]), FAKE["xau/m1.json"][1] + 1)
body["m1_ohlc"]["time"] = int(NOW_RESET); body["m15_ohlc"]["time"] = int(NOW_RESET) - 900; NOW[0] = NOW_RESET + 5
r = client.post("/", data=json.dumps(body), content_type="application/json"); d = r.get_json()
ctl = json.loads(FAKE["xau/control.json"][0])
check("換日自動返 RUN（Telegram ▶），同一根照問 Claude", ctl["mode"] == "RUN" and ctl["set_by"] == "ladder" and market.ny_date(NOW[0]) >= reset_day and any("▶" in t for t in TG) and len(FB.calls) > n_calls, (ctl, d, market.ny_date(NOW[0]), reset_day))
# 保證金 PAUSE 回升自動解
body["margin_level"] = 250; body["m1_ohlc"]["time"] = int(NOW_RESET) + 60; NOW[0] = NOW_RESET + 65
client.post("/", data=json.dumps(body), content_type="application/json")
ctl = json.loads(FAKE["xau/control.json"][0])
check("保證金 250% → PAUSE（margin，冇 auto_reset_day）", ctl["mode"] == "PAUSE" and ctl["auto_reset_day"] is None and "保證金" in ctl["reason"], ctl)
body["margin_level"] = 180; body["m1_ohlc"]["time"] = int(NOW_RESET) + 120; NOW[0] = NOW_RESET + 125; n_tg = len(TG)
client.post("/", data=json.dumps(body), content_type="application/json")
check("保證金 180% → 只多一個提示（每日一次）", any("180%" in t for t in TG[n_tg:]) and json.loads(FAKE["xau/control.json"][0])["mode"] == "PAUSE")
body["m1_ohlc"]["time"] = int(NOW_RESET) + 180; NOW[0] = NOW_RESET + 185; n_tg = len(TG)
client.post("/", data=json.dumps(body), content_type="application/json")
check("同一日同一提示唔重發", not any("180%" in t for t in TG[n_tg:]))
body["margin_level"] = 500; body["m1_ohlc"]["time"] = int(NOW_RESET) + 240; NOW[0] = NOW_RESET + 245
client.post("/", data=json.dumps(body), content_type="application/json")
check("保證金回升 → 自動返 RUN", json.loads(FAKE["xau/control.json"][0])["mode"] == "RUN")
del body["margin_level"]
# 累計虧損 ≥ 25%（當日事件）：先令 trades 累計大蝕
state = json.loads(FAKE["xau/state.json"][0])
state["trades"].append({"side": 1, "lots": 0.01, "entry": 5000.0, "exit": 4200.0, "opened_ts": NOW[0] - 3 * 86400 - 7200, "closed_ts": NOW[0] - 3 * 86400, "reason": "測試大蝕", "pnl_usd": -800.3, "hold_min": 60})
FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
body["m1_ohlc"]["time"] = int(NOW_RESET) + 300; NOW[0] = NOW_RESET + 305; n_tg = len(TG)
client.post("/", data=json.dumps(body), content_type="application/json")
ctl = json.loads(FAKE["xau/control.json"][0])
check("累計 ≥25% → PAUSE（ladder，換日重開）＋Telegram", ctl["mode"] == "PAUSE" and "累計虧損" in ctl["reason"] and ctl["auto_reset_day"] and any("累計虧損" in t for t in TG[n_tg:]), ctl)
# 換日：仍然 ≥25%，但係當日事件 → 自動 RUN 之後唔再 PAUSE
NOW2 = market.ny_day_start_ts(NOW[0]) + 86400 + 3600 * 2
FAKE["xau/m1.json"] = (json.dumps([{"time": int(NOW2) - (40 - k) * 60, "open": 3999.5, "high": 4000.5, "low": 3999.0, "close": 4000.0} for k in range(40)]), FAKE["xau/m1.json"][1] + 1)
body["m1_ohlc"]["time"] = int(NOW2); body["m15_ohlc"]["time"] = int(NOW2) - 900; NOW[0] = NOW2 + 5
client.post("/", data=json.dumps(body), content_type="application/json")
body["m1_ohlc"]["time"] = int(NOW2) + 60; NOW[0] = NOW2 + 65
client.post("/", data=json.dumps(body), content_type="application/json")
ctl = json.loads(FAKE["xau/control.json"][0])
check("換日後仍 ≥25% → 照 RUN（揀 A：當日事件，唔係持續狀態）", ctl["mode"] == "RUN" and ctl["cum_loss_above"], ctl)
state = json.loads(FAKE["xau/state.json"][0]); state["trades"] = [t for t in state["trades"] if t.get("reason") != "測試大蝕"]
FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
NOW_RESET = NOW2
FAKE["xau/control.json"] = (json.dumps({"mode": "RUN", "reason": "", "set_by": "user", "principal_hkd": None, "equity_peak": 0, "alerts_sent": {}}), 99)

print("=== 休市 ===")
NOW[0] = 1792857600.0 + 5        # 2026-10-24 週六 12:00 ET：休市
r = client.post("/", data=json.dumps({"token": "tok", "equity": 1, "m1_ohlc": {"time": int(NOW_RESET) + 100000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "is_new_bar": True}}), content_type="application/json")
check("休市 → 唔問", r.get_json()["message"] == "休市", r.get_json())

print("=== 實倉模式：指令佇列 ===")
config.EXECUTE = True
FB.calls.clear()
from datetime import datetime, timezone
T0 = int(datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc).timestamp()) - 400 * 60   # 週一 10:00 ET 開市；大過之前所有 bar
FAKE["xau/m1.json"] = (json.dumps([{"time": T0 + (360 + k) * 60, "open": 3999.5, "high": 4000.5, "low": 3999.0, "close": 4000.0} for k in range(40)]), FAKE["xau/m1.json"][1] + 1)
FAKE["xau/m15.json"] = (json.dumps([{"time": T0 + 400 * 60 - 900 * (30 - k), "open": 3999.0, "high": 4001.0, "low": 3998.0, "close": 4000.0} for k in range(30)]), FAKE["xau/m15.json"][1] + 1)
state = json.loads(FAKE["xau/state.json"][0]); state["trades_today"] = {"date": "", "count": 0}; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
FB.decision = {"action": "OPEN_LONG", "stop_price": 3990.0, "target_price": 4015.0, "confidence": 0.9, "reason": "買"}
st, d = hb(400, 4000)
check("實倉：cmd_text 有 open 指令、紙上唔開倉", d["cmd_text"].startswith("open|BUY|0.01|sl=3990.00|tp=4015.00|magic=921|id=") and json.loads(FAKE["xau/state.json"][0])["position"] is None, d)
cid = d["cmd_text"].split("id=")[1]
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
st, d2 = hb(401, 4001)
check("未回報 → 下一個心跳照帶同一指令", d2["cmd_text"] == d["cmd_text"])
r = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 123}), content_type="application/json")
check("cmd_ack → acked", r.get_json()["status"] == "acked")
st, d3 = hb(402, 4002)
check("回報後 cmd_text 清空", d3["cmd_text"] == "", d3)
r = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True}), content_type="application/json")
check("重複回報 → unknown", r.get_json()["status"] == "unknown")
config.EXECUTE = False

print("=== 頁面 ===")
r = client.get("/"); html = r.get_data(as_text=True)
check("頁面有陣名、模擬倉、成交紀錄、硬性風控、模式", "天覆陣" in html and "模擬倉" in html and "成交紀錄" in html and "XAU_MAX_SL_USD" in html and "模式同風控" in html)
j = client.get("/?format=json").get_json()
check("JSON：stats、decisions、risk、階梯、模式", j["ladder"]["level"] in "ABD" and j["control"]["mode"] == "RUN" and j["stats"]["n"] >= 3 and j["decisions"] and j["risk"]["XAU_LOTS"] == 0.01, j["stats"])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
