"""[R291] 🌌 天覆陣（xau/）：心跳權杖、K 線累積去重、電閘 LOCK 唔問 AI、篩選、硬性規則、紙上止損／止賺／最長持倉、
實倉指令佇列同回報、頁面。Claude 用假 brain，GCS 用假 bucket。"""
import json, os, sys, time, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", GATE_MODEL="claude-haiku-5-5",
                  XAU_MAX_SL_USD="30", XAU_MIN_SL_USD="2", XAU_MAX_HOLD_MIN="120", XAU_MAX_TRADES_PER_DAY="3",
                  ANTHROPIC_API_KEY="x")
sys.path.insert(0, "/home/user/20260918/xau")

try:
    import anthropic                             # noqa: F401
except ImportError:                              # 冇裝 SDK 都要跑到測試（Claude 用假 brain）
    _an = types.ModuleType("anthropic")
    class _E(Exception):
        pass
    _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = _E; sys.modules["anthropic"] = _an
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

def set_gate(open_):   # R253 後舊電閘已刪：保留呼叫點，唔做嘢
    pass

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
check("第 30 根起：照問", FB.calls and d["decision"] is not None, (d, FB.calls))
FB.calls.clear()
st, d = hb(39, 4000 + 39 * 0.1)
check("同一根重送 → duplicate", d.get("message") == "duplicate M1 bar", d)
st, d = hb(39, 4000, new=False)
check("is_new_bar=false 只存快照", d.get("message") is None and d["status"] == "monitoring", d)
m1 = json.loads(FAKE["xau/m1.json"][0]); check("M1 歷史 40 根、M15 ≥ 32 根", len(m1) == 40 and len(json.loads(FAKE["xau/m15.json"][0])) >= 32, len(json.loads(FAKE["xau/m15.json"][0])))

FB.screen_look = False
st, d = hb(40, 4004)
check("空倉 → 先篩選", FB.calls == ["screen"] and "篩選" in d["message"], (FB.calls, d))
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
check("context 有 M15／M1／風控／階梯（冇舊電閘）", "legacy_gate" not in FB.ctx and len(FB.ctx["bars_m1_older"]) + len(FB.ctx["bars_m1"]) >= 30 and FB.ctx["risk"]["lots"] == 0.01 and FB.ctx["position"] is None and FB.ctx["risk"]["ladder"]["level"] == "A")
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
FAKE["xau/control.json"] = (json.dumps({**ctl0, "mode": "RUN", "reason": "", "equity_peak": 99999.0}), 3)
state = json.loads(FAKE["xau/state.json"][0]); state["trades_today"] = {"date": "", "count": 0}; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
hb(174, 3995)
_c = json.loads(FAKE["xau/control.json"][0])
check("本金改變 → equity_peak 重設為當時權益（唔會用舊高水位亂發回撤警報）", _c["principal_seen"] == 20000 and _c["equity_peak"] < 99999.0 and not any("回撤" in t for t in TG), (_c["equity_peak"], TG[-2:]))                                                  # 開倉（AI OPEN_LONG）
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

print("=== TianfuExecutor v0.2 直接心跳格式 ===")
ea = {"action": "heartbeat", "token": "tok", "ea": "TianfuExecutor/0.20", "symbol": "XAUUSD", "currency": "HKD",
      "balance": 27165.70, "equity": 29172.53, "credit": 2006.83, "margin_level": 0.0, "floating": 0.0, "daily_pnl": 0.0,
      "buy_lots": 0.0, "sell_lots": 0.0, "net_lots": 0.0, "magic": 921, "dry_run": True, "positions": [],
      "m1_ohlc": {"symbol": "XAUUSD", "time": int(NOW_RESET) + 300, "open": 3990.0, "high": 3991.0, "low": 3989.5, "close": 3990.5, "volume": 12, "is_new_bar": True},
      "m15_ohlc": {"time": int(NOW_RESET) - 900, "open": 3990.0, "high": 3991.0, "low": 3989.0, "close": 3990.0}}
NOW[0] = NOW_RESET + 305
r = client.post("/", data=json.dumps(ea), content_type="application/json"); d = r.get_json()
acc = json.loads(FAKE["xau/account.json"][0])
check("EA 直接心跳：收到、存快照（margin_level 0 當冇）、M1 入歷史", r.status_code == 200 and d["status"] == "monitoring" and acc["equity"] == 29172.53 and acc["margin_level"] == 0.0 and json.loads(FAKE["xau/m1.json"][0])[-1]["time"] == int(NOW_RESET) + 300, (d, acc))
r2 = client.post("/", data=json.dumps({**ea, "m1_ohlc": {"time": int(NOW_RESET) + 300, "is_new_bar": False}}), content_type="application/json")
check("is_new_bar=false 心跳只存快照", r2.get_json().get("decision") is None)

