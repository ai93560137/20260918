"""📨 [R290] 外部 Telegram 頻道訊號 → Claude 解析 → 人手確認 → EA 指令（MT5）。由 main.py（zhuge-risk-manager）搬入天覆陣。

流程：tg_relay/tg_listener.py（claude-ops VM，用戶帳號讀頻道）POST action=tg_signal（帶 WEBHOOK_SECRET_TOKEN）→ 去重 →
Claude 解析成固定 JSON（只解析、唔決定）→ 預檢（黃金、止損、價格偏離、止損方向／距離、模式）→ 訊號確認 bot 發「✅／❌」按鈕 →
使用者按 ✅ → Telegram callback POST ?tg=signal（核對 secret_token 標頭、chat／使用者白名單）→ 重新檢查（逾時、模式、最新價）→
排 EA 指令（executor.enqueue，同天覆陣引擎共用 magic）→ EA 下一個心跳執行。XAU_EXECUTE=0 時指令唔會送到 EA。
TG_SIGNAL_ORDER_ENABLED=0（預設）時只分析、只發參考訊息，按鈕唔出現。
"""
import hmac
import os
import re
import uuid

import requests
from flask import jsonify

import brain
import config
import executor
import market
import storage
from storage import StorageError

ORDER_ENABLED = config._b("TG_SIGNAL_ORDER_ENABLED", False)
LOTS = config._f("TG_SIGNAL_LOTS", 0.01)
MAX_LOTS = config._f("TG_SIGNAL_MAX_LOTS", 0.10)
CONFIRM_TTL_SEC = config._i("TG_SIGNAL_CONFIRM_TTL_SEC", 900)        # 分析後幾秒內可確認
PRICE_MAX_AGE_SEC = config._i("TG_SIGNAL_PRICE_MAX_AGE_SEC", 300)    # 最新 M1 收市價最舊可接受幾秒
MAX_DRIFT_USD = config._f("TG_SIGNAL_MAX_DRIFT_USD", 5.0)            # 現價離訊號入場（區）最多幾美元
MAX_SL_USD = config._f("TG_SIGNAL_MAX_SL_USD", 30.0)
MODEL = config._s("TG_SIGNAL_AI_MODEL", config.MODEL)
NOTIFY_ALL = config._b("TG_SIGNAL_NOTIFY_ALL", False)                # 1 = 非交易訊息都發一則
PREFIX = config.PREFIX + "tg_signals/"
MAX_TEXT = 4000
GOLD_ALIASES = ("XAUUSD", "XAU/USD", "XAU", "GOLD", "黃金", "黄金")
M1_FILE = config.PREFIX + "m1.json"
STATE_FILE = config.PREFIX + "state.json"
CONTROL_FILE = config.PREFIX + "control.json"
_client = None
now_ts = market.now_ts if hasattr(market, "now_ts") else __import__("time").time


def log_event(message, severity="INFO", **fields):
    import json
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False, default=str), flush=True)


def sid_of(channel_id, msg_id, edit_ts=None):
    """GCS 物件名與 callback_data 用嘅 id（callback_data 上限 64 bytes）。"""
    cid = re.sub(r"[^0-9A-Za-z]", "", str(channel_id or "x"))[:24] or "x"
    mid = re.sub(r"[^0-9]", "", str(msg_id or ""))[:12] or "0"
    return f"{cid}_{mid}" + (f"_e{int(edit_ts)}" if edit_ts else "")


def tg_api(method, body):
    """呼叫訊號確認 bot（TG_SIGNAL_BOT_TOKEN）。回傳 JSON 或 None；不記錄權杖與網址。"""
    token = os.environ.get("TG_SIGNAL_BOT_TOKEN", "").strip()
    if not token:
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=body, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ [訊號 bot {method} 失敗] {type(exc).__name__}", flush=True)
        return None


