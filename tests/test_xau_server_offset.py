"""[R362] main.server_offset 用券商時區規則（UTC+2，美國夏令時期間 UTC+3）：週末 server_time 停住唔再計錯、夏令／冬令切換週、正常盤中、規則關。"""
import os, sys, types
os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", GATE_MODEL="claude-haiku-5-5", ANTHROPIC_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
try:
    import anthropic  # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules["anthropic"] = _an
import google, google.cloud  # noqa: E402
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = lambda *a, **k: None
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
exc_mod = types.ModuleType("google.api_core.exceptions"); exc_mod.PreconditionFailed = Exception; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod
import main as xau, config  # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

logs = []
xau.log_event = lambda msg, severity="INFO", **k: logs.append((severity, msg))
WED_SUMMER = 1793210400      # 2026-10-28 10:00 UTC（美國夏令時）
TUE_WINTER = 1793700000      # 2026-11-03 10:00 UTC（冬令）
SAT = 1793455200             # 2026-10-31 14:00 UTC 星期六
FRI_CLOSE_SERVER = 1793390400 + 3600 * 3 - 60   # 星期五 20:59 UTC 嘅伺服器時間（UTC+3）

print("=== 規則（XAU_SERVER_TZ_RULE=ny，預設）===")
check("預設規則 ny", config.SERVER_TZ_RULE == "ny")
check("夏令時盤中：心跳 server_time UTC+3 → 3 小時、冇 WARNING", xau.server_offset({"server_time": WED_SUMMER + 10800 + 2}, WED_SUMMER) == 10800 and not logs, logs)
check("冬令時盤中：UTC+2 → 2 小時", xau.server_offset({"server_time": TUE_WINTER + 7200}, TUE_WINTER) == 7200)
check("只有 M1 時間（冬令）：照樣 2 小時", xau.server_offset({"m1_ohlc": {"time": TUE_WINTER + 7200 - 70}}, TUE_WINTER) == 7200)
r = xau.server_offset({"server_time": FRI_CLOSE_SERVER, "m1_ohlc": {"time": FRI_CLOSE_SERVER - 60}}, SAT)
check("週末：server_time 停喺星期五收市 → 照用規則 3 小時（唔係 −17 小時）", r == 10800, r)
check("偏離規則 → 寫 WARNING（一次）", sum(1 for s, m in logs if s == "WARNING" and "伺服器時差" in m) == 1, logs)
xau.server_offset({"server_time": FRI_CLOSE_SERVER}, SAT + 60)
check("WARNING 每小時最多一次", sum(1 for s, m in logs if "伺服器時差" in m) == 1, logs)
# 切換週：2026-11-01 06:00 UTC 美國夏令時結束
check("切換前（11-01 05:00 UTC）3 小時、切換後（11-01 07:00 UTC）2 小時",
      xau.rule_offset(1793491200 + 5 * 3600) == 10800 and xau.rule_offset(1793491200 + 7 * 3600) == 7200)
check("3 月切換（2027-03-14 美國夏令時開始）：之前 2 小時、之後 3 小時",
      xau.rule_offset(1805007600 - 86400) == 7200 and xau.rule_offset(1805007600 + 86400) == 10800)
check("冇心跳時間資料 → 規則值", xau.server_offset({}, TUE_WINTER) == 7200)

print("=== 規則關（XAU_SERVER_TZ_RULE=off）===")
config.SERVER_TZ_RULE = "off"
check("規則關：照舊用心跳估（server_time）", xau.server_offset({"server_time": SAT + 3600}, SAT) == 3600)
check("規則關：冇資料 = 0", xau.server_offset({}, SAT) == 0)
config.SERVER_TZ_RULE = "ny"

print(f"\n結果：{OK} 過、{FAIL} 失敗")
sys.exit(1 if FAIL else 0)
