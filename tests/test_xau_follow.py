"""訊號書跟單（magic 932；使用者 10-22 批「CTC 0.01 手執銀仔落 demo」，IDEAS #123）：只限 SIG_FOLLOW_CHANNELS、TP1 全平、原 SL；
市價單即入、限價單等入區、過咗 TP1 略過；一次一張；control／階梯／EA 唔准就唔開；回報按 id 前綴 f；SIG_DECIDE=0 都做到。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5")
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
import main as xau, config, follower   # noqa: E402

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

def hb(i, close, magic=932, positions=None, extra=None):
    t = T0 + i * 60; NOW[0] = t + 5
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": 0,
            "realized_total": 0, "bots_daily_pnl": 0, "bots_floating": 0, "bots_realized_total": 0, "magic": magic, "positions": positions or [],
            "trade_allowed": {"terminal": True, "ea": True, "account": True},
            "m1_ohlc": {"time": t, "open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "is_new_bar": True},
            "m15_ohlc": {"time": T0 + (i // 15) * 900, "open": close, "high": close + 1, "low": close - 1, "close": close}, **(extra or {})}
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def put_signal(sid, side="BUY", lo=3999, hi=4001, sl=3990, tp=(4005, 4010), ch="5231", order_type=None, left_min=20):
    rows = json.loads(FAKE.get("xau/sig/signals/recent.json", ("[]", 0))[0])
    rows.append({"sid": sid, "kind": "new_signal", "status": "valid", "side": side, "entry_low": lo, "entry_high": hi, "sl": sl, "tp": list(tp),
                 "msg_ts": NOW[0] - 60, "valid_until_ts": NOW[0] + left_min * 60, "ch": ch, "order_type": order_type})
    FAKE["xau/sig/signals/recent.json"] = (json.dumps(rows), 1)
def fstate(): return json.loads(FAKE["xau/sig/follow/state.json"][0])

print("=== 設定 ===")
check("跟單開啟：頻道尾 4 位、magic 932、0.01 手", follower.enabled() and config.FOLLOW_CHANNELS == ("5231",) and config.FOLLOW_MAGIC == 932 and config.FOLLOW_LOTS == 0.01)
check("entry_check 純函數：市價單 ok、限價等、過 TP1 略過、止損錯邊略過",
      follower.entry_check({"side": "BUY", "sl": 3990, "tp": [4005], "entry_low": 3999, "entry_high": 4001, "order_type": "market"}, 4003)[0] == "ok"
      and follower.entry_check({"side": "BUY", "sl": 3990, "tp": [4005], "entry_low": 3999, "entry_high": 4001}, 4003)[0] == "wait"
      and follower.entry_check({"side": "BUY", "sl": 3990, "tp": [4005], "entry_low": 3999, "entry_high": 4001}, 4000.5)[0] == "ok"
      and follower.entry_check({"side": "BUY", "sl": 3990, "tp": [4005], "entry_low": 3999, "entry_high": 4001}, 4005.2)[0] == "skip"
      and follower.entry_check({"side": "SELL", "sl": 3990, "tp": [3985], "entry_low": 3999, "entry_high": 4001}, 4000)[0] == "skip")

print("=== 分流 ===")
st, d = hb(1, 4000, magic=931)
check("SIG_DECIDE=0：931 心跳仍然 ignored（S1 未開）", d.get("status") == "ignored", d)
st, d = hb(2, 4000)
check("932 心跳 → 跟單 monitoring、冇指令", st == 200 and d.get("book") == "follow" and d.get("cmd_text") == "" and "冇可跟訊號" in d.get("message", ""), d)
check("跟單戶口快照寫入 follow/account.json", "xau/sig/follow/account.json" in FAKE)

print("=== 市價單訊號 → 即刻開 0.01、SL 原 SL、TP＝TP1 ===")
put_signal("5231_1", order_type="market", lo=3999, hi=4001, sl=3990, tp=(4005, 4010))
st, d = hb(3, 4003)
check("排咗 open 指令：BUY 0.01 sl=3990 tp=4005 magic=932 id=f…", d["cmd_text"].startswith("open|BUY|0.01|sl=3990.00|tp=4005.00|magic=932|id=f"), d["cmd_text"])
o = fstate()["orders"][-1]
check("紀錄：sid、頻道尾號、入場依據市價單", o["sid"] == "5231_1" and o["ch"] == "5231" and o["entry"] == "市價單" and o["applied"].startswith("open|"), o)
st, d = hb(4, 4003)
check("未回報前唔會重複排", d["cmd_text"].count("open|") == 1 and "等 EA 回報" in d["message"], d)
cid = o["id"]
r = client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 777}), content_type="application/json")
check("cmd_ack（id 前綴 f）→ 跟單狀態記 ticket", r.get_json()["status"] == "acked" and fstate()["orders"][-1]["ticket"] == 777, fstate()["orders"][-1])
st, d = hb(5, 4003, positions=[{"ticket": 777, "side": "BUY", "entry": 4003.3, "lots": 0.01, "sl": 3990, "tp": 4005, "open_time": T0 + 3 * 60 + 10800}])
check("有倉 → 唔開新倉、cmd_text 空", d["cmd_text"] == "" and "有倉" in d["message"], d)
put_signal("5231_2", order_type="market")
st, d = hb(6, 4003, positions=[{"ticket": 777, "side": "BUY", "entry": 4003.3, "lots": 0.01, "sl": 3990, "tp": 4005, "open_time": T0 + 3 * 60 + 10800}])
check("有倉時嚟新訊號都唔開", d["cmd_text"] == "", d)

print("=== 限價單：等入區；過 TP1 略過；其他頻道唔跟 ===")
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
put_signal("5231_3", lo=3999, hi=4001, sl=3990, tp=(4005,))
st, d = hb(7, 4004)
check("現價 4004 喺區外 → 等（唔排指令、唔標 used）", d["cmd_text"] == "" and "等現價入入場區" in d["message"] and "5231_3" not in fstate()["used"], d)
st, d = hb(8, 4001.2)
check("現價入區（±點差）→ 開倉", d["cmd_text"].startswith("open|BUY|0.01|sl=3990.00|tp=4005.00|magic=932"), d)
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
put_signal("5231_4", lo=3999, hi=4001, sl=3990, tp=(4005,))
st, d = hb(9, 4006)
check("收到時已過 TP1 → 略過並標 used，之後唔再試", d["cmd_text"] == "" and "5231_4" in fstate()["used"], d)
put_signal("7713_9", order_type="market", ch="7713")
st, d = hb(10, 4000)
check("DAN（7713）訊號唔跟", d["cmd_text"] == "" and "冇可跟訊號" in d["message"], d)

print("=== 風控：control 非 RUN、階梯、EA 唔准 ===")
put_signal("5231_5", order_type="market")
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "PAUSE", "set_by": "user", "principal_hkd": 27000.0}), 2)
st, d = hb(11, 4000)
check("control PAUSE → 唔開", d["cmd_text"] == "" and "模式 PAUSE" in d["message"], d)
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 3)
st, d = hb(12, 4000, extra={"bots_daily_pnl": -1000})
check("戶口總階梯日蝕 −3.7% → Ⓑ／Ⓓ 唔開", d["cmd_text"] == "" and "階梯" in d["message"], d)
st, d = hb(13, 4000, extra={"trade_allowed": {"terminal": True, "ea": False, "account": True}})
check("EA 唔准交易 → 唔開", d["cmd_text"] == "" and "未准交易" in d["message"], d)
st, d = hb(14, 4000)
check("解除後開倉", d["cmd_text"].startswith("open|BUY|0.01"), d)

print("=== 頁面／JSON ===")
js = client.get("/?format=json").get_json()
check("status JSON 有 follow（magic、頻道、orders）", js.get("follow", {}).get("magic") == 932 and js["follow"]["channels"] == ["5231"] and len(js["follow"]["orders"]) >= 1, js.get("follow"))
html = client.get("/").get_data(as_text=True)
check("頁面有跟單區", "跟單（magic 932" in html and "5231_5" in html)

print("=== 紙上（XAU_EXECUTE=0）===")
config.EXECUTE = False
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
put_signal("5231_6", order_type="market")
st, d = hb(15, 4000)
check("紙上：記 order applied=paper、cmd_text 空", d["cmd_text"] == "" and fstate()["orders"][-1]["applied"] == "paper", d)
config.EXECUTE = True

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
