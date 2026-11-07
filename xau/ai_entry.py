"""[IDEAS #1003] AI 揀入場（使用者 11-07「AI 入場，用另一個戶口，真倉比對」→ 經總指揮「A。開新 idea，隨時真倉」）。

影子（SIG_AIENTRY=1）：規則學生（SIG_AIENTRY_RULES，預設 rev15）每次出區，即刻叫 AI 揀入場價、SL、TP（或者唔做），
寫 GCS xau/sig/aientry/（state.json＋log/<日>.jsonl）。成績由 research/student_offline/ai_entry_forward.py 用券商 M1 計，
同一批出區嘅 E6S4（933 方法）並排比較；判斷以 IDEAS #1003 預先登記為準。
實倉（XAU_EXECUTE=1 而且 SIG_AIENTRY_EXECUTE=1）：EA 用 magic 936 掛一張圖，心跳按 magic 分流到呢度（指令 id 前綴 i）；
計劃有效（SIG_AIENTRY_TTL_MIN 分鐘內）、現價去到 AI 入場價先市價入，SL／TP 用 AI 嘅；固定 SIG_AIENTRY_LOTS 手、一次一張；
策略層停線 C（SIG_AIENTRY_HWM_START 起計 ≤ −STOP_R 或回撤 ≥ DD_R）、control 非 RUN、階梯 Ⓑ／Ⓓ、EA 唔准、數據封鎖都唔開。
唔主動改止損／平倉（SL／TP 伺服器端）。預設全關。"""
import datetime as dt
import json
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "aientry/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
MAX_PLANS = 300
MAX_ORDERS = 200

SYSTEM = """You choose the entry for a rule-based {symbol} trade idea. Nothing you say is executed unless the owner turns live trading on;
your plans are graded against real prices afterwards.
A simple rule has just fired: price moved sharply in the last 15 minutes and the rule wants to trade the OPPOSITE way (a fade).
The direction is fixed by the rule (`entry_task.side`). Your job: decide whether to take it, and if so pick
- entry_price: a LIMIT price for that side, at or better than the current price (BUY: at or below; SELL: at or above),
  no further than entry_task.max_entry_distance from the current price. Code waits up to entry_task.valid_minutes for price to reach it, then gives up.
- stop_price: beyond the entry on the losing side, distance from entry between entry_task.stop_distance_min and stop_distance_max.
- target_price: on the winning side of the entry.
Use the bars, structure and session context. take=false (null prices) is fine when the setup looks poor.
Write `reason` in Traditional Chinese, a short tag (max 20 characters).
The owner's LESSONS (below, if any) describe what the owner wants; follow them."""

TOOL = {
    "name": "pick_entry",
    "description": "Return your entry plan for this rule signal. Call this exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "take": {"type": "boolean"},
            "entry_price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "stop_price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "target_price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "reason": {"type": "string"},
        },
        "required": ["take", "entry_price", "stop_price", "target_price", "reason"],
        "additionalProperties": False,
    },
}


def _m():
    import main            # 遲匯入避免循環
    return main


def log_event(message, severity="INFO", **fields):
    print(json.dumps({"severity": severity, "message": message, "component": "aientry", **fields}, ensure_ascii=False, default=str), flush=True)


def enabled():
    return bool(config.SIGNAL_BOOK and config.AIENTRY and config.AIENTRY_RULES)


