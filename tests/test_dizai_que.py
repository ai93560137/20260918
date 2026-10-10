"""[R143] 🕳️ 地載・缺（開市跳空突破）：main.py 引擎跟研究 open_breakout.simulate 逐筆一致；分段推進＝一次推進；通知；頁面與 JSON。"""
import json, os, sys, types

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
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

import json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, "/home/user/20260918/research/hsi_futures_range")
import dizai_search as ds, rsi_avg_down as rad, open_breakout as ob   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

SYM = "HK.HSI_FRONT"
random.seed(3)


def make(n_days=110, start="2026-03-02", px=24000.0):
    """平日交易日、每日 09:16 起 330 根 1 分 K；每天有隨機趨勢，令 2% 升跌、加倉、止賺、止蝕都會出現。"""
    bars, days, d = [], [], datetime.strptime(start, "%Y-%m-%d")
    while len(days) < n_days:
        if d.weekday() < 5:
            day = d.strftime("%Y-%m-%d"); days.append(day)
            px *= 1 + random.gauss(0, 0.006)
            drift = random.choice([-1, 1]) * abs(random.gauss(0, 2.2))
            t = d.replace(hour=9, minute=16)
            for k in range(330):
                o = px
                px = max(5000.0, px + drift + random.gauss(0, 14))
                hi, lo = max(o, px) + abs(random.gauss(0, 5)), min(o, px) - abs(random.gauss(0, 5))
                bars.append({"time_key": (t + timedelta(minutes=k)).strftime("%Y-%m-%d %H:%M:%S"),
                             "open": round(o), "high": round(hi), "low": round(lo), "close": round(px), "volume": 10})
        d += timedelta(days=1)
    return days, bars


days, raw = make()
bars = rad.clean(raw)
D = ds.prepare(bars)
rows = [{"date": d, "high": float(D["h"][s:e].max()), "low": float(D["l"][s:e].min()), "close": float(D["c"][e - 1])}
        for d, s, e in zip(D["days"], D["starts"], D["ends"])]
tk = D["tk"]



random.seed(11)
NQ = {d: random.choice([-1, 1]) * random.uniform(0, 0.012) for d in days}
def nq_fn(prev_last_tk, first_tk):
    return NQ[first_tk[:10]]

print("=== 1. 引擎跟研究 open_breakout.simulate 逐筆一致 ===")
st = main.dizai_que_new_state(days[0])
main.dizai_que_advance(st, bars, main._dz_ctx_fn(rows), nq_fn)
dslices = ob.day_slices(D)
pcs = {k: D["c"][D["ends"][k - 1] - 1] for k, s, e in dslices if k > 0}
first = {k: s for k, s, e in dslices}
prev_ok = {dslices[i][0] for i in range(1, len(dslices))}
def allow(k, b):
    if k not in prev_ok:
        return False
    gap = D["o"][first[k]] / pcs[k] - 1
    nq = NQ[D["days"][k]]
    return abs(gap) >= 0.005 and nq * b < 0
ref = ob.simulate(D, dslices, 0.0025, "對面", None, ob.RSI_RULES["不追極端"], 1, allow)
ref = [r for r in ref if r[0] >= 20]                      # 引擎要 20 日歷史（dizai_day_ctx）才判斷
a = [(D["days"][r[0]], r[3], r[2], round(r[1], 1)) for r in ref]
b = [(main.futu_session_of(t["entry_tk"], SYM), 1 if t["side"] == "買" else -1, t["reason"], round(t["pnl"], 1)) for t in st["trades"]]
check(f"研究 {len(a)} 筆、引擎 {len(b)} 筆，逐筆相同（日期、方向、止蝕／收市、點數）", a == b and len(a) >= 5,
      next(((x, y) for x, y in zip(a, b) if x != y), (len(a), len(b))))
check("止蝕與收市平倉都出現", {"sl", "close"} <= {t["reason"] for t in st["trades"]}, {t["reason"] for t in st["trades"]})
check("每日最多一筆", len({main.futu_session_of(t["entry_tk"], SYM) for t in st["trades"]}) == len(st["trades"]))
check("突破方向都跟 Nasdaq 相反", all((1 if t["side"] == "買" else -1) * t["nq"] < 0 for t in st["trades"]))

