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
check(f"回撤 10% 時可用曝險 = (20−10)/{main.WORST_GAP_PCT:g} = "
      f"{(20.0-10.0)/main.WORST_GAP_PCT:.2f}x",
      abs(r["exposure_cap"] - (20.0-10.0)/main.WORST_GAP_PCT) < 1e-6, r["exposure_cap"])
# 回撤 20% → 可用 0
dd2 = dict(good, equity=16000.0, balance=20000.0, net_lots=0.01)
r2 = main.evaluate_risk_gate(dd2, st)
check("回撤到容忍上限 → 可用曝險 0、不開閘", r2["exposure_cap"] == 0.0 and not r2["open"],
      (r2["exposure_cap"], r2["reason"]))

print("\n=== 4b. 曝險【數值】本身算得對（R74：之前只測了上限，沒測曝險）===")
# 1 盎司 = 0.01 手 × 100 oz/手 × 4300 = US$4,300 名義
# 戶口 HK$20,000 = US$2,564  →  曝險 1.677x
# [R79] 曝險算的是【下單之後】：持倉 + 即將下的那一張
ex_case = dict(good, net_lots=0.0, equity=20000.0, balance=20000.0)
r = main.evaluate_risk_gate(ex_case, main.default_gate_state())
want = main.ORDER_SIZE * main.CONTRACT_SIZE * 4300.0 / (20000.0 * main.FX_TO_USD["HKD"])
check(f"空手 → 下單後 1 盎司 = {want:.3f}x", abs(r["exposure"] - want) < 1e-9,
      f"得到 {r['exposure']}")
check("這個數字落在 1.6~1.8（和錦囊面板的 1.71x 對得上）", 1.6 < r["exposure"] < 1.8, r["exposure"])
r2 = main.evaluate_risk_gate(dict(ex_case, net_lots=0.01), main.default_gate_state())
check(f"已有 1 盎司 → 下單後 2 盎司 = {2*want:.2f}x，超過可用 "
      f"{min(main.EXPOSURE_HARD_CAP, 20.0/main.WORST_GAP_PCT):.2f}x → 這一關不過",
      not [c for c in r2["checks"] if c["key"] == "exposure"][0]["ok"], r2["reason"])

print("\n=== 4c. 回撤要對歷史高水位（R74）===")
st_hw = main.default_gate_state(); st_hw["equity_peak"] = 25000.0
# [R90] 高水位要標明是用哪一把尺量的，沒標記會被當成換尺前的舊值丟掉。
st_hw["equity_peak_basis"] = main.EQUITY_PEAK_BASIS
# 虧損已實現 → balance 也跟著掉，max(equity,balance) 會讀成 0% 回撤
r = main.evaluate_risk_gate(dict(good, equity=20000.0, balance=20000.0), st_hw)
check("已實現虧損仍算得出 20% 回撤", abs(r["drawdown_pct"] - 20.0) < 1e-9, r["drawdown_pct"])
check("回撤到容忍上限 → 可用曝險 0", r["exposure_cap"] == 0.0, r["exposure_cap"])
r2 = main.evaluate_risk_gate(dict(good, equity=30000.0, balance=30000.0), st_hw)
check("創新高後高水位跟上", abs(r2["equity_peak"] - 30000.0) < 1e-9, r2["equity_peak"])
check("創新高時回撤 0", r2["drawdown_pct"] == 0.0, r2["drawdown_pct"])

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

print("\n=== 6b. 沒變動就不要寫 GCS（R75）===")
FAKE.clear()
_ro = main.GoldIndicatorSession.is_gold_market_open
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
post({"action": "check_gate", "token": "tok", **good})
gen1 = FAKE.get(main.GATE_STATE_FILE, (None, 0))[1]
for _ in range(5):
    post({"action": "check_gate", "token": "tok", **good})
