"""設定：全部由 .env 或環境變數讀入。硬性風控數字喺呢度，AI 無權改。"""
import os
from dataclasses import dataclass, replace
from pathlib import Path

import markets
from markets import FX_TO_HKD, spec_for

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")

# 執行期檔案（logs、state、STOP／PAUSE、心跳）放呢度；VM 上設喺 repo 外，免受 git reset 影響
DATA_DIR = Path(os.getenv("AI_DATA_DIR") or BASE_DIR).expanduser()


def _env(name, default):
    return os.getenv(name, default)


# 使用者 2026-10-16：HSI 大期，之後加 MES、MNQ、MYM；每隻產品一個獨立程式（PRODUCT 環境變數）
_PRODUCT = _env("PRODUCT", "HSI").upper()
SPEC = spec_for(_PRODUCT)
# [R209] 使用者 10-17：真倉同模擬倉並行。模擬程式（zhuge-longfei／zhuge-longfei@<產品>）永遠 SIMULATE；
# 真倉程式（zhuge-longfei-real@<產品>，LONGFEI_INSTANCE=REAL）要產品喺 LONGFEI_REAL_PRODUCTS 先係 REAL，雙重鎖
_REAL_LIST = {x.strip().upper() for x in os.getenv("LONGFEI_REAL_PRODUCTS", "").split(",") if x.strip()}
_INSTANCE_REAL = os.getenv("LONGFEI_INSTANCE", "").strip().upper() == "REAL"
_IS_REAL = _INSTANCE_REAL and _PRODUCT in _REAL_LIST
# [R299] 使用者 10-27「揸耐啲、止蝕闊啲」：波段模式只限真倉（模擬程式冇 AI、唔開倉）
_SWING = _IS_REAL and os.getenv("SWING_EXIT", "0").strip().lower() in ("1", "true", "yes", "on")
_REAL_LOSS = None
# [R233] 使用者 10-19：美股真倉用自己嘅倉位同日蝕設定。只喺真倉程式生效，模擬照用產品預設。
# 次序：REAL_NOTIONAL_USD_<產品> → REAL_NOTIONAL_USD；REAL_DAILY_LOSS_<產品> → REAL_DAILY_LOSS_STOCK。
# 直接改 markets.SPECS 呢個程式（每隻產品一個程式）嘅產品規格，咁落單股數、AI 提示、日蝕全部一致。
if _IS_REAL and SPEC.kind == "stock":
    _n = os.getenv(f"REAL_NOTIONAL_USD_{_PRODUCT}") or os.getenv("REAL_NOTIONAL_USD")
    _l = _REAL_LOSS = os.getenv(f"REAL_DAILY_LOSS_{_PRODUCT}") or os.getenv("REAL_DAILY_LOSS_STOCK")
    SPEC = replace(SPEC, notional_usd=float(_n) if _n else SPEC.notional_usd,
                   daily_loss_hkd=float(_l) if _l else SPEC.daily_loss_hkd)
    markets.SPECS[_PRODUCT] = SPEC


