"""[R363] 按風險計手數：手數＝floor(權益×1% ÷ 每手止損 HKD, 0.01)，夾 [0.01, 上限]；細過 0.01 唔開；權益讀唔到退固定 0.05；預設關；
921／931 enqueue_cmd 用；live_book 記 risk_hkd；戶口合計開倉風險 %。"""
import json, os, sys, types
os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="1", GATE_MODEL="claude-haiku-5-5", ANTHROPIC_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
try:
    import anthropic  # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules["anthropic"] = _an
import google, google.cloud  # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def download_as_bytes(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0].encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1; FAKE[self.name] = (data, gen); self.generation = gen
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
exc_mod = types.ModuleType("google.api_core.exceptions"); exc_mod.PreconditionFailed = Exception; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod
import main as xau, config, risk_size as R, live_book  # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

print("=== 預設關 ===")
check("XAU_RISK_SIZING 預設 0 → size 回 None（用返原本手數）", config.RISK_SIZING is False and R.size(30000, 4000, 3994, 0.1) == (None, {"mode": "off"}))
config.RISK_SIZING = True
print("=== 計法 ===")
check("每手止損 HKD：6 美元 × 100 盎司 × 7.8 = 4680", R.per_lot_loss_hkd(4000, 3994) == 4680)
l, i = R.size(30000, 4000, 3994, 0.10)        # 1% = 300 → 300/4680 = 0.064 → 0.06
check("權益 30,000、止損 6 → 0.06 手、風險 280.8 HKD（0.94%）", l == 0.06 and i["risk_hkd"] == 280.8 and i["mode"] == "risk", (l, i))
l, i = R.size(30000, 4000, 3980, 0.10)        # 300/15600 = 0.019 → 0.01
check("止損 20 → 0.01 手（floor，唔向上捨入）", l == 0.01 and i["risk_hkd"] == 156.0, (l, i))
l, i = R.size(300000, 4000, 3994, 0.10)       # 3000/4680 = 0.64 → cap 0.10
check("上限 0.10：計出 0.64 → 0.10，capped", l == 0.10 and i["capped"], (l, i))
l, i = R.size(10000, 4000, 3970, 0.10)        # 100/23400 = 0.004 → skip
check("細過 0.01 → 唔開（0.0）＋原因", l == 0.0 and i["mode"] == "skip" and "唔夠 0.01" in i["why"], (l, i))
l, i = R.size(None, 4000, 3994, 0.10)
check("權益讀唔到 → 固定 0.05（fallback）", l == 0.05 and i["mode"] == "fallback", (l, i))
l, i = R.size(None, 4000, 3994, 0.03)
check("fallback 都夾上限", l == 0.03)
check("冇止損 → 唔開", R.size(30000, 4000, None, 0.1)[0] == 0.0 and R.size(30000, 4000, 4000, 0.1)[0] == 0.0)
check("SELL 方向一樣計（距離取絕對值）", R.size(30000, 4000, 4006, 0.10)[0] == 0.06)

print("=== 921／931 enqueue_cmd ===")
st = {"pending_cmds": []}
t = xau.enqueue_cmd(st, "OPEN_LONG", 3994.0, 4012.0, 1000.0, "abcd1234", px=4000.0, account={"equity": 30000})
check("開倉指令手數＝0.06（取代固定手數）", t and t.startswith("open|BUY|0.06|"), t)
check("state.risk_last 記低", st.get("risk_last", {}).get("risk_hkd") == 280.8, st.get("risk_last"))
st = {"pending_cmds": []}
t = xau.enqueue_cmd(st, "OPEN_SHORT", 4030.0, 3950.0, 1000.0, "abcd1235", px=4000.0, account={"equity": 10000})
check("唔夠 0.01 → 唔排指令", t is None and not st["pending_cmds"], t)
t = xau.enqueue_cmd({"pending_cmds": []}, "UPDATE_STOP", 3995.0, 4012.0, 1000.0, "abcd1236", account={"equity": 30000})
check("modify 唔受影響", t and t.startswith("modify|"), t)

print("=== 成交簿 risk_hkd ===")
rec = live_book.make({"side": 1, "lots": 0.06, "entry": 4000.0, "stop": 3994.0, "opened_ts": 1}, 300.0, 2)
check("live_book.make 記 risk_hkd＝280.8", rec.get("risk_hkd") == 280.8, rec)

print("=== 戶口合計開倉風險 ===")
FAKE["xau/sig/account.json"] = (json.dumps({"equity": 30000, "positions": [{"entry": 4000, "stop": 3994, "lots": 0.06}]}), 1)
FAKE["xau/sig/studentlive/account.json"] = (json.dumps({"positions": [{"entry": 4000, "stop": 4006, "lots": 0.06}]}), 1)
FAKE["xau/sig/g7live/account.json"] = (json.dumps({"positions": [{"entry": 4000, "stop": None, "lots": 0.02}]}), 1)
FAKE["xau/account.json"] = (json.dumps({"equity": 50000, "positions": []}), 1)
FAKE["xau/sig/follow/account.json"] = (json.dumps({"positions": []}), 1)
o = R.accounts_open_risk()
k69 = [k for k in o if "69" in k][0]; k63 = [k for k in o if "63" in k][0]
check("…69：兩張有止損 561.6 HKD＝1.87%、一張冇止損另計", o[k69]["risk_hkd"] == 561.6 and o[k69]["pct"] == 1.87 and o[k69]["none_sl"] == 1 and o[k69]["positions"] == 3, o)
check("…63：冇倉＝0%", o[k63]["pct"] == 0.0, o)
config.RISK_SIZING = False

print(f"\n結果：{OK} 過、{FAIL} 失敗")
sys.exit(1 if FAIL else 0)