print("=== API key 到期提示 ===")
check("key_expiry 解析", market.key_expiry(0, "2026-12-31 14:00")[1] > 0 and market.key_expiry(0, "")[0] is None)
config.KEY_EXPIRES_UTC = market.fmt_utc(NOW[0] + 5 * 86400, "%Y-%m-%d %H:%M"); n_tg = len(TG)
body2 = {"token": "tok", "action": "check_gate", "equity": 1, "credit": 0, "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
         "m1_ohlc": {"time": int(NOW_RESET) + 400, "open": 3990, "high": 3991, "low": 3989.5, "close": 3990.5, "is_new_bar": True},
         "m15_ohlc": {"time": int(NOW_RESET) - 900, "open": 3990, "high": 3991, "low": 3989, "close": 3990}}
NOW[0] = NOW_RESET + 405
client.post("/", data=json.dumps(body2), content_type="application/json")
check("到期前 5 日 → Telegram 提示一次、頁面警告", any("ANTHROPIC_API_KEY" in t for t in TG[n_tg:]) and "ANTHROPIC_API_KEY" in client.get("/").get_data(as_text=True) and client.get("/?format=json").get_json()["api_key"]["warn"])
body2["m1_ohlc"]["time"] = int(NOW_RESET) + 460; NOW[0] = NOW_RESET + 465; n_tg = len(TG)
client.post("/", data=json.dumps(body2), content_type="application/json")
check("同日唔重發", not any("ANTHROPIC_API_KEY" in t for t in TG[n_tg:]))
config.KEY_EXPIRES_UTC = "2026-12-31 14:00"

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

