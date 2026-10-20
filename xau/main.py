"""🌌 天覆陣：XAUUSD CFD（MT5）Claude 決策服務 — Cloud Run 入口。

流程（每個 EA 心跳）：
  1. 權杖檢查 → 2. 累積 M1／M15 → 3. 戶口快照 → 4. 新 M1 收盤：紙上止損／止賺／最長持倉 →
  5. 要問先問 Claude（空倉而電閘 LOCK 或休市就唔問；空倉先用 GATE_MODEL 篩）→ 6. 硬性規則 →
  7. 影子：紙上模擬；實倉（XAU_EXECUTE=1）：排指令，心跳回應 cmd_text 由 EA 執行 → 8. 寫決策紀錄。
狀態全部喺 GCS `xau/` 前綴；電閘影子階段只讀舊服務嘅 zhuge_gate_state.json。
"""
import json
import time
import uuid

import functions_framework
from flask import Flask, jsonify, request as flask_request

import brain
import config
import market
import notify
import page
import paper
import rules
import storage
from storage import StorageError

M1_FILE = config.PREFIX + "m1.json"
M15_FILE = config.PREFIX + "m15.json"
ACCOUNT_FILE = config.PREFIX + "account.json"
STATE_FILE = config.PREFIX + "state.json"
LESSONS_FILE = config.PREFIX + "lessons.md"
DECISIONS_PREFIX = config.PREFIX + "decisions/"
CONTROL_FILE = config.PREFIX + "control.json"      # 緊急停機開關、暫停開倉、本金（私人）、淨值高水位
BUNDLED_LESSONS = __file__.rsplit("/", 1)[0] + "/LESSONS.md"
CMD_TTL_SEC = 600            # 指令 10 分鐘內冇執行就作廢（EA 離線時唔好開舊單）


def now_ts():
    return time.time()


def log_event(message, severity="INFO", **fields):
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False, default=str), flush=True)


