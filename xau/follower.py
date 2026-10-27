"""訊號書跟單（使用者 10-22 批「CTC 0.01 手執銀仔落 demo」；IDEAS #123）：只限 SIG_FOLLOW_CHANNELS、固定手數、TP1 全平、用頻道原 SL；
獨立 magic（FOLLOW_MAGIC＝932）、獨立狀態前綴 xau/sig/follow/，成績同 S1（931）分得開；戶口總階梯（§6c）由 EA InpBotMagics 合計計入。
規則：市價單訊號即刻市價入；限價單訊號等現價入到入場區（±點差）先市價入；收到時已過 TP1、止損錯邊、TTL 過咗就唔入（標 used 唔再試）；
一次只一張；control 非 RUN、階梯 Ⓑ／Ⓓ、EA 唔准交易就唔開；唔改止損、唔主動平（SL／TP 伺服器端）。XAU_EXECUTE=0 只記紙上。"""
import re
import time
import uuid

import config
import executor
import market
import signals
import storage
from storage import StorageError

PREFIX = config.PREFIX + "follow/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
MAX_ORDERS = 200


def _m():
    import main            # 遲匯入避免循環（main 匯入 follower）
    return main


def enabled():
    return config.SIGNAL_BOOK and bool(config.FOLLOW_CHANNELS)


def is_follow_magic(payload):
    return str(payload.get("magic") or "") == str(config.FOLLOW_MAGIC)


def is_follow_cmd(cid):
    return str(cid or "").startswith("f")


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


def candidates(now):
    """未過期、驗證有效、指定頻道、未用過嘅入場訊號（新到舊）。"""
    try:
        rows = storage.read_json(config.PREFIX + "signals/recent.json", []) or []
    except StorageError:
        return []
    return [r for r in rows[::-1] if r.get("kind") == "new_signal" and r.get("status") == "valid"
            and (r.get("valid_until_ts") or 0) > now and str(r.get("ch") or "")[-4:] in config.FOLLOW_CHANNELS]


def avoid_hours(ch):
    """SIG_FOLLOW_AVOID_HOURS="5231:07-12,7713:13-14" → 該頻道 (起, 止) UTC 整點；冇就 None。"""
    ch = str(ch or "")[-4:]
    for part in (config.FOLLOW_AVOID_HOURS or "").split(","):
        part = part.strip()
        if ":" not in part or "-" not in part:
            continue
        c, hours = part.split(":", 1)
        if c.strip()[-4:] != ch:
            continue
        try:
            a, b = (int(x) for x in hours.split("-", 1))
        except ValueError:
            continue
        return a % 24, b % 24
    return None


