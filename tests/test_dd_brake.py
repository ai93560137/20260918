"""[R93] 回撤煞車：累積回撤達門檻就停當日新單，當日鎖存，隔日重評。"""
import datetime as dt, json, os, sys, types
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
import functions_framework, google, google.cloud
FAKE = {}
class _Blob:
    def __init__(s,n): s.name=n; s.generation=FAKE.get(n,(None,0))[1]
    def exists(s): return s.name in FAKE
    def download_as_text(s,*a,**k):
        if s.name not in FAKE: raise KeyError(s.name)
        return FAKE[s.name][0]
    def download_as_bytes(s,*a,**k): return s.download_as_text().encode()
    def upload_from_string(s,d,*a,**k):
        g=FAKE.get(s.name,(None,0))[1]+1; FAKE[s.name]=(d,g); s.generation=g
    def reload(s): s.generation=FAKE.get(s.name,(None,0))[1]
class _Bucket:
    def blob(s,n): return _Blob(n)
    def get_blob(s,n): return _Blob(n) if n in FAKE else None
class _Client:
    def __init__(s,*a,**k): pass
    def bucket(s,n): return _Bucket()
m=types.ModuleType("google.cloud.storage"); m.Client=_Client
sys.modules["google.cloud.storage"]=m; google.cloud.storage=m
g=types.ModuleType("google.genai"); g.Client=lambda *a,**k: None
g.types=types.SimpleNamespace(); sys.modules["google.genai"]=g
e=types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
e.PreconditionFailed=_PC; e.NotFound=KeyError
ac=types.ModuleType("google.api_core"); ac.exceptions=e
sys.modules["google.api_core"]=ac; sys.modules["google.api_core.exceptions"]=e
import main
main.macro_news_session.status = lambda now=None: {"locked": False, "known": True, "reason": "t",
                                                   "events": [], "warning": None}

OK=FAIL=0
def check(n,c,x=""):
    global OK,FAIL
    if c: OK+=1; print(f"  ✅ {n}")
    else: FAIL+=1; print(f"  ❌ {n} {x}")

NOW = dt.datetime(2026, 9, 22, 18, 0, tzinfo=dt.timezone.utc).timestamp()   # 週二開市中
TODAY = main._ny_date(NOW)
BRAKE = main.DD_BRAKE_PCT
print(f"\n（DD_BRAKE_PCT = {BRAKE:g}%　紐約日 = {TODAY}）")

def snap(equity, peak_balance=None):
    return {"equity": equity, "credit": 0.0, "balance": peak_balance or equity,
            "currency": "HKD", "net_lots": 0.0, "daily_pnl": 0.0,
            "m15_ohlc": {"close": 4380.0, "atr_m15": 7.66}}

def state_with_peak(peak, brake_day=""):
    st = main.default_gate_state()
    st["equity_peak"] = peak
    st["equity_peak_basis"] = main.EQUITY_PEAK_BASIS
    st["dd_brake_day"] = brake_day
    return st

def brake_of(r):
    return [c for c in r["checks"] if c["key"] == "brake"][0]

PEAK = 21642.93
def eq_at(dd_pct):
    return PEAK * (1 - dd_pct/100.0)

print("\n=== R93：六道關卡，不是五道 ===")
r = main.evaluate_risk_gate(snap(PEAK), state_with_peak(PEAK), NOW)
check("關卡數 = 6", len(r["checks"]) == 6, [c["key"] for c in r["checks"]])
check("有 brake 這一關", any(c["key"] == "brake" for c in r["checks"]))

print("\n=== R93：回撤在門檻之下 → 放行 ===")
r = main.evaluate_risk_gate(snap(eq_at(BRAKE - 3)), state_with_peak(PEAK), NOW)
b = brake_of(r)
print("      " + b["detail"][:70])
check("煞車這一關過", b["ok"], b["detail"][:120])
check("沒有踩下", r["dd_brake_hit"] is False)
# 此時曝險上限 =(容忍−回撤)/最壞跳空 可能已經不夠做 0.01 手 —— 那是曝險關的事。
# 這裡只驗「不是煞車擋的」，否則等於在測另一關。
check("關閘的理由裡沒有煞車",
      "brake" not in [c["key"] for c in r["checks"] if not c["ok"]],
      [c["key"] for c in r["checks"] if not c["ok"]])