gen2 = FAKE.get(main.GATE_STATE_FILE, (None, 0))[1]
check(f"5 次相同心跳沒有再寫入（generation {gen1} → {gen2}）", gen1 == gen2, (gen1, gen2))
post({"action": "check_gate", "token": "tok", **low})      # 波動掉下去 = 真的變了
gen3 = FAKE.get(main.GATE_STATE_FILE, (None, 0))[1]
check(f"狀態真的變了才寫（{gen2} → {gen3}）", gen3 > gen2, (gen2, gen3))
main.GoldIndicatorSession.is_gold_market_open = _ro

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

html = body_of(get("?view=dashboard"))
check("儀表板有錦囊區塊", "錦囊 v4 進場引擎" in html)
check("儀表板寫明出場在 EA", "InpHoldMinutes" in html)
check("儀表板寫明優勢未證實", "優勢未被證實" in html)

r = get("?view=gates&format=json")
payload = json.loads(body_of(r))
check("gates JSON 帶 driver", payload["gate"]["driver"] == "RISK", payload["gate"].get("driver"))
check("gates JSON 帶 long_only", payload["gate"]["long_only"] is True)
check("gates JSON 帶 risk", isinstance(payload["gate"]["risk"], dict))
check("gates JSON 帶 entry_engine", payload["gate"]["entry_engine"] == "JINNANG",
      payload["gate"].get("entry_engine"))
check("系統參數頁有錦囊一組",
      any(g["group"].startswith("🎯") for g in payload["system_params"]))
check("系統參數頁有風控電閘一組",
      any(g["group"].startswith("🛡️") for g in payload["system_params"]))

r = get("?view=jinnang&format=json")
check("錦囊 API 仍可讀", (r[1] if isinstance(r, tuple) else 200) == 200)

print("\n=== 10b. 錦囊 v4 進場引擎接線 ===")
check("ENTRY_ENGINE 預設是 JINNANG", main.ENTRY_ENGINE == "JINNANG", main.ENTRY_ENGINE)
v = main.JinnangSession.evaluate([])
check("沒有歷史時回『累積中』", v["ready"] is False and "累積中" in v["text"], v)
# 造一段假的 M15：先橫行 120 根，再向上突破
import math as _m
bars=[]; t0=1700000000
for i in range(150):
    px = 4300.0 + (0.6 if i % 2 else -0.6)          # 窄幅橫行
    bars.append(dict(time=t0+i*900, open=px, high=px+3.0, low=px-3.0, close=px))
v = main.JinnangSession.evaluate(bars)
check("橫行時不出訊號", v.get("signal") is None, v.get("text"))
check("橫行時有區間", v.get("box_live") is True, v.get("box_live"))
top = v.get("box_top")
brk = top + 40.0
bars.append(dict(time=t0+150*900, open=4300.0, high=brk+2, low=4299.0, close=brk))
v2 = main.JinnangSession.evaluate(bars)
check("向上突破 → BUY", v2.get("signal") == "BUY", v2.get("text"))
check("訊號帶 ATR%", v2.get("atr_pct") is not None and v2["atr_pct"] > 0, v2.get("atr_pct"))
_f = main.VOL_FLOOR_ATR_PCT
main.VOL_FLOOR_ATR_PCT = 99.0
v3 = main.JinnangSession.evaluate(bars)
check("波動門檻擋掉突破", v3.get("signal") is None and "波動不足" in v3["text"], v3.get("text"))
main.VOL_FLOOR_ATR_PCT = _f
bars2 = bars[:-1] + [dict(time=t0+150*900, open=4300.0, high=4301.0,
                          low=v.get("box_bot")-40.0, close=v.get("box_bot")-30.0)]
v4 = main.JinnangSession.evaluate(bars2)
check("向下跌破 → 不做（只做多）", v4.get("signal") is None and "只做多" in v4["text"], v4.get("text"))
# 同一根只評估一次
FAKE.clear()
check("claim_m15_bar 第一次 True", main.claim_m15_bar(t0+150*900) is True)
check("claim_m15_bar 第二次 False", main.claim_m15_bar(t0+150*900) is False)
# 有持倉時不加碼
r = main.jinnang_entry({"buy_lots":0.01,"sell_lots":0.0,"equity":20000.0}, main.now_ts(), frozenset(),
                       main.default_order_params())
