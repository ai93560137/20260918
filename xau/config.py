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
FOLLOW_ACCOUNT = _s("SIG_FOLLOW_ACCOUNT", "") or ACCOUNT    # [R357] 932 跟單嘅登入號（使用者 10-31：931 搬去另一戶口，932 留原戶口）；留空＝同 XAU_ACCOUNT
TEST_CMDS = _b("XAU_TEST_CMDS", False)                       # 1 = 開放 action=test_cmd（階段 B 測試清單用；真倉前要關）
# 10-23 使用者決定權杖「keep 123456」（公開）：cmd_ack 要核對 account（EA v0.38 起回報帶登入號）；
#   XAU_ACK_REQUIRE_ACCOUNT=1 時冇 account 嘅回報一律忽略（真倉開；demo 舊 EA 仍可用 0）
ACK_REQUIRE_ACCOUNT = _b("XAU_ACK_REQUIRE_ACCOUNT", False)

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
LOTS_LADDER = _b("XAU_LOTS_LADDER", False)                 # [R346] 手數階梯：每次全部平倉賺 +LOTS_STEP、蝕 −LOTS_STEP，夾喺 LOTS_MIN–MAX_LOTS；起點 XAU_LOTS（使用者 10-27 0.05→0.10）
LOTS_MIN = _f("XAU_LOTS_MIN", LOTS)
LOTS_STEP = _f("XAU_LOTS_STEP", 0.01)
LOTS_MILESTONE = _i("XAU_LOTS_MILESTONE", 0)              # [R349] 已達成里程碑數 0–4（MILESTONES M1–M4；總指揮 env set、使用者批）→ 升級上限 LOTS_MILESTONE_CAPS[n-1]；0＝上限係起點（使用者 10-28「達到里程碑先增加」）
LOTS_MILESTONE_CAPS = tuple(float(x) for x in _s("XAU_LOTS_MILESTONE_CAPS", "0.06,0.07,0.08,0.10").split(",") if x.strip())   # [R349] M1→0.06、M2→0.07、M3→0.08、M4→0.10
MIN_SL_PIPS = _f("XAU_MIN_SL_PIPS", PRODUCT["min_sl_pips"])  # 止損距離範圍（pip；XAUUSD 1 pip = 1 美元）
MAX_SL_PIPS = _f("XAU_MAX_SL_PIPS", PRODUCT["max_sl_pips"])
MIN_SL_USD = _f("XAU_MIN_SL_USD", MIN_SL_PIPS * PIP)        # 同一範圍以價格單位表示（名稱沿用）
MAX_SL_USD = _f("XAU_MAX_SL_USD", MAX_SL_PIPS * PIP)
MODIFY_MIN_DIST_USD = _f("XAU_MODIFY_MIN_DIST_USD", MIN_SL_USD + PRODUCT["spread_pips"] * PIP + PIP)   # [R340] UPDATE_STOP 新止損離現價最少幾多（價格單位）：經紀 stops level ≈ 最小止損距離，再加點差＋1 pip 緩衝；太貼就夾到呢個距離，夾完唔比現止損緊就唔發 modify（10-26／27 EURUSD E1／E3 Opus 追到 5 pip，EA 拒 18 次 invalid stops）
CHASE_BLOCK = _b("XAU_CHASE_BLOCK", PRODUCT["kind"] == "gold")   # [R351] M1 硬規則（使用者 10-30 批）：急跌後反抽沽／急升後回落買一律擋；黃金預設開，外匯數字未校準預設關
CHASE_WINDOW_MIN = _i("XAU_CHASE_WINDOW_MIN", 15)            # 回望幾多根 M1（含啱啱收盤嗰根）
CHASE_MOVE_USD = _f("XAU_CHASE_MOVE_USD", 6.0 * PIP)         # 窗內先高後低（買：先低後高）幅度 ≥ 呢個先算急跌／急升
CHASE_BACK_USD = _f("XAU_CHASE_BACK_USD", 3.0 * PIP)         # 決策價離該低位（買：高位）≥ 呢個＝已反抽，擋
SL_COOLDOWN_MIN = _i("XAU_SL_COOLDOWN_MIN", 15)              # [R355] #145 P2（使用者 10-30「提早判」）：止損平倉後 N 分鐘內唔准同方向再開（0＝關）
MAX_ENTRY_SLIP = _f("XAU_MAX_ENTRY_SLIP", 1.5 * PIP if PRODUCT["kind"] == "gold" else 0.0)   # [R355] #145 P3：open 指令帶 px=決策價｜dev=；EA v0.41 見不利偏離 > dev 唔開（0＝唔帶）
STOP_TIGHTEN_ONLY = _b("XAU_STOP_TIGHTEN_ONLY", True)       # [R354] UPDATE_STOP 只准收緊（10-30 L26 AI「止損放闊至6美元」放鬆 0.90 冇被擋）；硬性風控，AI 無權改
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
DATA_BLOCK_HOURS = _f("DATA_BLOCK_HOURS", 4.0)                # [R348] 美國高影響數據前幾多小時唔開新倉（GCS ops/us_data_calendar.json；0＝關）。使用者 10-28「數據之前4小時不入市」
HKD_PER_USD = _f("XAU_HKD_PER_USD", 7.8)
SPREAD_USD = _f("XAU_SPREAD_USD", PRODUCT["spread_pips"] * PIP)   # 紙上模擬每張來回成本（點差，價格單位）

