"""[R138] ⛰️ 地載陣（升跌 ≥ 2% 逆市＋加倍攤平＋留倉）兩組前向測試：main.py 引擎跟回測
（research/hsi_futures_range/dizai_martingale.simulate_mg）逐筆一致；分段推進＝一次推進；推 K_1M → 更新 → 頁面與 JSON。"""
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
import dizai_search as ds, rsi_avg_down as rad, dizai_martingale as mg, dizai_filters as fl   # noqa: E402

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
D = ds.prepare(bars); F = fl.day_features(D)
rows = [{"date": d, "high": float(D["h"][s:e].max()), "low": float(D["l"][s:e].min()), "close": float(D["c"][e - 1])}
        for d, s, e in zip(D["days"], D["starts"], D["ends"])]
tk = D["tk"]

print("=== 1. 引擎跟回測逐筆一致（兩組）===")
st = main.dizai_new_state(days[0])
main.dizai_advance(st, bars, main._dz_ctx_fn(rows))
SPEC = {"steady": ("confirm", 0.75, 30, 1000, None), "bold": ("cross", 1.0, 150, 3000, "run5_3")}
total_trades = 0
for key, (trig, g, tp, sl, flt) in SPEC.items():
    p = main.DIZAI_VARIANTS[key]
    check(f"{key} 參數跟回測一樣", (p["trig"], p["g_atr"], p["tp"], p["sl"], bool(p["run5"])) == (trig, g, tp, sl, bool(flt)))
    sig = ds.signals(D, "fade", trig, 0.02, "all")
    if flt:
        sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, flt)]
    ref = [x for x in mg.simulate_mg(D, sig, g, tp, sl_pts=sl) if x["reason"] != "open"]
    a = [(tk[x["fills"][0][0]], x["side"], x["reason"], x["lots"], round(x["pnl"], 1)) for x in ref]
    b = [(t["entry_tk"], 1 if t["side"] == "買" else -1, t["reason"], t["lots"], round(t["pnl"], 1)) for t in st["variants"][key]["trades"]]
    check(f"{key}：回測 {len(a)} 筆、引擎 {len(b)} 筆，逐筆相同", a == b and len(a) >= 3,
          next(((x, y) for x, y in zip(a, b) if x != y), (len(a), len(b))))
    total_trades += len(a)
allt = [t for v in st["variants"].values() for t in v["trades"]]
check("規則都走過：有加滿 4 張、有止賺、有止蝕", any(t["lots"] == 4 for t in allt) and {"tp", "sl"} <= {t["reason"] for t in allt},
      sorted({(t["reason"], t["lots"]) for t in allt}))

print("=== 2. 分段推進 = 一次推進 ===")
st2 = main.dizai_new_state(days[0])
cuts = sorted(random.sample(range(1, len(bars)), 25))
for a_, b_ in zip([0] + cuts, cuts + [len(bars)]):
    st2 = json.loads(json.dumps(st2))                         # 每段之間存一次 JSON（像寫回 GCS）
    main.dizai_advance(st2, bars[a_:b_], main._dz_ctx_fn(rows))
check("分 26 段推進（中間經過 JSON 存取）跟一次推進的交易與持倉完全一樣",
      json.dumps(st2["variants"], sort_keys=True) == json.dumps(json.loads(json.dumps(st["variants"])), sort_keys=True))

print("=== 3. 推 K_1M → dizai_update → 頁面與 JSON ===")
client = main.app.test_client()
FAKE.clear()
HK = timezone(timedelta(hours=8))
last3 = days[-3:]
main.gcs_write_text(main.futu_daily_file(SYM), json.dumps(
    [{"time_key": r["date"] + " 00:00:00", "open": r["close"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in rows[:-1]]))
by = {}
for b in raw:
    by.setdefault(b["time_key"][:10], []).append(b)
for day in last3[:2]:
    for k in range(0, len(by[day]), 400):
        r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": SYM, "kline_type": "K_1M",
                                   "source": "futu_opend:HK.HSI2610", "data": by[day][k:k + 400]})
        assert r.status_code == 200, r.get_data(as_text=True)