def load_lessons():
    try:
        text = storage.read_text(LESSONS_FILE)
    except StorageError:
        text = None
    if text is None:
        try:
            with open(BUNDLED_LESSONS, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return ""
    body = text.split("## 教學", 1)[1] if "## 教學" in text else text
    body = body.strip()
    return "" if body in ("", "（未有）") else body


_brain = None


def get_brain():
    global _brain
    if _brain is None:
        _brain = brain.ClaudeBrain(lessons_loader=load_lessons)
    return _brain


# ---------------------------------------------------------------------------
# 狀態
# ---------------------------------------------------------------------------
def load_state():
    try:
        state = storage.read_json(STATE_FILE, None)
    except StorageError as exc:
        log_event(f"⚠️ 狀態讀取失敗：{exc}", severity="WARNING")
        state = None
    base = paper.empty_state()
    base.update({"pending_cmds": [], "decisions": [], "usage_today": {"date": "", "decide": 0, "screen": 0,
                                                                        "cost_usd": 0.0, "ms": []}})
    if isinstance(state, dict):
        base.update(state)
    return base


def save_state(state):
    storage.write_json(STATE_FILE, state)


MODES = ("RUN", "PAUSE", "STOP")


def load_control():
    """唯一開關 GCS xau/control.json（冇網頁按鈕）。mode：RUN／PAUSE／STOP；set_by：user／ladder；
    auto_reset_day：紐約交易日，到咗自動返 RUN（只對 set_by=ladder 生效）；principal_hkd 私人。讀唔到當 STOP（fail-closed）。"""
    base = {"mode": "RUN", "reason": "", "set_by": "user", "set_at_utc": "", "auto_reset_day": None,
            "principal_hkd": None, "equity_peak": 0.0, "alerts_sent": {}, "cum_loss_above": False, "cum_loss_day": ""}
    try:
        doc = storage.read_json(CONTROL_FILE, None)
    except StorageError as exc:
        log_event(f"⚠️ control.json 讀取失敗（當 STOP）：{exc}", severity="WARNING")
        return {**base, "mode": "STOP", "reason": "control.json 讀取失敗", "set_by": "system"}
    if isinstance(doc, dict):
        base.update({k: doc[k] for k in base if k in doc})
    if base["mode"] not in MODES:
        base["mode"] = "RUN"
    return base


def save_control(control):
    storage.write_json(CONTROL_FILE, control)


def set_mode(control, mode, reason, set_by, now, auto_reset_day=None):
    control.update(mode=mode, reason=reason, set_by=set_by, set_at_utc=market.fmt_utc(now), auto_reset_day=auto_reset_day)
    log_event(f"🔀 [{config.TEAM_NAME}] 模式 → {mode}（{set_by}）：{reason}", severity="WARNING" if mode != "RUN" else "INFO", component="mode")


def risk_ladder(state, control, account, bar, now):
    """使用者 10-20：真倉同 C 戶口共用，日蝕只計天覆陣自己嘅單（模擬＝紙上；真倉＝EA 按 magic 回報）；
    「自己嘅權益」= 本金 + 累計已實現 + 浮動；保證金水平係戶口級。"""
    principal = market.to_float(control.get("principal_hkd"))
    daily_usd = paper.daily_pnl_usd(state, market.ny_day_start_ts(now), bar["close"])
    cum_usd = paper.cumulative_pnl_usd(state, bar["close"])
    own_equity = (principal + cum_usd * config.HKD_PER_USD) if principal else None
    if own_equity is not None and own_equity > (control.get("equity_peak") or 0.0):
        control["equity_peak"] = round(own_equity, 2)
    lad = rules.ladder(principal_hkd=principal, own_equity=own_equity,
                       peak_equity=(control.get("equity_peak") if principal else None),
                       daily_pnl_hkd=daily_usd * config.HKD_PER_USD,
                       margin_level=market.to_float(account.get("margin_level")), night=market.is_night(now))
    lad.update(own_equity_hkd=(round(own_equity, 2) if own_equity is not None else None),
               daily_pnl_hkd=round(daily_usd * config.HKD_PER_USD, 2), cum_pnl_usd=cum_usd, night=market.is_night(now),
               level=("D" if lad["stop"] else ("B" if lad["pause"] else "A")))
    return lad


def apply_ladder(state, control, lad, bar, now, day, decision_id, rec):
    """模式轉換（只會自動改 set_by=ladder 嘅模式；使用者設嘅唔郁）同 Telegram 提示。回傳 True = 今根已經處理完（唔問 Claude）。"""
    mode, set_by = control["mode"], control.get("set_by")
    next_day = market.ny_date(now + 86400) if market.ny_date(now + 86400) != day else market.ny_date(now + 2 * 86400)
    # 自動重置：換日（日蝕）／保證金回升
    if set_by == "ladder" and mode != "RUN":
        if control.get("auto_reset_day") and day >= control["auto_reset_day"]:
            set_mode(control, "RUN", f"換日自動重開（{control.get('reason')}）", "ladder", now)
            notify.tg_send(f"▶ 換日自動重開（之前：{control.get('reason')}）")
        elif mode == "PAUSE" and not control.get("auto_reset_day") and not lad["pause"]:
            set_mode(control, "RUN", "保證金水平回升，自動解除停開新倉", "ladder", now)
            notify.tg_send("▶ 保證金水平回升，自動解除停開新倉")
        mode = control["mode"]
    # 累計虧損 ≥ 25%：當日事件（edge）——由未達升到達嗰下先觸發；daily 模式每日 ≥25% 都觸發
    above = bool(lad.get("cum_loss"))
    was_above = bool(control.get("cum_loss_above"))
    control["cum_loss_above"] = above
    cum_trip = above and (not was_above if config.CUM_LOSS_RETRIGGER == "edge" else control.get("cum_loss_day") != day)
    if cum_trip and mode == "RUN" and not lad["pause"]:
        control["cum_loss_day"] = day
        set_mode(control, "PAUSE", lad["cum_loss_text"], "ladder", now, auto_reset_day=next_day)
        notify.tg_send(f"⏸ {lad['cum_loss_text']}")
        mode = control["mode"]
    handled = False
    if lad["stop"] and mode != "STOP":
        why = "；".join(lad["reasons"])
        closed = paper.force_close(state, bar, "日蝕 −" + f"{config.DAILY_LOSS_STOP_PCT:g}% 平倉停機", now)
        if config.EXECUTE:
            rec["applied"] = enqueue_cmd(state, "CLOSE", None, None, now, decision_id)
        set_mode(control, "STOP", why, "ladder", now, auto_reset_day=next_day)
        rec.update(kind="ladder", action="CLOSE", final="CLOSE", reason=why,
                   paper_exit=({"reason": closed["reason"], "pnl_usd": closed["pnl_usd"]} if closed else rec.get("paper_exit")))
        notify.tg_send(f"🛑 {why}｜今日 {lad['daily_pnl_hkd']:+,.0f} 港幣｜紐約 17:00 換日自動重開")
        handled = True
    elif lad["pause"] and mode == "RUN":
        why = "；".join(lad["reasons"])
        set_mode(control, "PAUSE", why, "ladder", now, auto_reset_day=(next_day if lad["pause_kind"] == "daily" else None))
        notify.tg_send(f"⏸ {why}")
    # 只提示嘅警報：每個交易日每項一次
    sent = control.setdefault("alerts_sent", {})
    if sent.get("day") != day:
        control["alerts_sent"] = sent = {"day": day}
    for key, text in (lad.get("alerts") or {}).items():
        if not sent.get(key):
            sent[key] = market.fmt_utc(now)
            notify.tg_send(f"⚠️ {text}（只提示，唔停唔鎖）")
            log_event(f"⚠️ [{config.TEAM_NAME}] {text}", severity="WARNING", component="ladder")
    return handled


def legacy_gate():
    """舊服務電閘：硬鎖／新聞鎖／armed。讀唔到當 LOCK（fail-closed）。"""
    try:
        g = storage.read_json(config.LEGACY_GATE_FILE, None)
    except StorageError as exc:
        return {"status": "LOCK", "reason": f"電閘讀取失敗：{exc}"}
    if not isinstance(g, dict):
        return {"status": "LOCK", "reason": "舊服務電閘不存在"}
    lock = g.get("hard_lock")
    if isinstance(lock, dict) and (lock.get("until_ts") is None or now_ts() < market.to_float(lock.get("until_ts"), 0)):
        return {"status": "LOCK", "reason": f"硬鎖：{lock.get('reason') or '未知'}"}
    if g.get("news_lock"):
        return {"status": "LOCK", "reason": "新聞鎖"}
    if not g.get("armed"):
        risk = g.get("risk") if isinstance(g.get("risk"), dict) else {}
        return {"status": "LOCK", "reason": risk.get("reason") or g.get("last_reason") or "未開閘"}
    return {"status": "OPEN", "reason": (g.get("risk") or {}).get("reason") or "六關全過"}


# ---------------------------------------------------------------------------
# 決策
# ---------------------------------------------------------------------------
def compact(bars):
    return [[b["time"], b["open"], b["high"], b["low"], b["close"]] for b in bars]


def build_context(state, m1, m15, account, gate, now, day, ladder=None, control=None):
    older, recent = m15[:-4], m15[-4:]
    pos = state.get("position")
    last = m1[-1]["close"]
    position = None
    if pos:
        position = {"side": "LONG" if pos["side"] > 0 else "SHORT", "lots": pos["lots"], "entry": pos["entry"],
                    "stop": pos.get("stop"), "target": pos.get("target"),
                    "age_min": int((now - pos["opened_ts"]) / 60),
                    "unrealized_usd": round((last - pos["entry"]) * pos["side"] * config.CONTRACT_SIZE * pos["lots"], 2)}
    return {
        "product": {"symbol": config.SYMBOL, "contract_size_oz": config.CONTRACT_SIZE,
                    "long_only": config.LONG_ONLY, "mode": "live" if config.EXECUTE else "shadow"},
        "bars_m15_older": compact(older),
        "time": market.session_text(now),
        "bars_m15_recent": compact(recent),
        "bars_m1": compact(m1[-60:]),
        "atr": {"m1_14": market.wilder_atr(m1), "m15_14": market.wilder_atr(m15),
                "ea_m1": account.get("atr_m1"), "ea_m5": account.get("atr_m5"), "ea_m15": account.get("atr_m15")},
        "last_price": last,
        "account": {"currency": account.get("currency"), "equity": account.get("equity"),
                    "balance": account.get("balance"), "daily_pnl": account.get("daily_pnl")},
        "legacy_gate": gate,
        "position": position,
        "risk": {"lots": rules.lots(), "min_sl_usd": config.MIN_SL_USD, "max_sl_usd": config.MAX_SL_USD,
                 "min_confidence": config.MIN_CONFIDENCE, "max_trades_per_day": config.MAX_TRADES_PER_DAY,
                 "trades_today": paper.trades_today(state, day), "max_hold_min": config.MAX_HOLD_MIN,
                 "ladder": {"level": (ladder or {}).get("level", "A"), "reasons": (ladder or {}).get("reasons", []),
                            "daily_pnl_hkd": (ladder or {}).get("daily_pnl_hkd"), "alerts": list((ladder or {}).get("alerts", {}).values())},
                 "mode": (control or {}).get("mode", "RUN"), "mode_reason": (control or {}).get("reason")},
        "recent_trades": [{"side": "LONG" if t["side"] > 0 else "SHORT", "entry": t["entry"], "exit": t["exit"],
                           "pnl_usd": t["pnl_usd"], "reason": t["reason"], "hold_min": t["hold_min"]}
                          for t in (state.get("trades") or [])[-5:]],
        "recent_decisions": [{"hkt": market.fmt_hkt(d["ts"]), "action": d.get("final"), "reason": d.get("reason")}
                             for d in (state.get("decisions") or [])[-6:]],
    }


def _bump_usage(state, kind, usage, ms, day):
    u = state.get("usage_today") or {}
    if u.get("date") != day:
        u = {"date": day, "decide": 0, "screen": 0, "cost_usd": 0.0, "ms": []}
    u[kind] = u.get(kind, 0) + 1
    u["cost_usd"] = round(u.get("cost_usd", 0.0) + (brain.cost_usd(usage) or 0.0), 4)
    u["ms"] = ((u.get("ms") or []) + [ms])[-300:]
    state["usage_today"] = u


def _record(state, rec, day):
    state["decisions"] = ((state.get("decisions") or []) + [rec])[-config.DECISION_LOG_MAX:]
    state["last_decision"] = rec
    try:
        storage.append_jsonl(f"{DECISIONS_PREFIX}{day}.jsonl", rec)
    except StorageError as exc:
        log_event(f"⚠️ 決策紀錄寫入失敗：{exc}", severity="WARNING")


def enqueue_cmd(state, action, stop, target, now, decision_id):
    """實倉：把動作變成 EA 指令（分行文字，EA 用 StringSplit 讀）。"""
    cid = decision_id[:8]
    if action in ("OPEN_LONG", "OPEN_SHORT"):
        text = f"open|{'BUY' if action == 'OPEN_LONG' else 'SELL'}|{rules.lots():.2f}|sl={stop:.2f}|tp={'' if target is None else f'{target:.2f}'}|magic={config.MAGIC}|id={cid}"
    elif action == "CLOSE":
        text = f"close|all|magic={config.MAGIC}|id={cid}"
    elif action == "UPDATE_STOP":
        text = f"modify|all|sl={stop:.2f}|tp={'' if target is None else f'{target:.2f}'}|magic={config.MAGIC}|id={cid}"
    else:
        return None
    state["pending_cmds"] = [c for c in (state.get("pending_cmds") or []) if now - c["ts"] < CMD_TTL_SEC]
    state["pending_cmds"].append({"id": cid, "text": text, "ts": now, "acked": False})
    return text


def cmd_text(state, now):
    if not config.EXECUTE:
        return ""
    return "\n".join(c["text"] for c in (state.get("pending_cmds") or [])
                     if not c.get("acked") and now - c["ts"] < CMD_TTL_SEC)


def process_bar(state, bar, m1, m15, account, now):
    """新 M1 收盤。回傳 (決策紀錄或 None, 摘要)。"""
    day = market.ny_date(now)
    exit_rec = paper.on_bar(state, bar, now)
    if exit_rec:
        log_event(f"📕 [{config.TEAM_NAME}] 紙上平倉 {exit_rec['reason']} {exit_rec['pnl_usd']:+.2f} USD", component="paper")
    gate = legacy_gate()                       # 只作參考資料傳畀 Claude，唔係硬閘（使用者 10-20）
    market_open = market.is_gold_market_open(now)
    control = load_control()
    ladder = risk_ladder(state, control, account, bar, now)
    state["ladder"] = ladder
    pos = state.get("position")
    decision_id = uuid.uuid4().hex
    rec = {"id": decision_id, "ts": now, "bar_time": bar["time"], "price": bar["close"], "legacy_gate": gate["status"],
           "ladder": ladder["level"], "mode": control["mode"], "execute": config.EXECUTE}
    if exit_rec:
        rec["paper_exit"] = {"reason": exit_rec["reason"], "pnl_usd": exit_rec["pnl_usd"]}
    handled = apply_ladder(state, control, ladder, bar, now, day, decision_id, rec)
    state["mode"] = {k: control.get(k) for k in ("mode", "reason", "set_by", "set_at_utc", "auto_reset_day")}
    try:
        save_control(control)
    except StorageError as exc:
        log_event(f"🚨 control.json 寫入失敗：{exc}", severity="ERROR")
    if handled:
        _record(state, rec, day)
        return rec, rec["reason"]
    if control["mode"] == "STOP":
        return None, f"STOP（{control.get('set_by')}）：{control.get('reason') or ''}"
    if not market_open:
        return None, "休市"
    if len(m15) < 20 or len(m1) < 30:
        return None, f"歷史不足（M15 {len(m15)}／M1 {len(m1)} 根），累積中"

    can_open = control["mode"] == "RUN"
    block = None if can_open else f"PAUSE（{control.get('set_by')}）：{control.get('reason') or ''}"
    ctx = build_context(state, m1, m15, account, gate, now, day, ladder, control)
    b = get_brain()
    if pos is None and config.GATE_MODEL:
        sc = b.screen(ctx)
        _bump_usage(state, "screen", sc.get("_usage"), sc.get("_ms", 0), day)
        if not sc.get("look"):
            rec.update(kind="screen", action="HOLD", final="HOLD", reason=f"篩選：{sc.get('reason')}",
                       ms=sc.get("_ms"), cost_usd=brain.cost_usd(sc.get("_usage")), model=config.GATE_MODEL)
            _record(state, rec, day)
            return rec, "篩選：唔值得睇"
        rec["screen"] = sc.get("reason")

    d = b.decide(ctx)
    _bump_usage(state, "decide", d.get("_usage"), d.get("_ms", 0), day)
    action, stop, target, why = rules.validate_decision(
        d, position=pos, last=bar["close"], can_open=can_open, block_reason=block,
        trades_today=paper.trades_today(state, day))
    rec.update(kind="decide", action=str(d.get("action")), final=action, stop=stop, target=target,
               confidence=d.get("confidence"), reason=str(d.get("reason") or "")[:400], rejected=why,
               ai_stop=d.get("stop_price"), ai_target=d.get("target_price"),
               ms=d.get("_ms"), usage=d.get("_usage"), cost_usd=brain.cost_usd(d.get("_usage")),
               model=(d.get("_usage") or {}).get("model") or config.MODEL, lessons=d.get("_lessons"),
               error=bool(d.get("_error")))
    if config.EXECUTE:
        rec["applied"] = enqueue_cmd(state, action, stop, target, now, decision_id) or "HOLD"
        if action in ("OPEN_LONG", "OPEN_SHORT"):
            paper.count_trade(state, day)
    else:
        rec["applied"] = paper.apply(state, action, stop, target, bar, now, day, decision_id)
    _record(state, rec, day)
    log_event(f"🧠 [{config.TEAM_NAME}] {action}{' ← AI ' + rec['action'] if why else ''} @ {bar['close']:.2f}"
              f"｜{rec['reason'][:80]}{'｜擋：' + why if why else ''}｜{rec['ms']} ms", component="brain",
              action=action, rejected=why, ms=rec["ms"], cost_usd=rec["cost_usd"])
    return rec, rec["applied"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _token_ok(payload):
    token = payload.get("token")
    return bool(config.TOKEN) and isinstance(token, str) and token.strip() == config.TOKEN


def handle_heartbeat(payload):
    now = now_ts()
    m1_raw = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    m15_raw = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "credit", "floating", "daily_pnl",
                                                             "buy_lots", "sell_lots", "net_lots", "margin_level")}
    account.update(currency=str(payload.get("currency") or "HKD"), symbol=str(payload.get("symbol") or ""),
                   status=str(payload.get("status") or ""), received_utc=market.fmt_utc(now), received_ts=now,
                   atr_m1=market.to_float(m15_raw.get("atr_m1")), atr_m5=market.to_float(m15_raw.get("atr_m5")),
                   atr_m15=market.to_float(m15_raw.get("atr_m15")))
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        log_event(f"⚠️ 戶口快照寫入失敗：{exc}", severity="WARNING")

    m15_bar = market.parse_bar(m15_raw)
    m15 = None
    if m15_bar:
        def mut15(h):
            new, _ = market.ingest(h, m15_bar, config.M15_MAX, config.M1_GAP_RESET_SEC * 15)
            return new, new
        try:
            m15 = storage.update(M15_FILE, mut15, default_factory=list)
        except StorageError as exc:
            log_event(f"⚠️ M15 寫入失敗：{exc}", severity="WARNING")

    state = load_state()
    resp = {"status": "monitoring", "team": config.TEAM_NAME, "mode": "live" if config.EXECUTE else "shadow",
            "cmd_text": cmd_text(state, now)}
    bar = market.parse_bar(m1_raw) if m1_raw.get("is_new_bar") else None
    if bar is None:
        return jsonify(resp), 200

    def mut1(h):
        new, is_new = market.ingest(h, bar, config.M1_MAX, config.M1_GAP_RESET_SEC)
        return (new if is_new else None), (new, is_new)
    try:
        m1, is_new = storage.update(M1_FILE, mut1, default_factory=list)
    except StorageError as exc:
        log_event(f"⚠️ M1 寫入失敗：{exc}", severity="WARNING")
        return jsonify({**resp, "message": "M1 storage error"}), 200
    if not is_new:
        return jsonify({**resp, "message": "duplicate M1 bar"}), 200
    if m15 is None:
        try:
            m15 = storage.read_json(M15_FILE, [])
        except StorageError:
            m15 = []

    rec, summary = process_bar(state, bar, m1, m15 or [], account, now)
    try:
        save_state(state)
    except StorageError as exc:
        log_event(f"⚠️ 狀態寫入失敗：{exc}", severity="ERROR")
    resp.update(cmd_text=cmd_text(state, now), message=summary,
                decision=({k: rec.get(k) for k in ("final", "action", "reason", "rejected", "stop", "target", "ms")} if rec else None))
    return jsonify(resp), 200