# --- 數據 ---
M1_MAX = _i("XAU_M1_MAX", 400)                              # ≈ 6.7 小時（要 ≥ 315 根先砌到 20 根 M15）
BARS_ARCHIVE = _i("XAU_BARS_ARCHIVE", 1)                     # [R345] 每根新 M1 存入 <PREFIX>bars/<UTC 日>.jsonl（全日 K 線，EURUSD 即日回測用；0＝關）
M15_MIN_BARS = 20                                            # Claude 決策要 ≥ 20 根 M15
M15_MAX = _i("XAU_M15_MAX", 200)                            # ≈ 50 小時
M15_OLDER_MAX = _i("XAU_M15_OLDER_MAX", 160)                # prompt 嘅「整點前 M15」固定攞最後 160 根（≈40 小時）：
                                                             # 10-23 慳成本 G——之前攞晒 <hour0 嘅全部，M15 清單封頂 200 根，每 15 分鐘最舊一根跌出就令 1h 快取段（連後面 M1 段）全部重寫
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
SIG_MERGE_SEC = _i("SIG_MERGE_SEC", 60)                      # [R343] 同一頻道幾秒內連續訊息合併解析（只喺單條判 invalid 時先試；0＝關）。10-27 黃金戰鬥機一條訊號拆兩條（「BUY」／入場區 SL TP）逐條都 invalid
SIG_PRICE_MAX_AGE_SEC = _i("SIG_PRICE_MAX_AGE_SEC", 300)     # 主服務最新 M1 最舊可接受幾秒，再舊就標 unverified
SIG_MAX_DRIFT = _f("SIG_MAX_DRIFT", MAX_SL_USD)               # 入場區離現價最多幾多（價格單位；預設 = 止損上限）
SIG_MAX_SL = _f("SIG_MAX_SL", MAX_SL_USD * 2)                 # 訊號止損距離上限（價格單位；只用嚟判斷訊號係咪合理，唔係落單止損）
SIG_PARSE_MODEL = _s("SIG_PARSE_MODEL", GATE_MODEL or "claude-haiku-5-5")
SIG_FILL_TOL = _f("SIG_FILL_TOL", SPREAD_USD)              # 計頻道準確度：限價入場區容許幾多誤差（頻道報價同 Ultima 唔同、買價＝賣價＋點差）
SIG_ASSUME_SYMBOL = _b("SIG_ASSUME_SYMBOL", True)            # 訊息冇寫商品就當本產品（使用者 10-21：頻道淨係出 XAUUSD）；入場離現價檢查會擋走其他商品
SIG_RECENT_MAX = 100
# S1（總指揮 10-21 轉達使用者「訊號書都要落單」）：SIG_DECIDE=1 先處理 EA 心跳（magic 931 圖表）同問 Claude；
# 只喺有有效訊號（未過期）或者有倉時先問；開倉一定要引用有效訊號。落唔落單照舊由 XAU_EXECUTE 決定（demo 先）。
SIG_DECIDE = _b("SIG_DECIDE", False)
# [R353] 931 S1 開新倉開關：使用者 10-30 先講「931 留畀規則學生」、之後改口「不用停」→ 預設開（S1 照舊，參考 7713）；
# 規則學生過門檻（IDEAS #146，11-25）後再定 931 點用。要停 S1 用 SIG_S1_OPEN=0，**唔好用 SIG_DECIDE=0**（規則學生靠 931 心跳推動，會一齊停）。
SIG_S1_OPEN = _b("SIG_S1_OPEN", True)
SIG_MAX_IN_PROMPT = _i("SIG_MAX_IN_PROMPT", 5)
# S1 demo 落單（使用者 10-22 批）：只參考指定頻道（頻道 id 尾 4 位，逗號分隔；空＝全部）；其他頻道只當「附和」計數
SIG_REFERENCE_CHANNELS = tuple(x.strip()[-4:] for x in _s("SIG_REFERENCE_CHANNELS", "").split(",") if x.strip())
# 收到／決策時價已經過咗 TP1、或者已經向有利方向走咗 ≥ SIG_LATE_R × 止損距離 → 當過期（90 日回測：該頻道 44% 訊號出時價已過 TP1）
SIG_LATE_R = _f("SIG_LATE_R", 1.0)
SIG_AGREE_MIN = _i("SIG_AGREE_MIN", 30)                      # 幾多分鐘內另一個頻道同方向算「附和」
# 跟單（使用者 10-22 批「CTC 0.01 手執銀仔落 demo」；IDEAS #123）：只限指定頻道（尾 4 位；空＝關）、固定手數、TP1 全平、用頻道原 SL、獨立 magic
FOLLOW_CHANNELS = tuple(x.strip()[-4:] for x in _s("SIG_FOLLOW_CHANNELS", "").split(",") if x.strip())
CHANNEL_NAMES = dict((k.strip()[-4:], v.strip()) for k, _, v in (x.partition(":") for x in _s("SIG_CHANNEL_NAMES", "5231:CTC,7713:DAN,0342:GoldBrother,5117:黃金戰鬥機").split(",")) if k.strip() and v.strip())   # [R350] 頻道尾號 → 名稱（MT5 註解「跟單CTC」）
FOLLOW_MAGIC = _i("SIG_FOLLOW_MAGIC", MAGIC + 1)             # 931 → 932（EA InpBotMagics 已包 931–935，計入戶口總階梯）
FOLLOW_LOTS = _f("SIG_FOLLOW_LOTS", 0.01)
FOLLOW_LOTS_LADDER = _b("SIG_FOLLOW_LOTS_LADDER", LOTS_LADDER)   # [R346] 跟單（932）自己一個級數；預設跟 XAU_LOTS_LADDER
FOLLOW_LOTS_MIN = _f("SIG_FOLLOW_LOTS_MIN", FOLLOW_LOTS)
FOLLOW_LOTS_MILESTONE = _i("SIG_FOLLOW_LOTS_MILESTONE", 0)    # [R349] 932 自己計已達成里程碑數（唔跟 921）
FOLLOW_MAX_LOTS = _f("SIG_FOLLOW_MAX_LOTS", MAX_LOTS)
# 10-23 DAN 第一張跟單：市價 BUY 時 TP1 只差 0.5 美元、SL 差 9.5 → 加「剩餘空間」下限：
#   現價到 TP1 ≥ SIG_FOLLOW_MIN_TP（價格單位；DAN TP1 步距 3、CTC 4–6，唔受影響），另外同 S1 一樣用 signals.is_late 略過「走咗」嘅限價訊號
FOLLOW_MIN_TP = _f("SIG_FOLLOW_MIN_TP", 2.0 if PRODUCT["digits"] == 2 else 0.0004)
# 10-23 使用者「逐級鎖，唔用 shadow，真」：呢啲頻道（尾 4 位）嘅跟單出場用逐級鎖——開倉 TP 掛最後一級，到 TP1 止損移保本，
#   之後每到 TP(k) 止損移到 TP(k−1)，只准收緊；其他頻道維持 TP1 全平。例 SIG_FOLLOW_LADDER_CHANNELS=7713（DAN）
FOLLOW_LADDER_CHANNELS = tuple(x.strip()[-4:] for x in _s("SIG_FOLLOW_LADDER_CHANNELS", "").split(",") if x.strip())
FOLLOW_LADDER_BUF = _f("SIG_FOLLOW_LADDER_BUF", 0.0)          # 鎖位再退幾多（價格單位；0＝剛好保本／上一級）
# 10-24 使用者「加『唔跟未到入場價』規則，倫敦時段都避」（CTC 入場點分析：提案 §27——收到時價仍未到入場價嗰 45% 係 −1.08 美元／張；倫敦 07–12 UTC −1.61／張）
#   SIG_FOLLOW_SKIP_UNREACHED_CHANNELS：呢啲頻道收到時現價仍喺入場價嘅反向（離 ≥ SIG_FOLLOW_UNREACHED_TOL）就略過，唔等限價；DAN 限價區設計上係反向 4±2，唔適用
#   SIG_FOLLOW_AVOID_HOURS：頻道:起-止（UTC 整點，止不含），逗號分隔多個；呢段時間收到嘅訊號略過。空＝關
FOLLOW_SKIP_UNREACHED_CHANNELS = tuple(x.strip()[-4:] for x in _s("SIG_FOLLOW_SKIP_UNREACHED_CHANNELS", "5231").split(",") if x.strip())
FOLLOW_UNREACHED_TOL = _f("SIG_FOLLOW_UNREACHED_TOL", 0.3 if PRODUCT["digits"] == 2 else 0.00003)
FOLLOW_AVOID_HOURS = _s("SIG_FOLLOW_AVOID_HOURS", "5231:07-12")
# 學徒計劃階段 0／1（使用者 10-22 批；xau/DAN_APPRENTICE.md、IDEAS #122）：特徵快照（永遠開）、規則學生（免費）、Claude 學生（XAU_SHADOW=1 先問 Opus）
STUDENT = _b("XAU_STUDENT", True)
SHADOW = _b("XAU_SHADOW", False)
SHADOW_HOURS_UTC = _s("XAU_SHADOW_HOURS_UTC", "01-07,12-15")       # DAN 活躍時段（§18）
SHADOW_INTERVAL_MIN = _i("XAU_SHADOW_INTERVAL_MIN", 30)
STUDENT_WINDOW_MIN = _i("XAU_STUDENT_WINDOW_MIN", 30)               # 訊號到之前幾多分鐘內嘅判斷先算「交咗卷」
STUDENT_ZONE_TOL = _f("XAU_STUDENT_ZONE_TOL", 3.0)                  # 入場區中位差 ≤3 美元算命中
STUDENT_R_TARGET = _f("XAU_STUDENT_R_TARGET", 2.0)                  # 學生自己成績：2R 全平
STUDENT_COST = _f("XAU_STUDENT_COST", SPREAD_USD + 0.2)             # 10-24 使用者批：學生自己成績用實際成交價計 R，每張扣點差＋滑價 0.2（美元／盎司）

