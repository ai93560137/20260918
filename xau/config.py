"""🌌 天覆陣（XAUUSD）設定：全部由環境變數讀入。硬性風控數字喺呢度，AI 無權改。

獨立 Cloud Run 服務（暫名 zhuge-xau），同 zhuge-risk-manager 共用 bucket，只寫 XAU_PREFIX 前綴。
沿用龍飛陣 hsi_ai_trader 嘅分層：brain（Claude）／rules（純邏輯）／paper（紙上模擬）／main（HTTP）。
"""
import os


def _s(name, default):
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _i(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def _b(name, default):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


TEAM_NAME = _s("XAU_TEAM_NAME", "天覆陣")
TEAM_EMOJI = _s("XAU_TEAM_EMOJI", "🌌")
SYMBOL = _s("XAU_SYMBOL", "XAUUSD")
TOKEN = _s("WEBHOOK_SECRET_TOKEN", "")                      # 同 zhuge-risk-manager 相同；心跳同指令回報都要帶
BUCKET = _s("XAU_BUCKET", "zhuge-risk-manager-bucket")
PREFIX = _s("XAU_PREFIX", "xau/")                           # 本服務只寫呢個前綴
LEGACY_GATE_FILE = _s("XAU_LEGACY_GATE_FILE", "zhuge_gate_state.json")   # 舊服務電閘：只讀，只作參考資料傳畀 Claude（唔係硬閘）

# --- 模式 ---
# EXECUTE=0（預設）：影子模式——Claude 照決策、紙上模擬、只寫 GCS，心跳回應 cmd_text 永遠空。
# EXECUTE=1：真倉——決定變成指令由 EA 執行。切換前要達到 IDEAS.md 預先登記嘅影子標準。
EXECUTE = _b("XAU_EXECUTE", False)
# 只接受呢個 MT5 登入號嘅心跳（數據＋指令）；其他登入號回 ignored。留空＝全收（影子階段）。階段 B：demo 登入號；轉真倉：真戶口登入號。
ACCOUNT = _s("XAU_ACCOUNT", "")
TEST_CMDS = _b("XAU_TEST_CMDS", False)                       # 1 = 開放 action=test_cmd（階段 B 測試清單用；真倉前要關）

# --- Claude ---
PROVIDER = _s("CLAUDE_PROVIDER", "api").lower()             # api（ANTHROPIC_API_KEY，同龍飛陣一樣）| vertex（同一 GCP 專案）
MODEL = _s("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = _s("CLAUDE_EFFORT", "low")                         # M1 每分鐘一次，先用 low；影子階段量度延遲再調
GATE_MODEL = _s("GATE_MODEL", "claude-haiku-5-5")           # 冇倉時先用平價模型篩一次（龍飛陣方案 A）；留空 = 唔篩
GATE_EFFORT = _s("GATE_EFFORT", "low")
API_TIMEOUT_SEC = _f("CLAUDE_TIMEOUT_SEC", 45)              # EA WebRequest 同步等緊；影子階段量 p95 再定
VERTEX_PROJECT = _s("CLAUDE_VERTEX_PROJECT", "")
VERTEX_REGION = _s("CLAUDE_VERTEX_REGION", "global")
MAX_TOKENS = _i("CLAUDE_MAX_TOKENS", 8000)                  # 思考 token 計入；太細會截斷
KEY_EXPIRES_UTC = _s("ANTHROPIC_KEY_EXPIRES_UTC", "2026-12-31 14:00")   # API key 到期（使用者 10-20 建）；到期前 14 日頁面警告＋Telegram 每日一次
KEY_WARN_DAYS = _i("ANTHROPIC_KEY_WARN_DAYS", 14)

# --- 硬性風控（AI 無權超越）---
LOTS = _f("XAU_LOTS", 0.01)
MAX_LOTS = _f("XAU_MAX_LOTS", 0.10)
MIN_SL_USD = _f("XAU_MIN_SL_USD", 2.0)                      # 止損距離下限（美元／盎司）
MAX_SL_USD = _f("XAU_MAX_SL_USD", 30.0)                     # 止損距離上限
MIN_CONFIDENCE = _f("XAU_MIN_CONFIDENCE", 0.6)              # 開倉要嘅最低信心
MAX_TRADES_PER_DAY = _i("XAU_MAX_TRADES_PER_DAY", 0)        # 0 = 唔限（紐約交易日計）
MAX_HOLD_MIN = _i("XAU_MAX_HOLD_MIN", 1440)                 # 最長持倉，到時程式強制平倉（安全網）
LONG_ONLY = _b("XAU_LONG_ONLY", False)                      # 影子階段兩邊都記錄；實倉前使用者決定
MAGIC = _i("XAU_MAGIC", 921)                               # 線上 V23 用 920，天覆陣用 921 免互相當自己單（總指揮 10-20）
# --- 風控階梯（RISK_LADDER §6c，PR #237；使用者 10-20：「龍飛陣，沒有硬鎖，這個概念可以刪除」）---
# 百分比對本金；本金只放 GCS xau/control.json principal_hkd，唔入 repo。日蝕只計天覆陣自己嘅單。
# 日蝕 −3% → PAUSE（停開新倉）、−6% → 平倉＋STOP；兩者紐約 17:00 換日自動返 RUN。
# 保證金水平（全戶口，EA 回報）< 300%（夜盤 ×1.5）→ PAUSE，回升自動解；< 200%／< 150% 只發 Telegram。
# 累計虧損 25% → PAUSE（換日自動返 RUN，當日事件）；高水位回撤 10%／20% 只發 Telegram。冇任何要人手解鎖嘅狀態；STOP 只由日蝕 −6% 或使用者設。
DAILY_LOSS_PAUSE_PCT = _f("XAU_DAILY_LOSS_PAUSE_PCT", 3.0)
DAILY_LOSS_STOP_PCT = _f("XAU_DAILY_LOSS_STOP_PCT", 6.0)
MARGIN_PAUSE_PCT = _f("XAU_MARGIN_PAUSE_PCT", 300.0)
MARGIN_ALERT_PCTS = (_f("XAU_MARGIN_ALERT1_PCT", 200.0), _f("XAU_MARGIN_ALERT2_PCT", 150.0))
DD_ALERT_PCTS = (_f("XAU_DD_ALERT1_PCT", 10.0), _f("XAU_DD_ALERT2_PCT", 20.0))        # 對高水位回撤，只提示
# 累計虧損 ≥ 25%（使用者 10-20 揀 A）：PAUSE＋Telegram，紐約換日自動 RUN；觸發係「當日事件」——由 <25% 升到 ≥25% 嗰下先觸發，
# 換日後仍 ≥25% 都照開新倉，要跌返落 25% 以下再升穿先會再停。XAU_CUM_LOSS_RETRIGGER=daily 改為每日只要 ≥25% 就再 PAUSE。
CUM_LOSS_PAUSE_PCT = _f("XAU_CUM_LOSS_PAUSE_PCT", 25.0)
CUM_LOSS_RETRIGGER = _s("XAU_CUM_LOSS_RETRIGGER", "edge").lower()                    # edge | daily
NIGHT_MULT = _f("XAU_NIGHT_MULT", 1.5)                      # 夜盤（紐約 18:00–02:00 ET）PAUSE 線 ×1.5
HKD_PER_USD = _f("XAU_HKD_PER_USD", 7.8)
SPREAD_USD = _f("XAU_SPREAD_USD", 0.30)                     # 紙上模擬每張來回成本（點差）

# --- 數據 ---
M1_MAX = _i("XAU_M1_MAX", 200)                              # ≈ 3 小時
M15_MAX = _i("XAU_M15_MAX", 200)                            # ≈ 50 小時
M1_GAP_RESET_SEC = _i("XAU_M1_GAP_RESET_SEC", 30 * 60)
CONTRACT_SIZE = 100.0                                       # XAUUSD 1 手 = 100 盎司
DECISION_LOG_MAX = 300

# 每百萬 token 美元（估算用；cache_write ≈ 輸入 ×1.25）
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
}