def is_gold(symbol):
    s = str(symbol or "").strip().upper()
    return bool(s) and any(s == a or s.startswith(a) for a in GOLD_ALIASES)


def normalize(raw):
    """把 AI 嘅輸出夾成固定欄位與型別；數字一律 to_float，絕不信任格式。"""
    raw = raw if isinstance(raw, dict) else {}
    f = market.to_float
    side = str(raw.get("side") or "").strip().upper()
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(side, side)
    lo, hi = f(raw.get("entry_low")), f(raw.get("entry_high"))
    if lo is None and hi is not None:
        lo = hi
    if hi is None and lo is not None:
        hi = lo
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    tps = raw.get("tp") if isinstance(raw.get("tp"), list) else [raw.get("tp")]
    kind = str(raw.get("kind") or "other").strip().lower()
    return {
        "kind": kind if kind in ("new_signal", "update", "other") else "other",
        "symbol": str(raw.get("symbol") or "").strip().upper() or None,
        "side": side if side in ("BUY", "SELL") else None,
        "order_type": str(raw.get("order_type") or "").strip().lower() or None,
        "entry_low": lo, "entry_high": hi, "sl": f(raw.get("sl")),
        "tp": [v for v in (f(t) for t in tps) if v is not None and v > 0][:5],
        "update_action": str(raw.get("update_action") or "").strip()[:200] or None,
        "confidence": f(raw.get("confidence")),
        "analysis": str(raw.get("analysis") or "").strip()[:800],
    }


def analyze(text, reply_text=None, channel=None):
    global _client
    if _client is None:
        _client = brain.make_client()
    data, err = brain.analyze_signal(_client, text, reply_text, channel, model=MODEL)
    return (normalize(data) if data is not None else None), err


def latest_price():
    """天覆陣累積嘅最新 M1 收市價。回傳 (price, age_sec) 或 (None, 原因)。"""
    try:
        m1 = storage.read_json(M1_FILE, [])
    except StorageError as exc:
        return None, f"讀取 M1 失敗：{exc}"
    if not m1:
        return None, "未有 M1 歷史"
    bar = m1[-1]
    return bar["close"], now_ts() - (bar["time"] + 60)


def check(sig, price, price_age):
    """下單前檢查。回傳 (ok, 原因, plan)。plan = {side, stop, target}（絕對價）。純函數。"""
    if sig.get("kind") != "new_signal":
        return False, "唔係新開倉訊號", None
    if not is_gold(sig.get("symbol")):
        return False, f"商品 {sig.get('symbol') or '未知'} 唔係黃金，系統只送 {config.SYMBOL}", None
    side, sl = sig.get("side"), sig.get("sl")
    if side not in ("BUY", "SELL"):
        return False, "缺方向", None
    if sl is None or sl <= 0:
        return False, "訊號冇止損，唔提供下單", None
    if price is None:
        return False, f"冇最新價（{price_age}）", None
    if price_age > PRICE_MAX_AGE_SEC:
        return False, f"最新價已過 {int(price_age)} 秒（上限 {PRICE_MAX_AGE_SEC}），EA 可能離線或休市", None
    lo, hi = sig.get("entry_low"), sig.get("entry_high")
    if lo is not None and hi is not None and (price < lo - MAX_DRIFT_USD or price > hi + MAX_DRIFT_USD):
        return False, f"現價 {price:.2f} 離入場 {lo:g}–{hi:g} 超過 {MAX_DRIFT_USD:g} 美元", None
    sl_distance = round(price - sl, 2) if side == "BUY" else round(sl - price, 2)
    if sl_distance <= 0:
        return False, f"止損 {sl:g} 已在現價 {price:.2f} 錯邊（已觸發）", None
    if sl_distance > MAX_SL_USD:
        return False, f"止損距離 {sl_distance:.2f} 美元超過上限 {MAX_SL_USD:g}", None
    target = None
    for tp in sig.get("tp") or []:
        if (tp - price if side == "BUY" else price - tp) > 0:
            target = tp
            break
    if sig.get("tp") and target is None:
        return False, f"所有止賺 {sig['tp']} 已喺現價 {price:.2f} 錯邊（行情已走完）", None
    return True, "", {"side": side, "stop": round(sl, 2), "target": target, "sl_distance": sl_distance}