print("=== 2. 分段推進 = 一次推進 ===")
seg = main.dizai_que_new_state(days[0])
cuts = sorted(random.sample(range(1, len(bars)), 30))
for a_, b_ in zip([0] + cuts, cuts + [len(bars)]):
    seg = json.loads(json.dumps(seg)); main.dizai_que_advance(seg, bars[a_:b_], main._dz_ctx_fn(rows), nq_fn)
check("交易、持倉、通知完全一樣", json.dumps([seg["trades"], seg["pos"], [n["text"] for n in seg["notices"]]], sort_keys=True)
      == json.dumps(json.loads(json.dumps([st["trades"], st["pos"], [n["text"] for n in st["notices"]]])), sort_keys=True))

print("=== 3. 通知 ===")
kinds = [n["kind"] for n in st["notices"]]
check("每筆有開倉與平倉通知；符合條件的日子有一則今日提醒", kinds.count("open") == len(st["trades"]) + (1 if st["pos"] else 0)
      and kinds.count("sl") + kinds.count("close") == len(st["trades"]) and kinds.count("gate") >= kinds.count("open"),
      {k: kinds.count(k) for k in set(kinds)})
check("全部以【地載陣・缺】開頭、id 以 que: 開頭", all(n["text"].startswith("【地載陣・缺】") and n["id"].startswith("que:") for n in st["notices"]))
for k in ("gate", "open", "sl", "close"):
    t = next((n["text"] for n in st["notices"] if n["kind"] == k), None)
    if t:
        print(f"--- {k} ---\n{t}")

print("=== 4. 推 K_1M → 更新 → 頁面、JSON、report=signals ===")
client = main.app.test_client()
FAKE.clear()
os.environ.pop("TG_BOT_TOKEN", None); os.environ.pop("TG_CHAT_ID", None)
HK = timezone(timedelta(hours=8))
main.gcs_write_text(main.futu_daily_file(SYM), json.dumps(
    [{"time_key": r["date"] + " 00:00:00", "open": r["close"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in rows[:-1]]))
by = {}
for b_ in raw:
    by.setdefault(b_["time_key"][:10], []).append(b_)
for d in days[-3:-1]:
    main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, d), json.dumps(by[d]))
main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, days[-1]), json.dumps(by[days[-1]][:200]))
now = datetime.strptime(days[-1] + " 12:30", "%Y-%m-%d %H:%M").replace(tzinfo=HK)
main.dizai_update(SYM, now=now)
qs = main.gcs_read_json(main.dizai_que_file(SYM), {})
check("第一次：建立狀態、開始日 = 今天、前兩日熱身", qs.get("start") == days[-1] and qs.get("last_bar") == by[days[-1]][198]["time_key"], (qs.get("start"), qs.get("last_bar")))
qd = main.dizai_data(SYM, now=now)["que"]
check("JSON：規則、回測、今日", qd["rules"]["gap"] == 0.005 and qd["backtest"]["n"] == 154 and qd["day"] is not None, qd.get("day"))
html = client.get("/?view=dizai").get_data(as_text=True)
check("頁面：地載・缺一節（規則、今日、前向、回測逐年）", all(x in html for x in ("地載・缺", "跳空", "Nasdaq 隔夜", "前向測試", "選擇偏差")), html[:200])
# report=signals：放一則未發的通知
qs["notices"] = [{"id": "que:99", "kind": "gate", "time": qs["last_bar"], "text": "【地載陣・缺】測試", "sent": False}]
main.gcs_write_text(main.dizai_que_file(SYM), json.dumps(qs))
sig = client.get("/?view=futu_range&report=signals").get_json()
check("report=signals 給出地載・缺通知", any(x["id"] == "que:99" for x in sig["signals"]), sig)
client.get("/?view=futu_range&report=signals&ack=que:99")
check("ack 後標記已發", main.gcs_read_json(main.dizai_que_file(SYM), {})["notices"][0].get("via") == "github")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