def handle_cmd_ack(payload):
    """EA 執行完指令回報：{"action":"cmd_ack","id":...,"ok":true,"ticket":...,"message":...}"""
    cid = str(payload.get("id") or "").strip()
    if not cid:
        return jsonify({"status": "error", "message": "missing id"}), 400

    def mutate(state):
        found = False
        for c in state.get("pending_cmds") or []:
            if c["id"] == cid and not c.get("acked"):
                c.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"),
                         message=str(payload.get("message") or "")[:200], acked_ts=now_ts())
                found = True
        return (state if found else None), found
    try:
        found = storage.update(STATE_FILE, mutate, default_factory=paper.empty_state)
    except StorageError as exc:
        return jsonify({"status": "error", "message": str(exc)[:100]}), 500
    log_event(f"📨 [{config.TEAM_NAME}] 指令回報 {cid} ok={payload.get('ok')} {'' if found else '（未知／已回報）'}", component="ea")
    return jsonify({"status": "acked" if found else "unknown", "id": cid}), 200


def build_status():
    state = load_state()
    try:
        m1 = storage.read_json(M1_FILE, [])
        m15 = storage.read_json(M15_FILE, [])
        account = storage.read_json(ACCOUNT_FILE, {})
    except StorageError:
        m1, m15, account = [], [], {}
    now = now_ts()
    u = state.get("usage_today") or {}
    ms = sorted(u.get("ms") or [])
    p95 = ms[int(len(ms) * 0.95) - 1] if len(ms) >= 2 else (ms[0] if ms else None)
    control = load_control()
    return {
        "team": config.TEAM_NAME, "symbol": config.SYMBOL, "execute": config.EXECUTE, "model": config.MODEL,
        "ladder": state.get("ladder") or {"level": "A", "reasons": []},
        "control": {"mode": control.get("mode"), "reason": control.get("reason"), "set_by": control.get("set_by"),
                    "set_at_utc": control.get("set_at_utc"), "auto_reset_day": control.get("auto_reset_day"),
                    "principal_set": bool(control.get("principal_hkd"))},
        "effort": config.EFFORT, "gate_model": config.GATE_MODEL, "updated_hkt": market.fmt_hkt(now, "%m-%d %H:%M:%S"),
        "gate": legacy_gate(), "market_open": market.is_gold_market_open(now), "session": market.session_text(now),
        "last_price": (m1[-1]["close"] if m1 else None), "m1_bars": len(m1), "m15_bars": len(m15),
        "account_received_utc": account.get("received_utc"),
        "position": state.get("position"), "stats": state.get("stats"), "trades": (state.get("trades") or [])[-40:],
        "metrics": paper.metrics(state.get("trades") or [], day_key=market.ny_date),
        "trades_today": paper.trades_today(state, market.ny_date(now)),
        "decisions": (state.get("decisions") or [])[-60:],
        "usage_today": {"decide": u.get("decide", 0), "screen": u.get("screen", 0), "cost_usd": u.get("cost_usd", 0.0), "p95_ms": p95},
        "pending_cmds": [c for c in (state.get("pending_cmds") or []) if not c.get("acked")],
        "risk": {"XAU_LOTS": rules.lots(), "XAU_MIN_SL_USD": config.MIN_SL_USD, "XAU_MAX_SL_USD": config.MAX_SL_USD,
                 "XAU_MIN_CONFIDENCE": config.MIN_CONFIDENCE, "XAU_MAX_TRADES_PER_DAY": config.MAX_TRADES_PER_DAY,
                 "XAU_MAX_HOLD_MIN": config.MAX_HOLD_MIN, "XAU_LONG_ONLY": config.LONG_ONLY, "XAU_MAGIC": config.MAGIC,
                 "XAU_EXECUTE": config.EXECUTE, "CLAUDE_PROVIDER": config.PROVIDER,
                 "日蝕 PAUSE／STOP %（換日自動重開）": f"{config.DAILY_LOSS_PAUSE_PCT:g}／{config.DAILY_LOSS_STOP_PCT:g}",
                 "保證金 PAUSE %（回升自動解）": config.MARGIN_PAUSE_PCT,
                 "累計虧損 PAUSE %（當日事件，換日自動重開）": f"{config.CUM_LOSS_PAUSE_PCT:g}（{config.CUM_LOSS_RETRIGGER}）",
                 "只提示：保證金 %／回撤 %": f"{'／'.join(f'{x:g}' for x in config.MARGIN_ALERT_PCTS)}；{'／'.join(f'{x:g}' for x in config.DD_ALERT_PCTS)}",
                 "夜盤倍數": config.NIGHT_MULT},
    }