check("推 K_1M 時已自動推進（第一次：前兩個交易日熱身）", main.dizai_state(SYM) is not None)
FAKE.pop(main.dizai_file(SYM), None)
now = datetime.strptime(last3[-1] + " 12:00", "%Y-%m-%d %H:%M").replace(tzinfo=HK)
part = by[last3[-1]][:120]
main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, last3[-1]), json.dumps(part))
main.dizai_update(SYM, now=now)
s1 = main.dizai_state(SYM)
check("第一次：開始日 = 今天、最新一根（可能未收完）不處理", s1 and s1["start"] == last3[-1] and s1["last_bar"] == part[-2]["time_key"],
      s1 and (s1["start"], s1["last_bar"]))
check("前兩個交易日只熱身 RSI、不交易", s1 and s1["rsi"].get("value") is not None and not any(
      t["entry_tk"] < last3[-1] for v in s1["variants"].values() for t in v["trades"]))
part2 = by[last3[-1]][:200]
main.gcs_write_text(main.archive_blob_name("futu_k_1m", SYM, last3[-1]), json.dumps(part2))
main.dizai_update(SYM, now=now)
s2 = main.dizai_state(SYM)
check("第二次：接着推進到新的倒數第二根", s2["last_bar"] == part2[-2]["time_key"], s2["last_bar"])
main.dizai_update(SYM, now=now)
check("沒有新 K 線 → 不變", main.dizai_state(SYM)["last_bar"] == part2[-2]["time_key"])
data = main.dizai_data(SYM, now=now)
pl = data["plans"]["bold"]
check("今日策略：開閘線 = 上日收市 ±2%、加倉間距 = 1 × ATR20", pl["gate_up"] == round(pl["prev_close"] * 1.02)
      and pl["gate_down"] == round(pl["prev_close"] * 0.98) and abs(pl["step"] - pl["atr"]) < 0.11, pl)
check("穩的間距 = 0.75 × ATR20", abs(data["plans"]["steady"]["step"] - 0.75 * data["plans"]["steady"]["atr"]) < 0.11)
html = client.get("/?view=dizai").get_data(as_text=True)
check("頁面：四組、今日策略、前向、八年回測、curve fitting 警告、免責、期權保護、Sharpe、Nasdaq 篩選", all(x in html for x in
      ("地載・穩", "地載・進", "地載・穩＋Nasdaq", "地載・進＋Nasdaq", "Nasdaq 篩選", "今日策略", "前向測試", "八年回測", "curve fitting",
       "不構成任何投資建議", "RRR", "期權保護", "Sharpe")), html[:300])
check("頁面公開、導覽列有地載陣", "nav-current'>⛰️ 地載陣" in html)
j = client.get("/?view=dizai&format=json").get_json()
check("JSON：兩組的勝率／RRR 統計與持倉", j["status"] == "ok" and set(j["stats"]) == {"steady", "bold", "steady_nq", "bold_nq", "bold_protected"}
      and all("worst_rrr" in v for v in j["stats"].values()))

print("=== 4. 持倉顯示 ===")
pos_st = None
st3 = main.dizai_new_state(days[0])
for b in bars:
    main.dizai_advance(st3, [b], main._dz_ctx_fn(rows))
    if st3["variants"]["bold"]["pos"] and st3["variants"]["bold"]["pos"]["adds"] >= 1:
        pos_st = json.loads(json.dumps(st3)); break
