"""[R141] ⚖️ 地載・衡（滾動選參、災難止蝕）：main.py 引擎跟研究 rsi_basic.run_adds 逐筆一致（多組參數）；分段推進＝一次推進；
推 K_1M → 更新 → 頁面與 JSON；今年沒有參數 → 不開新倉。"""
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
import dizai_search as ds, rsi_avg_down as rad, rsi_basic as rb   # noqa: E402

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


CASES = {
    "穿越 75/25 ≥2% 0.3% 不加倉 止蝕2%": {"trig": "cross", "hi": 75, "lo": 25, "move": 0.02, "tp_pct": 0.003, "add_lots": (), "step_pct": None, "dstop_pct": 0.02},
    "轉向 80/20 ≥1% 0.2% 加倉ATR 止蝕3%": {"trig": "confirm", "hi": 80, "lo": 20, "move": 0.01, "tp_pct": 0.002, "add_lots": (1, 1, 1, 1), "step_pct": None, "dstop_pct": 0.03},
    "穿越 70/30 ≥1% 0.5% 加倉1% 止蝕2%": {"trig": "cross", "hi": 70, "lo": 30, "move": 0.01, "tp_pct": 0.005, "add_lots": (1, 1, 1, 1), "step_pct": 0.01, "dstop_pct": 0.02},
    "轉向 75/25 ≥1% 0.15% 加倉2% 無止蝕": {"trig": "confirm", "hi": 75, "lo": 25, "move": 0.01, "tp_pct": 0.0015, "add_lots": (1, 1, 1, 1), "step_pct": 0.02, "dstop_pct": None},
}
YEAR = days[0][:4]

print("=== 1. 引擎跟研究 run_adds 逐筆一致 ===")
seen = set()
for name, p in CASES.items():
    main.DIZAI_HENG_PICKS = {YEAR: {**p, "train": "測試"}}
    st = main.dizai_heng_new_state(days[0])
    main.dizai_heng_advance(st, bars, main._dz_ctx_fn(rows))
    ref = rb.run_adds(D, rb.signals(D, p["hi"], p["lo"], p["trig"], p["move"]), None, p["add_lots"],
                      tp_pct=p["tp_pct"], step_pct=p["step_pct"], dstop_pct=p["dstop_pct"], entry_day=True)
    a = [(r["reason"], r["lots"], round(r["pnl"], 1)) for r in ref if r["reason"] != "open"]
    b = [(t["reason"], t["lots"], round(t["pnl"], 1)) for t in st["trades"]]
    check(f"{name}：研究 {len(a)} 筆、引擎 {len(b)} 筆，逐筆相同", a == b and len(a) >= 3,
          next(((x, y) for x, y in zip(a, b) if x != y), (len(a), len(b))))
    seen |= {(t["reason"], t["lots"] > 1) for t in st["trades"]}
check("規則都走過：止賺、災難止蝕、加過倉", {("tp", False), ("sl", False)} <= seen and any(x[1] for x in seen), sorted(seen))

print("=== 2. 分段推進 = 一次推進 ===")
p = CASES["穿越 70/30 ≥1% 0.5% 加倉1% 止蝕2%"]
main.DIZAI_HENG_PICKS = {YEAR: {**p, "train": "測試"}}
one = main.dizai_heng_new_state(days[0]); main.dizai_heng_advance(one, bars, main._dz_ctx_fn(rows))
seg = main.dizai_heng_new_state(days[0])
cuts = sorted(random.sample(range(1, len(bars)), 25))
for a_, b_ in zip([0] + cuts, cuts + [len(bars)]):
    seg = json.loads(json.dumps(seg))
    main.dizai_heng_advance(seg, bars[a_:b_], main._dz_ctx_fn(rows))
check("分 26 段推進（中間經過 JSON 存取）跟一次推進完全一樣",
      json.dumps({k: seg[k] for k in ("trades", "pos")}, sort_keys=True) == json.dumps(json.loads(json.dumps({k: one[k] for k in ("trades", "pos")})), sort_keys=True))

