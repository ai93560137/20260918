"""學徒計劃階段 0／1（使用者 10-22 批）：特徵快照（snapshots/<sid>.json、lag_min／moved_usd）、規則學生（三條規則、60 分鐘冷卻、先寫 GCS）、
Claude 學生（XAU_SHADOW、時段、間隔、唔落單）、對答案（方向／入場區 ±3／交卷）、學生自己成績（DAN 結構 2R）、網頁／JSON。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="1", TG_SIGNAL_INGEST_SECRET="ingest-secret",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="0", SIG_REFERENCE_CHANNELS="3860767713", XAU_STUDENT="1", XAU_SHADOW="1",
                  XAU_SHADOW_HOURS_UTC="", XAU_SHADOW_INTERVAL_MIN="30", GATE_MODEL="claude-haiku-5-5")
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
import main as xau, config, signals, student, features, market   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [1792600000.0]
xau.now_ts = lambda: NOW[0]; signals.now_ts = lambda: NOW[0]; market.now_ts = lambda: NOW[0]; student.now_ts = lambda: NOW[0]
T0 = int(NOW[0]) - 200 * 60                      # 200 根 M1（UTC＝伺服器時間，offset 0）

def mk_bars(path):
    """V 形：前 100 根由 4010 跌到 4000（擺動低 4000 喺第 100 根），之後升返 4001.5；最後 15 根再跌 4 美元（rev15 → BUY）。"""
    bars = []
    for i in range(200):
        if i < 100: c = 4010 - i * 0.1
        elif i < 185: c = 4000 + (i - 100) * 0.03
        else: c = 4002.55 - (i - 185) * 0.3
        bars.append({"time": T0 + i * 60, "open": round(c + 0.05, 2), "high": round(c + 0.2, 2), "low": round(c - 0.2, 2), "close": round(c, 2)})
    return bars
M1 = mk_bars(None)
FAKE["xau/m1.json"] = (json.dumps(M1), 1)
FAKE["xau/m15.json"] = (json.dumps([{"time": b["t"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in features.agg([{**b, "t": b["time"]} for b in M1], 15)]), 1)
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 1)

print("=== features 純函數 ===")
bu = features.utc(M1, 0)
sw = features.swings(bu[-120:], "BUY")
check("擺動低搵到 ≈4000", any(abs(p - 3999.8) < 0.3 for p in sw), sw)
lv = features.levels(bu, NOW[0])
check("levels：冇前日數據 → None、唔爆", lv["prev_high"] is None and "day_open" in lv)
check("lag_in_zone：區入面最近一根", features.lag_in_zone(bu, NOW[0], 3997.0, 4001.0, 0.3) in (1, 2), features.lag_in_zone(bu, NOW[0], 3997.0, 4001.0, 0.3))
check("lag_in_zone：6 小時冇去過 → None", features.lag_in_zone(bu, NOW[0], 4100, 4102, 0.3) is None)
st_ = features.structure(4000.0, "BUY")
check("DAN 結構：BUY 入場區 3994–3998、SL 3990、TP 3999…4014", st_["entry_low"] == 3994 and st_["entry_high"] == 3998 and st_["sl"] == 3990 and st_["tp"][0] == 3999 and st_["tp"][-1] == 4014, st_)
cands = features.rule_candidates(M1, 0, NOW[0])
rules = {c["rule"]: c for c in cands}
check("rev15：最後 15 分鐘跌 ≥3 → BUY", rules.get("rev15", {}).get("side") == "BUY", cands)
check("swing：現價 1998.x 附近有擺動低 4000？（現價 3998.4 喺擺動低下面 → 唔算「後面」）", "swing" not in rules or rules["swing"]["side"] == "SELL", cands)
g = features.grade({"side": "BUY", "entry_low": 3994, "entry_high": 3998, "ts": NOW[0] - 600}, "BUY", 3997.0, NOW[0])
check("grade：方向中、入場區 ±3 中、提前 10 分鐘", g["dir"] and g["zone"] and g["lead_min"] == 10, g)
snap = features.snapshot(M1, [], 0, NOW[0], "BUY", 3997.0, 3991.0, [4000, 4003], 3998.4)
check("snapshot：有 sess／atr／擺動距離／lag／moved／move15／pos60", snap["sess"] in ("asia", "london", "ny", "late") and snap.get("atr1") and "d_swing_m1" in snap and snap["lag_min"] is not None and snap["moved_usd"] == 1.4 and snap["move15"] is not None and "pos60" in snap, snap)

print("=== 規則學生：觸發、冷卻、先寫 GCS ===")
fired = student.rule_tick(M1, 0, NOW[0])
check("有規則觸發、寫入 state 同日誌 jsonl", fired and "xau/sig/student/state.json" in FAKE and any(k.startswith("xau/sig/student/log/") for k in FAKE), [f["student"] for f in fired])
n1 = len(json.loads(FAKE["xau/sig/student/state.json"][0])["preds"])
NOW[0] += 60
fired2 = student.rule_tick(M1, 0, NOW[0])
check("1 分鐘後同一規則唔再觸發（60 分鐘冷卻）", not fired2 and len(json.loads(FAKE["xau/sig/student/state.json"][0])["preds"]) == n1, fired2)
NOW[0] += 3600
fired3 = student.rule_tick(M1, 0, NOW[0])
check("61 分鐘後可以再觸發", bool(fired3), fired3)
p0 = fired3[0]
check("判斷有 id／ts／入場區／SL／2R 目標／現價", p0["ts"] == NOW[0] and p0["entry_low"] < p0["entry_high"] and p0["sl"] and len(p0["tp"]) == 1 and p0["price"], p0)

print("=== Claude 學生 ===")
config.SHADOW = True; config.SHADOW_HOURS_UTC = ""          # 測試用：全日都問（env 空字串會退回預設時段）
class FakeBrain:
    def __init__(self): self.decision = {"action": "OPEN_SHORT", "stop_price": 4005, "target_price": 3990, "confidence": 0.7, "reason": "淡"}; self.calls = 0
    def decide(self, ctx): self.calls += 1; self.ctx = ctx; return {**self.decision, "_usage": {"in": 10, "out": 5, "model": "claude-opus-5-5"}, "_ms": 5}
FB = FakeBrain()
ctx = lambda: {"last_price": 3998.4, "signals": [{"sid": "x"}], "bars_m1": []}
p = student.claude_tick(FB, ctx, NOW[0])
check("Claude 學生：問一次、prompt 冇 signals、有 student_task", FB.calls == 1 and "signals" not in FB.ctx and "STUDENT MODE" in FB.ctx["student_task"], FB.ctx.keys())
check("OPEN_SHORT → SELL 判斷，入場區＝現價 ±2，記 cost", p["side"] == "SELL" and abs((p["entry_low"] + p["entry_high"]) / 2 - 3998.4) < 0.01 and p["cost_usd"] >= 0, p)
check("30 分鐘內唔再問", student.claude_tick(FB, ctx, NOW[0] + 600) is None and FB.calls == 1)
FB.decision = {"action": "HOLD", "stop_price": None, "target_price": None, "confidence": 0.5, "reason": "等"}
p2 = student.claude_tick(FB, ctx, NOW[0] + 1900)
check("31 分鐘後再問；HOLD 都記（outcome=hold）", FB.calls == 2 and p2["side"] is None and p2["outcome"] == "hold", p2)
config.SHADOW = False
check("XAU_SHADOW=0 → 唔問", student.claude_tick(FB, ctx, NOW[0] + 9000) is None and FB.calls == 2)
config.SHADOW = True
config.SHADOW_HOURS_UTC = "01-07,12-15"
check("時段判斷：03 UTC 入、09 UTC 唔入、12 入", student.in_shadow_hours(3 * 3600) and not student.in_shadow_hours(9 * 3600) and student.in_shadow_hours(12 * 3600 + 5))
config.SHADOW_HOURS_UTC = ""

print("=== 階段 0 快照＋對答案（參考頻道訊號到）===")
def parsed(sig):
    signals.parse = lambda text, reply_text=None: (signals.normalize(sig), None)
def send(body):
    data = json.dumps(body).encode(); ts = int(NOW[0])
    h = {"X-Sig-Ts": str(ts), "X-Sig-Signature": signals.sign("ingest-secret", ts, data)}
    r = client.post("/", data=data, content_type="application/json", headers=h); return r.status_code, r.get_json()
FAKE["xau/m1.json"] = (json.dumps([{**b, "time": b["time"] + int(NOW[0] - 1792600000.0)} for b in M1]), 2)    # 搬到依家
NOW[0] += 300                                               # 學生 5 分鐘前交咗卷（fired3：rev15 BUY；FB：SELL 4 分鐘前… 睇邊個啱）
parsed({"kind": "new_signal", "symbol": "XAUUSD", "side": "BUY", "entry_low": 3996, "entry_high": 3998, "sl": 3990, "tp": [4001, 4004, 4007], "confidence": 0.9, "analysis": "x"})
st, d = send({"action": "tg_signal", "channel_id": 3860767713, "msg_id": 501, "text": "sig", "date": market.fmt_utc(NOW[0]).replace(" ", "T") + "+00:00"})
snapf = "xau/sig/snapshots/3860767713_501.json"
check("DAN 訊號 → 快照檔存在、有 features／m1／m15、冇原文", st == 200 and snapf in FAKE and "features" in json.loads(FAKE[snapf][0]) and "text" not in json.loads(FAKE[snapf][0]), (st, d, [k for k in FAKE if "snap" in k]))
sdoc = json.loads(FAKE[snapf][0])
check("快照 features 有 agree／lag_min／moved_usd／擺動距離", "agree" in sdoc["features"] and "lag_min" in sdoc["features"] and "d_swing_m1" in sdoc["features"], sdoc["features"])
rows = json.loads(FAKE["xau/sig/signals/recent.json"][0])
check("recent.json 公開欄位有 lag_min／moved_usd", "lag_min" in rows[-1] and "moved_usd" in rows[-1], rows[-1])
gr = [k for k in FAKE if k.startswith("xau/sig/student/grades/")]
check("對答案已寫（grades jsonl＋scores.grade）", gr and "grade" in json.loads(FAKE["xau/sig/student/scores.json"][0]), list(FAKE))
sc = json.loads(FAKE["xau/sig/student/scores.json"][0])["grade"]
rev = sc.get("rule:rev15", {}); cl = sc.get("claude", {})
check("rev15 學生（BUY，5 分鐘前）：交卷＋方向命中", rev.get("n") == 1 and rev.get("time") == 1 and rev.get("dir") == 1, sc)
check("Claude 學生（5 分鐘前話 SELL）：交卷但方向錯", cl.get("n") == 1 and cl.get("time") == 1 and cl.get("dir") == 0 and cl.get("zone") == 0, sc)
check("每個學生都計一次 n", all(sc.get(k, {}).get("n") == 1 for k in student.STUDENTS), sc)
stt = json.loads(FAKE["xau/sig/student/state.json"][0])
check("已對答案嘅判斷標 graded=sid", any(p.get("graded") == "3860767713_501" for p in stt["preds"]), [p.get("graded") for p in stt["preds"]])
parsed({"kind": "new_signal", "symbol": "XAUUSD", "side": "SELL", "entry_low": 3999, "entry_high": 4001, "sl": 4010, "tp": [3995], "confidence": 0.9, "analysis": "x"})
st, d = send({"action": "tg_signal", "channel_id": 2249680342, "msg_id": 77, "text": "sig", "date": market.fmt_utc(NOW[0]).replace(" ", "T") + "+00:00"})
check("非參考頻道：有快照、唔對答案", "xau/sig/snapshots/2249680342_77.json" in FAKE and json.loads(FAKE["xau/sig/student/scores.json"][0])["grade"]["rule:rev15"]["n"] == 1)

print("=== 學生自己成績（DAN 結構 2R 全平）===")
pred = next(p for p in stt["preds"] if p["student"] == "rule:rev15" and p.get("graded"))
mid = (pred["entry_low"] + pred["entry_high"]) / 2
t1 = int(pred["ts"]) + 60
bars = [{"time": t1, "open": mid + 1, "high": mid + 1, "low": mid - 0.5, "close": mid}, {"time": t1 + 60, "open": mid, "high": pred["tp"][0] + 0.5, "low": mid, "close": pred["tp"][0]}]
n = student.score_pending(bars, 0, pred["ts"] + 3600)
own = json.loads(FAKE["xau/sig/student/scores.json"][0]).get("own", {})
check("成交後到 2R → own.win、r_sum +2", n >= 1 and own.get("rule:rev15", {}).get("win") == 1 and own["rule:rev15"]["r_sum"] == 2.0, own)

print("=== 網頁／JSON／心跳唔爆 ===")
js = client.get("/?format=json").get_json()
check("status JSON 有 student（counts／scores）", js.get("student", {}).get("counts") and "scores" in js["student"], js.get("student"))
html = client.get("/").get_data(as_text=True)
check("頁面有學徒區同延遲／已走", "🎓 學徒" in html and "⏱" in html)
FAKE["xau/sig/m15.json"] = (json.dumps([{"time": T0 + k * 900, "open": 4000, "high": 4001, "low": 3999, "close": 4000} for k in range(30)]), 1)
FAKE["xau/sig/m1.json"] = (json.dumps(M1[-40:]), 1)
xau._brain = FB
t = int(NOW[0]) + 60; NOW[0] = t + 5
body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": 0, "magic": 931,
        "m1_ohlc": {"time": t, "open": 3998, "high": 3998.5, "low": 3997.5, "close": 3998, "is_new_bar": True},
        "m15_ohlc": {"time": T0 + 29 * 900, "open": 4000, "high": 4001, "low": 3999, "close": 4000}}
r = client.post("/", data=json.dumps(body), content_type="application/json")
check("931 心跳行學生 tick 冇爆、唔落單（EXECUTE=0）", r.status_code == 200 and r.get_json().get("cmd_text") == "", r.get_json())

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
