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
# 10-23 DAN 第一張跟單（3860767713_2766）：市價 BUY、冇入場區、SL 4005、TP1 4015、現價 4014.48 → TP1 只剩 0.52 而 SL 差 9.5
_dan = {"side": "BUY", "sl": 4005.0, "tp": [4015.0, 4018.0, 4021.0], "entry_low": None, "entry_high": None, "order_type": "market"}
v, why = follower.entry_check(_dan, 4014.48)
check("市價單離 TP1 只剩 0.52 < SIG_FOLLOW_MIN_TP 2.0 → skip", v == "skip" and "0.52" in why, (v, why))
v, why = follower.entry_check(_dan, 4012.5)
check("市價單離 TP1 剩 2.5 ≥ 2.0 → ok", v == "ok", (v, why))
v, why = follower.entry_check({"side": "SELL", "sl": 4025.0, "tp": [4015.0], "entry_low": None, "entry_high": None, "order_type": "market"}, 4016.0)
check("空單鏡像：離 TP1 剩 1.0 < 2.0 → skip", v == "skip", (v, why))
# 有入場區：BUY 3999–4001、SL 3990（風險 10）、TP1 4015：現價 4011（離區中位 11 ≥ 1×風險）→ 走咗 skip；現價 4006 → 未入區 wait
_zone = {"side": "BUY", "sl": 3990.0, "tp": [4015.0], "entry_low": 3999.0, "entry_high": 4001.0}
v, why = follower.entry_check(_zone, 4011.0)
check("有入場區：已離區 ≥1×止損距離 → skip（走咗，同 S1 is_late）", v == "skip" and "走咗" in why, (v, why))
check("有入場區：離區 6 < 風險 10 → wait 等回入場區", follower.entry_check(_zone, 4006.0)[0] == "wait", follower.entry_check(_zone, 4006.0))
check("限價訊號剩餘空間用入場區中位計：區 3999–4001、TP1 4002（中位→TP1 2.0）現價 4001.5 → wait；TP1 4001.5（1.5）→ skip", follower.entry_check({"side": "BUY", "sl": 3990.0, "tp": [4002.0], "entry_low": 3999.0, "entry_high": 4001.0}, 4001.5)[0] == "wait" and follower.entry_check({"side": "BUY", "sl": 3990.0, "tp": [4001.5], "entry_low": 3999.0, "entry_high": 4001.0}, 4001.4)[0] == "skip", (follower.entry_check({"side": "BUY", "sl": 3990.0, "tp": [4002.0], "entry_low": 3999.0, "entry_high": 4001.0}, 4001.5), follower.entry_check({"side": "BUY", "sl": 3990.0, "tp": [4001.5], "entry_low": 3999.0, "entry_high": 4001.0}, 4001.4)))
check("CTC 執銀仔結構（TP1 4–6、SL 21）唔受影響：市價 BUY 4000、TP1 4005、SL 3979 → ok", follower.entry_check({"side": "BUY", "sl": 3979.0, "tp": [4005.0], "entry_low": None, "entry_high": None, "order_type": "market"}, 4000.0)[0] == "ok")
check("config：SIG_FOLLOW_MIN_TP 2.0", config.FOLLOW_MIN_TP == 2.0)
# 10-24 使用者「加『唔跟未到入場價』規則，倫敦時段都避」（CTC 5231；提案 §27）
_at = lambda h: (1792800000 // 86400) * 86400 + h * 3600 + 600          # 某日 UTC h:10
check("config：預設 CTC 唔跟未到入場價（tol 0.3）、避 07–12 UTC", config.FOLLOW_SKIP_UNREACHED_CHANNELS == ("5231",) and config.FOLLOW_UNREACHED_TOL == 0.3
      and follower.avoid_hours("5231") == (7, 12) and follower.avoid_hours("7713") is None and follower.avoid_hours("3996305231") == (7, 12))
_ctc = {"ch": "3996305231", "side": "BUY", "sl": 3980.0, "tp": [4006.0, 4012.0], "entry_low": 4000.0, "entry_high": 4000.0}
v, why = follower.entry_check(_ctc, 3999.5, _at(3))
check("CTC BUY 入場 4000、現價 3999.5（反向 0.5 ≥ 0.3）→ skip 未到入場價", v == "skip" and "未到入場價" in why, (v, why))
check("CTC 現價 3999.8（反向 0.2 < 0.3）→ ok（±點差容許）", follower.entry_check(_ctc, 3999.8, _at(3))[0] == "ok", follower.entry_check(_ctc, 3999.8, _at(3)))
check("CTC 現價 4001.5（已走 1.5）→ wait 等回入場區（規則只管反向）", follower.entry_check(_ctc, 4001.5, _at(3))[0] == "wait", follower.entry_check(_ctc, 4001.5, _at(3)))
_ctc_sell = {**_ctc, "side": "SELL", "sl": 4020.0, "tp": [3994.0, 3988.0]}
check("CTC SELL 鏡像：現價 4000.5（反向 0.5）→ skip；3999.0（已走）→ wait", follower.entry_check(_ctc_sell, 4000.5, _at(3))[0] == "skip" and follower.entry_check(_ctc_sell, 3999.0, _at(3))[0] == "wait")
_dan_zone = {"ch": "3860767713", "side": "BUY", "sl": 3990.0, "tp": [4003.0, 4006.0, 4009.0], "entry_low": 3999.0, "entry_high": 4001.0}
check("DAN（唔喺名單）現價 3996 反向 4 → 仍然 wait 等入區（規則唔適用）", follower.entry_check(_dan_zone, 3996.0, _at(3))[0] == "wait", follower.entry_check(_dan_zone, 3996.0, _at(3)))
v, why = follower.entry_check(_ctc, 4000.0, _at(7))
check("CTC 07:10 UTC 收到 → skip 時段", v == "skip" and "07–12" in why, (v, why))
check("CTC 11:10 skip、12:10 ok、06:10 ok", follower.entry_check(_ctc, 4000.0, _at(11))[0] == "skip" and follower.entry_check(_ctc, 4000.0, _at(12))[0] == "ok" and follower.entry_check(_ctc, 4000.0, _at(6))[0] == "ok")
check("DAN 08:10 唔受時段規則影響", follower.entry_check(_dan_zone, 4000.0, _at(8))[0] == "ok", follower.entry_check(_dan_zone, 4000.0, _at(8)))
check("冇 ch 嘅舊測試訊號：兩條規則都唔觸發", follower.entry_check({"side": "BUY", "sl": 3990, "tp": [4005], "entry_low": 3999, "entry_high": 4001}, 3995.0, _at(8))[0] == "wait")
_old = config.FOLLOW_AVOID_HOURS; config.FOLLOW_AVOID_HOURS = "5231:22-02,7713:13-14"
check("avoid_hours 跨午夜 22–02 同多頻道解析", follower.in_avoid_hours("5231", _at(23)) and follower.in_avoid_hours("5231", _at(1)) and not follower.in_avoid_hours("5231", _at(2)) and follower.avoid_hours("7713") == (13, 14))
config.FOLLOW_AVOID_HOURS = ""; check("SIG_FOLLOW_AVOID_HOURS 空＝關", follower.avoid_hours("5231") is None and not follower.in_avoid_hours("5231", _at(8)))
config.FOLLOW_AVOID_HOURS = _old
check("status JSON 有 skip_unreached_channels／unreached_tol／avoid_hours", follower.status()["skip_unreached_channels"] == ["5231"] and follower.status()["avoid_hours"].get("5231") == (7, 12))

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

print("=== 逐級鎖（使用者 10-23「真」：DAN 7713 出場改逐級鎖，CTC 維持 TP1）===")
config.EXECUTE = True
config.FOLLOW_CHANNELS = ("5231", "7713"); config.FOLLOW_LADDER_CHANNELS = ("7713",)
check("exit_mode：7713 ladder、5231 tp1", follower.exit_mode("3860767713") == "ladder" and follower.exit_mode("5231") == "tp1")
_o = {"side": "BUY", "tps": [4015.0, 4018.0, 4021.0, 4024.0, 4027.0, 4030.0]}
_p = {"entry": 4012.2, "stop": 4005.0, "target": 4030.0}
check("ladder_stop：未到 TP1 → 唔郁", follower.ladder_stop(_o, _p, 4014.9)[0] is None)
check("ladder_stop：到 TP1 → 保本（入場價）", follower.ladder_stop(_o, _p, 4015.0) == (4012.2, 0, "保本"))
check("ladder_stop：到 TP2 → 鎖 TP1", follower.ladder_stop(_o, _p, 4018.4) == (4015.0, 1, "鎖 TP1"))
check("ladder_stop：到 TP3 → 鎖 TP2；回落到 TP2 以下唔放鬆", follower.ladder_stop(_o, {**_p, "stop": 4015.0}, 4021.1)[0] == 4018.0 and follower.ladder_stop(_o, {**_p, "stop": 4018.0}, 4019.0)[0] is None)
check("ladder_stop：現止損已 ≥ 鎖位 → 唔郁", follower.ladder_stop(_o, {**_p, "stop": 4012.2}, 4016.0)[0] is None)
_os = {"side": "SELL", "tps": [3985.0, 3982.0, 3979.0]}
check("ladder_stop 空倉鏡像：到 TP2 → 鎖 TP1 3985", follower.ladder_stop(_os, {"entry": 3988.0, "stop": 3994.0, "target": 3979.0}, 3981.9) == (3985.0, 1, "鎖 TP1"))
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
put_signal("7713_9", lo=None, hi=None, sl=4005, tp=(4015, 4018, 4021, 4024, 4027, 4030), ch="7713", order_type="market")
st, d = hb(20, 4012)
check("DAN 市價單：開倉指令 TP 掛最後一級 4030、SL 4005；order 記 exit=ladder、tps 六級", d["cmd_text"].startswith("open|BUY|0.01|sl=4005.00|tp=4030.00|magic=932") and fstate()["orders"][-1]["exit"] == "ladder" and len(fstate()["orders"][-1]["tps"]) == 6, (d["cmd_text"], fstate()["orders"][-1]))
cid = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 901}), content_type="application/json")
POS = [{"ticket": 901, "side": "BUY", "entry": 4012.2, "lots": 0.01, "sl": 4005.0, "tp": 4030.0, "open_time": T0 + 20 * 60}]
st, d = hb(21, 4013.5, positions=POS)
check("有倉未到 TP1 → 唔排 modify", d["cmd_text"] == "" and "未到 TP1" in d["message"], d)
st, d = hb(22, 4015.2, positions=POS)
check("到 TP1 → modify sl=4012.20（保本）tp=4030.00，id 前綴 f", d["cmd_text"].startswith("modify|all|sl=4012.20|tp=4030.00|magic=932|id=f") and "保本" in d["message"] or "TP1" in d["message"], d)
mid = d["cmd_text"].split("id=")[1]
st, d = hb(23, 4016.0, positions=POS)
check("modify 未 ack → 唔重複排", d["cmd_text"].count("modify") == 1 and "等 EA" in d["message"], d)
client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": mid, "ok": True}), content_type="application/json")
POS2 = [{**POS[0], "sl": 4012.2}]
st, d = hb(24, 4016.5, positions=POS2)
check("ack 後 EA 回報 sl=4012.2，價 4016.5（仍 TP1 級）→ 唔再排", d["cmd_text"] == "" and "已 ≥ 鎖位" in d["message"], d)
st, d = hb(25, 4018.6, positions=POS2)
check("到 TP2 → modify sl=4015.00（鎖 TP1）", d["cmd_text"].startswith("modify|all|sl=4015.00|tp=4030.00"), d)
mid2 = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": mid2, "ok": True}), content_type="application/json")
POS3 = [{**POS[0], "sl": 4015.0}]
st, d = hb(26, 4016.2, positions=POS3)
check("回落到 TP1–TP2 之間 → 唔放鬆（止損留 4015）", d["cmd_text"] == "" and "已 ≥ 鎖位" in d["message"], d)
check("order.ladder 記最後鎖位 k=1 sl=4015", fstate()["orders"][-1]["ladder"]["k"] == 1 and fstate()["orders"][-1]["ladder"]["sl"] == 4015.0, fstate()["orders"][-1].get("ladder"))
# CTC 仍然 TP1 全平
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
put_signal("5231_9", lo=None, hi=None, sl=3979, tp=(4005, 4010), ch="5231", order_type="market")
st, d = hb(27, 4000)
check("CTC 市價單仍然 TP1 全平（tp=4005.00）、exit=tp1", d["cmd_text"].startswith("open|BUY|0.01|sl=3979.00|tp=4005.00") and fstate()["orders"][-1]["exit"] == "tp1", d["cmd_text"])
cid = d["cmd_text"].split("id=")[1]
client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 902}), content_type="application/json")
st, d = hb(28, 4003.0, positions=[{"ticket": 902, "side": "BUY", "entry": 4000.2, "lots": 0.01, "sl": 3979.0, "tp": 4005.0, "open_time": T0 + 27 * 60}])
check("CTC 有倉：唔經逐級鎖、唔 modify", d["cmd_text"] == "" and d["message"] == "有倉（SL／TP 伺服器端）", d)
js = client.get("/?format=json").get_json()
check("JSON follow.exit 每頻道模式", js["follow"]["exit"] == {"5231": "tp1", "7713": "ladder"} and js["follow"]["ladder_channels"] == ["7713"], js["follow"].get("exit"))
config.FOLLOW_CHANNELS = ("5231",); config.FOLLOW_LADDER_CHANNELS = ()