print("\n=== R93：回撤達門檻 → 停當日新單 ===")
r = main.evaluate_risk_gate(snap(eq_at(BRAKE + 1)), state_with_peak(PEAK), NOW)
b = brake_of(r)
print("      " + b["detail"][:100])
check("煞車這一關不過", not b["ok"], b["detail"][:120])
check("回報踩下了", r["dd_brake_hit"] is True)
check("電閘關上", not r["open"])
check("訊息說明已開的倉不受影響", "已開的倉不受影響" in b["detail"], b["detail"])
check("訊息說明要人介入，等不會自己好", "等下去不會自己好" in b["detail"], b["detail"])

print("\n=== R93：剛好等於門檻也要煞（>= 不是 >）===")
r = main.evaluate_risk_gate(snap(eq_at(BRAKE)), state_with_peak(PEAK), NOW)
check("回撤 = 門檻 → 煞停", not brake_of(r)["ok"], brake_of(r)["detail"][:100])

print("\n=== R93：當日鎖存 —— 盤中回撤縮回去也不放行 ===")
r = main.evaluate_risk_gate(snap(PEAK), state_with_peak(PEAK, brake_day=TODAY), NOW)
b = brake_of(r)
check("回撤已回到 0%，仍然煞停", not b["ok"], b["detail"][:120])
check("說明是今日稍早踩下的", "已鎖存" in b["detail"], b["detail"][:140])
check("但不再回報「踩下」（避免重複寫入）", r["dd_brake_hit"] is False)

print("\n=== R93：隔日重評 —— 昨天的鎖存不影響今天 ===")
YDAY = main._ny_date(NOW - 86400)
r = main.evaluate_risk_gate(snap(PEAK), state_with_peak(PEAK, brake_day=YDAY), NOW)
check("昨天踩下、今天回撤 0% → 放行", brake_of(r)["ok"], brake_of(r)["detail"][:120])

print("\n=== R93：缺淨值要 fail-closed，不可以當成沒事 ===")
r = main.evaluate_risk_gate({"currency": "HKD"}, state_with_peak(PEAK), NOW)
b = brake_of(r)
check("算不出回撤 → 這一關不過", not b["ok"], b["detail"])
check("說明原因", "算不出回撤" in b["detail"], b["detail"])

print("\n=== R93：DD_BRAKE_PCT=0 可以整條停用 ===")
old = main.DD_BRAKE_PCT
main.DD_BRAKE_PCT = 0.0
r = main.evaluate_risk_gate(snap(eq_at(50)), state_with_peak(PEAK), NOW)
check("停用後回撤 50% 也不煞", brake_of(r)["ok"], brake_of(r)["detail"])
check("停用時不會誤報踩下", r["dd_brake_hit"] is False)
main.DD_BRAKE_PCT = old

print("\n=== R93：鎖存要寫進 GCS，而且只寫一次 ===")
FAKE.clear()
FAKE[main.GATE_STATE_FILE] = (json.dumps(state_with_peak(PEAK)), 1)
main.apply_risk_to_gate(snap(eq_at(BRAKE + 1)), False)
saved = json.loads(FAKE[main.GATE_STATE_FILE][0])
check("dd_brake_day 寫進去了", saved.get("dd_brake_day") == main._ny_date(),
      saved.get("dd_brake_day"))
check("armed 變 False", saved.get("armed") is False, saved.get("armed"))
gen = FAKE[main.GATE_STATE_FILE][1]
main.apply_risk_to_gate(snap(eq_at(BRAKE + 1)), False)
check("同一天同狀態不重複寫入", FAKE[main.GATE_STATE_FILE][1] == gen,
      FAKE[main.GATE_STATE_FILE][1])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
