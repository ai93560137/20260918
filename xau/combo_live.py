"""[R364] 組合 A 單倉真倉（IDEAS #183／#186；使用者 11-01「組合 A 準備放 935」、揀「一個 magic 935，同時 1 張；戶口 …69；每張 1%，上限 0.01 手」）。
預設關（SIG_COMBO_LIVE=0）；開唔開由使用者經總指揮批（影子前向 #184 仲進行緊）。做法同 934（g7_live）一樣：EA 用 magic 935 掛一張圖，
心跳按 magic 分流到呢度；獨立狀態前綴 xau/sig/combolive/、指令 id 前綴 k（唔係十六進制，唔會同 931 隨機 id 撞）。

六個成份（2026 年參數＝#184 用 2022–2025 揀出嗰組；同 research d1_indicators／h4_indicators／robust2 計法一致）：
  1 D1 Keltner 突破：收市由下面升穿 EMA20＋2×ATR20 → 買；跌穿 EMA20−2×ATR20 → 沽；TP 4／SL 2 × D1 ATR20；20 日
  2 D1 拋物線 SAR 轉向：SAR 轉向上＋收市 > SMA200 → 買；轉向下＋收市 < SMA200 → 沽；TP 4／SL 2；20 日
  3 D1 威廉 %R(14)：由 ≤ −80 升上 −80 以上＋收市 > SMA200 → 買；由 ≥ −20 跌落 −20 以下＋收市 < SMA200 → 沽；TP 4／SL 2；20 日
  4 H4 MACD(12,26,9) 交叉＋H4 收市同 H4 SMA200 同邊；TP 2／SL 2 × H4 ATR20；80 小時
  5 H4 拋物線 SAR 轉向＋H4 SMA200；TP 2／SL 2；80 小時
  6 星期效應：券商日（22:00 UTC 起）星期五開盤做多；SL 1.5 × 前一日 D1 ATR20；冇 TP；24 小時平
D1／H4 由 H1 合成（22:00 UTC 日界／H4 22:00 對齊）；H1 由經紀 M1（xau/sig/bars/）合成，冇就用券商 MT5 歷史（xau/sig/mt5m1/），
H1 存喺 xau/sig/combolive/h1.json（第一次由 MT5 歷史補 COMBO_SEED_DAYS 日）。K 線收市後 COMBO_SIGNAL_TTL_MIN 分鐘內先入（市價，帶 px／dev）。
同一時間最多 1 張；同時幾個訊號按成份次序揀第一個（同 #186 回測）。開倉後按成份記低時間止蝕，到鐘市價平倉。
手數：risk_size 按 COMBO_RISK_PCT%（1%）計，上限 COMBO_MAX_LOTS（0.01）；計出嚟唔夠 0.01 就照開 0.01，但 0.01 手風險超過權益 COMBO_FLOOR_MAX_PCT%（10%）就唔開。
風控：control 非 RUN、階梯 Ⓑ／Ⓓ、EA 唔准、數據封鎖、935 當日蝕到 COMBO_DAY_STOP_HKD、同戶口（931＋933＋934＋935）倉數 ≥ COMBO_ACCOUNT_MAX、
今年唔係 COMBO_PARAM_YEAR（參數要按 #184 每年重揀）都唔開。純計算函數冇 I/O，方便測試。"""
import datetime as dt
import math
import uuid

import config
import executor
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "combolive/"
STATE_FILE = PREFIX + "state.json"
ACCOUNT_FILE = PREFIX + "account.json"
H1_FILE = PREFIX + "h1.json"
MAX_ORDERS = 200
FRESH_SEC = 300
DAY_SHIFT = 7200                       # 券商日／H4 由 22:00 UTC 起計：key＝(t+7200)//期
MIN_D1 = 230                           # SMA200 要 200 日；多留少少

# 成份（次序＝同時出訊號時嘅優先次序）：名、家族、時框、TP 倍、SL 倍、時間止蝕（小時）
COMPONENTS = (
    ("D1 Keltner 突破", "J5", "D1", 4.0, 2.0, 480.0),
    ("D1 拋物線 SAR", "J7", "D1", 4.0, 2.0, 480.0),
    ("D1 威廉 %R", "J8", "D1", 4.0, 2.0, 480.0),
    ("H4 MACD", "J2", "H4", 2.0, 2.0, 80.0),
    ("H4 拋物線 SAR", "J7", "H4", 2.0, 2.0, 80.0),
    ("星期效應", "S2", "D1", None, 1.5, 24.0),
)


