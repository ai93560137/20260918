"""設定：全部由 .env 或環境變數讀入。硬性風控數字喺呢度，AI 無權改。"""
import os
from dataclasses import dataclass
from pathlib import Path

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


def _bool(name, default):
    return str(os.getenv(name, default)).lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    # --- Futu OpenD ---
    opend_host: str = _env("OPEND_HOST", "127.0.0.1")
    opend_port: int = int(_env("OPEND_PORT", "11111"))
    trd_env: str = _env("TRD_ENV", "SIMULATE")          # SIMULATE 或 REAL
    acc_id: int = int(_env("FUTU_ACC_ID", "0"))          # 0 = 自動揀第一個期貨戶口
    trade_password: str = _env("FUTU_TRADE_PASSWORD", "")  # 留空 = 已喺 OpenD 解鎖

    # --- 合約 ---
    # 使用者 2026-10-16：龍飛陣用大期 HSI（雲垂陣對沖用細期 MHI，分開合約免得淨額混埋）
    product: str = _env("PRODUCT", "HSI")                # 恒指大期
    point_value: float = float(_env("POINT_VALUE", "50"))  # HSI 每點 HK$50（MHI 係 10）

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
    fee_per_side_hkd: float = float(_env("FEE_PER_SIDE_HKD", "40"))     # 每張每邊佣金＋徵費估算，計日蝕用（寧高唔低）
    no_entry_before_close_min: int = int(_env("NO_ENTRY_BEFORE_CLOSE_MIN", "10"))
    flatten_before_night_close_min: int = int(_env("FLATTEN_BEFORE_NIGHT_CLOSE_MIN", "10"))
    flatten_before_night_close: bool = _bool("FLATTEN_BEFORE_NIGHT_CLOSE", "false")
    slippage_points: float = float(_env("SLIPPAGE_POINTS", "3"))
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