print("=== 階段 B：XAU_ACCOUNT 過濾、實倉持倉由 EA、最長持倉／STOP 排 close、test_cmd ===")
config.EXECUTE = True; config.ACCOUNT = "70001"; config.TEST_CMDS = True
FB.calls.clear(); FB.decision = {"action": "OPEN_LONG", "stop_price": 3990.0, "target_price": 4015.0, "confidence": 0.9, "reason": "買"}
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; state["trades_today"] = {"date": "", "count": 0}; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
T1 = T0 + 500 * 60
FAKE["xau/m1.json"] = (json.dumps([{"time": T1 - (40 - k) * 60, "open": 3999.5, "high": 4000.5, "low": 3999.0, "close": 4000.0} for k in range(40)]), FAKE["xau/m1.json"][1] + 1)
FAKE["xau/m15.json"] = (json.dumps([{"time": T1 - 900 * (30 - k), "open": 3999.0, "high": 4001.0, "low": 3998.0, "close": 4000.0} for k in range(30)]), FAKE["xau/m15.json"][1] + 1)
def live_hb(i, close, positions, account="70001", **extra):
    t = T1 + i * 60
    body = {"action": "heartbeat", "token": "tok", "account": account, "server": "Demo", "symbol": "XAUUSD", "currency": "HKD",
            "balance": 10000, "equity": 10000, "credit": 0, "margin_level": 0, "floating": extra.get("floating", 0.0), "daily_pnl": extra.get("daily_pnl", 0.0),
            "realized_total": extra.get("realized_total", 0.0), "trade_allowed": extra.get("trade_allowed"), "buy_lots": 0.01 if positions else 0, "sell_lots": 0, "net_lots": 0.01 if positions else 0, "magic": 921,
            "dry_run": False, "positions": positions,
            "m1_ohlc": {"time": t, "open": close - 0.5, "high": close + 0.3, "low": close - 0.8, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": T1 - 900, "open": 3999.0, "high": 4001.0, "low": 3998.0, "close": 4000.0}}
    NOW[0] = t + 5
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()
st, d = live_hb(0, 4000, [], account="99999")
check("非 XAU_ACCOUNT 嘅心跳 → ignored，唔入 K 線", d["status"] == "ignored" and d["cmd_text"] == "" and json.loads(FAKE["xau/m1.json"][0])[-1]["time"] == T1 - 60, d)
st, d = live_hb(0, 4000, [])
check("demo 心跳：Claude OPEN → 排 open 指令", d["cmd_text"].startswith("open|BUY|0.01|sl=3990.00|tp=4015.00|magic=921|id="), d)
cid = d["cmd_text"].split("id=")[1]
POS = [{"ticket": 555, "side": "BUY", "lots": 0.01, "entry": 4000.2, "sl": 3990.0, "tp": 4015.0, "open_time": T1 + 10}]
client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 555}), content_type="application/json")
st, d = live_hb(1, 4001, POS)
check("EA 回報持倉 → 服務持倉以 EA 為準；AI 再 OPEN 被擋（已有倉位）", d["cmd_text"] == "" and d["decision"]["final"] == "HOLD" and "已有倉位" in d["decision"]["rejected"] and json.loads(FAKE["xau/state.json"][0])["position"]["ticket"] == 555, d)
check("context 持倉來自 EA", FB.ctx["position"]["entry"] == 4000.2 and FB.ctx["position"]["stop"] == 3990.0)
FB.decision = {"action": "UPDATE_STOP", "stop_price": 3995.0, "target_price": None, "confidence": 0.9, "reason": "收緊"}
st, d = live_hb(2, 4002, POS)
check("AI UPDATE_STOP → modify 指令（止賺保留 4015）", d["cmd_text"].startswith("modify|all|sl=3995.00|tp=4015.00"), d)
mid = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": mid, "ok": True}), content_type="application/json")
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
st, d = live_hb(3, 4003, POS, daily_pnl=-50.0, floating=20.0)
state = json.loads(FAKE["xau/state.json"][0])
check("真倉階梯用 EA 數字：今日 = daily_pnl＋floating = −30 HKD", abs(state["ladder"]["daily_pnl_hkd"] - (-30.0)) < 0.01, state["ladder"])
config.MAX_HOLD_MIN = 1
st, d = live_hb(5, 4003, POS)
check("最長持倉到 → 排 close（一次）", d["cmd_text"].startswith("close|all|magic=921"), d)
st, d = live_hb(6, 4003, POS)
check("未回報前唔重複排 close", d["cmd_text"].count("close|") == 1, d)
config.MAX_HOLD_MIN = 120
closeid = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": closeid, "ok": True}), content_type="application/json")
st, d = live_hb(7, 4003, [])
check("EA 回報平倉後：持倉 None、冇指令", d["cmd_text"] == "" and json.loads(FAKE["xau/state.json"][0])["position"] is None, d)
# 使用者 STOP 而有倉 → 排 close
FAKE["xau/control.json"] = (json.dumps({"mode": "STOP", "reason": "使用者停機", "set_by": "user", "principal_hkd": None, "equity_peak": 0, "alerts_sent": {}}), 50)
st, d = live_hb(8, 4003, POS)
check("使用者 STOP 而 EA 有倉 → 排 close", d["cmd_text"].startswith("close|all") and "STOP" in d["message"], d)
FAKE["xau/control.json"] = (json.dumps({"mode": "RUN", "reason": "", "set_by": "user", "principal_hkd": None, "equity_peak": 0, "alerts_sent": {}}), 51)
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
# test_cmd
r = client.post("/", data=json.dumps({"token": "tok", "action": "test_cmd", "op": "open", "side": "SELL", "sl": 4010.5, "tp": 3990}), content_type="application/json")
check("test_cmd open → queued", r.get_json()["status"] == "queued" and r.get_json()["text"].startswith("open|SELL|0.01|sl=4010.50|tp=3990.00"), r.get_json())
r = client.post("/", data=json.dumps({"token": "tok", "action": "test_cmd", "op": "open", "no_sl": True}), content_type="application/json")
check("test_cmd no_sl → sl=0（測 EA 拒絕）", "sl=0|" in r.get_json()["text"], r.get_json())
# GCS 測試指令檔（唔使權杖）
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t0", "op": "open", "side": "BUY", "sl": 3990, "tp": 4015}), 1)
st, d = live_hb(9, 4003, [])
tf = json.loads(FAKE["xau/test_cmd.json"][0])
check("test_cmd.json 冇 ts → 唔排，result 記錯誤", "open|" not in d["cmd_text"] and tf["result"]["status"] == "error" and "ts" in tf["result"]["message"], tf)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t0b", "op": "open", "side": "BUY", "sl": 3990, "tp": 4015, "ts": T1 + 9 * 60 - 700}), 2)
st, d = live_hb(9, 4003, [])
tf = json.loads(FAKE["xau/test_cmd.json"][0])
check("test_cmd.json ts 超過 10 分鐘 → 唔排（部署後殘留檔唔會落單）", "open|" not in d["cmd_text"] and tf["result"]["status"] == "error", tf)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t1", "op": "open", "side": "BUY", "sl": 3990, "tp": 4015, "ts": T1 + 9 * 60}), 3)
st, d = live_hb(9, 4003, [])
check("GCS test_cmd.json → 心跳排 open 指令", "open|BUY|0.01|sl=3990.00|tp=4015.00|magic=921|id=" in d["cmd_text"], d)
tf = json.loads(FAKE["xau/test_cmd.json"][0])
check("test_cmd.json 寫回 consumed＋result", bool(tf.get("consumed")) and tf["result"]["status"] == "queued" and tf["id"] == "t1", tf)
st, d = live_hb(10, 4003, [])
check("已 consumed 嘅檔唔會再排", d["cmd_text"].count("open|") == 1, d)
# 第 5 項去重：resend=true → ack 後 180 秒內心跳仍帶同一指令（EA 靠 Seen 檔只執行一次）
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t5", "op": "open", "side": "BUY", "sl": 3990, "tp": 4015, "ts": T1 + 10 * 60 + 30, "resend": True}), 4)
st, d = live_hb(10, 4003, [])
rid = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": rid, "ok": True, "ticket": 777}), content_type="application/json")
st, d = live_hb(11, 4003, [])
check("resend：ack 後下一個心跳仍帶同一 id", d["cmd_text"].count("id=" + rid) == 1, d)
st, d2 = live_hb(15, 4003, [])
check("resend：180 秒後唔再送", "id=" + rid not in d2["cmd_text"], d2)
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t2", "op": "open", "side": "SELL", "ts": T1 + 11 * 60}), 6)
st, d = live_hb(11, 4003, [])
tf = json.loads(FAKE["xau/test_cmd.json"][0])
check("test_cmd.json 冇 sl → 唔排，result 記錯誤", d["cmd_text"].count("open|") == 0 and tf["result"]["status"] == "error", tf)
config.TEST_CMDS = False
r = client.post("/", data=json.dumps({"token": "tok", "action": "test_cmd", "op": "close"}), content_type="application/json")
check("XAU_TEST_CMDS=0 → 403", r.status_code == 403)
FAKE["xau/test_cmd.json"] = (json.dumps({"id": "t3", "op": "close", "ts": T1 + 12 * 60}), 7)
st, d = live_hb(12, 4003, [])
check("XAU_TEST_CMDS=0 → 唔讀 test_cmd.json", "close|" not in d["cmd_text"] and "consumed" not in FAKE["xau/test_cmd.json"][0], d)
# 伺服器時間 → UTC（EA open_time 係 MT5 伺服器時間，UltimaMarkets ≈ UTC+3）
check("伺服器時差：由剛收盤 M1 時間估（取整 15 分鐘）", xau.server_offset({"m1_ohlc": {"time": 1_000_000 + 10800 - 70}}, 1_000_000) == 10800)
check("伺服器時差：EA 有送 server_time 就直接用", xau.server_offset({"server_time": 1_000_000 + 7200 + 3}, 1_000_000) == 7200)
check("伺服器時差：冇資料 = 0", xau.server_offset({}, 1_000_000) == 0)
_p = xau.own_positions({"positions": [{"side": "BUY", "lots": 0.01, "entry": 4000, "sl": 0, "tp": 0, "open_time": 1_000_000 + 10800}]}, 10800)
check("open_time 換算成 UTC（最長持倉先會準）", _p[0]["opened_ts"] == 1_000_000 and _p[0]["stop"] is None, _p)
j = client.get("/?format=json").get_json()
check("JSON 有 account_id／xau_account／live_positions", j["account_id"] == "70001" and j["xau_account"] == "70001" and isinstance(j["live_positions"], list))
st, d = live_hb(13, 4003, [], trade_allowed={"terminal": True, "ea": False, "account": True})
j = client.get("/?format=json").get_json()
check("JSON 有 trade_allowed／server_offset", j["trade_allowed"] == {"terminal": True, "ea": False, "account": True} and j["server_offset"] == 0, j.get("trade_allowed"))
html = client.get("/").get_data(as_text=True)
check("頁面顯示自動交易被擋（EA 屬性）", "MT5 自動交易被擋" in html and "允許算法交易" in html)
config.EXECUTE = False; config.ACCOUNT = ""
state = json.loads(FAKE["xau/state.json"][0]); state["pending_cmds"] = []; state["position"] = None; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)

