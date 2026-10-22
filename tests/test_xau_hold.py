"""慳成本 H（使用者 10-23 揀「穩陣＋H」）：有倉時規則止損（教學第 1／4 條）。純函數＋shadow 唔改行為＋on 模式只喺特定分鐘問 Opus。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", ANTHROPIC_API_KEY="x", XAU_EXECUTE="0", XAU_HOLD_RULES="shadow",
                  XAU_REUSE_HOLD="off", GATE_MODEL="", XAU_MAX_HOLD_MIN="0")
sys.path.insert(0, "/home/user/20260918/xau")
try:
    import anthropic                             # noqa: F401
except ImportError:
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
import main as xau, config, hold_rules, market, paper   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

# ---------------------------------------------------------------- 純函數
print("=== suggest：教學第 1／4 條")
ATR = 2.0
def bars(prices):
    return [{"time": 1000 + i * 60, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p} for i, p in enumerate(prices)]
rise = bars([4000.0 + 0.01 * i for i in range(130)])      # 嚴格上升：冇擺動低（swing 候選 None）
flat = rise
pos = {"side": 1, "entry": 4000.0, "stop": 3994.0, "target": 4020.0}
s = hold_rules.suggest(pos, flat, ATR, 4005.0, 3994.0)
check("浮盈 5 < 1R（6）→ 唔郁、stage pre_1r", s["sl"] is None and s["stage"] == "pre_1r" and s["r_mult"] == 0.83, s)
s = hold_rules.suggest(pos, flat, ATR, 4006.0, 3994.0)
check("浮盈 = 1R、價 4006：候選 ATR 4004 vs 保本 4000 → 取 4004（已 ≥ 保本，且離現價 ≥0.5×ATR）", s["sl"] == 4004.0 and s["reason"] == "跟 1×ATR", s)
s = hold_rules.suggest(pos, flat, ATR, 4006.0, 3994.0)
# 浮盈 1R 但 ATR 大：trail = 4006 − 8 = 3998 < 保本 4000 → 保本
s = hold_rules.suggest(pos, flat, 8.0, 4006.0, 3994.0)
check("ATR 8 → 1×ATR 候選 3998 低過保本 → 保本 4000（教學第 1 條）", s["sl"] == 4000.0 and s["reason"] == "保本", s)
# 擺動點：M1 有個低位 4003 喺 (price − 0.5ATR) 之外，且比 ATR 候選遠 → 取較遠（教學第 4 條）
sw = bars([4000.0] * 100 + [4006.0] * 8 + [4003.0] + [4006.0] * 8 + [4007.0] * 10)
s = hold_rules.suggest(pos, sw, ATR, 4007.0, 3994.0)
check("擺動低 4002.8（外 0.1ATR＝4002.6）vs 1×ATR 4005 → 取較遠 4002.6", s["sl"] == 4002.6 and s["reason"] == "跟擺動點" and s["trail_swing"] == 4002.6, s)
pos2 = {**pos, "stop": 4004.0}
s = hold_rules.suggest(pos2, flat, ATR, 4006.0, 3994.0)
check("候選 4004 = 現止損 → 唔郁（只准收緊）", s["sl"] is None and "只准收緊" in s["reason"], s)
pos3 = {**pos, "stop": 4005.0}
s = hold_rules.suggest(pos3, flat, ATR, 4006.0, 3994.0)
check("候選 4004 鬆過現止損 4005 → 唔郁（唔可以移遠）", s["sl"] is None and "只准收緊" in s["reason"], s)
s = hold_rules.suggest(pos, flat, 2.0, 4012.0, 3994.0)
check("價 4012：1×ATR 候選 4010，離現價 2 = 1×ATR ≥ 0.5×ATR → 4010", s["sl"] == 4010.0, s)
s = hold_rules.suggest(pos, flat, 2.0, 4005.5, 3994.0)
check("浮盈 5.5 < 6 → 未到 1R 唔郁", s["sl"] is None and s["stage"] == "pre_1r")
pos4 = {**pos, "stop": 4003.9}
s = hold_rules.suggest(pos4, flat, ATR, 4006.0, 3994.0)
check("收緊 0.1 < 0.1×ATR（0.2）→ 唔郁（免每分鐘 modify）", s["sl"] is None and "幅度" in s["reason"], s)
s = hold_rules.suggest(pos, flat, None, 4010.0, 3994.0)
check("冇 ATR → unknown 交 Claude", s["sl"] is None and s["stage"] == "unknown")
s = hold_rules.suggest(pos, flat, ATR, 4010.0, None)
check("冇初始止損 → unknown 交 Claude", s["sl"] is None and s["stage"] == "unknown")
# 空倉鏡像
spos = {"side": -1, "entry": 4000.0, "stop": 4006.0, "target": 3980.0}
s = hold_rules.suggest(spos, flat, ATR, 3994.0, 4006.0)
check("空倉：浮盈 1R、價 3994 → 1×ATR 候選 3996（≥保本）", s["sl"] == 3996.0, s)
s = hold_rules.suggest({**spos, "stop": 3995.0}, flat, ATR, 3994.0, 4006.0)
check("空倉：候選 3996 鬆過現止損 3995 → 唔郁", s["sl"] is None, s)
sw_s = bars([4000.0] * 100 + [3994.0] * 8 + [3997.0] + [3994.0] * 8 + [3993.0] * 10)
s = hold_rules.suggest(spos, sw_s, ATR, 3993.0, 4006.0)
check("空倉擺動高 3997.2（外 0.1ATR＝3997.4）vs 1×ATR 3995 → 取較遠 3997.4", s["sl"] == 3997.4 and s["reason"] == "跟擺動點", s)
# 0.5×ATR 上限：候選唔會近過 0.5×ATR
s = hold_rules.suggest({**pos, "stop": 3999.0}, bars([4000.0] * 100 + [4010.0] * 8 + [4009.5] + [4010.0] * 8 + [4010.2] * 10), 2.0, 4010.2, 3994.0)
check("擺動低 4009.3 太近（< 0.5×ATR）唔算擺動點；1×ATR 候選 4008.2", s["sl"] == 4008.2 and s["trail_swing"] is None, s)
s = hold_rules.suggest({**pos, "stop": 3999.0}, bars([4000.0] * 100 + [4010.0] * 8 + [3990.0] + [4010.0] * 8 + [4010.2] * 10), 2.0, 4010.2, 3994.0)
check("上一個擺動低 3989.8 好遠 → 取較遠＝擺動點，但只准收緊 → 保本 4000（教學第 1 條）", s["sl"] == 4000.0 and s["reason"] == "保本", s)
check("strict_swings：橫行打和唔算擺動點", hold_rules.strict_swings(bars([4000.0] * 30), 1) == [] and hold_rules.strict_swings(bars([4000.0] * 30), -1) == [])
check("strict_swings：低位 4003 嚴格最細 → 一個擺動低", hold_rules.strict_swings(sw, 1) == [4002.8], hold_rules.strict_swings(sw, 1))
# 四位小數產品
s = hold_rules.suggest({"side": 1, "entry": 1.1000, "stop": 1.0990, "target": 1.1030}, bars([1.1] * 130), 0.0008, 1.1012, 1.0990, nd=5)
check("EURUSD 5 位：浮盈 12 pip ≥ 1R（10）→ 1×ATR 候選 1.1004", s["sl"] == 1.1004, s)

print("=== should_ask：Opus 只喺特定分鐘問")
config.HOLD_RULES_ASK_MIN = 5
hr = {"initial_stop": 3994.0, "last_m15_time": 900, "last_ask_ts": 1000.0}
p = {"side": 1, "entry": 4000.0, "stop": 3994.0, "target": 4020.0}
check("同一 M15、未夠 5 分鐘、唔近 SL／TP → 唔問", hold_rules.should_ask(hr, p, 4005.0, 2.0, 900, 1000.0 + 120) == [])
check("新 M15 → 問", "新 M15" in hold_rules.should_ask(hr, p, 4005.0, 2.0, 1800, 1000.0 + 120))
check("首次 1R → 問", "首次 1R" in hold_rules.should_ask(hr, p, 4006.0, 2.0, 900, 1000.0 + 120, r_hit_first=True))
check("離止損 ≤0.5×ATR → 問", "近止損" in hold_rules.should_ask(hr, p, 3995.0, 2.0, 900, 1000.0 + 120))
check("離止賺 ≤0.5×ATR → 問", "近止賺" in hold_rules.should_ask(hr, p, 4019.2, 2.0, 900, 1000.0 + 120))
check("滿 5 分鐘 → 問", any("5 分鐘" in w for w in hold_rules.should_ask(hr, p, 4005.0, 2.0, 900, 1000.0 + 300)))
check("冇初始止損 → 問", "冇初始止損／ATR" in hold_rules.should_ask({"initial_stop": None, "last_m15_time": 900, "last_ask_ts": 1000.0}, p, 4005.0, 2.0, 900, 1060.0))

print("=== track／compare")
t = hold_rules.track(None, {"ticket": 5, "side": 1, "entry": 4000.0, "stop": 3994.0}, 10.0)
check("track：新倉 key=t5、initial_stop=3994", t["key"] == "t5" and t["initial_stop"] == 3994.0 and t["stats"] == {}, t)
t["stats"] = {"ai_moves": 3}
t2 = hold_rules.track(t, {"ticket": 5, "side": 1, "entry": 4000.0, "stop": 3998.0}, 20.0)
check("同一倉再 track：initial_stop 唔變（止損已移到 3998）", t2 is t and t2["initial_stop"] == 3994.0)
t3 = hold_rules.track(t2, {"ticket": 6, "side": -1, "entry": 4010.0, "stop": 4016.0}, 30.0)
check("換倉：重設但 stats 跨倉保留", t3["key"] == "t6" and t3["initial_stop"] == 4016.0 and t3["stats"] == {"ai_moves": 3}, t3)
check("track 紙上倉 key 用 opened_ts", hold_rules.track(None, {"side": 1, "entry": 1, "stop": 0.5, "opened_ts": 77}, 0)["key"] == "p77")
st = hold_rules.compare(None, 4004.0, "UPDATE_STOP", 4004.5, 3994.0, 1.0)
check("compare：Opus 4004.5 vs 規則 4004 → both、within_tol", st["ai_moves"] == 1 and st["both"] == 1 and st["within_tol"] == 1 and st["agree_pct"] == 100.0, st)
st = hold_rules.compare(st, 4004.0, "UPDATE_STOP", 4008.0, 3994.0, 1.0)
check("compare：相差 4 → both 但唔 within → 50%", st["both"] == 2 and st["within_tol"] == 1 and st["agree_pct"] == 50.0, st)
st = hold_rules.compare(st, None, "UPDATE_STOP", 4001.0, 3994.0, 1.0)
check("compare：Opus 移、規則唔移 → ai_only", st["ai_only"] == 1)
st = hold_rules.compare(st, 4005.0, "HOLD", None, 3994.0, 1.0)
check("compare：規則移、Opus HOLD → rule_only", st["rule_only"] == 1 and st["rule_moves"] == 3)
st = hold_rules.compare(st, None, "UPDATE_STOP", 3994.0, 3994.0, 1.0)
check("compare：Opus UPDATE_STOP 但止損冇變 → 唔算移", st["ai_moves"] == 3)
check("mode 預設 shadow；亂寫當 shadow", hold_rules.mode() == "shadow" and (setattr(config, "HOLD_RULES", "xx") or hold_rules.mode() == "shadow"))
config.HOLD_RULES = "shadow"

# ---------------------------------------------------------------- 整合（紙上）
print("=== shadow：唔改行為，只記錄")
NOW = [1792600000.0]
xau.now_ts = lambda: NOW[0]
class FB:
    decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}; calls = []
    def screen(self, ctx): return {"look": True, "reason": "", "_usage": {}, "_ms": 1}
    def decide(self, ctx): FB.calls.append("decide"); return {**FB.decision, "_usage": {"in": 5000, "out": 300, "cache_read": 4000, "model": "claude-opus-5-5"}, "_ms": 2500, "_lessons": None}
xau._brain = FB()
app = xau.app; client = app.test_client()
T0 = 1792599000
def last_rec():
    return json.loads(FAKE["xau/state.json"][0])["last_decision"]
def hb(i, close, high=None, low=None, m15_time=None, m1_tail=None):
    t = T0 + i * 60; o = close
    body = {"action": "heartbeat", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "credit": 5000,
            "floating": 0, "daily_pnl": 0, "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
            "m1_ohlc": {"time": t, "open": o, "high": high if high is not None else close + 0.2, "low": low if low is not None else close - 0.2, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": m15_time if m15_time is not None else T0 + (i // 15) * 900, "open": o, "high": close + 1, "low": close - 1, "close": close}}
    NOW[0] = t + 5
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    j = r.get_json()
    if j.get("decision") is not None:
        j["decision"] = last_rec()                      # 心跳回應只帶部分欄位；測試讀完整紀錄
    return r.status_code, j
def seed(m1_closes, m15_n=40):
    FAKE["xau/m1.json"] = (json.dumps([{"time": T0 - (len(m1_closes) - k) * 60, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p} for k, p in enumerate(m1_closes)]), 1)
    FAKE["xau/m15.json"] = (json.dumps([{"time": T0 - 900 * (m15_n - k), "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.0} for k in range(m15_n)]), 1)   # M15 ATR = 2
seed([4000.0] * 130)
FB.decision = {"action": "OPEN_LONG", "stop_price": 3994.0, "target_price": 4020.0, "confidence": 0.9, "reason": "買"}
st, d = hb(1, 4000.0)
state = json.loads(FAKE["xau/state.json"][0])
check("紙上開多 @4000 止損 3994", state["position"] and state["position"]["stop"] == 3994.0, d)
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
FB.calls.clear()
st, d = hb(2, 4003.0)
state = json.loads(FAKE["xau/state.json"][0])
hr = state.get("hold_rules") or {}
check("shadow：有倉照問 Opus；rec.hold_rules stage pre_1r、ask 含「新 M15」（第一次）", FB.calls == ["decide"] and d["decision"]["hold_rules"]["stage"] == "pre_1r" and "新 M15" in d["decision"]["hold_rules"]["ask"], d["decision"].get("hold_rules"))
check("state.hold_rules：key=p<opened_ts>、initial_stop 3994", hr.get("key", "").startswith("p") and hr.get("initial_stop") == 3994.0, hr)
def atr15():
    return market.wilder_atr(json.loads(FAKE["xau/m15.json"][0]))
def cur_stop():
    return json.loads(FAKE["xau/state.json"][0])["position"]["stop"]
st, d = hb(3, 4006.5)
h = d["decision"]["hold_rules"]; a = atr15()
check("浮盈 ≥1R：規則建議 = 現價 − 1×M15 ATR、ask 含「首次 1R」；Opus HOLD → 止損唔變（shadow）", h["sl"] == round(4006.5 - a, 2) and "首次 1R" in h["ask"] and cur_stop() == 3994.0, (h, a))
state = json.loads(FAKE["xau/state.json"][0])
check("stats：rule_only 1", state["hold_rules"]["stats"]["rule_only"] == 1 and state["hold_rules"]["stats"]["ai_moves"] == 0, state["hold_rules"]["stats"])
FB.decision = {"action": "UPDATE_STOP", "stop_price": round(4006.5 - atr15() + 0.5, 2), "target_price": None, "confidence": 0.9, "reason": "收緊"}
st, d = hb(4, 4006.5)
state = json.loads(FAKE["xau/state.json"][0])
h = d["decision"]["hold_rules"]
check("Opus 移（規則＋0.5）vs 規則 → both、within_tol、ai_sl 記錄", state["hold_rules"]["stats"]["both"] == 1 and state["hold_rules"]["stats"]["within_tol"] == 1 and h["ai_sl"] == FB.decision["stop_price"], (h, state["hold_rules"]["stats"]))
check("shadow 第 4 分鐘：同 M15、未滿 5 分鐘、唔近 SL／TP → ask 空（on 模式會唔問），rule_minutes 1", h["ask"] == [] and state["hold_rules"]["stats"]["rule_minutes"] == 1, (h["ask"], state["hold_rules"]["stats"]))
check("止損已改（Opus 嘅決定照行）", cur_stop() == FB.decision["stop_price"])
check("JSON status 有 hold_rules.mode=shadow", xau.build_status()["hold_rules"]["mode"] == "shadow" and xau.build_status()["hold_rules"]["stats"]["both"] == 1)

print("=== on：規則處理、Opus 只喺特定分鐘問")
config.HOLD_RULES = "on"
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
FB.calls.clear()
old = cur_stop()
st, d = hb(5, 4009.0)          # 同一 M15（i//15 = 0）、上次問係 i=3（首次 1R）→ 2 分鐘前 → 唔問；規則 1×ATR 收緊
r = d["decision"]
check("on：唔問 Opus，規則移止損（1×ATR），kind=hold_rules、cost 0", FB.calls == [] and r["kind"] == "hold_rules" and r["final"] == "UPDATE_STOP" and cur_stop() == round(4009.0 - atr15(), 2) and cur_stop() > old and r["cost_usd"] == 0.0, r)
st, d = hb(6, 4009.05)
check("on：規則冇新建議（幅度 < 0.1×ATR）→ kind=hold_rules HOLD，唔問 Opus", FB.calls == [] and d["decision"]["kind"] == "hold_rules" and d["decision"]["final"] == "HOLD", d["decision"])
st, d = hb(7, 4009.1, m15_time=T0 + 900)      # 新 M15 → 問
check("on：新 M15 → 問 Opus", FB.calls == ["decide"] and d["decision"]["kind"] == "decide" and "新 M15" in d["decision"]["hold_rules"]["ask"], d["decision"].get("hold_rules"))
FB.calls.clear()
st, d = hb(8, round(cur_stop() + 0.3, 2), m15_time=T0 + 900)      # 離止損 0.3 ≤ 0.5×ATR → 問
check("on：近止損 → 問 Opus", FB.calls == ["decide"] and "近止損" in d["decision"]["hold_rules"]["ask"], d["decision"].get("hold_rules"))
FB.calls.clear()
far = round(cur_stop() + atr15() + 0.5, 2)                        # 離止損 > 0.5×ATR、離止賺 4020 亦遠
for k in range(9, 13):
    hb(k, far, m15_time=T0 + 900)
check("on：之後 4 分鐘唔問", FB.calls == [], FB.calls)
st, d = hb(13, far, m15_time=T0 + 900)     # 距 i=8 滿 5 分鐘
check("on：滿 5 分鐘 → 問 Opus", FB.calls == ["decide"] and any("5 分鐘" in w for w in d["decision"]["hold_rules"]["ask"]), d["decision"].get("hold_rules"))
FB.calls.clear()
loose = round(cur_stop() - 1.0, 2)
FB.decision = {"action": "UPDATE_STOP", "stop_price": loose, "target_price": None, "confidence": 0.9, "reason": "放鬆"}
st, d = hb(14, far, m15_time=T0 + 1800)
check("新 M15 問 Opus：Opus 移遠 1 美元（rules.validate 唔擋，Opus 權限照舊）", cur_stop() == loose, (cur_stop(), loose))
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
FB.calls.clear()
st, d = hb(15, 4019.5, m15_time=T0 + 1800)    # 近止賺 4020 → 問
check("on：近止賺 → 問 Opus", FB.calls == ["decide"] and "近止賺" in d["decision"]["hold_rules"]["ask"], d["decision"].get("hold_rules"))
FB.calls.clear()
st, d = hb(16, 4014.0, m15_time=T0 + 1800)
check("on：下一分鐘規則收返（現價 − 1×ATR），唔問", FB.calls == [] and cur_stop() == round(4014.0 - atr15(), 2) and cur_stop() > loose, (d["decision"], cur_stop()))
config.HOLD_RULES = "off"
FB.calls.clear()
st, d = hb(17, 4014.5, m15_time=T0 + 1800)
check("off：每分鐘照問 Opus，rec 冇 hold_rules", FB.calls == ["decide"] and "hold_rules" not in d["decision"], d["decision"].keys())
config.HOLD_RULES = "shadow"

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
