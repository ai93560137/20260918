"""[R369] 921 反向真倉（IDEAS #225；使用者 11-03 喺總指揮「根據921做一個完全相反嘅策略，用真倉；921照舊影子測試；不要影響921決策」）。
預設關（XAU_REVERSE_LIVE=0）。只喺主服務（zhuge-xau，唔係訊號書），而且只喺 921 影子（XAU_EXECUTE=0）時先有事件。

做法：
  921 影子紙上開倉（main.process_bar → paper.apply）→ main 事後寫一個「open」事件入 xau/reverse/state.json（921 決策一啲都唔改）；
  921 紙上平倉（止蝕／止賺／AI 平倉／最長持倉／日蝕）→ 寫「close」事件。
  EA 用 magic 926 掛一張圖（…63），心跳按 magic 分流到呢度：
    open 事件（SIGNAL_TTL 秒內）→ 反方向市價開，SL＝921 TP、TP＝921 SL（伺服器端），帶 px／dev（EA v0.41 滑價上限）；
    close 事件 → close|all|magic=926；
    保險：926 有倉但 921 影子已經冇倉（漏咗事件）→ 平；control＝STOP → 平。
  921 移止損唔跟：反向 TP 固定喺 921 原 SL；921 平倉時反向跟住市價平（最多遲一個心跳）。
風控：control 非 RUN、EA 唔准交易／dry_run、926 當日蝕到 XAU_REVERSE_DAY_STOP_HKD、921 冇 TP（反向冇 SL）都唔開。
固定手數 XAU_REVERSE_LOTS（夾 XAU_REVERSE_MAX_LOTS）。指令 id 前綴 v（921 嘅 id 係 hex，唔會撞）。純計算函數冇 I/O，方便測試。"""
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "reverse/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
MAX_EVENTS = 100
MAX_ORDERS = 200
ORPHAN_GRACE_SEC = 180          # 926 有倉而 921 影子冇倉：開倉後呢段時間內唔當漏咗（等 921 state 寫好）


def _m():
    import main            # 遲匯入避免循環
    return main


def enabled():
    return (not config.SIGNAL_BOOK) and config.REVERSE_LIVE and bool(config.REVERSE_MAGIC)


