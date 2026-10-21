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


TEAM_NAME = _s("XAU_TEAM_NAME", "天覆陣訊號書" if _s("XAU_BOOK", "claude").lower() == "signal" else "天覆陣")
TEAM_EMOJI = _s("XAU_TEAM_EMOJI", "🌌")
ZHUGE_URL = _s("ZHUGE_URL", "https://zhuge-risk-manager-1056099871997.europe-west1.run.app/").rstrip("/") + "/"   # 舊服務（導覽列連去各陣頁）
SYMBOL = _s("XAU_SYMBOL", "XAUUSD").upper()
# --- 產品表（使用者 10-21：擴展到主要外匯，一個產品一個服務；環境變數名沿用 XAU_* 係歷史原因）---
# pip：1 pip 嘅價格；digits：報價小數位；min/max_sl_pips：止損距離範圍；spread_pips：紙上模擬每張來回成本；
# quote：報價貨幣（紙上盈虧 = 價差 × 合約 × 手數，單位係 quote；quote 唔係 USD 要設 XAU_QUOTE_PER_USD 換算）；prefix：GCS 前綴；magic：EA magic
PRODUCTS = {
    "XAUUSD": {"contract": 100.0, "pip": 1.0, "digits": 2, "min_sl_pips": 2.0, "max_sl_pips": 30.0, "spread_pips": 0.30, "quote": "USD",
               "prefix": "xau/", "magic": 921, "kind": "gold",
               "desc": "spot gold CFD {symbol} on MetaTrader 5 (1 lot = 100 oz, price in US$ per oz, 1 pip = US$1)"},
    "EURUSD": {"contract": 100000.0, "pip": 0.0001, "digits": 5, "min_sl_pips": 5.0, "max_sl_pips": 40.0, "spread_pips": 1.0, "quote": "USD",
               "prefix": "fx/eurusd/", "magic": 922, "kind": "fx",
               "desc": "EUR/USD spot forex CFD {symbol} on MetaTrader 5 (1 lot = 100,000 EUR, price in US$ per EUR, 1 pip = 0.0001)"},
    "GBPUSD": {"contract": 100000.0, "pip": 0.0001, "digits": 5, "min_sl_pips": 6.0, "max_sl_pips": 50.0, "spread_pips": 1.2, "quote": "USD",
               "prefix": "fx/gbpusd/", "magic": 923, "kind": "fx",
               "desc": "GBP/USD spot forex CFD {symbol} on MetaTrader 5 (1 lot = 100,000 GBP, price in US$ per GBP, 1 pip = 0.0001)"},
    "AUDUSD": {"contract": 100000.0, "pip": 0.0001, "digits": 5, "min_sl_pips": 5.0, "max_sl_pips": 40.0, "spread_pips": 1.0, "quote": "USD",
               "prefix": "fx/audusd/", "magic": 924, "kind": "fx",
               "desc": "AUD/USD spot forex CFD {symbol} on MetaTrader 5 (1 lot = 100,000 AUD, price in US$ per AUD, 1 pip = 0.0001)"},
    "USDJPY": {"contract": 100000.0, "pip": 0.01, "digits": 3, "min_sl_pips": 5.0, "max_sl_pips": 40.0, "spread_pips": 1.0, "quote": "JPY",
               "prefix": "fx/usdjpy/", "magic": 925, "kind": "fx",
               "desc": "USD/JPY spot forex CFD {symbol} on MetaTrader 5 (1 lot = 100,000 USD, price in JPY per US$, 1 pip = 0.01)"},
}
PRODUCT = PRODUCTS.get(SYMBOL) or {"contract": 100000.0, "pip": 0.0001, "digits": 5, "min_sl_pips": 5.0, "max_sl_pips": 40.0, "spread_pips": 1.0,
                                     "quote": "USD", "prefix": f"fx/{SYMBOL.lower()}/", "magic": 929, "kind": "fx",
                                     "desc": "spot forex CFD {symbol} on MetaTrader 5 (1 lot = 100,000 base units)"}
