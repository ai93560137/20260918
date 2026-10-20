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


def ladder(*, principal_hkd, equity_net, peak_equity, daily_pnl_hkd, margin_level, night, cfg=config):
    """風控階梯（RISK_LADDER §6c 草稿）。回傳 {"level": "A"|"B"|"C"|"D", "reasons": [...], "can_open": bool, "halve": bool, "flatten": bool}。
    principal_hkd 冇設 → 日蝕／硬止損唔計（只計回撤同保證金）；缺數據嗰項跳過（唔會因為冇數據就 Ⓓ）。"""
    level, reasons = "A", []
    mult = cfg.NIGHT_MULT if night else 1.0

    def bump(new, why):
        nonlocal level
        reasons.append(why)
        if "ABCD".index(new) > "ABCD".index(level):
            level = new

    if principal_hkd and principal_hkd > 0:
        if daily_pnl_hkd is not None:
            pct = daily_pnl_hkd / principal_hkd * 100
            if pct <= -cfg.DAILY_LOSS_D_PCT * mult:
                bump("D", f"當日虧損 {pct:.1f}% ≤ −{cfg.DAILY_LOSS_D_PCT * mult:g}%")
            elif pct <= -cfg.DAILY_LOSS_B_PCT * mult:
                bump("B", f"當日虧損 {pct:.1f}% ≤ −{cfg.DAILY_LOSS_B_PCT * mult:g}%")
        if equity_net is not None and equity_net <= principal_hkd * (1 - cfg.HARD_STOP_PCT / 100):
            bump("D", f"淨值－信用跌至本金 {equity_net / principal_hkd * 100:.0f}%（硬止損 −{cfg.HARD_STOP_PCT:g}%）")
    if equity_net is not None and peak_equity and peak_equity > 0:
        dd = max(0.0, (peak_equity - equity_net) / peak_equity * 100)
        if dd >= cfg.DD_D_PCT:
            bump("D", f"高水位回撤 {dd:.1f}% ≥ {cfg.DD_D_PCT:g}%")
        elif dd >= cfg.DD_B_PCT * mult:
            bump("B", f"高水位回撤 {dd:.1f}% ≥ {cfg.DD_B_PCT * mult:g}%")
    if margin_level is not None and margin_level > 0:
        if margin_level < cfg.MARGIN_D_PCT:
            bump("D", f"保證金水平 {margin_level:.0f}% < {cfg.MARGIN_D_PCT:g}%")
        elif margin_level < cfg.MARGIN_C_PCT * mult:
            bump("C", f"保證金水平 {margin_level:.0f}% < {cfg.MARGIN_C_PCT * mult:g}%")
        elif margin_level < cfg.MARGIN_B_PCT * mult:
            bump("B", f"保證金水平 {margin_level:.0f}% < {cfg.MARGIN_B_PCT * mult:g}%")
    return {"level": level, "reasons": reasons, "can_open": level == "A",
            "halve": level == "C", "flatten": level == "D"}


def validate_decision(d, *, position, last, can_open, trades_today, cfg=config, block_reason=None):
    """position: None 或 {side: ±1, entry, stop, target, ...}。can_open=False（階梯 Ⓑ 以上／暫停開倉／停機）就唔准開新倉。
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
        if not can_open:
            return "HOLD", None, None, block_reason or "而家唔准開新倉（風控階梯／暫停／停機）"
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
