"""純邏輯：交易時段、交易日、合約選擇、止蝕檢查、AI 決策驗證。冇 I/O，方便測試。"""
import re
from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo

from markets import HKT, session_status, trading_day_key  # noqa: F401  （時段規則喺 markets.py，按產品市場）


def now_hkt() -> datetime:
    return datetime.now(HKT)


CONTRACT_RE = re.compile(r"^(HK|US)\.([A-Z]+)(\d{2})(\d{2})$")   # HK.HSI2610、US.MES2612


def pick_front_month(contracts, product: str, today: date, roll_days: int = 0):
    """contracts: [(code, last_trade_date)]。揀即月；距離最後交易日唔夠 roll_days 日（港期 0＝最後交易日當日）就轉下月。"""
    cands = []
    for code, ltd in contracts:
        m = CONTRACT_RE.match(code)
        if not m or m.group(2) != product or ltd is None:
            continue
        if ltd > today + timedelta(days=roll_days):
            cands.append((ltd, code))
    if not cands:
        return None
    return sorted(cands)[0][1]


def stop_hit(side: int, price: float, stop: float | None) -> bool:
    if stop is None or price is None:
        return False
    return price <= stop if side > 0 else price >= stop


def target_hit(side: int, price: float, target: float | None) -> bool:
    if target is None or price is None:
        return False
    return price >= target if side > 0 else price <= target


VALID_ACTIONS = {"HOLD", "OPEN_LONG", "OPEN_SHORT", "CLOSE", "UPDATE_STOP"}


def validate_decision(d: dict, *, position: int, entry: float | None, last: float,
                      cfg, remaining_loss: float, can_open: bool, trades_today: int, qty: int = 1):
    """將 AI 嘅決定過一次硬性規則。回傳 (最終動作, stop, target, 被拒原因或 None)。"""
    action = str(d.get("action", "HOLD")).upper()
    if action not in VALID_ACTIONS:
        return "HOLD", None, None, f"未知動作 {action}"

    stop = d.get("stop_price")
    target = d.get("target_price")
    stop = float(stop) if stop not in (None, "") else None
    target = float(target) if target not in (None, "") else None

    if action in ("OPEN_LONG", "OPEN_SHORT"):
        side = 1 if action == "OPEN_LONG" else -1
        if position != 0:
            return "HOLD", None, None, "已有倉位，唔可以再開（最多 1 張，要先 CLOSE）"
        if not can_open:
            return "HOLD", None, None, "而家唔准開新倉（時段/暫停/上限）"
        if cfg.max_trades_per_day and trades_today >= cfg.max_trades_per_day:
            return "HOLD", None, None, "今日開倉次數已到上限"
        if stop is None:
            return "HOLD", None, None, "冇止蝕，拒絕開倉"
        dist = (last - stop) * side
        if dist <= 0:
            return "HOLD", None, None, "止蝕位喺錯邊"
        if cfg.min_stop_points and dist < cfg.min_stop_points:
            stop = last - side * cfg.min_stop_points
        if cfg.max_stop_points and dist > cfg.max_stop_points:
            stop = last - side * cfg.max_stop_points
        risk_hkd = (abs(last - stop) + cfg.slippage_points * 2) * cfg.point_value * qty   # qty：期貨張數／ETF 股數
        if risk_hkd > remaining_loss:
            return "HOLD", None, None, f"止蝕風險 HK${risk_hkd:.0f} 超過今日剩餘額度 HK${remaining_loss:.0f}"
        if target is not None and (target - last) * side <= 0:
            target = None
        return action, round(stop), (round(target) if target else None), None

    if action == "CLOSE":
        if position == 0:
            return "HOLD", None, None, "冇倉位可平"
        return "CLOSE", None, None, None

    if action == "UPDATE_STOP":
        if position == 0 or stop is None:
            return "HOLD", None, None, "冇倉位或冇新止蝕"
        side = 1 if position > 0 else -1
        if (last - stop) * side <= 0:
            return "CLOSE", None, None, "新止蝕已被穿，即平"
        if cfg.max_stop_points and entry is not None and (entry - stop) * side > cfg.max_stop_points:
            stop = entry - side * cfg.max_stop_points
        return "UPDATE_STOP", round(stop), (round(target) if target else None), None

    return "HOLD", None, None, None
