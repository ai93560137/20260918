"""[R85] 只有【當下】那一根被改寫才叫「正在形成」；舊 K 線被改寫是另一回事。"""
import io, os, sys, types, contextlib
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
import functions_framework
import google, google.cloud
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

OK=FAIL=0
def check(n,c,x=""):
    global OK,FAIL
    if c: OK+=1; print(f"  ✅ {n}")
    else: FAIL+=1; print(f"  ❌ {n} {x}")

sess = main.MTFDynamicLevelsSession()
OFF = main.BROKER_UTC_OFFSET_HOURS * 3600

def ingest(bar):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sess.ingest(bar)
    return buf.getvalue()

def bar_at(server_ts, close):
    return {"time": server_ts, "open": 3000.0, "high": 3010.0, "low": 2990.0, "close": close}

print("\n=== R85：當下那一根被改寫 → 才提示改 JN_M15_LAST_CLOSED ===")
FAKE.clear()
now_server = int((main.now_ts() + OFF) // 900 * 900)       # 當下這根 M15（券商時間）
ingest(bar_at(now_server, 3005.0))
out = ingest(bar_at(now_server, 3007.0))
check("提到【正在形成】", "正在形成" in out, out)
check("叫人設成 0", "設成 0" in out, out)
check("標 R80", "[R80]" in out, out)
check("印出改了哪個欄位", "close 3005.0→3007.0" in out, out)

print("\n=== R85：44 小時前的舊 K 線被改寫 → 不准叫人改設定 ===")
FAKE.clear()
old_server = int(((main.now_ts() - 44.3 * 3600) + OFF) // 900 * 900)
ingest(bar_at(old_server, 3005.0))
out = ingest(bar_at(old_server, 3007.0))
check("不叫人改設定（沒有「設成 0」）", "設成 0" not in out, out)
check("明說別動 JN_M15_LAST_CLOSED", "別動 JN_M15_LAST_CLOSED" in out, out)
check("點名商品混用的可能", "XAUUSD+" in out, out)
check("報出這根有多舊（小時）", "44." in out and "小時" in out, out)
check("標 R85 不是 R80", "[R85]" in out and "[R80]" not in out, out)

print("\n=== R85：OHLC 完全沒變 → 一個字都不該印 ===")
FAKE.clear()
ingest(bar_at(now_server, 3005.0))
out = ingest(bar_at(now_server, 3005.0))
check("重複同一根不出警告", out.strip() == "", repr(out))

print("\n=== R85：新的一根 → 不出警告 ===")
out = ingest(bar_at(now_server + 900, 3009.0))
check("新 K 線不出警告", "R80" not in out and "R85" not in out, out)

print("\n=== R85：OHLC 相同但存檔多了欄位 → 要講明是格式問題 ===")
FAKE.clear()
import json as _json
b = bar_at(now_server, 3005.0)
FAKE[main.M15_HISTORY_FILE] = (_json.dumps([{**b, "volume": 123}]), 1)
out = ingest(b)
check("指出 OHLC 四個值相同", "OHLC 四個值完全相同" in out, out)
check("明說別動 JN_M15_LAST_CLOSED", "別動 JN_M15_LAST_CLOSED" in out, out)
check("列出舊存檔多了哪個欄位", "volume" in out, out)
check("不叫人改設定", "設成 0" not in out, out)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
