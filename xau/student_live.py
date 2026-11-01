"""[R358] 規則學生真倉（使用者 10-31 揀 A：新 magic 933，同 931 S1 分開成交簿；「先準備定、判定成功之後就可以開始」）。
預設關（SIG_STUDENT_LIVE=0）；只落 SIG_STUDENT_LIVE_RULES 列明、已過 IDEAS #146 門檻嘅規則學生判斷。
做法同跟單（follower，932）一樣：EA 用 magic 933 掛一張圖，心跳按 magic 分流到呢度；獨立狀態前綴 xau/sig/studentlive/、指令 id 前綴 s。
入場：學生出區後 SIG_STUDENT_TTL_MIN 分鐘內現價入到入場區（±SIG_FILL_TOL）先市價入，用學生自己嘅結構 SL 同 2R TP（同影子成績一樣）；
過咗 TP、SL 錯邊、TTL 過咗就放棄。一次一張；931＋933 同戶口合共最多 SIG_STUDENT_MAX_CONCURRENT 張（含排緊嘅開倉）；
control 非 RUN、階梯 Ⓑ／Ⓓ、EA 唔准、數據封鎖、933 當日蝕到 SIG_STUDENT_DAY_STOP_HKD 都唔開。唔主動改止損／平倉（SL／TP 伺服器端）。"""
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "studentlive/"
STATE_FILE = PREFIX + "state.json"
TEST_FILE = PREFIX + "test_cmd.json"        # [R359] 933 真單測試（XAU_TEST_CMDS=1＋XAU_EXECUTE=1 先生效；同 931 嘅 xau/sig/test_cmd.json 一樣用法）
ACCOUNT_FILE = PREFIX + "account.json"
MAX_ORDERS = 200


def _m():
    import main            # 遲匯入避免循環
    return main


def enabled():
    return config.SIGNAL_BOOK and config.STUDENT_LIVE and bool(config.STUDENT_LIVE_RULES)