def _m():
    import main            # 遲匯入避免循環
    return main


def enabled():
    return config.SIGNAL_BOOK and config.COMBO_LIVE


def is_magic(payload):
    return str(payload.get("magic") or "") == str(config.COMBO_MAGIC)


def is_cmd(cid):
    return str(cid or "").startswith("k")


def empty_state():
    return {"pending_cmds": [], "orders": [], "last": None, "seen": {}, "signals": []}


def load_state():
    base = empty_state()
    try:
        doc = storage.read_json(STATE_FILE, None)
    except StorageError:
        doc = None
    if isinstance(doc, dict):
        base.update(doc)
    return base


# ------------------------------------------------------------------ 純計算（同 research numpy 版一致）
def group(h1, period):
    """h1＝[(t,o,h,l,c)…] → [(key, o, h, l, c, 第一根 H1 t)…]；key＝(t+7200)//period。"""
    out = []
    for t, o, h, l, c in h1:
        k = (int(t) + DAY_SHIFT) // period
        if out and out[-1][0] == k:
            k0, o0, h0, l0, _, t0 = out[-1]
            out[-1] = (k, o0, max(h0, h), min(l0, l), c, t0)
        else:
            out.append((k, o, h, l, c, int(t)))
    return out


def ema(xs, n):
    a = 2 / (n + 1)
    out = []
    for x in xs:
        out.append(x if not out else a * x + (1 - a) * out[-1])
    return out


def rolling_mean(xs, n):
    out = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def true_range(h, l, c):
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def psar(h, l, af0=0.02, step=0.02, amax=0.2):
    """同 research d1_indicators.psar：回傳 (sar, up)；index 0 冇值（None／False）。"""
    n = len(h); sar = [None] * n; up = [False] * n
    if n < 3:
        return sar, up
    bull = True; s = l[0]; ep = h[0]; af = af0
    for i in range(1, n):
        s = s + af * (ep - s)
        if bull:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                bull, s, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, amax)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                bull, s, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + step, amax)
        sar[i] = s; up[i] = bull
    return sar, up


def indicators(bars):
    """bars＝group() 結果。回傳 dict（每個都係同長度 list；計唔到嘅位置係 None）。"""
    h = [b[2] for b in bars]; l = [b[3] for b in bars]; c = [b[4] for b in bars]
    tr = true_range(h, l, c)
    atr = rolling_mean(tr, 20)
    e20 = ema(c, 20)
    ku = [None if a is None else e + 2 * a for e, a in zip(e20, atr)]
    kl = [None if a is None else e - 2 * a for e, a in zip(e20, atr)]
    s200 = rolling_mean(c, 200)
    _, sar_up = psar(h, l)
    wr = [None] * len(c)
    for i in range(13, len(c)):
        hh, ll = max(h[i - 13:i + 1]), min(l[i - 13:i + 1])
        wr[i] = None if hh == ll else -100 * (hh - c[i]) / (hh - ll)
    macd = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    sig = ema(macd, 9)
    return {"c": c, "atr": atr, "ku": ku, "kl": kl, "s200": s200, "sar_up": sar_up, "wr": wr, "macd": macd, "sig": sig}


def _gt(a, b):
    return a is not None and b is not None and a > b


def _lt(a, b):
    return a is not None and b is not None and a < b


