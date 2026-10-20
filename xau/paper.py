"""紙上模擬：影子模式用，記錄 Claude 決定嘅假想盈虧。純函數，操作 state dict，冇 I/O。

成交假設（保守）：開倉／平倉都用該根 M1 收市價，每張來回扣 SPREAD_USD 點差；
同一根 K 線同時碰到止損同止賺，當止損。盈虧以美元計（1 手 = 100 盎司）。"""
import config
import rules


def empty_state():
    return {"position": None, "trades": [], "trades_today": {"date": "", "count": 0},
            "stats": {"n": 0, "wins": 0, "pnl_usd": 0.0, "peak": 0.0, "max_dd": 0.0}, "last_decision": None}


def _pnl(pos, exit_price):
    gross = (exit_price - pos["entry"]) * pos["side"] * config.CONTRACT_SIZE * pos["lots"]
    cost = config.SPREAD_USD * config.CONTRACT_SIZE * pos["lots"]
    return round(gross - cost, 2)


def _close(state, pos, exit_price, reason, now_ts):
    pnl = _pnl(pos, exit_price)
    trade = {**pos, "exit": exit_price, "closed_ts": now_ts, "reason": reason, "pnl_usd": pnl,
             "hold_min": int((now_ts - pos["opened_ts"]) / 60)}
    state["position"] = None
    state["trades"] = (state.get("trades") or [])[-199:] + [trade]
    st = state["stats"]
    st["n"] += 1
    st["wins"] += 1 if pnl > 0 else 0
    st["pnl_usd"] = round(st["pnl_usd"] + pnl, 2)
    st["peak"] = max(st["peak"], st["pnl_usd"])
    st["max_dd"] = round(max(st["max_dd"], st["peak"] - st["pnl_usd"]), 2)
    return trade


def on_bar(state, bar, now_ts):
    """每根新 M1：先睇止損／止賺／最長持倉。回傳平倉紀錄或 None。"""
    pos = state.get("position")
    if not pos:
        return None
    side = pos["side"]
    if rules.stop_hit(side, bar["low"], bar["high"], pos.get("stop")):
        return _close(state, pos, pos["stop"], "止損", now_ts)
    if rules.target_hit(side, bar["low"], bar["high"], pos.get("target")):
        return _close(state, pos, pos["target"], "止賺", now_ts)
    if rules.hold_expired(pos["opened_ts"], now_ts):
        return _close(state, pos, bar["close"], f"最長持倉 {config.MAX_HOLD_MIN} 分鐘", now_ts)
    return None


def count_trade(state, day):
    td = state.get("trades_today") or {}
    if td.get("date") != day:
        td = {"date": day, "count": 0}
    td["count"] += 1
    state["trades_today"] = td
    return td["count"]


def trades_today(state, day):
    td = state.get("trades_today") or {}
    return td.get("count", 0) if td.get("date") == day else 0


def apply(state, action, stop, target, bar, now_ts, day, decision_id):
    """執行已過硬性規則嘅動作。回傳一句摘要。"""
    pos = state.get("position")
    price = bar["close"]
    if action in ("OPEN_LONG", "OPEN_SHORT"):
        side = 1 if action == "OPEN_LONG" else -1
        state["position"] = {"side": side, "entry": price, "lots": rules.lots(), "stop": stop, "target": target,
                             "opened_ts": now_ts, "decision_id": decision_id}
        n = count_trade(state, day)
        return f"紙上開倉 {'多' if side > 0 else '空'} @ {price:.2f} 止損 {stop} 止賺 {target or '—'}（今日第 {n} 筆）"
    if action == "CLOSE" and pos:
        t = _close(state, pos, price, "AI 平倉", now_ts)
        return f"紙上平倉 @ {price:.2f}，{t['pnl_usd']:+.2f} 美元"
    if action == "UPDATE_STOP" and pos:
        old = pos.get("stop")
        pos["stop"], pos["target"] = stop, target
        return f"止損 {old} → {stop}，止賺 {target or '—'}"
    return "HOLD"
