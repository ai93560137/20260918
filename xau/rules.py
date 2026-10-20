"""純邏輯：AI 決定過硬性規則、止損止賺觸發、最長持倉。冇 I/O，方便測試。沿用龍飛陣 rules.py 嘅做法，單位改成美元價位。"""
import config

VALID_ACTIONS = {"HOLD", "OPEN_LONG", "OPEN_SHORT", "CLOSE", "UPDATE_STOP"}


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def stop_hit(side, low, high, stop):
    """用該根 K 線嘅高低位判斷（紙上模擬保守：先當止損）。"""
    if stop is None:
        return False
    return low <= stop if side > 0 else high >= stop


def target_hit(side, low, high, target):
    if target is None:
        return False
    return high >= target if side > 0 else low <= target


def hold_expired(opened_ts, now_ts, max_hold_min=None):
    max_hold_min = config.MAX_HOLD_MIN if max_hold_min is None else max_hold_min
    return bool(max_hold_min) and now_ts - opened_ts >= max_hold_min * 60


def validate_decision(d, *, position, last, gate_open, trades_today, cfg=config):
    """position: None 或 {side: ±1, entry, stop, target, ...}。
    回傳 (最終動作, stop, target, 被拒原因或 None)。唔合規一律變 HOLD。"""
    action = str(d.get("action", "HOLD")).upper()
    if action not in VALID_ACTIONS:
        return "HOLD", None, None, f"未知動作 {action}"
    stop, target = _num(d.get("stop_price")), _num(d.get("target_price"))
    conf = _num(d.get("confidence")) or 0.0

    if action in ("OPEN_LONG", "OPEN_SHORT"):
        side = 1 if action == "OPEN_LONG" else -1
        if position is not None:
            return "HOLD", None, None, "已有倉位，唔可以再開（最多 1 張，要先 CLOSE）"
        if not gate_open:
            return "HOLD", None, None, "電閘 LOCK，唔准開新倉"
        if cfg.LONG_ONLY and side < 0:
            return "HOLD", None, None, "XAU_LONG_ONLY=1，唔做空"
        if cfg.MAX_TRADES_PER_DAY and trades_today >= cfg.MAX_TRADES_PER_DAY:
            return "HOLD", None, None, "今日開倉次數已到上限"
        if conf < cfg.MIN_CONFIDENCE:
            return "HOLD", None, None, f"信心 {conf:.2f} 低過門檻 {cfg.MIN_CONFIDENCE:.2f}"
        if stop is None:
            return "HOLD", None, None, "冇止損，拒絕開倉"
        dist = (last - stop) * side
        if dist <= 0:
            return "HOLD", None, None, "止損喺錯邊"
        if dist < cfg.MIN_SL_USD:
            stop = round(last - side * cfg.MIN_SL_USD, 2)
        if dist > cfg.MAX_SL_USD:
            return "HOLD", None, None, f"止損距離 {dist:.2f} 超過上限 {cfg.MAX_SL_USD:g} 美元"
        if target is not None and (target - last) * side <= 0:
            target = None                                   # 止賺錯邊：唔送，唔因此拒絕
        return action, round(stop, 2), (round(target, 2) if target is not None else None), None

    if action == "CLOSE":
        if position is None:
            return "HOLD", None, None, "冇倉可平"
        return "CLOSE", None, None, None

    if action == "UPDATE_STOP":
        if position is None:
            return "HOLD", None, None, "冇倉可改"
        side = position["side"]
        if stop is None:
            return "HOLD", None, None, "UPDATE_STOP 冇止損價"
        if (last - stop) * side <= 0:
            return "HOLD", None, None, "新止損喺錯邊（已過現價）"
        if target is not None and (target - last) * side <= 0:
            target = position.get("target")
        return "UPDATE_STOP", round(stop, 2), (round(target, 2) if target is not None else position.get("target")), None

    return "HOLD", None, None, None


def lots():
    return max(0.01, min(round(config.LOTS, 2), round(config.MAX_LOTS, 2)))
