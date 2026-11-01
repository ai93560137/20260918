"""[R364] 組合 A 單倉真倉（magic 935）：D1／H4 合成、指標、六個成份訊號、星期五、手數（1% 唔夠就 0.01、超 10% 唔開）、
心跳分流、開倉指令、同一 H4 唔再判、時間止蝕、參數年份、id 前綴 k、回報分流、預設關。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5",
                  SIG_COMBO_LIVE="1", XAU_RISK_SIZING="1")
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
import datetime as dt                            # noqa: E402
import main as xau, config, combo_live as C, g7_live as G     # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [0.0]
xau.now_ts = lambda: NOW[0]
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 1)

print("=== 純計算 ===")
d1 = C.group([(1793656800 + 3600 * i, 1, 2, 0, 1) for i in range(30)], 86400)      # 11-02 22:00 起 30 根 H1
check("D1 由 22:00 UTC 開始（券商日）", len(d1) == 2 and d1[0][5] == 1793656800 and (d1[0][5] + 7200) % 86400 == 0, d1)
h4 = C.group([(1793656800 + 3600 * i, 1, 2, 0, 1) for i in range(9)], 14400)
check("H4 以 22:00 UTC 對齊", [b[5] % 14400 for b in h4] == [79200 % 14400] * len(h4), h4)
check("rolling_mean 前 n−1 個係 None", C.rolling_mean([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0])
sar, up = C.psar([10, 11, 12, 13, 12, 9, 8], [9, 10, 11, 12, 10, 7, 6])
check("拋物線 SAR：升市向上、急跌轉向下", up[3] and not up[6], (sar, up))
check("星期五（券商日）判斷：2026-11-06 係星期五", C.friday_of(dt.date(2026, 11, 6).toordinal() - dt.date(1970, 1, 1).toordinal()))
sl, tp = C.levels(1, 4000.0, 60.0, 120.0); sl2, tp2 = C.levels(-1, 4000.0, 30.0, None)
check("levels：買 SL 3940／TP 4120；沽冇 TP（星期效應）", (sl, tp, sl2, tp2) == (3940.0, 4120.0, 4030.0, None), (sl, tp, sl2, tp2))
lots, info = C.floor_lots(30000, 4000.0, 3880.0, 0.01)      # 0.01 手風險 120×7.8＝936 HKD＝3.1%
check("1% 唔夠 0.01 手 → 照開 0.01（風險 ≤ 10%）", lots == 0.01 and info.get("mode") == "floor", info)
lots, info = C.floor_lots(5000, 4000.0, 3880.0, 0.01)       # 936 HKD＝18.7%
check("0.01 手風險 > 10% → 唔開", lots == 0.0, info)
lots, info = C.floor_lots(2000000, 4000.0, 3880.0, 0.01)
check("權益大都夾住 0.01 手上限", lots == 0.01, info)
check("id 前綴 k；931 隨機 hex 唔會撞", C.is_cmd("k1234567") and not C.is_cmd("abcdef01") and not C.is_cmd("g1234567"))
check("magic 935、1%、上限 0.01、戶口上限 3、參數年 2026", config.COMBO_MAGIC == 935 and config.COMBO_RISK_PCT == 1.0 and config.COMBO_MAX_LOTS == 0.01
      and config.COMBO_ACCOUNT_MAX == 3 and config.COMBO_PARAM_YEAR == 2026)

print("=== R365 A+：D1 內包線突破 ===")
check("A+ 七個成份、內包線突破排最後（TP4／SL2、480 小時）", len(C.COMPONENTS) == 7 and C.COMPONENTS[-1] == ("D1 內包線突破", "C3", "D1", 4.0, 2.0, 480.0), C.COMPONENTS[-1])
ib = {"h": [110, 108, 112], "l": [100, 102, 105], "c": [105, 105, 111], "s200": [90, 90, 90]}
check("內包線（第 2 根喺第 1 根入面）＋收市破母線高＋SMA200 之上 → 買", C.family_side(ib, "C3", 2) == 1)
ib2 = {"h": [110, 108, 104], "l": [100, 102, 98], "c": [105, 105, 99], "s200": [120, 120, 120]}
check("破母線低＋SMA200 之下 → 沽", C.family_side(ib2, "C3", 2) == -1)
ib3 = dict(ib, s200=[120, 120, 120])
check("破高但喺 SMA200 之下 → 唔做（filt）", C.family_side(ib3, "C3", 2) == 0)
ib4 = {"h": [110, 111, 115], "l": [100, 102, 105], "c": [105, 105, 114], "s200": [90, 90, 90]}
check("上一根唔係內包線 → 唔做", C.family_side(ib4, "C3", 2) == 0)
check("status 標 A+", C.status().get("version") == "A+" if isinstance(C.status(), dict) else False, C.status() if isinstance(C.status(), dict) else None)

# ---------- 合成 600 日 H1：慢升，最後一個券商日（11-02 22:00→11-03 22:00）急升 → D1 Keltner 突破 ----------
DAY_END = 1793743200          # 2026-11-03 22:00 UTC（星期二收市＝星期三券商日開始）
def h1_series():
    rows, px = [], 3000.0
    start = DAY_END - 600 * 86400
    for t in range(start, DAY_END, 3600):
        wd = dt.datetime.fromtimestamp(t + 7200, dt.timezone.utc).weekday()
        if wd >= 5:
            continue
        step = 0.02 if t < DAY_END - 86400 else 12.0
        o = px; px = px + step + (0.8 if (t // 3600) % 2 else -0.8)
        rows.append((t, o, max(o, px) + 1.0, min(o, px) - 1.0, px))
    return rows
H1 = h1_series()
cands = C.candidates(H1, DAY_END + 600)
check("急升日收市 → 第一個訊號係 D1 Keltner 突破（買）", cands and cands[0]["comp"] == "D1 Keltner 突破" and cands[0]["side"] == 1, cands)
k = cands[0] if cands else {}
check("Keltner：TP＝4×ATR、SL＝2×ATR、80→480 小時", k and abs(k["tp_dist"] - 2 * k["sl_dist"]) < 1e-9 and k["hold_h"] == 480.0, k)

def hb(now, close, positions=None, daily=0.0, magic=935, equity=28000):
    NOW[0] = now
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": equity, "floating": 0, "daily_pnl": daily,
            "realized_total": 0, "magic": magic, "positions": positions or [], "trade_allowed": {"terminal": True, "ea": True, "account": True},
            "m1_ohlc": {"time": now - 65, "open": close, "high": close, "low": close, "close": close, "is_new_bar": True}}
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def cstate(): return json.loads(FAKE["xau/sig/combolive/state.json"][0])

print("=== 心跳 ===")
FAKE["xau/sig/combolive/h1.json"] = (json.dumps([list(b) for b in H1]), 1)
last = H1[-1][4]
fresh = [{"time": t + 2 * 3600, "utc": t, "open": last, "high": last + 0.2, "low": last - 0.2, "close": last} for t in range(DAY_END + 3600, DAY_END + 3600 + 600, 60)]
FAKE["xau/sig/bars/2026-11-03.jsonl"] = (json.dumps(fresh), 1)
G._DAY_CACHE.clear()
NOWT = DAY_END + 3600 + 600 + 5          # 23:10 UTC：休市後第一根 H1（23:00）開咗 10 分鐘
st, d = hb(NOWT, last)
check("magic 935 心跳分流到 combolive", st == 200 and d.get("book") == "combolive", d)
check("開倉指令：BUY 0.01 手、magic=935、id 前綴 k、帶 px／dev、note 組合A", d["cmd_text"].startswith("open|BUY|0.01|") and "magic=935" in d["cmd_text"]
      and "|id=k" in d["cmd_text"] and "|px=" in d["cmd_text"] and "note=" in d["cmd_text"], d)
o = cstate()["orders"][-1]
check("order 記成份、時間止蝕 480 小時、TP＝2×SL 距離", o["comp"] == "D1 Keltner 突破" and o["hold_h"] == 480.0
      and abs((o["tp"] - o["price"]) - 2 * (o["price"] - o["sl"])) < 0.02, o)
st, d2 = hb(NOWT + 60, last)
check("等回報 → 唔再開", d2["message"].startswith("等 EA 回報開倉"), d2)
cid = o["id"]
r = client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 555, "account": config.COMBO_ACCOUNT}), content_type="application/json")
check("cmd_ack 前綴 k 分流到組合 A", r.get_json().get("status") == "acked" and cstate()["orders"][-1]["acked"], r.get_json())
pos = [{"ticket": 555, "side": "BUY", "entry": last, "lots": 0.01, "sl": o["sl"], "tp": o["tp"], "open_time": NOWT + 2 * 3600}]
st, d3 = hb(NOWT + 3600, last, positions=pos)
check("有倉：唔開新倉、未到鐘唔平", d3["message"].startswith("有倉") and d3["cmd_text"] == "", d3)
st, d4 = hb(NOWT + 480 * 3600 + 60, last, positions=pos)
check("480 小時到 → close|all|magic=935", "close|all|magic=935" in d4["cmd_text"], d4)

print("=== 擋單 ===")
FAKE.pop("xau/sig/combolive/state.json", None)
st, d5 = hb(NOWT, last, equity=2000)          # 0.01 手風險 ≈ 274 HKD ＝ 13.7%
check("0.01 手風險 > 權益 10% → 唔開", d5["cmd_text"] == "" and "唔開" in d5["message"], d5)
FAKE.pop("xau/sig/combolive/state.json", None)
st, d6 = hb(NOWT, last, daily=-6000)
check("當日蝕 ≥ 5000 → 唔開（日蝕停開或者風控階梯）", d6["cmd_text"] == "" and ("暫停開新倉" in d6["message"] or "階梯" in d6["message"]), d6)
FAKE.pop("xau/sig/combolive/state.json", None)
config.COMBO_PARAM_YEAR = 2027
st, d7 = hb(NOWT, last)
check("參數年份 ≠ 今年 → 唔開（要重揀參數）", d7["cmd_text"] == "" and "參數年份" in d7["message"], d7)
config.COMBO_PARAM_YEAR = 2026
FAKE.pop("xau/sig/combolive/state.json", None)
config.COMBO_LIVE = False
st, d8 = hb(NOWT, last)
check("SIG_COMBO_LIVE=0 → 935 心跳唔分流（交返其他書）", d8.get("book") != "combolive", d8)
config.COMBO_LIVE = True

print(f"\n結果：{OK} 過、{FAIL} 失敗")
sys.exit(1 if FAIL else 0)