check("有持倉 → 不加碼", isinstance(r, str) and "不加碼" in r, r)
# build_order：tp_distance=None 不送 TP
o = main.build_order({"signal":"BUY","ticker":"XAUUSD","price":4300.0,"sl_distance":50.0,
                      "tp_distance":None}, main.default_order_params())
tpf = main.distance_fields(main.default_order_params())["tp"]
check("tp_distance=None → 封包不含 TP 欄位", tpf not in o, list(o))
o2 = main.build_order({"signal":"BUY","ticker":"XAUUSD","price":4300.0,"sl_distance":50.0},
                      main.default_order_params())
check("舊引擎照常有 TP 欄位", tpf in o2, list(o2))

print("\n=== 10c. 兩頁的資料來源跟著引擎走 ===")
pl = json.loads(body_of(get("?view=gates&format=json")))
gates = pl["switches"]["gates"]
na = [g["key"] for g in gates if not g["applies"]]
ap = [g["key"] for g in gates if g["applies"]]
check("gates JSON 每個關卡都有 applies", all("applies" in g for g in gates))
check(f"錦囊只用 risk_cap/news/ai（得到 {sorted(ap)}）",
      set(ap) == {"risk_cap", "news", "ai"}, sorted(ap))
check(f"其餘 {len(na)} 個標成不適用且帶說明",
      len(na) > 0 and all(g["na_note"] for g in gates if not g["applies"]), na)
check("switches 帶 engine", pl["switches"]["engine"] == "JINNANG", pl["switches"].get("engine"))

op = json.loads(body_of(get("?view=order&format=json")))
pv = op["preview"]
check("order 預覽標明引擎", pv.get("engine") == "JINNANG", pv.get("engine"))
check("order 預覽說明不送 TP", "不送 TP" in (pv.get("engine_note") or ""), pv.get("engine_note"))
tpf = main.distance_fields(main.default_order_params())["tp"]
check("order 預覽封包真的沒有 TP 欄位", tpf not in pv["order"], list(pv["order"]))
check("order 預覽止損 = ATR × JN_DISASTER_SL_ATR",
      abs(pv["sl_distance"] - max(main.MIN_SL_DISTANCE,
          round(pv["atr_m15"] * main.JN_DISASTER_SL_ATR, 2))) < 1e-9, pv["sl_distance"])

_e = main.ENTRY_ENGINE
main.ENTRY_ENGINE = "PYRAMID"
pv2 = main.order_preview(main.default_order_params())
check("回退 PYRAMID 後預覽又有 TP", tpf in pv2["order"], list(pv2["order"]))
main.ENTRY_ENGINE = _e

for f, must in (("gates.html", ["gate.driver", "entry_engine", "gate.applies", "目前引擎不使用"]),
                ("order.html", ["engine_note", "param-na", "不讀這個值"])):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    for m in must:
        check(f"{f} 含「{m}」", m in txt)

print("\n=== 10d. 七頁導覽列一致 ===")
VIEWS = [v for v, _ in main.PAGE_LINKS]
check(f"main.py 的 PAGE_LINKS 有 7 頁（{len(VIEWS)}）", len(VIEWS) == 7, VIEWS)
for f in ("jinnang_sheet.html", "jinnang_tracker.html", "gates.html", "order.html"):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    self_view = f[:-5] if f.startswith("jinnang") else f[:-5] + "_app"
    # 當前頁不該連到自己（下面另有一項專門檢查），所以從必須出現的清單裡排除
    miss = [v for v in VIEWS if v != self_view and v not in txt]
    check(f"{f} 連到其餘 6 頁", not miss, f"缺 {miss}")
