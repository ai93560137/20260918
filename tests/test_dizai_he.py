"""[R145] ⚡ 突破V（開市突破＋VHSI）跟研究 open_breakout.simulate 一致；🧩 地載・合兩個版本的合併盈虧、淨倉、頁面、策略總表。"""
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
import numpy as np

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




random.seed(5)
VH = {d: (random.uniform(15, 30), 22.0) for d in days}       # (上日 VHSI, 75 分位)：約一半日子高過
vfn = lambda d: VH.get(d)

print("=== 1. 突破V 引擎跟研究一致 ===")
st = main.dizai_que_new_state(days[0])
main.dizai_que_advance(st, bars, main._dz_ctx_fn(rows), lambda a, b: None, SYM, cfg=main.DIZAI_TUPO, vhsi_fn=vfn)
dsl = ob.day_slices(D)
ref = ob.simulate(D, dsl, 0.0025, "對面", 1, None, 1, lambda k, b: VH[D["days"][k]][0] > VH[D["days"][k]][1])
ref = [r for r in ref if r[0] >= 20]
a = [(D["days"][r[0]], r[3], r[2], round(r[1], 1)) for r in ref]
b = [(main.futu_session_of(t["entry_tk"], SYM), 1 if t["side"] == "買" else -1, t["reason"], round(t["pnl"], 1)) for t in st["trades"]]
check(f"研究 {len(a)} 筆、引擎 {len(b)} 筆，逐筆相同", a == b and len(a) >= 10, next(((x, y) for x, y in zip(a, b) if x != y), (len(a), len(b))))
check("止賺、止蝕、收市都出現", {"tp", "sl", "close"} <= {t["reason"] for t in st["trades"]}, {t["reason"] for t in st["trades"]})
check("突破V 不產生通知", not st.get("notices"))
check("VHSI 一年 75 分位跟 numpy 一樣", abs(main._pct_linear(list(range(1, 253)), 75) - float(np.percentile(np.arange(1, 253), 75))) < 1e-9)
rowsv = [(f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 10 + (i % 17)) for i in range(300)]
fv = main.dizai_vhsi_fn(rowsv)
dd = rowsv[280][0]
w = [r[1] for r in rowsv[280 - 252:280]]
check("vhsi_fn：只用日期早於今日的 252 日", fv(dd) == (rowsv[279][1], float(np.percentile(w, 75))) and fv(rowsv[100][0]) is None, fv(dd))

print("=== 2. 地載・合：兩個版本 ===")
parts = {"que": {"trades": [{"pnl": 100, "exit_tk": "2026-10-12 16:30:00"}], "pos": (0, 0), "started": True},
         "tupo": {"trades": [{"pnl": -50, "exit_tk": "2026-10-12 11:00:00"}], "pos": (1, 1), "started": True},
         "steady60": {"trades": [{"pnl": 30, "exit_tk": "2026-10-13 10:00:00"}], "pos": (-1, 2), "started": True},
         "bold_nq": {"trades": [], "pos": (0, 0), "started": True},
         "heng": {"trades": [{"pnl": -200, "exit_tk": "2026-10-12 12:00:00"}], "pos": (-1, 1), "started": True}}
he = main.dizai_he_data(SYM, parts)
check("不含衡：100 − 50 + 30 × 2 = +110；淨倉 1 − 2 × 2 = −3 張", he["ex"]["total_pts"] == 110 and he["ex"]["net_lots"] == -3, he["ex"])
check("含衡：再 −200 → −90；淨倉 −4；回撤 −250", he["in"]["total_pts"] == -90 and he["in"]["net_lots"] == -4 and he["in"]["max_dd_pts"] == -250, he["in"])

print("=== 3. 頁面、JSON、策略總表 ===")
FAKE.clear()
main.gcs_write_text(main.dizai_tupo_file(SYM), json.dumps({"version": main.DIZAI_QUE_VERSION, "start": "2026-10-12", "trades": [],
                     "pos": {"side": -1, "entry": 24800, "entry_tk": "2026-10-12 09:40:00", "sl": 24924, "tp": 24676}}))
client = main.app.test_client()
html = client.get("/?view=dizai").get_data(as_text=True)
check("地載陣頁：地載・合兩欄、突破V、穩60", all(x in html for x in ("地載・合（不含衡）", "地載・合（含衡）", "突破V", "地載・穩60")), html[:200])
check("地載・合在最上方", html.index("🧩 地載・合") < html.index("⚖️ 地載・衡"))
j = client.get("/?view=dizai&format=json").get_json()
check("JSON 有 he（兩版本）與 tupo", set(j["he"]) == {"ex", "in"} and "tupo" in j)
sj = client.get("/?view=strategies&format=json").get_json()
keys = {r["key"]: r for r in sj["rows"]}
check("策略總表：突破V 做空、合兩行（淨倉）、穩60 一行", keys["tupo"]["pos"]["side"] == -1 and "he_ex" in keys and "he_in" in keys and "dz_steady60" in keys)
check("合的淨倉不重複算入方向相反", not any("地載・合" in n for c in sj["conflicts"] for n in c["long"] + c["short"]))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