def is_magic(payload):
    return bool(config.AIENTRY_MAGIC) and str(payload.get("magic") or "") == str(config.AIENTRY_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("i")       # 唔係 hex，唔會撞 931 嘅隨機 id


def empty_state():
    return {"plans": [], "pending_cmds": [], "used": [], "orders": [], "last": None, "usage": {"n": 0, "cost_usd": 0.0}}


def load_state():
    base = empty_state()
    try:
        doc = storage.read_json(STATE_FILE, None)
    except StorageError:
        doc = None
    if isinstance(doc, dict):
        base.update(doc)
    return base


# ---------------------------------------------------------------- 計劃（純函數）
def validate(raw, side, price):
    """AI 回覆 → (計劃 dict, 原因)。計劃 None＝唔做／唔合格。純函數。"""
    if not isinstance(raw, dict) or not raw.get("take"):
        return None, "AI 唔做"
    try:
        e, sl, tp = (float(raw.get(k)) for k in ("entry_price", "stop_price", "target_price"))
    except (TypeError, ValueError):
        return None, "價位唔齊"
    if side not in ("BUY", "SELL") or price is None:
        return None, "方向／現價唔齊"
    sgn = 1 if side == "BUY" else -1
    if (e - price) * sgn > config.SIG_FILL_TOL:
        return None, f"入場價 {e:g} 喺現價 {price:g} 錯邊（要等回調）"
    if abs(price - e) > config.AIENTRY_MAX_DIST:
        return None, f"入場價離現價 {abs(price - e):.2f} > {config.AIENTRY_MAX_DIST:g}"
    risk = (e - sl) * sgn
    if not (config.AIENTRY_SL_MIN <= risk <= config.AIENTRY_SL_MAX):
        return None, f"止蝕距離 {risk:.2f} 唔喺 {config.AIENTRY_SL_MIN:g}–{config.AIENTRY_SL_MAX:g}"
    if (tp - e) * sgn <= 0:
        return None, "止賺錯邊"
    nd = config.PRICE_DIGITS
    return {"entry": round(e, nd), "sl": round(sl, nd), "tp": round(tp, nd), "risk": round(risk, nd)}, "ok"


def entry_check(plan, price):
    """回傳 (ok|wait|skip, 原因)。純函數。"""
    sgn = 1 if plan.get("side") == "BUY" else -1
    e, sl, tp = plan.get("entry"), plan.get("sl"), plan.get("tp")
    if None in (e, sl, tp, price):
        return "skip", "欄位唔齊"
    if (price - sl) * sgn <= 0:
        return "skip", "止損已經觸發／錯邊"
    if (price - tp) * sgn >= 0:
        return "skip", "現價已過止賺"
    if (price - e) * sgn <= config.SIG_FILL_TOL:
        return "ok", f"現價去到入場價 {e:g}"
    return "wait", f"等現價去到 {e:g}"


# ---------------------------------------------------------------- 問 AI（影子）
def _call(brain_obj, ctx):
    """回傳 (tool input dict or None, usage, error)。測試可以覆蓋。"""
    import brain as _brain
    lessons, _ver = brain_obj._lessons()
    system = [{"type": "text", "text": SYSTEM.replace("{symbol}", config.SYMBOL) + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else ""),
               "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    try:
        msg = brain_obj.client.messages.create(
            model=config.AIENTRY_MODEL, max_tokens=config.MAX_TOKENS, system=system, tools=[TOOL],
            tool_choice={"type": "auto", "disable_parallel_tool_use": True}, output_config={"effort": config.EFFORT},
            messages=[{"role": "user", "content": _brain._user_content(ctx, "Call the `pick_entry` tool.", stable_ttl=config.CACHE_TTL_STABLE, ttl="1h", cache_m1=False)}])
        usage = _brain._usage(msg, config.AIENTRY_MODEL, ttl="1h")
        if msg.stop_reason in ("refusal", "max_tokens"):
            return None, usage, f"AI {msg.stop_reason}"
        for block in msg.content:
            if block.type == "tool_use" and block.name == "pick_entry":
                return dict(block.input), usage, None
        return None, usage, "AI 冇回傳計劃"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"AI 出錯：{type(exc).__name__}: {str(exc)[:100]}"


def ask(brain_obj, ctx_builder, pred, now=None):
    """規則學生出區 → 問 AI 揀入場。回傳計劃記錄或 None（關咗／唔係登記嘅規則）。"""
    if not enabled() or pred.get("student") not in config.AIENTRY_RULES or pred.get("side") not in ("BUY", "SELL"):
        return None
    now = market.now_ts() if now is None else now
    price = pred.get("price")
    ctx = {k: v for k, v in (ctx_builder() or {}).items() if k != "signals"}
    ctx["entry_task"] = {"rule": pred["student"], "side": pred["side"], "rule_price": price, "rule_ref_move": pred.get("ref"),
                         "valid_minutes": config.AIENTRY_TTL_MIN, "max_entry_distance": config.AIENTRY_MAX_DIST,
                         "stop_distance_min": config.AIENTRY_SL_MIN, "stop_distance_max": config.AIENTRY_SL_MAX}
    raw, usage, err = _call(brain_obj, ctx)
    import brain as _brain
    cost = _brain.cost_usd(usage) or 0.0
    plan, why = validate(raw, pred["side"], price) if not err else (None, err)
    rec = {"id": uuid.uuid4().hex[:8], "pred": pred.get("id"), "student": pred["student"], "side": pred["side"], "ts": now, "utc": market.fmt_utc(now),
           "price": price, "take": bool((raw or {}).get("take")), "raw": {k: (raw or {}).get(k) for k in ("entry_price", "stop_price", "target_price")},
           "reason": str((raw or {}).get("reason") or "")[:60], "valid": plan is not None, "why": why, "cost_usd": cost, "error": err,
           **(plan or {})}

    def mutate(st):
        st = st if isinstance(st, dict) and st.get("plans") is not None else empty_state()
        st["plans"] = [*st["plans"], rec][-MAX_PLANS:]
        u = st.setdefault("usage", {"n": 0, "cost_usd": 0.0}); u["n"] += 1; u["cost_usd"] = round(u["cost_usd"] + cost, 4)
        return st, None
    try:
        storage.update(STATE_FILE, mutate, default_factory=empty_state)
        storage.append_jsonl(f"{PREFIX}log/{market.ny_date(now)}.jsonl", rec)
    except StorageError as exc:
        log_event(f"⚠️ AI 入場計劃寫入失敗：{exc}", severity="WARNING")
    log_event(f"🤖 [{config.TEAM_NAME}] AI 入場 {pred['student']} {pred['side']} @ {price}："
              + (f"入 {rec['entry']} SL {rec['sl']} TP {rec['tp']}" if plan else why) + f"｜{rec['reason']}｜${cost:.4f}", plan=rec["id"])
    return rec


# ---------------------------------------------------------------- 實倉（magic 936）
def strategy_stop(state):
    """策略層停線 C：由 SIG_AIENTRY_HWM_START 起計成交簿 R。回傳 (原因 or None, 統計)。純函數。"""
    if not config.AIENTRY_HWM_START:
        return None, {}
    try:
        start = dt.datetime.strptime(config.AIENTRY_HWM_START[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return "SIG_AIENTRY_HWM_START 格式錯（要 YYYY-MM-DD），為安全停開新倉", {}
    cum = peak = 0.0; n = 0
    for x in sorted((state or {}).get("book") or [], key=lambda r: r.get("closed_ts") or 0):
        if (x.get("closed_ts") or 0) < start or x.get("r") is None:
            continue
        cum += float(x["r"]); n += 1; peak = max(peak, cum)
    st = {"start": config.AIENTRY_HWM_START, "n": n, "cum_r": round(cum, 2), "dd_r": round(peak - cum, 2)}
    if cum <= -config.AIENTRY_STOP_R:
        return f"936 由 {config.AIENTRY_HWM_START} 起累計 {cum:+.2f}R ≤ −{config.AIENTRY_STOP_R:g}R → 停開新倉（使用者批改 SIG_AIENTRY_HWM_START 先重開）", st
    if peak - cum >= config.AIENTRY_DD_R:
        return f"936 由高位回撤 {peak - cum:.2f}R ≥ {config.AIENTRY_DD_R:g}R → 停開新倉（使用者批改 SIG_AIENTRY_HWM_START 先重開）", st
    return None, st


def _order_meta(state, pos):
    o = next((x for x in reversed(state.get("orders") or []) if x.get("ticket") is not None and str(x.get("ticket")) == str(pos.get("ticket"))), None)
    return {"ch": "AI入場", "decision_price": o.get("entry")} if o else {}


def _decide(m, state, account, price, now):
    if account.get("positions"):
        return "有倉（SL／TP 伺服器端）"
    if m.pending_has(state, "open"):
        return "等 EA 回報開倉"
    control = m.load_control()
    if control.get("mode") != "RUN":
        return f"模式 {control.get('mode')}，唔開新倉"
    lad = m.risk_ladder({}, control, account, {"close": price or 0.0}, now)
    if lad.get("stop") or lad.get("pause"):
        return f"階梯 {lad.get('level')}，唔開新倉"
    live = config.book_live(config.AIENTRY_MAGIC)
    ta = account.get("trade_allowed")
    if live and isinstance(ta, dict) and ta and not all(bool(v) for v in ta.values()):
        return "EA／終端／戶口未准交易"
    hwm_why, _hwm = strategy_stop(state)
    if hwm_why:
        return hwm_why
    if price is None:
        return "心跳冇 M1 收市價"
    import data_block
    data_ev, _info = data_block.check(state, now, market.ny_date(now), log=m.log_event, tg=m.notify.tg_send)
    state["data_block"] = data_ev
    if data_ev:
        return f"📅 數據封鎖：{data_block.text(data_ev)}"
    used = set(state.get("used") or [])
    ttl = config.AIENTRY_TTL_MIN * 60
    for p in reversed(state.get("plans") or []):
        if not p.get("valid") or p["id"] in used or not (0 <= now - float(p.get("ts") or 0) <= ttl):
            continue
        verdict, reason = entry_check(p, price)
        if verdict == "skip":
            state["used"] = [*state.get("used", []), p["id"]][-500:]
            log_event(f"🤖 [{config.TEAM_NAME}] AI 入場略過 {p['side']}（{p['id']}）：{reason}")
            continue
        if verdict == "wait":
            return f"{p['side']}：{reason}"
        action = "OPEN_LONG" if p["side"] == "BUY" else "OPEN_SHORT"
        cid = "i" + uuid.uuid4().hex[:7]
        n = round(config.AIENTRY_LOTS, 2)
        text = executor.enqueue(state, action, p["sl"], p["tp"], now, cid, lots=n, tag=p["id"], magic=config.AIENTRY_MAGIC,
                                note="AI入場", px=price, dev=(config.MAX_ENTRY_SLIP or None)) if live else None
        order = {"id": cid, "plan": p["id"], "side": p["side"], "lots": n, "entry": p["entry"], "sl": p["sl"], "tp": p["tp"],
                 "price": price, "ts": now, "utc": market.fmt_utc(now), "applied": text or "paper", "acked": False}
        state["orders"] = [*state.get("orders", []), order][-MAX_ORDERS:]
        state["used"] = [*state.get("used", []), p["id"]][-500:]
        log_event(f"🤖 [{config.TEAM_NAME}] AI 入場{'真倉' if text else '紙上'} {p['side']} {n:.2f} 手 @ {price}｜SL {p['sl']}｜TP {p['tp']}｜{reason}", cmd=cid)
        return f"AI 入場 {p['side']}（{reason}）"
    return "冇有效 AI 計劃"


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.AIENTRY_ACCOUNT and str(payload.get("account") or "").strip() != config.AIENTRY_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level",
                                                             "bots_daily_pnl", "bots_floating", "bots_realized_total")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.AIENTRY_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        log_event(f"⚠️ AI 入場戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    state = load_state()
    import live_book
    pos = (account.get("positions") or [None])[0]
    try:
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, extra=lambda p: _order_meta(state, p)):
            log_event(f"📗 [{config.TEAM_NAME}] AI 入場真倉平倉 {t['pnl_hkd']:+.2f} HKD（R {t.get('r')}）")
    except Exception as exc:  # noqa: BLE001
        log_event(f"⚠️ AI 入場成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING")
    state["pos_seen"] = pos
    why = _decide(m, state, account, price, now) if enabled() else "AI 入場未開（SIG_AIENTRY=0）"
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        log_event(f"⚠️ AI 入場狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "aientry", "magic": config.AIENTRY_MAGIC,
                      "mode": "live" if config.book_live(config.AIENTRY_MAGIC) else "shadow",
                      "cmd_text": executor.cmd_text(state, now, config.AIENTRY_MAGIC), "message": why}), 200


def ack(cid, payload, now):
    def mutate(state):
        found = executor.ack(state, cid, payload, now)
        for o in state.get("orders") or []:
            if o.get("id") == cid:
                o.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"), message=str(payload.get("message") or "")[:120])
        return (state if found else None), found
    return storage.update(STATE_FILE, mutate, default_factory=empty_state)


def status():
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    return {"on": enabled(), "live": config.book_live(config.AIENTRY_MAGIC), "magic": config.AIENTRY_MAGIC, "rules": list(config.AIENTRY_RULES),
            "model": config.AIENTRY_MODEL, "lots": config.AIENTRY_LOTS, "ttl_min": config.AIENTRY_TTL_MIN,
            "hwm": dict(zip(("why", "stat"), strategy_stop(st))), "usage": st.get("usage"),
            "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "trade_allowed", "dry_run")},
            "plans": [{k: p.get(k) for k in ("utc", "student", "side", "price", "take", "valid", "why", "entry", "sl", "tp", "reason")}
                      for p in (st.get("plans") or [])[-10:][::-1]],
            "orders": [{**o, "id": executor.mask_id(o.get("id"))} for o in (st.get("orders") or [])[-20:][::-1]],
            "last": st.get("last"), "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}
