"""[R361] H1 回調策略真倉（IDEAS #162 G7；使用者 11-01「H1 回調星期一用真倉」→ 新 magic 934，同 931 S1、933 學生分開成交簿／風控）。
預設關（SIG_G7_LIVE=0）。做法同 933（student_live）一樣：EA 用 magic 934 掛一張圖，心跳按 magic 分流到呢度；
獨立狀態前綴 xau/sig/g7live/、指令 id 前綴 g。

訊號（同 research/strategy_search/search2.py G7 一致）：
  H4 EMA50 斜率（H1 收盤時已收盤嘅最後一根 H4，對比前一根）＞0 而 H1 RSI(14) 啱啱跌穿 TH（上一根 ＞TH、呢根 ≤TH）→ 買；
  斜率＜0 而 H1 RSI 啱啱升穿 100−TH → 沽。H1 收盤後 SIG_G7_SIGNAL_TTL_MIN 分鐘內市價入（帶 px／dev，EA v0.41 滑價上限）。
  SL＝入場 ∓ K×H1 ATR(14)；TP＝R×SL 距離；開倉 SIG_G7_HOLD_H 小時仲未完 → 市價平倉（時間止蝕）。同時 1 張。
  H1／H4 由 M1 合成：經紀 M1（xau/sig/bars/<日>.jsonl，931 心跳寫）優先，冇就用券商 MT5 歷史（xau/sig/mt5m1/<日>.json）；
  H4 以 22:00 UTC 對齊（22、02、06…）。數據唔夠（H4 < 60 根）或者最新 M1 舊過 5 分鐘就唔開。
風控：control 非 RUN、階梯 Ⓑ／Ⓓ、EA 唔准、數據封鎖、934 當日蝕到 SIG_G7_DAY_STOP_HKD、同戶口合共倉數 ≥ SIG_G7_ACCOUNT_MAX 都唔開。
934 唔計入 931＋933 嗰個 SIG_STUDENT_MAX_CONCURRENT 上限。純計算函數冇 I/O，方便測試。"""
import datetime as dt
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "g7live/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
BARS_PREFIX = config.PREFIX + "bars/"
MT5_PREFIX = config.PREFIX + "mt5m1/"
MAX_ORDERS = 200
H4_SHIFT = 22 * 3600 % (4 * 3600)          # 7200：H4 由 22:00 UTC 起計
MIN_H4 = 60
FRESH_SEC = 300
_DAY_CACHE = {}                             # 已完結日子嘅 M1（同一個 Cloud Run 實例重用）


def _m():
    import main            # 遲匯入避免循環
    return main


def enabled():
    return config.SIGNAL_BOOK and config.G7_LIVE