def _bool(name, default):
    return str(os.getenv(name, default)).lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    # --- Futu OpenD ---
    opend_host: str = _env("OPEND_HOST", "127.0.0.1")
    opend_port: int = int(_env("OPEND_PORT", "11111"))
    # 唔再跟 TRD_ENV（HSI 都係）：真倉只喺真倉程式＋settings.env 嘅 LONGFEI_REAL_PRODUCTS 列明（改要經 PR＋「更新部機」）
    trd_env: str = "REAL" if _IS_REAL else "SIMULATE"
    instance_real: bool = _INSTANCE_REAL
    acc_id: int = int(_env("FUTU_ACC_ID", "0"))          # 0 = 自動揀第一個期貨戶口
    real_acc_id: int = int(_env("FUTU_REAL_ACC_ID", "0"))  # 真倉準備檢查用；0 = 自動揀有該市場權限嘅真實戶口
    real_preflight_min: int = int(_env("REAL_PREFLIGHT_MIN", "30"))   # 每幾分鐘唯讀檢查一次真實戶口；0 = 唔查
    trade_password: str = _env("FUTU_TRADE_PASSWORD", "")  # 留空 = 已喺 OpenD 解鎖

    # --- 合約 ---
    # 使用者 2026-10-16：龍飛陣用大期 HSI（雲垂陣對沖用細期 MHI，分開合約免得淨額混埋）；之後加 MES、MNQ、MYM
    product: str = _PRODUCT
    market: str = SPEC.market                            # HK／US
    kind: str = SPEC.kind                                # future／stock（ETF）
    currency: str = SPEC.currency
    tick: float = SPEC.tick
    roll_days: int = SPEC.roll_days
    # 每點（每張／每股）價值一律換算做 HKD（日蝕上限、止蝕風險、盈虧都用 HKD 比較）：HSI 50；MES 39；ETF 每股 7.8
    point_value: float = float(_env("POINT_VALUE", str(SPEC.point_value * FX_TO_HKD[SPEC.currency])))

    # --- Claude ---
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")
    # [R218] 使用者 10-17：決策用最強而價錢合理嘅模型（Opus 5.5，約 Sonnet 兩倍）；Fable 5.1 貴 5 倍又慢，未有數據證明值得
    model: str = _env("CLAUDE_MODEL", "claude-opus-5-5")
    decision_interval_min: int = int(_env("DECISION_INTERVAL_MIN", "5"))
    effort: str = _env("CLAUDE_EFFORT", "medium")        # low/medium/high/xhigh/max；Opus 5.5 預設 medium（寫明，免模型預設改咗都唔知）
    # [R218] 方案 A：冇倉時先用平價 Haiku 篩一次，值得睇先問決策模型；有倉照直接問（管理止蝕同平倉）。留空 = 唔篩
    gate_model: str = _env("GATE_MODEL", "claude-haiku-5-5")
    gate_effort: str = _env("GATE_EFFORT", "low")

    # --- 硬性風控（AI 無權超越）---
    max_qty: int = int(_env("MAX_QTY", "1"))
    # HK$；次序：DAILY_LOSS_LIMIT_<產品> → 期貨先跟 DAILY_LOSS_LIMIT → 產品預設（ETF HK$100,000，HSI HK$10,000）
    daily_loss_limit: float = float(_REAL_LOSS or os.getenv(f"DAILY_LOSS_LIMIT_{_PRODUCT}") or
                                    (SPEC.kind == "future" and os.getenv("DAILY_LOSS_LIMIT")) or SPEC.daily_loss_hkd)
    # 使用者 2026-10-16 取消每張止蝕 20–150 點、每日 20 次、夜市收市前平倉三條限制；0／false = 唔限
    # [R234] 真倉後備止蝕：開倉即喺富途伺服器掛 GTC 止損市價單（部機／OpenD 死咗都生效）。
    # 觸發價比程式止蝕再遠 SERVER_STOP_BUFFER_PCT%，平時由程式自己先止蝕；平倉前先撤。美股 10-19 真戶口驗證過；
    # 港期未驗證（模擬盤唔支援），所以預設只開美股，期貨要驗證後設 SERVER_STOP=1
    server_stop: bool = _IS_REAL and _bool("SERVER_STOP", "1" if SPEC.kind == "stock" else "0")
    server_stop_buffer_pct: float = float(_env("SERVER_STOP_BUFFER_PCT", "0.3"))
    # [R294] 使用者 10-26「信心 0.65」：真倉開倉要 AI 信心 ≥ 呢個數；模擬照舊（0＝唔限）
    real_min_confidence: float = float(_env("REAL_MIN_CONFIDENCE", "0")) if _IS_REAL else 0.0
    # [R295] 使用者 10-26「模擬唔再用 api call，改為即日回測」：模擬倉唔叫 Claude（決策同篩選都停），真倉照舊
    sim_ai: bool = _IS_REAL or _bool("LONGFEI_SIM_AI", "1")
    # [R297] 使用者 10-27「批 #133」：浮賺 ≥ 呢個 R 數之後，程式自動將止蝕最少移到開倉價（保本）；0＝唔開
    breakeven_at_r: float = float(_env("BREAKEVEN_AT_R", "0"))
    # [R298] 10-27 MHI 開倉單連續「下單失敗」仍然每 5 分鐘重試：同一日失敗 N 次就唔再開新倉（有倉照管）；0＝唔限
    order_fail_max: int = int(_env("ORDER_FAIL_MAX", "0"))
    # [R299] 使用者 10-27「開倉前先查購買力。ok」：真倉期貨冇倉時，問 AI 之前先問富途最多可開幾張，兩邊都 0 就 HOLD 唔叫 AI
    real_bp_check: bool = _IS_REAL and SPEC.kind != "stock" and _bool("REAL_BP_CHECK", "0")
    # [R299] 使用者 10-27「揸耐啲、止蝕闊啲。ok」（IDEAS #135）：波段出場由程式管，有倉唔再叫 AI；
    # 止蝕最少 SWING_MIN_STOP 點、每日最多開 SWING_MAX_OPENS 次；浮賺 ≥ SWING_TRAIL_START 點之後用 SWING_TRAIL 點移動止蝕（只收緊），
    # 最多揸 SWING_MAX_DAYS 個交易日（第 N 日日市收市前平）。點數按 10-27 恒指 14 日平均日波幅約 330 點：止蝕 0.35、移動 0.5 個日波幅
    swing_exit: bool = _SWING
    swing_trail_start: float = float(_env("SWING_TRAIL_START", "165"))
    swing_trail: float = float(_env("SWING_TRAIL", "165"))
    swing_max_days: int = int(_env("SWING_MAX_DAYS", "3"))
    # [R235] 使用者 10-19：美股真倉「用盡富途槓桿、唔留緩衝」：開倉股數 = 富途而家最多可買／可沽空數量
    # ÷ 未有倉嘅真倉美股隻數（等每隻都開到）。REAL_NOTIONAL_USD 唔再用。只限真倉美股
    real_size_max: bool = _IS_REAL and SPEC.kind == "stock" and _bool("REAL_SIZE_MAX", "0")
    # [R249] 使用者 10-20 揀：將來真倉每單 = REAL_SIZE_FRAC × 實時權益（HK$，例如 0.1），取代用盡槓桿；
    # 由 R248 購買力重演得出：0.1 × 權益差唔多全部模擬單都做得到。設咗就優先過 REAL_SIZE_MAX。只限真倉美股
    real_size_frac: float = float(_env("REAL_SIZE_FRAC", "0")) if (_IS_REAL and SPEC.kind == "stock") else 0.0
    real_products: tuple = tuple(sorted(_REAL_LIST))
    max_stop_points: float = float(_env("MAX_STOP_POINTS", "0"))         # 每張單最大止蝕點數，0 = 唔限
    min_stop_points: float = float(_env("SWING_MIN_STOP", "120") if _SWING else _env("MIN_STOP_POINTS", "0"))  # 0 = 唔限
    max_trades_per_day: int = int(_env("SWING_MAX_OPENS", "1") if _SWING else _env("MAX_TRADES_PER_DAY", "0"))  # 0 = 唔限
    fee_per_side_hkd: float = float(_env("FEE_PER_SIDE_HKD", str(SPEC.fee_per_side_hkd)))     # 每張每邊佣金＋徵費估算，計日蝕用（寧高唔低）
    # [R209] 真倉期貨開倉前：開倉後緩衝（淨值 − 維持保證金 − 每張初始保證金）要 ≥ Ⓑ 線（夜盤 ×1.5）＋ 日蝕上限
    # （總指揮 10-17 建議；Ⓑ 線跟 RISK_LADDER，改咗要同步）
    fut_ladder_b_day: float = float(_env("FUT_LADDER_B_DAY", "37500"))
    fut_ladder_night_mult: float = float(_env("FUT_LADDER_NIGHT_MULT", "1.5"))
    # [R216] 使用者 10-17：ETF 組合限制（只限開新倉，唔會平已有嘅倉）
    etf_group_us_eq: tuple = tuple(x.strip().upper() for x in _env("ETF_GROUP_US_EQ", "SPY,QQQ,DIA,IWM").split(",")
                                   if x.strip())
    # [R225] 使用者 10-18：科技七雄另開一組（同方向最多 group_max_same_dir 隻），同美股大盤組分開計
    etf_group_tech: tuple = tuple(x.strip().upper() for x in _env("ETF_GROUP_TECH", "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA")
                                  .split(",") if x.strip())
    group_max_same_dir: int = int(_env("GROUP_MAX_SAME_DIR", "2"))               # 美股大盤組同方向最多幾隻；0 = 唔限
    etf_total_daily_loss: float = float((_IS_REAL and os.getenv("REAL_ETF_TOTAL_DAILY_LOSS"))
                                        or _env("ETF_TOTAL_DAILY_LOSS", "200000"))  # 全部 ETF＋個股合計日蝕（HK$）；0 = 唔限；真倉用 REAL_ETF_TOTAL_DAILY_LOSS
    no_entry_before_close_min: int = int(_env("NO_ENTRY_BEFORE_CLOSE_MIN", "10"))
    flatten_before_night_close_min: int = int(_env("FLATTEN_BEFORE_NIGHT_CLOSE_MIN", "10"))
    flatten_before_night_close: bool = _bool("FLATTEN_BEFORE_NIGHT_CLOSE", "false")
    slippage_points: float = float(_env("SLIPPAGE_POINTS", str(SPEC.slippage)))
    stale_quote_sec: int = int(_env("STALE_QUOTE_SEC", "180"))
    max_consecutive_errors: int = int(_env("MAX_CONSECUTIVE_ERRORS", "10"))

    # --- 運行 ---
    risk_loop_sec: float = float(_env("RISK_LOOP_SEC", "5"))
    log_dir: Path = DATA_DIR / "logs"
    state_file: Path = DATA_DIR / "state.json"
    stop_file: Path = DATA_DIR / "STOP"      # 存在 = 即刻平倉並停止開新倉
    pause_file: Path = DATA_DIR / "PAUSE"    # 存在 = 唔開新倉，照樣管理止蝕
    heartbeat_file: Path = DATA_DIR / "heartbeat"  # 每個 tick 更新；watchdog 靠佢判斷程式仲生存


CFG = Config()