def is_magic(payload):
    return str(payload.get("magic") or "") == str(config.STUDENT_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("s")


def empty_state():
    return {"pending_cmds": [], "used": [], "orders": [], "last": None}


def load_state():
    base = empty_state()
    try:
        doc = storage.read_json(STATE_FILE, None)
    except StorageError:
        doc = None
    if isinstance(doc, dict):
        base.update(doc)
    return base


def lots(state=None):
    import lots_ladder
    return max(0.01, lots_ladder.current(state, start=round(config.STUDENT_LOTS, 2), lo=round(config.STUDENT_LOTS_MIN, 2),
                                         hi=round(config.STUDENT_MAX_LOTS, 2), on=config.STUDENT_LOTS_LADDER))


def lots_kw():
    return dict(start=round(config.STUDENT_LOTS, 2), lo=round(config.STUDENT_LOTS_MIN, 2), hi=round(config.STUDENT_MAX_LOTS, 2),
                step=round(config.LOTS_STEP, 2), on=config.STUDENT_LOTS_LADDER)


def candidates(now):
    """未過 TTL、准落真倉嘅規則學生判斷（新到舊）。"""
    try:
        st = storage.read_json(config.PREFIX + "student/state.json", {}) or {}
    except StorageError:
        return []
    ttl = config.STUDENT_TTL_MIN * 60
    return [p for p in (st.get("preds") or [])[::-1]
            if p.get("student") in config.STUDENT_LIVE_RULES and 0 <= now - float(p.get("ts") or 0) <= ttl]


def entry_check(pred, price):
    """回傳 (ok|wait|skip, 原因)。純函數。"""
    side = pred.get("side"); sgn = 1 if side == "BUY" else -1
    lo, hi, sl, tps = pred.get("entry_low"), pred.get("entry_high"), pred.get("sl"), pred.get("tp") or []
    if side not in ("BUY", "SELL") or None in (lo, hi, sl, price) or not tps:
        return "skip", "欄位唔齊"
    tp = tps[0]
    if (price - tp) * sgn >= 0:
        return "skip", "現價已過 TP"
    if (price - sl) * sgn <= 0:
        return "skip", "止損已經觸發／錯邊"
    tol = config.SIG_FILL_TOL
    if lo - tol <= price <= hi + tol:
        return "ok", "現價喺入場區"
    return "wait", f"等現價入入場區 {lo:g}–{hi:g}"


def s1_open_count(now):
    """同戶口 931 S1 嘅倉數＋排緊嘅開倉（931 戶口快照同 state）。"""
    m = _m()
    n = 0
    try:
        acct = storage.read_json(m.ACCOUNT_FILE, {}) or {}
        n += len(acct.get("positions") or [])
        st = storage.read_json(m.STATE_FILE, {}) or {}
        n += sum(1 for c in (st.get("pending_cmds") or []) if not c.get("acked") and str(c.get("text") or "").startswith("open|")
                 and now - float(c.get("ts") or 0) < executor.CMD_TTL_SEC)
    except StorageError:
        return 0
    return n


def busy(now=None):
    """畀 931 S1 用：933 有倉或者排緊開倉 → 931 唔好再開（合共上限）。關咗就永遠 False。"""
    if not enabled():
        return False
    now = market.now_ts() if now is None else now
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
        st = load_state()
    except StorageError:
        return False
    n = len(acct.get("positions") or []) + sum(1 for c in (st.get("pending_cmds") or []) if not c.get("acked")
                                               and str(c.get("text") or "").startswith("open|") and now - float(c.get("ts") or 0) < executor.CMD_TTL_SEC)
    return n >= config.STUDENT_MAX_CONCURRENT


def status():
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    return {"on": enabled(), "magic": config.STUDENT_MAGIC, "rules": list(config.STUDENT_LIVE_RULES), "lots": lots(st),
            "lots_ladder": {"on": config.STUDENT_LOTS_LADDER, "start": config.STUDENT_LOTS, "min": config.STUDENT_LOTS_MIN, "max": config.STUDENT_MAX_LOTS,
                            "level": st.get("lots_level"), "log": (st.get("lots_log") or [])[-10:]},
            "day_stop_hkd": config.STUDENT_DAY_STOP_HKD, "ttl_min": config.STUDENT_TTL_MIN, "max_concurrent": config.STUDENT_MAX_CONCURRENT,
            "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "trade_allowed", "dry_run")},
            "orders": [{**o, "id": executor.mask_id(o.get("id"))} for o in (st.get("orders") or [])[-20:][::-1]],
            "last": st.get("last"), "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}


def ack(cid, payload, now):
    def mutate(state):
        found = executor.ack(state, cid, payload, now)
        for o in state.get("orders") or []:
            if o.get("id") == cid:
                o.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"), message=str(payload.get("message") or "")[:120])
        return (state if found else None), found
    return storage.update(STATE_FILE, mutate, default_factory=empty_state)


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.STUDENT_ACCOUNT and str(payload.get("account") or "").strip() != config.STUDENT_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level",
                                                             "bots_daily_pnl", "bots_floating", "bots_realized_total")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.STUDENT_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ 學生真倉戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    state = load_state()
    import lots_ladder, live_book
    pos = (account.get("positions") or [None])[0]
    try:   # 成交簿只係紀錄：出錯唔可以拖垮心跳
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, extra=lambda p: _order_meta(state, p)):
            m.log_event(f"📗 [{config.TEAM_NAME}] 學生真倉平倉 {t['pnl_hkd']:+.2f} HKD（{t.get('ch') or '—'}）", component="studentlive")
    except Exception as exc:  # noqa: BLE001
        m.log_event(f"⚠️ 學生真倉成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING", component="studentlive")
    moved = lots_ladder.live_close(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, note="ea", **lots_kw())
    state["pos_seen"] = pos
    if moved:
        m.log_event(f"🪜 [{config.TEAM_NAME}] 學生真倉手數階梯 {moved[0]:.2f} → {moved[1]:.2f}", component="studentlive")
    _consume_test(m, state, now)
    why = _decide(m, state, account, price, now) if enabled() else "學生真倉未開（SIG_STUDENT_LIVE=0 或冇准落嘅規則）"
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        m.log_event(f"⚠️ 學生真倉狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "studentlive", "magic": config.STUDENT_MAGIC,
                      "mode": "live" if config.EXECUTE else "shadow", "cmd_text": executor.cmd_text(state, now), "message": why}), 200


def _consume_test(m, state, now):
    """[R359] GCS xau/sig/studentlive/test_cmd.json：{"op":"open|close","side","sl","tp","lots","ts"}；未用過、ts 喺 TTL 內就排入 933（id 前綴 s），
    寫回 consumed＋result。學生真倉關（SIG_STUDENT_LIVE_RULES 空）都照用——測試唔會觸發規則單。"""
    if not (config.TEST_CMDS and config.EXECUTE):
        return
    try:
        doc = storage.read_json(TEST_FILE, None)
    except StorageError:
        return
    if not isinstance(doc, dict) or not doc.get("op") or doc.get("consumed"):
        return
    ts = market.to_float(doc.get("ts"))
    if ts is None or abs(now - ts) > executor.CMD_TTL_SEC:
        body = {"status": "error", "message": f"ts missing or older than {executor.CMD_TTL_SEC}s (use date +%s)"}
    else:
        text, err = m.test_text(state, doc, now, "s" + uuid.uuid4().hex[:7], magic=config.STUDENT_MAGIC)
        body = {"status": "queued", "text": text} if text else {"status": "error", "message": err}
        m.log_event(f"🧪 [{config.TEAM_NAME}] 933 test_cmd：{text or err}", severity="WARNING", component="studentlive")
    try:
        storage.write_json(TEST_FILE, {**doc, "consumed": market.fmt_utc(now), "result": body})
    except StorageError as exc:
        m.log_event(f"🚨 933 test_cmd.json 寫回 consumed 失敗（可能重複排指令）：{exc}", severity="ERROR", component="studentlive")