print("=== 3. 今年沒有參數 → 不開新倉 ===")
main.DIZAI_HENG_PICKS = {"1999": {**p, "train": "測試"}}
none = main.dizai_heng_new_state(days[0]); main.dizai_heng_advance(none, bars, main._dz_ctx_fn(rows))
check("沒有今年參數：零交易", not none["trades"] and none["pos"] is None)
check("規則說明：今年參數未選定", "未選定" in main._dz_heng_rule(None))

print("=== 4. 推 K_1M → 更新 → 頁面與 JSON ===")
main.DIZAI_HENG_PICKS = {YEAR: {**CASES["穿越 75/25 ≥2% 0.3% 不加倉 止蝕2%"], "train": "測試"}}
client = main.app.test_client()
FAKE.clear()
HK = timezone(timedelta(hours=8))
main.gcs_write_text(main.futu_daily_file(SYM), json.dumps(
    [{"time_key": r["date"] + " 00:00:00", "open": r["close"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in rows[:-1]]))
by = {}
for b in raw:
    by.setdefault(b["time_key"][:10], []).append(b)
for d in days[-3:-1]:
    main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, d), json.dumps(by[d]))
now = datetime.strptime(days[-1] + " 12:00", "%Y-%m-%d %H:%M").replace(tzinfo=HK)
part = by[days[-1]][:150]
main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, days[-1]), json.dumps(part))
main.dizai_update(SYM, now=now)
h = main.gcs_read_json(main.dizai_heng_file(SYM), {})
check("第一次：開始日 = 今天、前兩日熱身 RSI、最新一根不處理", h.get("start") == days[-1] and h.get("last_bar") == part[-2]["time_key"]
      and h["rsi"].get("value") is not None and not any(t["entry_tk"] < days[-1] for t in h["trades"]), (h.get("start"), h.get("last_bar")))
part2 = by[days[-1]][:260]
main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, days[-1]), json.dumps(part2))
main.dizai_update(SYM, now=now)
check("第二次：接着推進", main.gcs_read_json(main.dizai_heng_file(SYM), {}).get("last_bar") == part2[-2]["time_key"])
data = main.dizai_data(SYM, now=now)
hd = data["heng"]
check("JSON：今年參數、開閘線 = 上日收市 ±2%、滾動測試六年", hd["params"]["hi"] == 75 and hd["gate"]["up"] == round(hd["gate"]["prev_close"] * 1.02)
      and len(hd["walk_forward"]) == 6 and "stats" in hd, hd.get("gate"))
html = client.get("/?view=dizai").get_data(as_text=True)
check("頁面：地載・衡在最上方、規則、今日策略、前向、滾動測試", all(x in html for x in ("地載・衡", "災難止蝕", "滾動測試", "下一次換參數", "前兩年"))
      and html.index("地載・衡") < html.index("地載・穩"), html[:200])
j = client.get("/?view=dizai&format=json").get_json()
check("JSON 端點有 heng", j.get("heng", {}).get("params", {}).get("trig") == "cross")

print("=== 5. [R142] Telegram 通知 ===")
p = CASES["穿越 70/30 ≥1% 0.5% 加倉1% 止蝕2%"]
main.DIZAI_HENG_PICKS = {YEAR: {**p, "train": "測試"}}
st = main.dizai_heng_new_state(days[0]); main.dizai_heng_advance(st, bars, main._dz_ctx_fn(rows))
kinds = [e["kind"] for e in st["notices"]]
check("每筆交易都有開倉與平倉通知；有加倉、止賺、止蝕、開閘", kinds.count("open") == len(st["trades"]) + (1 if st["pos"] else 0)
      and kinds.count("tp") + kinds.count("sl") == len(st["trades"]) and {"gate", "add", "tp", "sl"} <= set(kinds),
      {k: kinds.count(k) for k in set(kinds)})
gates = {}
for e in st["notices"]:
    if e["kind"] == "gate":
        gates.setdefault(main.futu_session_of(e["time"], SYM), []).append(e["text"])
