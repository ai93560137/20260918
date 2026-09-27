"""[R90] 換了風控淨值的定義之後，舊尺量的高水位不可以再沿用。"""
import json, os, sys, types
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

# C 戶口實況：結餘 21,642.93 + 信用 5,114.00 = 淨值 26,756.93
SNAP = {"equity": 26756.93, "credit": 5114.00, "balance": 21642.93,
        "currency": "HKD", "net_lots": 0.0, "daily_pnl": 0.0,
        "m15_ohlc": {"close": 4380.0, "atr_m15": 7.66}}   # ATR% = 0.175%，過波動關

def gate_open_now(state):
    # 市場時段用 2026-09-22 18:36 UTC（週二，開市中）
    import datetime as dt
    now = dt.datetime(2026, 9, 22, 18, 36, tzinfo=dt.timezone.utc).timestamp()
    return main.evaluate_risk_gate(SNAP, state, now)

print("\n=== R90：舊尺的高水位會把電閘鎖死（修之前的行為） ===")
stale = main.default_gate_state()
stale["equity_peak"] = 26756.93          # R88 之前記的（含信用）
stale["equity_peak_basis"] = ""          # 沒有標記 = 舊尺
r = gate_open_now(stale)
expo = [c for c in r["checks"] if c["key"] == "exposure"][0]
print("      " + expo["detail"][:90])
check("舊高水位不被採用（不再讀成 19% 回撤）", "回撤 0.0%" in expo["detail"], expo["detail"][:120])
check("曝險關卡通過", expo["ok"], expo["detail"][:120])
check("電閘開得了", r["open"], r["reason"][:120])
check("回傳的新高水位 = 風控淨值", abs(r["equity_peak"] - 21642.93) < 0.01, r["equity_peak"])
check("回傳帶上新尺標記", r["equity_peak_basis"] == main.EQUITY_PEAK_BASIS, r.get("equity_peak_basis"))

print("\n=== R90：同一把尺量的高水位，照樣要生效（真回撤不可以被抹掉） ===")
same = main.default_gate_state()
same["equity_peak"] = 26000.0
same["equity_peak_basis"] = main.EQUITY_PEAK_BASIS      # 新尺
r2 = gate_open_now(same)
expo2 = [c for c in r2["checks"] if c["key"] == "exposure"][0]
print("      " + expo2["detail"][:90])
check("沿用同尺高水位", "26,000" in expo2["detail"], expo2["detail"][:120])
check("真的回撤有算出來", "回撤 16.8%" in expo2["detail"], expo2["detail"][:120])
check("回傳的高水位不會被壓低", abs(r2["equity_peak"] - 26000.0) < 0.01, r2["equity_peak"])

print("\n=== R90：換尺那一次一定要寫進 GCS（否則永遠鎖著） ===")
FAKE.clear()
FAKE[main.GATE_STATE_FILE] = (json.dumps({**main.default_gate_state(),
                                          "equity_peak": 26756.93,
                                          "equity_peak_basis": "",
                                          "armed": False}), 1)
res = main.apply_risk_to_gate(SNAP, False)
saved = json.loads(FAKE[main.GATE_STATE_FILE][0])
check("狀態檔已更新", FAKE[main.GATE_STATE_FILE][1] > 1, FAKE[main.GATE_STATE_FILE][1])
check("基準標記寫進去了", saved.get("equity_peak_basis") == main.EQUITY_PEAK_BASIS,
      saved.get("equity_peak_basis"))
check("高水位改成 21,642.93", abs(saved.get("equity_peak", 0) - 21642.93) < 0.01,
      saved.get("equity_peak"))
check("armed 變 True", saved.get("armed") is True, saved.get("armed"))
check("電閘狀態 OPEN", main.gate_status(saved) == "OPEN", main.gate_status(saved))

print("\n=== R90：第二次心跳不可以又重設一次（不能每分鐘抹掉高水位） ===")
gen_before = FAKE[main.GATE_STATE_FILE][1]
main.apply_risk_to_gate(SNAP, False)
saved2 = json.loads(FAKE[main.GATE_STATE_FILE][0])
check("高水位保持不變", abs(saved2.get("equity_peak", 0) - 21642.93) < 0.01, saved2.get("equity_peak"))
check("沒有多餘的寫入", FAKE[main.GATE_STATE_FILE][1] == gen_before, FAKE[main.GATE_STATE_FILE][1])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