for f, cur in (("jinnang_sheet.html", "錦囊執行單"), ("jinnang_tracker.html", "錦囊九十筆")):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    check(f"{f} 自己那格標成 current",
          f'class="nav-link nav-current" aria-current="page">✅ {cur}<' in txt
          or f'class="nav-link nav-current" aria-current="page">🗒️ {cur}<' in txt)
    check(f"{f} 沒有連到自己", f'href="?view={f[:-5]}"' not in txt)
# 兩頁實際 serve 出來要含全部連結
for v in ("jinnang_sheet", "jinnang_tracker"):
    html = body_of(get("?view=" + v))
    miss = [x for x in VIEWS if x != v and ("?view=" + x) not in html]
    check(f"?view={v} 實際輸出含其餘 6 個連結", not miss, f"缺 {miss}")

# 七頁的導覽列要用同一組 class（統一外觀）
mainsrc = io.open("/home/user/20260918/main.py", encoding="utf-8").read()
for cls in (".nav-links", ".nav-link", ".nav-current"):
    check(f"main.py 定義 {cls}", cls + "{" in mainsrc or cls + " {" in mainsrc)
for f in ("jinnang_sheet.html", "jinnang_tracker.html", "gates.html", "order.html"):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    check(f"{f} 用 nav-link 膠囊樣式", 'class="nav-link' in txt or "'nav-link" in txt or "nav-link " in txt)
    check(f"{f} 沒有殘留舊的方塊 nav", "\n.nav{display:flex" not in txt)
for f in ("jinnang_sheet.html", "jinnang_tracker.html"):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    check(f"{f} 淺色值與 main.py 相同", "--nav-bg:#EEF4FF" in txt and "--nav-on-bg:#0F62FE" in txt)
    check(f"{f} 深色模式有自己的導覽列配色", txt.count("--nav-bg:#1B2430") == 2, txt.count("--nav-bg:#1B2430"))

# CSS 大括號配對 —— 上一次改導覽列時弄丟過 3 個，加進來擋住同一個錯
import re as _re
for f in ("jinnang_sheet.html", "jinnang_tracker.html", "gates.html", "order.html"):
    txt = io.open("/home/user/20260918/" + f, encoding="utf-8").read()
    css = "".join(_re.findall(r"<style>(.*?)</style>", txt, _re.S))
    check(f"{f} CSS 大括號配對", css.count("{") == css.count("}"),
          f'{css.count("{")}/{css.count("}")}')
    # 每個 :root / @media 主題區塊都要自己收口，否則後面的規則會被吃進去。
    # 算括號平衡，不看 } 在哪一行（執行單是多行格式，收口在下一行）。
    for blk in ("prefers-color-scheme:dark", 'data-theme="dark"'):
        i = css.find(blk)
        if i < 0:
            continue
        depth, closed, j = 0, False, i
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth <= 0:
                    closed = True
                    break
            j += 1
        tail = css[j + 1:j + 400]
        check(f"{f} 的 {blk} 區塊有收口且沒吃掉後面的規則",
              closed and ("*{box-sizing" in tail or "body{" in tail or ".nav-link" in tail),
              tail[:40].replace(chr(10), " "))

print("\n=== 10e. R79：倉位大小、最壞跳空、下單後曝險 ===")
import math as _m
check("WORST_GAP_PCT = 7.6（150 分鐘持倉的實測最壞逆行 7.55%）",
      abs(main.WORST_GAP_PCT - 7.6) < 1e-9, main.WORST_GAP_PCT)
# R81：不能一開始就鎖死。1 盎司 × 最壞跳空 必須留得下回撤空間。
_expo = main.ORDER_SIZE * main.CONTRACT_SIZE * 4378.0 / (20000.0 * main.FX_TO_USD["HKD"])
_stop = main.DD_TOLERANCE_PCT - _expo * main.WORST_GAP_PCT
check(f"HK$20,000 / 金價 4,378 不會一開始就鎖死（回撤 {_stop:.1f}% 才停）",
      _stop > 3.0, f"{_stop:.2f}%")