def family_side(ind, fam, i):
    """第 i 根（已收市）有冇訊號：回傳 1／−1／0。同 research d1_indicators.signals（J5 ex2、J7 filt、J8 th20 filt、J2 filt）。"""
    if i < 1:
        return 0
    c, cp = ind["c"][i], ind["c"][i - 1]
    tu, td = _gt(c, ind["s200"][i]), _lt(c, ind["s200"][i])
    if fam == "J5":
        if _gt(c, ind["ku"][i]) and ind["ku"][i - 1] is not None and cp <= ind["ku"][i - 1]:
            return 1
        if _lt(c, ind["kl"][i]) and ind["kl"][i - 1] is not None and cp >= ind["kl"][i - 1]:
            return -1
    elif fam == "J7":
        up, upp = ind["sar_up"][i], (ind["sar_up"][i - 1] if i >= 1 else True)
        if up and not upp and tu:
            return 1
        if (not up) and upp and td:
            return -1
    elif fam == "J8":
        w, wp = ind["wr"][i], ind["wr"][i - 1]
        if w is not None and wp is not None:
            if w > -80 and wp <= -80 and tu:
                return 1
            if w < -20 and wp >= -20 and td:
                return -1
    elif fam == "J2":
        m, s, mp, sp = ind["macd"][i], ind["sig"][i], ind["macd"][i - 1], ind["sig"][i - 1]
        if m > s and mp <= sp and tu:
            return 1
        if m < s and mp >= sp and td:
            return -1
    return 0


def friday_of(key):
    """券商日 key（(t+7200)//86400）係咪星期五。"""
    return dt.datetime.fromtimestamp(key * 86400, dt.timezone.utc).weekday() == 4


def candidates(h1, now):
    """用 now 之前已收市嘅 K 線，搵最新一根 D1／H4 收市（同星期五開盤）出嘅訊號。
    回傳 list（按成份次序）：{"comp", "side", "bar_close"（收市 UTC，入場時間起點）, "sl_dist", "tp_dist"|None, "hold_h", "why"}。"""
    h1 = [b for b in h1 if b[0] + 3600 <= now]
    out = []
    frames = {}
    for tf, per in (("D1", 86400), ("H4", 14400)):
        bars = group(h1, per)
        cur = (int(now) + DAY_SHIFT) // per
        bars = [b for b in bars if b[0] < cur]                 # 只要已收市
        frames[tf] = (bars, indicators(bars) if bars else None, per)
    for name, fam, tf, tp_m, sl_m, hold in COMPONENTS:
        bars, ind, per = frames[tf]
        if not bars or ind is None:
            continue
        i = len(bars) - 1
        if fam == "S2":
            cur = (int(now) + DAY_SHIFT) // 86400
            if friday_of(cur) and bars[-1][0] == cur - 1 and ind["atr"][i] is not None:     # 今日係星期五：用前一日 ATR
                out.append({"comp": name, "side": 1, "bar_close": cur * 86400 - DAY_SHIFT, "sl_dist": sl_m * ind["atr"][i], "tp_dist": None,
                            "hold_h": hold, "why": "星期五開盤做多"})
            continue
        if tf == "D1" and len(bars) < MIN_D1:
            continue
        side = family_side(ind, fam, i)
        a = ind["atr"][i]
        if side and a:
            close_t = (bars[i][0] + 1) * per - DAY_SHIFT
            out.append({"comp": name, "side": side, "bar_close": close_t, "sl_dist": sl_m * a, "tp_dist": tp_m * a, "hold_h": hold,
                        "why": f"{name} {'買' if side > 0 else '沽'}（{tf} 收市 {ind['c'][i]:.2f}、ATR {a:.2f}）"})
    return out


def levels(side, price, sl_dist, tp_dist):
    nd = config.PRICE_DIGITS
    sl = round(price - side * sl_dist, nd)
    return sl, (None if tp_dist is None else round(price + side * tp_dist, nd))


def floor_lots(equity, price, sl, max_lots):
    """[使用者 11-01] 按 COMBO_RISK_PCT% 計；唔夠 0.01 就 0.01，但 0.01 手風險 > COMBO_FLOOR_MAX_PCT% 就 0（唔開）。回傳 (手數, info)。"""
    import risk_size
    lots, info = risk_size.size(equity, price, sl, max_lots, pct=config.COMBO_RISK_PCT, fallback=0.01)
    if lots is None:                                  # 按風險關咗：用固定最細
        return min(0.01, max_lots), {"mode": "fixed"}
    if lots == 0.0 and info.get("mode") == "skip" and info.get("per_lot_hkd"):
        risk = info["per_lot_hkd"] * 0.01
        try:
            eq = float(equity)
        except (TypeError, ValueError):
            eq = 0.0
        if eq > 0 and risk / eq * 100 <= config.COMBO_FLOOR_MAX_PCT:
            return 0.01, {"mode": "floor", "risk_hkd": round(risk, 2), "risk_pct": round(risk / eq * 100, 2),
                          "why": f"{config.COMBO_RISK_PCT:g}% 唔夠 0.01 手，照開 0.01（風險 {risk / eq * 100:.1f}%）"}
        return 0.0, {**info, "why": f"0.01 手風險 {risk:,.0f} HKD 超過權益 {config.COMBO_FLOOR_MAX_PCT:g}%"}
    return lots, info