print("=== 頁面 ===")
r = client.get("/"); html = r.get_data(as_text=True)
check("頁面頂有導覽列：12 個舊服務頁連結（絕對網址、同一次序）＋本頁高亮", html.count("class='nav-link' href='https://zhuge-risk-manager-1056099871997.europe-west1.run.app/?view=") == 12
      and html.index("?view=welcome") < html.index("?view=futu_range") < html.index("?view=longfei") < html.index("?view=fund_report")
      and "<span class='nav-link nav-current'>🌌 天覆陣 XAUUSD</span>" in html and "↗" not in html.split("</nav>")[0], html[:1500].split("<nav")[-1][:400])
check("使用者 10-21：標題冇 CFD（MT5）、冇 AI 用量卡、決策表只有延遲、風控表冇 CLAUDE_PROVIDER／XAU_MAGIC／XAU_EXECUTE、冇模型字眼",
      "<title>🌌 天覆陣・XAUUSD 自動交易</title>" in html and "天覆陣・XAUUSD 自動交易</h1>" in html and "CFD（MT5）" not in html
      and "AI 今日用量" not in html and "延遲／費用" not in html and "<th>延遲</th>" in html and "cost_usd" not in html
      and "CLAUDE_PROVIDER" not in html and "<td>XAU_MAGIC</td>" not in html and "<td>XAU_EXECUTE</td>" not in html and "effort" not in html and "claude-opus" not in html
      and "<td>XAU_MAX_SL_USD</td>" in html)
