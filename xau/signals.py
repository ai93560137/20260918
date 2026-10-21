"""📨 訊號書 S0：外部 Telegram 訊號 → 驗證簽名 → Haiku 解析 → 驗證 → 存 GCS（唔問 Opus、唔落單）。

使用者 10-21 揀方案 B（xau/TG_SIGNAL_PROPOSAL.md）：VM 上嘅 tg_relay/tg_listener.py 用使用者 TG 帳戶讀白名單頻道，
POST 到訊號書服務（XAU_BOOK=signal）。訊號只係 Claude 決策嘅參考資料（S1 先接入決策），原文唔會入 Opus prompt。

安全：
- 入口用 TG_SIGNAL_INGEST_SECRET 做 HMAC-SHA256（hmac.compare_digest、時間戳 ±SIG_MAX_SKEW_SEC），唔接受 WEBHOOK_SECRET_TOKEN。
- 每個容器每分鐘最多 SIG_RATE_PER_MIN 個請求；body 上限 SIG_MAX_BODY。
- 日誌只印 sid、種類、狀態；唔印原文、連結、權杖。網頁同 JSON 只顯示結構化欄位。
"""
import hashlib
import hmac
import json
import re
import threading
import time
from collections import deque

from flask import jsonify

import brain
import config
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "signals/"
RECENT_FILE = PREFIX + "recent.json"
LISTENER_FILE = config.PREFIX + "listener.json"
MAIN_M1_FILE = config.MAIN_PREFIX + "m1.json"
MAX_TEXT = 4000
GOLD_ALIASES = ("XAUUSD", "XAU", "GOLD", "黃金", "黄金")
now_ts = time.time
_client = None
_rate = deque()
_rate_lock = threading.Lock()


def log_event(message, severity="INFO", **fields):
    print(json.dumps({"severity": severity, "message": message, "component": "signal_book", **fields},
                     ensure_ascii=False, default=str), flush=True)


# ---------- 入口：簽名、速率 ----------
def sign(secret, ts, body: bytes):
    """VM 同服務共用：hex(HMAC-SHA256(secret, f"{ts}." + body))。"""
    return hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(headers, body: bytes, now=None):
    """回傳 (ok, 原因)。常數時間比較；冇設密鑰一律拒絕。"""
    secret = config.SIG_INGEST_SECRET
    if not secret:
        return False, "TG_SIGNAL_INGEST_SECRET 未設定"
    ts, given = headers.get("X-Sig-Ts", ""), headers.get("X-Sig-Signature", "")
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return False, "bad timestamp"
    if abs((now if now is not None else now_ts()) - ts_i) > config.SIG_MAX_SKEW_SEC:
        return False, "stale timestamp"
    if not hmac.compare_digest(str(given).encode(), sign(secret, ts_i, body).encode()):
        return False, "bad signature"
    return True, ""


def rate_ok(now=None):
    now = now if now is not None else now_ts()
    with _rate_lock:
        while _rate and now - _rate[0] > 60:
            _rate.popleft()
        if len(_rate) >= config.SIG_RATE_PER_MIN:
            return False
        _rate.append(now)
        return True


# ---------- 解析、驗證（純函數為主） ----------
def sid_of(channel_id, msg_id, edit_ts=None):
    cid = re.sub(r"[^0-9A-Za-z]", "", str(channel_id or "x"))[:24] or "x"
    mid = re.sub(r"[^0-9]", "", str(msg_id or ""))[:12] or "0"
    return f"{cid}_{mid}" + (f"_e{int(edit_ts)}" if edit_ts else "")


def symbol_matches(symbol):
    s = re.sub(r"[^0-9A-Z黃黄金]", "", str(symbol or "").upper())
    if not s:
        return False
    if config.PRODUCT_KIND == "gold":
        return any(s == a or s.startswith(a) for a in GOLD_ALIASES)
    return s == config.SYMBOL


def normalize(raw):
    """AI 輸出夾成固定欄位；數字一律 to_float。analysis 只存檔，唔畀決策用。"""
    raw = raw if isinstance(raw, dict) else {}
    f = market.to_float
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(str(raw.get("side") or "").strip().upper(), str(raw.get("side") or "").strip().upper())
    lo, hi = f(raw.get("entry_low")), f(raw.get("entry_high"))
    lo, hi = (lo if lo is not None else hi), (hi if hi is not None else lo)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    tps = raw.get("tp") if isinstance(raw.get("tp"), list) else [raw.get("tp")]
    kind = str(raw.get("kind") or "other").strip().lower()
    return {
        "kind": kind if kind in ("new_signal", "update", "other") else "other",
        "symbol": str(raw.get("symbol") or "").strip().upper()[:16] or None,
        "side": side if side in ("BUY", "SELL") else None,
        "entry_low": lo, "entry_high": hi, "sl": f(raw.get("sl")),
        "tp": [v for v in (f(t) for t in tps) if v is not None and v > 0][:5],
        "update_action": str(raw.get("update_action") or "").strip()[:200] or None,
        "confidence": f(raw.get("confidence")),
        "analysis": str(raw.get("analysis") or "").strip()[:800],
    }


