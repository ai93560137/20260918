"""[R290] 天覆陣入面嘅 Telegram 頻道訊號：解析正規化、下單前檢查、去重、確認 bot 權限、只排一次指令、影子模式唔送 EA。
由 main.py（zhuge-risk-manager）搬入 xau/，分析改用 Claude（測試用假 brain）。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", TG_SIGNAL_ORDER_ENABLED="1", TG_SIGNAL_CHAT_ID="555",
                  TG_SIGNAL_WEBHOOK_SECRET="sec", TG_SIGNAL_BOT_TOKEN="bot", ANTHROPIC_API_KEY="x", GATE_MODEL="")
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

import main as xau, config, tgsignal, market   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [1792599000.0]
market.now_ts = lambda: NOW[0]
tgsignal.now_ts = lambda: NOW[0]
xau.now_ts = lambda: NOW[0]

def post(body):
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def press(data, user=555, chat=555, secret="sec", cq_id="q1"):
    body = {"update_id": 1, "callback_query": {"id": cq_id, "from": {"id": user}, "data": data,
            "message": {"message_id": 77, "chat": {"id": chat}}}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
    r = client.post("/?tg=signal", data=json.dumps(body), content_type="application/json", headers=headers)
    return r.status_code, r.get_json()

TG_CALLS = []
tgsignal.tg_api = lambda method, body: TG_CALLS.append((method, body)) or {"ok": True, "result": {"message_id": 77}}

def set_price(close, age=0):
    FAKE["xau/m1.json"] = (json.dumps([{"time": int(NOW[0] - age - 60), "open": close, "high": close, "low": close, "close": close}]), 1)

BUY = {"kind": "new_signal", "symbol": "XAUUSD", "side": "BUY", "entry_low": 2648, "entry_high": 2650,
       "sl": 2640, "tp": [2660, 2680], "confidence": 0.9, "analysis": "買入黃金"}
def analyzed(sig):
    tgsignal.analyze = lambda text, reply_text=None, channel=None: (tgsignal.normalize(sig), None)
FAKE["xau/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user"}), 1)

print("=== normalize ===")
n = tgsignal.normalize({"kind": "NEW_SIGNAL", "side": "long", "entry_low": "2650", "entry_high": "2645", "sl": "x", "tp": ["2660", None, -1], "symbol": "gold"})
check("LONG→BUY、入場區排序、壞數字→None、TP 濾走無效", n["side"] == "BUY" and (n["entry_low"], n["entry_high"]) == (2645, 2650) and n["sl"] is None and n["tp"] == [2660] and n["kind"] == "new_signal", n)
check("未知 kind → other", tgsignal.normalize({"kind": "spam"})["kind"] == "other")

print("=== check ===")
s = tgsignal.normalize(BUY)
ok, why, plan = tgsignal.check(s, 2649.5, 10)
check("正常 BUY：止損 2640、止賺取第一個 2660", ok and plan["stop"] == 2640 and plan["target"] == 2660 and plan["sl_distance"] == 9.5, (why, plan))
check("冇止損 → 拒", not tgsignal.check({**s, "sl": None}, 2649.5, 10)[0])
check("非黃金 → 拒", not tgsignal.check({**s, "symbol": "EURUSD"}, 2649.5, 10)[0])
check("價格過舊 → 拒", not tgsignal.check(s, 2649.5, 9999)[0])
check("偏離入場區 > 5 → 拒", not tgsignal.check(s, 2656.0, 10)[0])
check("止損已觸發 → 拒", not tgsignal.check({**s, "entry_low": None, "entry_high": None}, 2639.0, 10)[0])
check("止損太遠 → 拒", not tgsignal.check({**s, "sl": 2600}, 2649.5, 10)[0])
check("TP 全部錯邊 → 拒", not tgsignal.check({**s, "tp": [2645], "entry_low": None, "entry_high": None}, 2649.5, 10)[0])
sell = tgsignal.normalize({**BUY, "side": "SELL", "sl": 2658, "tp": [2630]})
ok, why, plan = tgsignal.check(sell, 2649.0, 10)
check("SELL 方向正確", ok and plan["stop"] == 2658 and plan["target"] == 2630, (why, plan))
check("update 唔可以下單", not tgsignal.check({**s, "kind": "update"}, 2649.5, 10)[0])

print("=== action=tg_signal ===")
check("冇權杖 → 403", post({"action": "tg_signal", "text": "x"})[0] == 403)
set_price(2649.5); analyzed(BUY)
st, d = post({"action": "tg_signal", "token": "tok", "channel": "GoldVIP", "channel_id": -100123, "msg_id": 42, "text": "BUY GOLD 2650-2648 SL 2640 TP 2660/2680"})
check("新訊號 → stored、可確認、已通知", st == 200 and d["confirmable"] and d["notified"] and d["sid"] == "100123_42", d)
send = [b for m, b in TG_CALLS if m == "sendMessage"][-1]
check("訊息附兩個按鈕、影子模式提示", [x["callback_data"] for x in send["reply_markup"]["inline_keyboard"][0]] == ["tgs:ok:100123_42", "tgs:no:100123_42"] and "影子模式" in send["text"])
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 42, "text": "BUY again"})
check("同一則訊息 → duplicate", d["status"] == "duplicate", d)
check("紀錄喺 xau/tg_signals/", "xau/tg_signals/100123_42.json" in FAKE)

print("=== 確認 bot ===")
check("冇 secret 標頭 → 403", press("tgs:ok:100123_42", secret=None)[0] == 403)
check("錯 secret → 403", press("tgs:ok:100123_42", secret="bad")[0] == 403)
check("非白名單使用者 → forbidden", press("tgs:ok:100123_42", user=999)[1]["status"] == "forbidden")
st, d = press("tgs:ok:100123_42")
state = json.loads(FAKE["xau/state.json"][0])
check("確認 → 排一條 open 指令（影子：queued_shadow）", d["status"] == "queued_shadow" and len(state["pending_cmds"]) == 1 and state["pending_cmds"][0]["text"].startswith("open|BUY|0.01|sl=2640.00|tp=2660.00|magic=921|note=訊號S1|id=") and state["pending_cmds"][0]["tag"] == "tg:100123_42", (d, state.get("pending_cmds")))
st, d = press("tgs:ok:100123_42", cq_id="q2")
check("再按一次 → duplicate，唔再排", d["status"] == "duplicate" and len(json.loads(FAKE["xau/state.json"][0])["pending_cmds"]) == 1, d)
hb = {"token": "tok", "action": "heartbeat", "equity": 1, "m1_ohlc": {"time": 1, "is_new_bar": False}}
st, d = post(hb)
check("影子模式：心跳 cmd_text 仍然空（指令唔會送到 EA）", d["cmd_text"] == "")
config.EXECUTE = True
st, d = post(hb)
check("實倉模式：心跳帶出 TG 指令", d["cmd_text"].startswith("open|BUY|0.01|sl=2640.00"), d)
config.EXECUTE = False

print("=== 略過／逾時／模式／唔確認嘅情況 ===")
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 43, "text": "BUY GOLD"})
st, d = press("tgs:no:100123_43")
check("略過 → skipped", d["status"] == "skipped", d)
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 44, "text": "BUY GOLD"})
tgsignal.save("100123_44", lambda r: ({**r, "received_ts": r["received_ts"] - 10000}, None))
check("逾時 → expired", press("tgs:ok:100123_44")[1]["status"] == "expired")
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 45, "text": "BUY GOLD"})
FAKE["xau/control.json"] = (json.dumps({"mode": "PAUSE", "set_by": "ladder", "reason": "日蝕"}), 2)
check("確認時模式 PAUSE → rejected", press("tgs:ok:100123_45")[1]["status"] == "rejected")
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 46, "text": "BUY GOLD"})
check("分析時已 PAUSE → 唔提供按鈕", not d["confirmable"], d)
FAKE["xau/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user"}), 3)
state = json.loads(FAKE["xau/state.json"][0]); state["position"] = {"side": 1}; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 47, "text": "BUY GOLD"})
check("天覆陣已有倉 → rejected（最多 1 張）", "已有倉位" in press("tgs:ok:100123_47")[1]["status"] or press("tgs:ok:100123_47", cq_id="q9")[1]["status"] in ("duplicate",) and "已有倉位" in json.loads(FAKE["xau/tg_signals/100123_47.json"][0])["result"])
state["position"] = None; FAKE["xau/state.json"] = (json.dumps(state), FAKE["xau/state.json"][1] + 1)
analyzed({"kind": "update", "update_action": "止損移到保本"})
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 48, "text": "Move SL to BE"})
check("管理指示 → 只通知、冇按鈕", d["notified"] and not d["confirmable"], d)
analyzed({"kind": "other"}); n_before = len(TG_CALLS)
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 49, "text": "Good morning"})
check("閒聊 → 唔發 Telegram", not d["notified"] and len(TG_CALLS) == n_before, d)
tgsignal.ORDER_ENABLED = False; analyzed(BUY)
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 50, "text": "BUY GOLD"})
check("TG_SIGNAL_ORDER_ENABLED=0 → 只分析、冇按鈕", not d["confirmable"] and d["notified"], d)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
