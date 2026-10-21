"""訊號書 S1（總指揮 10-21 轉達使用者「訊號書都要落單」）：SIG_DECIDE=1 先處理 EA 心跳；冇有效訊號唔問 Claude；
開倉一定要引用有效訊號；理由註明參考咗邊條訊號；唔使 Haiku 篩選；magic 931；system／tool 有訊號書段，主服務唔受影響。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="1", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="0", GATE_MODEL="claude-haiku-5-5")
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
import main as xau, config, signals, market, brain   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [1792600000.0]
xau.now_ts = lambda: NOW[0]
signals.now_ts = lambda: NOW[0]
market.now_ts = lambda: NOW[0]

class FakeBrain:
    def __init__(self): self.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等", "signal_id": None}; self.calls = []; self.ctx = None
    def screen(self, ctx): self.calls.append("screen"); return {"look": True, "reason": "x", "_usage": {}, "_ms": 1}
    def decide(self, ctx): self.calls.append("decide"); self.ctx = ctx; return {**self.decision, "_usage": {"in": 1, "out": 1, "model": "claude-opus-5-5"}, "_ms": 10, "_lessons": None}
FB = FakeBrain(); xau._brain = FB
T0 = 1792599000
FAKE["xau/sig/m15.json"] = (json.dumps([{"time": T0 - 900 * (30 - k), "open": 3999.0, "high": 4001.0, "low": 3998.0, "close": 4000.0} for k in range(30)]), 1)
FAKE["xau/sig/m1.json"] = (json.dumps([{"time": T0 - 60 * (40 - k), "open": 4000.0, "high": 4000.5, "low": 3999.5, "close": 4000.0} for k in range(40)]), 1)
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user"}), 1)

def hb(i, close):
    t = T0 + i * 60
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": 0,
            "m1_ohlc": {"time": t, "open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": T0 + (i // 15) * 900, "open": close, "high": close + 1, "low": close - 1, "close": close}}
    NOW[0] = t + 5
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def put_signal(sid, side="BUY", lo=3999, hi=4001, sl=3990, tp=(4010,), status="valid", left_min=20):
    rows = json.loads(FAKE.get("xau/sig/signals/recent.json", ("[]", 0))[0])
    rows.append({"sid": sid, "kind": "new_signal", "status": status, "side": side, "entry_low": lo, "entry_high": hi, "sl": sl, "tp": list(tp),
                 "msg_ts": NOW[0] - 60, "valid_until_ts": NOW[0] + left_min * 60})
    FAKE["xau/sig/signals/recent.json"] = (json.dumps(rows), 1)

print("=== 設定 ===")
check("magic 931、前綴 xau/sig/", config.MAGIC == 931 and config.PREFIX == "xau/sig/")
check("decide tool 有 signal_id（訊號書）", "signal_id" in brain.TOOL["input_schema"]["required"])
check("system 有訊號書段", "SIGNAL BOOK MODE" in brain.SYSTEM)

print("=== 冇有效訊號唔問 Claude ===")
st, d = hb(1, 4000)
check("EA 心跳收得（SIG_DECIDE=1）", st == 200 and d.get("status") != "ignored", d)
check("冇訊號 → 唔 screen、唔 decide", FB.calls == [], FB.calls)

print("=== 有效訊號 → 直接 decide（唔 Haiku 篩）===")
put_signal("1001_7")
NOW[0] = T0 + 2 * 60
put_signal("1001_8", status="expired")
hb(2, 4000)
check("有效訊號 → decide、冇 screen", FB.calls == ["decide"], FB.calls)
check("prompt 只有有效訊號（結構化）", [s["sid"] for s in FB.ctx["signals"]] == ["1001_7"] and "text" not in FB.ctx["signals"][0], FB.ctx.get("signals"))

print("=== 開倉要引用有效訊號 ===")
FB.decision = {"action": "OPEN_LONG", "stop_price": 3992, "target_price": 4010, "confidence": 0.8, "reason": "突破", "signal_id": None}
hb(3, 4000)
st_ = json.loads(FAKE["xau/sig/state.json"][0])
last = st_["decisions"][-1]
check("冇 signal_id → HOLD", last["final"] == "HOLD" and "引用有效訊號" in (last.get("rejected") or ""), last)
FB.decision = {**FB.decision, "signal_id": "1001_7"}
hb(4, 4000)
st_ = json.loads(FAKE["xau/sig/state.json"][0])
last = st_["decisions"][-1]
check("引用有效訊號 → 開倉（紙上）", last["final"] == "OPEN_LONG" and last.get("signal_id") == "1001_7", last)
check("理由自動註明訊號", "參考 TG 訊號 1001_7" in last["reason"] and "SL 3990" in last["reason"], last["reason"])

print("=== 有倉冇訊號都照管倉 ===")
FB.calls.clear()
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "揸住", "signal_id": None}
FAKE["xau/sig/signals/recent.json"] = ("[]", 1)
hb(5, 4001)
check("有倉 → 照問 decide", FB.calls == ["decide"], FB.calls)

print("=== 舊入口關閉 ===")
r = client.post("/", data=json.dumps({"action": "test_cmd", "token": "tok", "op": "open"}), content_type="application/json")
check("test_cmd 唔開放", r.get_json().get("status") != "queued", r.get_json())

html = client.get("/").get_data(as_text=True)
check("頁面有 S1 落單區同決策理由", "S1 落單" in html and "參考 TG 訊號 1001_7" in html)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