# --- 慳成本（使用者 10-21 揀「穩陣 A+F+D」；xau/COST_PLAN.md）---
# A：決策嘅「產品＋整點前 M15」快取段用 1h（一個鐘先變一次），整點前 M1 段仍然 5m；system 本身已經 1h
CACHE_TTL_STABLE = _s("CACHE_TTL_STABLE", "1h")
# 10-23 晚：M1 段（整點前 M1，每個鐘先變一次）由 5m 改 1h。10-23 實數：Haiku 篩走＋H 規則令 Opus 調用相隔常 >5 分鐘，5m 段 62 次重寫（$0.49）；
#   1h 寫 $8/M 但每個鐘只寫一次（23×1,596 tok ≈ $0.29）→ 每日慳約 $0.15（XAU）／$0.02（EUR）。退回：CACHE_TTL_M1=5m
CACHE_TTL_M1 = _s("CACHE_TTL_M1", "1h")
# 10-23 使用者「做 1 至 4 … Opus 唔講話」：即時段（每次都要重新讀、$4/M）由 ≈1,960 tok 壓到 ≈1,300：
#   ① 風控常數（手數、止損上下限、信心門檻、日上限、最長持倉）搬入 product（1h 快取段）；② recent_decisions 6 → 3；
#   ③ 本小時 M1 時間欄改「本小時第幾分鐘」（0–59，唔再 10 位 epoch）；④ 本小時 M1 只送最近 M1_LIVE_MAX 根。
#   reason 改短標籤（最多 REASON_MAX_CHARS 個字；0＝叫 Opus 留空），日誌行由 Python 按 action／價／SL／TP／信心組出（輸出 265 → 約 40 tok）。
M1_LIVE_MAX = _i("XAU_M1_LIVE_MAX", 30)                     # 本小時 M1 最多送幾根（0＝全部）
RECENT_DECISIONS = _i("XAU_RECENT_DECISIONS", 3)            # 即時段帶幾條最近決策
REASON_MAX_CHARS = _i("XAU_REASON_MAX_CHARS", 20)           # Opus reason 標籤上限；0＝留空。退回舊行為：XAU_REASON_MAX_CHARS=200
# F：空倉、上次係 HOLD、價格變動 < REUSE_ATR_MULT × M1 ATR、冇新 M15 收盤 → 沿用 HOLD（最多連續 REUSE_MAX_MIN 分鐘）
#    off｜shadow（預設：只記錄「會沿用」唔慳錢，驗證一日）｜on
REUSE_HOLD = _s("XAU_REUSE_HOLD", "shadow").lower()
REUSE_ATR_MULT = _f("XAU_REUSE_ATR_MULT", 0.3)
REUSE_MAX_MIN = _i("XAU_REUSE_MAX_MIN", 5)
# D：空倉時只喺呢段 UTC 鐘數問 Claude（例 "07-17" = 07:00–16:59 UTC；空＝全日）；有倉照管
ACTIVE_HOURS_UTC = _s("XAU_ACTIVE_HOURS_UTC", "")
# H（使用者 10-23 揀「穩陣＋H」）：有倉時程式按教學第 1／4 條移止損（hold_rules.py）；off｜shadow（預設：只記錄唔改行為）｜on
#    on 時 Opus 只喺新 M15／首次 1R／價格離 SL 或 TP ≤0.5×ATR／每 HOLD_RULES_ASK_MIN 分鐘先問；止損只准收緊、唔收到 0.5×ATR 內
HOLD_RULES = _s("XAU_HOLD_RULES", "shadow").lower()
# S（使用者 10-23「開 S shadow」）：空倉時規則前篩（prescreen.py），off｜shadow（預設：照問，只記錄）｜on（唔問，cost 0）
#    問 Opus 條件：新 M15／價格離上次問 Opus ≥ ATR_MULT×M1 ATR／貼近擺動點或前日高低亞洲高低 ≤ NEAR／前 15 分鐘走 ≥ MOVE15
PRESCREEN = _s("XAU_PRESCREEN", "shadow").lower()
PRESCREEN_ATR_MULT = _f("XAU_PRESCREEN_ATR_MULT", 0.3)
PRESCREEN_NEAR = _f("XAU_PRESCREEN_NEAR", 2.0 if PRODUCT["digits"] == 2 else 0.0005)
PRESCREEN_MOVE15 = _f("XAU_PRESCREEN_MOVE15", 3.0 if PRODUCT["digits"] == 2 else 0.0010)
HOLD_RULES_ASK_MIN = _i("XAU_HOLD_RULES_ASK_MIN", 5)
HOLD_RULES_TOL = _f("XAU_HOLD_RULES_TOL", 1.0 if PRODUCT["digits"] == 2 else 0.0010)   # shadow 統計：規則 vs Opus 止損「相差 ≤tol」