def validate(sig, price, price_age):
    """回傳 (status, 原因)。status：valid／unverified（冇新鮮價）／invalid／info（唔係開倉訊號）。純函數。"""
    if sig.get("kind") != "new_signal":
        return "info", "唔係新開倉訊號（管理指示或閒聊，只供參考）"
    if not (symbol_matches(sig.get("symbol")) or (config.SIG_ASSUME_SYMBOL and not sig.get("symbol"))):
        return "invalid", f"商品 {sig.get('symbol') or '未知'} 唔係 {config.SYMBOL}"
    side, sl = sig.get("side"), sig.get("sl")
    if side not in ("BUY", "SELL"):
        return "invalid", "缺方向"
    if sl is None or sl <= 0:
        return "invalid", "冇止損"
    tps = sig.get("tp") or []
    lo, hi = sig.get("entry_low"), sig.get("entry_high")
    ref = (lo + hi) / 2 if lo is not None else None
    if ref is not None:                                    # 唔靠現價都可以查嘅一致性
        if (side == "BUY" and sl >= ref) or (side == "SELL" and sl <= ref):
            return "invalid", "止損喺入場錯邊"
        if tps and ((side == "BUY" and tps[0] <= ref) or (side == "SELL" and tps[0] >= ref)):
            return "invalid", "止賺喺入場錯邊"
    if price is None or price_age is None or price_age > config.SIG_PRICE_MAX_AGE_SEC:
        return "unverified", "冇新鮮價（主服務 M1 太舊或休市）"
    if lo is not None and (price < lo - config.SIG_MAX_DRIFT or price > hi + config.SIG_MAX_DRIFT):
        return "invalid", f"現價離入場區超過 {config.SIG_MAX_DRIFT:g}"
    dist = price - sl if side == "BUY" else sl - price
    if dist <= 0:
        return "invalid", "止損已經觸發"
    if dist > config.SIG_MAX_SL:
        return "invalid", f"止損距離 {dist:.{config.PRICE_DIGITS}f} 超過 {config.SIG_MAX_SL:g}"
    return "valid", ""


def msg_time(payload, received):
    """訊息時間（epoch）；解唔到就用收到時間。"""
    raw = str(payload.get("date") or "")
    try:
        from datetime import datetime
        t = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        return t if t <= received + 60 else received
    except ValueError:
        return received


def public_view(rec):
    """網頁／JSON 用：只有結構化欄位，冇原文、冇頻道名、冇 analysis。"""
    sig = rec.get("signal") or {}
    return {"sid": rec.get("sid"), "received_utc": rec.get("received_utc"), "msg_utc": rec.get("msg_utc"),
            "valid_until_utc": rec.get("valid_until_utc"), "valid_until_ts": rec.get("valid_until_ts"), "status": rec.get("status"), "reason": rec.get("reason"),
            "kind": sig.get("kind"), "side": sig.get("side"), "entry_low": sig.get("entry_low"), "entry_high": sig.get("entry_high"),
            "sl": sig.get("sl"), "tp": sig.get("tp"), "parse_confidence": sig.get("confidence"), "price": rec.get("price"),
            "edited": bool(rec.get("edit_ts"))}


# ---------- I/O ----------
def latest_price():
    try:
        m1 = storage.read_json(MAIN_M1_FILE, [])
    except StorageError:
        return None, None
    if not m1:
        return None, None
    bar = m1[-1]
    return bar.get("close"), now_ts() - (bar["time"] + 60)


def parse(text, reply_text):
    global _client
    if _client is None:
        _client = brain.make_client()
    data, err = brain.analyze_signal(_client, text, reply_text, None, model=config.SIG_PARSE_MODEL)
    return (normalize(data) if data is not None else None), err