# ------------------------------------------------------------------ 數據
def _h1_from_m1(rows):
    out = []
    for t, o, h, l, c in rows:
        k = int(t) // 3600 * 3600
        if out and out[-1][0] == k:
            _, o0, h0, l0, _ = out[-1]
            out[-1] = (k, o0, max(h0, h), min(l0, l), c)
        else:
            out.append((k, o, h, l, c))
    return out


def load_h1(now):
    """讀 H1 快取，用最近 3 日 M1 補新嘅 H1；快取唔夠 COMBO_SEED_DAYS 日就由 MT5 歷史重建。回傳 (H1 list, 最新 M1 時間)。"""
    import g7_live
    try:
        doc = storage.read_json(H1_FILE, None)
    except StorageError:
        doc = None
    h1 = [tuple(x) for x in doc] if isinstance(doc, list) else []
    need_from = now - config.COMBO_SEED_DAYS * 86400
    if not h1 or h1[0][0] > need_from + 86400 * 7:
        rows = g7_live.load_m1(now, days=config.COMBO_SEED_DAYS)
        h1 = _h1_from_m1(rows)
    else:
        rows = g7_live.load_m1(now, days=3)
        new = _h1_from_m1(rows)
        if new:
            cut = new[0][0]
            h1 = [b for b in h1 if b[0] < cut] + new
    h1 = [b for b in h1 if b[0] >= need_from - 86400 * 30]
    try:
        storage.write_json(H1_FILE, [list(b) for b in h1])
    except StorageError:
        pass
    return h1, (rows[-1][0] if rows else None)


def entry_ref(h1, bar_close):
    """收市之後第一根有成交嘅 H1 開盤時間（週末／每日休市之後先開到）；未有就 None。"""
    return next((b[0] for b in h1 if b[0] >= bar_close), None)


# ------------------------------------------------------------------ 狀態／回報
def account_open_count(now):
    """同戶口 931＋933＋934＋935 倉數＋排緊嘅開倉（g7_live 已計埋 935）。"""
    import g7_live
    return g7_live.account_open_count(now)


def status():
    st = load_state()
    try:
        acct = storage.read_json(ACCOUNT_FILE, {}) or {}
    except StorageError:
        acct = {}
    return {"on": enabled(), "magic": config.COMBO_MAGIC, "risk_pct": config.COMBO_RISK_PCT, "max_lots": config.COMBO_MAX_LOTS,
            "param_year": config.COMBO_PARAM_YEAR, "components": [c[0] for c in COMPONENTS],
            "day_stop_hkd": config.COMBO_DAY_STOP_HKD, "account_max": config.COMBO_ACCOUNT_MAX,
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
    return {"ch": f"組合A:{o.get('comp')}", "decision_price": o.get("price")} if o else {"ch": "組合A"}


def handle_heartbeat(payload):
    m = _m(); now = m.now_ts()
    if config.COMBO_ACCOUNT and str(payload.get("account") or "").strip() != config.COMBO_ACCOUNT:
        return m.jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    offset = m.server_offset(payload, now)
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "floating", "daily_pnl", "realized_total", "margin_level")}
    account.update(account_id=str(payload.get("account") or "")[:24], dry_run=bool(payload.get("dry_run")), positions=m.own_positions(payload, offset),
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   received_utc=market.fmt_utc(now), received_ts=now, magic=config.COMBO_MAGIC)
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        m.log_event(f"⚠️ 組合 A 真倉戶口快照寫入失敗：{exc}", severity="WARNING")
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    price = market.to_float(m1.get("close"))
    state = load_state()
    import live_book
    pos = (account.get("positions") or [None])[0]
    try:   # 成交簿只係紀錄：出錯唔可以拖垮心跳
        for t in live_book.track(state, state.get("pos_seen"), pos, account.get("realized_total"), now=now, extra=lambda p: _order_meta(state, p)):
            m.log_event(f"📗 [{config.TEAM_NAME}] 組合 A 真倉平倉 {t['pnl_hkd']:+.2f} HKD", component="combolive")
    except Exception as exc:  # noqa: BLE001
        m.log_event(f"⚠️ 組合 A 成交簿記錄失敗（唔影響交易）：{type(exc).__name__}: {exc}", severity="WARNING", component="combolive")
    state["pos_seen"] = pos
    why = _decide(m, state, account, price, now) if enabled() else "組合 A 真倉未開（SIG_COMBO_LIVE=0）"
    state["last"] = {"ts": now, "utc": market.fmt_utc(now), "price": price, "note": why}
    try:
        storage.write_json(STATE_FILE, state)
    except StorageError as exc:
        m.log_event(f"⚠️ 組合 A 狀態寫入失敗：{exc}", severity="ERROR")
    return m.jsonify({"status": "monitoring", "team": config.TEAM_NAME, "book": "combolive", "magic": config.COMBO_MAGIC,
                      "mode": "live" if config.EXECUTE else "shadow", "cmd_text": executor.cmd_text(state, now), "message": why}), 200


