"""慳成本 S（使用者 10-23「開 S shadow」）：空倉規則前篩。純函數、shadow 唔改行為只記錄、on 模式唔問 Opus／Haiku。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", ANTHROPIC_API_KEY="x", XAU_EXECUTE="0", XAU_HOLD_RULES="off", XAU_PRESCREEN="shadow",
                  XAU_REUSE_HOLD="off", GATE_MODEL="claude-haiku-5-5", XAU_MAX_HOLD_MIN="0")
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
import main as xau, config, prescreen, market   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

print("=== evaluate 純函數")
def bars(prices, t0=1000):
    return [{"time": t0 + i * 60, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p} for i, p in enumerate(prices)]
rise = bars([4000.0 + 0.01 * i for i in range(130)])          # 平穩微升：冇擺動點、M1 ATR ≈ 0.4
m15 = [{"time": 900 * k, "open": 4000, "high": 4001, "low": 3999, "close": 4000} for k in range(30)]
NOW = 1000 + 130 * 60 + 5
r = prescreen.evaluate(rise, m15, 4001.3, None, 0, NOW)
check("冇錨點 → 一定問", r["ask"] and r["reasons"] == ["冇上次決策"], r)
anchor = {"price": 4001.3, "m15_time": m15[-1]["time"]}
r = prescreen.evaluate(rise, m15, 4001.32, anchor, 0, NOW)
check("同一 M15、價格冇變、唔貼位、冇急走 → 唔問", not r["ask"], r)
r = prescreen.evaluate(rise, m15 + [{"time": 900 * 30, "open": 4000, "high": 4001, "low": 3999, "close": 4000}], 4001.32, anchor, 0, NOW)
check("新 M15 → 問", r["ask"] and "新 M15" in r["reasons"], r)
r = prescreen.evaluate(rise, m15, 4001.3 + 0.3, anchor, 0, NOW)
check("價格離錨點 0.3 ≥ 0.3×M1 ATR（≈0.4→0.12）→ 問", r["ask"] and any("M1 ATR" in x for x in r["reasons"]), r)
sw = bars([4000.0] * 100 + [4006.0] * 8 + [4003.0] + [4006.0] * 8 + [4007.0] * 10)
anchor2 = {"price": 4004.3, "m15_time": m15[-1]["time"]}
r = prescreen.evaluate(sw, m15, 4004.3, anchor2, 0, 1000 + len(sw) * 60 + 5)
check("現價 4004.3 距擺動低 4002.8 = 1.5 ≤ 2 → 問（貼近關鍵位）", r["ask"] and any("貼近" in x for x in r["reasons"]) and r["near"] == 1.5, r)
fast = bars([4000.0] * 110 + [4000.0 - 0.25 * i for i in range(1, 21)])
anchor3 = {"price": fast[-1]["close"], "m15_time": m15[-1]["time"]}
r = prescreen.evaluate(fast, m15, fast[-1]["close"], anchor3, 0, 1000 + len(fast) * 60 + 5)
check("前 15 分鐘跌 3.75 ≥ 3 → 問", r["ask"] and any("前 15 分鐘" in x for x in r["reasons"]), r)
st = prescreen.bump(None, False); st = prescreen.bump(st, True, opened=True); st = prescreen.bump(st, False, opened=True)
check("bump：3 分鐘、skip 2、opens 2、opens_in_skip 1 → kept 50%、skip 66.7%", st["minutes"] == 3 and st["skip"] == 2 and st["opens"] == 2 and st["opens_in_skip"] == 1 and st["opens_kept_pct"] == 50.0 and st["skip_pct"] == 66.7, st)
check("mode 預設 shadow；亂寫當 shadow", prescreen.mode() == "shadow" and (setattr(config, "PRESCREEN", "zz") or prescreen.mode() == "shadow"))
config.PRESCREEN = "shadow"

print("=== 整合：shadow 唔改行為；on 唔問")
NOWL = [1792600000.0]
xau.now_ts = lambda: NOWL[0]
class FB:
    decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}; calls = []; look = True
    def screen(self, ctx): FB.calls.append("screen"); return {"look": FB.look, "reason": "睇下", "_usage": {"in": 100, "out": 10, "model": "claude-haiku-5-5"}, "_ms": 300}
    def decide(self, ctx): FB.calls.append("decide"); return {**FB.decision, "_usage": {"in": 5000, "out": 300, "cache_read": 4000, "model": "claude-opus-5-5"}, "_ms": 2500, "_lessons": None}
xau._brain = FB()
app = xau.app; client = app.test_client()
T0 = 1792599000
def last_rec():
    return json.loads(FAKE["xau/state.json"][0])["last_decision"]
def hb(i, close, m15_time=None):
    t = T0 + i * 60
    body = {"action": "heartbeat", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "credit": 5000,
            "floating": 0, "daily_pnl": 0, "buy_lots": 0, "sell_lots": 0, "net_lots": 0,
            "m1_ohlc": {"time": t, "open": close, "high": close + 0.2, "low": close - 0.2, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": m15_time if m15_time is not None else T0 - 900, "open": close, "high": close + 1, "low": close - 1, "close": close}}
    NOWL[0] = t + 5
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()
FAKE["xau/m1.json"] = (json.dumps([{"time": T0 - (130 - k) * 60, "open": 4000.0 + 0.01 * k, "high": 4000.2 + 0.01 * k, "low": 3999.8 + 0.01 * k, "close": 4000.0 + 0.01 * k} for k in range(130)]), 1)
FAKE["xau/m15.json"] = (json.dumps([{"time": T0 - 900 * (40 - k), "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.0} for k in range(40)]), 1)
FB.calls.clear()
st, d = hb(1, 4001.3)
r = last_rec()
check("shadow 第一分鐘：冇錨點 → 規則會問；照 Haiku＋Opus", r["prescreen"]["ask"] and FB.calls == ["screen", "decide"], (r.get("prescreen"), FB.calls))
FB.calls.clear()
st, d = hb(2, 4001.31)
r = last_rec(); state = json.loads(FAKE["xau/state.json"][0])
check("shadow 第二分鐘：規則唔會問（ask False），但 shadow 照問 Haiku＋Opus（行為唔變）", r["prescreen"]["ask"] is False and FB.calls == ["screen", "decide"], (r.get("prescreen"), FB.calls))
check("stats：2 分鐘、skip 1、opens 0；錨點仍係第一分鐘價", state["prescreen_stats"]["skip"] == 1 and state["prescreen_stats"]["minutes"] == 2 and state["prescreen_anchor"]["price"] == 4001.3, (state.get("prescreen_stats"), state.get("prescreen_anchor")))
FB.decision = {"action": "OPEN_LONG", "stop_price": 3994.0, "target_price": 4020.0, "confidence": 0.9, "reason": "買"}
st, d = hb(3, 4001.32)
state = json.loads(FAKE["xau/state.json"][0])
check("shadow：Opus 喺「規則唔問」嘅分鐘開倉 → opens_in_skip 1（漏單計數）", state["prescreen_stats"]["opens"] == 1 and state["prescreen_stats"]["opens_in_skip"] == 1 and state["position"] is not None, state["prescreen_stats"])
FB.decision = {"action": "CLOSE", "stop_price": None, "target_price": None, "confidence": 0.9, "reason": "走"}
FB.calls.clear()
st, d = hb(4, 4001.4)
r = last_rec()
check("有倉：唔經前篩（rec 冇 prescreen），直接問 Opus", "prescreen" not in r and FB.calls == ["decide"], (r.keys(), FB.calls))
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
config.PRESCREEN = "on"
FB.calls.clear()
st, d = hb(5, 4001.41)      # 錨點 4001.32（第 3 分鐘問過）、同 M15、唔貼位 → on：唔問
r = last_rec()
check("on：規則唔問 → kind=prescreen、cost 0、唔叫 Haiku 同 Opus", r["kind"] == "prescreen" and r["final"] == "HOLD" and r["cost_usd"] == 0.0 and FB.calls == [], (r.get("kind"), FB.calls))
FB.calls.clear()
st, d = hb(6, 4001.45, m15_time=T0 + 900)   # 新 M15 → 問
r = last_rec()
check("on：新 M15 → 問 Haiku＋Opus，kind=decide", r["kind"] == "decide" and FB.calls == ["screen", "decide"] and "新 M15" in r["prescreen"]["reasons"], (r.get("kind"), FB.calls, r.get("prescreen")))
FB.calls.clear(); FB.look = False
st, d = hb(7, 4001.9, m15_time=T0 + 900)    # 價格離錨點 0.45 ≥ 0.3×ATR → 問，但 Haiku 擋
r = last_rec(); state = json.loads(FAKE["xau/state.json"][0])
check("on：規則問、Haiku 擋 → kind=screen，stats minutes 加", r["kind"] == "screen" and FB.calls == ["screen"] and state["prescreen_stats"]["minutes"] == 6, (r.get("kind"), FB.calls, state["prescreen_stats"]))   # 第 4 分鐘有倉唔經前篩
FB.look = True
check("JSON status 有 prescreen.mode／skip_pct", xau.build_status()["prescreen"]["mode"] == "on" and "skip_pct" in xau.build_status()["prescreen"])
config.PRESCREEN = "on"
_orig = prescreen.evaluate
def _boom(*a, **k): raise ValueError("boom")
prescreen.evaluate = _boom
FB.calls.clear()
st, d = hb(8, 4001.91, m15_time=T0 + 900)
r = last_rec()
check("前篩例外 → fail-open 當要問（照問 Haiku＋Opus、kind=decide、reasons 記例外），唔中斷決策", r["kind"] == "decide" and FB.calls == ["screen", "decide"] and any("例外" in x for x in r["prescreen"]["reasons"]), (r.get("kind"), FB.calls, r.get("prescreen")))
prescreen.evaluate = _orig
config.PRESCREEN = "off"
FB.calls.clear()
st, d = hb(9, 4001.92, m15_time=T0 + 900)
r = last_rec()
check("off：每分鐘照問，rec 冇 prescreen", "prescreen" not in r and FB.calls == ["screen", "decide"], (r.keys(), FB.calls))
config.PRESCREEN = "shadow"

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
