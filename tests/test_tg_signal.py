"""[R264] 外部 Telegram 頻道訊號：解析正規化、下單前檢查、去重、確認 bot 權限、只送一次。"""
import json, os, sys, types

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
os.environ.update(TG_SIGNAL_ORDER_ENABLED="1", TG_SIGNAL_CHAT_ID="555", TG_SIGNAL_WEBHOOK_SECRET="sec",
                  TG_SIGNAL_BOT_TOKEN="bot", BROKER_API_URL="https://broker.example/hook")
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

import main
import json
OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")
client = main.app.test_client()

def post(body):
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def press(data, user=555, chat=555, secret="sec", cq_id="q1"):
    body = {"update_id": 1, "callback_query": {"id": cq_id, "from": {"id": user}, "data": data,
            "message": {"message_id": 77, "chat": {"id": chat}}}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
    r = client.post("/?tg=signal", data=json.dumps(body), content_type="application/json", headers=headers)
    return r.status_code, r.get_json()

TG_CALLS, BROKER = [], []
main.tgs_api = lambda method, body: TG_CALLS.append((method, body)) or {"ok": True, "result": {"message_id": 77}}
class _Resp:
    ok, status_code, text = True, 200, '{"ok":true}'
def fake_post(url, json=None, timeout=None):
    BROKER.append((url, json)); return _Resp()
main.requests.post = fake_post

def set_price(close, age=0):
    ts = main.fmt_utc(main.now_ts() - age)
    main.gcs_write_text(main.WEBHOOK_LOG_FILE, json.dumps([{"timestamp_utc": ts, "payload": {"m1_ohlc": {"close": close}}}]))

BUY = {"kind": "new_signal", "symbol": "XAUUSD", "side": "BUY", "entry_low": 2648, "entry_high": 2650,
       "sl": 2640, "tp": [2660, 2680], "confidence": 0.9, "analysis": "買入黃金"}
def analyzed(sig):
    main.tgs_analyze = lambda text, reply_text=None, channel=None: (main.tgs_normalize(sig), None)

print("=== tgs_normalize ===")
n = main.tgs_normalize({"kind": "NEW_SIGNAL", "side": "long", "entry_low": "2650", "entry_high": "2645", "sl": "x",
                        "tp": ["2660", None, -1], "symbol": "gold"})
check("LONG→BUY、入場區排序、壞數字→None、TP 濾走無效", n["side"] == "BUY" and (n["entry_low"], n["entry_high"]) == (2645, 2650)
      and n["sl"] is None and n["tp"] == [2660] and n["kind"] == "new_signal", n)
check("未知 kind → other", main.tgs_normalize({"kind": "spam"})["kind"] == "other")
check("parse_ai_json 容 ```json", main.tgs_parse_ai_json('```json\n{"kind":"other"}\n```') == {"kind": "other"})

print("=== tgs_check ===")
s = main.tgs_normalize(BUY)
ok, why, plan = main.tgs_check(s, 2649.5, 10)
check("正常 BUY：止損距離 9.5、止賺取第一個 10.5", ok and plan == {"side": "BUY", "sl_distance": 9.5, "tp_distance": 10.5}, (why, plan))
check("冇止損 → 拒", not main.tgs_check({**s, "sl": None}, 2649.5, 10)[0])
check("非黃金 → 拒", not main.tgs_check({**s, "symbol": "EURUSD"}, 2649.5, 10)[0])
check("GOLD 別名接受", main.tgs_check({**s, "symbol": "GOLD"}, 2649.5, 10)[0])
check("價格過舊 → 拒", not main.tgs_check(s, 2649.5, 9999)[0])
check("偏離入場區 > 5 → 拒", not main.tgs_check(s, 2656.0, 10)[0])
check("止損已觸發 → 拒", not main.tgs_check({**s, "entry_low": None, "entry_high": None}, 2639.0, 10)[0])
check("止損太遠 → 拒", not main.tgs_check({**s, "sl": 2600}, 2649.5, 10)[0])
check("TP 全部錯邊 → 拒", not main.tgs_check({**s, "tp": [2645], "entry_low": None, "entry_high": None}, 2649.5, 10)[0])
sell = main.tgs_normalize({**BUY, "side": "SELL", "sl": 2658, "tp": [2630]})
ok, why, plan = main.tgs_check(sell, 2649.0, 10)
check("SELL 距離方向正確", ok and plan["sl_distance"] == 9.0 and plan["tp_distance"] == 19.0, (why, plan))
check("update 唔可以下單", not main.tgs_check({**s, "kind": "update"}, 2649.5, 10)[0])

print("=== action=tg_signal ===")
check("冇權杖 → 403", post({"action": "tg_signal", "text": "x"})[0] == 403)
set_price(2649.5); analyzed(BUY)
st, d = post({"action": "tg_signal", "token": "tok", "channel": "GoldVIP", "channel_id": -100123, "msg_id": 42,
              "text": "BUY GOLD 2650-2648 SL 2640 TP 2660/2680"})
check("新訊號 → stored、可確認、已通知", st == 200 and d["confirmable"] and d["notified"] and d["sid"] == "100123_42", d)
send = [b for m, b in TG_CALLS if m == "sendMessage"][-1]
check("訊息附兩個按鈕", [x["callback_data"] for x in send["reply_markup"]["inline_keyboard"][0]] == ["tgs:ok:100123_42", "tgs:no:100123_42"])
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 42, "text": "BUY again"})
check("同一則訊息 → duplicate（唔再分析）", d["status"] == "duplicate", d)
check("tg_signal 唔入 webhook 紀錄（價格來源唔會被擠走）",
      all("text" not in (r.get("payload") or {}) for r in main.gcs_read_json(main.WEBHOOK_LOG_FILE, [])))

