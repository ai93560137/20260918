"""[R361] H1 回調真倉（magic 934；使用者 11-01「H1 回調星期一用真倉」）：訊號（H4 EMA50 斜率＋H1 RSI 穿 35／65）、H1／H4 合成邊界、
SL／TP、時間止蝕、週末缺口、每根 H1 只判一次、TTL、戶口總倉數上限、日蝕停開、數據唔新鮮、id 前綴 g、回報分流、預設關。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5",
                  SIG_G7_LIVE="1", SIG_G7_DAY_STOP_HKD="300")
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
import main as xau, config, g7_live as G         # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
NOW = [0.0]
xau.now_ts = lambda: NOW[0]
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 1)

# ---------- 合成數據：15 日每分鐘升 0.05，最後一個 H1 急跌 120（RSI 跌穿 35、H4 斜率仍然向上）----------
END = 1793664000          # 2026-11-03 00:00 UTC（星期二），H1 23:00 啱啱收
def series(drop=-120.0, days=15, end=END):
    rows, px = [], 3800.0
    start = end - days * 86400
    for t in range(start, end, 60):
        step = 0.05
        if t >= end - 3600:
            step = drop / 60
        o = px; px = px + step
        rows.append((t, o, max(o, px) + 0.02, min(o, px) - 0.02, px))
    return rows

print("=== 純計算 ===")
h4 = G.aggregate([(1793656800 + 60 * i, 1, 1, 1, 1) for i in range(300)], 4 * 3600, G.H4_SHIFT)
check("H4 以 22:00 UTC 對齊（02:00、06:00…）", all((k - 22 * 3600) % (4 * 3600) == 0 for k, *_ in h4), [dt.datetime.fromtimestamp(k, dt.timezone.utc).hour for k, *_ in h4])
h1 = G.aggregate([(3600 * 5 + 60 * i, i, i + 1, i - 1, i + 0.5) for i in range(120)], 3600)
check("H1 合成邊界：120 根 M1 → 2 根 H1，開／高／低／收啱", len(h1) == 2 and h1[0][1] == 0 and h1[0][2] == 60 and h1[0][3] == -1 and h1[0][4] == 59.5 and h1[1][1] == 60, h1)
rows = series()
s = G.signal(rows, END + 65, th=35, k=1.5)
check("急跌 H1：RSI 跌穿 35、H4 斜率 > 0 → BUY", s.get("side") == "BUY" and s["rsi"] <= 35 < s["rsi_prev"] and s["slope"] > 0, s)
check("SL 距離 = 1.5 × H1 ATR", abs(s["sl_dist"] - 1.5 * s["atr"]) < 1e-2, s)
after = [(t, rows[-1][4] - 0.1 * k, rows[-1][4] - 0.1 * k + 0.05, rows[-1][4] - 0.1 * (k + 1) - 0.05, rows[-1][4] - 0.1 * (k + 1)) for k, t in enumerate(range(END, END + 3600, 60))]
s2 = G.signal(rows + after, END + 3600 + 65, th=35, k=1.5)
check("下一根 H1 RSI 仍 ≤35 但唔係啱啱穿 → 冇訊號", s2.get("side") is None, s2)
s3 = G.signal(series(drop=+5.0), END + 65)
check("冇急跌 → 冇訊號", s3.get("side") is None, s3)
rows_down = [(t, 7600 - o, 7600 - l, 7600 - h, 7600 - c) for t, o, h, l, c in rows]
s4 = G.signal(rows_down, END + 65, th=35, k=1.5)
check("鏡像（跌市急升）→ SELL", s4.get("side") == "SELL" and s4["slope"] < 0 and s4["rsi"] >= 65, s4)
check("數據唔夠 → 冇訊號＋原因", "數據唔夠" in G.signal(rows[-3000:], END + 65).get("why", ""))
sl, tp = G.levels("BUY", 4000.0, 15.0, r=2.0)
sl2, tp2 = G.levels("SELL", 4000.0, 15.0, r=2.0)
check("levels：BUY SL 3985／TP 4030；SELL SL 4015／TP 3970", (sl, tp, sl2, tp2) == (3985.0, 4030.0, 4015.0, 3970.0), (sl, tp, sl2, tp2))
check("時間止蝕：72 小時到先平；冇開倉時間用落單時間", G.time_stop_due({"opened_ts": 1000}, 1000 + 72 * 3600, 72) and not G.time_stop_due({"opened_ts": 1000}, 1000 + 71 * 3600, 72)
      and G.time_stop_due({"opened_ts": 0}, 1000 + 72 * 3600, 72, opened_fallback=1000) and not G.time_stop_due(None, 10**10, 72))
# 週末缺口：星期五 20:00 開倉，星期一 22:00 都已經過 72 小時（按時鐘計，同回測一樣）
fri = 1793390400   # 2026-10-30 20:00 UTC 星期五
check("時間止蝕按時鐘計（週末都計）：星期五 20:00 開 → 星期一 20:00 到", G.time_stop_due({"opened_ts": fri}, fri + 72 * 3600, 72))
wk = [(100, 1, 2, 0.5, 1.5), (160, 1.5, 1.5, 1.5, 1.5), (220, 1.5, 1.5, 1.5, 1.5), (280, 1.5, 2, 1, 1.8), (340, 1.8, 1.8, 1.8, 1.9)]
check("剔休市平盤 K 線（高＝低、收市同上一根一樣），真 K 線保留", G.drop_flat(wk) == [wk[0], wk[3], wk[4]], G.drop_flat(wk))
# 券商時區：10-29（夏令 UTC+3）、11-03（冬令 UTC+2）
check("broker_utc：美國夏令時 UTC+3、之後 UTC+2", G.broker_utc(1793311200 + 3 * 3600) == 1793311200 and G.broker_utc(1793664000 + 2 * 3600) == 1793664000)
# 週末 server_offset 計錯：星期五 K 線（伺服器時間一樣）被存去星期六檔、utc 錯 → 讀返要合併、唔重複
fri_t = 1793390400 + 3 * 3600   # 星期五 20:00 UTC 嘅伺服器時間
FAKE["xau/sig/bars/2026-10-30.jsonl"] = (json.dumps([{"time": fri_t, "utc": fri_t - 3 * 3600, "open": 1, "high": 2, "low": 0.5, "close": 1.5}]), 1)
FAKE["xau/sig/bars/2026-10-31.jsonl"] = (json.dumps([{"time": fri_t, "utc": fri_t + 66000, "open": 1, "high": 2, "low": 0.5, "close": 1.5}]), 1)
G._DAY_CACHE.clear()
lm = G.load_m1(1793390400 + 2 * 86400, days=3)
check("週末重複存嘅星期五 K 線：用伺服器時間重算 UTC → 只剩一根、時間啱", [b[0] for b in lm] == [1793390400], lm)
FAKE.pop("xau/sig/bars/2026-10-30.jsonl"); FAKE.pop("xau/sig/bars/2026-10-31.jsonl"); G._DAY_CACHE.clear()
check("id 前綴 g；931 隨機 hex 永遠唔會撞（hex 冇 g）", G.is_cmd("g1234567") and not G.is_cmd("f1234567") and not G.is_cmd("abcdef01"))
check("magic 934、0.05 手、日蝕 300、戶口上限 3", config.G7_MAGIC == 934 and config.G7_LOTS == 0.05 and config.G7_DAY_STOP_HKD == 300 and config.G7_ACCOUNT_MAX == 3)

# ---------- 心跳流程 ----------
def put_bars(rows):
    by = {}
    for t, o, h, l, c in rows:
        by.setdefault(dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d"), []).append({"time": t + (2 * 3600 if t >= 1793512800 else 3 * 3600), "utc": t, "open": o, "high": h, "low": l, "close": c})
    for d, v in by.items():
        FAKE[f"xau/sig/bars/{d}.jsonl"] = (json.dumps(v), 1)
    G._DAY_CACHE.clear()

def hb(now, close, positions=None, daily=0.0, magic=934):
    NOW[0] = now
    body = {"action": "check_gate", "token": "tok", "symbol": "XAUUSD", "currency": "HKD", "balance": 23000, "equity": 28000, "floating": 0, "daily_pnl": daily,
            "realized_total": 0, "magic": magic, "positions": positions or [], "trade_allowed": {"terminal": True, "ea": True, "account": True},
            "m1_ohlc": {"time": now - 65, "open": close, "high": close, "low": close, "close": close, "is_new_bar": True}}
    r = client.post("/", data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()

def gstate(): return json.loads(FAKE["xau/sig/g7live/state.json"][0])

print("=== 心跳 ===")
put_bars(rows)
price = rows[-1][4]
st, d = hb(END + 65, price)
check("magic 934 心跳分流到 g7live", st == 200 and d.get("book") == "g7live", d)
check("BUY 開倉指令：magic=934、0.05 手、帶 px／dev、id 前綴 g、note H1回調", d["cmd_text"].startswith("open|BUY|0.05|") and "magic=934" in d["cmd_text"]
      and "|px=" in d["cmd_text"] and "|id=g" in d["cmd_text"] and "note=" in d["cmd_text"], d)
o = gstate()["orders"][-1]
check("SL／TP：TP 距離 = 2 × SL 距離", abs((o["tp"] - o["price"]) - 2 * (o["price"] - o["sl"])) < 0.02, o)
st, d2 = hb(END + 125, price)
check("同一根 H1 唔再判、唔再開（等回報）", d2["message"].startswith("等 EA 回報開倉") or "已判" in d2["message"], d2)
cid = o["id"]
NOW[0] = END + 130
r = client.post("/", data=json.dumps({"action": "cmd_ack", "token": "tok", "id": cid, "ok": True, "ticket": 777, "message": "done"}), content_type="application/json")
check("cmd_ack 前綴 g → H1 回調書收", r.get_json().get("status") == "acked" and gstate()["orders"][-1].get("ticket") == 777, r.get_json())
pos = [{"ticket": 777, "side": "BUY", "entry": price, "lots": 0.05, "sl": o["sl"], "tp": o["tp"], "open_time": END + 70}]
st, d3 = hb(END + 3600 * 5, price, positions=pos)
check("有倉未到 72 小時 → 唔郁", "有倉" in d3["message"] and d3["cmd_text"] == "", d3)
st, d4 = hb(END + 70 + 72 * 3600, price, positions=pos)
check("到 72 小時 → 時間止蝕 close|all|magic=934", "close|all|magic=934" in d4["cmd_text"] and "時間止蝕" in d4["message"], d4)
st, d5 = hb(END + 130 + 72 * 3600, price, positions=pos)
check("平倉指令未回報 → 唔重複排", d5["cmd_text"].count("close|") == 1 and "等 EA 回報平倉" in d5["message"], d5)

print("=== 風控 ===")
def fresh_state():
    FAKE["xau/sig/g7live/state.json"] = (json.dumps(G.empty_state()), 1)
fresh_state()
FAKE["xau/sig/account.json"] = (json.dumps({"positions": [{"ticket": 1}, {"ticket": 2}]}), 1)
FAKE["xau/sig/studentlive/account.json"] = (json.dumps({"positions": [{"ticket": 3}]}), 1)
st, d = hb(END + 65, price)
check("同戶口 931 兩張＋933 一張＝3 → 唔開", d["cmd_text"] == "" and "上限 3" in d["message"], d)
FAKE["xau/sig/account.json"] = (json.dumps({"positions": []}), 1); FAKE["xau/sig/studentlive/account.json"] = (json.dumps({"positions": []}), 1)
fresh_state()
st, d = hb(END + 65, price, daily=-350)
check("934 今日蝕 350 ≥ 300 → 停開", d["cmd_text"] == "" and "暫停開新倉" in d["message"], d)
fresh_state()
flat = [(t, price, price + 0.02, price - 0.02, price) for t in range(END, END + 20 * 60, 60)]
put_bars(rows + flat)
st, d = hb(END + 65 + 20 * 60, price)
check("H1 收盤後 20 分鐘先見到（TTL 15）→ 唔追", d["cmd_text"] == "" and "唔追" in d["message"], d)
fresh_state()
FAKE.pop("xau/sig/bars/2026-11-03.jsonl", None)
put_bars(rows)
st, d = hb(END + 65 + 600, price)   # 最新 M1 舊過 5 分鐘
check("M1 唔新鮮 → 唔開", d["cmd_text"] == "" and "唔新鮮" in d["message"], d)
fresh_state()
config.G7_LIVE = False
st, d = hb(END + 65, price)
check("SIG_G7_LIVE 關 → 心跳唔分流（交返 931 流程）", d.get("book") != "g7live", d)
config.G7_LIVE = True
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "STOP", "set_by": "user"}), 2)
fresh_state()
st, d = hb(END + 65, price)
check("control STOP → 唔開", d["cmd_text"] == "" and "STOP" in d["message"], d)
FAKE["xau/sig/control.json"] = (json.dumps({"mode": "RUN", "set_by": "user", "principal_hkd": 27000.0}), 3)
NOW[0] = END + 65
sts = G.status()
check("status：magic、參數、訊號紀錄", sts["magic"] == 934 and sts["params"]["hold_h"] == 72 and isinstance(sts["signals"], list), sts)

print("=== 回測引擎：同一根 SL／TP 都掂當 SL ===")
try:
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "strategy_search"))
    import search2 as W
    H = np.full((1, W.MAX_H), np.nan, np.float32); L = H.copy(); C = H.copy(); O = H.copy(); E = np.full((1, W.MAX_H), 10**9, np.int64)
    H[0, :3] = [1, 40, 1]; L[0, :3] = [-1, -20, -1]; C[0, :3] = 0; O[0, :3] = 0; E[0, :3] = [0, 300, 600]
    r, _, _ = W.simulate(np.array([15.0]), (H, L, C, E, np.array([0]), O), 2.0, 72)
    check("同一根 K 線 SL（−15）同 TP（+30）都掂 → 當 SL（−1R − 成本）", abs(r[0] - (-15 - 0.5) / 15) < 1e-6, r)
except ImportError:
    print("  （冇 numpy，略過回測引擎測試）")

print(f"\n結果：{OK} 過、{FAIL} 失敗")
sys.exit(1 if FAIL else 0)
