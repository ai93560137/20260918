"""設定：全部由 .env 或環境變數讀入。硬性風控數字喺呢度，AI 無權改。"""
import os
from dataclasses import dataclass
from pathlib import Path

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


def _bool(name, default):
    return str(os.getenv(name, default)).lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    # --- Futu OpenD ---
    opend_host: str = _env("OPEND_HOST", "127.0.0.1")
    opend_port: int = int(_env("OPEND_PORT", "11111"))
    # 唔再跟 TRD_ENV（HSI 都係）：真倉只喺真倉程式＋settings.env 嘅 LONGFEI_REAL_PRODUCTS 列明（改要經 PR＋「更新部機」）
    trd_env: str = "REAL" if (_INSTANCE_REAL and _PRODUCT in _REAL_LIST) else "SIMULATE"
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
    model: str = _env("CLAUDE_MODEL", "claude-sonnet-5-5")
    decision_interval_min: int = int(_env("DECISION_INTERVAL_MIN", "5"))
    effort: str = _env("CLAUDE_EFFORT", "")              # low/medium/high/xhigh/max；留空 = 模型預設（Sonnet 5.5 係 high）

    # --- 硬性風控（AI 無權超越）---
    max_qty: int = int(_env("MAX_QTY", "1"))
    # HK$；次序：DAILY_LOSS_LIMIT_<產品> → 期貨先跟 DAILY_LOSS_LIMIT → 產品預設（ETF HK$100,000，HSI HK$10,000）
    daily_loss_limit: float = float(os.getenv(f"DAILY_LOSS_LIMIT_{_PRODUCT}") or
                                    (SPEC.kind == "future" and os.getenv("DAILY_LOSS_LIMIT")) or SPEC.daily_loss_hkd)
    # 使用者 2026-10-16 取消每張止蝕 20–150 點、每日 20 次、夜市收市前平倉三條限制；0／false = 唔限
    max_stop_points: float = float(_env("MAX_STOP_POINTS", "0"))         # 每張單最大止蝕點數，0 = 唔限
    min_stop_points: float = float(_env("MIN_STOP_POINTS", "0"))         # 0 = 唔限
    max_trades_per_day: int = int(_env("MAX_TRADES_PER_DAY", "0"))       # 0 = 唔限
    fee_per_side_hkd: float = float(_env("FEE_PER_SIDE_HKD", str(SPEC.fee_per_side_hkd)))     # 每張每邊佣金＋徵費估算，計日蝕用（寧高唔低）
    # [R209] 真倉期貨開倉前：開倉後緩衝（淨值 − 維持保證金 − 每張初始保證金）要 ≥ Ⓑ 線（夜盤 ×1.5）＋ 日蝕上限
    # （總指揮 10-17 建議；Ⓑ 線跟 RISK_LADDER，改咗要同步）
    fut_ladder_b_day: float = float(_env("FUT_LADDER_B_DAY", "37500"))
    fut_ladder_night_mult: float = float(_env("FUT_LADDER_NIGHT_MULT", "1.5"))
    # [R216] 使用者 10-17：ETF 組合限制（只限開新倉，唔會平已有嘅倉）
    etf_group_us_eq: tuple = tuple(x.strip().upper() for x in _env("ETF_GROUP_US_EQ", "SPY,QQQ,DIA,IWM").split(",")
                                   if x.strip())
    group_max_same_dir: int = int(_env("GROUP_MAX_SAME_DIR", "2"))               # 美股大盤組同方向最多幾隻；0 = 唔限
    etf_total_daily_loss: float = float(_env("ETF_TOTAL_DAILY_LOSS", "200000"))  # 全部 ETF 合計日蝕（HK$）；0 = 唔限
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