def is_magic(payload):
    return bool(config.REVERSE_MAGIC) and str(payload.get("magic") or "") == str(config.REVERSE_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("v")


def empty_state():
    return {"pending_cmds": [], "orders": [], "events": [], "last": None, "pos_seen": None, "book": []}


def load_state():
    base = empty_state()
    try:
        doc = storage.read_json(STATE_FILE, None)
    except StorageError:
        doc = None
    if isinstance(doc, dict):
        base.update(doc)
    return base


# ------------------------------------------------------------------ 純計算
def mirror(side, stop, target):
    """921 方向／SL／TP → 反向 (side, sl, tp)。921 冇 TP（反向冇 SL）或者冇 SL 回 None。"""
    if side not in (1, -1) or stop is None or target is None:
        return None
    return -side, float(target), float(stop)


def lots():
    return max(0.01, min(float(config.REVERSE_LOTS), float(config.REVERSE_MAX_LOTS)))


def open_block(control_mode, account, now=None, principal=None):
    """唔准開新倉嘅原因；None＝可以開。principal＝control.principal_hkd（§6c 戶口合計日蝕線用）。"""
    if control_mode != "RUN":
        return f"control＝{control_mode}"
    if account.get("dry_run"):
        return "EA dry_run"
    ta = account.get("trade_allowed")
    if isinstance(ta, dict) and not all(bool(v) for v in ta.values()):
        return "EA 唔准交易"
    day = account.get("daily_pnl")
    if config.REVERSE_DAY_STOP_HKD and day is not None and day <= -abs(config.REVERSE_DAY_STOP_HKD):
        return f"926 今日 {day:+.0f} HKD ≤ −{config.REVERSE_DAY_STOP_HKD:g}"
    bd = account.get("bots_daily_pnl")
    if principal and bd is not None:                      # §6c：…63 戶口天覆陣全部 magic 今日合計（已實現＋浮動）
        tot = bd + (account.get("bots_floating") or 0.0)
        line = -abs(principal) * config.DAILY_LOSS_STOP_PCT / 100
        if tot <= line:
            return f"…63 戶口今日合計 {tot:+.0f} HKD ≤ {line:+.0f}（§6c 日蝕 {config.DAILY_LOSS_STOP_PCT:g}%）"
    return None


def plan(events, pos, pending_open, pending_close, block, now, ttl=None):
    """處理未做嘅事件 → (動作 list, 事件結果 dict id→note)。動作：("open", ev) 或 ("close", reason)。純函數。"""
    ttl = config.REVERSE_SIGNAL_TTL_SEC if ttl is None else ttl
    acts, notes = [], {}
    has_pos, will_open, will_close = bool(pos), pending_open, pending_close
    for ev in events:
        if ev.get("done"):
            continue
        if ev.get("kind") == "close":
            if (has_pos or will_open) and not will_close:
                acts.append(("close", ev.get("reason") or "921 平倉"))
                will_close = True
                notes[ev["id"]] = "已排平倉"
            else:
                notes[ev["id"]] = "冇倉，唔使平"
            has_pos = will_open = False
        elif ev.get("kind") == "open":
            if now - float(ev.get("ts") or 0) > ttl:
                notes[ev["id"]] = f"過咗 {ttl} 秒，唔追"
            elif (has_pos or will_open) and not will_close:
                notes[ev["id"]] = "926 已經有倉／排緊開倉"
            elif block:
                notes[ev["id"]] = f"唔開：{block}"
            elif mirror(ev.get("side921"), ev.get("stop921"), ev.get("target921")) is None:
                notes[ev["id"]] = "921 冇 SL／TP，反向唔開"
            else:
                acts.append(("open", ev))
                will_open, has_pos, will_close = True, False, False
                notes[ev["id"]] = "已排開倉"
    return acts, notes


def merge(fresh, mine):
    """寫回時同 GCS 最新版本合併：events 以最新為準（921 可能啱啱加咗新事件），只套用我處理過嘅 done／note；其他欄用我嘅。純函數。"""
    fresh = {**empty_state(), **(fresh or {})}
    done = {e["id"]: e for e in (mine.get("events") or []) if e.get("done")}
    events = [({**e, **{k: done[e["id"]][k] for k in ("done", "note", "done_ts") if k in done[e["id"]]}} if e.get("id") in done else e)
              for e in (fresh.get("events") or [])]
    return {**fresh, **{k: v for k, v in mine.items() if k != "events"}, "events": events}


# ------------------------------------------------------------------ 921 影子事件（main 呼叫；出錯 main 會接住）
def emit(kind, now, **kw):
    if not enabled():
        return None
    ev = {"id": uuid.uuid4().hex[:8], "kind": kind, "ts": now, "utc": market.fmt_utc(now), "done": False, **kw}

    def mutate(state):
        state = {**empty_state(), **(state or {})}
        state["events"] = [*(state.get("events") or []), ev][-MAX_EVENTS:]
        return state, ev
    return storage.update(STATE_FILE, mutate, default_factory=empty_state)


# ------------------------------------------------------------------ 回報／狀態
def cmd_text(state, now):
    if not config.REVERSE_LIVE:
        return ""
    return "\n".join(c["text"] for c in (state.get("pending_cmds") or [])
                     if (not c.get("acked") or now < (c.get("resend_until") or 0)) and now - c["ts"] < executor.CMD_TTL_SEC)


def _pending(state, op, now):
    return any((not c.get("acked")) and str(c.get("text") or "").startswith(op + "|") and now - c["ts"] < executor.CMD_TTL_SEC
               for c in (state.get("pending_cmds") or []))


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
    return {"on": enabled(), "magic": config.REVERSE_MAGIC, "lots": lots(), "day_stop_hkd": config.REVERSE_DAY_STOP_HKD,
            "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "trade_allowed", "dry_run")},
            "events": (st.get("events") or [])[-20:][::-1],
            "orders": [{**o, "id": executor.mask_id(o.get("id"))} for o in (st.get("orders") or [])[-20:][::-1]],
            "book": (st.get("book") or [])[-50:][::-1], "last": st.get("last"),
            "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}


def _order_meta(state, pos):
    o = next((x for x in reversed(state.get("orders") or []) if x.get("ticket") is not None and str(x.get("ticket")) == str(pos.get("ticket"))), None)
    return {"ch": "921反向", "decision_price": o.get("price")} if o else {"ch": "921反向"}


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.REVERSE_ACCOUNT and str(payload.get("account") or "").strip() != config.REVERSE_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level",
                                                             "bots_daily_pnl", "bots_floating", "bots_realized_total")}   # bots_*：EA InpBotMagics 合計（§6c）
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.REVERSE_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ 921 反向戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    import live_book
    state = load_state()
    pos = (account.get("positions") or [None])[0]
    try:   # 成交簿只係紀錄：出錯唔可以拖垮心跳
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, extra=lambda p: _order_meta(state, p)):
            m.log_event(f"📗 [{config.TEAM_NAME}] 921 反向真倉平倉 {t['pnl_hkd']:+.2f} HKD", component="reverse")
    except Exception as exc:  # noqa: BLE001
        m.log_event(f"⚠️ 921 反向成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING", component="reverse")
    state["pos_seen"] = pos
    why = _decide(m, state, account, price, now) if enabled() else "921 反向未開（XAU_REVERSE_LIVE=0）"
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        state = storage.update(STATE_FILE, lambda fresh: (lambda v: (v, v))(merge(fresh, state)), default_factory=empty_state)
    except StorageError as exc:
        m.log_event(f"⚠️ 921 反向狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "reverse", "magic": config.REVERSE_MAGIC,
                      "mode": "live" if config.REVERSE_LIVE else "off", "cmd_text": cmd_text(state, now), "message": why}), 200