def entry(req):
    if req.method == "OPTIONS":
        return "", 204
    if req.method == "GET":
        status = build_status()
        if req.args.get("format") == "json":
            return jsonify(status), 200
        return page.render(status), 200, {"Content-Type": "text/html; charset=utf-8"}
    try:
        raw = req.get_data().decode("utf-8").replace("\x00", "").strip()     # MT5 char 陣列常以 \0 結尾
        payload = json.loads(raw) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return jsonify({"status": "error", "message": "invalid JSON"}), 400
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "invalid payload"}), 400
    if not _token_ok(payload):
        return jsonify({"status": "error", "message": "Unauthorized token"}), 403
    action = payload.get("action")
    if action == "cmd_ack":
        return handle_cmd_ack(payload)
    if "equity" in payload or action in ("check_gate", "heartbeat"):
        return handle_heartbeat(payload)
    return jsonify({"status": "ignored", "message": "No handler for this payload"}), 200


@functions_framework.http
def xau_entry(request):
    return entry(request)


app = Flask(__name__)
app.add_url_rule("/", "root", lambda: entry(flask_request), methods=["GET", "POST", "OPTIONS"])
app.add_url_rule("/<path:_p>", "any", lambda _p: entry(flask_request), methods=["GET", "POST", "OPTIONS"])
