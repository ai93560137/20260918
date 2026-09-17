# =============================================================================
# 智能諸葛亮 AI 量化交易系統 — GCP Cloud Function (v12 rewrite)
# -----------------------------------------------------------------------------
# Rewrite of v11 that resolves logic-review findings R1–R67 (security still out
# of scope, as requested). Tags like [R4] mark where a finding is addressed.
#
# BEHAVIOUR CHANGES — read before deploying
#   * No dry-run mode: every approved signal is sent LIVE to the real account.
#   * Gate + trend state is ONE JSON document (regime, direction, armed,
#     hard lock, news lock) updated with GCS generation checks. Entries are
#     only taken in the confirmed trend direction.                   [R4 R9 R30 R35]
#   * TARGET_HIT and manual LOCK are HARD locks that the state machine cannot
#     reopen. The dashboard "OPEN" button became "release hard lock / resume
#     auto"; the gate then opens on the next Setup→Trigger cycle.       [R10 R29]
#   * Position cap is risk-based: equity × RISK_PCT ÷ (SL distance × 100),
#     also capped by margin and HARD_MAX_LOTS.                              [R11]
#   * Entry rules are deterministic Python. The LLM is an optional reviewer
#     with ONE fail policy (AI_FAIL_OPEN, default = reject).        [R2 R5 R13 R14]
#   * Pyramid base price and pending SFT entries are written only after the
#     broker accepts the order.                                         [R3 R24f]
#   * News lock = ±30 min around High-impact USD events, from the FF JSON
#     feed (explicit UTC offsets). Unknown calendar blocks new entries.
#                                                                [R13e R16 R17]
#   * New GCS objects (legacy files are left untouched):
#       zhuge_gate_state.json, pyramid_state.json, gcp_decision_log.json,
#       ai_training/pending_signals_v2.json, cache/ff_calendar_thisweek.json
# =============================================================================
import hashlib
import html
import json
import math
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import functions_framework
import requests
from flask import jsonify, redirect
from google import genai
from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage
from google.genai import types


# =============================================================================
# ⚙️ Configuration (all overridable with environment variables)
# =============================================================================
def _env_str(name, default):
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Auth (unchanged; security out of scope) ---------------------------------
GCP_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "123456")

# --- Execution ----------------------------------------------------------------
ORDER_SIZE = _env_float("ORDER_SIZE", 0.01)
BROKER_API_URL = "https://webhooktrade.com/signals/v1/webhook_receptions.php?t=e66cdac4abb48f1a"
BROKER_TIMEOUT_SEC = _env_int("BROKER_TIMEOUT_SEC", 8)            # keep total request < EA WebRequest timeout
ORDER_SYMBOL = _env_str("ORDER_SYMBOL", "XAUUSD")                    # symbol sent to webhooktrade
ORDER_SETTLE_SEC = _env_int("ORDER_SETTLE_SEC", 180)                  # [R12c R25]
LOCKED_HTTP_STATUS = _env_int("LOCKED_HTTP_STATUS", 403)              # [R63] 403 kept for EA compatibility

ORDER_TEMPLATE = {
    "username": "Webhook8",
    "api_key": os.environ.get("WEBHOOK_API_KEY", "9dff998f1ed0a6cb"),
    "broker": "metatrader",
    "account_type": "real",
    "symbol": ORDER_SYMBOL,
    "action": "PENDING",
    "size": f"{ORDER_SIZE:.2f}",
    "strategy": "GCP",
    "comment": "1M BOS GCP AI",
}

# Exit parameters are passed to the bridge as-is. Units/semantics depend on
# webhooktrade — verify them against its documentation before going live. [R33]
TS_ACTIVATION_PRICE = _env_str("TS_ACTIVATION_PRICE", "2")
TS_DISTANCE_PRICE = _env_str("TS_DISTANCE_PRICE", "4")
BREAKEVEN_DISTANCE_PRICE = _env_str("BREAKEVEN_DISTANCE_PRICE", "3")
BREAKEVEN_PROFIT = _env_str("BREAKEVEN_PROFIT", "30")

# --- Risk -----------------------------------------------------------------------
CONTRACT_SIZE = 100.0                                                 # XAUUSD: 1 lot = 100 oz
ACCOUNT_CURRENCY_DEFAULT = _env_str("ACCOUNT_CURRENCY", "HKD")
FX_TO_USD = {"USD": 1.0, "HKD": 1.0 / 7.8}                            # [R11c]
ACCOUNT_TO_USD_RATE = _env_float("ACCOUNT_TO_USD_RATE", 0.0)           # used for any other currency
RISK_PCT = _env_float("RISK_PCT", 0.02)                               # [R11] risk of full pyramid at SL
BROKER_LEVERAGE = _env_float("BROKER_LEVERAGE", 500.0)                # [R11d] set your REAL leverage
MAX_MARGIN_PCT = _env_float("MAX_MARGIN_PCT", 0.20)
HARD_MAX_LOTS = _env_float("HARD_MAX_LOTS", 1.00)
MIN_SL_DISTANCE = _env_float("MIN_SL_DISTANCE", 6.0)
SL_ATR_MULT = _env_float("SL_ATR_MULT", 1.5)
TARGET_RRR = _env_float("TARGET_RRR", 2.0)                            # [R15] fixed, no feedback loop
ADD_SPACING_ATR = _env_float("ADD_SPACING_ATR", 0.5)
REENTRY_COOLDOWN_SEC = _env_int("REENTRY_COOLDOWN_SEC", 300)          # [R25b]
FIRST_ENTRY_MODE = _env_str("FIRST_ENTRY_MODE", "BREAKOUT").upper()   # BREAKOUT | MID   [R5]
M15_CLOSE_POSITION_MIN = _env_float("M15_CLOSE_POSITION_MIN", 0.7)    # [R5c]
RSI_BUY_MAX = _env_float("RSI_BUY_MAX", 85.0)
RSI_SELL_MIN = _env_float("RSI_SELL_MIN", 15.0)
BREAKEVEN_EPS = _env_float("BREAKEVEN_EPS", 1.0)                      # [R24c] |profit| <= this = break-even
STATS_WINDOW = _env_int("STATS_WINDOW", 100)
BROKER_UTC_OFFSET_HOURS = _env_float("BROKER_UTC_OFFSET_HOURS", 0.0)  # [R42] MT5 server time - UTC

# --- M1 regime radar -----------------------------------------------------------
MIN_M1_BARS = _env_int("MIN_M1_BARS", 65)                             # [R47] 60-min window + margin
M1_HISTORY_MAX = 200
M1_GAP_RESET_SEC = _env_int("M1_GAP_RESET_SEC", 15 * 60)              # [R21]
NOISE_K = _env_float("NOISE_K", 1.0)                                  # [R31] threshold = K·σ·√minutes

# --- News -----------------------------------------------------------------------
NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"  # [R17] ISO dates with UTC offset
NEWS_LOCK_BEFORE_MIN = _env_int("NEWS_LOCK_BEFORE_MIN", 30)           # [R16]
NEWS_LOCK_AFTER_MIN = _env_int("NEWS_LOCK_AFTER_MIN", 30)
NEWS_LOCK_IMPACTS = {s.strip() for s in _env_str("NEWS_LOCK_IMPACTS", "High").split(",") if s.strip()}
NEWS_CACHE_TTL_SEC = 900
NEWS_FAIL_BACKOFF_SEC = 300                                           # [R53]
NEWS_MAX_STALE_SEC = 12 * 3600
NEWS_FAIL_CLOSED = _env_bool("NEWS_FAIL_CLOSED", True)                # [R13e]

# --- AI reviewer ---------------------------------------------------------------
AI_REVIEW_ENABLED = _env_bool("AI_REVIEW_ENABLED", True)
AI_FAIL_OPEN = _env_bool("AI_FAIL_OPEN", False)                       # [R2 R13f R13g] one policy
AI_MODEL = _env_str("AI_MODEL", "gemini-2.5-flash")
AI_LOCATION = _env_str("AI_LOCATION", "us-central1")
AI_THINKING_BUDGET = _env_int("AI_THINKING_BUDGET", 0)                # [R14] 0 = no thinking (Flash only)

# --- Storage ---------------------------------------------------------------------
BUCKET_NAME = "zhuge-risk-manager-bucket"
ACCOUNT_FILE = "mt5_account_snapshot.txt"
GATE_STATE_FILE = "zhuge_gate_state.json"
PYRAMID_STATE_FILE = "pyramid_state.json"
DECISION_LOG_FILE = "gcp_decision_log.json"
M1_VERDICT_LOG_FILE = "m1_ai_verdict.txt"
M1_HISTORY_FILE = "m1_history/XAUUSD_M1.json"
M15_HISTORY_FILE = "m15_history/XAUUSD_M15.json"
TRADE_HISTORY_FILE = "risk_management/trade_history.jsonl"
SFT_DATASET_FILE = "ai_training/sft_dataset.jsonl"
TRADING_RULES_FILE = "ai_training/trading_rules.txt"
PENDING_SIGNALS_FILE = "ai_training/pending_signals_v2.json"
WEBHOOK_LOG_FILE = "logs/latest_webhook_payload.json"
NEWS_CACHE_FILE = "cache/ff_calendar_thisweek.json"

DECISION_LOG_MAX = 50
SFT_MAX_LINES = 2000                                                  # [R6c]
PENDING_TTL_SEC = 7 * 86400                                           # [R24]
PENDING_MAX = 300

UTC = timezone.utc
NY_TZ = ZoneInfo("America/New_York")

REGIME_RANGE = "RANGE"
REGIME_SETUP = "SETUP"
REGIME_TREND = "TREND"
REGIME_PAUSE = "PAUSE"      # verdict only
REGIME_NODATA = "NODATA"    # verdict only

DIR_WORD = {"UP": "多頭", "DOWN": "空頭"}
CANDLE_WORD = {"BULL": "收陽", "BEAR": "收陰", "DOJI": "收十字"}


# =============================================================================
# 🧰 Utilities
# =============================================================================
def now_ts():
    return time.time()