check("開閘提醒每日每方向最多一次", all(len(v) <= 2 for v in gates.values()) and gates, max(len(v) for v in gates.values()))
check("全部以【地載陣・衡】開頭、開倉／開閘註明紙上", all(e["text"].startswith("【地載陣・衡】") for e in st["notices"])
      and all("不是落盤指示" in e["text"] for e in st["notices"] if e["kind"] in ("open", "gate")))
ex = {k: next(e["text"] for e in st["notices"] if e["kind"] == k) for k in ("gate", "open", "add", "tp", "sl")}
for k, t in ex.items():
    print(f"--- {k} ---\n{t}")
t0 = st["trades"][0]
o0 = next(e for e in st["notices"] if e["kind"] == "open")
check("開倉通知的價位 = 交易紀錄的入場價", f"@ {t0['entry']:,.0f}" in o0["text"], o0["text"])
seg = main.dizai_heng_new_state(days[0])
for a_, b_ in zip([0] + cuts, cuts + [len(bars)]):
    seg = json.loads(json.dumps(seg)); main.dizai_heng_advance(seg, bars[a_:b_], main._dz_ctx_fn(rows))
check("分段推進的通知跟一次推進一樣", [e["text"] for e in seg["notices"]] == [e["text"] for e in st["notices"]])

FAKE.clear()
st["last_bar"] = bars[-1]["time_key"]
recent = [e for e in st["notices"] if e["time"] >= (datetime.strptime(st["last_bar"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")]
st["notices"] = st["notices"][-6:] if not recent else st["notices"]
main.gcs_write_text(main.dizai_heng_file(SYM), json.dumps(st))
os.environ.pop("TG_BOT_TOKEN", None); os.environ.pop("TG_CHAT_ID", None)
got = []
n = main.dizai_heng_flush(SYM, send=lambda t: got.append(t) or True)
h = main.gcs_read_json(main.dizai_heng_file(SYM), {})
fresh = [e for e in h["notices"] if not e.get("sent")]
check("沒設 TG 環境變數：Cloud Run 不發；太舊的標記不發；新的留給 GitHub 排程", n == 0 and not got
      and all(e.get("via") == "stale" for e in h["notices"] if e.get("sent")), (n, len(got)))
sig = client.get(f"/?view=futu_range&report=signals").get_json()
ids = [x["id"] for x in sig["signals"] if x["id"].startswith("heng:")]
check("report=signals 給出未發的地載・衡通知", ids == [e["id"] for e in fresh], (ids, [e["id"] for e in fresh]))
if ids:
    client.get(f"/?view=futu_range&report=signals&ack={ids[0]}")
    h = main.gcs_read_json(main.dizai_heng_file(SYM), {})
    check("ack 後標記已發（via github）", next(e for e in h["notices"] if e["id"] == ids[0]).get("via") == "github")
# 直接發
for e in h["notices"]:
    e["sent"] = False; e.pop("via", None)
h["notices"][-1]["time"] = h["last_bar"]
main.gcs_write_text(main.dizai_heng_file(SYM), json.dumps(h))
os.environ["TG_BOT_TOKEN"], os.environ["TG_CHAT_ID"] = "x", "y"
got = []
n = main.dizai_heng_flush(SYM, send=lambda t: got.append(t) or True)
h = main.gcs_read_json(main.dizai_heng_file(SYM), {})
check("有 TG 環境變數：直接發新的、標記 via cloud_run；report=signals 不再給（免重複）",
      n >= 1 and got and all(e.get("sent") for e in h["notices"]) and any(e.get("via") == "cloud_run" for e in h["notices"])
      and not [x for x in client.get("/?view=futu_range&report=signals").get_json()["signals"] if x["id"].startswith("heng:")], (n, len(got)))
got2 = []
main.dizai_heng_flush(SYM, send=lambda t: got2.append(t) or True)
check("已發的不會再發", not got2)
os.environ.pop("TG_BOT_TOKEN"); os.environ.pop("TG_CHAT_ID")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
