"""慳成本 H（使用者 10-23 揀「穩陣＋H」；xau/COST_PLAN.md §6）：有倉時由程式按教學第 1／4 條計止損，
Opus 只喺 (a) 新 M15 收盤 (b) 浮盈首次到 1R (c) 價格入到離 SL／TP 0.5×M15 ATR 內 (d) 距上次問 ≥ HOLD_RULES_ASK_MIN 分鐘 先問。
模式 XAU_HOLD_RULES：off｜shadow（預設：只記「規則會點移」同 Opus 實際點移，唔改行為）｜on。
硬規則：止損只准收緊（唔可以移遠）；唔收到 0.5×ATR 之內；未到 1R 唔郁（教學第 1 條）。純函數，冇 I/O。"""
import config

BE_R = 1.0            # 浮盈 ≥1R → 保本（教學第 1 條）
MIN_ATR_MULT = 0.5    # 唔收到 0.5×M15 ATR 之內（教學第 4 條）
TRAIL_ATR_MULT = 1.0  # 跟 1×M15 ATR 或擺動點，取較遠（教學第 4 條）
SWING_BUF_ATR = 0.1   # 擺動點外少少
MIN_STEP_ATR = 0.1    # 細過 0.1×ATR 嘅收緊唔郁（免每分鐘 modify）


def mode():
    m = (getattr(config, "HOLD_RULES", "shadow") or "shadow").lower()
    return m if m in ("off", "shadow", "on") else "shadow"


def strict_swings(bars, side, w=5):
    """擺動低（多）／高（空）：±w 根內嚴格最極端（features.swings 容許打和，橫行時每根都算，呢度唔要）。"""
    pts = []
    for j in range(w, len(bars) - w):
        others = bars[j - w:j] + bars[j + 1:j + w + 1]
        if side > 0 and bars[j]["low"] < min(b["low"] for b in others):
            pts.append(bars[j]["low"])
        if side < 0 and bars[j]["high"] > max(b["high"] for b in others):
            pts.append(bars[j]["high"])
    return pts


def pos_key(pos):
    """同一張倉嘅識別：EA ticket，紙上就 opened_ts。"""
    if not pos:
        return None
    return f"t{pos.get('ticket')}" if pos.get("ticket") is not None else f"p{pos.get('opened_ts')}"


def track(hr, pos, now):
    """state['hold_rules']：換咗倉就重設；初始止損＝第一次見到呢張倉時嘅止損（部署中途接手嘅倉就係當時嘅 SL）。"""
    key = pos_key(pos)
    if not hr or hr.get("key") != key:
        hr = {"key": key, "initial_stop": pos.get("stop"), "entry": pos.get("entry"), "r_hit_ts": None,
              "last_ask_ts": 0, "last_m15_time": None, "since": now, "stats": (hr or {}).get("stats") or {}}   # stats 跨倉累積（shadow 一星期）
    if hr.get("initial_stop") is None and pos.get("stop") is not None:
        hr["initial_stop"] = pos.get("stop")
    return hr