def in_avoid_hours(ch, now):
    rng = avoid_hours(ch)
    if not rng or now is None:
        return False
    a, b = rng
    h = int(now // 3600) % 24
    return a <= h < b if a <= b else (h >= a or h < b)


def entry_check(sig, price, now=None):
    """回傳 (ok|wait|skip, 原因)。純函數（now 只用於時段規則；None＝而家）。"""
    side = sig.get("side"); sgn = 1 if side == "BUY" else -1
    sl, tps, lo, hi = sig.get("sl"), sig.get("tp") or [], sig.get("entry_low"), sig.get("entry_high")
    if side not in ("BUY", "SELL") or sl is None or not tps or price is None:
        return "skip", "欄位唔齊"
    ch = str(sig.get("ch") or "")[-4:]
    now = time.time() if now is None else now
    if in_avoid_hours(ch, now):                            # 10-24 使用者：倫敦時段都避（CTC 07–12 UTC −1.61 美元／張）
        a, b = avoid_hours(ch)
        return "skip", f"時段 {a:02d}–{b:02d} UTC 唔跟"
    tp1 = tps[0]
    if ch in config.FOLLOW_SKIP_UNREACHED_CHANNELS:        # 10-24 使用者：唔跟未到入場價（收到時價仍喺入場價反向 ≥ tol → 唔等限價，略過）
        ref, _src = signals.ref_entry(sig)
        if ref is not None:
            behind = (ref - price) * sgn
            if behind >= config.FOLLOW_UNREACHED_TOL:
                return "skip", f"收到時價未到入場價（反向 {behind:.{config.PRICE_DIGITS}f} ≥ {config.FOLLOW_UNREACHED_TOL:g}）"
    if (price - tp1) * sgn >= 0:
        return "skip", "收到時價已過 TP1"
    nd = config.PRICE_DIGITS
    market_now = any(k in str(sig.get("order_type") or "") for k in ("market", "now"))
    ref = price if (market_now or lo is None or hi is None) else (lo + hi) / 2     # 限價訊號會喺入場區成交，用區中位計剩餘空間
    remain = (tp1 - ref) * sgn
    if remain < config.FOLLOW_MIN_TP:                      # 10-23 DAN 2766：市價 BUY 時 TP1 只剩 0.5 美元而 SL 9.5，唔值得入
        return "skip", f"入場到 TP1 只有 {remain:.{nd}f} < {config.FOLLOW_MIN_TP:g}"
    if signals.is_late(sig, price):                        # 同 S1 一樣：已向有利方向離入場區 ≥ SIG_LATE_R×止損距離＝走咗
        return "skip", f"走咗（離入場區已 ≥ {config.SIG_LATE_R:g}×止損距離）"
    dist = (price - sl) * sgn
    if dist <= 0:
        return "skip", "止損已經觸發／錯邊"
    if dist > config.SIG_MAX_SL:
        return "skip", f"止損距離 {dist:.{config.PRICE_DIGITS}f} 超過 {config.SIG_MAX_SL:g}"
    if market_now or lo is None:
        return "ok", "市價單"
    tol = config.SIG_FILL_TOL
    if lo - tol <= price <= hi + tol:
        return "ok", "現價喺入場區"
    return "wait", f"等現價入入場區 {lo:g}–{hi:g}"


def status():
    """status JSON／網頁用。"""
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    return {"magic": config.FOLLOW_MAGIC, "channels": list(config.FOLLOW_CHANNELS), "lots": config.FOLLOW_LOTS,
            "exit": {ch: exit_mode(ch) for ch in config.FOLLOW_CHANNELS}, "ladder_channels": list(config.FOLLOW_LADDER_CHANNELS),
            "skip_unreached_channels": list(config.FOLLOW_SKIP_UNREACHED_CHANNELS), "unreached_tol": config.FOLLOW_UNREACHED_TOL,
            "avoid_hours": {ch: avoid_hours(ch) for ch in config.FOLLOW_CHANNELS if avoid_hours(ch)},
            "execute": config.EXECUTE, "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "floating", "trade_allowed", "dry_run")},
            "orders": [{**o, "id": executor.mask_id(o.get("id")), "applied": (re.sub(r"id=([0-9a-f]+)", lambda m: "id=" + executor.mask_id(m.group(1)), str(o.get("applied") or "")))} for o in (st.get("orders") or [])[-20:][::-1]],
            "used": len(st.get("used") or []), "last": st.get("last"),
            "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}   # 10-23：id 遮罩


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
    if config.ACCOUNT and str(payload.get("account") or "").strip() != config.ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level",
                                                             "bots_daily_pnl", "bots_floating", "bots_realized_total")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.FOLLOW_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ 跟單戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    state = load_state()
    resp = {"status": "monitoring", "team": config.TEAM_NAME, "book": "follow", "magic": config.FOLLOW_MAGIC,
            "mode": "live" if config.EXECUTE else "shadow", "cmd_text": executor.cmd_text(state, now)}
    why = _decide(m, state, account, price, now)
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        m.log_event(f"⚠️ 跟單狀態寫入失敗：{exc}", severity="ERROR")
    resp.update(cmd_text=executor.cmd_text(state, now), message=why)
    return m.jsonify(resp), 200


def exit_mode(ch):
    """tp1（TP1 全平，CTC）或 ladder（逐級鎖，DAN；使用者 10-23 真倉直接開）。"""
    return "ladder" if str(ch or "")[-4:] in config.FOLLOW_LADDER_CHANNELS else "tp1"


def ladder_stop(order, pos, price):
    """逐級鎖純函數：回傳 (新止損或 None, 級數 k, 原因)。k=0 到 TP1 → 保本（入場價）；k≥1 到 TP(k+1) → 鎖 TP(k)。只准收緊。"""
    tps, side = order.get("tps") or [], 1 if order.get("side") == "BUY" else -1
    if not tps or price is None or pos is None:
        return None, -1, "冇 TP／價／倉"
    k = -1
    for i, tp in enumerate(tps):
        if (price - tp) * side >= 0:
            k = i
    if k < 0:
        return None, k, "未到 TP1"
    entry = pos.get("entry")
    want = entry if k == 0 else tps[k - 1]
    if want is None:
        return None, k, "冇入場價"
    want = want - side * config.FOLLOW_LADDER_BUF
    want = round(want, config.PRICE_DIGITS)
    cur = pos.get("stop")
    if cur is not None and (want - cur) * side <= 0:
        return None, k, f"現止損 {cur} 已 ≥ 鎖位 {want}"
    if (want - price) * side >= 0:
        return None, k, "鎖位喺現價錯邊"
    return want, k, ("保本" if k == 0 else f"鎖 TP{k}")


def _manage(m, state, account, price, now):
    """有倉：逐級鎖頻道按級數收緊止損（排 modify，伺服器端執行）；TP1 頻道唔郁。"""
    pos = (account.get("positions") or [None])[0]
    orders = state.get("orders") or []
    order = next((o for o in reversed(orders) if o.get("ok") and (o.get("ticket") in (None, pos.get("ticket")) if pos else False)), None)
    if order is None or exit_mode(order.get("ch")) != "ladder":
        return "有倉（SL／TP 伺服器端）"
    if m.pending_has(state, "modify"):
        return "有倉（逐級鎖：等 EA 回報 modify）"
    want, k, why = ladder_stop(order, pos, price)
    if want is None:
        return f"有倉（逐級鎖 k={k}：{why}）"
    last = order.get("ladder") or {}
    if last.get("sl") == want and now - (last.get("ts") or 0) < 300:          # 同一鎖位 5 分鐘內唔重複排（EA 拒絕時免每分鐘重試）
        return f"有倉（逐級鎖 TP{k + 1}：止損 {want} 已排，等 EA）"
    cid = "f" + uuid.uuid4().hex[:7]
    target = pos.get("target") if pos.get("target") is not None else (order.get("tps") or [None])[-1]
    text = executor.enqueue(state, "UPDATE_STOP", want, target, now, cid, tag=order.get("sid"), magic=config.FOLLOW_MAGIC) if config.EXECUTE else None
    order["ladder"] = {"k": k, "sl": want, "ts": now, "utc": market.fmt_utc(now), "cmd": cid}
    m.log_event(f"📨 [{config.TEAM_NAME}] 跟單逐級鎖 {order.get('sid')} 到 TP{k + 1} → 止損 {want}（{why}）@ {price}｜{'已排 modify' if text else '紙上'}",
                component="follow", sid=order.get("sid"), cmd=cid)
    return f"有倉（逐級鎖 TP{k + 1}：止損 → {want}）"


def _decide(m, state, account, price, now):
    if account.get("positions"):
        return _manage(m, state, account, price, now)
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
    if price is None:
        return "心跳冇 M1 收市價"
    used = set(state.get("used") or [])
    for sig in candidates(now):
        if sig["sid"] in used:
            continue
        verdict, reason = entry_check(sig, price, now)
        if verdict == "skip":
            state["used"] = [*state.get("used", []), sig["sid"]][-500:]
            m.log_event(f"📨 [{config.TEAM_NAME}] 跟單略過 {sig['sid']}：{reason}", component="follow")
            continue
        if verdict == "wait":
            return f"{sig['sid']}：{reason}"
        side = sig["side"]; action = "OPEN_LONG" if side == "BUY" else "OPEN_SHORT"
        ch = str(sig.get("ch") or "")[-4:]; mode = exit_mode(ch)
        tp_cmd = sig["tp"][-1] if mode == "ladder" else sig["tp"][0]          # 逐級鎖：伺服器端 TP 掛最後一級，中途由 modify 鎖
        cid = "f" + uuid.uuid4().hex[:7]
        text = executor.enqueue(state, action, sig["sl"], tp_cmd, now, cid, lots=config.FOLLOW_LOTS, tag=sig["sid"], magic=config.FOLLOW_MAGIC) if config.EXECUTE else None
        order = {"id": cid, "sid": sig["sid"], "ch": ch, "side": side, "lots": config.FOLLOW_LOTS, "sl": sig["sl"], "tp": tp_cmd,
                 "tps": list(sig["tp"]), "exit": mode,
                 "price": price, "ts": now, "utc": market.fmt_utc(now), "entry": reason, "applied": text or "paper", "acked": False}
        state["orders"] = [*state.get("orders", []), order][-MAX_ORDERS:]
        state["used"] = [*state.get("used", []), sig["sid"]][-500:]
        m.log_event(f"📨 [{config.TEAM_NAME}] 跟單 {sig['sid']} {side} {config.FOLLOW_LOTS} 手 @ {price}｜SL {sig['sl']}｜{'TP' + str(len(sig['tp'])) + ' ' + str(tp_cmd) + '（逐級鎖）' if mode == 'ladder' else 'TP1 ' + str(sig['tp'][0])}｜{reason}｜{'已排指令' if text else '紙上'}",
                    component="follow", sid=sig["sid"], cmd=cid)
        return f"跟單 {sig['sid']} {side}（{reason}）"
    return "冇可跟訊號"
