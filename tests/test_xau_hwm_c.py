"""[11-07] HWM 選項 C（戶口層 XAU_DD_STOP_PCT／XAU_HWM_START、933 策略層 R 線）＋933 E6S4 結構覆寫（SIG_STUDENT_STRUCT）。"""
import json, os, sys, types

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_BOOK="signal", SIG_DECIDE="0", TG_SIGNAL_INGEST_SECRET="s",
                  ANTHROPIC_API_KEY="x", XAU_EXECUTE="1", SIG_S1_EXECUTE="1", SIG_FOLLOW_EXECUTE="1", SIG_STUDENT_EXECUTE="1", SIG_G7_EXECUTE="1", SIG_COMBO_EXECUTE="1", SIG_FOLLOW_CHANNELS="3996305231", GATE_MODEL="claude-haiku-5-5",
                  SIG_STUDENT_LIVE="1", SIG_STUDENT_LIVE_RULES="rev15", SIG_STUDENT_DAY_STOP_HKD="300")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
try:
    import anthropic                             # noqa: F401
except ImportError:
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
import main as xau, config, follower, student_live   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = xau.app.test_client()
import rules  # noqa: E402

print("=== SIG_STUDENT_STRUCT 解析 ===")
st = config._struct("rev15:6,2,4,1;rule:rev15x:6,2,4,1;bad:1,2;neg:-1,2,4,1")
check("rev15／rev15x 解析、錯格式略過", st == {"rule:rev15": (6.0, 2.0, 4.0, 1.0), "rule:rev15x": (6.0, 2.0, 4.0, 1.0)}, st)
check("空字串 → {}", config._struct("") == {})

print("=== restructure ===")
config.STUDENT_STRUCT = {"rule:rev15": (6.0, 2.0, 4.0, 1.0)}
pb = {"id": "p1", "student": "rule:rev15", "side": "BUY", "price": 4100.0, "entry_low": 4095, "entry_high": 4097, "sl": 4089, "tp": [4111]}
b = student_live.restructure(pb)
check("BUY：中位 4094、區 4092–4096、SL 4090、TP 4098", (b["entry_low"], b["entry_high"], b["sl"], b["tp"]) == (4092.0, 4096.0, 4090.0, [4098.0]), b)
s_ = student_live.restructure({**pb, "side": "SELL"})
check("SELL：中位 4106、區 4104–4108、SL 4110、TP 4102", (s_["entry_low"], s_["entry_high"], s_["sl"], s_["tp"]) == (4104.0, 4108.0, 4110.0, [4102.0]), s_)
check("冇設定嘅規則原樣", student_live.restructure({**pb, "student": "rule:level"}) == {**pb, "student": "rule:level"})
check("原 pred 唔被改", pb["sl"] == 4089)

print("=== entry_check（新結構） ===")
check("出區時現價（4100，高過 TP）→ wait 唔係 skip", student_live.entry_check(b, 4100.0)[0] == "wait", student_live.entry_check(b, 4100.0))
check("回調入區 4095 → ok", student_live.entry_check(b, 4095.0)[0] == "ok")
check("跌穿 SL 4089 → skip", student_live.entry_check(b, 4089.0)[0] == "skip")
check("舊結構仍然：現價過 TP → skip", student_live.entry_check(pb, 4112.0)[0] == "skip")

print("=== 933 策略層停線 ===")
config.STUDENT_HWM_START = ""
check("START 空 → 唔設", student_live.strategy_stop({"book": [{"closed_ts": 1, "r": -20}]})[0] is None)
config.STUDENT_HWM_START = "2026-11-09"
t0 = 1794182400  # 2026-11-09 00:00 UTC
book = [{"closed_ts": t0 - 100, "r": -50.0}] + [{"closed_ts": t0 + i, "r": -1.0} for i in range(7)]
why, stat = student_live.strategy_stop({"book": book})
check("START 之前嘅單唔計；−7R 未到線", why is None and stat["cum_r"] == -7.0 and stat["n"] == 7, stat)
why, stat = student_live.strategy_stop({"book": book + [{"closed_ts": t0 + 9, "r": -1.04}]})
check("累計 −8.04R → 停", why and "−8R" in why, why)
book2 = [{"closed_ts": t0 + 1, "r": 6.0}] + [{"closed_ts": t0 + 2 + i, "r": -1.0} for i in range(10)]
why, stat = student_live.strategy_stop({"book": book2})
check("累計 −4R 但由高位 +6 回撤 10R → 停", why and "回撤" in why and stat["dd_r"] == 10.0, (why, stat))
config.STUDENT_HWM_START = "2026/11/09"
check("START 格式錯 → 為安全停", "格式錯" in (student_live.strategy_stop({})[0] or ""))
config.STUDENT_HWM_START = ""

print("=== 戶口層 XAU_DD_STOP_PCT ===")
class C:
    DAILY_LOSS_STOP_PCT = 1000; DAILY_LOSS_PAUSE_PCT = 20; NIGHT_MULT = 1.5; CUM_LOSS_PAUSE_PCT = 25
    DD_ALERT_PCTS = (10.0, 20.0); MARGIN_PAUSE_PCT = 300; MARGIN_ALERT_PCTS = (200, 150); DD_STOP_PCT = 20.0
lad = rules.ladder(principal_hkd=None, own_equity=79.0, peak_equity=100.0, daily_pnl_hkd=None, margin_level=None, night=False, cfg=C)
check("回撤 21% ≥ 20% → pause（hwm）", lad["pause"] and lad["pause_kind"] == "hwm" and not lad["stop"], lad)
lad = rules.ladder(principal_hkd=None, own_equity=85.0, peak_equity=100.0, daily_pnl_hkd=None, margin_level=None, night=False, cfg=C)
check("回撤 15% → 唔停（只提示 dd1）", not lad["pause"] and "dd1" in lad["alerts"], lad)
C.DD_STOP_PCT = 0.0
lad = rules.ladder(principal_hkd=None, own_equity=50.0, peak_equity=100.0, daily_pnl_hkd=None, margin_level=None, night=False, cfg=C)
check("DD_STOP_PCT=0（預設）→ 照舊只提示", not lad["pause"], lad)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
