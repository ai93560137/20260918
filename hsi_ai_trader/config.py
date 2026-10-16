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


def _bool(name, default):
    return str(os.getenv(name, default)).lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    # --- Futu OpenD ---
    opend_host: str = _env("OPEND_HOST", "127.0.0.1")
    opend_port: int = int(_env("OPEND_PORT", "11111"))
    # 使用者 2026-10-16：美期（MES／MNQ／MYM）只跑模擬盤（富途冇美期即時報價權限），TRD_ENV=REAL 都當 SIMULATE；
    # 轉真倉只適用 HSI。要開美期真倉要改呢度（經 PR），唔可以淨係改環境變數。
    trd_env: str = "SIMULATE" if SPEC.market == "US" else _env("TRD_ENV", "SIMULATE")
    acc_id: int = int(_env("FUTU_ACC_ID", "0"))          # 0 = 自動揀第一個期貨戶口
    trade_password: str = _env("FUTU_TRADE_PASSWORD", "")  # 留空 = 已喺 OpenD 解鎖

    # --- 合約 ---
    # 使用者 2026-10-16：龍飛陣用大期 HSI（雲垂陣對沖用細期 MHI，分開合約免得淨額混埋）；之後加 MES、MNQ、MYM
    product: str = _PRODUCT
    market: str = SPEC.market                            # HK／US
    currency: str = SPEC.currency
    tick: float = SPEC.tick
    roll_days: int = SPEC.roll_days
    # 每點價值一律換算做 HKD（日蝕上限、止蝕風險、盈虧都用 HKD 比較）：HSI 50；MES 5×7.8＝39
    point_value: float = float(_env("POINT_VALUE", str(SPEC.point_value * FX_TO_HKD[SPEC.currency])))

    # --- Claude ---
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")
    model: str = _env("CLAUDE_MODEL", "claude-sonnet-5-5")
    decision_interval_min: int = int(_env("DECISION_INTERVAL_MIN", "5"))
    effort: str = _env("CLAUDE_EFFORT", "")              # low/medium/high/xhigh/max；留空 = 模型預設（Sonnet 5.5 係 high）

    # --- 硬性風控（AI 無權超越）---
    max_qty: int = int(_env("MAX_QTY", "1"))
    daily_loss_limit: float = float(_env("DAILY_LOSS_LIMIT", "10000"))   # HK$
    # 使用者 2026-10-16 取消每張止蝕 20–150 點、每日 20 次、夜市收市前平倉三條限制；0／false = 唔限
    max_stop_points: float = float(_env("MAX_STOP_POINTS", "0"))         # 每張單最大止蝕點數，0 = 唔限
    min_stop_points: float = float(_env("MIN_STOP_POINTS", "0"))         # 0 = 唔限
    max_trades_per_day: int = int(_env("MAX_TRADES_PER_DAY", "0"))       # 0 = 唔限
    fee_per_side_hkd: float = float(_env("FEE_PER_SIDE_HKD", str(SPEC.fee_per_side_hkd)))     # 每張每邊佣金＋徵費估算，計日蝕用（寧高唔低）
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