print("=== 確認 bot ===")
check("冇 secret 標頭 → 403", press("tgs:ok:100123_42", secret=None)[0] == 403)
check("錯 secret → 403", press("tgs:ok:100123_42", secret="bad")[0] == 403)
check("非白名單使用者 → forbidden，未送單", press("tgs:ok:100123_42", user=999)[1]["status"] == "forbidden" and not BROKER)
st, d = press("tgs:ok:100123_42")
check("確認 → 送單一次", d["status"] == "sent" and len(BROKER) == 1, d)
order = BROKER[0][1]
check("封包：BUY 0.01 手、止損 9.50、止賺 10.50、冇移動止損／保本、comment=TG",
      order["action"] == "BUY" and order["size"] == "0.01" and order.get("sl_distance_price") == "9.50"
      and order.get("tp_distance_price") == "10.50" and order["comment"] == "TG"
      and not any(k.startswith(("ts_", "breakeven")) for k in order), order)
st, d = press("tgs:ok:100123_42", cq_id="q2")
check("再按一次 → duplicate，唔會再送", d["status"] == "duplicate" and len(BROKER) == 1, d)

print("=== 略過／逾時／硬鎖／唔確認嘅情況 ===")
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 43, "text": "BUY GOLD"})
st, d = press("tgs:no:100123_43")
check("略過 → skipped、冇送單", d["status"] == "skipped" and len(BROKER) == 1, d)
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 44, "text": "BUY GOLD"})
main.tgs_save("100123_44", lambda r: ({**r, "received_ts": r["received_ts"] - 10000}, None))
check("逾時 → expired、冇送單", press("tgs:ok:100123_44")[1]["status"] == "expired" and len(BROKER) == 1)
post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 45, "text": "BUY GOLD"})
main.gcs_write_text(main.GATE_STATE_FILE, json.dumps({"hard_lock": {"reason": "管理員緊急鎖死", "until_ts": None}}))
check("確認時電閘硬鎖 → rejected", press("tgs:ok:100123_45")[1]["status"] == "rejected" and len(BROKER) == 1)
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 46, "text": "BUY GOLD"})
check("分析時已硬鎖 → 唔提供按鈕", not d["confirmable"], d)
main.gcs_write_text(main.GATE_STATE_FILE, json.dumps({}))
analyzed({"kind": "update", "update_action": "止損移到保本"})
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 47, "text": "Move SL to BE"})
check("管理指示 → 只通知、冇按鈕", d["notified"] and not d["confirmable"], d)
analyzed({"kind": "other"}); n_before = len(TG_CALLS)
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 48, "text": "Good morning"})
check("閒聊 → 唔發 Telegram", not d["notified"] and len(TG_CALLS) == n_before, d)
main.TG_SIGNAL_ORDER_ENABLED = False; analyzed(BUY)
st, d = post({"action": "tg_signal", "token": "tok", "channel_id": -100123, "msg_id": 49, "text": "BUY GOLD"})
check("TG_SIGNAL_ORDER_ENABLED=0 → 只分析、冇按鈕", not d["confirmable"] and d["notified"], d)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
