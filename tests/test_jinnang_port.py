"""驗證 main.py 的 JinnangSession 與 jinnang_v4_reconcile.py 產生同樣的訊號。"""
import os, sys, types, math
os.environ.setdefault("GCP_SECRET_TOKEN","tok")
sys.path.insert(0,"/home/user/20260918")
import functions_framework, google, google.cloud
FAKE={}
class _B:
    def __init__(s,n): s.name=n; s.generation=0
    def exists(s): return False
    def download_as_text(s,*a,**k): raise KeyError(s.name)
    def download_as_bytes(s,*a,**k): raise KeyError(s.name)
    def upload_from_string(s,d,*a,**k): pass
    def reload(s): pass
class _Bk:
    def blob(s,n): return _B(n)
    def get_blob(s,n): return None
class _C:
    def __init__(s,*a,**k): pass
    def bucket(s,n): return _Bk()
m=types.ModuleType("google.cloud.storage"); m.Client=_C
sys.modules["google.cloud.storage"]=m; google.cloud.storage=m
g=types.ModuleType("google.genai"); g.Client=lambda *a,**k: None; g.types=types.SimpleNamespace()
sys.modules["google.genai"]=g
e=types.ModuleType("google.api_core.exceptions")
class _P(Exception): pass
e.PreconditionFailed=_P; e.NotFound=KeyError
ac=types.ModuleType("google.api_core"); ac.exceptions=e
sys.modules["google.api_core"]=ac; sys.modules["google.api_core.exceptions"]=e

import main
sys.path.insert(0,"/home/user/20260918/tradingview")
import pandas as pd, numpy as np
from jinnang_v4_reconcile import load_m15, trades

CSV='/root/.claude/uploads/13c02be0-89e0-5e8c-9f33-0cd3bcee9388/3564dfe6-XAUUSD_M15_MAX.csv'
df = load_m15(CSV)
# 取一段做驗證（全量太慢：JinnangSession 每根 O(n)）
SLICE = int(os.environ.get("SLICE", "4000"))
sub = df.iloc[:SLICE]
ref = trades(sub)
ref_entries = set(ref.entry_time)
print(f"參考實作（reconcile）在前 {SLICE} 根裡有 {len(ref_entries)} 個進場訊號")

bars = [dict(time=int(t.timestamp()), open=r.Open, high=r.High, low=r.Low, close=r.Close)
        for t, r in sub.iterrows()]
need = max(main.JN_LEN_TREND, main.JN_LEN_RANGE, main.JN_ATR_LEN+1, main.JN_MIN_BARS)
got, checked = set(), 0
WIN = main.MTFDynamicLevelsSession.history_max      # 生產環境只會有這麼多根
for i in range(need, len(bars)):
    v = main.JinnangSession.evaluate(bars[max(0, i+1-WIN):i+1])
    checked += 1
    if v.get("signal") == "BUY":
        got.add(sub.index[i])
print(f"視窗 = {WIN} 根（與生產環境一致）")
print(f"main.py 的 JinnangSession 在同一段掃出 {len(got)} 個訊號（評估了 {checked} 根）")

# reconcile 只在【尚未被消耗的區間】才出訊號；JinnangSession 是無狀態的逐根判定，
# 所以 got ⊇ ref_entries。檢查的是「ref 的每一筆 got 都有」。
# 暖機期（前 need 根）參考實作有訊號但 JinnangSession 還不判定 —— 那不是邏輯差異
warm = set(sub.index[:need])
ref_entries = ref_entries - warm
print(f"（扣掉暖機期前 {need} 根裡的 {len(warm & set(ref.entry_time))} 筆，參考剩 {len(ref_entries)} 筆）")
missing = sorted(ref_entries - got)
extra = sorted(got - ref_entries)
print(f"\n參考有、main.py 沒有：{len(missing)} 筆  ← 這是必須為 0 的")
for t in missing[:5]: print("   ", t)
print(f"main.py 有、參考沒有：{len(extra)} 筆  ← 加入區間消耗後應為 0")
for t in extra[:5]: print("   ", t)
ok = len(missing) == 0 and len(extra) == 0 and len(ref_entries) > 0
print("\n" + ("✅ 通過：暖機期之後，兩個實作的訊號完全一致"
              if ok else "❌ 不通過"))
sys.exit(0 if ok else 1)