def handle_ingest(headers, body: bytes):
    if len(body) > config.SIG_MAX_BODY:
        return jsonify({"status": "error", "message": "too large"}), 413
    if not rate_ok():
        log_event("🚦 訊號入口超過速率上限", severity="WARNING")
        return jsonify({"status": "error", "message": "rate limited"}), 429
    ok, why = verify(headers, body)
    if not ok:
        log_event(f"🚫 訊號入口拒絕：{why}", severity="WARNING")
        return jsonify({"status": "error", "message": "forbidden"}), 403
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return jsonify({"status": "error", "message": "invalid JSON"}), 400
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "invalid payload"}), 400
    action = payload.get("action")
    if action == "tg_heartbeat":
        return handle_heartbeat(payload)
    if action == "tg_signal":
        return handle_signal(payload)
    return jsonify({"status": "ignored"}), 200


def handle_heartbeat(payload):
    now = now_ts()
    row = {"received_utc": market.fmt_utc(now), "ts": now, "version": str(payload.get("script_version") or "")[:32],
           "channels": market.to_float(payload.get("channels")), "connected": bool(payload.get("connected")),
           "forwarded": market.to_float(payload.get("forwarded")), "dropped": market.to_float(payload.get("dropped"))}
    try:
        storage.write_json(LISTENER_FILE, row)
    except StorageError as exc:
        return jsonify({"status": "error", "message": f"storage: {exc}"}), 500
    return jsonify({"status": "ok"}), 200


def handle_signal(payload):
    text = str(payload.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        return jsonify({"status": "ignored", "message": "empty text"}), 200
    now = now_ts()
    sid = sid_of(payload.get("channel_id"), payload.get("msg_id"), payload.get("edit_ts"))
    t_msg = msg_time(payload, now)
    rec = {"sid": sid, "status": "parsing", "channel_id": str(payload.get("channel_id") or "")[:32],
           "msg_id": payload.get("msg_id"), "edit_ts": payload.get("edit_ts"), "text": text,
           "reply_text": str(payload.get("reply_text") or "")[:1500] or None,
           "received_ts": now, "received_utc": market.fmt_utc(now), "msg_ts": t_msg, "msg_utc": market.fmt_utc(t_msg),
           "valid_until_ts": t_msg + config.SIG_TTL_MIN * 60, "valid_until_utc": market.fmt_utc(t_msg + config.SIG_TTL_MIN * 60)}
    try:
        claimed = storage.update(f"{PREFIX}{sid}.json", lambda d: (None, False) if d else (rec, True), default_factory=dict)
    except StorageError as exc:
        return jsonify({"status": "error", "message": f"storage: {exc}"}), 500
    if not claimed:
        return jsonify({"status": "duplicate", "sid": sid}), 200

    sig, err = parse(text, rec["reply_text"])
    price, age = latest_price()
    if sig is None:
        status, reason = "error", "解析失敗"
    elif now > rec["valid_until_ts"]:
        status, reason = "expired", "收到時已過期"
    else:
        status, reason = validate(sig, price, age)
    rec.update(signal=sig, parse_error=(err or "")[:200] or None, status=status, reason=reason,
               price=price if age is not None and age <= config.SIG_PRICE_MAX_AGE_SEC else None)
    try:
        storage.write_json(f"{PREFIX}{sid}.json", rec)
        view = public_view(rec)
        storage.update(RECENT_FILE, lambda rows: ([*(rows if isinstance(rows, list) else []), view][-config.SIG_RECENT_MAX:], None),
                       default_factory=list)
        storage.append_jsonl(f"{PREFIX}{market.ny_date(now)}.jsonl", view)
    except StorageError as exc:
        log_event(f"⚠️ 訊號寫入失敗 {sid}：{type(exc).__name__}", severity="WARNING", sid=sid)
    log_event(f"📨 訊號 {sid} → {(sig or {}).get('kind') or '解析失敗'}｜{status}", sid=sid, status=status)
    return jsonify({"status": "stored", "sid": sid, "signal_status": status}), 200


def recent(now=None):
    """網頁用：最近訊號（過期嘅 valid 顯示為 expired）同監聽心跳。"""
    now = now if now is not None else now_ts()
    try:
        rows = storage.read_json(RECENT_FILE, []) or []
        listener = storage.read_json(LISTENER_FILE, {}) or {}
    except StorageError:
        rows, listener = [], {}
    out = []
    for r in rows[-30:][::-1]:
        r = dict(r)
        if r.get("status") in ("valid", "unverified") and r.get("valid_until_ts") and r["valid_until_ts"] < now:
            r["status"] = "expired"
        out.append(r)
    age = now - listener["ts"] if listener.get("ts") else None
    return {"rows": out, "listener": {**{k: v for k, v in listener.items() if k != "ts"}, "age_sec": age}}
