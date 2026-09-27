"""[R88] 風控用的淨值要扣掉信用；舊封包沒有 credit 時要保守回退。"""
import io, json, os, sys, types
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

RE = main.risk_equity

print("\n=== R88：C 戶口的真實數字 ===")
# MT5 交易分頁：結餘 21,642.93 + 信用 5,114.00 = 淨值 26,756.93
live = {"equity": 26756.93, "credit": 5114.00, "balance": 21642.93}
check("扣掉信用 = 結餘", abs(RE(live) - 21642.93) < 0.005, RE(live))
check("不是淨值", abs(RE(live) - 26756.93) > 1)

print("\n=== R88：有浮動盈虧時 ===")
# 浮虧 500：結餘不變，淨值 = 結餘 + 信用 + 浮動
check("浮虧會反映出來",
      abs(RE({"equity": 26256.93, "credit": 5114.00, "balance": 21642.93}) - 21142.93) < 0.005)
check("浮盈會反映出來",
      abs(RE({"equity": 27256.93, "credit": 5114.00, "balance": 21642.93}) - 22142.93) < 0.005)

print("\n=== R88：沒有信用的戶口 ===")
check("credit=0 → 就是淨值", abs(RE({"equity": 20000.0, "credit": 0.0, "balance": 20000.0}) - 20000.0) < 1e-9)

print("\n=== R88：舊 EA 的封包沒有 credit → 保守回退 ===")
check("退回結餘（有信用時結餘較小）",
      abs(RE({"equity": 26756.93, "balance": 21642.93}) - 21642.93) < 0.005)
check("浮虧讓淨值低於結餘時，取較小的淨值",
      abs(RE({"equity": 19000.0, "balance": 20000.0}) - 19000.0) < 1e-9)
check("只有淨值 → 只好用淨值", abs(RE({"equity": 20000.0}) - 20000.0) < 1e-9)
check("只有結餘 → 用結餘", abs(RE({"balance": 20000.0}) - 20000.0) < 1e-9)

print("\n=== R88：壞資料不可以變成大數字 ===")
check("兩個都沒有 → None", RE({}) is None)
check("不是 dict → None", RE(None) is None, RE(None))
check("信用比淨值大 → 夾到 0，不是負數", RE({"equity": 1000.0, "credit": 5000.0}) == 0.0)
check("信用是負數 → 當 0，不會反而加大", abs(RE({"equity": 20000.0, "credit": -5000.0}) - 20000.0) < 1e-9)
check("信用是 'N/A' → 當沒有，退回結餘",
      abs(RE({"equity": 26756.93, "credit": "N/A", "balance": 21642.93}) - 21642.93) < 0.005)

print("\n=== R88：倉位真的變小了（2% 是對自己的錢算） ===")
cur, px = "HKD", 4380.0
# 錦囊真正用的倉位距離：價格 × JN_SIZING_ADVERSE_PCT%（R79），不是災難停損
sl = round(px * main.JN_SIZING_ADVERSE_PCT / 100.0, 2)
lots_wrong, _ = main.PureGCPPyramidingSession.calculate_max_lots(26756.93, cur, px, sl)
lots_right, _ = main.PureGCPPyramidingSession.calculate_max_lots(RE(live), cur, px, sl)
print(f"      倉位距離 {sl:.2f} → 用淨值 {lots_wrong:.4f} 手 / 用扣信用後 {lots_right:.4f} 手")
check("兩邊都不是 0（否則這項等於沒測）", lots_wrong > 0 and lots_right > 0, (lots_wrong, lots_right))
# 兩邊都 0.01：上限雖然縮了，但都還在 ORDER_SIZE 之上，實際下單量不變。
# 這一點要寫死，否則以後有人看到「數字沒變」會以為扣信用沒生效。
check("實際下單量仍是 ORDER_SIZE（上限還在 0.01 之上）",
      lots_right == lots_wrong == main.ORDER_SIZE, (lots_right, lots_wrong, main.ORDER_SIZE))

# 真正的危險：上限掉到 ORDER_SIZE 以下就會算出 0.00 手，安靜地完全不下單（R79）。
floor_eq = main.ORDER_SIZE * sl * main.CONTRACT_SIZE / (main.FX_TO_USD["HKD"] * main.RISK_PCT)
print(f"      下得了 {main.ORDER_SIZE} 手的最低風控淨值 = HK${floor_eq:,.2f}"
      f"（目前 {RE(live):,.2f}，餘裕 {(RE(live)/floor_eq-1)*100:+.1f}%）")
check("目前的風控淨值還在那條線之上", RE(live) > floor_eq, (RE(live), floor_eq))
check("用淨值算會高估餘裕", (26756.93/floor_eq) > (RE(live)/floor_eq))

# 未 floor 的理論值要照 21642.93/26756.93 = 0.8089 縮
raw_w = 26756.93 * main.FX_TO_USD["HKD"] * main.RISK_PCT / (sl * main.CONTRACT_SIZE)
raw_r = RE(live)   * main.FX_TO_USD["HKD"] * main.RISK_PCT / (sl * main.CONTRACT_SIZE)
print(f"      未取整：{raw_w:.4f} → {raw_r:.4f}　比值 {raw_r/raw_w:.4f}（應為 0.8089）")
check("縮放比例 = 結餘 ÷ 淨值", abs(raw_r/raw_w - 21642.93/26756.93) < 1e-6, raw_r/raw_w)

print("\n=== R88：快照要把 credit 存下來 ===")
FAKE.clear()
snap = main.save_account_snapshot(
    {"symbol": "NONE", "equity": 26756.93, "credit": 5114.00, "balance": 21642.93,
     "m1_ohlc": {"symbol": "XAUUSD", "time": 1, "is_new_bar": True}}, {}, {})
check("快照有 credit 欄位", snap.get("credit") == 5114.00, snap.get("credit"))
check("快照的 equity 仍是原始值（顯示用）", snap.get("equity") == 26756.93, snap.get("equity"))
check("從快照算出的風控淨值正確", abs(RE(snap) - 21642.93) < 0.005, RE(snap))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