def _enqueue(m, state, kind, now, price, reason, side=None, sl=None, tp=None, ev=None):
    cid = "v" + uuid.uuid4().hex[:7]
    if kind == "open":
        action = "OPEN_LONG" if side > 0 else "OPEN_SHORT"
        text = executor.enqueue(state, action, sl, tp, now, cid, lots=lots(), magic=config.REVERSE_MAGIC, note="921反向",
                                px=price, dev=(config.MAX_ENTRY_SLIP or None))
    else:
        text = executor.enqueue(state, "CLOSE", None, None, now, cid, magic=config.REVERSE_MAGIC)
    state["orders"] = [*state.get("orders", []), {"id": cid, "kind": kind, "ts": now, "utc": market.fmt_utc(now), "price": price,
                                                  "side": side, "sl": sl, "tp": tp, "lots": lots() if kind == "open" else None,
                                                  "reason": reason, "event": (ev or {}).get("id"), "applied": text, "acked": False}][-MAX_ORDERS:]
    m.log_event(f"🔁 [{config.TEAM_NAME}] 921 反向 {kind} {'' if side is None else ('BUY' if side > 0 else 'SELL')} {reason}｜{text}", component="reverse", cmd=cid)
    return text


def _decide(m, state, account, price, now):
    pos = (account.get("positions") or [None])[0]
    control = m.load_control()
    block = open_block(control.get("mode"), account, now, principal=market.to_float(control.get("principal_hkd")))
    notes_out = []
    if control.get("mode") == "STOP" and pos and not _pending(state, "close", now):
        _enqueue(m, state, "close", now, price, "control＝STOP")
        return "control＝STOP，排平倉"
    acts, notes = plan(state.get("events") or [], pos, _pending(state, "open", now), _pending(state, "close", now), block, now)
    for ev in state.get("events") or []:
        if ev.get("id") in notes:
            ev.update(done=True, note=notes[ev["id"]], done_ts=now)
    for kind, arg in acts:
        if kind == "close":
            _enqueue(m, state, "close", now, price, arg)
            notes_out.append(f"平倉（{arg}）")
        else:
            side, sl, tp = mirror(arg.get("side921"), arg.get("stop921"), arg.get("target921"))
            px = arg.get("price") or price
            _enqueue(m, state, "open", now, px, f"反 921 {'多' if arg.get('side921') == 1 else '空'}", side=side, sl=sl, tp=tp, ev=arg)
            notes_out.append(f"開{'多' if side > 0 else '空'}（SL {sl}／TP {tp}）")
    if pos and not acts and not _pending(state, "close", now):            # 保險：921 影子冇倉但 926 有倉（漏咗 close 事件）
        last_open = next((o for o in reversed(state.get("orders") or []) if o.get("kind") == "open"), None)
        if last_open is None or now - float(last_open.get("ts") or 0) > ORPHAN_GRACE_SEC:
            try:
                main_pos = (m.load_state() or {}).get("position")
            except Exception:  # noqa: BLE001
                main_pos = "unknown"
            if main_pos is None:
                _enqueue(m, state, "close", now, price, "921 影子已冇倉（保險）")
                return "921 影子已冇倉，排平倉（保險）"
    if notes_out:
        return "；".join(notes_out)
    if pos:
        return "有倉（SL／TP 伺服器端；921 平倉時跟住平）"
    return f"冇倉；{block}" if block else "冇倉，等 921 影子開倉"
