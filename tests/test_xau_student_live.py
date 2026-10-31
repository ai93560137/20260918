"""[R358] 規則學生真倉（magic 933；使用者 10-31 揀 A）：只落准咗嘅規則、入場區內市價入、TTL、931＋933 合共上限、日蝕暫停、id 前綴 s、預設關。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5",
                  SIG_STUDENT_LIVE="1", SIG_STUDENT_LIVE_RULES="rev15", SIG_STUDENT_DAY_STOP_HKD="300")
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
import main as xau, config, follower, student_live   # noqa: E402

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

def hb(i, close, magic=933, positions=None, extra=None):
    t = T0 + i * 60; NOW[0] = t + 5
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": 0,
            "realized_total": 0, "bots_daily_pnl": 0, "bots_floating": 0, "bots_realized_total": 0, "magic": magic, "positions": positions or [],
            "trade_allowed": {"terminal": True, "ea": True, "account": True},
            "m1_ohlc": {"time": t, "open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": T0 + (i // 15) * 900, "open": close, "high": close + 1, "low": close - 1, "close": close}, **(extra or {})}
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()


def put_pred(pid, student="rule:rev15", side="SELL", lo=3999, hi=4001, sl=4006, tp=3990, age=60):
    st = json.loads(FAKE.get("xau/sig/student/state.json", (json.dumps({"preds": []}), 0))[0])
    st["preds"].append({"id": pid, "student": student, "ts": NOW[0] - age, "side": side, "entry_low": lo, "entry_high": hi, "sl": sl, "tp": [tp], "price": 4000})
    FAKE["xau/sig/student/state.json"] = (json.dumps(st), 1)
def sstate(): return json.loads(FAKE["xau/sig/studentlive/state.json"][0])

print("=== [R358] 設定 ===")
check("預設 magic 933、只准 rule:rev15、0.05 手、日蝕 300", student_live.enabled() and config.STUDENT_MAGIC == 933 and config.STUDENT_LIVE_RULES == ("rule:rev15",) and config.STUDENT_LOTS == 0.05)
check("entry_check：入場區內 ok、過 TP skip、未到 wait、SL 錯邊 skip",
      student_live.entry_check({"side": "SELL", "entry_low": 3999, "entry_high": 4001, "sl": 4006, "tp": [3990]}, 4000)[0] == "ok"
      and student_live.entry_check({"side": "SELL", "entry_low": 3999, "entry_high": 4001, "sl": 4006, "tp": [3990]}, 3989)[0] == "skip"
      and student_live.entry_check({"side": "SELL", "entry_low": 3999, "entry_high": 4001, "sl": 4006, "tp": [3990]}, 3995)[0] == "wait"
      and student_live.entry_check({"side": "SELL", "entry_low": 3999, "entry_high": 4001, "sl": 4006, "tp": [3990]}, 4007)[0] == "skip")

print("=== 落單 ===")
put_pred("p1", student="rule:level")
st, d = hb(1, 4000)
check("未准嘅規則（level）唔落", d["cmd_text"] == "" and "冇可落" in d["message"], d)
put_pred("p2")
st, d = hb(2, 4000)
check("rev15 SELL 入場區內 → open SELL 0.05 magic=933、id 前綴 s、帶 px／dev", d["cmd_text"].startswith("open|SELL|0.05|sl=4006.00|tp=3990.00|magic=933|note=學生rev15|px=4000.00|dev=") and "|id=s" in d["cmd_text"], d)
cid = sstate()["orders"][-1]["id"]
r = client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 77}), content_type="application/json").get_json()
check("cmd_ack 前綴 s → 學生真倉收到", r.get("status") == "acked" and sstate()["orders"][-1]["ok"] is True, r)
pos = [{"ticket": 77, "side": "SELL", "lots": 0.05, "entry": 4000, "sl": 4006, "tp": 3990, "open_time": T0}]
st, d = hb(3, 3998, positions=pos)
check("有倉 → 唔再開", d["cmd_text"] == "" and "有倉" in d["message"], d)
check("busy()：933 有倉 → 931 唔開", student_live.busy(NOW[0]))
st, d = hb(4, 3990, positions=[], extra={"realized_total": -50})

print("=== 風控 ===")
put_pred("p3")
st, d = hb(5, 4000, extra={"daily_pnl": -350})
check("933 今日蝕 ≥300 → 暫停", d["cmd_text"] == "" and "暫停開新倉" in d["message"], d)
FAKE["xau/sig/account.json"] = (json.dumps({"positions": [{"ticket": 1}]}), 9)
st, d = hb(6, 4000)
check("931 有倉 → 合共上限擋", d["cmd_text"] == "" and "合共上限" in d["message"], d)
FAKE["xau/sig/account.json"] = (json.dumps({"positions": []}), 10)
put_pred("p4", age=31 * 60)
st, d = hb(7, 4000)
check("p3 照落（931 冇倉）", d["cmd_text"].startswith("open|SELL"), d)
check("過咗 TTL 30 分鐘嘅 p4 唔會係候選", all(p["id"] != "p4" for p in student_live.candidates(NOW[0])))
config.STUDENT_ACCOUNT = "11"
st, d = hb(8, 4000, extra={"account": "99"})
check("戶口唔啱 → ignored", d.get("status") == "ignored", d)
config.STUDENT_ACCOUNT = ""

print("=== 關 ===")
config.STUDENT_LIVE = False
check("SIG_STUDENT_LIVE=0 → enabled False、busy False", not student_live.enabled() and not student_live.busy(NOW[0]))
config.STUDENT_LIVE = True

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