# 空手卻超標時，訊息要說清楚是死鎖
_g = main.WORST_GAP_PCT
main.WORST_GAP_PCT = 40.0
rr = main.evaluate_risk_gate(dict(good, net_lots=0.0, equity=20000.0, balance=20000.0),
                             main.default_gate_state())
_ex = [c for c in rr["checks"] if c["key"] == "exposure"][0]
check("空手就超標時寫明『等下去沒有用』", not _ex["ok"] and "等下去沒有用" in _ex["detail"],
      _ex["detail"][:60])
check("並給出需要多少本金", "本金要 ≥" in _ex["detail"], _ex["detail"][-40:])
main.WORST_GAP_PCT = _g
check("JN_SIZING_ADVERSE_PCT = 1.10（實測最壞單筆虧損 1.097%）",
      abs(main.JN_SIZING_ADVERSE_PCT - 1.10) < 1e-9, main.JN_SIZING_ADVERSE_PCT)
# 曝險要看下單之後
r = main.evaluate_risk_gate(dict(good, net_lots=0.0, equity=20000.0, balance=20000.0),
                            main.default_gate_state())
want = (0.0 + main.ORDER_SIZE) * main.CONTRACT_SIZE * 4300.0 / (20000.0 * main.FX_TO_USD["HKD"])
check(f"空手時曝險已計入即將下的那張（{want:.2f}x）",
      abs(r["exposure"] - want) < 1e-9, r["exposure"])
check("1 盎司在零回撤時過得了曝險關",
      [c for c in r["checks"] if c["key"] == "exposure"][0]["ok"], r["reason"])
# 金價上限
c = main.jinnang_price_ceiling(20000.0, "HKD")
check(f"HK$20,000 的金價上限 ≈ US$4,662（得到 {c:,.0f}）", 4600 < c < 4720, c)
check("本金加倍，上限也加倍",
      abs(main.jinnang_price_ceiling(40000.0, "HKD") - 2 * c) < 1e-6)
# 端到端：一個真的訊號要下得了單
FAKE.clear()
_ro = main.GoldIndicatorSession.is_gold_market_open
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
bars2 = []
for i in range(210):
    px = 4300.0 + (0.6 if i % 2 else -0.6)
    bars2.append(dict(time=1700000000 + i * 900, open=px, high=px + 3.0, low=px - 3.0, close=px))
v = main.JinnangSession.evaluate(bars2)
brk = v["box_top"] + 40.0
# [R80] EA 送已收盤的 K 線 → 突破根就是歷史的最後一根
bars2.append(dict(time=1700000000 + 210 * 900, open=4300.0, high=brk + 2, low=4299.0, close=brk))
main.gcs_write_text(main.M15_HISTORY_FILE, json.dumps(bars2))
vv = main.JinnangSession.evaluate(bars2)
pay = dict(good, buy_lots=0.0, sell_lots=0.0, net_lots=0.0,
           m15_ohlc={"close": brk, "atr_m15": vv["atr"]})
cand = main.jinnang_entry(pay, main.now_ts(), frozenset(), main.default_order_params())
check("訊號 → 真的產生候選單（不再被 0.00 手擋掉）", isinstance(cand, dict), cand)
if isinstance(cand, dict):
    o = main.build_order(cand, main.default_order_params())
    check("封包 action = BUY", o["action"] == "BUY", o.get("action"))
    check("封包 size = 0.01", float(o["size"]) == 0.01, o.get("size"))
    tpf = main.distance_fields(main.default_order_params())["tp"]
    check("封包沒有 TP", tpf not in o, list(o))
main.GoldIndicatorSession.is_gold_market_open = _ro

print("\n=== 10f. R80：EA 送的是已收盤的 M15 ===")
check("JN_M15_LAST_CLOSED 預設 True（配合 V22/V23 的 CopyRates shift=1）",
      main.JN_M15_LAST_CLOSED is True, main.JN_M15_LAST_CLOSED)
FAKE.clear()
_ro2 = main.GoldIndicatorSession.is_gold_market_open
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
b3 = []
for i in range(210):
    px = 4300.0 + (0.6 if i % 2 else -0.6)
    b3.append(dict(time=1700000000 + i * 900, open=px, high=px + 3.0, low=px - 3.0, close=px))
