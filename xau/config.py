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
LEGACY_GATE_FILE = _s("XAU_LEGACY_GATE_FILE", "zhuge_gate_state.json")   # 影子階段只讀舊服務嘅電閘（唔寫）

# --- 模式 ---
# EXECUTE=0（預設）：影子模式——Claude 照決策、紙上模擬、只寫 GCS，心跳回應 cmd_text 永遠空。
# EXECUTE=1：真倉——決定變成指令由 EA 執行。切換前要達到 IDEAS.md 預先登記嘅影子標準。
EXECUTE = _b("XAU_EXECUTE", False)

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

# --- 硬性風控（AI 無權超越）---
LOTS = _f("XAU_LOTS", 0.01)
MAX_LOTS = _f("XAU_MAX_LOTS", 0.10)
MIN_SL_USD = _f("XAU_MIN_SL_USD", 2.0)                      # 止損距離下限（美元／盎司）
MAX_SL_USD = _f("XAU_MAX_SL_USD", 30.0)                     # 止損距離上限
MIN_CONFIDENCE = _f("XAU_MIN_CONFIDENCE", 0.6)              # 開倉要嘅最低信心
MAX_TRADES_PER_DAY = _i("XAU_MAX_TRADES_PER_DAY", 0)        # 0 = 唔限（紐約交易日計）
MAX_HOLD_MIN = _i("XAU_MAX_HOLD_MIN", 1440)                 # 最長持倉，到時程式強制平倉（安全網）
LONG_ONLY = _b("XAU_LONG_ONLY", False)                      # 影子階段兩邊都記錄；實倉前使用者決定
MAGIC = _i("XAU_MAGIC", 920)
CALL_WHEN_LOCKED = _b("XAU_CALL_WHEN_LOCKED", False)        # 空倉而電閘 LOCK 時唔問 Claude（慳錢）
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
