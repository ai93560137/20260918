"""[R137] ⛰️ 地載陣：main.py 前向測試引擎跟回測（research/hsi_futures_range/rsi_avg_down.py 收市平倉版）逐筆一致；
推 K_1M → 重算當天 → 頁面與 JSON。"""
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

import argparse, json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path("/home/user/20260918/research/hsi_futures_range")))
import rsi_avg_down as research                   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

SYM = "HK.HSI_FRONT"
random.seed(7)


def minutes_of(day):
    """一個交易日的 1 分 K 時間：日市 09:16–12:00、13:01–16:30，夜市 17:16–翌日 03:00。"""
    d = datetime.strptime(day, "%Y-%m-%d")
    out, t = [], d.replace(hour=9, minute=16)
    while t <= d.replace(hour=16, minute=30):
        if not (d.replace(hour=12, minute=0) < t <= d.replace(hour=13, minute=0)):
            out.append(t)
        t += timedelta(minutes=1)
    t = d.replace(hour=17, minute=16)
    while t <= d + timedelta(days=1, hours=3):
        out.append(t)
        t += timedelta(minutes=1)
    return [x.strftime("%Y-%m-%d %H:%M:%S") for x in out]


def make_days(n, start="2026-08-03", px=24000.0):
    """n 個平日交易日的隨機遊走 1 分 K；每天開市跳空、日內有趨勢，好讓 1% 開閘與加倉都會發生。"""
    days, d, bars = [], datetime.strptime(start, "%Y-%m-%d"), []
    while len(days) < n:
        if d.weekday() < 5:
            day = d.strftime("%Y-%m-%d")
            days.append(day)
            px *= 1 + random.gauss(0, 0.008)
            drift = random.gauss(0, 0.6)
            for t in minutes_of(day):
                o = px
                px = max(1000.0, px + drift + random.gauss(0, 11))
                hi, lo = max(o, px) + abs(random.gauss(0, 4)), min(o, px) - abs(random.gauss(0, 4))
                bars.append({"time_key": t, "open": round(o), "high": round(hi), "low": round(lo),
                             "close": round(px), "volume": 10})
        d += timedelta(days=1)
    return days, bars


days, bars = make_days(40)
print("=== 1. 引擎跟回測逐筆一致（40 個交易日的模擬 1 分 K）===")
q = argparse.Namespace(rsi_n=14, rsi_hi=80, rsi_lo=20, move_pct=0.01, same_dir=False, session_close=True,
                       sl_pct=0.02, step=300, cost=1.0)
ref, _ = research.run(research.clean(bars), q)
by_day = {}
for b in research.clean(bars):
    by_day.setdefault(research.session_of(b["time_key"]), []).append(b)
mine = []
for i, day in enumerate(days):
    if i == 0:
        continue
    prev = by_day[days[i - 1]]
    res = main.dizai_simulate(by_day[day], [b["close"] for b in prev][-main.DIZAI_WARM:], prev[-1]["close"], True)
    mine += res["trades"]
    check_open = res["position"] is None
KEYS = ("entry_time", "side", "entry", "exit_time", "reason", "exit", "max_lots", "adds", "reduces", "pnl_pts")
RND = lambda t: tuple(round(t[k], 1) if k == "exit" else t[k] for k in KEYS)
a = [RND(t) for t in ref]
b = [RND(t) for t in mine]
check(f"回測 {len(a)} 筆、引擎 {len(b)} 筆，逐筆相同", a == b and len(a) >= 10,
      next(((x, y) for x, y in zip(a, b) if x != y), (len(a), len(b))))
check("有加倉、減倉、止賺、收市平倉的單（規則都走過）",
      any(t["adds"] for t in mine) and any(t["reduces"] for t in mine)
      and {"tp", "close"} <= {t["reason"] for t in mine}, {t["reason"] for t in mine})
check("收市後沒有未平倉", check_open)