def _decide(m, state, account, price, now):
    pos = (account.get("positions") or [None])[0]
    if pos:
        last_open = next((o for o in reversed(state.get("orders") or []) if o.get("ok") and o.get("kind") == "open"), None)
        hold = float((last_open or {}).get("hold_h") or 24.0)
        t0 = pos.get("opened_ts") or (last_open or {}).get("ts")
        if t0 and now - float(t0) >= hold * 3600:
            if m.pending_has(state, "close"):
                return "時間止蝕：等 EA 回報平倉"
            cid = "k" + uuid.uuid4().hex[:7]
            text = executor.enqueue(state, "CLOSE", None, None, now, cid, magic=config.COMBO_MAGIC) if config.EXECUTE else None
            state["orders"] = [*state.get("orders", []), {"id": cid, "kind": "close", "ts": now, "utc": market.fmt_utc(now), "price": price,
                                                          "reason": f"時間止蝕 {hold:g} 小時（{(last_open or {}).get('comp')}）", "applied": text or "paper", "acked": False}][-MAX_ORDERS:]
            m.log_event(f"⏱ [{config.TEAM_NAME}] 組合 A 時間止蝕（{hold:g} 小時）平倉｜{'已排指令' if text else '紙上'}", component="combolive", cmd=cid)
            return f"時間止蝕平倉（{hold:g} 小時）"
        return f"有倉（{(last_open or {}).get('comp', '?')}；SL／TP 伺服器端；到鐘時間止蝕）"
    if m.pending_has(state, "open"):
        return "等 EA 回報開倉"
    year = dt.datetime.fromtimestamp(now, dt.timezone.utc).year
    if year != config.COMBO_PARAM_YEAR:
        return f"參數年份 {config.COMBO_PARAM_YEAR} ≠ 今年 {year}：要按 IDEAS #184 重揀參數先開（SIG_COMBO_PARAM_YEAR）"
    # 每個 H4 時段（22:00 對齊）判一次；市場未開（M1 唔新鮮）就等，唔記低已判
    h4_key = (int(now) + DAY_SHIFT) // 14400
    if state.get("last_h4") == h4_key:
        return f"呢個 H4 已判（{(state.get('last_cand') or {}).get('why', '冇訊號')}）"
    try:
        h1, last_m1 = load_h1(now)
    except Exception as exc:  # noqa: BLE001
        return f"讀 H1 失敗：{type(exc).__name__}"
    if not h1 or last_m1 is None or now - (last_m1 + 60) > FRESH_SEC:
        return "M1 數據唔新鮮（休市或者 931 心跳 K 線存檔停咗），等"
    cands = candidates(h1, now)
    seen = state.get("seen") or {}
    fresh = [c for c in cands if seen.get(c["comp"]) != c["bar_close"]]
    state["last_h4"] = h4_key
    for c in cands:
        seen[c["comp"]] = c["bar_close"]
    state["seen"] = dict(list(seen.items())[-20:])
    if not fresh:
        state["last_cand"] = {"why": "冇新訊號"}
        return "冇新訊號"
    c = fresh[0]                                        # 按成份次序揀第一個（#186）
    rec = {**{k: c[k] for k in ("comp", "side", "why")}, "utc": market.fmt_utc(c["bar_close"]), "price": price,
           "others": [x["comp"] for x in fresh[1:]]}
    state["signals"] = [*state.get("signals", []), rec][-200:]
    state["last_cand"] = rec
    ref = entry_ref(h1, c["bar_close"]) or now
    age = now - ref
    if age > config.COMBO_SIGNAL_TTL_MIN * 60:
        rec["skip"] = f"收市後第一根 K 線開咗 {age / 60:.0f} 分鐘先見到，唔追"
        return rec["skip"]
    control = m.load_control()
    if control.get("mode") != "RUN":
        rec["skip"] = f"模式 {control.get('mode')}"
        return f"{c['comp']} 訊號，但模式 {control.get('mode')}，唔開"
    lad = m.risk_ladder({}, control, account, {"close": price or 0.0}, now)
    if lad.get("stop") or lad.get("pause"):
        rec["skip"] = f"階梯 {lad.get('level')}"
        return f"{c['comp']} 訊號，但階梯 {lad.get('level')}，唔開"
    ta = account.get("trade_allowed")
    if config.EXECUTE and isinstance(ta, dict) and ta and not all(bool(v) for v in ta.values()):
        rec["skip"] = "EA 未准交易"
        return "EA／終端／戶口未准交易"
    if config.COMBO_DAY_STOP_HKD and (account.get("daily_pnl") or 0.0) <= -config.COMBO_DAY_STOP_HKD:
        rec["skip"] = "日蝕停開"
        return f"935 今日已蝕 {account.get('daily_pnl'):+.2f} HKD ≥ {config.COMBO_DAY_STOP_HKD:g}，暫停開新倉"
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
    if n_open >= config.COMBO_ACCOUNT_MAX:
        rec["skip"] = f"戶口倉數 {n_open}"
        return f"同戶口已有 {n_open} 張倉／排緊開倉（上限 {config.COMBO_ACCOUNT_MAX}），唔開"
    sl, tp = levels(c["side"], price, c["sl_dist"], c["tp_dist"])
    n, r_info = floor_lots(account.get("equity"), price, sl, config.COMBO_MAX_LOTS)
    if r_info.get("mode") == "fallback":
        m.log_event(f"⚠️ [{config.TEAM_NAME}] 組合 A 按風險計手數：{r_info.get('why')}", severity="WARNING", component="risk")
    if not n:
        rec["skip"] = "手數唔開"
        return f"{c['comp']} 訊號，但唔開（{r_info.get('why')}）"
    action = "OPEN_LONG" if c["side"] > 0 else "OPEN_SHORT"
    cid = "k" + uuid.uuid4().hex[:7]
    text = executor.enqueue(state, action, sl, tp, now, cid, lots=n, tag="COMBO", magic=config.COMBO_MAGIC,
                            note="組合A", px=price, dev=(config.MAX_ENTRY_SLIP or None)) if config.EXECUTE else None
    order = {"id": cid, "kind": "open", "comp": c["comp"], "side": "BUY" if c["side"] > 0 else "SELL", "lots": n, "sl": sl, "tp": tp,
             "hold_h": c["hold_h"], "price": price, "ts": now, "risk": r_info, "utc": market.fmt_utc(now), "why": c["why"],
             "applied": text or "paper", "acked": False}
    state["orders"] = [*state.get("orders", []), order][-MAX_ORDERS:]
    rec["order"] = cid
    m.log_event(f"🧩 [{config.TEAM_NAME}] 組合 A 真倉 {c['comp']} {order['side']} {n:.2f} 手 @ {price}｜SL {sl}｜TP {tp}｜{c['why']}｜{'已排指令' if text else '紙上'}",
                component="combolive", cmd=cid)
    return f"組合 A {c['comp']} {order['side']}"