def fmt_utc(ts=None, fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.fromtimestamp(now_ts() if ts is None else ts, UTC).strftime(fmt)


def fmt_ny(ts):
    return datetime.fromtimestamp(ts, NY_TZ).strftime("%m-%d %H:%M 紐約")


def to_float(value, default=None):
    """Safe float parse: None/''/'N/A'/NaN/bool -> default.  [R23]"""
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def esc(value):
    return html.escape("" if value is None else str(value))


def fmt_num(value, spec="{:,.2f}"):
    number = to_float(value)
    return "—" if number is None else spec.format(number)


def countdown_text(seconds):
    seconds = int(abs(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} 天 {hours} 小時"
    if hours:
        return f"{hours} 小時 {minutes} 分鐘"
    return f"{minutes} 分鐘"


def normalize_symbol(symbol):
    """'XAUUSD.m', 'XAUUSDm', 'GOLD#' -> 'XAUUSD'.  [R24d]"""
    text = str(symbol or "").strip().upper()
    for sep in ".#-_ ":
        text = text.split(sep)[0]
    if text.startswith("XAUUSD") or text.startswith("GOLD"):
        return "XAUUSD"
    return text


def next_ny_rollover_ts(now=None):
    """Next 17:00 New York (gold daily rollover)."""
    ny_now = datetime.fromtimestamp(now_ts() if now is None else now, NY_TZ)
    target = ny_now.replace(hour=17, minute=0, second=0, microsecond=0)
    if ny_now >= target:
        target += timedelta(days=1)
    return target.timestamp()


def _startup_warnings():
    print(f"⚙️ [啟動] 🔴 實盤下單模式 (account_type={ORDER_TEMPLATE['account_type']}) | "
          f"RISK_PCT={RISK_PCT} | LEVERAGE={BROKER_LEVERAGE} | FIRST_ENTRY_MODE={FIRST_ENTRY_MODE}", flush=True)
    activation, distance = to_float(TS_ACTIVATION_PRICE), to_float(TS_DISTANCE_PRICE)
    if activation is not None and distance is not None and distance > activation:
        print(f"⚠️ [出場參數] TS_DISTANCE ({distance}) > TS_ACTIVATION ({activation})：啟動移動止損時止損可能仍在進場價之下，"
              f"請確認 webhooktrade 語義。[R33]", flush=True)
    if FIRST_ENTRY_MODE not in ("BREAKOUT", "MID"):
        print(f"⚠️ [設定] FIRST_ENTRY_MODE={FIRST_ENTRY_MODE} 無效，將視為 BREAKOUT。", flush=True)


_startup_warnings()


# =============================================================================
# 💾 GCS layer — every read-modify-write is generation-checked  [R35 R36 R50]
# =============================================================================
class StorageError(Exception):
    pass


_storage_client = None
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"


def _bucket():
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client.bucket(BUCKET_NAME)


def gcs_read_text(name):
    """Return the object's text, None if it does not exist. Raises StorageError."""
    try:
        blob = _bucket().get_blob(name)
        if blob is None:
            return None
        return blob.download_as_bytes().decode("utf-8")
    except NotFound:
        return None
    except Exception as exc:
        raise StorageError(f"read {name}: {exc}") from exc


def gcs_read_json(name, default):
    text = gcs_read_text(name)
    if text is None or not text.strip():
        return default
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StorageError(f"corrupt JSON in {name}: {exc}") from exc


def gcs_write_text(name, text):
    try:
        _bucket().blob(name).upload_from_string(text, content_type=TEXT_CONTENT_TYPE)
    except Exception as exc:
        raise StorageError(f"write {name}: {exc}") from exc


def jsonl_loads(text):
    rows, bad = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            bad += 1
    if bad:
        print(f"⚠️ [JSONL] 略過 {bad} 行損毀資料", flush=True)
    return rows


def jsonl_dumps(rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _backoff(attempt):
    time.sleep(random.uniform(0.05, 0.2) * (1.5 ** attempt))


def _load_for_update(name, loads, default_factory, reset_on_corrupt):
    blob = _bucket().get_blob(name)
    if blob is None:
        return 0, default_factory()
    generation = blob.generation
    raw = blob.download_as_bytes(if_generation_match=generation).decode("utf-8")
    if not raw.strip():
        return generation, default_factory()
    try:
        return generation, loads(raw)
    except ValueError as exc:
        if not reset_on_corrupt:
            raise StorageError(f"corrupt data in {name}: {exc}") from exc
        print(f"⚠️ [GCS] {name} 內容損毀，已重設為預設值: {exc}", flush=True)   # [R40]
        return generation, default_factory()


def gcs_update(name, mutate, *, loads=json.loads, dumps=None, default_factory=dict,
               reset_on_corrupt=False, attempts=10):
    """Atomic read-modify-write.

    mutate(data) -> (new_data, result). Return new_data=None to skip the write.
    mutate may run several times (on conflicts), so it must not have side effects.
    Raises StorageError if the object cannot be read or written.
    """
    dumps = dumps or (lambda data: json.dumps(data, ensure_ascii=False))
    for attempt in range(attempts):
        try:
            generation, data = _load_for_update(name, loads, default_factory, reset_on_corrupt)
        except (PreconditionFailed, NotFound):
            _backoff(attempt)
            continue
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"read {name}: {exc}") from exc

        new_data, result = mutate(data)
        if new_data is None:
            return result
        try:
            _bucket().blob(name).upload_from_string(
                dumps(new_data), if_generation_match=generation, content_type=TEXT_CONTENT_TYPE)
            return result
        except PreconditionFailed:
            _backoff(attempt)
        except Exception as exc:
            raise StorageError(f"write {name}: {exc}") from exc
    raise StorageError(f"update {name}: gave up after {attempts} concurrent-write retries")


# =============================================================================
# 📝 Decision log (keyed de-duplication)  [R37 R38 R59 R64]
# =============================================================================
def log_decision(message, key=None):
    """Consecutive entries with the same key replace each other, so per-minute
    'waiting' messages cannot push real decisions out of the window."""
    print(message, flush=True)
    entry = {"t": fmt_utc(fmt="%m-%d %H:%M:%S"), "k": key or "", "m": message}

    def mutate(logs):
        logs = logs if isinstance(logs, list) else []
        if logs and logs[0].get("m") == message:
            return None, None
        if key and logs and logs[0].get("k") == key:
            logs[0] = entry
        else:
            logs.insert(0, entry)
        return logs[:DECISION_LOG_MAX], None

    try:
        gcs_update(DECISION_LOG_FILE, mutate, default_factory=list, reset_on_corrupt=True)
    except StorageError as exc:
        print(f"⚠️ [決策日誌寫入失敗] {exc}", flush=True)


def read_decision_logs():
    try:
        logs = gcs_read_json(DECISION_LOG_FILE, [])
        return logs if isinstance(logs, list) else []
    except StorageError as exc:
        print(f"⚠️ [決策日誌讀取失敗] {exc}", flush=True)
        return []


# =============================================================================
# 💰 Account snapshot
# =============================================================================
def save_account_snapshot(payload, m15_ohlc, m15_levels):
    # Missing numbers are stored as None (shown as "—"), never as fake defaults.  [R61]
    snapshot = {
        "status": str(payload.get("status") or "").strip().upper(),
        "symbol": str(payload.get("symbol") or "NONE"),
        "currency": str(payload.get("currency") or ACCOUNT_CURRENCY_DEFAULT),
        "net_lots": to_float(payload.get("net_lots")),
        "buy_lots": to_float(payload.get("buy_lots")),
        "sell_lots": to_float(payload.get("sell_lots")),
        "equity": to_float(payload.get("equity")),
        "balance": to_float(payload.get("balance")),
        "floating": to_float(payload.get("floating")),
        "daily_pnl": to_float(payload.get("daily_pnl")),
        "m15_ohlc": m15_ohlc or {},
        "m15_levels": m15_levels or {},
        "received_utc": fmt_utc(),
    }
    try:
        gcs_write_text(ACCOUNT_FILE, json.dumps(snapshot, ensure_ascii=False))
    except StorageError as exc:
        print(f"⚠️ [戶口快照寫入失敗] {exc}", flush=True)


def read_account_snapshot():
    try:
        data = gcs_read_json(ACCOUNT_FILE, {})
        return data if isinstance(data, dict) else {}
    except StorageError as exc:
        print(f"⚠️ [戶口快照讀取失敗] {exc}", flush=True)
        return {}


# =============================================================================
# 🚦 Gate + trend state (single machine-readable document)  [R4 R8 R9 R10 R30 R35]
# =============================================================================
def default_gate_state():
    return {
        "regime": REGIME_RANGE,   # RANGE | SETUP | TREND
        "dir": None,              # UP | DOWN | None
        "armed": False,           # True only after SETUP -> same-direction TREND
        "hard_lock": None,        # {"reason", "since_utc", "until_ts" (None = until manual release)}
        "news_lock": False,
        "last_m1_bar_time": 0,    # idempotency for M1 packets  [R25]
        "last_reason": "",
        "updated_utc": None,
    }


def _merge_gate_state(raw):
    state = default_gate_state()
    if isinstance(raw, dict):
        state.update({key: raw[key] for key in state if key in raw})
    return state


def hard_lock_active(state, now=None):
    lock = state.get("hard_lock")
    if not isinstance(lock, dict):
        return False
    until = to_float(lock.get("until_ts"))
    return until is None or (now_ts() if now is None else now) < until


def gate_status(state, now=None):
    if hard_lock_active(state, now) or state.get("news_lock"):
        return "LOCK"
    if state.get("armed") and state.get("regime") == REGIME_TREND and state.get("dir") in ("UP", "DOWN"):
        return "OPEN"
    return "LOCK"


def read_gate_state():
    """Fails safe: an unreadable state is reported as LOCK.  [R13a]"""
    try:
        return _merge_gate_state(gcs_read_json(GATE_STATE_FILE, None))
    except StorageError as exc:
        print(f"⚠️ [電閘狀態讀取失敗 → 視為 LOCK] {exc}", flush=True)
        state = default_gate_state()
        state["last_reason"] = "電閘狀態讀取失敗"
        return state


def update_gate_state(fn, reset_on_corrupt=False):
    """fn(state) mutates state in place and returns (changed, result)."""
    def mutate(raw):
        state = _merge_gate_state(raw)
        changed, result = fn(state)
        if not changed:
            return None, result
        state["updated_utc"] = fmt_utc()
        return state, result

    return gcs_update(GATE_STATE_FILE, mutate, default_factory=dict, reset_on_corrupt=reset_on_corrupt)


def next_trend_state(state, verdict, skip_setup=False):
    """Pure transition function. Returns (regime, dir, armed, reason).

    RANGE/NODATA            -> RANGE, disarm
    PAUSE(d)                -> keep SETUP(d)/TREND(d) as-is, otherwise RANGE          [R8]
    SETUP(d)                -> pullback inside an armed TREND(d) keeps it armed,
                               otherwise SETUP(d), disarmed                             [R8b]
    TREND(d)                -> after SETUP(d): TRIGGER, armed
                               after TREND(d): keep armed flag
                               otherwise (no setup / opposite direction): TREND(d), disarmed [R30]
    """
    regime, cur_dir, armed = state.get("regime"), state.get("dir"), bool(state.get("armed"))
    v_regime, v_dir = verdict.get("regime"), verdict.get("dir")
    word = DIR_WORD.get(v_dir, "")

    if v_regime in (REGIME_RANGE, REGIME_NODATA):
        return REGIME_RANGE, None, False, "橫行或數據不足，解除武裝"
    if v_regime == REGIME_PAUSE:
        if regime == REGIME_TREND and cur_dir == v_dir:
            return regime, cur_dir, armed, f"{word}趨勢中 M1 短暫停頓，維持原狀態"
        if regime == REGIME_SETUP and cur_dir == v_dir:
            return regime, cur_dir, False, f"{word} Setup 中 M1 停頓，繼續等待 Trigger"
        return REGIME_RANGE, None, False, "M1 停頓但缺少同向趨勢背景，視為橫行"
    if v_regime == REGIME_SETUP:
        if regime == REGIME_TREND and cur_dir == v_dir and armed:
            return REGIME_TREND, cur_dir, True, f"{word}趨勢中的健康回調，維持開閘"
        return REGIME_SETUP, v_dir, False, f"{word} Setup 醞釀中，等待同向 Trigger"
    if v_regime == REGIME_TREND:
        if regime == REGIME_SETUP and cur_dir == v_dir:
            return REGIME_TREND, v_dir, True, f"Trigger 觸發：{word} Setup → 同向趨勢確認"
        if regime == REGIME_TREND and cur_dir == v_dir:
            if skip_setup and not armed:
                return REGIME_TREND, v_dir, True, f"{word}趨勢延續，Setup 確認關卡已略過 → 開閘"
            return REGIME_TREND, v_dir, armed, f"{word}趨勢延續（{'開閘中' if armed else '未經 Setup 確認，維持鎖定'}）"
        if skip_setup:
            return REGIME_TREND, v_dir, True, f"{word}趨勢出現，Setup 確認關卡已略過 → 直接開閘"
        return REGIME_TREND, v_dir, False, f"缺乏同向 Setup 的突發{word}趨勢，拒絕開閘"
    return REGIME_RANGE, None, False, f"未知判定 {v_regime}，解除武裝"


def _state_label(state_tuple):
    regime, direction, armed = state_tuple
    name = {REGIME_RANGE: "橫行", REGIME_SETUP: "Setup", REGIME_TREND: "趨勢"}.get(regime, str(regime))
    word = DIR_WORD.get(direction, "")
    return f"{word}{name}" + ("（已武裝）" if armed else "")


def apply_verdict_to_gate(verdict, news_locked, skip_setup=False):
    def fn(state):
        before = gate_status(state)
        prev = (state.get("regime"), state.get("dir"), bool(state.get("armed")))
        regime, direction, armed, reason = next_trend_state(state, verdict, skip_setup)
        if news_locked and armed:
            # Disarm during news: a fresh Setup→Trigger is required after the event.  [R49]
            armed = False
            reason += "｜新聞風控期間解除武裝，事件後需重新 Setup→Trigger"
        state.update(regime=regime, dir=direction, armed=armed, news_lock=bool(news_locked), last_reason=reason)
        return True, {"before": before, "after": gate_status(state), "reason": reason,
                      "prev": prev, "now": (regime, direction, armed)}

    return update_gate_state(fn)


def claim_m1_bar(bar_time):
    """True only for the first packet carrying this bar time.  [R25]"""
    def fn(state):
        if bar_time <= int(to_float(state.get("last_m1_bar_time"), 0)):
            return False, False
        state["last_m1_bar_time"] = bar_time
        return True, True

    try:
        return update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [M1 去重寫入失敗，本根略過] {exc}", flush=True)
        return False


def set_hard_lock(reason, until_ts=None):
    """Hard lock the gate. An existing stronger/longer lock is kept.  [R10]"""
    def fn(state):
        current = state.get("hard_lock")
        if hard_lock_active(state) and isinstance(current, dict):
            current_until = to_float(current.get("until_ts"))
            if current_until is None or (until_ts is not None and current_until >= until_ts):
                was_armed = state.get("armed")
                state["armed"] = False
                return bool(was_armed), None
        state["hard_lock"] = {"reason": reason, "since_utc": fmt_utc(), "until_ts": until_ts}
        state["armed"] = False
        state["last_reason"] = f"硬鎖：{reason}"
        return True, None

    update_gate_state(fn, reset_on_corrupt=True)


def clear_hard_lock():
    def fn(state):
        state["hard_lock"] = None
        state["last_reason"] = "管理員解除硬鎖，恢復自動（需重新 Setup→Trigger）"
        return True, None

    update_gate_state(fn, reset_on_corrupt=True)


def disarm_gate(reason):
    def fn(state):
        if not state.get("armed"):
            return False, None
        state["armed"] = False
        state["last_reason"] = reason
        return True, None

    try:
        update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [解除武裝寫入失敗] {exc}", flush=True)


# =============================================================================
# 📌 Pyramid state (base price, last order, last close)
# =============================================================================
def read_pyramid_state():
    data = gcs_read_json(PYRAMID_STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def update_pyramid_state(**fields):
    def mutate(data):
        data = data if isinstance(data, dict) else {}
        data.update(fields)
        data["updated_utc"] = fmt_utc()
        return data, data

    return gcs_update(PYRAMID_STATE_FILE, mutate, default_factory=dict, reset_on_corrupt=True)


# =============================================================================
# 🧩 M1 history, indicators and regime verdict
# =============================================================================
def wilder_rsi_last(closes, period=14):
    """Wilder RSI of the last close. Seed uses changes 1..period, smoothing starts
    at period+1 (fixes the double-counted change).  [R22]"""
    if len(closes) <= period:
        return None

    def rsi(avg_gain, avg_loss):
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    return round(rsi(avg_gain, avg_loss), 2)


def _verdict(regime, direction, text):
    return {"regime": regime, "dir": direction, "text": text}


class GoldIndicatorSession:
    @staticmethod
    def is_gold_market_open(now=None):
        ny = datetime.fromtimestamp(now_ts() if now is None else now, NY_TZ)
        weekday, hour = ny.weekday(), ny.hour
        if weekday == 5:
            return False
        if weekday == 4 and hour >= 17:
            return False
        if weekday == 6 and hour < 18:
            return False
        if weekday in (0, 1, 2, 3) and hour == 17:
            return False
        return True  # holidays not handled  [R44]

    @staticmethod
    def parse_bar(ohlc):
        """Validated bar or None. Assumes the EA sends the bar that just CLOSED
        when is_new_bar is true.  [R46]"""
        if not isinstance(ohlc, dict):
            return None
        bar_time = to_float(ohlc.get("time"))
        values = {key: to_float(ohlc.get(key)) for key in ("open", "high", "low", "close")}
        if bar_time is None or bar_time <= 0 or any(v is None or v <= 0 for v in values.values()):
            return None
        if values["high"] < max(values["open"], values["close"]) - 1e-6 or \
                values["low"] > min(values["open"], values["close"]) + 1e-6:
            return None
        if values["open"] == values["high"] == values["low"] == values["close"]:
            print("⚠️ [M1] 收到 O=H=L=C 的 K 線：請確認 EA 傳的是『剛收盤』而非『剛開盤』的 K 線。[R46]", flush=True)
        return {"time": int(bar_time), **values}

    @staticmethod
    def read_bars():
        try:
            bars = gcs_read_json(M1_HISTORY_FILE, [])
            return bars if isinstance(bars, list) else []
        except StorageError as exc:
            print(f"⚠️ [M1 歷史讀取失敗] {exc}", flush=True)
            return []

    @staticmethod
    def ingest_bar(bar):
        """Append in time order; drop out-of-order bars; restart history after a gap.  [R21]"""
        def mutate(history):
            history = history if isinstance(history, list) else []
            if history:
                last_time = history[-1]["time"]
                if bar["time"] < last_time:
                    print(f"⚠️ [M1] 忽略亂序 K 線 {bar['time']} < {last_time}", flush=True)
                    return None, history
                if bar["time"] == last_time:
                    if history[-1] == bar:
                        return None, history
                    history[-1] = bar
                else:
                    if bar["time"] - last_time > M1_GAP_RESET_SEC:
                        print(f"ℹ️ [M1] 偵測到 {int((bar['time'] - last_time) / 60)} 分鐘缺口，重新累積歷史。", flush=True)
                        history = []
                    history.append(bar)
            else:
                history.append(bar)
            history = history[-M1_HISTORY_MAX:]
            return history, history

        return gcs_update(M1_HISTORY_FILE, mutate, default_factory=list, reset_on_corrupt=True)

    @staticmethod
    def _move_over(bars, minutes):
        """(price move, actual minutes) between the last bar and the bar ~minutes earlier,
        using timestamps instead of bar counts.  [R21]"""
        last = bars[-1]
        target = last["time"] - minutes * 60
        tolerance = max(60, minutes * 6)
        for bar in reversed(bars[:-1]):
            if bar["time"] <= target:
                if target - bar["time"] > tolerance:
                    return None
                return last["close"] - bar["close"], (last["time"] - bar["time"]) / 60.0
        return None

    @staticmethod
    def compute_verdict(bars):
        """Machine-readable regime from M1 closes over 60/24/4-minute windows.
        Thresholds scale with measured per-minute volatility × √minutes.  [R8 R9 R31]"""
        n = len(bars)
        if n < MIN_M1_BARS:
            return _verdict(REGIME_NODATA, None, f"【數據累積中⏳】 連續 M1 K 線 {n}/{MIN_M1_BARS} 根，暫不判定。")

        diffs = [bars[i]["close"] - bars[i - 1]["close"]
                 for i in range(n - 60, n) if bars[i]["time"] - bars[i - 1]["time"] == 60]
        if len(diffs) < 30:
            return _verdict(REGIME_NODATA, None, "【數據不足⏳】 最近 60 分鐘缺漏 K 線過多，暫不判定。")
        mean = sum(diffs) / len(diffs)
        sigma = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
        if sigma <= 0:
            return _verdict(REGIME_RANGE, None, "【明確橫行💤】 價格近乎無波動。")

        signs, parts = {}, []
        for label, minutes in (("M15", 60), ("M5", 24), ("M1", 4)):
            found = GoldIndicatorSession._move_over(bars, minutes)
            if found is None:
                return _verdict(REGIME_NODATA, None, f"【數據不足⏳】 {label} 窗口（{minutes} 分鐘）缺少對應 K 線。")
            move, actual = found
            threshold = NOISE_K * sigma * math.sqrt(actual)
            signs[label] = 1 if move > threshold else (-1 if move < -threshold else 0)
            parts.append(f"{label}:{move / actual:+.3f}/分 門檻±{threshold / actual:.3f}")
        detail = ", ".join(parts)

        big = signs["M15"]
        if big != 0 and signs["M5"] == big:
            direction = "UP" if big > 0 else "DOWN"
            word = DIR_WORD[direction]
            if signs["M1"] == big:
                return _verdict(REGIME_TREND, direction, f"【單邊趨勢中✅】 三級共振{'向上' if big > 0 else '向下'} ({detail})")
            if signs["M1"] == -big:
                return _verdict(REGIME_SETUP, direction,
                                f"【突破整理邊緣🔆】 大級別{word}，M1 {'回調' if big > 0 else '反彈'} ({detail})")
            return _verdict(REGIME_PAUSE, direction, f"【趨勢停頓⏸️】 大級別{word}，M1 暫時持平 ({detail})")
        return _verdict(REGIME_RANGE, None, f"【明確橫行💤】 M15/M5 未同向越過雜訊門檻 ({detail})")

    @staticmethod
    def _append_verdict_log(text):
        line = f"[{fmt_utc()} UTC] {text}"

        def mutate(lines):
            lines = [row for row in (lines or []) if row.strip()]
            lines.insert(0, line)
            return lines[:50], None

        try:
            gcs_update(M1_VERDICT_LOG_FILE, mutate, loads=lambda s: s.splitlines(),
                       dumps=lambda rows: "\n".join(rows), default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [M1 判定日誌寫入失敗] {exc}", flush=True)

    def process_m1_bar(self, bar, news_locked, skip_setup=False):
        history = self.ingest_bar(bar)
        verdict = self.compute_verdict(history)
        rsi = wilder_rsi_last([b["close"] for b in history])
        print(f"📊 [M1 盤勢監控] {verdict['text']}", flush=True)
        self._append_verdict_log(verdict["text"])

        result = apply_verdict_to_gate(verdict, news_locked, skip_setup)
        before, after, reason = result["before"], result["after"], result["reason"]
        print(f"🔍 [狀態機] {before} → {after} | {reason}", flush=True)
        if before != after:
            log_decision(f"{'🟢' if after == 'OPEN' else '🔒'} [電閘 {before}→{after}] {reason}", key="gate")
        elif result["prev"] != result["now"]:
            log_decision(f"🔄 [狀態轉換] {_state_label(result['prev'])} → {_state_label(result['now'])}：{reason}",
                         key="regime")
        else:
            short = verdict["text"].split(" (")[0]
            log_decision(f"📡 [盤勢監控] {short}｜電閘 {after}：{reason}", key="monitor")
        return {"verdict": verdict, "rsi": rsi, "bars": len(history)}


gold_indicator_session = GoldIndicatorSession()


# =============================================================================
# 📊 M15 Bollinger levels — writer and pure reader are separate  [R20 R26 R50]
# =============================================================================
class MTFDynamicLevelsSession:
    bb_period = 20
    bb_std_dev = 2.0
    history_max = 30

    @staticmethod
    def parse_bar(m15_ohlc):
        if not isinstance(m15_ohlc, dict):
            return None
        bar_time = to_float(m15_ohlc.get("time"))
        values = {key: to_float(m15_ohlc.get(key)) for key in ("open", "high", "low", "close")}
        if bar_time is None or bar_time <= 0 or any(v is None or v <= 0 for v in values.values()):
            return None
        if values["high"] < values["low"]:
            return None
        return {"time": int(bar_time), **values}

    def ingest(self, m15_ohlc):
        """POST path only: store the bar (if valid and changed) and return levels."""
        bar = self.parse_bar(m15_ohlc)
        if bar is None:
            print("⚠️ [M15] 收到不完整的 M15 K 線，拒絕寫入歷史。[R26]", flush=True)
            return self.read_levels()

        def mutate(history):
            history = history if isinstance(history, list) else []
            if history and bar["time"] < history[-1]["time"]:
                return None, history
            if history and bar["time"] == history[-1]["time"]:
                if history[-1] == bar:
                    return None, history
                history[-1] = bar
            else:
                history.append(bar)
            history = history[-self.history_max:]
            return history, history

        try:
            history = gcs_update(M15_HISTORY_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [M15 歷史寫入失敗] {exc}", flush=True)
            return {"status": "unavailable"}
        return self.compute_levels(history)

    def read_levels(self):
        """Read-only (safe for GET pages)."""
        try:
            history = gcs_read_json(M15_HISTORY_FILE, [])
        except StorageError as exc:
            print(f"⚠️ [M15 歷史讀取失敗] {exc}", flush=True)
            return {"status": "unavailable"}
        return self.compute_levels(history if isinstance(history, list) else [])

    def compute_levels(self, history):
        valid = [b for b in history if to_float(b.get("close"), 0.0) > 0]
        if len(valid) < self.bb_period:
            return {"status": "insufficient_data", "count": len(valid)}
        # The window includes the forming bar, like MT5's current-bar BB.  [R51]
        closes = [b["close"] for b in valid[-self.bb_period:]]
        sma20 = sum(closes) / self.bb_period
        std_dev = math.sqrt(sum((x - sma20) ** 2 for x in closes) / self.bb_period)
        upper, lower = sma20 + self.bb_std_dev * std_dev, sma20 - self.bb_std_dev * std_dev
        bandwidth = (upper - lower) / sma20 * 100.0 if sma20 else 0.0
        return {
            "status": "ready",
            "M15_R1": round(upper, 2),
            "M15_MID": round(sma20, 2),
            "M15_S1": round(lower, 2),
            "M15_BB_WIDTH": round(bandwidth, 2),
        }


mtf_levels_session = MTFDynamicLevelsSession()


def m15_close_position(m15_ohlc):
    """(close - low) / (high - low) of the forming M15 bar, or None."""
    if not isinstance(m15_ohlc, dict):
        return None
    high, low, close = (to_float(m15_ohlc.get(k)) for k in ("high", "low", "close"))
    if high is None or low is None or close is None or high <= low:
        return None
    return round((close - low) / (high - low), 2)


# =============================================================================
# ⚖️ Trade history and statistics  [R7 R15 R28 R34 R42]
# =============================================================================
class RiskManagerSession:
    @staticmethod
    def read_trades():
        return jsonl_loads(gcs_read_text(TRADE_HISTORY_FILE) or "")

    def record_trade(self, trade):
        """Returns (stats, is_new). Raises StorageError instead of faking stats.  [R34b]"""
        def mutate(trades):
            if any(t.get("ticket") == trade["ticket"] for t in trades):
                return None, (trades, False)
            trades.append(trade)
            return trades, (trades, True)

        trades, is_new = gcs_update(TRADE_HISTORY_FILE, mutate, loads=jsonl_loads,
                                    dumps=jsonl_dumps, default_factory=list)
        return self.calculate_stats(trades), is_new

    def get_current_stats(self):
        try:
            return self.calculate_stats(self.read_trades())
        except StorageError as exc:
            print(f"⚠️ [交易歷史讀取失敗] {exc}", flush=True)
            stats = self.calculate_stats([])
            stats["error"] = True
            return stats

    @staticmethod
    def _summarize(profits):
        wins = [p for p in profits if p > BREAKEVEN_EPS]
        losses = [p for p in profits if p < -BREAKEVEN_EPS]
        decided = len(wins) + len(losses)
        return {
            "trades": len(profits),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(profits) - decided,
            "win_rate": round(len(wins) / decided * 100, 2) if decided else 0.0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(abs(sum(losses)) / len(losses), 2) if losses else 0.0,
            "expectancy": round(sum(profits) / len(profits), 2) if profits else 0.0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        }

    def calculate_stats(self, trades):
        """TP ratio is fixed (TARGET_RRR); stats are reported, not fed back.  [R15]
        Break-even exits are counted separately from wins and losses.  [R24c]"""
        profits = [to_float(t.get("profit"), 0.0) for t in trades]
        all_time = self._summarize(profits)
        recent = self._summarize(profits[-STATS_WINDOW:])
        return {
            "win_rate": all_time["win_rate"],
            "recommended_rrr": TARGET_RRR,
            "total_trades": all_time["trades"],
            "all_time": all_time,
            "recent": recent,
        }


risk_manager_session = RiskManagerSession()


# =============================================================================
# 🧠 SFT pipeline — compact contexts, matched pairing  [R6 R7 R24]
# =============================================================================
def build_signal_meta(candidate, m15_levels, m15_ohlc, rsi):
    return {
        "time_utc": fmt_utc(),
        "symbol": candidate["ticker"],
        "signal": candidate["signal"],
        "kind": candidate["kind"],
        "price": round(candidate["price"], 2),
        "trend_dir": candidate["direction"],
        "rsi_m1": rsi,
        "m15_r1": m15_levels.get("M15_R1"),
        "m15_mid": m15_levels.get("M15_MID"),
        "m15_s1": m15_levels.get("M15_S1"),
        "m15_bw": m15_levels.get("M15_BB_WIDTH"),
        "m15_close_pos": m15_close_position(m15_ohlc),
        "atr_m15": round(candidate["atr_m15"], 2),
        "sl_distance": candidate["sl_distance"],
        "exposure": candidate["exposure"],
        "max_lots": candidate["max_lots"],
    }


def format_signal_meta(meta):
    def num(key):
        value = to_float(meta.get(key))
        return "N/A" if value is None else f"{value:.2f}"

    def dist(key):
        price, level = to_float(meta.get("price")), to_float(meta.get(key))
        return "N/A" if price is None or level is None else f"{price - level:+.2f}"

    kind = "首單" if meta.get("kind") == "FIRST" else "加單"
    return (f"{meta.get('signal')} {kind} @ {num('price')} | 趨勢:{DIR_WORD.get(meta.get('trend_dir'), 'N/A')} | "
            f"RSI14(M1):{num('rsi_m1')} | M15 BB 上/中/下:{num('m15_r1')}/{num('m15_mid')}/{num('m15_s1')} "
            f"(帶寬 {num('m15_bw')}%) | 距上軌:{dist('m15_r1')} 距中軌:{dist('m15_mid')} 距下軌:{dist('m15_s1')} | "
            f"M15收盤位置:{num('m15_close_pos')} | ATR15:{num('atr_m15')} | SL距離:{num('sl_distance')} | "
            f"持倉:{num('exposure')}/{num('max_lots')}手")


def outcome_label(profit):
    if profit > BREAKEVEN_EPS:
        return "APPROVE"
    if profit < -BREAKEVEN_EPS:
        return "REJECT"
    return "BREAKEVEN"


class SFTDataPipeline:
    @staticmethod
    def get_trading_rules():
        try:
            text = gcs_read_text(TRADING_RULES_FILE)
        except StorageError as exc:
            print(f"⚠️ [規則庫讀取失敗] {exc}", flush=True)
            text = None
        body = text.strip()[:4000] if text and text.strip() else "目前無額外規則。"
        return "【自我反思與進化規則庫】\n" + body

    @staticmethod
    def get_dynamic_few_shot(limit=3):
        """Last losing signals as compact one-liners WITH their outcome.  [R6 R6b]
        Legacy rows (without 'meta') are ignored, so old nested prompts never re-enter."""
        try:
            text = gcs_read_text(SFT_DATASET_FILE) or ""
        except StorageError as exc:
            print(f"⚠️ [SFT 讀取失敗] {exc}", flush=True)
            return ""
        lessons = []
        for row in reversed(jsonl_loads(text)[-300:]):
            if not isinstance(row, dict):
                continue
            meta, outcome = row.get("meta"), row.get("outcome")
            if not isinstance(meta, dict) or not isinstance(outcome, dict) or outcome.get("label") != "REJECT":
                continue
            lessons.append(f"- {format_signal_meta(meta)} → 實盤結算 {to_float(outcome.get('profit'), 0.0):+.2f}")
            if len(lessons) >= limit:
                break
        return ("【歷史虧損教訓 (Dynamic Few-Shot)】\n" + "\n".join(lessons)) if lessons else ""

    @staticmethod
    def save_pending_signal(meta):
        item = {"id": uuid.uuid4().hex, "symbol": normalize_symbol(meta.get("symbol")), "ts": now_ts(), "meta": meta}

        def mutate(queue):
            queue = queue if isinstance(queue, list) else []
            queue.append(item)
            cutoff = now_ts() - PENDING_TTL_SEC
            kept = [q for q in queue if to_float(q.get("ts"), 0) >= cutoff][-PENDING_MAX:]
            if len(kept) < len(queue):
                print(f"⚠️ [SFT 佇列] 丟棄 {len(queue) - len(kept)} 筆過期/超量待配對訊號", flush=True)
            return kept, None

        try:
            gcs_update(PENDING_SIGNALS_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [SFT 暫存失敗] {exc}", flush=True)

    @staticmethod
    def pair_trade_result(symbol, profit, ticket, entry_ts=None):
        """Match a closed deal to its entry signal. With entry_ts (UTC seconds) the
        latest pending signal sent before that time is used; otherwise FIFO.  [R24b]
        Limitation: one position closed in several partial deals consumes several signals."""
        target_symbol = normalize_symbol(symbol)

        def mutate(queue):
            queue = queue if isinstance(queue, list) else []
            indexes = [i for i, q in enumerate(queue) if q.get("symbol") == target_symbol]
            if not indexes:
                return None, None
            chosen = indexes[0]
            if entry_ts is not None:
                before = [i for i in indexes if to_float(queue[i].get("ts"), 0) <= entry_ts + 120]
                if before:
                    chosen = max(before, key=lambda i: to_float(queue[i].get("ts"), 0))
            item = queue.pop(chosen)
            return queue, item

        try:
            item = gcs_update(PENDING_SIGNALS_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [SFT 配對失敗] {exc}", flush=True)
            return
        if not item or not isinstance(item.get("meta"), dict):
            return

        label = outcome_label(profit)
        example = {
            "contents": [
                {"role": "user", "parts": [{"text": format_signal_meta(item["meta"])}]},
                {"role": "model", "parts": [{"text": f"{label} | 實盤結算 {profit:+.2f}"}]},
            ],
            "meta": item["meta"],
            "outcome": {"label": label, "profit": profit, "ticket": ticket, "closed_utc": fmt_utc()},
        }

        def append(rows):
            rows.append(example)
            return rows[-SFT_MAX_LINES:], None

        try:
            gcs_update(SFT_DATASET_FILE, append, loads=jsonl_loads, dumps=jsonl_dumps, default_factory=list)
        except StorageError as exc:
            print(f"⚠️ [SFT 寫入失敗] {exc}", flush=True)


sft_pipeline_session = SFTDataPipeline()


# =============================================================================
# 📦 Raw payload log
# =============================================================================
class WebhookLogSession:
    @staticmethod
    def save_payload(payload):
        entry = {"timestamp_utc": fmt_utc(), "payload": payload}

        def mutate(history):
            history = history if isinstance(history, list) else ([history] if isinstance(history, dict) else [])
            history.insert(0, entry)
            return history[:30], None

        try:
            gcs_update(WEBHOOK_LOG_FILE, mutate, dumps=lambda d: json.dumps(d, ensure_ascii=False, indent=2),
                       default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [Payload 紀錄異常] {exc}", flush=True)

    @staticmethod
    def get_last_payload():
        try:
            data = gcs_read_json(WEBHOOK_LOG_FILE, [])
        except StorageError:
            return "封包紀錄讀取失敗。"
        if not data:
            return "尚未收到任何封包。"
        if not isinstance(data, list):
            return json.dumps(data, ensure_ascii=False, indent=2)
        blocks = []
        for idx, item in enumerate(data, 1):
            body = json.dumps(item.get("payload", {}), ensure_ascii=False, indent=2)
            blocks.append(f"// ────── 封包 #{idx} [{item.get('timestamp_utc', '未知時間')} UTC] ──────\n{body}")
        return "\n\n".join(blocks)


webhook_log_session = WebhookLogSession()


# =============================================================================
# 📰 Macro news calendar  [R13e R16 R17 R32 R52 R53 R54]
# =============================================================================
class MacroNewsSession:
    def __init__(self):
        self._memory = None

    def _load(self, now):
        memory = self._memory
        if memory and memory.get("events") is not None and now - to_float(memory.get("fetched_ts"), 0) < NEWS_CACHE_TTL_SEC:
            return memory

        try:
            doc = gcs_read_json(NEWS_CACHE_FILE, None)          # shared across instances  [R52]
            doc = doc if isinstance(doc, dict) else None
        except StorageError:
            doc = None
        if doc and doc.get("events") is not None and now - to_float(doc.get("fetched_ts"), 0) < NEWS_CACHE_TTL_SEC:
            self._memory = doc
            return doc

        base = doc or memory or {}
        if now - to_float(base.get("last_fail_ts"), 0) < NEWS_FAIL_BACKOFF_SEC:   # [R53]
            self._memory = base
            return base

        try:
            response = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            events = response.json()
            if not isinstance(events, list):
                raise RuntimeError("unexpected feed format")
            fresh = {"fetched_ts": now, "events": events, "last_fail_ts": 0, "error": None}
        except Exception as exc:
            fresh = {**base, "last_fail_ts": now, "error": str(exc)[:200]}

        self._memory = fresh
        try:
            gcs_write_text(NEWS_CACHE_FILE, json.dumps(fresh, ensure_ascii=False))
        except StorageError:
            pass
        return fresh

    def status(self, now=None):
        """{'known', 'locked', 'reason', 'events', 'warning'}"""
        now = now_ts() if now is None else now
        doc = self._load(now)
        raw_events = doc.get("events")
        warning = f"日曆更新失敗：{doc['error']}" if doc.get("error") else None
        if raw_events is None or now - to_float(doc.get("fetched_ts"), 0) > NEWS_MAX_STALE_SEC:
            return {"known": False, "locked": False, "reason": warning or "日曆資料不可用",
                    "events": [], "warning": warning}

        events, lock = [], None
        for event in raw_events:
            if not isinstance(event, dict) or (event.get("country") or "") != "USD":
                continue
            impact = event.get("impact") or ""
            if impact not in ("High", "Medium"):
                continue
            try:
                event_dt = datetime.fromisoformat(str(event.get("date") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_dt.tzinfo is None:
                continue  # never guess a timezone  [R17]
            diff = event_dt.timestamp() - now
            title = event.get("title") or "未命名數據"
            in_lock = impact in NEWS_LOCK_IMPACTS and -NEWS_LOCK_AFTER_MIN * 60 <= diff <= NEWS_LOCK_BEFORE_MIN * 60
            if in_lock and lock is None:
                lock = (title, diff)
            if -3600 <= diff <= 4 * 86400:
                events.append({
                    "title": title, "impact": impact, "ts": event_dt.timestamp(),
                    "time_utc": event_dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
                    "countdown": f"{countdown_text(diff)}後" if diff > 0 else f"已發布 {countdown_text(diff)}",
                    "is_imminent": in_lock,
                })
        events.sort(key=lambda e: e["ts"])

        if lock:
            title, diff = lock
            timing = f"將於 {countdown_text(diff)}後發布" if diff > 0 else f"已發布 {countdown_text(diff)}，冷卻中"
            reason = f"【重大數據熔斷】{title} {timing}"
        else:
            reason = "目前無重大美元數據威脅"
        return {"known": True, "locked": bool(lock), "reason": reason, "events": events, "warning": warning}


macro_news_session = MacroNewsSession()


def news_blocks_entries(news):
    return bool(news.get("locked")) or (not news.get("known") and NEWS_FAIL_CLOSED)


# =============================================================================
# 🤖 Optional LLM reviewer — one consistent fail policy  [R2 R5 R13f R13g R14 R66]
# =============================================================================
class AIReviewSession:
    def __init__(self):
        self.client = None
        if not AI_REVIEW_ENABLED:
            print("ℹ️ [Vertex AI] AI_REVIEW_ENABLED=0，AI 覆核停用。", flush=True)
            return
        try:
            self.client = genai.Client(vertexai=True, location=AI_LOCATION)
            print("✅ [Vertex AI] Gemini 客戶端初始化成功。", flush=True)
        except Exception as exc:
            print(f"⚠️ [Vertex AI] 初始化失敗：{exc}（訊號依 AI_FAIL_OPEN={AI_FAIL_OPEN} 處理）", flush=True)

    @staticmethod
    def _fallback(why):
        return AI_FAIL_OPEN, f"{why} → 依 AI_FAIL_OPEN 設定{'放行' if AI_FAIL_OPEN else '拒絕'}"

    @staticmethod
    def _config():
        kwargs = {"temperature": 0.0, "max_output_tokens": 256}
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=AI_THINKING_BUDGET)
        except Exception:
            pass
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def build_prompt(meta, rules_text, few_shot):
        rsi_note = "" if meta.get("rsi_m1") is not None else "（RSI 目前不可用，請勿當作 50 解讀）"
        return (
            "Role: XAUUSD 風險覆核員。\n"
            "此訊號已通過程式化硬性規則（趨勢方向、M15 布林帶結構、RSI 極值、風險倉位上限、ATR 加碼距離）。"
            "請勿重新驗算這些數字條件。\n"
            "你的任務：參考規則庫與歷史虧損教訓，判斷此訊號是否與過去虧損情境高度相似，或有明顯不利的風險背景。\n\n"
            f"訊號：{format_signal_meta(meta)}{rsi_note}\n\n"
            f"{rules_text}\n\n"
            f"{few_shot or '【歷史虧損教訓】目前無。'}\n\n"
            "OUTPUT FORMAT (CRITICAL): 只回覆一行，格式為「APPROVE | 理由」或「REJECT | 理由」。"
            "不要使用 JSON、Markdown 或多行。"
        )

    def review(self, meta):
        if not AI_REVIEW_ENABLED:
            return True, "AI 覆核已停用 (AI_REVIEW_ENABLED=0)"
        if self.client is None:
            return self._fallback("Vertex AI 未初始化")
        prompt = self.build_prompt(meta, sft_pipeline_session.get_trading_rules(),
                                   sft_pipeline_session.get_dynamic_few_shot())
        try:
            response = self.client.models.generate_content(model=AI_MODEL, contents=prompt, config=self._config())
            text = (response.text or "").strip()
        except Exception as exc:
            return self._fallback(f"AI API 錯誤：{str(exc)[:150]}")
        print(f"🔍 [Vertex AI 原始回應] {text[:300]}", flush=True)
        if not text:
            return self._fallback("AI 空回應")

        first_line = text.splitlines()[0]
        decision, separator, reason = first_line.partition("|")
        decision = decision.strip().strip("*`'\" ").upper()
        reason = reason.strip() or "（無理由）"
        if not separator:
            return self._fallback(f"AI 回應格式錯誤：{first_line[:80]}")
        if decision == "APPROVE":
            return True, reason
        if decision == "REJECT":
            return False, reason
        return self._fallback(f"AI 回應無法辨識：{first_line[:80]}")


ai_review_session = AIReviewSession()


# =============================================================================
# 🎯 Deterministic entry / pyramiding engine  [R3 R4 R5 R11 R12 R13 R25]
# =============================================================================
class PureGCPPyramidingSession:
    @staticmethod
    def calculate_max_lots(equity, currency, price, sl_distance, ignore_risk=False):
        """Max total exposure so that the whole pyramid stopped out loses about
        RISK_PCT of equity, also limited by margin and HARD_MAX_LOTS.  [R11]"""
        rate = FX_TO_USD.get(str(currency).upper()) or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
        if not rate or equity <= 0 or price <= 0 or sl_distance <= 0:
            return 0.0, f"無法換算 {currency} → USD（請設定 ACCOUNT_TO_USD_RATE）"
        equity_usd = equity * rate
        risk_lots = equity_usd * RISK_PCT / (sl_distance * CONTRACT_SIZE)
        margin_lots = equity_usd * MAX_MARGIN_PCT / (price * CONTRACT_SIZE / BROKER_LEVERAGE)
        lots = min(margin_lots, HARD_MAX_LOTS) if ignore_risk else min(risk_lots, margin_lots, HARD_MAX_LOTS)
        note = f"風險 {risk_lots:.3f}{'（已略過）' if ignore_risk else ''} / 保證金 {margin_lots:.3f} / 硬上限 {HARD_MAX_LOTS:.2f}"
        return math.floor(lots * 100 + 1e-9) / 100.0, note

    @staticmethod
    def _first_entry_structure(side, close, levels, m15_ohlc):
        r1, mid, s1 = levels["M15_R1"], levels["M15_MID"], levels["M15_S1"]
        if FIRST_ENTRY_MODE == "MID":
            if side == "BUY" and close <= mid:
                return False, f"價格 {close:.2f} 未站上 M15 中軌 {mid:.2f}"
            if side == "SELL" and close >= mid:
                return False, f"價格 {close:.2f} 未跌破 M15 中軌 {mid:.2f}"
            return True, ""
        # BREAKOUT: the rule that used to live only in the AI prompt, now exact.  [R5]
        if side == "BUY" and close <= r1:
            return False, f"價格 {close:.2f} 未突破 M15 上軌 {r1:.2f}"
        if side == "SELL" and close >= s1:
            return False, f"價格 {close:.2f} 未跌破 M15 下軌 {s1:.2f}"
        position = m15_close_position(m15_ohlc)
        if position is None:
            return False, "M15 K 線高低點資料不足"
        if side == "BUY" and position < M15_CLOSE_POSITION_MIN:
            return False, f"M15 收盤位置 {position:.2f} 未靠近高點（需 ≥ {M15_CLOSE_POSITION_MIN:.2f}）"
        if side == "SELL" and position > 1 - M15_CLOSE_POSITION_MIN:
            return False, f"M15 收盤位置 {position:.2f} 未靠近低點（需 ≤ {1 - M15_CLOSE_POSITION_MIN:.2f}）"
        return True, ""

    def evaluate_and_trigger(self, payload, gate_state, m15_levels, bar, rsi, now=None, bypass=frozenset()):
        """Returns a candidate dict or None. Nothing here sends orders or moves the
        pyramid base price (except re-anchoring when no base exists)."""
        now = now_ts() if now is None else now
        direction = gate_state.get("dir")
        if gate_status(gate_state, now) != "OPEN" or direction not in ("UP", "DOWN"):
            return None
        side = "BUY" if direction == "UP" else "SELL"
        symbol = ORDER_SYMBOL   # EA sends symbol "NONE" when flat, so never trust payload symbol for orders

        buy_lots, sell_lots = to_float(payload.get("buy_lots")), to_float(payload.get("sell_lots"))
        equity = to_float(payload.get("equity"))
        if buy_lots is None or sell_lots is None or equity is None or equity <= 0:      # [R13c]
            log_decision("⏸️ [資料不足] 封包缺少 buy_lots / sell_lots / equity，本根不交易。", key="data")
            return None
        buy_lots, sell_lots = round(buy_lots, 2), round(sell_lots, 2)                   # [R12]
        reported_net = to_float(payload.get("net_lots"))
        if reported_net is not None and abs(round(reported_net, 2) - round(buy_lots - sell_lots, 2)) >= 0.01:
            print(f"⚠️ [淨敞口不一致] EA net_lots={reported_net} 但 buy-sell={buy_lots - sell_lots:.2f}（以 buy/sell 為準）[R12b]", flush=True)

        if m15_levels.get("status") != "ready":                                         # [R13d]
            log_decision(f"⏸️ [結構未就緒] M15 布林帶狀態：{m15_levels.get('status')}，暫停交易。", key="data")
            return None
        m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}
        atr = to_float(m15_ohlc.get("atr_m15"))
        if atr is None or atr <= 0:
            log_decision("⏸️ [資料不足] 缺少有效的 ATR(M15)，本根不交易。", key="data")
            return None

        close, open_price = bar["close"], bar["open"]
        sl_distance = max(MIN_SL_DISTANCE, round(atr * SL_ATR_MULT, 2))
        currency = str(payload.get("currency") or ACCOUNT_CURRENCY_DEFAULT)
        max_lots, sizing_note = self.calculate_max_lots(equity, currency, close, sl_distance,
                                                        ignore_risk="risk_cap" in bypass)

        try:
            pstate = read_pyramid_state()
        except StorageError as exc:                                                      # [R13b]
            log_decision(f"⏸️ [狀態讀取失敗] 加單狀態不可用，本根不交易：{exc}", key="data")
            return None

        gross = round(buy_lots + sell_lots, 2)
        since_order = now - to_float(pstate.get("last_order_ts"), 0.0)
        if since_order < ORDER_SETTLE_SEC and abs(gross - to_float(pstate.get("exposure_at_order"), -1.0)) < 0.005:
            log_decision(f"⏳ [等待成交回報] 上一張訂單送出 {int(since_order)} 秒，持倉尚未更新，暫停決策。", key="settle")
            return None                                                                  # [R12c]
        if buy_lots > 0 and sell_lots > 0:
            log_decision(f"⏸️ [對沖持倉] Buy {buy_lots:.2f} / Sell {sell_lots:.2f}，系統不處理對沖倉，暫停交易。", key="risk")
            return None

        if "rsi" not in bypass and rsi is not None and ((side == "BUY" and rsi >= RSI_BUY_MAX) or (side == "SELL" and rsi <= RSI_SELL_MIN)):
            log_decision(f"⏳ [RSI 極值] RSI14(M1)={rsi:.2f}，拒絕追{'多' if side == 'BUY' else '空'}。", key="filter")
            return None

        candle = "BULL" if close > open_price else ("BEAR" if close < open_price else "DOJI")   # [R39]
        candle_ok = candle == ("BULL" if side == "BUY" else "BEAR")
        word = DIR_WORD[direction]
        base = {"signal": side, "ticker": symbol, "price": close, "direction": direction,
                "sl_distance": sl_distance, "atr_m15": atr, "max_lots": max_lots, "exposure": gross}

        # ---- First entry: only in the gate's trend direction  [R4] ----
        if gross == 0:
            since_close = now - to_float(pstate.get("last_close_ts"), 0.0)
            if "cooldown" not in bypass and since_close < REENTRY_COOLDOWN_SEC:                                       # [R25b]
                log_decision(f"⏳ [平倉冷卻] 距上次平倉 {int(since_close)} 秒（需 {REENTRY_COOLDOWN_SEC} 秒）。", key="wait")
                return None
            if not candle_ok and "candle" not in bypass:
                log_decision(f"⏳ [首單過濾] {word}趨勢，但 M1 {CANDLE_WORD[candle]}，等待同向 K 線。", key="filter")
                return None
            ok, why = (True, "") if "structure" in bypass else self._first_entry_structure(side, close, m15_levels, m15_ohlc)
            if not ok:
                log_decision(f"⏳ [首單過濾] {word}趨勢：{why}。", key="filter")
                return None
            if max_lots + 1e-9 < ORDER_SIZE:
                log_decision(f"🛑 [資金控管] 風險上限 {max_lots:.2f} 手 < 單筆 {ORDER_SIZE:.2f} 手（{sizing_note}），不開首單。", key="risk")
                return None
            log_decision(f"🎯 [首單候選] {side} @ {close:.2f}（{word}趨勢，上限 {max_lots:.2f} 手），送交新聞與 AI 覆核。{bypass_note(bypass)}", key="candidate")
            return {**base, "kind": "FIRST"}

        # ---- Pyramid add ----
        exposure_dir = "UP" if buy_lots > 0 else "DOWN"
        if exposure_dir != direction:
            log_decision(f"🛑 [方向衝突] 持倉為{DIR_WORD[exposure_dir]}，但電閘趨勢為{word}，不加碼。", key="risk")
            return None
        if gross + ORDER_SIZE > max_lots + 1e-9:
            log_decision(f"🛑 [資金控管] 持倉 {gross:.2f} + {ORDER_SIZE:.2f} 將超過風險上限 {max_lots:.2f} 手（{sizing_note}），停止加單。", key="risk")
            return None                                                                  # [R11e] never reduces
        if not candle_ok and "candle" not in bypass:
            log_decision(f"⏳ [動能過濾] 持{word}倉，但 M1 {CANDLE_WORD[candle]}，本根不加單。", key="filter")
            return None
        mid = m15_levels["M15_MID"]
        if "structure" not in bypass and ((side == "BUY" and close < mid) or (side == "SELL" and close > mid)):
            log_decision(f"🛑 [結構破壞] 價格 {close:.2f} 已{'跌破' if side == 'BUY' else '站上'} M15 中軌 {mid:.2f}，停止加{'多' if side == 'BUY' else '空'}。", key="structure")
            return None

        anchor = to_float(pstate.get("last_entry_price"))
        if not anchor or pstate.get("last_entry_dir") != direction:                      # [R13b]
            try:
                update_pyramid_state(last_entry_price=close, last_entry_dir=direction)
            except StorageError as exc:
                print(f"⚠️ [加單基準寫入失敗] {exc}", flush=True)
                return None
            log_decision(f"📌 [重設加單基準] 找不到同向的上次進場價，以 {close:.2f} 為新基準，本根不加單。", key="anchor")
            return None

        spacing = round(atr * ADD_SPACING_ATR, 2)
        target = anchor + spacing if side == "BUY" else anchor - spacing
        if "add_spacing" not in bypass and ((side == "BUY" and close < target) or (side == "SELL" and close > target)):
            log_decision(f"⏳ [冷卻等待] 前次:{anchor:.2f} ➔ 需{'突破' if side == 'BUY' else '跌破'}:{target:.2f}，目前:{close:.2f}。", key="wait")
            return None
        log_decision(f"🎯 [加單候選] {side} @ {close:.2f} 越過加碼距離 (目標:{target:.2f})，持倉 {gross:.2f}/{max_lots:.2f} 手，送交覆核。{bypass_note(bypass)}", key="candidate")
        return {**base, "kind": "ADD"}


pure_gcp_session = PureGCPPyramidingSession()


# =============================================================================
# 🚀 Execution: news → AI → broker → commit state  [R1 R1b R3 R24f R64 R65]
# =============================================================================
def build_order(candidate):
    order = ORDER_TEMPLATE.copy()
    order["action"] = candidate["signal"]
    order["symbol"] = candidate["ticker"]
    sl = candidate["sl_distance"]
    order["sl_distance_price"] = f"{sl:.2f}"
    order["tp_distance_price"] = f"{round(sl * TARGET_RRR, 2):.2f}"
    order["ts_activation_price"] = TS_ACTIVATION_PRICE
    order["ts_distance_price"] = TS_DISTANCE_PRICE
    order["breakeven_distance_price"] = BREAKEVEN_DISTANCE_PRICE
    order["breakeven_profit"] = BREAKEVEN_PROFIT
    return order


def execute_signal(candidate, payload, m15_levels, rsi, news, bypass=frozenset()):
    signal, price = candidate["signal"], candidate["price"]
    label = "首單" if candidate["kind"] == "FIRST" else "加單"
    m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}
    meta = build_signal_meta(candidate, m15_levels, m15_ohlc, rsi)

    if "news" not in bypass and news_blocks_entries(news):
        reason = news["reason"] if news.get("known") else f"日曆狀態未知（{news.get('reason')}），NEWS_FAIL_CLOSED=1"
        log_decision(f"📰 [新聞攔截] {label} {signal} @ {price:.2f} 取消：{reason}", key="news_reject")
        return {"status": "news_rejected", "reason": reason}

    approved, ai_reason = (True, "AI 覆核關卡已略過") if "ai" in bypass else ai_review_session.review(meta)
    if not approved:
        log_decision(f"❌ [AI 攔截] {label} {signal} @ {price:.2f} 理由：{ai_reason}", key="ai_reject")
        return {"status": "ai_rejected", "reason": ai_reason}

    order = build_order(candidate)
    summary = (f"{label} {signal} {candidate['ticker']} @ {price:.2f} | SL:{order['sl_distance_price']} "
               f"TP:{order['tp_distance_price']} | 持倉 {candidate['exposure']:.2f}/{candidate['max_lots']:.2f} 手")

    print(f"🚀 [實盤下單 JSON] {json.dumps(order, ensure_ascii=False)}", flush=True)
    sent_at = now_ts()
    commit = {"last_entry_price": price, "last_entry_dir": candidate["direction"],
              "last_order_ts": sent_at, "exposure_at_order": candidate["exposure"]}
    try:
        response = requests.post(BROKER_API_URL, json=order, timeout=BROKER_TIMEOUT_SEC)
    except requests.Timeout:
        # The order may have been placed: block decisions until exposure changes.  [R1b]
        try:
            update_pyramid_state(**commit, last_order_status="UNKNOWN")
        except StorageError as exc:
            print(f"⚠️ [狀態寫入失敗] {exc}", flush=True)
        log_decision(f"⚠️ [下單逾時] {summary}：訂單可能已成交，暫停 {ORDER_SETTLE_SEC} 秒等待持倉回報。", key="broker_error")
        return {"status": "broker_timeout", "executed_signal": signal}
    except requests.RequestException as exc:
        log_decision(f"❌ [下單失敗] {summary}：{str(exc)[:150]}", key="broker_error")
        return {"status": "broker_error", "reason": str(exc)[:150]}

    body = (response.text or "")[:300]
    print(f"📨 [券商回應] HTTP {response.status_code}: {body}", flush=True)
    if not response.ok:
        log_decision(f"❌ [下單失敗] {summary}：HTTP {response.status_code} {body[:120]}", key="broker_error")
        return {"status": "broker_error", "http_status": response.status_code}

    # Only now: move the pyramid base and queue the SFT context.  [R3 R24f]
    try:
        update_pyramid_state(**commit, last_order_status="SENT")
    except StorageError as exc:
        print(f"🚨 [嚴重] 訂單已送出但加單狀態寫入失敗：{exc}", flush=True)
    sft_pipeline_session.save_pending_signal(meta)
    log_decision(f"✅ [已送出] {summary}", key="entry_sent")
    return {"status": "success", "executed_signal": signal}


# =============================================================================
# 📡 POST handlers
# =============================================================================
def parse_payload(req):
    try:
        raw = req.get_data().decode("utf-8")
    except UnicodeDecodeError:
        return None
    clean = raw.replace("\x00", "").strip()          # MT5 char arrays often end with \0  [R60]
    if not clean:
        return {}
    try:
        data = json.loads(clean)
    except ValueError:
        data = req.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def locked_response(state):
    lock = state.get("hard_lock") if hard_lock_active(state) else None
    return jsonify({
        "status": "forbidden", "message": "Gate is LOCK", "current_gate": "LOCK",
        "regime": state.get("regime"), "dir": state.get("dir"), "news_lock": state.get("news_lock"),
        "hard_lock": lock.get("reason") if lock else None,
    }), LOCKED_HTTP_STATUS


def handle_trade_result(payload):
    entry = str(payload.get("entry") or payload.get("deal_entry") or "").strip().upper()
    if entry in ("IN", "DEAL_ENTRY_IN"):                                                 # [R24e]
        return jsonify({"status": "ignored", "message": "opening deal"}), 200
    profit = to_float(payload.get("profit"))
    if profit is None:
        return jsonify({"status": "error", "message": "missing profit"}), 400

    now = now_ts()
    volume = to_float(payload.get("volume"), 0.0)
    deal_type = str(payload.get("deal_type") or "")
    broker_time = str(payload.get("time") or "").strip()
    symbol = payload.get("symbol") or ORDER_TEMPLATE["symbol"]
    ticket = str(payload.get("ticket") or "").strip()
    if not ticket:                                                                       # [R28]
        digest = hashlib.sha1(f"{broker_time}|{profit}|{volume}|{deal_type}|{symbol}".encode()).hexdigest()
        ticket = f"noticket-{digest[:16]}"

    trade = {
        "ticket": ticket, "profit": profit, "volume": volume, "deal_type": deal_type,
        "symbol": normalize_symbol(symbol), "position_id": str(payload.get("position_id") or ""),
        "time": broker_time or fmt_utc(now), "time_source": "broker" if broker_time else "server_utc",   # [R42]
        "received_utc": fmt_utc(now),
    }
    try:
        stats, is_new = risk_manager_session.record_trade(trade)                         # dedupe FIRST  [R7]
    except StorageError as exc:
        print(f"⚠️ [交易歷史寫入失敗] {exc}", flush=True)
        return jsonify({"status": "error", "message": "trade history unavailable"}), 500

    if is_new:
        entry_ts = to_float(payload.get("entry_time"))   # optional: MT5 position open time (server epoch)
        if entry_ts is not None:
            entry_ts -= BROKER_UTC_OFFSET_HOURS * 3600
        sft_pipeline_session.pair_trade_result(symbol, profit, ticket, entry_ts)
        try:
            update_pyramid_state(last_close_ts=now)
        except StorageError as exc:
            print(f"⚠️ [平倉時間寫入失敗] {exc}", flush=True)

    return jsonify({"status": "success" if is_new else "duplicate",
                    "win_rate": stats["win_rate"], "recommended_rrr": stats["recommended_rrr"]}), 200


def handle_heartbeat(payload, can_trade):
    now = now_ts()
    action = payload.get("action")
    status_signal = str(payload.get("status") or "").strip().upper()
    m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}   # [R23b]

    # 1) Hard events first, so nothing below can skip them.  [R10 R62]
    if status_signal in ("TARGET_HIT", "RISK_HIT"):
        until = next_ny_rollover_ts(now)
        lock_reason = "當日獲利達標 (TARGET_HIT)" if status_signal == "TARGET_HIT" else "EA 帳戶風控觸發 (RISK_HIT)"
        try:
            set_hard_lock(lock_reason, until)
            update_pyramid_state(last_entry_price=None, last_entry_dir=None)
        except StorageError as exc:
            print(f"🚨 [嚴重] TARGET_HIT 硬鎖寫入失敗：{exc}", flush=True)
        log_decision(f"🛑 [{lock_reason}] 電閘硬鎖至 {fmt_ny(until)}，重置加單基準價。", key="target_hit")
    elif action == "close_gate":
        disarm_gate("EA 要求 close_gate：解除武裝，需重新 Setup→Trigger")                  # [R19]

    # 2) M15 levels (writer path) and account snapshot.
    m15_levels = mtf_levels_session.ingest(m15_ohlc) if m15_ohlc else mtf_levels_session.read_levels()
    save_account_snapshot(payload, m15_ohlc, m15_levels)

    # 3) M1 bar: validate, de-duplicate, update regime/gate.
    m1_result, bar, news = None, None, None
    bypass = read_gate_bypass()
    m1_ohlc = payload.get("m1_ohlc")
    if isinstance(m1_ohlc, dict) and m1_ohlc.get("is_new_bar"):
        bar = gold_indicator_session.parse_bar(m1_ohlc)
        if bar is None:
            print("⚠️ [M1] 無效的 m1_ohlc，略過。", flush=True)
        elif not gold_indicator_session.is_gold_market_open(now):
            print("ℹ️ [M1] 休市時段，略過。", flush=True)
            log_decision("🌙 [休市] 黃金休市時段，暫停盤勢判定。", key="monitor")
        elif not claim_m1_bar(bar["time"]):
            print(f"ℹ️ [M1] 重複的 K 線封包 {bar['time']}，略過。", flush=True)
        else:
            news = macro_news_session.status(now)
            try:
                m1_result = gold_indicator_session.process_m1_bar(
                    bar, news["locked"] and "news" not in bypass, skip_setup="setup_trigger" in bypass)
            except Exception as exc:
                print(f"⚠️ [M1 盤勢狀態機異常] {exc}", flush=True)

    # 4) Gate check.
    gate_state = read_gate_state()
    if gate_status(gate_state, now) != "OPEN":
        return locked_response(gate_state)
    if not can_trade:                                                                    # [R18]
        return jsonify({"status": "error", "message": "Unauthorized token"}), 403
    if m1_result is None:
        return jsonify({"status": "monitoring", "message": "No new M1 bar to evaluate", "current_gate": "OPEN"}), 200

    # 5) Engine → execution.
    candidate = pure_gcp_session.evaluate_and_trigger(payload, gate_state, m15_levels, bar, m1_result["rsi"], now,
                                                      bypass=bypass)
    if not candidate:
        return jsonify({"status": "monitoring", "message": "Waiting for pure GCP criteria", "current_gate": "OPEN"}), 200
    return jsonify(execute_signal(candidate, payload, m15_levels, m1_result["rsi"], news, bypass)), 200


# =============================================================================
# 🌐 Web pages (read-only except the explicit dashboard actions)
# =============================================================================
BASE_CSS = """
:root { --primary:#0f62fe; --success:#198754; --danger:#dc3545; --warning:#d97706; --bg:#f4f7fb; --card:#fff; --text:#161616; --muted:#6c757d; }
* { box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); padding:20px 15px; margin:0; }
.container { max-width:1050px; margin:0 auto; }
.nav { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:24px; padding:15px 20px; background:var(--card); border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.03); }
.nav a { color:var(--primary); text-decoration:none; font-weight:bold; font-size:14px; margin-left:15px; }
.page-title { font-size:18px; font-weight:bold; margin:0; }
.grid { display:grid; gap:16px; margin-bottom:24px; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); }
.card { background:var(--card); padding:20px; border-radius:16px; box-shadow:0 4px 15px rgba(0,0,0,.04); }
.card-title { font-size:13px; color:var(--muted); margin-bottom:8px; font-weight:600; }
.card-value { font-size:24px; font-weight:bold; }
.card-small { font-size:16px; font-weight:bold; }
.card-desc { font-size:12px; color:#adb5bd; margin-top:8px; }
.section { background:var(--card); padding:25px; border-radius:16px; box-shadow:0 4px 15px rgba(0,0,0,.04); margin-bottom:24px; }
.section-header { font-size:16px; font-weight:700; margin:30px 0 15px; padding-bottom:10px; border-bottom:2px solid #e9ecef; }
h2 { font-size:17px; margin:0 0 16px; }
.pos { color:var(--success)!important; } .neg { color:var(--danger)!important; } .muted { color:var(--muted)!important; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { padding:10px 12px; text-align:left; border-bottom:1px solid #f1f3f5; }
th { color:var(--muted); font-weight:600; background:#f8f9fa; position:sticky; top:0; }
.scroll { max-height:350px; overflow:auto; }
.mono { font-family:"Courier New",Courier,monospace; white-space:pre-wrap; }
.log-box { background:#f8f9fa; border-left:4px solid var(--primary); padding:12px 16px; border-radius:0 8px 8px 0; max-height:300px; overflow-y:auto; }
.log-line { margin-bottom:6px; font-size:13px; border-bottom:1px dashed #e9ecef; padding-bottom:4px; }
.log-card { background:#f8f9fa; border-left:4px solid var(--primary); padding:14px 18px; margin-bottom:12px; border-radius:0 8px 8px 0; }
.log-ctx { color:#495057; line-height:1.6; font-size:13px; margin-bottom:8px; word-break:break-word; }
.log-res { font-weight:bold; font-size:14px; padding-top:8px; border-top:1px dashed #dee2e6; }
.badge { padding:4px 8px; border-radius:4px; font-weight:bold; font-size:11px; }
.badge-high { background:#f8d7da; color:#721c24; } .badge-medium { background:#fff3cd; color:#856404; }
.badge-imminent { background:var(--danger); color:#fff; animation:blink 1.5s infinite; }
@keyframes blink { 50% { opacity:.5; } }
.btn { display:inline-block; padding:14px 24px; border-radius:8px; margin:6px; font-weight:bold; color:#fff; text-decoration:none; }
.btn-open { background:var(--success); } .btn-lock { background:var(--danger); } .btn-primary { background:var(--primary); } .btn-dark { background:#212529; }
.banner { padding:12px; margin-bottom:20px; border-radius:8px; font-weight:bold; }
.level-box { background:#f8f9fa; padding:16px; border-radius:8px; }
"""

LOG_KEY_COLORS = {
    "candidate": "#0d6efd", "entry_sent": "#198754", "gate": "#3730a3", "regime": "#3730a3", "monitor": "#6c757d", "admin": "#d97706",
    "wait": "#6c757d", "filter": "#6c757d", "settle": "#6c757d", "anchor": "#6c757d",
    "data": "#d97706", "risk": "#dc3545", "structure": "#dc3545", "ai_reject": "#dc3545",
    "news_reject": "#dc3545", "broker_error": "#dc3545", "target_hit": "#dc3545",
}

CHART_SCRIPT = """
<script>
(function () {
  var el = document.getElementById('pnlChart');
  if (!el || typeof Chart === 'undefined') return;
  var ctx = el.getContext('2d');
  var gradient = ctx.createLinearGradient(0, 0, 0, 280);
  gradient.addColorStop(0, 'rgba(15, 98, 254, 0.2)');
  gradient.addColorStop(1, 'rgba(15, 98, 254, 0)');
  var labels = __LABELS__, data = __DATA__;
  new Chart(ctx, { type: 'line',
    data: { labels: labels.length ? labels : ['Init'],
            datasets: [{ label: '累計已實現損益', data: data.length ? data : [0], borderColor: '#0f62fe',
                         backgroundColor: gradient, borderWidth: 2.5, fill: true, tension: 0.25, pointRadius: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } } });
})();
</script>
"""


def html_page(title, body, head_extra=""):
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
            f"<title>{esc(title)}</title><style>{BASE_CSS}</style>{head_extra}</head>"
            f"<body><div class='container'>{body}</div></body></html>")


def pnl_class(value):
    number = to_float(value)
    if number is None or number == 0:
        return "muted"
    return "pos" if number > 0 else "neg"


def gate_summary(state):
    """Short investor-facing description of why the gate is open/locked.  [R27b]"""
    if hard_lock_active(state):
        lock = state["hard_lock"]
        until = to_float(lock.get("until_ts"))
        return "neg", f"🛑 硬鎖：{lock.get('reason')}" + (f"（至 {fmt_ny(until)}）" if until else "（需手動解除）")
    if state.get("news_lock"):
        return "neg", "📰 新聞風控中"
    if gate_status(state) == "OPEN":
        return "pos", f"✅ 放行（{DIR_WORD.get(state.get('dir'), '')}趨勢）"
    regime_text = {REGIME_RANGE: "橫行", REGIME_SETUP: "Setup 醞釀", REGIME_TREND: "趨勢未確認"}.get(state.get("regime"), "—")
    return "muted", f"⏸️ 等待趨勢確認（{regime_text}）"


def render_welcome_page():
    body = """
    <div class='section' style='text-align:center; max-width:700px; margin:60px auto; padding:50px 40px;'>
      <div style='font-size:60px; margin-bottom:20px;'>🤖⚡</div>
      <h1 style='color:#0d6efd; margin-bottom:10px; font-size:32px;'>智能諸葛亮 AI 量化風控樞紐</h1>
      <p style='color:#6c757d; font-size:16px; margin-bottom:40px; line-height:1.6;'>純 GCP 自動決策版本 (v12)<br>趨勢狀態機、風險倉位與 ATR 加單。</p>
      <div style='display:flex; flex-direction:column; gap:15px; max-width:400px; margin:0 auto;'>
        <a href='?view=info' class='btn btn-primary'>📄 投資人日誌 (實盤績效與 GCP 決策)</a>
        <a href='?view=gates_app' class='btn' style='background:#d97706;'>🎛️ 關卡開關頁面 (獨立版)</a>
        <a href='?view=gates' class='btn' style='background:#b45309;'>🎛️ 關卡開關頁面 (內建版)</a>
        <a href='?view=dashboard' class='btn btn-dark'>🎛️ 系統控制台 (管理員)</a>
      </div>
      <div style='margin-top:40px; font-size:12px; color:#adb5bd;'>&copy; 2026 AI Trading Lab. All rights reserved.</div>
    </div>"""
    return html_page("智能諸葛亮 AI 量化交易系統", body)


def build_dashboard_page(msg):
    state = read_gate_state()
    status = gate_status(state)
    acc = read_account_snapshot()
    stats = risk_manager_session.get_current_stats()
    currency = acc.get("currency") or ACCOUNT_CURRENCY_DEFAULT
    bars_count = len(gold_indicator_session.read_bars())
    try:
        verdict_log = gcs_read_text(M1_VERDICT_LOG_FILE) or "等待 M1 盤勢監控模組收集 K 棒..."
    except StorageError:
        verdict_log = "M1 判定日誌讀取失敗。"

    banners = {
        "auto": ("#d4edda", "#155724", "⚡ 已解除硬鎖並恢復自動。電閘會在下一次 Setup→Trigger 後開啟。"),
        "locked": ("#f8d7da", "#721c24", "🔒 已啟動緊急硬鎖。狀態機不會自動重新開閘，需手動恢復自動。"),
        "error": ("#fff3cd", "#856404", "⚠️ 電閘狀態寫入失敗，請查看 Cloud Logging。"),
    }
    banner = ""
    if msg in banners:
        bg, fg, text = banners[msg]
        banner = f"<div class='banner' style='background:{bg}; color:{fg};'>{text}</div>"

    bypass = read_gate_bypass()
    gates_warning = (f"<div class='banner' style='background:#fff3cd; color:#8a4b00;'>⚠️ {esc(detect_gate_mode(bypass))}："
                     f"已略過 {len(bypass)} 個關卡{esc(bypass_note(bypass))} → <a href='?view=gates'>關卡開關頁面</a></div>") if bypass else ""
    gate_color = "#198754" if status == "OPEN" else "#dc3545"
    gate_bg = "#d1e7dd" if status == "OPEN" else "#f8d7da"
    summary_class, summary_text = gate_summary(state)
    recent = stats.get("recent", {})

    body = f"""
    <div class='nav'><h1 class='page-title'>⚙️ 智能諸葛亮核心控制台 (Admin)</h1>
      <div><a href='?view=welcome'>🏠 返回首頁</a><a href='?view=gates'>🎛️ 關卡開關</a><a href='?view=info'>📄 投資人日誌 ➔</a></div></div>
    {banner}{gates_warning}
    <div class='section-header'>🧠 M1 動能雷達（{bars_count} 根連續 K 線，需 {MIN_M1_BARS}）</div>
    <div class='log-box mono' style='color:#3730a3; font-weight:600; max-height:200px;'>{esc(verdict_log)}</div>

    <div class='section' style='text-align:center; border-top:5px solid {gate_color}; margin-top:24px;'>
      <div class='muted' style='font-weight:600;'>雲端風控電閘狀態 (Gate Status)</div>
      <div style='display:inline-block; background:{gate_bg}; color:{gate_color}; padding:8px 20px; border-radius:30px; font-weight:800; font-size:24px; margin:15px 0;'>【 {status} 】</div>
      <div class='{summary_class}' style='font-weight:600; margin-bottom:6px;'>{esc(summary_text)}</div>
      <div class='muted' style='font-size:13px;'>趨勢狀態：{esc(state.get('regime'))} / {esc(DIR_WORD.get(state.get('dir'), '—'))} / 武裝：{'是' if state.get('armed') else '否'}｜{esc(state.get('last_reason'))}</div>
      <div style='margin-top:15px;'>
        <a href='?view=dashboard&action=auto' class='btn btn-open'>🟢 解除硬鎖・恢復自動</a>
        <a href='?view=dashboard&action=lock' class='btn btn-lock'>🔴 緊急硬鎖 (LOCK)</a>
      </div>
      <div class='muted' style='font-size:12px; margin-top:6px;'>恢復自動後，電閘仍需完成 Setup→Trigger 才會開啟。🔴 實盤下單模式</div>
    </div>

    <div class='section-header'>💰 帳戶即時資金狀態 ({esc(currency)})｜更新：{esc(acc.get('received_utc', '—'))} UTC</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>Equity (淨值)</div><div class='card-value'>{fmt_num(acc.get('equity'))}</div></div>
      <div class='card'><div class='card-title'>Balance (餘額)</div><div class='card-value'>{fmt_num(acc.get('balance'))}</div></div>
      <div class='card'><div class='card-title'>今日已實現損益</div><div class='card-value {pnl_class(acc.get('daily_pnl'))}'>{fmt_num(acc.get('daily_pnl'), '{:+,.2f}')}</div></div>
      <div class='card'><div class='card-title'>浮動損益</div><div class='card-value {pnl_class(acc.get('floating'))}'>{fmt_num(acc.get('floating'), '{:+,.2f}')}</div></div>
    </div>

    <div class='section-header'>📡 MT5 實盤持倉狀態</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>Symbol</div><div class='card-small'>{esc(acc.get('symbol', 'NONE'))}</div></div>
      <div class='card'><div class='card-title'>Net Lots (多+/空-)</div><div class='card-small {pnl_class(acc.get('net_lots'))}'>{fmt_num(acc.get('net_lots'), '{:+.2f}')}</div></div>
      <div class='card'><div class='card-title'>Buy / Sell Lots</div><div class='card-small'><span class='pos'>{fmt_num(acc.get('buy_lots'))}</span> / <span class='neg'>{fmt_num(acc.get('sell_lots'))}</span></div></div>
    </div>

    <div class='section-header'>📈 近 {STATS_WINDOW} 筆交易統計{'（讀取失敗）' if stats.get('error') else ''}</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>勝率（不含保本）</div><div class='card-small'>{recent.get('win_rate', 0):.1f}%</div><div class='card-desc'>{recent.get('wins', 0)} 勝 / {recent.get('losses', 0)} 負 / {recent.get('breakeven', 0)} 保本</div></div>
      <div class='card'><div class='card-title'>平均獲利 / 平均虧損</div><div class='card-small'>{recent.get('avg_win', 0):,.2f} / {recent.get('avg_loss', 0):,.2f}</div></div>
      <div class='card'><div class='card-title'>每筆期望值</div><div class='card-small {pnl_class(recent.get('expectancy'))}'>{recent.get('expectancy', 0):+,.2f}</div></div>
      <div class='card'><div class='card-title'>TP 倍數 (固定)</div><div class='card-small'>{TARGET_RRR:.2f}R</div></div>
    </div>

    <div class='section-header'>📦 最新接收封包 (Raw Payload)</div>
    <div class='mono' style='background:#1e1e1e; color:#d4d4d4; border-left:4px solid var(--primary); padding:16px 20px; border-radius:0 8px 8px 0; font-size:13px; max-height:350px; overflow:auto;'>{esc(webhook_log_session.get_last_payload())}</div>
    """
    return html_page("智能諸葛亮量化儀表板 - 核心控制台", body)


def _legacy_decision_log_html():
    """Shown only while the v12 log is still empty: last lines of the v11 text log."""
    try:
        legacy = gcs_read_text("gcp_decision_log.txt") or ""
    except StorageError:
        legacy = ""
    lines = [line for line in legacy.splitlines() if line.strip()][:30]
    if not lines:
        return "<div class='muted'>系統正在等待首次決策...</div>"
    return ("<div class='muted' style='margin-bottom:8px; font-weight:600;'>v12 尚無紀錄，以下為 v11 舊版決策紀錄：</div>"
            + "".join(f"<div class='log-line muted'>{esc(line)}</div>" for line in lines))


def _trade_sort_key(trade):
    return str(trade.get("time") or "").replace(".", "-")     # MT5 "2026.09.16 10:00" -> sortable  [R57]


def build_info_page():
    # ---- trades & realized PnL curve ----
    try:
        trades = sorted(risk_manager_session.read_trades(), key=_trade_sort_key)
        history_note = ""
    except StorageError as exc:
        print(f"⚠️ [交易歷史讀取失敗] {exc}", flush=True)
        trades, history_note = [], "（交易歷史讀取失敗）"
    stats = risk_manager_session.calculate_stats(trades)

    labels, series, cumulative = [], [], 0.0
    for trade in trades:
        cumulative += to_float(trade.get("profit"), 0.0)
        labels.append(_trade_sort_key(trade)[5:16] or "未知")                           # [R56]
        series.append(round(cumulative, 2))

    trade_rows = "".join(
        f"<tr><td>{esc(t.get('time', '未知'))}<span class='muted' style='font-size:11px;'> "
        f"{'MT5' if t.get('time_source') == 'broker' else ('UTC' if t.get('time_source') else '')}</span></td>"
        f"<td>{esc(t.get('ticket'))}</td>"
        f"<td>{(esc(fmt_num(t.get('volume'))) + ' 手 ' + esc(t.get('deal_type'))) if t.get('deal_type') else '舊資料'}</td>"
        f"<td class='{pnl_class(t.get('profit'))}' style='font-weight:bold;'>{fmt_num(t.get('profit'), '{:+,.2f}')}</td></tr>"
        for t in reversed(trades[-300:])
    ) or "<tr><td colspan='4' class='muted' style='text-align:center;'>尚無結算紀錄</td></tr>"

    # ---- SFT log (last 50 only)  [R6d] ----
    sft_cards = ""
    try:
        rows = jsonl_loads(gcs_read_text(SFT_DATASET_FILE) or "")[-50:]
    except StorageError:
        rows = []
    outcome_display = {"APPROVE": ("🎯 獲利交易", "#198754"), "REJECT": ("🛡️ 虧損交易", "#d97706"),
                       "BREAKEVEN": ("⚖️ 保本出場", "#6c757d")}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        try:
            meta = row.get("meta")
            context = format_signal_meta(meta) if isinstance(meta, dict) else str(row["contents"][0]["parts"][0]["text"])
            result_text = str(row["contents"][1]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError):
            continue
        if len(context) > 600:
            context = context[:600] + "…（舊版格式已截斷）"
        label = (row.get("outcome") or {}).get("label") or ("APPROVE" if result_text.upper().startswith("APPROVE") else "REJECT")
        title, color = outcome_display.get(label, outcome_display["REJECT"])
        sft_cards += (f"<div class='log-card'><div class='log-ctx'>{esc(context)}</div>"
                      f"<div class='log-res' style='color:{color};'>[{title}] {esc(result_text)}</div></div>")
    sft_cards = sft_cards or "<div class='log-card muted' style='text-align:center;'>等待首筆實盤結算後寫入日誌...</div>"

    # ---- gate, account, news ----
    state = read_gate_state()
    gate_class, gate_text = gate_summary(state)
    snapshot = read_account_snapshot()
    daily_pnl = snapshot.get("daily_pnl")

    news = macro_news_session.status()
    if not news["known"]:
        calendar_html = f"<span class='neg'>⚠️ {esc(news['reason'])}</span>"                # [R27c]
    elif news["locked"]:
        calendar_html = f"<span class='neg'>🛑 {esc(news['reason'])}</span>"
    elif news["warning"]:
        calendar_html = f"<span style='color:#d97706;'>⚠️ 使用快取｜{esc(news['warning'])}</span>"  # [R32]
    else:
        calendar_html = f"<span class='pos'>✅ 連線正常 ({len(news['events'])} 個數據已就緒)</span>"

    news_rows = ""
    for event in news["events"][:8]:
        badge = "badge-imminent" if event["is_imminent"] else ("badge-high" if event["impact"] == "High" else "badge-medium")
        event_dt = datetime.fromtimestamp(event["ts"], UTC)
        news_rows += (
            f"<tr><td>{esc(event['time_utc'])}</td>"
            f"<td style='color:#0f62fe; font-weight:600;'>{event_dt.astimezone(ZoneInfo('Europe/London')).strftime('%m-%d %H:%M')}</td>"
            f"<td style='color:#198754; font-weight:600;'>{event_dt.astimezone(ZoneInfo('Asia/Hong_Kong')).strftime('%m-%d %H:%M')}</td>"
            f"<td><span class='badge {badge}'>{esc(event['impact'])}</span></td><td style='font-weight:600;'>{esc(event['title'])}</td>"
            f"<td style='font-weight:bold;'>{esc(event['countdown'])}{' ⚠️ 避險中' if event['is_imminent'] else ''}</td></tr>")
    news_rows = news_rows or "<tr><td colspan='6' class='muted' style='text-align:center;'>近期無重大美元數據</td></tr>"

    # ---- levels & indicators (read-only)  [R20 R27d R58] ----
    levels = mtf_levels_session.read_levels()
    ready = levels.get("status") == "ready"
    r1, mid, s1 = (levels.get(k, "等待中") if ready else "等待中" for k in ("M15_R1", "M15_MID", "M15_S1"))
    bandwidth = f"{levels['M15_BB_WIDTH']}%" if ready else "..."
    bars = gold_indicator_session.read_bars()
    rsi = wilder_rsi_last([b["close"] for b in bars])
    snap_m15 = snapshot.get("m15_ohlc") if isinstance(snapshot.get("m15_ohlc"), dict) else {}   # [R23c]
    atr_text = " / ".join(esc(snap_m15.get(k, "N/A")) for k in ("atr_m1", "atr_m5", "atr_m15"))

    log_lines = "".join(
        f"<div class='log-line' style='color:{LOG_KEY_COLORS.get(entry.get('k'), '#3730a3')};'>"
        f"[{esc(entry.get('t'))} UTC] {esc(entry.get('m'))}</div>"
        for entry in read_decision_logs()
    ) or _legacy_decision_log_html()

    all_time = stats["all_time"]
    chart = CHART_SCRIPT.replace("__LABELS__", json.dumps(labels).replace("</", "<\\/")) \
                        .replace("__DATA__", json.dumps(series))

    body = f"""
    <div class='nav'><h1 class='page-title'>📊 投資人數據中心 (Investor Transparency Hub)</h1><a href='?view=welcome'>← 返回首頁</a></div>
    <div class='grid'>
      <div class='card'><div class='card-title'>累計已實現損益 ({esc(ACCOUNT_CURRENCY_DEFAULT)})</div>
        <div class='card-value {pnl_class(cumulative)}'>{cumulative:+,.2f}</div><div class='card-desc'>全部已結算交易{history_note}</div></div>
      <div class='card'><div class='card-title'>今日已實現損益</div>
        <div class='card-value {pnl_class(daily_pnl)}'>{fmt_num(daily_pnl, '{:+,.2f}')}</div><div class='card-desc'>MT5 心跳同步</div></div>
      <div class='card'><div class='card-title'>實盤勝率（不含保本）</div>
        <div class='card-value'>{all_time['win_rate']:.1f}%</div>
        <div class='card-desc'>{all_time['trades']} 筆｜期望值 {all_time['expectancy']:+,.2f}｜TP {TARGET_RRR:.1f}R</div></div>
      <div class='card'><div class='card-title'>諸葛亮電閘</div>
        <div class='card-small {gate_class}' style='padding-top:6px;'>{esc(gate_text)}</div><div class='card-desc'>趨勢狀態機 + 硬鎖 + 新聞風控</div></div>
      <div class='card'><div class='card-title'>ForexFactory 連線狀態</div>
        <div style='font-size:14px; font-weight:bold; padding-top:6px;'>{calendar_html}</div><div class='card-desc'>重大財經數據監控引擎</div></div>
    </div>

    <div class='section'><h2>🤖 純 GCP 交易大腦即時決策還原</h2>
      <p class='muted' style='font-size:12px;'>每一次候選訊號、覆核結果與實際送單都會記錄於此。</p>
      <div class='log-box'>{log_lines}</div></div>

    <div class='section'><h2>🎯 核心決策水位與指標基準</h2>
      <div class='grid' style='grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); margin-bottom:10px;'>
        <div class='level-box' style='border-left:4px solid #dc3545;'><div class='card-title'>M15 上軌 (R1)</div><div class='card-small neg'>{esc(r1)}</div></div>
        <div class='level-box' style='border-left:4px solid #0f62fe;'><div class='card-title'>M15 中軌 (SMA20)</div><div class='card-small' style='color:#0f62fe;'>{esc(mid)}</div><div class='card-desc'>帶寬: {esc(bandwidth)}</div></div>
        <div class='level-box' style='border-left:4px solid #198754;'><div class='card-title'>M15 下軌 (S1)</div><div class='card-small pos'>{esc(s1)}</div></div>
      </div>
      <div style='background:#eef2ff; border-radius:8px; padding:12px 16px; font-size:13px; color:#3730a3;'>
        📡 <b>即時技術背景</b> ➔ <b>RSI(14, M1):</b> {fmt_num(rsi) if rsi is not None else '計算中'} | <b>ATR (M1/M5/M15):</b> {atr_text}</div></div>

    <div class='section'><h2>📅 ForexFactory 總經事件預警表 (USD High/Medium)</h2>
      <p class='muted' style='font-size:12px;'>{'/'.join(sorted(NEWS_LOCK_IMPACTS))} 級事件發布前 {NEWS_LOCK_BEFORE_MIN} 分鐘至發布後 {NEWS_LOCK_AFTER_MIN} 分鐘禁止新倉。</p>
      <div class='scroll'><table><tr><th>發布時間 (UTC)</th><th style='color:#0f62fe;'>倫敦</th><th style='color:#198754;'>香港</th><th>衝擊</th><th>經濟指標</th><th>倒數</th></tr>{news_rows}</table></div></div>

    <div class='section'><h2>📈 累計已實現損益曲線 (Realized PnL)</h2>
      <p class='muted' style='font-size:12px;'>僅含已平倉損益，不含浮動盈虧與出入金。</p>
      <div style='position:relative; height:280px;'><canvas id='pnlChart'></canvas></div></div>

    <div class='section'><h2>💰 實盤結算歷史</h2>
      <div class='scroll'><table><tr><th>結算時間</th><th>交易單號</th><th>平倉組成</th><th>淨損益</th></tr>{trade_rows}</table></div></div>

    <div class='section'><h2>🧠 AI 決策與風控日誌 (最近 50 筆)</h2><div class='scroll' style='max-height:400px;'>{sft_cards}</div></div>
    {chart}
    """
    return html_page("實盤績效與 AI 決策日誌 - 投資人專區", body,
                     head_extra="<script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'></script>")


# =============================================================================
# 🎛️ 關卡開關 (gate switches) — stored separately from the gate state machine
# =============================================================================
GATE_SWITCHES_FILE = "gate_switches.json"

# key, 名稱, 正常時檢查什麼, 略過後的效果, 風險提示
GATE_SWITCH_DEFS = [
    ("setup_trigger", "趨勢確認：Setup → Trigger",
     "必須先出現同向回調（Setup），再出現同向趨勢，電閘才開啟。",
     "只要判定為「單邊趨勢」就直接開閘，不等回調。",
     "容易在急拉急跌的末端追價。"),
    ("structure", "M15 布林帶結構",
     "首單：多單須突破上軌（空單跌破下軌），且 M15 收盤靠近高點（低點）。加單：價格須在中軌正確一側。",
     "首單與加單都不看布林帶位置。",
     "可能在帶內震盪區或逆結構位置進場。"),
    ("candle", "M1 收線方向",
     "多單須當根 M1 收陽，空單須收陰。",
     "不看當根 M1 陰陽。",
     "可能在反向 K 線上進場。"),
    ("risk_cap", "2% 風險倉位上限",
     "整組倉位打到止損時，虧損不超過淨值 × RISK_PCT。",
     "改用保證金上限（淨值 × MAX_MARGIN_PCT）與 HARD_MAX_LOTS 硬上限。",
     "⚠️ 整組止損的虧損可能是正常的數倍，請看下方試算。"),
    ("rsi", "RSI 極值",
     "多單 RSI(14, M1) 須低於 RSI_BUY_MAX，空單須高於 RSI_SELL_MIN。",
     "不看 RSI。",
     "可能在超買追多、超賣追空。"),
    ("news", "新聞風控",
     "高衝擊美元事件前後鎖閘；日曆無法載入時也禁止新倉。",
     "數據公布期間照常交易，日曆失效也照常交易。",
     "⚠️ 數據行情跳空與滑價可能遠超止損距離。"),
    ("ai", "AI 覆核",
     "Gemini 須回覆 APPROVE；出錯或格式錯誤時拒絕。",
     "不呼叫 Gemini，直接放行。",
     "少一層定性過濾。"),
    ("cooldown", "平倉後冷卻",
     "平倉後須等 REENTRY_COOLDOWN_SEC 秒才開新首單。",
     "平倉後可立即再開首單。",
     "止損後可能馬上再次進場。"),
    ("add_spacing", "加單 ATR 間距",
     "加單須比上次進場價多走 ADD_SPACING_ATR × ATR(M15)。",
     "每根符合條件的 K 線都可加單，直到倉位上限。",
     "⚠️ 加單會非常密集，平均成本貼近現價。"),
]
GATE_SWITCH_KEYS = [d[0] for d in GATE_SWITCH_DEFS]
GATE_SWITCH_NAMES = {d[0]: d[1] for d in GATE_SWITCH_DEFS}

# Data / safety preconditions: no switch is offered for these.
GATE_ALWAYS_ON_NOTES = [
    "M1 數據累積（約 65 根）與 M15 布林帶、ATR(M15) 資料就緒",
    "封包缺少 equity / buy_lots / sell_lots",
    "多空對沖持倉、持倉方向與趨勢相反",
    "上一張訂單送出後等待成交回報（防重複下單）",
    "加單基準價不存在時先記錄基準、本根不加單",
    "硬鎖、券商回應失敗",
]

GATE_MODES = {
    "strict": ("🛡️ 恢復嚴格", frozenset()),
    "relaxed": ("🟡 寬鬆模式", frozenset({"setup_trigger", "structure", "candle", "risk_cap"})),
    "aggressive": ("🔥 激進模式", frozenset({"setup_trigger", "structure", "candle", "risk_cap", "rsi", "news", "ai"})),
}


def read_gate_bypass():
    """Set of switched-off gates. Fails safe: unreadable file = every gate checks normally."""
    try:
        doc = gcs_read_json(GATE_SWITCHES_FILE, {})
    except StorageError as exc:
        print(f"⚠️ [關卡開關讀取失敗 → 全部關卡照常檢查] {exc}", flush=True)
        return frozenset()
    bypass = doc.get("bypass") if isinstance(doc, dict) else None
    if not isinstance(bypass, list):
        return frozenset()
    return frozenset(k for k in bypass if k in GATE_SWITCH_KEYS)


def read_gate_switch_doc():
    try:
        doc = gcs_read_json(GATE_SWITCHES_FILE, {})
        return doc if isinstance(doc, dict) else {}
    except StorageError:
        return {}


def write_gate_bypass(bypass, mode_label):
    doc = {
        "bypass": sorted(k for k in bypass if k in GATE_SWITCH_KEYS),
        "mode": mode_label,
        "updated_utc": fmt_utc(),
    }
    gcs_write_text(GATE_SWITCHES_FILE, json.dumps(doc, ensure_ascii=False))
    return doc


def solo_test_status(bypass):
    """逐關測試：剛好只略過一個關卡時，回報目前測到第幾關。"""
    keys = list(bypass)
    total = len(GATE_SWITCH_KEYS)
    if len(keys) != 1 or keys[0] not in GATE_SWITCH_KEYS:
        return {"active": False, "index": None, "key": None, "title": None, "total": total}
    index = GATE_SWITCH_KEYS.index(keys[0])
    return {"active": True, "index": index + 1, "key": keys[0],
            "title": GATE_SWITCH_NAMES[keys[0]], "total": total}


def next_solo_bypass(bypass, step):
    """start / next / prev / stop -> 下一組 bypass（一次只略過一個關卡，走到底會繞回第一關）。"""
    total = len(GATE_SWITCH_KEYS)
    status = solo_test_status(bypass)
    if step == "stop":
        return frozenset()
    if step == "start" or not status["active"]:
        return frozenset({GATE_SWITCH_KEYS[0]})
    offset = 1 if step == "next" else (-1 if step == "prev" else 0)
    return frozenset({GATE_SWITCH_KEYS[(status["index"] - 1 + offset) % total]})


def detect_gate_mode(bypass):
    for key, (label, keys) in GATE_MODES.items():
        if bypass == keys:
            return label
    status = solo_test_status(bypass)
    if status["active"]:
        return f"🧪 逐關測試 {status['index']}/{status['total']}：{status['title']}"
    return "✏️ 自訂"


def bypass_note(bypass):
    if not bypass:
        return ""
    return "｜⚠️ 已略過：" + "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in bypass)


GATES_CSS = """
<style>
.gate-row { display:flex; gap:14px; align-items:flex-start; padding:16px; border-radius:12px; margin-bottom:12px;
            background:#f8f9fa; border-left:5px solid #198754; }
.gate-row.off { background:#fff4e5; border-left-color:#d97706; }
.gate-body { flex:1; min-width:0; }
.gate-title { font-weight:700; font-size:15px; margin-bottom:4px; }
.gate-state { font-size:12px; font-weight:700; padding:2px 8px; border-radius:10px; margin-left:6px; white-space:nowrap; }
.gate-state.on { background:#d1e7dd; color:#146c43; } .gate-state.off { background:#ffe5b4; color:#8a4b00; }
.gate-text { font-size:13px; color:#495057; line-height:1.55; margin-top:4px; }
.gate-risk { font-size:12px; color:#b45309; margin-top:4px; }
.switch { position:relative; display:inline-block; width:52px; height:30px; flex-shrink:0; margin-top:2px; }
.switch input { opacity:0; width:0; height:0; }
.slider { position:absolute; cursor:pointer; inset:0; background:#d97706; border-radius:30px; transition:.2s; }
.slider:before { content:""; position:absolute; height:24px; width:24px; left:3px; top:3px; background:#fff; border-radius:50%; transition:.2s; }
.switch input:checked + .slider { background:#198754; }
.switch input:checked + .slider:before { transform:translateX(22px); }
.mode-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }
.mode-btn { width:100%; border:none; border-radius:10px; padding:16px; font-size:16px; font-weight:700; color:#fff; cursor:pointer; }
.mode-desc { font-size:12px; color:#6c757d; margin-top:6px; line-height:1.5; }
.save-bar { position:sticky; bottom:0; background:rgba(244,247,251,.96); padding:12px 0; }
</style>
"""


def _risk_cap_preview():
    """Uses the last account snapshot to show what switching off the 2% cap means."""
    snap = read_account_snapshot()
    m15 = snap.get("m15_ohlc") if isinstance(snap.get("m15_ohlc"), dict) else {}
    equity, price, atr = to_float(snap.get("equity")), to_float(m15.get("close")), to_float(m15.get("atr_m15"))
    currency = str(snap.get("currency") or ACCOUNT_CURRENCY_DEFAULT)
    if not equity or not price or not atr:
        return "（尚無足夠的帳戶與 ATR 資料可試算）"
    sl = max(MIN_SL_DISTANCE, round(atr * SL_ATR_MULT, 2))
    normal, _ = PureGCPPyramidingSession.calculate_max_lots(equity, currency, price, sl)
    loose, _ = PureGCPPyramidingSession.calculate_max_lots(equity, currency, price, sl, ignore_risk=True)
    rate = FX_TO_USD.get(currency.upper()) or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
    if not rate:
        return "（無法換算帳戶貨幣）"
    loss_normal = normal * sl * CONTRACT_SIZE / rate
    loss_loose = loose * sl * CONTRACT_SIZE / rate
    pct_loose = loss_loose / equity * 100 if equity else 0
    return (f"以最新快照試算（淨值 {equity:,.0f} {currency}、止損 {sl:.2f} 美元）："
            f"啟用時上限 {normal:.2f} 手，整組止損約 {loss_normal:,.0f} {currency}；"
            f"停用後上限 {loose:.2f} 手，整組止損約 {loss_loose:,.0f} {currency}（淨值的 {pct_loose:.0f}%）。")


# -----------------------------------------------------------------------------
# 🔌 JSON API for the standalone gates.html  (GET/POST ?view=gates&format=json)
# -----------------------------------------------------------------------------
GATES_API_REQUIRE_TOKEN = _env_bool("GATES_API_REQUIRE_TOKEN", True)   # writes need the webhook token
GATES_CORS_ORIGIN = _env_str("GATES_CORS_ORIGIN", "*")                 # set to your page origin to narrow it
GATES_APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gates.html")


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": GATES_CORS_ORIGIN,
        "Access-Control-Allow-Headers": "Content-Type, X-Gate-Token",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Max-Age": "3600",
        "Vary": "Origin",
    }


def _json_response(payload, status=200):
    response = jsonify(payload)
    for key, value in _cors_headers().items():
        response.headers[key] = value
    return response, status


def cors_preflight():
    return _json_response({"status": "ok"})


def gates_state_payload(message=None):
    """Everything the standalone page needs, so the page holds no rule text of its own."""
    bypass = read_gate_bypass()
    doc = read_gate_switch_doc()
    state = read_gate_state()
    summary_class, summary_text = gate_summary(state)
    lock = state.get("hard_lock") if hard_lock_active(state) else None
    until = to_float(lock.get("until_ts")) if isinstance(lock, dict) else None
    return {
        "status": "ok",
        "message": message,
        "server_utc": fmt_utc(),
        "gate": {
            "status": gate_status(state),
            "regime": state.get("regime"),
            "dir": state.get("dir"),
            "dir_word": DIR_WORD.get(state.get("dir")),
            "armed": bool(state.get("armed")),
            "news_lock": bool(state.get("news_lock")),
            "last_reason": state.get("last_reason"),
            "summary": summary_text,
            "summary_class": summary_class,
            "hard_lock": ({"reason": lock.get("reason"), "since_utc": lock.get("since_utc"),
                           "until_ts": until, "until_text": fmt_ny(until) if until else None}
                          if isinstance(lock, dict) else None),
        },
        "switches": {
            "mode": detect_gate_mode(bypass),
            "bypass": sorted(bypass),
            "updated_utc": doc.get("updated_utc"),
            "gates": [{"key": key, "title": title, "normal": normal, "skipped": skipped,
                       "risk": risk, "enabled": key not in bypass}
                      for key, title, normal, skipped, risk in GATE_SWITCH_DEFS],
        },
        "modes": [{"key": key, "label": label, "bypass": sorted(keys)} for key, (label, keys) in GATE_MODES.items()],
        "test": solo_test_status(bypass),
        "risk_preview": _risk_cap_preview(),
        "always_on": GATE_ALWAYS_ON_NOTES,
        "auth_required": GATES_API_REQUIRE_TOKEN,
    }


def handle_gates_api_get():
    return _json_response(gates_state_payload())


def _gates_token_ok(req, body):
    """Reads are open (like the other pages); writes need the token unless disabled."""
    if not GATES_API_REQUIRE_TOKEN:
        return True
    token = req.headers.get("X-Gate-Token") or (body or {}).get("token") or req.args.get("token")
    return isinstance(token, str) and token.strip() == GCP_SECRET_TOKEN.strip()


def handle_gates_api_post(req):
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "請求內容不是 JSON 物件"}, 400)
    if not _gates_token_ok(req, body):
        return _json_response({"status": "error", "message": "Unauthorized token"}, 403)

    op = body.get("op")
    try:
        if op == "mode":
            mode = body.get("mode")
            if mode not in GATE_MODES:
                return _json_response({"status": "error", "message": f"未知模式：{mode}"}, 400)
            label, new_bypass = GATE_MODES[mode]
            write_gate_bypass(new_bypass, label)
        elif op == "solo":                               # 逐關測試：一次只略過一個關卡
            key, step = body.get("key"), body.get("step")
            if key is not None:
                if key not in GATE_SWITCH_KEYS:
                    return _json_response({"status": "error", "message": f"未知的關卡代號：{key}"}, 400)
                new_bypass = frozenset({key})
            elif step in ("start", "next", "prev", "stop"):
                new_bypass = next_solo_bypass(read_gate_bypass(), step)
            else:
                return _json_response({"status": "error", "message": "solo 需要 key，或 step=start/next/prev/stop"}, 400)
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
        elif op == "save":
            requested = body.get("bypass")
            if not isinstance(requested, list) or not all(isinstance(k, str) for k in requested):
                return _json_response({"status": "error", "message": "bypass 必須是關卡代號字串陣列"}, 400)
            unknown = sorted(set(requested) - set(GATE_SWITCH_KEYS))
            if unknown:
                return _json_response({"status": "error", "message": f"未知的關卡代號：{'、'.join(unknown)}"}, 400)
            new_bypass = frozenset(requested)
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
        else:
            return _json_response({"status": "error", "message": "op 必須是 'mode'、'solo' 或 'save'"}, 400)
    except StorageError as exc:
        print(f"⚠️ [關卡開關 API 寫入失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "儲存失敗，設定未改變，請查看 Cloud Logging。"}, 500)

    names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in new_bypass) or "無"
    log_decision(f"🎛️ [關卡開關·獨立頁] {detect_gate_mode(new_bypass)}｜略過：{names}", key="admin")
    return _json_response(gates_state_payload("設定已儲存，下一根 M1 K 線生效。"))


def serve_gates_app():
    """Serves the standalone page from the deployed source, so one file covers both uses."""
    try:
        with open(GATES_APP_FILE, encoding="utf-8") as handle:
            return handle.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except OSError as exc:
        print(f"⚠️ [關卡開關獨立頁讀取失敗 → 改用內建頁面] {exc}", flush=True)
        return build_gates_page(None)


def build_gates_page(msg):
    bypass = read_gate_bypass()
    doc = read_gate_switch_doc()
    state = read_gate_state()
    status = gate_status(state)
    summary_class, summary_text = gate_summary(state)
    mode_label = detect_gate_mode(bypass)

    banners = {
        "saved": ("#d4edda", "#155724", "✅ 設定已儲存，下一根 M1 K 線生效。"),
        "mode": ("#d4edda", "#155724", "✅ 模式已套用，下一根 M1 K 線生效。"),
        "test": ("#e7f1ff", "#084298", "🧪 逐關測試已更新，下一根 M1 K 線生效。"),
        "error": ("#f8d7da", "#721c24", "❌ 儲存失敗，設定未改變，請查看 Cloud Logging。"),
    }
    banner = ""
    if msg in banners:
        bg, fg, text = banners[msg]
        banner = f"<div class='banner' style='background:{bg}; color:{fg};'>{text}</div>"

    rows = ""
    for key, title, normal, skipped, risk in GATE_SWITCH_DEFS:
        is_on = key not in bypass
        extra = f"<div class='gate-text'>{esc(_risk_cap_preview())}</div>" if key == "risk_cap" else ""
        rows += (
            f"<div class='gate-row {'' if is_on else 'off'}'>"
            f"<label class='switch'><input type='checkbox' name='on_{key}' value='1' {'checked' if is_on else ''}>"
            f"<span class='slider'></span></label>"
            f"<div class='gate-body'><div class='gate-title'>{esc(title)}"
            f"<span class='gate-state {'on' if is_on else 'off'}'>{'✅ 檢查中' if is_on else '⚠️ 已略過'}</span></div>"
            f"<div class='gate-text'><b>啟用：</b>{esc(normal)}</div>"
            f"<div class='gate-text'><b>略過：</b>{esc(skipped)}</div>"
            f"<div class='gate-risk'>{esc(risk)}</div>{extra}</div></div>"
        )

    def mode_card(key, color, desc, confirm_text):
        label = GATE_MODES[key][0]
        onsubmit = f" onsubmit=\"return confirm('{confirm_text}');\"" if confirm_text else ""
        return (f"<form method='POST' action='?view=gates'{onsubmit}>"
                f"<input type='hidden' name='op' value='mode'><input type='hidden' name='mode' value='{key}'>"
                f"<button type='submit' class='mode-btn' style='background:{color};'>{label}</button>"
                f"<div class='mode-desc'>{desc}</div></form>")

    relaxed_names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in GATE_MODES["relaxed"][1])
    aggressive_extra = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS
                                 if k in GATE_MODES["aggressive"][1] and k not in GATE_MODES["relaxed"][1])
    modes = (
        "<div class='mode-grid'>"
        + mode_card("relaxed", "#d97706", f"略過：{esc(relaxed_names)}。", "確認套用寬鬆模式？")
        + mode_card("aggressive", "#dc3545", f"寬鬆模式再加上略過：{esc(aggressive_extra)}。",
                    "激進模式會同時略過倉位上限、新聞風控與 AI 覆核，實盤風險很高。確認套用？")
        + mode_card("strict", "#198754", "全部關卡恢復檢查（預設）。", "")
        + "</div>"
    )

    updated = esc(doc.get("updated_utc") or "—")
    always_on = "".join(f"<li>{esc(note)}</li>" for note in GATE_ALWAYS_ON_NOTES)

    test = solo_test_status(bypass)
    test_line = (f"目前測試第 {test['index']} / {test['total']} 關：{esc(test['title'])}"
                 f"（其餘 {test['total'] - 1} 關維持檢查）"
                 if test["active"] else "目前不在逐關測試（略過的關卡不是剛好一個）")

    def solo_form(fields, label, color, confirm=""):
        hidden = "".join(f"<input type='hidden' name='{k}' value='{v}'>" for k, v in fields.items())
        onsubmit = f" onsubmit=\"return confirm('{confirm}');\"" if confirm else ""
        return (f"<form method='POST' action='?view=gates' style='display:inline-block; margin:4px;'{onsubmit}>"
                f"<input type='hidden' name='op' value='solo'>{hidden}"
                f"<button type='submit' class='mode-btn' style='background:{color}; width:auto; padding:12px 18px; "
                f"font-size:14px;'>{label}</button></form>")

    first_name = esc(GATE_SWITCH_NAMES[GATE_SWITCH_KEYS[0]])
    test_buttons = (
        solo_form({"step": "start"}, f"▶️ 開始測試（只略過「{first_name}」）", "#0f62fe",
                  f"開始逐關測試：只略過「{first_name}」，其餘關卡維持檢查。確認？")
        + solo_form({"step": "prev"}, "⬅️ 上一關", "#6c757d")
        + solo_form({"step": "next"}, "➡️ 下一關", "#0f62fe")
        + solo_form({"step": "stop"}, "⏹️ 結束測試（全部恢復檢查）", "#198754")
    )
    jump_options = "".join(
        f"<option value='{key}'{' selected' if test['key'] == key else ''}>{i}. {esc(GATE_SWITCH_NAMES[key])}</option>"
        for i, key in enumerate(GATE_SWITCH_KEYS, 1))
    test_jump = (
        "<form method='POST' action='?view=gates' style='display:inline-block; margin:4px;' "
        "onsubmit=\"return confirm('直接跳到這一關？該關卡會被略過，其餘維持檢查。');\">"
        "<input type='hidden' name='op' value='solo'>"
        f"<select name='key' style='padding:11px 12px; border:1px solid #dee2e6; border-radius:8px; font-size:14px;'>{jump_options}</select> "
        "<button type='submit' class='mode-btn' style='background:#d97706; width:auto; padding:12px 18px; font-size:14px;'>跳到這一關</button></form>"
    )
    body = f"""
    <div class='nav'><h1 class='page-title'>🎛️ 關卡開關頁面</h1>
      <div><a href='?view=welcome'>🏠 首頁</a><a href='?view=gates_app'>🆕 獨立版</a><a href='?view=dashboard'>⚙️ 控制台</a><a href='?view=info'>📄 投資人日誌</a></div></div>
    {banner}
    <div class='section' style='text-align:center;'>
      <div class='muted' style='font-weight:600;'>目前模式</div>
      <div style='font-size:24px; font-weight:800; margin:8px 0;'>{esc(mode_label)}</div>
      <div class='muted' style='font-size:13px;'>略過 {len(bypass)} / {len(GATE_SWITCH_KEYS)} 個關卡｜最後更新：{updated} UTC</div>
      <div style='margin-top:12px; font-size:14px;'>電閘：<b>{status}</b>｜<span class='{summary_class}'>{esc(summary_text)}</span></div>
      <div class='muted' style='font-size:12px; margin-top:6px;'>硬鎖（TARGET_HIT、RISK_HIT、緊急鎖死）不受本頁影響，請到控制台解除。</div>
    </div>

    <div class='section'><h2>⚡ 一鍵模式</h2>{modes}</div>

    <div class='section'><h2>🧪 逐關測試模式</h2>
      <p class='muted' style='font-size:12px;'>從「全部檢查中」出發，一次只略過一個關卡、其餘維持檢查，逐關往下走，
      用來確認是哪一關擋住訊號。走到最後一關後會繞回第一關。</p>
      <div class='gate-row' style='border-left-color:#0f62fe;'><div class='gate-body'>
        <div class='gate-title'>{test_line}</div>
        <div class='gate-risk'>⚠️ 這是實盤：被略過的那一關在測試期間不會保護你，請測完按「結束測試」。</div>
      </div></div>
      <div>{test_buttons}</div>
      <div style='margin-top:8px;'>{test_jump}</div>
    </div>

    <div class='section'><h2>🔧 逐關調整</h2>
      <p class='muted' style='font-size:12px;'>綠色＝該關卡照常檢查；橙色＝略過。調整後按最下方「儲存」。</p>
      <form method='POST' action='?view=gates'>
        <input type='hidden' name='op' value='save'>
        {rows}
        <div class='save-bar'><button type='submit' class='mode-btn' style='background:#0f62fe;'>💾 儲存逐關設定</button></div>
      </form>
    </div>

    <div class='section'><h2>🔒 本頁無法略過的檢查</h2>
      <div class='gate-text'>以下是資料或安全前提，略過後系統無法正確計算方向、止損或持倉，因此不提供開關：</div>
      <ul class='gate-text'>{always_on}</ul>
    </div>
    """
    return html_page("關卡開關頁面 - 智能諸葛亮", body, head_extra=GATES_CSS)


