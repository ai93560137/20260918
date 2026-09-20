"""main.py 風控電閘改動的回歸測試。用假的 GCS（記憶體）跑，不碰雲端。"""
import io, json, os, sys, types, time

os.environ.setdefault("GCP_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")

# --- 攔截 google.cloud.storage，改用記憶體（先讓 functions_framework 正常載入）---
import functions_framework                      # noqa: E402  真的載入，別被假模組蓋掉
import google, google.cloud                      # noqa: E402  命名空間套件
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def exists(self): return self.name in FAKE
    def download_as_text(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0]
    def download_as_bytes(self, *a, **k):
        return self.download_as_text().encode("utf-8")
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

# 不要打外網
main.macro_news_session.status = lambda now=None: {"locked": False, "known": True, "reason": "test", "events": [], "warning": None}
main.ai_review_session.review = lambda meta: (True, "test")

from flask import Flask, request as flask_request
app = Flask(__name__)
OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

def post(body):
    with app.test_request_context("/", method="POST", json=body):
        return main.receive_tradingview_signal(flask_request)
def get(qs=""):
    with app.test_request_context("/" + qs, method="GET"):
        return main.receive_tradingview_signal(flask_request)
def body_of(resp):
    r = resp[0] if isinstance(resp, tuple) else resp
    return r if isinstance(r, str) else r.get_data(as_text=True)

print("\n=== 1. 風控電閘：缺數據要 fail-closed ===")
FAKE.clear()
st = main.default_gate_state()
r = main.evaluate_risk_gate({}, st)
check("空快照 → 不開閘", r["open"] is False)
check("五道關卡都有回報", len(r["checks"]) == 5, r["checks"])
check("理由寫明是哪幾關", "波動水位" in r["reason"], r["reason"])

print("\n=== 2. 五關全過 → 開閘 ===")
good = {"equity": 20000.0, "balance": 20000.0, "daily_pnl": 0.0, "net_lots": 0.0,
        "currency": "HKD", "m15_ohlc": {"close": 4300.0, "atr_m15": 8.0}}
# 4300 * 0.10% = 4.3 → atr 8.0 => 0.186% 過關
open_now = main.GoldIndicatorSession.is_gold_market_open()
r = main.evaluate_risk_gate(good, st)
check(f"開市時五關全過（現在 is_open={open_now}）",
      r["open"] is open_now, r["reason"])
check("ATR% 算得對", abs(r["atr_pct"] - 8.0/4300*100) < 1e-9, r["atr_pct"])

print("\n=== 2b. 強制開市，驗證真正的開閘路徑 ===")
_real_open = main.GoldIndicatorSession.is_gold_market_open
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
r = main.evaluate_risk_gate(good, st)
check("強制開市後五關全過 → 開閘", r["open"] is True, r["reason"])
check("五關全部 ok", all(c["ok"] for c in r["checks"]), [c for c in r["checks"] if not c["ok"]])
FAKE.clear()
resp = post({"action": "check_gate", "token": "tok", **good})
code = resp[1] if isinstance(resp, tuple) else 200
st_open = main.read_gate_state()
check("心跳後 armed=True", st_open.get("armed") is True, st_open.get("last_reason"))
check("心跳回應 200（沒有 M1 → monitoring）", code == 200, code)
check("gate_summary 顯示放行", main.gate_summary(st_open)[0] == "pos", main.gate_summary(st_open))
r2 = get("?view=dashboard")
html = body_of(r2)
check("儀表板有風控五關表", "風控電閘五關" in html)
check("儀表板標明雷達不參與開閘", "不參與開閘" in html)
main.GoldIndicatorSession.is_gold_market_open = _real_open

print("\n=== 3. 波動不足 → 鎖 ===")
low = dict(good, m15_ohlc={"close": 4300.0, "atr_m15": 2.0})   # 0.0465% < 0.10%
r = main.evaluate_risk_gate(low, st)
check("低波動不開閘", r["open"] is False)
check("原因指名波動", "波動水位" in r["reason"], r["reason"])

print("\n=== 4. 曝險上限（空城計公式）===")
# 回撤 10% → 可用 = (20-10)/14 = 0.714x
dd = dict(good, equity=18000.0, balance=20000.0, net_lots=0.05)
r = main.evaluate_risk_gate(dd, st)
ex = [c for c in r["checks"] if c["key"] == "exposure"][0]
check("回撤 10% 時可用曝險 ≈ 0.71x", abs(r["exposure_cap"] - (20.0-10.0)/14.0) < 1e-6,
      r["exposure_cap"])
# 回撤 20% → 可用 0
dd2 = dict(good, equity=16000.0, balance=20000.0, net_lots=0.01)
r2 = main.evaluate_risk_gate(dd2, st)
check("回撤到容忍上限 → 可用曝險 0、不開閘", r2["exposure_cap"] == 0.0 and not r2["open"],
      (r2["exposure_cap"], r2["reason"]))

