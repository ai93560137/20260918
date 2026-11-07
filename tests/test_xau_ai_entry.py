"""[IDEAS #1003] AI 揀入場（影子計劃＋magic 936 實倉）：計劃驗證、入場檢查、ask 記錄、936 心跳分流、獨立開關、TTL、停線 C、id 前綴 i。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5",
                  SIG_AIENTRY="1", SIG_AIENTRY_EXECUTE="1", SIG_AIENTRY_ACCOUNT="5550063")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
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
import main as xau, config, ai_entry   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [1792600000.0]
xau.now_ts = lambda: NOW[0]
T0 = 1792599000
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 1)

def hb(i, close, magic=936, account="5550063", positions=None):
    t = T0 + i * 60; NOW[0] = t + 5
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": 0,
            "realized_total": 0, "bots_daily_pnl": 0, "bots_floating": 0, "bots_realized_total": 0, "magic": magic, "positions": positions or [],
            "account": account, "trade_allowed": {"terminal": True, "ea": True, "account": True},
            "m1_ohlc": {"time": t, "open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": T0 + (i // 15) * 900, "open": close, "high": close + 1, "low": close - 1, "close": close}}
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

print("=== 設定 ===")
check("magic 931 → 936、預設規則 rev15", config.AIENTRY_MAGIC == 936 and config.AIENTRY_RULES == ("rule:rev15",))
check("只開 SIG_AIENTRY_EXECUTE → 淨係 936 真倉（933 唔係）", config.book_live(936) and not config.book_live(933) and not config.book_live(931))

print("=== validate（純函數）===")
v = lambda **k: ai_entry.validate({"take": True, "entry_price": 3994, "stop_price": 3988, "target_price": 4004, "reason": "x", **k}, "BUY", 4000.0)
p, why = v()
check("BUY 回調 6、SL 6、TP 上面 → 合格", p == {"entry": 3994.0, "sl": 3988.0, "tp": 4004.0, "risk": 6.0}, (p, why))
check("take=false → 唔做", ai_entry.validate({"take": False}, "BUY", 4000.0)[0] is None)
check("BUY 入場價高過現價 → 錯邊", v(entry_price=4003)[0] is None)
check("入場價離現價 > 15 → 唔合格", v(entry_price=3980, stop_price=3975, target_price=3990)[0] is None)
check("止蝕距離 < 2 → 唔合格", v(stop_price=3993)[0] is None)
check("止蝕距離 > 15 → 唔合格", v(stop_price=3970)[0] is None)
check("止賺錯邊 → 唔合格", v(target_price=3990)[0] is None)
p, _ = ai_entry.validate({"take": True, "entry_price": 4005, "stop_price": 4011, "target_price": 3995, "reason": ""}, "SELL", 4000.0)
check("SELL 反彈入、SL 上面 → 合格", p and p["risk"] == 6.0, p)
check("價位唔係數字 → 唔合格", ai_entry.validate({"take": True, "entry_price": None, "stop_price": 1, "target_price": 2}, "BUY", 4000.0)[0] is None)

print("=== entry_check（純函數）===")
plan = {"side": "BUY", "entry": 3994.0, "sl": 3988.0, "tp": 4004.0}
check("現價 3999 → 等", ai_entry.entry_check(plan, 3999.0)[0] == "wait")
check("現價 3994.2 → 入（容差內）", ai_entry.entry_check(plan, 3994.2)[0] == "ok")
check("現價跌穿 SL → 略過", ai_entry.entry_check(plan, 3987.0)[0] == "skip")
check("現價已過 TP → 略過", ai_entry.entry_check(plan, 4005.0)[0] == "skip")

print("=== ask（影子記錄）===")
calls = []
def fake_call(brain_obj, ctx):
    calls.append(ctx)
    return {"take": True, "entry_price": 3994, "stop_price": 3988, "target_price": 4004, "reason": "回調入"}, None, None
ai_entry._call = fake_call
pred = {"id": "p1", "student": "rule:rev15", "side": "BUY", "price": 4000.0, "ref": -3.5}
NOW[0] = T0 + 5
rec = ai_entry.ask(object(), lambda: {"last_price": 4000.0, "signals": [1]}, pred, NOW[0])
st = json.loads(FAKE["xau/sig/aientry/state.json"][0])
check("rev15 出區 → 問 AI、記錄合格計劃", rec and rec["valid"] and st["plans"][-1]["entry"] == 3994.0 and st["usage"]["n"] == 1, rec)
check("context 有 entry_task、冇 signals", calls and "entry_task" in calls[-1] and "signals" not in calls[-1] and calls[-1]["entry_task"]["side"] == "BUY")
check("寫咗 log jsonl", any(k.startswith("xau/sig/aientry/log/") for k in FAKE))
check("唔係登記規則（level）→ 唔問", ai_entry.ask(object(), lambda: {}, {**pred, "student": "rule:level"}, NOW[0]) is None and len(calls) == 1)
config.AIENTRY = False
check("SIG_AIENTRY=0 → 唔問", ai_entry.ask(object(), lambda: {}, pred, NOW[0]) is None and len(calls) == 1)
config.AIENTRY = True
ai_entry._call = lambda b, c: (None, None, "AI 出錯：X")
rec2 = ai_entry.ask(object(), lambda: {}, {**pred, "id": "p2"}, NOW[0])
check("AI 出錯 → 記錄唔合格、唔會落", rec2 and not rec2["valid"] and rec2["error"])

print("=== 936 心跳（實倉）===")
FAKE["xau/sig/account.json"] = (json.dumps({"marker": "931"}), 1)
code, d = hb(1, 3999.0)
check("現價未到入場價 → 等、冇指令", d.get("book") == "aientry" and d["cmd_text"] == "" and "等現價" in d["message"], d)
check("936 心跳唔寫 931 快照", json.loads(FAKE["xau/sig/account.json"][0]).get("marker") == "931")
code, d = hb(2, 3994.1)
check("現價到入場價 → 排 open 指令（0.01 手、AI SL／TP、magic 936、id 前綴 i、note AI入場）",
      d["cmd_text"].startswith("open|BUY|0.01|sl=3988.00|tp=4004.00|magic=936|note=AI入場") and "|id=i" in d["cmd_text"], d)
st = json.loads(FAKE["xau/sig/aientry/state.json"][0])
cid = st["orders"][-1]["id"]
r = client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 99, "account": "5550063"}), content_type="application/json").get_json()
check("cmd_ack 前綴 i → 分流到 AI 入場書", r.get("status") == "acked", r)
code, d = hb(3, 3994.0)
check("同一計劃唔會落第二次", d["cmd_text"] == "" or "id=" + cid in d["cmd_text"], d)
code, d = hb(4, 3994.0, account="999")
check("戶口唔啱 → ignored", d.get("status") == "ignored", d)

print("=== 獨立開關／TTL ===")
FAKE["xau/sig/aientry/state.json"] = (json.dumps({"plans": [{"id": "q1", "valid": True, "side": "SELL", "entry": 4005.0, "sl": 4011.0, "tp": 3995.0, "ts": T0 + 600}],
                                                  "pending_cmds": [], "used": [], "orders": []}), 50)
config.AIENTRY_EXECUTE = False; config.BOOK_EXECUTE[936] = False
code, d = hb(11, 4005.0)
st = json.loads(FAKE["xau/sig/aientry/state.json"][0])
check("SIG_AIENTRY_EXECUTE=0 → 紙上記錄、cmd_text 空", d["cmd_text"] == "" and d["mode"] == "shadow" and st["orders"][-1]["applied"] == "paper", d)
config.AIENTRY_EXECUTE = True; config.BOOK_EXECUTE[936] = True
FAKE["xau/sig/aientry/state.json"] = (json.dumps({"plans": [{"id": "q2", "valid": True, "side": "SELL", "entry": 4005.0, "sl": 4011.0, "tp": 3995.0, "ts": T0}],
                                                  "pending_cmds": [], "used": [], "orders": []}), 60)
code, d = hb(40, 4005.0)
check("計劃過咗 30 分鐘 TTL → 唔落", d["cmd_text"] == "" and "冇有效" in d["message"], d)

print("=== 停線 C ===")
config.AIENTRY_HWM_START = "2026-10-01"
book = [{"closed_ts": 1792000000 + k, "r": -1.0} for k in range(8)]
why, stt = ai_entry.strategy_stop({"book": book})
check("由起計日累計 −8R → 停", why and "≤ −8R" in why and stt["cum_r"] == -8.0, (why, stt))
why, stt = ai_entry.strategy_stop({"book": [{"closed_ts": 1792000000, "r": 6.0}] + [{"closed_ts": 1792000001 + k, "r": -1.0} for k in range(10)]})
check("由高位回撤 10R → 停", why and "回撤" in why, (why, stt))
config.AIENTRY_HWM_START = "bad"
check("起計日格式錯 → 為安全停", "格式錯" in (ai_entry.strategy_stop({})[0] or ""))
config.AIENTRY_HWM_START = ""
check("冇起計日 → 唔計", ai_entry.strategy_stop({"book": book})[0] is None)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