def handle_gates_post(req):
    form = req.form
    op = form.get("op")
    try:
        if op == "mode" and form.get("mode") in GATE_MODES:
            label, keys = GATE_MODES[form.get("mode")]
            write_gate_bypass(keys, label)
            new_bypass, msg = keys, "mode"
        elif op == "solo":                               # 逐關測試：一次只略過一個關卡
            key, step = form.get("key"), form.get("step")
            if key in GATE_SWITCH_KEYS:
                new_bypass = frozenset({key})
            elif step in ("start", "next", "prev", "stop"):
                new_bypass = next_solo_bypass(read_gate_bypass(), step)
            else:
                return redirect("?view=gates")
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
            msg = "test"
        elif op == "save":
            new_bypass = frozenset(k for k in GATE_SWITCH_KEYS if form.get(f"on_{k}") != "1")
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
            msg = "saved"
        else:
            return redirect("?view=gates")
    except StorageError as exc:
        print(f"⚠️ [關卡開關寫入失敗] {exc}", flush=True)
        return redirect("?view=gates&msg=error")

    names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in new_bypass) or "無"
    log_decision(f"🎛️ [關卡開關] {detect_gate_mode(new_bypass)}｜略過：{names}", key="admin")
    return redirect(f"?view=gates&msg={msg}")