check("JSON 仍然有費用同模型（只係網頁唔顯示）", j["usage_today"].get("cost_usd") is not None and j.get("model") and j["risk"].get("CLAUDE_PROVIDER"))
check("頁面有陣名、模擬倉、成交紀錄、硬性風控、模式", "天覆陣" in html and "模擬倉" in html and "成交紀錄" in html and "XAU_MAX_SL_USD" in html and "模式同風控" in html)
j = client.get("/?format=json").get_json()
check("JSON：stats、decisions、risk、階梯、模式", j["ladder"]["level"] in "ABD" and j["control"]["mode"] == "RUN" and j["stats"]["n"] >= 3 and j["decisions"] and j["risk"]["XAU_LOTS"] == 0.01, j["stats"])

print("=== M15 由 M1 砌＋EA 回填（唔使等 5 小時）===")
check("m15_from_m1：只取完整 15 根", len(market.m15_from_m1([{"time": 900 * 100 + 60 * k, "open": 1 + k, "high": 10 + k, "low": 0.5, "close": 2 + k} for k in range(20)])) == 1)
_g = market.m15_from_m1([{"time": 900 * 100 + 60 * k, "open": 1 + k, "high": 10 + k, "low": 0.5 - k * 0.01, "close": 2 + k} for k in range(15)])[0]
check("m15_from_m1：OHLC 正確", _g["open"] == 1 and _g["high"] == 24 and abs(_g["low"] - 0.36) < 1e-9 and _g["close"] == 16, _g)
check("merge_bars：去重、後者覆蓋、排序、截 max_len", [b["time"] for b in market.merge_bars([{"time": 2, "open": 1, "high": 1, "low": 1, "close": 1}, {"time": 1, "open": 0, "high": 0, "low": 0, "close": 0}], [{"time": 2, "open": 9, "high": 9, "low": 9, "close": 9}, {"time": 3, "open": 1, "high": 1, "low": 1, "close": 1}], 2)] == [2, 3])
check("parse_hist：陣列格式＋壞行跳過", len(market.parse_hist([[100, 1, 2, 0.5, 1.5], [0, 1, 2, 0.5, 1.5], "x", [101, 1, 2, 0.5, 1.5]])) == 2)
TS = T0 + 910 * 60                                              # 對齊 15 分鐘邊界
FAKE["xau/m1.json"] = (json.dumps([{"time": TS + k * 60, "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.5} for k in range(330)]), FAKE["xau/m1.json"][1] + 1)
FAKE["xau/m15.json"] = (json.dumps([{"time": TS - 900 * (3 - k), "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.0} for k in range(3)]), FAKE["xau/m15.json"][1] + 1)
st, d = hb(1240, 4000.5)
_m15 = json.loads(FAKE["xau/m15.json"][0])
check("M15 唔夠 → 由 330 根 M1 砌到 ≥ 20 根並寫入；need_history=false", len(_m15) >= 20 and d.get("need_history") is False, (len(_m15), d.get("need_history"), d.get("message")))
check("砌出嚟嘅 M15 時間對齊 15 分鐘（≥22 根）、EA 送嘅保留", sum(1 for b in _m15 if b["time"] % 900 == 0) >= 22 and _m15[0]["time"] == TS - 2700, _m15[:2])
FAKE["xau/m15.json"] = (json.dumps([]), FAKE["xau/m15.json"][1] + 1)
FAKE["xau/m1.json"] = (json.dumps([{"time": TS + 330 * 60, "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.5}]), FAKE["xau/m1.json"][1] + 1)
st, d0 = hb(1241, 4000.5)
check("歷史空 → need_history=true", d0.get("need_history") is True, d0)
t = T0 + 1242 * 60
body = {"action": "heartbeat", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "credit": 0, "floating": 0, "daily_pnl": 0,
        "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
        "m1_ohlc": {"time": t, "open": 4000, "high": 4001, "low": 3999, "close": 4000.5, "is_new_bar": True},
        "m15_ohlc": {"time": T0 + (1242 // 15) * 900, "open": 4000, "high": 4001, "low": 3999, "close": 4000.5},
        "m1_hist": [[TS + k * 60, 4000, 4001, 3999, 4000.5] for k in range(300)],
        "m15_hist": [[TS - 900 * (60 - k), 4000, 4001, 3999, 4000.2] for k in range(60)]}
NOW[0] = t + 5
r = client.post("/", data=json.dumps(body), content_type="application/json"); d1 = r.get_json()
_m1, _m15 = json.loads(FAKE["xau/m1.json"][0]), json.loads(FAKE["xau/m15.json"][0])
check("EA 回填 m1_hist／m15_hist → 合併入歷史，need_history=false", len(_m1) >= 300 and len(_m15) >= 60 and d1.get("need_history") is False and _m15[0]["time"] == TS - 900 * 60, (len(_m1), len(_m15), d1.get("need_history")))
check("回填後 M1 歷史仍然排序、冇重複", [b["time"] for b in _m1] == sorted(set(b["time"] for b in _m1)))

print("=== Prompt caching（使用者 10-21）：整點切、三段快取、TTL ===")
import brain as _brain
_h0 = (int(FB.ctx["bars_m1"][0][0]) // 3600) * 3600 if FB.ctx.get("bars_m1") else None
check("build_context：整點前 M1／M15 入快取段，本小時嘅係即時段", _h0 is not None and all(b[0] >= _h0 for b in FB.ctx["bars_m1"]) and all(b[0] < _h0 for b in FB.ctx["bars_m1_older"])
      and all(b[0] < _h0 for b in FB.ctx["bars_m15_older"]) and all(b[0] >= _h0 for b in FB.ctx["bars_m15_recent"]), (_h0, FB.ctx["bars_m1"][:1], FB.ctx["bars_m1_older"][-1:]))
_uc = _brain._user_content(FB.ctx, "Call the `decide` tool.")
check("_user_content：三段，首兩段 cache_control ttl=1h，第三段冇", len(_uc) == 3 and _uc[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and _uc[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "cache_control" not in _uc[2])
check("快取段只含穩定 key；即時段有 account／position／risk", "bars_m15_older" in _uc[0]["text"] and "bars_m1_older" in _uc[1]["text"] and "bars_m1\"" in _uc[2]["text"] and "account" in _uc[2]["text"] and "bars_m1_older" not in _uc[2]["text"])
_us = _brain._user_content(FB.ctx, "Screen this bar.", _brain.CACHE_TTL_SCREEN)
check("篩選用 5m TTL", _us[0]["cache_control"]["ttl"] == "5m")
check("cost_usd：1h TTL 寫 2×、5m TTL 寫 1.25×", abs(_brain.cost_usd({"in": 0, "out": 0, "cache_read": 0, "cache_write": 1000, "cache_ttl": "1h", "model": "claude-opus-5-5"}) - 0.008) < 1e-9
      and abs(_brain.cost_usd({"in": 0, "out": 0, "cache_read": 0, "cache_write": 1000, "cache_ttl": "5m", "model": "claude-opus-5-5"}) - 0.005) < 1e-9)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