def mode_block():
    """天覆陣模式唔係 RUN 就唔送：STOP／PAUSE（日蝕、保證金、使用者）。回傳原因或 None。"""
    try:
        ctl = storage.read_json(CONTROL_FILE, {}) or {}
    except StorageError as exc:
        return f"control.json 讀取失敗：{exc}"
    mode = ctl.get("mode", "RUN")
    return None if mode == "RUN" else f"天覆陣模式 {mode}（{ctl.get('reason') or ''}）"


def lots():
    return max(0.01, min(round(LOTS, 2), round(MAX_LOTS, 2)))


def message(rec):
    sig = rec.get("analysis") or {}
    lines = [f"📨 頻道訊號｜{rec.get('channel') or '未知頻道'}", "", (rec.get("text") or "")[:900], "", "🤖 解析"]
    if sig:
        entry = "市價" if sig.get("entry_low") is None else (
            f"{sig['entry_low']:g}" if sig["entry_low"] == sig["entry_high"] else f"{sig['entry_low']:g}–{sig['entry_high']:g}")
        lines.append(f"種類 {sig.get('kind')}｜{sig.get('symbol') or '—'} {sig.get('side') or '—'}｜入場 {entry}"
                     f"｜止損 {sig.get('sl') if sig.get('sl') is not None else '—'}"
                     f"｜止賺 {', '.join(f'{t:g}' for t in sig.get('tp') or []) or '—'}")
        if sig.get("update_action"):
            lines.append(f"管理指示：{sig['update_action']}")
        if sig.get("confidence") is not None:
            lines.append(f"解析把握 {sig['confidence']:.0%}")
        if sig.get("analysis"):
            lines.append(sig["analysis"])
    else:
        lines.append(f"解析失敗：{rec.get('error') or '未知'}")
    pre = rec.get("precheck") or {}
    lines.append("")
    if pre.get("ok"):
        plan = pre["plan"]
        lines.append(f"📋 若確認：{plan['side']} {lots():.2f} 手 {config.SYMBOL}｜現價 {pre['price']:.2f}"
                     f"｜止損 {plan['stop']}（距離 {plan['sl_distance']:.2f}）｜止賺 {plan['target'] or '不送'}"
                     + ("" if config.EXECUTE else "｜⚠ 影子模式：指令唔會送到 EA"))
        lines.append(f"⏳ {CONFIRM_TTL_SEC // 60} 分鐘內有效；按確認時會用當時最新價重新檢查。")
    else:
        lines.append(f"🚫 唔提供下單：{pre.get('reason') or '—'}")
    return "\n".join(lines)[:4000]


def save(sid, mutate_fn):
    return storage.update(f"{PREFIX}{sid}.json", mutate_fn, default_factory=dict)