def is_magic(payload):
    return str(payload.get("magic") or "") == str(config.G7_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("g")


def empty_state():
    return {"pending_cmds": [], "orders": [], "last": None, "last_h1": None, "signals": []}


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
def aggregate(m1, sec, shift=0):
    """m1＝[(utc, o, h, l, c)…]（按時間）→ [(key, o, h, l, c)…]；key＝(t−shift)//sec*sec+shift。"""
    out = []
    for t, o, h, l, c in m1:
        k = (int(t) - shift) // sec * sec + shift
        if out and out[-1][0] == k:
            _, o0, h0, l0, _ = out[-1]
            out[-1] = (k, o0, max(h0, h), min(l0, l), c)
        else:
            out.append((k, o, h, l, c))
    return out


def ema(xs, n):
    a = 2 / (n + 1)
    out = []
    for x in xs:
        out.append(x if not out else a * x + (1 - a) * out[-1])
    return out


def rsi(closes, n=14):
    """同 research search.rsi：Wilder ≈ EMA(2n−1)，第一個差＝0。"""
    if not closes:
        return []
    d = [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    au = ema([max(x, 0.0) for x in d], 2 * n - 1)
    ad = ema([max(-x, 0.0) for x in d], 2 * n - 1)
    out = []
    for u, w in zip(au, ad):
        if w == 0:
            out.append(100.0 if u > 0 else float("nan"))
        else:
            out.append(100 - 100 / (1 + u / w))
    return out


def atr(bars, n=14):
    """同 research TF.atr：TR[0]＝h−l，之後 max(h−l, |h−c前|, |l−c前|)；ATR＝最近 n 個 TR 平均（唔夠回 None）。"""
    if len(bars) < n:
        return None
    trs = [bars[0][2] - bars[0][3]] + [max(b[2] - b[3], abs(b[2] - p[4]), abs(b[3] - p[4])) for p, b in zip(bars, bars[1:])]
    return sum(trs[-n:]) / n


def signal(m1, now, th=None, k=None, r=None):
    """用 now 之前已收盤嘅 K 線判最新一根已收盤 H1。回傳 dict：
    {"h1": H1 開盤 key, "side": BUY|SELL|None, "rsi", "rsi_prev", "slope", "atr", "sl_dist", "why"}；數據唔夠回 side=None＋why。"""
    th = config.G7_RSI_TH if th is None else th
    k = config.G7_SL_ATR if k is None else k
    rows = [b for b in m1 if b[0] + 60 <= now]
    h1 = [b for b in aggregate(rows, 3600) if b[0] + 3600 <= now]
    h4 = [b for b in aggregate(rows, 4 * 3600, H4_SHIFT) if b[0] + 4 * 3600 <= now]
    if len(h1) < 21 or len(h4) < MIN_H4:
        return {"h1": h1[-1][0] if h1 else None, "side": None, "why": f"數據唔夠（H1 {len(h1)}／21、H4 {len(h4)}／{MIN_H4}）"}
    last = h1[-1]
    h4c = [b for b in h4 if b[0] + 4 * 3600 <= last[0] + 3600]          # H1 收盤時已收盤嘅 H4
    if len(h4c) < 51:
        return {"h1": last[0], "side": None, "why": "H4 未夠 51 根"}
    e = ema([b[4] for b in h4c], 50)
    slope = e[-1] - e[-2]
    rs = rsi([b[4] for b in h1], 14)
    cur, prev = rs[-1], rs[-2]
    a = atr(h1, 14)
    out = {"h1": last[0], "rsi": round(cur, 2), "rsi_prev": round(prev, 2), "slope": round(slope, 4), "atr": round(a, 3) if a else None, "side": None}
    if a is None or a <= 0:
        out["why"] = "H1 ATR 計唔到"
        return out
    out["sl_dist"] = round(k * a, 3)
    if slope > 0 and cur <= th and not (prev <= th):
        out["side"] = "BUY"
    elif slope < 0 and cur >= 100 - th and not (prev >= 100 - th):
        out["side"] = "SELL"
    out["why"] = (f"{out['side']}：H4 EMA50 斜率 {slope:+.3f}、H1 RSI {prev:.1f}→{cur:.1f}" if out["side"]
                  else f"冇訊號（H4 斜率 {slope:+.3f}、H1 RSI {prev:.1f}→{cur:.1f}）")
    return out


def levels(side, price, sl_dist, r=None):
    r = config.G7_TP_R if r is None else r
    sgn = 1 if side == "BUY" else -1
    nd = config.PRICE_DIGITS
    return round(price - sgn * sl_dist, nd), round(price + sgn * r * sl_dist, nd)


def time_stop_due(pos, now, hold_h=None, opened_fallback=None):
    hold_h = config.G7_HOLD_H if hold_h is None else hold_h
    t0 = (pos or {}).get("opened_ts") or opened_fallback
    return bool(pos) and bool(t0) and now - float(t0) >= hold_h * 3600


# ------------------------------------------------------------------ 數據
def _day_rows(day, today):
    if day in _DAY_CACHE and day < today:
        return _DAY_CACHE[day]
    rows = []
    try:
        doc = storage.read_json(f"{BARS_PREFIX}{day}.jsonl", None)
    except StorageError:
        doc = None
    if isinstance(doc, list) and doc:
        rows = [(int(b["utc"]), float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
                for b in doc if isinstance(b, dict) and b.get("utc") is not None]
    if not rows:
        try:
            doc = storage.read_json(f"{MT5_PREFIX}{day}.json", None)
        except StorageError:
            doc = None
        if isinstance(doc, list):
            rows = [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in doc if isinstance(x, (list, tuple)) and len(x) >= 5]
    rows.sort()
    if day < today:
        _DAY_CACHE[day] = rows
    return rows


def load_m1(now, days=None):
    days = config.G7_LOOKBACK_DAYS if days is None else days
    d1 = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    today = d1.isoformat()
    out = []
    for k in range(days, -1, -1):
        out += _day_rows((d1 - dt.timedelta(days=k)).isoformat(), today)
    return out


# ------------------------------------------------------------------ 狀態／回報
def account_open_count(now):
    """同戶口 931＋933＋934 倉數＋排緊嘅開倉。"""
    m = _m()
    n = 0
    files = [(m.ACCOUNT_FILE, m.STATE_FILE)]
    try:
        import student_live
        files.append((student_live.ACCOUNT_FILE, student_live.STATE_FILE))
    except Exception:  # noqa: BLE001
        pass
    files.append((ACCOUNT_FILE, STATE_FILE))
    for af, sf in files:
        try:
            acct = storage.read_json(af, {}) or {}
            st = storage.read_json(sf, {}) or {}
        except StorageError:
            continue
        n += len(acct.get("positions") or [])
        n += sum(1 for c in (st.get("pending_cmds") or []) if not c.get("acked") and str(c.get("text") or "").startswith("open|")
                 and now - float(c.get("ts") or 0) < executor.CMD_TTL_SEC)
    return n


def status():
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    return {"on": enabled(), "magic": config.G7_MAGIC, "lots": config.G7_LOTS,
            "params": {"rsi_th": config.G7_RSI_TH, "sl_atr": config.G7_SL_ATR, "tp_r": config.G7_TP_R, "hold_h": config.G7_HOLD_H},
            "day_stop_hkd": config.G7_DAY_STOP_HKD, "account_max": config.G7_ACCOUNT_MAX,
            "account": {k: acct.get(k) for k in ("received_utc", "positions", "daily_pnl", "realized_total", "trade_allowed", "dry_run")},
            "orders": [{**o, "id": executor.mask_id(o.get("id"))} for o in (st.get("orders") or [])[-20:][::-1]],
            "signals": (st.get("signals") or [])[-20:][::-1], "book": (st.get("book") or [])[-50:][::-1],
            "last": st.get("last"), "pending": [executor.mask_cmd(c) for c in (st.get("pending_cmds") or []) if not c.get("acked")]}


def ack(cid, payload, now):
    def mutate(state):
        found = executor.ack(state, cid, payload, now)
        for o in state.get("orders") or []:
            if o.get("id") == cid:
                o.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"), message=str(payload.get("message") or "")[:120])
        return (state if found else None), found
    return storage.update(STATE_FILE, mutate, default_factory=empty_state)


def _order_meta(state, pos):
    o = next((x for x in reversed(state.get("orders") or []) if x.get("ticket") is not None and str(x.get("ticket")) == str(pos.get("ticket"))), None)
    return {"ch": "G7", "decision_price": o.get("price")} if o else {"ch": "G7"}


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.G7_ACCOUNT and str(payload.get("account") or "").strip() != config.G7_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.G7_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ H1 回調真倉戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    state = load_state()
    import live_book
    pos = (account.get("positions") or [None])[0]
    try:   # 成交簿只係紀錄：出錯唔可以拖垮心跳
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, extra=lambda p: _order_meta(state, p)):
            m.log_event(f"📗 [{config.TEAM_NAME}] H1 回調真倉平倉 {t['pnl_hkd']:+.2f} HKD", component="g7live")
    except Exception as exc:  # noqa: BLE001
        m.log_event(f"⚠️ H1 回調成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING", component="g7live")
    state["pos_seen"] = pos
    why = _decide(m, state, account, price, now) if enabled() else "H1 回調真倉未開（SIG_G7_LIVE=0）"
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        m.log_event(f"⚠️ H1 回調狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "g7live", "magic": config.G7_MAGIC,
                      "mode": "live" if config.EXECUTE else "shadow", "cmd_text": executor.cmd_text(state, now), "message": why}), 200


def _decide(m, state, account, price, now):
    pos = (account.get("positions") or [None])[0]
    if pos:
        last_open = next((o for o in reversed(state.get("orders") or []) if o.get("ok") and o.get("kind") == "open"), None)
        if time_stop_due(pos, now, opened_fallback=(last_open or {}).get("ts")):
            if m.pending_has(state, "close"):
                return "時間止蝕：等 EA 回報平倉"
            cid = "g" + uuid.uuid4().hex[:7]
            text = executor.enqueue(state, "CLOSE", None, None, now, cid, magic=config.G7_MAGIC) if config.EXECUTE else None
            state["orders"] = [*state.get("orders", []), {"id": cid, "kind": "close", "ts": now, "utc": market.fmt_utc(now), "price": price,
                                                          "reason": f"時間止蝕 {config.G7_HOLD_H:g} 小時", "applied": text or "paper", "acked": False}][-MAX_ORDERS:]
            m.log_event(f"⏱ [{config.TEAM_NAME}] H1 回調時間止蝕（{config.G7_HOLD_H:g} 小時）平倉｜{'已排指令' if text else '紙上'}", component="g7live", cmd=cid)
            return f"時間止蝕平倉（{config.G7_HOLD_H:g} 小時）"
        return "有倉（SL／TP 伺服器端；到鐘時間止蝕）"
    if m.pending_has(state, "open"):
        return "等 EA 回報開倉"
    # 每根 H1 只判一次（記低判過邊根），同 TTL：H1 收盤後太耐就唔追
    try:
        rows = load_m1(now)
    except Exception as exc:  # noqa: BLE001
        return f"讀 M1 失敗：{type(exc).__name__}"
    if not rows or now - (rows[-1][0] + 60) > FRESH_SEC:
        return "M1 數據唔新鮮（931 心跳 K 線存檔停咗？），唔開"
    sig = signal(rows, now)
    if sig.get("h1") is None:
        return sig.get("why") or "冇 H1"
    if state.get("last_h1") == sig["h1"]:
        return f"H1 {market.fmt_utc(sig['h1'], '%H:%M')} 已判（{(state.get('last_sig') or {}).get('why', '')}）"
    state["last_h1"] = sig["h1"]
    state["last_sig"] = {k: sig.get(k) for k in ("h1", "side", "rsi", "rsi_prev", "slope", "atr", "sl_dist", "why")}
    if not sig.get("side"):
        return sig.get("why")
    age = now - (sig["h1"] + 3600)
    rec = {**state["last_sig"], "utc": market.fmt_utc(sig["h1"] + 3600), "price": price}
    state["signals"] = [*state.get("signals", []), rec][-200:]
    if age > config.G7_SIGNAL_TTL_MIN * 60:
        rec["skip"] = f"H1 收盤後 {age / 60:.0f} 分鐘先見到，唔追"
        return rec["skip"]
    control = m.load_control()
    if control.get("mode") != "RUN":
        rec["skip"] = f"模式 {control.get('mode')}"
        return f"{sig['side']} 訊號，但模式 {control.get('mode')}，唔開"
    lad = m.risk_ladder({}, control, account, {"close": price or 0.0}, now)
    if lad.get("stop") or lad.get("pause"):
        rec["skip"] = f"階梯 {lad.get('level')}"
        return f"{sig['side']} 訊號，但階梯 {lad.get('level')}，唔開"
    ta = account.get("trade_allowed")
    if config.EXECUTE and isinstance(ta, dict) and ta and not all(bool(v) for v in ta.values()):
        rec["skip"] = "EA 未准交易"
        return "EA／終端／戶口未准交易"
    if config.G7_DAY_STOP_HKD and (account.get("daily_pnl") or 0.0) <= -config.G7_DAY_STOP_HKD:
        rec["skip"] = "日蝕停開"
        return f"934 今日已蝕 {account.get('daily_pnl'):+.2f} HKD ≥ {config.G7_DAY_STOP_HKD:g}，暫停開新倉"
    if price is None:
        rec["skip"] = "冇現價"
        return "心跳冇 M1 收市價"
    import data_block
    data_ev, _info = data_block.check(state, now, market.ny_date(now), log=m.log_event, tg=m.notify.tg_send)
    state["data_block"] = data_ev
    if data_ev:
        rec["skip"] = "數據封鎖"
        return f"📅 數據封鎖：{data_block.text(data_ev)}"
    n_open = account_open_count(now)
    if n_open >= config.G7_ACCOUNT_MAX:
        rec["skip"] = f"戶口倉數 {n_open}"
        return f"同戶口已有 {n_open} 張倉／排緊開倉（上限 {config.G7_ACCOUNT_MAX}），唔開"
    sl, tp = levels(sig["side"], price, sig["sl_dist"])
    action = "OPEN_LONG" if sig["side"] == "BUY" else "OPEN_SHORT"
    cid = "g" + uuid.uuid4().hex[:7]
    text = executor.enqueue(state, action, sl, tp, now, cid, lots=config.G7_LOTS, tag="G7", magic=config.G7_MAGIC,
                            note="H1回調", px=price, dev=(config.MAX_ENTRY_SLIP or None)) if config.EXECUTE else None
    order = {"id": cid, "kind": "open", "side": sig["side"], "lots": config.G7_LOTS, "sl": sl, "tp": tp, "price": price, "ts": now,
             "utc": market.fmt_utc(now), "h1": market.fmt_utc(sig["h1"]), "why": sig["why"], "applied": text or "paper", "acked": False}
    state["orders"] = [*state.get("orders", []), order][-MAX_ORDERS:]
    rec["order"] = cid
    m.log_event(f"📈 [{config.TEAM_NAME}] H1 回調真倉 {sig['side']} {config.G7_LOTS:.2f} 手 @ {price}｜SL {sl}｜TP {tp}｜{sig['why']}｜{'已排指令' if text else '紙上'}",
                component="g7live", cmd=cid)
    return f"H1 回調 {sig['side']}（{sig['why']}）"
