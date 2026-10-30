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


def ladder(*, principal_hkd, own_equity, peak_equity, daily_pnl_hkd, margin_level, night, cfg=config):
    """風控階梯（龍飛陣做法，冇硬鎖）。回傳
    {"pause": bool, "stop": bool, "pause_kind": "daily"|"margin"|None, "reasons": [...], "alerts": {key: text}}。
    pause／stop 由日蝕（只計自己嘅單）同保證金水平決定；alerts 只發 Telegram，唔影響交易。缺數據嗰項跳過。"""
    mult = cfg.NIGHT_MULT if night else 1.0
    out = {"pause": False, "stop": False, "pause_kind": None, "reasons": [], "alerts": {}, "cum_loss": False}
    if principal_hkd and principal_hkd > 0:
        if daily_pnl_hkd is not None:
            pct = daily_pnl_hkd / principal_hkd * 100
            if pct <= -cfg.DAILY_LOSS_STOP_PCT * mult:
                out.update(stop=True, pause=True, pause_kind="daily")
                out["reasons"].append(f"當日虧損 {pct:.1f}% ≤ −{cfg.DAILY_LOSS_STOP_PCT * mult:g}% → 平倉停機（換日自動重開）")
            elif pct <= -cfg.DAILY_LOSS_PAUSE_PCT * mult:
                out.update(pause=True, pause_kind="daily")
                out["reasons"].append(f"當日虧損 {pct:.1f}% ≤ −{cfg.DAILY_LOSS_PAUSE_PCT * mult:g}% → 停開新倉（換日自動重開）")
        out["cum_loss"] = bool(own_equity is not None and own_equity <= principal_hkd * (1 - cfg.CUM_LOSS_PAUSE_PCT / 100))
        if out["cum_loss"]:
            out["cum_loss_text"] = f"累計虧損達本金 {100 - own_equity / principal_hkd * 100:.0f}% ≥ {cfg.CUM_LOSS_PAUSE_PCT:g}% → 停開新倉（換日自動重開）"
    if own_equity is not None and peak_equity and peak_equity > 0:
        dd = max(0.0, (peak_equity - own_equity) / peak_equity * 100)
        for i, line in enumerate(cfg.DD_ALERT_PCTS):
            if dd >= line:
                out["alerts"][f"dd{i + 1}"] = f"高水位回撤 {dd:.1f}% ≥ {line:g}%"
    if margin_level is not None and margin_level > 0:
        if margin_level < cfg.MARGIN_PAUSE_PCT * mult and not out["pause"]:
            out.update(pause=True, pause_kind="margin")
            out["reasons"].append(f"戶口保證金水平 {margin_level:.0f}% < {cfg.MARGIN_PAUSE_PCT * mult:g}% → 停開新倉（回升自動解）")
        for i, line in enumerate(cfg.MARGIN_ALERT_PCTS):
            if margin_level < line:
                out["alerts"][f"margin{i + 1}"] = f"戶口保證金水平 {margin_level:.0f}% < {line:g}%（戶口級提示，天覆陣唔平倉）"
    return out