print("\n=== 5. 單日虧損上限 ===")
bad = dict(good, daily_pnl=-700.0)    # 20000 * 3% = 600
r = main.evaluate_risk_gate(bad, st)
check("虧超過 3% → 鎖", not r["open"] and "單日虧損" in r["reason"], r["reason"])
r = main.evaluate_risk_gate(dict(good, daily_pnl=-500.0), st)
check("虧 500 未達上限 → 這關過",
      [c for c in r["checks"] if c["key"] == "daily"][0]["ok"])

print("\n=== 6. 訓練節奏 ===")
st2 = main.default_gate_state()
st2["trades_today"] = {"ny_date": main._ny_date(), "count": main.TRAINING_MAX_PER_DAY}
r = main.evaluate_risk_gate(good, st2)
check("今日額滿 → 鎖", not r["open"] and "訓練節奏" in r["reason"], r["reason"])
st3 = main.default_gate_state()
st3["trades_today"] = {"ny_date": "1999-01-01", "count": 99}
check("昨天的計數不算今天", main.trades_today_count(st3) == 0)

print("\n=== 7. gate_status 不再看 regime ===")
s = main.default_gate_state(); s["armed"] = True; s["regime"] = main.REGIME_RANGE
check("armed + 橫行 → 仍 OPEN（RISK 模式）", main.gate_status(s) == "OPEN")
s["armed"] = False
check("未 armed → LOCK", main.gate_status(s) == "LOCK")
s["armed"] = True; s["hard_lock"] = {"reason": "x", "until_ts": None}
check("硬鎖壓過一切", main.gate_status(s) == "LOCK")

print("\n=== 8. 只做多 ===")
FAKE.clear()
res = main.execute_signal({"signal": "SELL", "price": 4300.0, "kind": "FIRST",
                           "ticker": "XAUUSD", "direction": "DOWN"},
                          {"m15_ohlc": {"close": 4300.0, "atr_m15": 8.0}}, {}, 50.0,
                          {"locked": False, "known": True})
check("空單被擋", res["status"] == "long_only_rejected", res)

print("\n=== 9. 心跳端到端 ===")
FAKE.clear()
resp = post({"action": "check_gate", "token": "tok", **good})
code = resp[1] if isinstance(resp, tuple) else 200
st_after = main.read_gate_state()
check("心跳有寫入風控評估", isinstance(st_after.get("risk"), dict) and st_after["risk"].get("checks"))
check(f"開市={open_now} 時 armed={st_after.get('armed')}", bool(st_after.get("armed")) is open_now)
check("回應碼合理", code in (200, main.LOCKED_HTTP_STATUS), code)

FAKE.clear()
resp = post({"action": "check_gate", "token": "tok", **low})
code = resp[1] if isinstance(resp, tuple) else 200
check("低波動心跳 → 403", code == main.LOCKED_HTTP_STATUS, code)

print("\n=== 10. 既有功能沒被弄壞 ===")
FAKE.clear()
for view, label in (("dashboard", "控制台"), ("gates", "電閘頁"), ("info", "資訊頁"),
                    ("gates_app", "gates.html"), ("order_app", "order.html"),
                    ("jinnang_sheet", "錦囊執行單"), ("jinnang_tracker", "錦囊進度表")):
    try:
        r = get(f"?view={view}")
        c = r[1] if isinstance(r, tuple) else 200
        check(f"{label} 回應 {c}", c == 200, c)
    except Exception as e:
        check(f"{label}", False, f"{type(e).__name__}: {e}")

r = get("?view=gates&format=json")
payload = json.loads(body_of(r))
check("gates JSON 帶 driver", payload["gate"]["driver"] == "RISK", payload["gate"].get("driver"))
check("gates JSON 帶 long_only", payload["gate"]["long_only"] is True)
check("gates JSON 帶 risk", isinstance(payload["gate"]["risk"], dict))
check("系統參數頁有風控電閘一組",
      any(g["group"].startswith("🛡️") for g in payload["system_params"]))

r = get("?view=jinnang&format=json")
check("錦囊 API 仍可讀", (r[1] if isinstance(r, tuple) else 200) == 200)

print("\n=== 11. GATE_DRIVER=REGIME 可回退 ===")
main.GATE_DRIVER = "REGIME"
s = main.default_gate_state(); s["armed"] = True; s["regime"] = main.REGIME_TREND; s["dir"] = "UP"
check("回退後 TREND+armed → OPEN", main.gate_status(s) == "OPEN")
s["regime"] = main.REGIME_RANGE
check("回退後 RANGE → LOCK", main.gate_status(s) == "LOCK")
main.GATE_DRIVER = "RISK"

print(f"\n{'='*50}\n通過 {OK} / 失敗 {FAIL}\n{'='*50}")
sys.exit(1 if FAIL else 0)