def handle_get(req):
    view = req.args.get("view", "welcome")
    action = req.args.get("action")
    if view == "gates" and req.args.get("format") == "json":     # standalone gates.html reads state
        return handle_gates_api_get()
    if view == "gates_app":                                      # standalone gates.html, served here
        return serve_gates_app()
    if view == "info":
        return build_info_page()
    if view == "gates":
        return build_gates_page(req.args.get("msg"))
    if view == "dashboard":
        if action in ("auto", "open"):          # "open" kept for old bookmarks  [R29]
            try:
                clear_hard_lock()
                log_decision("🟢 [管理員] 解除硬鎖，恢復自動模式。", key="gate")
                return redirect("?view=dashboard&msg=auto")
            except StorageError as exc:
                print(f"⚠️ [電閘寫入失敗] {exc}", flush=True)
                return redirect("?view=dashboard&msg=error")
        if action == "lock":
            try:
                set_hard_lock("管理員緊急鎖死", None)
                log_decision("🔒 [管理員] 啟動緊急硬鎖。", key="gate")
                return redirect("?view=dashboard&msg=locked")
            except StorageError as exc:
                print(f"⚠️ [電閘寫入失敗] {exc}", flush=True)
                return redirect("?view=dashboard&msg=error")
        return build_dashboard_page(req.args.get("msg"))
    return render_welcome_page()