def chase_block(m1, side, price, cfg=config):
    """[R351] MILESTONES M1 硬規則：開倉前 CHASE_WINDOW_MIN 根 M1 內，有一個高位之後（嚴格喺後面嗰根）出現跌 ≥ CHASE_MOVE_USD 嘅低位，
    而決策價高過該低位 ≥ CHASE_BACK_USD → 擋 SELL（急跌後反抽沽）；BUY 對稱（急升後回落買）。回傳擋嘅原因或 None。"""
    if not getattr(cfg, "CHASE_BLOCK", False) or not m1 or price is None:
        return None
    t0 = m1[-1]["time"] - (cfg.CHASE_WINDOW_MIN - 1) * 60
    ext, nd = None, getattr(cfg, "PRICE_DIGITS", 2)
    for b in (x for x in m1 if x["time"] >= t0):
        if side < 0:
            if ext is not None and ext - b["low"] >= cfg.CHASE_MOVE_USD and price - b["low"] >= cfg.CHASE_BACK_USD:
                return (f"M1 硬規則：{cfg.CHASE_WINDOW_MIN} 分鐘內由 {ext:.{nd}f} 急跌到 {b['low']:.{nd}f}（{ext - b['low']:.{nd}f}），"
                        f"決策價 {price:.{nd}f} 已反抽 {price - b['low']:.{nd}f}，唔准反抽沽")
            ext = b["high"] if ext is None else max(ext, b["high"])
        else:
            if ext is not None and b["high"] - ext >= cfg.CHASE_MOVE_USD and b["high"] - price >= cfg.CHASE_BACK_USD:
                return (f"M1 硬規則：{cfg.CHASE_WINDOW_MIN} 分鐘內由 {ext:.{nd}f} 急升到 {b['high']:.{nd}f}（{b['high'] - ext:.{nd}f}），"
                        f"決策價 {price:.{nd}f} 已回落 {b['high'] - price:.{nd}f}，唔准回落買")
            ext = b["low"] if ext is None else min(ext, b["low"])
    return None


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
        nd = getattr(cfg, "PRICE_DIGITS", 2)
        if dist < cfg.MIN_SL_USD:
            stop = round(last - side * cfg.MIN_SL_USD, nd)
        if dist > cfg.MAX_SL_USD:
            return "HOLD", None, None, f"止損距離 {dist / cfg.PIP:.1f} pip 超過上限 {cfg.MAX_SL_PIPS:g} pip"
        if target is not None and (target - last) * side <= 0:
            target = None                                   # 止賺錯邊：唔送，唔因此拒絕
        return action, round(stop, nd), (round(target, nd) if target is not None else None), None

    if action == "CLOSE":
        if position is None:
            return "HOLD", None, None, "冇倉可平"
        return "CLOSE", None, None, None

    if action == "UPDATE_STOP":
        if position is None:
            return "HOLD", None, None, "冇倉可改"
        nd = getattr(cfg, "PRICE_DIGITS", 2)                     # 10-23 修：之前寫死 round(…, 2)，EURUSD 1.1218→1.12、SL＝TP，EA 全部 invalid stops
        side = position["side"]
        if stop is None:
            return "HOLD", None, None, "UPDATE_STOP 冇止損價"
        if (last - stop) * side <= 0:
            return "HOLD", None, None, "新止損喺錯邊（已過現價）"
        min_dist = getattr(cfg, "MODIFY_MIN_DIST_USD", cfg.MIN_SL_USD)
        if (last - stop) * side < min_dist:                          # [R340] 太貼現價：夾到最小距離；夾完唔比現止損緊就唔發（EA 會拒 invalid stops，白燒一次指令）
            asked = (last - stop) * side
            stop = round(last - side * min_dist, nd)
            cur = position.get("stop")
            if cur is not None and (stop - cur) * side <= 0:
                return "HOLD", None, None, f"新止損離價 {asked / cfg.PIP:.1f} pip < 最小 {min_dist / cfg.PIP:.1f} pip，夾返都唔比現止損緊，唔改"
        cur = position.get("stop")
        if getattr(cfg, "STOP_TIGHTEN_ONLY", False) and cur is not None and (stop - cur) * side <= 0:   # [R354] 只准收緊：放鬆／冇變一律唔改
            return "HOLD", None, None, (f"新止損 {stop:.{nd}f} 唔比現止損 {cur:.{nd}f} 緊（只准收緊，唔准放鬆）" if (stop - cur) * side < 0
                                        else "新止損同現止損一樣，唔改")
        if target is not None and (target - last) * side <= 0:
            target = position.get("target")
        return "UPDATE_STOP", round(stop, nd), (round(target, nd) if target is not None else position.get("target")), None

    return "HOLD", None, None, None


def lots_cap(follow=False):
    """[R349] 升級上限：已達成里程碑數（XAU_LOTS_MILESTONE／SIG_FOLLOW_LOTS_MILESTONE）→ XAU_LOTS_MILESTONE_CAPS；0＝起點；唔超硬上限。"""
    import lots_ladder
    if follow:
        return lots_ladder.cap_for(round(config.FOLLOW_LOTS, 2), config.LOTS_MILESTONE_CAPS, config.FOLLOW_LOTS_MILESTONE, round(config.FOLLOW_MAX_LOTS, 2))
    return lots_ladder.cap_for(round(config.LOTS, 2), config.LOTS_MILESTONE_CAPS, config.LOTS_MILESTONE, round(config.MAX_LOTS, 2))


def lots(state=None):
    """[R346] 手數：階梯開就用 state 嘅級數（起點 XAU_LOTS，夾 XAU_LOTS_MIN–min(XAU_MAX_LOTS, 里程碑上限)）；關＝固定 XAU_LOTS。"""
    import lots_ladder
    return max(0.01, lots_ladder.current(state, start=round(config.LOTS, 2), lo=round(config.LOTS_MIN, 2), hi=round(config.MAX_LOTS, 2), on=config.LOTS_LADDER, cap=lots_cap()))


def follow_lots(state=None):
    """[R346] 跟單（932）手數，自己一個級數（[R349] 自己嘅里程碑上限）。"""
    import lots_ladder
    return max(0.01, lots_ladder.current(state, start=round(config.FOLLOW_LOTS, 2), lo=round(config.FOLLOW_LOTS_MIN, 2), hi=round(config.FOLLOW_MAX_LOTS, 2), on=config.FOLLOW_LOTS_LADDER, cap=lots_cap(follow=True)))


def lots_ladder_kw(follow=False):
    """[R346] 畀 lots_ladder.step／live_close 用嘅參數（[R349] 含 cap）。"""
    if follow:
        return dict(start=round(config.FOLLOW_LOTS, 2), lo=round(config.FOLLOW_LOTS_MIN, 2), hi=round(config.FOLLOW_MAX_LOTS, 2), step=round(config.LOTS_STEP, 2), on=config.FOLLOW_LOTS_LADDER, cap=lots_cap(follow=True))
    return dict(start=round(config.LOTS, 2), lo=round(config.LOTS_MIN, 2), hi=round(config.MAX_LOTS, 2), step=round(config.LOTS_STEP, 2), on=config.LOTS_LADDER, cap=lots_cap())