def handle_signal(payload):
    """VM 監聽腳本推上嚟嘅頻道訊息。"""
    text = str(payload.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        return jsonify({"status": "ignored", "message": "empty text"}), 200
    sid = sid_of(payload.get("channel_id"), payload.get("msg_id"), payload.get("edit_ts"))
    now = now_ts()
    rec = {"sid": sid, "status": "analyzing", "channel": str(payload.get("channel") or "")[:80],
           "channel_id": str(payload.get("channel_id") or "")[:32], "msg_id": payload.get("msg_id"),
           "msg_date": str(payload.get("date") or "")[:32], "text": text,
           "reply_text": str(payload.get("reply_text") or "")[:1500] or None, "received_ts": now,
           "received_utc": market.fmt_utc(now)}
    try:
        claimed = save(sid, lambda d: (None, False) if d else (rec, True))
    except StorageError as exc:
        return jsonify({"status": "error", "message": f"storage: {exc}"}), 500
    if not claimed:
        return jsonify({"status": "duplicate", "sid": sid}), 200

    sig, err = analyze(text, rec["reply_text"], rec["channel"])
    rec.update(analysis=sig, error=err)
    if sig and sig["kind"] == "new_signal":
        price, age = latest_price()
        ok, why, plan = check(sig, price, age)
        block = mode_block() if ok else None
        if not ORDER_ENABLED:
            ok, why = False, "TG_SIGNAL_ORDER_ENABLED=0（只分析，唔送單）"
        elif block:
            ok, why = False, block
        rec["precheck"] = {"ok": ok, "reason": why, "plan": plan, "price": price}
    else:
        rec["precheck"] = {"ok": False, "reason": "AI 解析失敗" if err else "唔係新開倉訊號（只供參考）"}
    rec["status"] = "pending" if rec["precheck"]["ok"] else "info"

    if sig is None or sig["kind"] != "other" or NOTIFY_ALL:
        body = {"chat_id": os.environ.get("TG_SIGNAL_CHAT_ID", "").strip(), "text": message(rec), "disable_web_page_preview": True}
        if rec["status"] == "pending":
            body["reply_markup"] = {"inline_keyboard": [[{"text": "✅ 確認下單", "callback_data": f"tgs:ok:{sid}"},
                                                         {"text": "❌ 略過", "callback_data": f"tgs:no:{sid}"}]]}
        sent = tg_api("sendMessage", body)
        rec["tg_message_id"] = ((sent or {}).get("result") or {}).get("message_id")
        rec["notified"] = bool(sent and sent.get("ok"))
    try:
        save(sid, lambda d: ({**d, **rec}, None))
    except StorageError as exc:
        print(f"⚠️ [頻道訊號寫入失敗] {exc}", flush=True)
    log_event(f"📨 [頻道訊號] {rec['channel']} #{rec['msg_id']} → {sig['kind'] if sig else 'AI 失敗'}｜{rec['status']}"
              f"｜{rec['precheck'].get('reason') or '可確認'}", component="tg_signal", sid=sid)
    return jsonify({"status": "stored", "sid": sid, "kind": sig["kind"] if sig else None,
                    "confirmable": rec["status"] == "pending", "notified": rec.get("notified", False)}), 200


def send_order(rec):
    """確認後排 EA 指令。回傳 (status, 給使用者的一句話)。"""
    sig = rec.get("analysis") or {}
    now = now_ts()
    if now - market.to_float(rec.get("received_ts"), 0.0) > CONFIRM_TTL_SEC:
        return "expired", f"已超過 {CONFIRM_TTL_SEC // 60} 分鐘，作廢"
    if not ORDER_ENABLED:
        return "disabled", "TG_SIGNAL_ORDER_ENABLED=0，唔送單"
    block = mode_block()
    if block:
        return "rejected", block
    price, age = latest_price()
    ok, why, plan = check(sig, price, age)
    if not ok:
        return "rejected", why
    cmd_id = uuid.uuid4().hex

    live_pos = None
    if config.EXECUTE:
        try:
            live_pos = (storage.read_json(config.PREFIX + "account.json", {}) or {}).get("positions") or []
        except StorageError:
            live_pos = []

    def mutate(state):
        if state.get("position") or live_pos:
            return None, None
        text = executor.enqueue(state, "OPEN_LONG" if plan["side"] == "BUY" else "OPEN_SHORT", plan["stop"], plan["target"],
                                now, cmd_id, lots=lots(), tag=f"tg:{rec.get('sid')}")
        return state, text
    try:
        text = storage.update(STATE_FILE, mutate, default_factory=dict)
    except StorageError as exc:
        return "error", f"狀態寫入失敗：{exc}"
    if text is None:
        return "rejected", "天覆陣已有倉位（最多 1 張）"
    summary = f"{plan['side']} {lots():.2f} 手 {config.SYMBOL} @≈{price:.2f}｜止損 {plan['stop']}｜止賺 {plan['target'] or '不送'}"
    log_event(f"✅ [頻道訊號已排指令] {rec.get('channel')} #{rec.get('msg_id')}｜{summary}｜{text}", component="tg_signal")
    if not config.EXECUTE:
        return "queued_shadow", f"已排指令但影子模式（XAU_EXECUTE=0），唔會送到 EA｜{summary}"
    return "queued", f"已排指令，EA 下一個心跳執行｜{summary}"


def handle_callback(request):
    """Telegram 訊號確認 bot 的 webhook（?tg=signal）。只處理白名單 chat／使用者的按鈕。"""
    secret = os.environ.get("TG_SIGNAL_WEBHOOK_SECRET", "").strip()
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
        return jsonify({"status": "error", "message": "forbidden"}), 403
    update = request.get_json(force=True, silent=True) or {}
    cq = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else None
    if not cq:
        return jsonify({"status": "ignored"}), 200
    chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id") or "")
    user_id = str((cq.get("from") or {}).get("id") or "")
    allowed_chat = os.environ.get("TG_SIGNAL_CHAT_ID", "").strip()
    allowed_users = {u.strip() for u in os.environ.get("TG_SIGNAL_ALLOWED_USERS", "").split(",") if u.strip()} or {allowed_chat}
    answer = lambda txt: tg_api("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": txt[:190]})  # noqa: E731
    if not allowed_chat or chat_id != allowed_chat or user_id not in allowed_users:
        log_event(f"🚫 [頻道訊號] 非白名單按鈕 chat={chat_id} user={user_id}", severity="WARNING", component="tg_signal")
        answer("無權限")
        return jsonify({"status": "forbidden"}), 200
    parts = str(cq.get("data") or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "tgs" or parts[1] not in ("ok", "no"):
        answer("未知按鈕")
        return jsonify({"status": "ignored"}), 200
    sid, want = parts[2], parts[1]
    now = now_ts()

    def claim(d):
        if not d:
            return None, "missing"
        if d.get("status") != "pending":
            return None, d.get("status")
        return {**d, "status": "sending" if want == "ok" else "skipped", "decided_utc": market.fmt_utc(now), "decided_by": user_id}, "claimed"
    try:
        claimed = save(sid, claim)
    except StorageError as exc:
        answer("儲存失敗，未送單")
        return jsonify({"status": "error", "message": str(exc)[:100]}), 200
    if claimed != "claimed":
        answer(f"已處理過（{claimed}）")
        return jsonify({"status": "duplicate", "state": claimed}), 200
    if want == "no":
        result, msg = "skipped", "已略過"
    else:
        rec = storage.read_json(f"{PREFIX}{sid}.json", {})
        try:
            result, msg = send_order(rec)
        except Exception as exc:  # noqa: BLE001  唔好令 Telegram 重送 → 重複落單
            result, msg = "error", f"處理異常：{type(exc).__name__}"
            log_event(f"💥 [頻道訊號] {type(exc).__name__}: {exc}", severity="ERROR", component="tg_signal")
    try:
        save(sid, lambda d: ({**d, "status": result, "result": msg, "done_utc": market.fmt_utc(now)}, None))
    except StorageError as exc:
        print(f"⚠️ [頻道訊號結果寫入失敗] {exc}", flush=True)
    answer(msg)
    msg_id = (cq.get("message") or {}).get("message_id")
    if msg_id:
        tg_api("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})
        tg_api("sendMessage", {"chat_id": chat_id, "text": f"{'✅' if result.startswith('queued') else 'ℹ️'} {msg}", "reply_to_message_id": msg_id})
    return jsonify({"status": result}), 200