# =============================================================================
# 📈 Entry point
# =============================================================================
def log_event(message, severity="INFO", **fields):
    """One structured log line. Cloud Run turns JSON on stdout into jsonPayload
    with a real severity, so it is visible under the default "Info" filter."""
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False, default=str), flush=True)


def _payload_summary(payload):
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    return {
        "action": payload.get("action"),
        "status_signal": payload.get("status"),
        "symbol": payload.get("symbol"),
        "equity": payload.get("equity"),
        "buy_lots": payload.get("buy_lots"),
        "sell_lots": payload.get("sell_lots"),
        "m1_time": m1.get("time"),
        "is_new_bar": m1.get("is_new_bar"),
        "ticket": payload.get("ticket"),
        "profit": payload.get("profit"),
    }


def _response_info(response):
    body, code = (response[0], response[1]) if isinstance(response, tuple) else (response, 200)
    if hasattr(body, "get_json"):
        body = body.get_json(silent=True)
    return code, (body or {}).get("status") if isinstance(body, dict) else None


def _dispatch_post(payload):
    action = payload.get("action")
    if action == "trade_result":
        return handle_trade_result(payload)

    token = payload.get("token")
    token_ok = isinstance(token, str) and token.strip() == GCP_SECRET_TOKEN.strip()

    if action in ("check_gate", "close_gate") or "net_lots" in payload or "equity" in payload:
        # MT5 heartbeats carrying equity are trusted, same as v11.
        return handle_heartbeat(payload, can_trade=("equity" in payload) or token_ok)

    if not token_ok:
        return jsonify({"status": "error", "message": "Unauthorized token"}), 403
    if action == "update_levels":
        return jsonify({"status": "success", "message": "TV levels received but intentionally ignored."}), 200
    return jsonify({"status": "ignored", "message": "No handler for this payload"}), 200