print("=== [R348] 數據封鎖：收到開倉訊號唔跟、記 skipped_data；事件過後照跟 ===")
import data_block as _db, time as _time
def _iso(ts): return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(ts))
_cfg_db = config.DATA_BLOCK_HOURS; config.DATA_BLOCK_HOURS = 4.0
FAKE["xau/sig/signals/recent.json"] = ("[]", 1); FAKE["xau/sig/follow/state.json"] = (json.dumps(follower.empty_state()), 1)
_t = T0 + 40 * 60; NOW[0] = _t
FAKE["ops/us_data_calendar.json"] = (json.dumps({"updated_utc": _iso(_t - 3600), "block_hours": 4, "events": [{"t": _iso(_t + 3600), "title": "FOMC", "src": "manual"}]}), 1)
_db._cache.update(ts=0, doc=None, error=None)
put_signal("5231_40", lo=None, hi=None, sl=3979, tp=(4005,), ch="5231", order_type="market")
st, d = hb(40, 4000)
_fs = fstate()
check("封鎖中：市價訊號唔跟、cmd_text 空、記 skipped_data、sid 入 used", d["cmd_text"] == "" and (_fs.get("skipped_data") or [{}])[-1].get("sid") == "5231_40" and "5231_40" in _fs["used"] and (_fs.get("data_block") or {}).get("title") == "FOMC", (d, _fs.get("skipped_data")))
js = client.get("/?format=json").get_json()
check("JSON follow.data_block／skipped_data", (js["follow"].get("data_block") or {}).get("title") == "FOMC" and len(js["follow"].get("skipped_data") or []) == 1, js["follow"].get("data_block"))
FAKE["ops/us_data_calendar.json"] = (json.dumps({"updated_utc": _iso(_t - 3600), "block_hours": 4, "events": [{"t": _iso(_t - 60), "title": "FOMC", "src": "manual"}]}), 2)
_db._cache.update(ts=0, doc=None, error=None); NOW[0] = T0 + 41 * 60
put_signal("5231_41", lo=None, hi=None, sl=3979, tp=(4005,), ch="5231", order_type="market")
st, d = hb(41, 4000)
check("事件過後：新訊號照跟", d["cmd_text"].startswith("open|BUY|") and fstate().get("data_block") is None, d["cmd_text"])
config.DATA_BLOCK_HOURS = _cfg_db; FAKE.pop("ops/us_data_calendar.json", None); _db._cache.update(ts=0, doc=None, error=None)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