check("找到一個加過倉的持倉時刻", pos_st is not None)
if pos_st:
    pos_st["mark"] = {"time": pos_st["last_bar"], "price": [x for x in bars if x["time_key"] == pos_st["last_bar"]][0]["close"]}
    plan = main.dizai_plan("bold", pos_st["variants"]["bold"], main.dizai_day_ctx(rows, pos_st["last_sess"]), pos_st["mark"], pos_st["last_sess"])
    pp = plan["position"]
    s_ = 1 if pp["side"] == "買" else -1
    check("持倉：止賺 = 平均成本 ±150、止蝕 = 平均成本 ∓3000、下次加 2 張", pp["tp"] == round(pp["avg"] + s_ * 150, 1)
          and pp["sl"] == round(pp["avg"] - s_ * 3000, 1) and pp["next_add_lots"] == 2 and pp["lots"] == 2, pp)

print("=== 4b. [R139] 地載・進的期權保護（紙上）跟回測一致 ===")
import dizai_options as do
import numpy as np
from datetime import datetime as _dt
class _V:                                             # 固定 VHSI 22
    def at(self, day): return 0.22
D["tday"] = np.array([(do.bar_time(t) - _dt(2000, 1, 1)).total_seconds() / 86400 for t in D["tk"]])
st4 = main.dizai_new_state(days[0])
main.dizai_advance(st4, bars, main._dz_ctx_fn(rows), vol_fn=lambda tk: 0.22)
sig = [(i, s_) for i, s_ in ds.signals(D, "fade", "cross", 0.02, "all") if fl.keep(F, D, i, s_, "run5_3")]
ref = [x for x in mg.simulate_mg(D, sig, 1.0, 150, sl_pts=3000) if x["reason"] != "open"]
mine = st4["variants"]["bold"]["trades"]
same_opt = True
for x, t in zip(ref, mine):
    x["sl_pts"] = 3000
    _, net, nb = do.protect_series(D, [x], _V(), 2, 1.0, 14)
    same_opt &= (nb == ("opt" in t)) and abs(net - t.get("opt", {}).get("pnl", 0.0)) < 0.01
check("加到 2 張就買期權、每筆期權盈虧跟 research protect_series 一樣", same_opt and any("opt" in t for t in mine))
check("期權不影響期貨部分（跟沒有 vol_fn 時逐筆相同）", [t["pnl"] for t in mine] == [t["pnl"] for t in st["variants"]["bold"]["trades"]])
t_ = next(t for t in mine if "opt" in t)
check("沽單買 Call、好單買 Put；行使價在價外 1 × ATR20", t_["opt"]["call"] == (t_["side"] == "沽")
      and ((t_["opt"]["K"] > t_["opt"]["S"]) if t_["opt"]["call"] else (t_["opt"]["K"] < t_["opt"]["S"])))
check("連期權盈虧 = 期貨 + 期權", abs(t_["pnl_protected"] - (t_["pnl"] + t_["opt"]["pnl"])) < 0.11)
check("穩不買期權", not any("opt" in t for t in st4["variants"]["steady"]["trades"]))
check("BS：平價 Call = 平價 Put（r = 0）、到期 = 內在值", abs(main._dz_bs(24000, 24000, 0.05, 0.2, True) - main._dz_bs(24000, 24000, 0.05, 0.2, False)) < 1e-6
      and main._dz_bs(24500, 24000, 0, 0.2, True) == 500 and main._dz_bs(24500, 24000, 0, 0.2, False) == 0)

print("=== 4c. [R140] Nasdaq 篩選：引擎跟 research dizai_cross 一致；GCS 的 Nasdaq 5 分 K 讀取 ===")
import dizai_cross as dc, dizai_more as dm
from datetime import timedelta as _td
rng = random.Random(5)
t0 = datetime.strptime(days[0], "%Y-%m-%d") - _td(days=3)
ut, uc, px = [], [], 15000.0
for k in range(int((len(days) + 60) * 1.5 * 96)):              # 15 分 K（UTC 收市時間）
    px *= 1 + rng.gauss(0, 0.002)
    ut.append(((t0 + _td(minutes=15 * (k + 1))) - dc.EPOCH).total_seconds() / 60)
    uc.append(px)
