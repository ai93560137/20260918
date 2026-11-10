"""[IDEAS #1125] 趨勢突破真倉簿（magic 927，…63 戶口）。預設關（XAU_TREND_LIVE=0）。只喺主服務（zhuge-xau，唔係訊號書）。
使用者 11-08：「兩個戶口一個做一類」→ 趨勢家族揀 #1107 上季突破＋#1113 低波幅 20 日突破；「跟 10 月尾 signal」→「補入 10-30 嗰張空單」（XAU_TREND_ADOPT=qbrk）。

規則（同 research/strategy_search/h1_lab6.r1107、h1_lab7.r1113 一樣，日線按 UTC 日由 M1 砌）：
  qbrk：今季第一次穿上季高（做多）／低（做空）→ SL 上季中位，季尾（最後一個平日 UTC 20:45 後）平；一季一次（穿咗就用咗，唔理有冇做到）。
  lvbrk：昨日 D1 ATR14 ≤ 過去 250 個 ATR 嘅 20% 分位 → 今日穿前 20 日高／低 → SL 20 日中位，第 10 個交易日 UTC 20:45 後平；只喺當日入。
  mobrk（#1114，11-10 使用者「選一條取代 933，開真倉」）：今個月頭 3 個交易日高／低 → 第 4 個交易日起第一次穿 → SL 另一端（做多 SL＝區間低），月尾（最後一個平日 UTC 20:45 後）平；一個月一次。
  入場用市價（回測用突破價），止蝕距離 ≤ 0.5 美元唔做。
訊號書服務（zhuge-xau-sig，…69）都可以開：XAU_TREND_LIVE=1＋XAU_TREND_MAGIC（例如 933）＋XAU_TREND_RULES=mobrk；狀態寫 xau/sig/trend/。
做法：EA 用 magic 927 掛一張 …63 XAUUSD 圖（或者 XAU_TREND_MAGIC=926 用返 926 圖：趨勢簿分流排喺 926 反向之前，921 影子照餵 K 線），心跳按 magic 分流到呢度；指令 id 前綴 w；一次一張（EA close 按 magic 全平）；SL 伺服器端即掛、冇 TP。
日線：狀態 d1 由心跳 M1 合併；冇或者唔夠就用部署模組 trend_d1_seed.py（MT5／券商 M1 砌嘅 UTC 日線）。
風控：control 非 RUN、EA 唔准交易／dry_run、927 當日蝕到 XAU_TREND_DAY_STOP_HKD、產品唔係 XAUUSD 都唔開；control＝STOP → 平。純計算函數冇 I/O。"""
import datetime as dt
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "trend/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
MAX_DAYS = 420
MAX_ORDERS = 200
NAMES = {"qbrk": "上季突破（#1107）", "lvbrk": "低波幅 20 日突破（#1113）", "mobrk": "月初三日區間突破（#1114）"}


def _m():
    import main
    return main


def enabled():
    return config.TREND_LIVE and bool(config.TREND_MAGIC)          # [11-10] 訊號書服務都可以開（要設 XAU_TREND_MAGIC）