@functions_framework.http
def receive_tradingview_signal(request):
    if request.method == "OPTIONS":                  # CORS preflight from the standalone page
        return cors_preflight()
    if request.method == "GET":
        return handle_get(request)
    if request.args.get("view") == "gates":          # posts from the gate switch pages
        if request.args.get("format") == "json" or (request.content_type or "").startswith("application/json"):
            return handle_gates_api_post(request)
        return handle_gates_post(request)

    payload = parse_payload(request)
    if payload is None:
        log_event("📥 [收到封包] 無法解碼的請求內容", severity="WARNING", component="webhook")
        return jsonify({"status": "error", "message": "Invalid bytes coding"}), 400

    summary = _payload_summary(payload)
    log_event(f"📥 [收到封包] action={summary['action']} status={summary['status_signal']} "
              f"buy={summary['buy_lots']} sell={summary['sell_lots']} m1={summary['m1_time']}",
              component="webhook", direction="in", **summary)
    webhook_log_session.save_payload(payload)

    started = now_ts()
    try:
        response = _dispatch_post(payload)
    except Exception as exc:
        log_event(f"💥 [處理異常] {type(exc).__name__}: {exc}", severity="ERROR", component="webhook",
                  action=summary["action"])
        raise
    code, status = _response_info(response)
    log_event(f"📤 [回應] HTTP {code} {status} ({int((now_ts() - started) * 1000)} ms)",
              severity="INFO" if code < 500 else "ERROR", component="webhook", direction="out",
              action=summary["action"], http_status=code, result=status)
    return response