vv = main.JinnangSession.evaluate(b3)
brk = vv["box_top"] + 40.0
b3.append(dict(time=1700000000 + 210 * 900, open=4300.0, high=brk + 2, low=4299.0, close=brk))
# 歷史的【最後一根】就是突破根（EA 送已收盤的，所以它就在最後）
main.gcs_write_text(main.M15_HISTORY_FILE, json.dumps(b3))
pay3 = dict(good, buy_lots=0.0, sell_lots=0.0, net_lots=0.0,
            m15_ohlc={"close": brk, "atr_m15": vv["atr"]})
c3 = main.jinnang_entry(pay3, main.now_ts(), frozenset(), main.default_order_params())
check("突破根在歷史最後一根時，同一次心跳就進場（不晚 15 分鐘）",
      isinstance(c3, dict), c3)
# 切成 False 時要丟掉最後一根 → 同一份資料就不該出訊號
_f = main.JN_M15_LAST_CLOSED
main.JN_M15_LAST_CLOSED = False
FAKE.clear(); main.gcs_write_text(main.M15_HISTORY_FILE, json.dumps(b3))
c4 = main.jinnang_entry(pay3, main.now_ts(), frozenset(), main.default_order_params())
check("JN_M15_LAST_CLOSED=0 時會丟掉最後一根（同一份資料不出訊號）",
      not isinstance(c4, dict), c4)
main.JN_M15_LAST_CLOSED = _f
main.GoldIndicatorSession.is_gold_market_open = _ro2

print("\n=== 10g. 空戶口（real 但沒錢）會鎖死，拿不到任何資料 ===")
_ro3 = main.GoldIndicatorSession.is_gold_market_open
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
g2 = dict(good, m15_ohlc={"close": 4378.0, "atr_m15": 8.0})
sz = max(main.MIN_SL_DISTANCE, round(4378.0 * main.JN_SIZING_ADVERSE_PCT / 100, 2))
for eq, want_open in ((0.0, False), (100.0, False), (5000.0, False), (20000.0, True)):
    st2 = main.default_gate_state()
    rr = main.evaluate_risk_gate(dict(g2, equity=eq, balance=eq), st2)
    lots, _ = main.PureGCPPyramidingSession.calculate_max_lots(eq, "HKD", 4378.0, sz)
    tradable = rr["open"] and lots >= main.ORDER_SIZE
    check(f"本金 {eq:,.0f} → {'下得了單' if want_open else '下不了單'}",
          tradable is want_open, f"open={rr['open']} lots={lots}")
# 空戶口的理由要寫明是「缺淨值」，不是別的
r0 = main.evaluate_risk_gate(dict(g2, equity=0.0, balance=0.0), main.default_gate_state())
check("空戶口的曝險關理由是『缺淨值』",
      "缺淨值" in [c for c in r0["checks"] if c["key"] == "exposure"][0]["detail"])
check("空戶口時 jinnang_entry 直接拒絕",
      isinstance(main.jinnang_entry(dict(g2, equity=0.0), main.now_ts(), frozenset(),
                                    main.default_order_params()), str))
main.GoldIndicatorSession.is_gold_market_open = _ro3

print("\n=== 10h. R82：金鑰不可以寫在原始碼裡（這個 repo 是公開的）===")
src = io.open("/home/user/20260918/main.py", encoding="utf-8").read()
check("main.py 的 api_key 沒有寫死的預設值",
      'os.environ.get("WEBHOOK_API_KEY", "")' in src)
