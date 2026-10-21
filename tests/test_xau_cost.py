"""慳成本（使用者 10-21 揀「穩陣 A+F+D」，xau/COST_PLAN.md）：A 混合快取 TTL、F 市況冇變沿用 HOLD、D 時段外空倉唔問。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", ANTHROPIC_API_KEY="x", XAU_EXECUTE="0", XAU_REUSE_HOLD="on", XAU_ACTIVE_HOURS_UTC="07-17")
sys.path.insert(0, "/home/user/20260918/xau")
try:
    import anthropic                             # noqa: F401
except ImportError:                              # 冇裝 SDK 都要跑到測試（Claude 用假 brain）
    _an = types.ModuleType("anthropic")
    class _E(Exception):
        pass
    _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = _E; sys.modules["anthropic"] = _an
import google, google.cloud                      # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def download_as_bytes(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0].encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1
        FAKE[self.name] = (data, gen); self.generation = gen
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
exc_mod = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
exc_mod.PreconditionFailed = _PC; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod
import main as xau, config, brain   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

print("=== A 混合快取 TTL ===")
uc = brain._user_content({"product": {}, "bars_m15_older": [], "bars_m1_older": [], "bars_m1": []}, "x", stable_ttl="1h")
check("產品＋M15 段 1h、整點前 M1 段 5m（1h 喺 5m 前面）", uc[0]["cache_control"]["ttl"] == "1h" and uc[1]["cache_control"]["ttl"] == "5m", [c.get("cache_control") for c in uc])
check("預設 CACHE_TTL_STABLE=1h", config.CACHE_TTL_STABLE == "1h")
c_mixed = brain.cost_usd({"in": 0, "out": 0, "cache_read": 0, "cache_write": 2000, "cw_1h": 1000, "cw_5m": 1000, "model": "claude-opus-5-5"})
check("混合寫入成本 = 1000×4×2 + 1000×4×1.25（/1e6）", abs(c_mixed - 0.013) < 1e-9, c_mixed)

print("=== D 時段 ===")
H = lambda h: 1792540800 + h * 3600   # 10-21 00:00 UTC 起
check("07-17：06:59 唔問、07:00 問、16:59 問、17:00 唔問",
      (xau.in_active_hours(H(6) + 3599), xau.in_active_hours(H(7)), xau.in_active_hours(H(16) + 3599), xau.in_active_hours(H(17))) == (False, True, True, False))
config.ACTIVE_HOURS_UTC = "22-07"
check("跨午夜 22-07：23 點問、12 點唔問", xau.in_active_hours(H(23)) and not xau.in_active_hours(H(12)))
config.ACTIVE_HOURS_UTC = ""
check("空＝全日", xau.in_active_hours(H(3)))

print("=== F 沿用 HOLD ===")
m1 = [{"time": 1000 + 60 * i, "open": 4000, "high": 4001, "low": 3999, "close": 4000.0} for i in range(30)]   # ATR ≈ 2
m15 = [{"time": 900, "open": 4000, "high": 4001, "low": 3999, "close": 4000}]
st = {"reuse_anchor": {"ts": 2000, "price": 4000.0, "m15_time": 900}, "last_decision": {"kind": "decide", "final": "HOLD"}}
check("價格冇變、同一根 M15、2 分鐘內 → 沿用", bool(xau.reuse_hold(st, m1, m15, 2120)))
check("超過 5 分鐘 → 唔沿用", xau.reuse_hold(st, m1, m15, 2000 + 301) is None)
check("新 M15 收盤 → 唔沿用", xau.reuse_hold(st, m1, m15 + [{"time": 1800, "open": 1, "high": 1, "low": 1, "close": 1}], 2120) is None)
m1b = m1[:-1] + [{**m1[-1], "close": 4001.5}]
check("價格移動 ≥ 0.3×ATR → 唔沿用", xau.reuse_hold(st, m1b, m15, 2120) is None)
check("上次唔係 HOLD → 唔沿用", xau.reuse_hold({**st, "last_decision": {"kind": "decide", "final": "OPEN_LONG"}}, m1, m15, 2120) is None)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