print("=== 2. 未收市：最後一根不強制平倉，持倉帶止賺／止蝕／加倉位 ===")
day = next(d for d in days[1:] for t in mine if t["entry_time"][:10] == d and t["reason"] == "close")
prev = by_day[days[days.index(day) - 1]]
cut = [b for b in by_day[day] if b["time_key"] < next(t["exit_time"] for t in mine if t["entry_time"][:10] == day and t["reason"] == "close")]
res = main.dizai_simulate(cut, [b["close"] for b in prev][-main.DIZAI_WARM:], prev[-1]["close"], False)
pos = res["position"]
check("持倉中：有方向、張數、平均成本、止賺、止蝕、加倉位", pos and pos["lots"] >= 1 and pos["tp"] and pos["sl"] and pos["add_at"], pos)
if pos:
    s = 1 if pos["side"] == "買" else -1
    check("止蝕 = 平均成本逆向 2%；加倉位在逆向", abs(pos["sl"] - pos["avg"] * (1 - s * 0.02)) < 0.2 and s * (pos["avg"] - pos["add_at"]) > 0, pos)

print("=== 3. 推 K_1M → 重算當天 → 狀態檔、頁面、JSON ===")
client = main.app.test_client()
d1, d2 = days[-2], days[-1]
raw_by = {}
for b in bars:                                    # 推原始 K 線（帶成交量；成交量 0／空的會被引擎剔除）
    raw_by.setdefault(research.session_of(b["time_key"]), []).append(b)
for day in (d1, d2):
    rows = raw_by[day]
    for k in range(0, len(rows), 400):
        r = client.post("/", json={"action": "futu_data", "token": "tok", "source": "futu_opend:HK.HSI2610",
                                   "symbol": SYM, "kline_type": "K_1M", "data": rows[k:k + 400]})
        assert r.status_code == 200, r.get_data(as_text=True)
check("1 分 K 只封存、不蓋即時 5 分 K 快照", main.read_futu_snapshot(SYM) in ({}, None) or main.read_futu_snapshot(SYM).get("kline_type") != "K_1M")
HK = timezone(timedelta(hours=8))
now_mid = datetime.strptime(d2 + " 14:00", "%Y-%m-%d %H:%M").replace(tzinfo=HK)
FAKE.pop(main.dizai_file(SYM), None)
main.dizai_update(SYM, now=now_mid)
st = main.dizai_state(SYM)
check("今天未收市：記下 prev_close（上一交易日收市）、未定案", st and st["sessions"][d2]["prev_close"] == by_day[d1][-1]["close"]
      and st["sessions"][d2]["final"] is False and st["start"] == d2, st and {k: v for k, v in st["sessions"][d2].items() if k != "tail"})
now_after = datetime.strptime(d2, "%Y-%m-%d").replace(tzinfo=HK) + timedelta(days=1, hours=3, minutes=5)
main.dizai_update(SYM, now=now_after)
st = main.dizai_state(SYM)
exp = [t for t in mine if research.session_of(t["entry_time"]) == d2]
got = st["sessions"][d2]
check("收市後再算：定案，交易跟回測一致", got["final"] and [RND(t) for t in got["trades"]] == [RND(t) for t in exp],
      (got["final"], len(got["trades"]), len(exp)))
data = main.dizai_data(SYM, now=now_after)
check("JSON：今日策略有開閘線 = 上日收市 ±1%", data["status"] == "ok" and data["today"]["gate_up"] == round(got["prev_close"] * 1.01)
      and data["today"]["gate_down"] == round(got["prev_close"] * 0.99), data.get("today"))
check("JSON：統計只算已收市的日子", data["stats"]["days"] == 1 and data["stats"]["trades"] == len(exp), data["stats"])
r = client.get("/?view=dizai")
html = r.get_data(as_text=True)
check("頁面 200、有名稱、今日策略、前向測試、規則、免責", r.status_code == 200 and all(x in html for x in
      ("⛰️ 地載陣", "今日策略", "前向測試", "陣法（規則）", "不構成任何投資建議")), html[:300])
check("頁面不用登入（公開）、導覽列有地載陣", "nav-current'>⛰️ 地載陣" in html)
r = client.get("/?view=dizai&format=json")
check("?view=dizai&format=json 回 JSON", r.status_code == 200 and r.get_json()["status"] == "ok")
check("JSON 不含熱身收市價（tail）", all("tail" not in d for d in r.get_json()["days"]))

print("=== 4. 沒有數據時 ===")
FAKE.pop(main.dizai_file(SYM), None)
html = client.get("/?view=dizai").get_data(as_text=True)
check("空狀態頁面提示等本地腳本 v14", "v14" in html and "陣法（規則）" in html)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