def is_magic(payload):
    return bool(config.TREND_MAGIC) and str(payload.get("magic") or "") == str(config.TREND_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("w")


def empty_state():
    return {"d1": {}, "pos": None, "used": {}, "adopted": [], "pending_cmds": [], "orders": [], "book": [], "last": None, "pos_seen": None}


def load_state():
    base = empty_state()
    try:
        doc = storage.read_json(STATE_FILE, None)
    except StorageError:
        doc = None
    if isinstance(doc, dict):
        base.update(doc)
    return base


def load_seed():
    try:
        import trend_d1_seed
        return dict(trend_d1_seed.SEED)
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------ 純計算：日線
def d1_merge(d1, bars):
    """bars：UTC K 線 [{"t","open","high","low","close"}] → 合併入 d1（key＝UTC 日數字串）。同一根重覆嚟冇影響。純函數。"""
    d1 = {k: dict(v) for k, v in (d1 or {}).items()}
    for b in bars:
        k = str(int(b["t"]) // 86400)
        r = d1.get(k)
        if r is None:
            d1[k] = {"o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "t0": int(b["t"]), "t1": int(b["t"])}
            continue
        r["h"], r["l"] = max(r["h"], b["high"]), min(r["l"], b["low"])
        if b["t"] < r["t0"]:
            r["o"], r["t0"] = b["open"], int(b["t"])
        if b["t"] >= r["t1"]:
            r["c"], r["t1"] = b["close"], int(b["t"])
    if len(d1) > MAX_DAYS:
        for k in sorted(d1, key=int)[:-MAX_DAYS]:
            d1.pop(k)
    return d1


def days_of(d1):
    return [(int(k), d1[k]) for k in sorted(d1, key=int)]


def qkey(day):
    u = dt.datetime.fromtimestamp(int(day) * 86400, dt.timezone.utc)
    return u.year * 4 + (u.month - 1) // 3


def quarter_last_weekday(qk):
    y, q = divmod(qk, 4)
    nxt = dt.date(y + (q == 3), (q + 1) % 4 * 3 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return (d - dt.date(1970, 1, 1)).days


def mkey(day):
    u = dt.datetime.fromtimestamp(int(day) * 86400, dt.timezone.utc)
    return u.year * 12 + u.month - 1


def month_last_weekday(mk):
    y, m0 = divmod(mk, 12)
    nxt = dt.date(y + (m0 == 11), (m0 + 1) % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return (d - dt.date(1970, 1, 1)).days


def mobrk_levels(days, today):
    """今個月頭 3 個交易日嘅高低；未夠 3 日或者今日仲係頭 3 日 → None。"""
    cur = [(d, r) for d, r in days if mkey(d) == mkey(today)]
    if len(cur) < 4 or today <= cur[2][0]:
        return None
    first = [r for _, r in cur[:3]]
    return max(r["h"] for r in first), min(r["l"] for r in first), cur[2][0]


def mobrk_signal(days, today, used):
    """[IDEAS #1114] 第 4 個交易日起第一次穿頭 3 日高（做多，SL 區間低）／低（做空，SL 區間高）；一個月一次。同 research h1_lab8.r1114。"""
    mk = mkey(today)
    if used.get("mobrk") == mk:
        return None
    lv = mobrk_levels(days, today)
    if lv is None:
        return None
    hi, lo, d3 = lv
    for d, r in days:
        if mkey(d) == mk and d3 < d < today and _break(r, hi, lo):
            return {"rule": "mobrk", "period": mk, "used_only": True}        # 今個月早過今日已經穿咗
    r = dict(days).get(today)
    if r is None:
        return None
    sg = _break(r, hi, lo)
    if not sg:
        return None
    return {"rule": "mobrk", "side": sg, "sl": round(lo if sg > 0 else hi, 2), "period": mk, "level": hi if sg > 0 else lo}


def atr_list(days, n=14):
    """同 batch_1019.atr：TR 用上日收市（第一日用自己收市），ATR[i]＝最近 n 個 TR 平均（i ≥ n 先有）。"""
    out, tr = [], []
    for i, (_, r) in enumerate(days):
        pc = days[i - 1][1]["c"] if i else r["c"]
        tr.append(max(r["h"] - r["l"], abs(r["h"] - pc), abs(r["l"] - pc)))
        out.append(sum(tr[i - n + 1:i + 1]) / n if i >= n else None)
    return out


def quantile(xs, q):
    """同 numpy.quantile 預設（linear）。"""
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _break(r, hi, lo):
    up, dn = r["h"] >= hi, r["l"] <= lo
    if not (up or dn):
        return 0
    return 1 if up else -1                       # 同一日兩邊都穿：同回測一樣當做多


def qbrk_levels(days, today):
    prev = [r for d, r in days if qkey(d) == qkey(today) - 1]
    if not prev:
        return None
    hi, lo = max(r["h"] for r in prev), min(r["l"] for r in prev)
    return hi, lo, (hi + lo) / 2


def qbrk_signal(days, today, used):
    """今季第一次穿上季高低 → {"rule","side","sl","period"}；已用／未穿／冇上季數據 → None。days 包今日（今日 h／l 計到而家）。"""
    qk = qkey(today)
    if used.get("qbrk") == qk:
        return None
    lv = qbrk_levels(days, today)
    if lv is None:
        return None
    hi, lo, mid = lv
    for d, r in days:
        if qkey(d) == qk and d < today and _break(r, hi, lo):
            return {"rule": "qbrk", "period": qk, "used_only": True}          # 今季早過今日已經穿咗
    r = dict(days)[today] if today in dict(days) else None
    if r is None:
        return None
    sg = _break(r, hi, lo)
    if not sg:
        return None
    return {"rule": "qbrk", "side": sg, "sl": round(mid, 2), "period": qk, "level": hi if sg > 0 else lo}


def qbrk_adopt(days, today):
    """補入（使用者揀）：今季已經穿咗、仲未掂上季中位（未止蝕）→ {"rule","side","sl","period","since"}；否則 None。"""
    qk = qkey(today)
    lv = qbrk_levels(days, today)
    if lv is None:
        return None
    hi, lo, mid = lv
    cur = [(d, r) for d, r in days if qkey(d) == qk]
    for i, (d, r) in enumerate(cur):
        sg = _break(r, hi, lo)
        if not sg:
            continue
        stopped = any((x["l"] <= mid) if sg > 0 else (x["h"] >= mid) for _, x in cur[i:])
        return None if stopped else {"rule": "qbrk", "side": sg, "sl": round(mid, 2), "period": qk, "since": d, "adopt": True}
    return None


def lvbrk_signal(days, today, used):
    """昨日 ATR14 喺一年 20% 分位以下 → 今日穿前 20 日高低。days 最後一日要係今日。"""
    if used.get("lvbrk") == today or not days or days[-1][0] != today:
        return None
    prev = days[:-1]
    if len(prev) < 264:
        return None
    a = atr_list(prev)
    k = len(prev) - 1
    w = a[k - 249:k + 1]
    if any(x is None for x in w) or a[k] > quantile(w, 0.2):
        return None
    hi, lo = max(r["h"] for _, r in prev[-20:]), min(r["l"] for _, r in prev[-20:])
    sg = _break(days[-1][1], hi, lo)
    if not sg:
        return None
    return {"rule": "lvbrk", "side": sg, "sl": round((hi + lo) / 2, 2), "period": today, "level": hi if sg > 0 else lo}


def exit_due(pos, days, now):
    """到期平倉嘅原因或 None。qbrk：季尾最後一個平日 UTC ≥ 20:45，或者已經入咗下季；lvbrk：第 10 個交易日 UTC ≥ 20:45，或者第 11 日。"""
    if not pos or not days:
        return None
    today = days[-1][0]
    late = (int(now) % 86400) // 60 >= config.TREND_EXIT_UTC_MIN
    if pos.get("rule") == "qbrk":
        qk = int(pos.get("period") or 0)
        if qkey(today) > qk:
            return "季尾已過，平"
        if today >= quarter_last_weekday(qk) and late:
            return "季尾收市平"
        return None
    if pos.get("rule") == "mobrk":
        mk = int(pos.get("period") or 0)
        if mkey(today) > mk:
            return "月尾已過，平"
        if today >= month_last_weekday(mk) and late:
            return "月尾收市平"
        return None
    if pos.get("rule") == "lvbrk":
        idx = [d for d, _ in days]
        e0 = int(pos.get("period") or 0)
        n = sum(1 for d in idx if d >= e0)                # 入場日都計
        if n >= 11 or (n >= 10 and late):
            return "第 10 個交易日收市平"
    return None


def open_block(control_mode, account):
    if control_mode != "RUN":
        return f"control＝{control_mode}"
    if account.get("dry_run"):
        return "EA dry_run"
    ta = account.get("trade_allowed")
    if isinstance(ta, dict) and not all(bool(v) for v in ta.values()):
        return "EA 唔准交易"
    day = account.get("daily_pnl")
    if config.TREND_DAY_STOP_HKD and day is not None and day <= -abs(config.TREND_DAY_STOP_HKD):
        return f"{config.TREND_MAGIC} 今日 {day:+.0f} HKD ≤ −{config.TREND_DAY_STOP_HKD:g}"
    return None


def lots():
    return max(0.01, min(float(config.TREND_LOTS), float(config.TREND_MAX_LOTS)))


def plan(state, days, pos, price, now, block, pending):
    """→ (動作, 說明)。動作：None、("open", sig)、("close", reason)、("used", sig)。純函數（唔改 state）。"""
    if not days:
        return None, "冇日線"
    today = days[-1][0]
    if pos or state.get("pos"):
        why = exit_due(state.get("pos") or {"rule": None}, days, now)
        if pos and why and not pending:
            return ("close", why), why
        return None, "有倉（SL 伺服器端；到期平）" if pos else "等倉位回報"
    if pending:
        return None, "排緊指令"
    age = last_bar_age(state.get("d1"), now)
    if age is None or age > STALE_SEC:
        return None, "休市／K 線唔新鮮，唔開新倉"
    if recent_reject(state, now):
        return None, f"啱啱開倉被拒，{RETRY_SEC // 60} 分鐘後再試"
    used = state.get("used") or {}
    for rule in config.TREND_RULES:
        if rule == "qbrk" and "qbrk" in config.TREND_ADOPT and qkey(today) not in (state.get("adopted") or []):
            sig = qbrk_adopt(days, today)
            if sig and not exit_due({"rule": "qbrk", "period": sig["period"]}, days, now):
                return (None, f"補入 {NAMES['qbrk']} 等緊：{block}") if block else (("open", sig), "補入 10 月尾上季突破")
        sig = (qbrk_signal(days, today, used) if rule == "qbrk" else lvbrk_signal(days, today, used) if rule == "lvbrk"
               else mobrk_signal(days, today, used) if rule == "mobrk" else None)
        if not sig:
            continue
        if sig.get("used_only"):
            return ("used", sig), f"{NAMES[rule]} 今期已經用咗"
        risk = (price - sig["sl"]) * sig["side"] if price else 0
        if risk <= 0.5:
            return ("used", sig), f"{NAMES[rule]} 止蝕距離 {risk:.2f} ≤ 0.5，唔做"
        if block:
            return None, f"{NAMES[rule]} 有訊號但暫時唔開：{block}"
        return ("open", sig), f"{NAMES[rule]} 突破"
    cur = {"mobrk": mkey(today), "qbrk": qkey(today)}
    if config.TREND_RULES and all(r in cur and used.get(r) == cur[r] for r in config.TREND_RULES):
        return None, "冇倉；今期已用，等下一期"
    return None, (f"冇倉；{block}" if block else "冇倉，等突破")


STALE_SEC = 300          # 最新 M1 收市超過 5 分鐘＝休市／冇數據：唔開新倉
RETRY_SEC = 600          # 開倉被 EA 拒絕之後 10 分鐘內唔再試


def revert_failed(state):
    """EA 拒絕嘅開倉（ok=False，例如休市 market closed）唔算用咗：撤返 used／adopted，等下次再試。改 state，回傳撤咗幾多張。"""
    n = 0
    for o in state.get("orders") or []:
        if o.get("kind") != "open" or not o.get("acked") or o.get("ok") or o.get("reverted"):
            continue
        rule = o.get("rule")
        period = o.get("period")
        if period is None:                               # 舊單冇記 period：qbrk 用季、lvbrk 用日
            day = int(float(o.get("ts") or 0)) // 86400
            period = qkey(day) if rule == "qbrk" else mkey(day) if rule == "mobrk" else day
        used = dict(state.get("used") or {})
        if used.get(rule) == period:
            used.pop(rule)
            state["used"] = used
        if rule == "qbrk":
            state["adopted"] = [x for x in (state.get("adopted") or []) if x != period]
        o["reverted"] = True
        n += 1
    return n


def last_bar_age(d1, now):
    days = days_of(d1 or {})
    return (now - (days[-1][1]["t1"] + 60)) if days else None


def recent_reject(state, now):
    return any(o.get("kind") == "open" and o.get("acked") and not o.get("ok") and now - float(o.get("ts") or 0) < RETRY_SEC
               for o in (state.get("orders") or []))


# ------------------------------------------------------------------ 回報／狀態
def cmd_text(state, now):
    if not config.TREND_LIVE:
        return ""
    return "\n".join(c["text"] for c in (state.get("pending_cmds") or [])
                     if (not c.get("acked") or now < (c.get("resend_until") or 0)) and now - c["ts"] < executor.CMD_TTL_SEC)


def _pending(state, now):
    return any((not c.get("acked")) and now - c["ts"] < executor.CMD_TTL_SEC for c in (state.get("pending_cmds") or []))


def ack(cid, payload, now):
    def mutate(state):
        found = executor.ack(state, cid, payload, now)
        for o in state.get("orders") or []:
            if o.get("id") == cid:
                o.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"), message=str(payload.get("message") or "")[:120])
                if o.get("kind") == "open" and not payload.get("ok"):
                    state["pos"] = None                  # 開唔到：唔當有倉
                    revert_failed(state)                 # 唔當用咗訊號（例如休市被拒），開市再試
        return (state if found else None), found
    return storage.update(STATE_FILE, mutate, default_factory=empty_state)


def status():
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    days = days_of(st.get("d1") or {})
    levels = {}
    if days and "mobrk" in config.TREND_RULES:                     # [11-10] 網頁顯示今個月頭 3 日區間
        today = days[-1][0]; mk = mkey(today); lv = mobrk_levels(days, today)
        levels["mobrk"] = {"month": f"{mk // 12}-{mk % 12 + 1:02d}", "used": (st.get("used") or {}).get("mobrk") == mk,
                           "hi": lv[0] if lv else None, "lo": lv[1] if lv else None}
    return {"on": enabled(), "levels": levels, "names": {k: NAMES.get(k, k) for k in config.TREND_RULES}, "magic": config.TREND_MAGIC, "rules": list(config.TREND_RULES), "adopt": list(config.TREND_ADOPT), "lots": lots(),
            "d1_days": len(days), "d1_last": days[-1][0] if days else None, "pos": st.get("pos"), "used": st.get("used"),
            "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "trade_allowed", "dry_run")},
            "orders": [{**o, "id": executor.mask_id(o.get("id"))} for o in (st.get("orders") or [])[-20:][::-1]],
            "book": (st.get("book") or [])[-50:][::-1], "last": st.get("last"),
            "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}


def _unseen_meta(state):
    """[11-09] 心跳之間開完又平（冇見過倉位）：用最近一張成功、未入簿嘅開倉單補資料。"""
    last_close = max((b.get("closed_ts") or 0 for b in state.get("book") or []), default=0)
    o = next((x for x in reversed(state.get("orders") or []) if x.get("kind") == "open" and x.get("acked") and x.get("ok")
              and not x.get("booked") and (x.get("ts") or 0) > last_close), None)
    if not o:
        return None
    o["booked"] = True
    return {"ticket": o.get("ticket"), "side": o.get("side"), "lots": o.get("lots"), "entry": o.get("price"), "stop": o.get("sl"),
            "opened_ts": o.get("ts"), "ch": "趨勢" + str(o.get("rule") or ""), "decision_price": o.get("price"), "id": o.get("id")}


def _enqueue(m, state, kind, now, price, reason, sig=None, n_lots=None):
    cid = "w" + uuid.uuid4().hex[:7]
    if kind == "open":
        text = executor.enqueue(state, "OPEN_LONG" if sig["side"] > 0 else "OPEN_SHORT", sig["sl"], None, now, cid, lots=n_lots,
                                magic=config.TREND_MAGIC, note="趨勢" + sig["rule"])
    else:
        text = executor.enqueue(state, "CLOSE", None, None, now, cid, magic=config.TREND_MAGIC)
    state["orders"] = [*state.get("orders", []), {"id": cid, "kind": kind, "ts": now, "utc": market.fmt_utc(now), "price": price,
                                                  "rule": (sig or {}).get("rule"), "side": (sig or {}).get("side"), "sl": (sig or {}).get("sl"),
                                                  "period": (sig or {}).get("period"), "adopt": bool((sig or {}).get("adopt")),
                                                  "lots": n_lots, "reason": reason, "applied": text, "acked": False}][-MAX_ORDERS:]
    m.log_event(f"📈 [{config.TEAM_NAME}] 趨勢簿 {kind} {reason}｜{text}", component="trend", cmd=cid)
    return text


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.TREND_ACCOUNT and str(payload.get("account") or "").strip() != config.TREND_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    m.shadow_feed(payload, now)                          # 用返 926 圖（XAU_TREND_MAGIC=926）時 921 影子照用呢張圖嘅 K 線（同 reverse_live 一樣；921 心跳新鮮就唔用）
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.TREND_MAGIC,
                   symbol=str(payload.get("symbol") or "")[:16], product_ok=m.product_ok(payload))
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ 趨勢簿戶口快照寫入失敗：{exc}", severity="WARNING")
    state = load_state()
    bars = market.parse_hist(payload.get("m1_hist"))
    b = market.parse_bar(payload.get("m1_ohlc"))
    if b:
        bars.append(b)
    price = b["close"] if b else None
    if account["product_ok"] and bars:
        d1 = state.get("d1") or {}
        if len(d1) < 270:
            d1 = {**load_seed(), **d1}
        state["d1"] = d1_merge(d1, [{"t": x["time"] - offset, **{k: x[k] for k in ("open", "high", "low", "close")}} for x in bars])
    import live_book
    pos = (account.get("positions") or [None])[0]
    try:
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now,
                                 extra=lambda p: {"ch": "趨勢" + str((state.get("pos") or {}).get("rule") or "")},
                                 unseen=lambda: _unseen_meta(state)):
            m.log_event(f"📗 [{config.TEAM_NAME}] 趨勢簿平倉 {t['pnl_hkd']:+.2f} HKD", component="trend")
    except Exception as exc:  # noqa: BLE001
        m.log_event(f"⚠️ 趨勢簿成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING", component="trend")
    if revert_failed(state):                               # 包括部署前已經被拒嘅舊單（11-08 21:08 休市補入）
        m.log_event(f"📈 [{config.TEAM_NAME}] 趨勢簿：之前被 EA 拒絕嘅開倉唔當用咗，開市再試", component="trend")
    sp = state.get("pos") or {}
    if sp and not pos and not _pending(state, now) and (state.get("pos_seen") or now - float(sp.get("ts") or 0) > 600):
        state["pos"] = None                                # 伺服器端止蝕／到期平咗
    state["pos_seen"] = pos
    if not enabled():
        why = "趨勢簿未開（XAU_TREND_LIVE=0）"
    elif not account["product_ok"]:
        why = f"⚠ {config.TREND_MAGIC} 圖唔係 {config.SYMBOL}（symbol={account['symbol'] or '冇報'}）：唔出指令"
    else:
        why = _decide(m, state, account, pos, price, now)
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        m.log_event(f"⚠️ 趨勢簿狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "trend", "magic": config.TREND_MAGIC,
                      "mode": "live" if config.TREND_LIVE else "off", "cmd_text": cmd_text(state, now), "message": why}), 200


def _decide(m, state, account, pos, price, now):
    control = m.load_control()
    if control.get("mode") == "STOP" and pos and not _pending(state, now):
        _enqueue(m, state, "close", now, price, "control＝STOP")
        return "control＝STOP，排平倉"
    days = days_of(state.get("d1") or {})
    act, why = plan(state, days, pos, price, now, open_block(control.get("mode"), account), _pending(state, now))
    if not act:
        return why
    kind, arg = act
    if kind == "close":
        _enqueue(m, state, "close", now, price, arg)
        return f"平倉（{arg}）"
    sig = arg
    state["used"] = {**(state.get("used") or {}), sig["rule"]: sig["period"]}
    if sig.get("adopt"):
        state["adopted"] = [*(state.get("adopted") or []), sig["period"]][-8:]
    if kind == "used":
        m.log_event(f"📈 [{config.TEAM_NAME}] 趨勢簿：{why}", component="trend")
        return why
    n = lots()
    _enqueue(m, state, "open", now, price, why, sig=sig, n_lots=n)
    state["pos"] = {"rule": sig["rule"], "side": sig["side"], "sl": sig["sl"], "period": sig["period"], "ts": now, "utc": market.fmt_utc(now),
                    "price": price, "adopt": bool(sig.get("adopt"))}
    m.log_event(f"📈 [{config.TEAM_NAME}] 趨勢簿開{'多' if sig['side'] > 0 else '空'} {n:.2f} 手 SL {sig['sl']}（{why}）", component="trend")
    try:
        m.notify.tg_send(f"📈 趨勢簿（{config.TREND_MAGIC}）開{'多' if sig['side'] > 0 else '空'} {n:.2f} 手｜{why}｜現價 {price}｜SL {sig['sl']}")
    except Exception:  # noqa: BLE001
        pass
    return f"開{'多' if sig['side'] > 0 else '空'} {n:.2f} 手（SL {sig['sl']}）"