def suggest(pos, m1, atr15, price, initial_stop, nd=None):
    """規則止損。回傳 {"sl": 新止損或 None, "stage", "r_mult", "reason", 候選…}。sl None＝唔郁。"""
    nd = config.PRICE_DIGITS if nd is None else nd
    side, entry, cur = pos["side"], pos["entry"], pos.get("stop")
    out = {"sl": None, "stage": None, "r_mult": None, "reason": ""}
    r = abs(entry - initial_stop) if initial_stop is not None else None
    if not r or not atr15:
        out.update(stage="unknown", reason="冇初始止損／ATR，交 Claude")
        return out
    profit = (price - entry) * side
    out["r_mult"] = round(profit / r, 2)
    if profit < BE_R * r:
        out.update(stage="pre_1r", reason=f"浮盈 {out['r_mult']}R < 1R，唔郁")
        return out
    be = entry
    trail_atr = price - side * TRAIL_ATR_MULT * atr15
    sw = [p for p in strict_swings(m1[-120:], side) if (price - p) * side > MIN_ATR_MULT * atr15]
    trail_sw = (sw[-1] - side * SWING_BUF_ATR * atr15) if sw else None
    out.update(be=round(be, nd), trail_atr=round(trail_atr, nd), trail_swing=(round(trail_sw, nd) if trail_sw is not None else None))
    # 教學第 4 條：ATR 同擺動點取較遠（離現價遠）；教學第 1 條：至少保本
    trail = trail_atr if trail_sw is None else (trail_atr if (price - trail_atr) * side >= (price - trail_sw) * side else trail_sw)
    new = be if (be - trail) * side > 0 else trail
    # 唔收到 0.5×ATR 之內
    cap = price - side * MIN_ATR_MULT * atr15
    if (new - cap) * side > 0:
        new = cap
    new = round(new, nd)
    out["stage"] = "trail"
    if (new - price) * side >= 0:
        out["reason"] = "候選喺現價錯邊，唔郁"
        return out
    if cur is not None and (new - cur) * side <= 0:
        out["reason"] = f"候選 {new} 冇比現止損 {cur} 緊，唔郁（只准收緊）"
        return out
    if cur is not None and abs(new - cur) < MIN_STEP_ATR * atr15:
        out["reason"] = f"收緊幅度 {abs(new - cur):.{nd}f} < {MIN_STEP_ATR:g}×ATR，唔郁"
        return out
    out.update(sl=new, reason=("保本" if new == round(be, nd) else ("跟擺動點" if trail_sw is not None and new == round(trail_sw, nd) else "跟 1×ATR")))
    return out


def should_ask(hr, pos, price, atr15, m15_time, now, r_hit_first=False):
    """on 模式：邊啲分鐘要問 Opus。回傳原因 list（空＝唔問，由規則處理）。"""
    why = []
    if hr.get("initial_stop") is None or not atr15:
        why.append("冇初始止損／ATR")
    if m15_time is not None and hr.get("last_m15_time") != m15_time:
        why.append("新 M15")
    if r_hit_first:
        why.append("首次 1R")
    if atr15:
        if pos.get("stop") is not None and abs(price - pos["stop"]) <= MIN_ATR_MULT * atr15:
            why.append("近止損")
        if pos.get("target") is not None and abs(price - pos["target"]) <= MIN_ATR_MULT * atr15:
            why.append("近止賺")
    if now - (hr.get("last_ask_ts") or 0) >= config.HOLD_RULES_ASK_MIN * 60:
        why.append(f"滿 {config.HOLD_RULES_ASK_MIN} 分鐘")
    return why


def compare(stats, rule_sl, ai_action, ai_stop, cur_stop, tol):
    """shadow 統計：Opus 實際移止損 vs 規則會移去邊。目標：一星期內 Opus 移嘅止損同規則相差 ≤tol 嘅比例 ≥80%。"""
    stats = dict(stats or {})
    for k in ("ai_moves", "rule_moves", "both", "within_tol", "ai_only", "rule_only"):
        stats.setdefault(k, 0)
    ai_moved = ai_action == "UPDATE_STOP" and ai_stop is not None and ai_stop != cur_stop
    rule_moved = rule_sl is not None
    if ai_moved:
        stats["ai_moves"] += 1
    if rule_moved:
        stats["rule_moves"] += 1
    if ai_moved and rule_moved:
        stats["both"] += 1
        if abs(ai_stop - rule_sl) <= tol:
            stats["within_tol"] += 1
    elif ai_moved:
        stats["ai_only"] += 1
    elif rule_moved:
        stats["rule_only"] += 1
    stats["agree_pct"] = round(100.0 * stats["within_tol"] / stats["ai_moves"], 1) if stats["ai_moves"] else None
    return stats
