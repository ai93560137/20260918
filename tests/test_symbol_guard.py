"""[R86] 商品名：不一致要擋單，沒核對過要明講，兩者不能互相冒充。"""
import io, json, os, sys, types, contextlib
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

OK=FAIL=0
def check(n,c,x=""):
    global OK,FAIL
    if c: OK+=1; print(f"  ✅ {n}")
    else: FAIL+=1; print(f"  ❌ {n} {x}")

OURS = str(main.read_order_params()[0].get("symbol") or main.ORDER_SYMBOL).strip()
print(f"\n（送單用的商品名 = {OURS!r}）")

print("\n=== R86：不一致 → 有話講 ===")
snap = {"broker_symbol": "XAUUSD+"} if OURS != "XAUUSD+" else {"broker_symbol": "XAUUSD"}
w = main.broker_symbol_mismatch(snap)
check("回報不一致", bool(w), w)
check("兩個名字都印出來", OURS in (w or "") and snap["broker_symbol"] in (w or ""), w)
check("不一致時不會再喊「未核對」", main.broker_symbol_unverified(snap) is None)

print("\n=== R86：一致 → 兩條都安靜 ===")
snap_ok = {"broker_symbol": OURS}
check("不報不一致", main.broker_symbol_mismatch(snap_ok) is None)
check("不報未核對", main.broker_symbol_unverified(snap_ok) is None)

print("\n=== R86：從沒核對過 → 不可以沉默 ===")
snap_none = {"broker_symbol": ""}
check("不報不一致（避免把自己鎖死）", main.broker_symbol_mismatch(snap_none) is None)
u = main.broker_symbol_unverified(snap_none)
check("明講沒有被核對過", bool(u) and "沒有被核對過" in u, u)
check("說明為什麼收不到", "M1" in (u or ""), u)

print("\n=== R86：m1_ohlc.symbol 取得到真名，頂層 NONE 不干擾 ===")
FAKE.clear()
snap = main.save_account_snapshot(
    {"symbol": "NONE", "m1_ohlc": {"symbol": "XAUUSD+", "time": 1, "is_new_bar": True}}, {}, {})
check("broker_symbol 取自 m1_ohlc", snap["broker_symbol"] == "XAUUSD+", snap["broker_symbol"])
check("頂層仍記錄 NONE", snap["symbol"] == "NONE", snap["symbol"])

print("\n=== R86：休市期間 m1_ohlc 不帶 symbol → 沿用上次存的，不會倒退 ===")
snap2 = main.save_account_snapshot(
    {"symbol": "NONE", "m1_ohlc": {"time": 2, "is_new_bar": False}}, {}, {})
check("沿用上一次的券商商品名", snap2["broker_symbol"] == "XAUUSD+", snap2["broker_symbol"])
check("沿用後不再喊未核對", main.broker_symbol_unverified(snap2) is None)

print("\n=== R86：擋單的位置（結構檢查，非端對端） ===")
src = open("/home/user/20260918/main.py").read()
i_params = src.index("    order_params = read_order_params()[0]\n\n    # 4b)")
i_block  = src.index("sym_warn = broker_symbol_mismatch(snapshot)")
i_engine = src.index('if ENTRY_ENGINE == "JINNANG":', i_block)   # 派單那一處，不是檔案前面那個
check("擋單檢查在進場引擎之前", i_params < i_block < i_engine)
check("擋單時回 monitoring（EA 不動作）",
      'jsonify({"status": "monitoring", "current_gate": "OPEN",' in src[i_block:i_engine])
check("擋單有寫進決策日誌", 'key="symbol_mismatch_block"' in src[i_block:i_engine])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