import re as _r2
hexes = set(_r2.findall(r'"[0-9a-f]{16}"', src))
check(f"原始碼裡沒有 16 位 hex 的疑似金鑰（找到 {len(hexes)} 個）", not hexes, hexes)
# 金鑰字面值不可出現在 repo 裡。只看 key/token/secret/api 附近的 hex，
# 否則會誤抓 SHA 雜湊（基準檔的 sha256、去重用的 digest 等）。
import glob as _gl, os as _os
_hits = []
_pat = _r2.compile(r'(?i)(api[_-]?key|token|secret|password)["\']?\s*[:=]\s*["\']([0-9a-f]{16,})["\']')
for _f in _gl.glob("/home/user/20260918/**/*", recursive=True):
    if _os.path.isdir(_f) or "/.git/" in _f or "/personal/" in _f: continue
    if _os.path.splitext(_f)[1] not in (".py", ".md", ".html", ".pine", ".mq5", ".json"): continue
    try: _t = io.open(_f, encoding="utf-8", errors="ignore").read()
    except Exception: continue
    for _m in _pat.finditer(_t):
        _hits.append((_os.path.basename(_f), _m.group(1), _m.group(2)[:8] + "…"))
check("repo 裡沒有任何寫死的金鑰／權杖", not _hits, _hits[:3])
# URL 裡的 ?t=... 也是憑證
_url = _r2.findall(r'https?://[^\s"\']*[?&](?:t|token|key)=([0-9a-zA-Z]{8,})', src)
check("BROKER_API_URL 沒有把權杖寫進原始碼", not _url, _url[:2])
check("BROKER_API_URL 改成環境變數", '_env_str("BROKER_API_URL", "")' in src)

print("\n=== 10i. R83：商品代號要跟券商一致 ===")
# 不靠人記 XAUUSD / XAUUSD+：拿 EA 回報的圖表商品名自動比對
FAKE.clear()
main.save_account_snapshot(dict(good, symbol="NONE",
                                m1_ohlc={"symbol": main.ORDER_SYMBOL, "time": 1, "open": 1,
                                         "high": 1, "low": 1, "close": 1}), {}, {})
check("名字一樣時不示警", main.broker_symbol_mismatch() is None, main.broker_symbol_mismatch())
FAKE.clear()
main.save_account_snapshot(dict(good, symbol="NONE",
                                m1_ohlc={"symbol": "XAUUSD+", "time": 1, "open": 1,
                                         "high": 1, "low": 1, "close": 1}), {}, {})
w = main.broker_symbol_mismatch()
check("EA 回報 XAUUSD+ 而設定是 XAUUSD → 示警", w is not None and "XAUUSD+" in w, w)
check("示警訊息告訴你要改成哪一個", w and "改成「XAUUSD+」" in w, w)
FAKE.clear()
main.save_account_snapshot(dict(good, symbol="NONE"), {}, {})
check("EA 還沒回報商品名時不亂示警", main.broker_symbol_mismatch() is None)
# 心跳端到端：不一致時 Log 會記一筆
FAKE.clear()
post({"action": "check_gate", "token": "tok", **dict(good, symbol="NONE",
      m1_ohlc={"symbol": "XAUUSD+", "time": 1, "open": 1, "high": 1, "low": 1, "close": 1})})
logs = main.read_decision_logs()
check("心跳會把不一致寫進決策日誌",
      any("商品名不一致" in str(x) for x in logs), str(logs)[:80])
pl2 = json.loads(body_of(get("?view=gates&format=json")))
check("gates JSON 帶 symbol_mismatch", pl2.get("symbol_mismatch") is not None,
      pl2.get("symbol_mismatch"))

print("\n=== 11. GATE_DRIVER=REGIME 可回退 ===")
main.GATE_DRIVER = "REGIME"
s = main.default_gate_state(); s["armed"] = True; s["regime"] = main.REGIME_TREND; s["dir"] = "UP"
check("回退後 TREND+armed → OPEN", main.gate_status(s) == "OPEN")
s["regime"] = main.REGIME_RANGE
check("回退後 RANGE → LOCK", main.gate_status(s) == "LOCK")
main.GATE_DRIVER = "RISK"

print(f"\n{'='*50}\n通過 {OK} / 失敗 {FAIL}\n{'='*50}")
sys.exit(1 if FAIL else 0)