ut, uc = np.array(ut), np.array(uc)
def nq_fn(utc):
    k = np.searchsorted(ut, (utc - dc.EPOCH).total_seconds() / 60, "right") - 1
    return None if k < 0 else (float(uc[k]), dc.EPOCH + _td(minutes=float(ut[k])))
st5 = main.dizai_new_state(days[0])
main.dizai_advance(st5, bars, main._dz_ctx_fn(rows), nq_fn=nq_fn)
for key, trig, g, tp, sl, f5 in (("steady_nq", "confirm", 0.75, 30, 1000, None), ("bold_nq", "cross", 1.0, 150, 1500, "run5_3")):
    sig = dm.tf_signals(D, trig, 1)
    if f5: sig = [(i, s_) for i, s_ in sig if fl.keep(F, D, i, s_, f5)]
    allsig = len(sig)
    feat = dc.features(D, sig, (ut, uc)); sig = [(i, s_) for i, s_ in sig if dc.keep(feat, i, s_, "oppo")]
    ref = dm.run_seq(D, sig, g, tp, sl)
    a_ = [(tk[x["fills"][0][0]], x["side"], x["reason"], x["lots"], round(x["pnl"], 1)) for x in ref]
    b_ = [(t["entry_tk"], 1 if t["side"] == "買" else -1, t["reason"], t["lots"], round(t["pnl"], 1)) for t in st5["variants"][key]["trades"]]
    check(f"{key}：Nasdaq 擋走部分訊號（{len(sig)}／{allsig}），引擎 {len(b_)} 筆跟回測逐筆相同", a_ == b_ and len(sig) < allsig and len(a_) >= 1,
          next(((x, y) for x, y in zip(a_, b_) if x != y), (len(a_), len(b_))))
check("沒有 nq_fn（數據未到）→ Nasdaq 組照做，跟同參數不篩選一樣",
      [t["pnl"] for t in st["variants"]["steady_nq"]["trades"]] == [t["pnl"] for t in st["variants"]["steady"]["trades"]])
FAKE.clear()
nqb = [{"time_key": "2026-10-09 15:55:00", "open": 1, "high": 1, "low": 1, "close": 31000.0, "volume": 1},
       {"time_key": "2026-10-09 16:00:00", "open": 1, "high": 1, "low": 1, "close": 31100.0, "volume": 1}]
client.post("/", json={"action": "futu_data", "token": "tok", "symbol": "US.NQ_FRONT", "kline_type": "K_5M",
                       "source": "mt5_cfd:NAS100ft", "data": nqb, "options": []})
fn = main.dizai_nq_fn()
r1 = fn(datetime(2026, 10, 9, 19, 58))                          # 紐約 15:58（夏令 UTC−4）→ 只可用 15:55 那根
r2 = fn(datetime(2026, 10, 10, 1, 30))                          # 紐約 21:30 → 16:00 那根
check("GCS 的 Nasdaq 5 分 K：紐約時間轉 UTC，只取已收完的", r1 and r1[0] == 31000.0 and r2 and r2[0] == 31100.0
      and r2[1] == datetime(2026, 10, 9, 20, 0), (r1, r2))
check("Nasdaq 升跌：同一段時間、太舊就 None", abs(main.dizai_nq_move(fn, "2026-10-10 03:57:00", "2026-10-10 09:29:00") - (31100 / 31000 - 1)) < 1e-12
      and main.dizai_nq_move(fn, "2026-10-01 03:00:00", "2026-10-20 10:00:00") is None)

print("=== 5. 沒有數據 ===")
FAKE.pop(main.dizai_file(SYM), None)
html = client.get("/?view=dizai").get_data(as_text=True)
check("空狀態頁面提示等本地腳本 v14、仍列兩組回測", "v14" in html and "地載・進" in html and "八年回測" in html)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