def _order_meta(state, pos):
    o = next((x for x in reversed(state.get("orders") or []) if x.get("ticket") is not None and str(x.get("ticket")) == str(pos.get("ticket"))), None)
    return {"ch": o.get("student"), "decision_price": o.get("price")} if o else {}


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
    ta = account.get("trade_allowed")
    if config.EXECUTE and isinstance(ta, dict) and ta and not all(bool(v) for v in ta.values()):
        return "EA／終端／戶口未准交易"
    if config.STUDENT_DAY_STOP_HKD and (account.get("daily_pnl") or 0.0) <= -config.STUDENT_DAY_STOP_HKD:
        return f"933 今日已蝕 {account.get('daily_pnl'):+.2f} HKD ≥ {config.STUDENT_DAY_STOP_HKD:g}，暫停開新倉"
    if price is None:
        return "心跳冇 M1 收市價"
    import data_block
    data_ev, _info = data_block.check(state, now, market.ny_date(now), log=m.log_event, tg=m.notify.tg_send)
    state["data_block"] = data_ev
    if data_ev:
        return f"📅 數據封鎖：{data_block.text(data_ev)}"
    if s1_open_count(now) >= config.STUDENT_MAX_CONCURRENT:
        return f"931 S1 有倉／排緊開倉，同戶口合共上限 {config.STUDENT_MAX_CONCURRENT} 張"
    used = set(state.get("used") or [])
    for p in candidates(now):
        if p["id"] in used:
            continue
        verdict, reason = entry_check(p, price)
        if verdict == "skip":
            state["used"] = [*state.get("used", []), p["id"]][-500:]
            m.log_event(f"🎓 [{config.TEAM_NAME}] 學生真倉略過 {p['student']} {p['side']}（{p['id']}）：{reason}", component="studentlive")
            continue
        if verdict == "wait":
            return f"{p['student']} {p['side']}：{reason}"
        action = "OPEN_LONG" if p["side"] == "BUY" else "OPEN_SHORT"
        cid = "s" + uuid.uuid4().hex[:7]
        n = lots(state)
        import risk_size
        r_lots, r_info = risk_size.size(account.get("equity"), price, p["sl"], config.STUDENT_MAX_LOTS)   # [R363] 按風險計手數
        if r_lots is not None:
            if r_info.get("mode") == "fallback":
                m.log_event(f"⚠️ [{config.TEAM_NAME}] 學生真倉按風險計手數：{r_info['why']}", severity="WARNING", component="risk")
            if r_lots == 0.0:
                state["used"] = [*state.get("used", []), p["id"]][-500:]
                return f"{p['student']} {p['side']}：按風險計手數唔開（{r_info.get('why')}）"
            n = r_lots
        text = executor.enqueue(state, action, p["sl"], p["tp"][0], now, cid, lots=n, tag=p["id"], magic=config.STUDENT_MAGIC,
                                note="學生" + p["student"].removeprefix("rule:"), px=price, dev=(config.MAX_ENTRY_SLIP or None)) if config.EXECUTE else None
        order = {"id": cid, "pred": p["id"], "student": p["student"], "side": p["side"], "lots": n, "sl": p["sl"], "tp": p["tp"][0], "risk": r_info if r_lots is not None else None,
                 "price": price, "ts": now, "utc": market.fmt_utc(now), "entry": reason, "applied": text or "paper", "acked": False}
        state["orders"] = [*state.get("orders", []), order][-MAX_ORDERS:]
        state["used"] = [*state.get("used", []), p["id"]][-500:]
        m.log_event(f"🎓 [{config.TEAM_NAME}] 學生真倉 {p['student']} {p['side']} {n:.2f} 手 @ {price}｜SL {p['sl']}｜TP {p['tp'][0]}｜{reason}｜{'已排指令' if text else '紙上'}",
                    component="studentlive", cmd=cid)
        return f"學生真倉 {p['student']} {p['side']}（{reason}）"
    return "冇可落嘅學生判斷"