PIP = _f("XAU_PIP", PRODUCT["pip"])
PRICE_DIGITS = _i("XAU_PRICE_DIGITS", PRODUCT["digits"])
PRODUCT_KIND = PRODUCT["kind"]
PRODUCT_DESC = _s("XAU_PRODUCT_DESC", PRODUCT["desc"]).replace("{symbol}", SYMBOL)
QUOTE_CCY = PRODUCT["quote"]
QUOTE_PER_USD = _f("XAU_QUOTE_PER_USD", 1.0)                 # 報價貨幣兌美元（USDJPY 要設，例如 150）；USD 報價 = 1
TOKEN = _s("WEBHOOK_SECRET_TOKEN", "")                      # 同 zhuge-risk-manager 相同；心跳同指令回報都要帶
BUCKET = _s("XAU_BUCKET", "zhuge-risk-manager-bucket")
# --- 訊號書（使用者 10-21 揀方案 B：xau/TG_SIGNAL_PROPOSAL.md）---
# XAU_BOOK=signal：同一套程式另開一個服務（zhuge-xau-sig 等），GCS 前綴 <產品前綴>sig/、magic +10（931–935）；
# 原本 921–925 服務完全睇唔到訊號，做對照組。S0 階段只收訊號、解析、存檔，唔問 Opus、唔落單（EA 心跳一律 ignored）。
BOOK = _s("XAU_BOOK", "claude").lower()                     # claude（預設）| signal
SIGNAL_BOOK = BOOK == "signal"
MAIN_PREFIX = PRODUCT["prefix"]                             # 主服務前綴：訊號書讀佢嘅 m1.json 攞最新價（只讀）
PREFIX = _s("XAU_PREFIX", PRODUCT["prefix"] + ("sig/" if SIGNAL_BOOK else ""))   # 本服務只寫呢個前綴（XAUUSD xau/、外匯 fx/<symbol>/；訊號書加 sig/）

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
MIN_SL_PIPS = _f("XAU_MIN_SL_PIPS", PRODUCT["min_sl_pips"])  # 止損距離範圍（pip；XAUUSD 1 pip = 1 美元）
MAX_SL_PIPS = _f("XAU_MAX_SL_PIPS", PRODUCT["max_sl_pips"])
MIN_SL_USD = _f("XAU_MIN_SL_USD", MIN_SL_PIPS * PIP)        # 同一範圍以價格單位表示（名稱沿用）
MAX_SL_USD = _f("XAU_MAX_SL_USD", MAX_SL_PIPS * PIP)
MIN_CONFIDENCE = _f("XAU_MIN_CONFIDENCE", 0.6)              # 開倉要嘅最低信心
MAX_TRADES_PER_DAY = _i("XAU_MAX_TRADES_PER_DAY", 0)        # 0 = 唔限（紐約交易日計）
MAX_HOLD_MIN = _i("XAU_MAX_HOLD_MIN", 1440)                 # 最長持倉，到時程式強制平倉（安全網）
LONG_ONLY = _b("XAU_LONG_ONLY", False)                      # 影子階段兩邊都記錄；實倉前使用者決定
MAGIC = _i("XAU_MAGIC", PRODUCT["magic"] + (10 if SIGNAL_BOOK else 0))   # XAUUSD 921（V23 用 920）、EURUSD 922、GBPUSD 923、AUDUSD 924、USDJPY 925；訊號書 +10（931–935）
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
SPREAD_USD = _f("XAU_SPREAD_USD", PRODUCT["spread_pips"] * PIP)   # 紙上模擬每張來回成本（點差，價格單位）

# --- 數據 ---
M1_MAX = _i("XAU_M1_MAX", 400)                              # ≈ 6.7 小時（要 ≥ 315 根先砌到 20 根 M15）
M15_MIN_BARS = 20                                            # Claude 決策要 ≥ 20 根 M15
M15_MAX = _i("XAU_M15_MAX", 200)                            # ≈ 50 小時
M1_GAP_RESET_SEC = _i("XAU_M1_GAP_RESET_SEC", 30 * 60)
CONTRACT_SIZE = _f("XAU_CONTRACT_SIZE", PRODUCT["contract"])   # XAUUSD 1 手 = 100 盎司；外匯 1 手 = 100,000
DECISION_LOG_MAX = 300

# 每百萬 token 美元（估算用；cache_write ≈ 輸入 ×1.25）
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
}

# --- 訊號書入口（S0；只喺 SIGNAL_BOOK 生效）---
# VM 監聽程式用 TG_SIGNAL_INGEST_SECRET 做 HMAC-SHA256 簽名（標頭 X-Sig-Ts、X-Sig-Signature，內容 = f"{ts}.{原始 body}"），
# 唔用 WEBHOOK_SECRET_TOKEN（已等於公開，handoff §6.4b）。密鑰由使用者喺 Cloud Run 控制台填，唔經對話。
SIG_INGEST_SECRET = _s("TG_SIGNAL_INGEST_SECRET", "")
SIG_MAX_SKEW_SEC = _i("SIG_MAX_SKEW_SEC", 300)               # 簽名時間戳最多差幾秒（防重播）
SIG_RATE_PER_MIN = _i("SIG_RATE_PER_MIN", 30)                # 每個容器每分鐘最多幾個請求（超過回 429）
SIG_MAX_BODY = _i("SIG_MAX_BODY", 16000)                     # body 上限 bytes
SIG_TTL_MIN = _i("SIG_TTL_MIN", 30)                          # 訊號有效分鐘（由訊息時間起計）
SIG_PRICE_MAX_AGE_SEC = _i("SIG_PRICE_MAX_AGE_SEC", 300)     # 主服務最新 M1 最舊可接受幾秒，再舊就標 unverified
SIG_MAX_DRIFT = _f("SIG_MAX_DRIFT", MAX_SL_USD)               # 入場區離現價最多幾多（價格單位；預設 = 止損上限）
SIG_MAX_SL = _f("SIG_MAX_SL", MAX_SL_USD * 2)                 # 訊號止損距離上限（價格單位；只用嚟判斷訊號係咪合理，唔係落單止損）
SIG_PARSE_MODEL = _s("SIG_PARSE_MODEL", GATE_MODEL or "claude-haiku-5-5")
SIG_FILL_TOL = _f("SIG_FILL_TOL", SPREAD_USD)              # 計頻道準確度：限價入場區容許幾多誤差（頻道報價同 Ultima 唔同、買價＝賣價＋點差）
SIG_ASSUME_SYMBOL = _b("SIG_ASSUME_SYMBOL", True)            # 訊息冇寫商品就當本產品（使用者 10-21：頻道淨係出 XAUUSD）；入場離現價檢查會擋走其他商品
SIG_RECENT_MAX = 100
