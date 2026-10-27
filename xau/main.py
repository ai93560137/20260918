"""🌌 天覆陣：XAUUSD CFD（MT5）Claude 決策服務 — Cloud Run 入口。

流程（每個 EA 心跳）：
  1. 權杖檢查 → 2. 累積 M1／M15 → 3. 戶口快照 → 4. 新 M1 收盤：紙上止損／止賺／最長持倉 →
  5. 要問先問 Claude（空倉而電閘 LOCK 或休市就唔問；空倉先用 GATE_MODEL 篩）→ 6. 硬性規則 →
  7. 影子：紙上模擬；實倉（XAU_EXECUTE=1）：排指令，心跳回應 cmd_text 由 EA 執行 → 8. 寫決策紀錄。
狀態全部喺 GCS `xau/` 前綴。
"""
import json
import time
import uuid

import functions_framework
from flask import Flask, jsonify, request as flask_request

import brain
import config
import executor
import market
import notify
import page
import paper
import rules
import storage
import signals
import follower
import hold_rules
import lots_ladder
import prescreen
import student
import tgsignal
from storage import StorageError

M1_FILE = config.PREFIX + "m1.json"
M15_FILE = config.PREFIX + "m15.json"
ACCOUNT_FILE = config.PREFIX + "account.json"
STATE_FILE = config.PREFIX + "state.json"
LESSONS_FILE = config.PREFIX + "lessons.md"
DECISIONS_PREFIX = config.PREFIX + "decisions/"
BARS_PREFIX = config.PREFIX + "bars/"                 # [R345] 全日 M1 存檔（xau/EURUSD_SIM_PLAN.md A1）
CONTROL_FILE = config.PREFIX + "control.json"      # 緊急停機開關、暫停開倉、本金（私人）、淨值高水位
TEST_CMD_FILE = config.PREFIX + "test_cmd.json"    # 階段 B 測試指令檔（XAU_TEST_CMDS=1 先讀；用過寫回 consumed）
BUNDLED_LESSONS = __file__.rsplit("/", 1)[0] + "/LESSONS.md"


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
            "principal_hkd": None, "equity_peak": 0.0, "principal_seen": None, "alerts_sent": {}, "cum_loss_above": False, "cum_loss_day": ""}
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


def server_offset(payload, now):
    """EA 送嘅時間（MT5 伺服器時間，UltimaMarkets ≈ UTC+3）同真 UTC 嘅差（秒）。
    EA 有送 server_time 就直接計（取整到分鐘）；否則用剛收盤嗰根 M1 嘅時間估（取整到 15 分鐘；收盤後 1–2 分鐘內收到都估得準）。"""
    st = market.to_float(payload.get("server_time"))
    if st:
        return int(round((st - now) / 60.0) * 60)
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    t = market.to_float(m1.get("time"))
    if not t:
        return 0
    return int(round((t - now) / 900.0) * 900)


def own_positions(payload, offset=0):
    """EA 心跳 positions[]（EA 已只數自己 magic）→ 乾淨列表；open_time 係伺服器時間，減 offset 換成 UTC（最長持倉用）。"""
    out = []
    for p in (payload.get("positions") or []) if isinstance(payload.get("positions"), list) else []:
        if not isinstance(p, dict):
            continue
        side = 1 if str(p.get("side") or "").upper() == "BUY" else -1
        entry, lots = market.to_float(p.get("entry")), market.to_float(p.get("lots"))
        if entry is None or lots is None:
            continue
        out.append({"ticket": p.get("ticket"), "side": side, "entry": entry, "lots": lots,
                    "stop": (market.to_float(p.get("sl")) or None), "target": (market.to_float(p.get("tp")) or None),
                    "opened_ts": ((market.to_float(p.get("open_time")) or 0) - offset) if market.to_float(p.get("open_time")) else 0})
    return out


def live_position(account):
    """實倉模式：持倉以 EA 心跳為準（最多 1 張；多過 1 張取最早嗰張，並記警告）。"""
    pos = (account or {}).get("positions") or []
    if not pos:
        return None
    if len(pos) > 1:
        log_event(f"⚠️ [{config.TEAM_NAME}] EA 回報 {len(pos)} 張自己 magic 嘅倉（應該最多 1 張）", severity="WARNING", component="ea")
    p = sorted(pos, key=lambda x: x.get("opened_ts") or 0)[0]
    return {**p, "decision_id": None, "source": "ea"}


def pending_has(state, op):
    now = now_ts()
    return any((not c.get("acked")) and c["text"].startswith(op + "|") and now - c["ts"] < executor.CMD_TTL_SEC
               for c in (state.get("pending_cmds") or []))


def risk_ladder(state, control, account, bar, now):
    """使用者 10-20：真倉同真倉戶口共用，日蝕只計天覆陣自己嘅單（模擬＝紙上；真倉＝EA 按 magic 回報）；
    「自己嘅權益」= 本金 + 累計已實現 + 浮動；保證金水平係戶口級。"""
    principal = market.to_float(control.get("principal_hkd"))
    scope = "paper"
    if config.EXECUTE:
        # 真倉：EA 回報（戶口貨幣 HKD）。v0.35 起優先用 bots_*（天覆陣全部產品合計：InpBotMagics，唔計手動單同其他 EA）——
        # 戶口總階梯（xau/ACCOUNT_LADDER.md 方案 A，使用者 10-21 批）；冇 bots_* 就退回自己 magic（daily_pnl／floating／realized_total）。
        if market.to_float(account.get("bots_daily_pnl")) is not None:
            scope = "account"
            floating = market.to_float(account.get("bots_floating"), 0.0) or 0.0
            daily_hkd = (market.to_float(account.get("bots_daily_pnl"), 0.0) or 0.0) + floating
            cum_hkd = (market.to_float(account.get("bots_realized_total"), 0.0) or 0.0) + floating
        else:
            scope = "own"
            floating = market.to_float(account.get("floating"), 0.0) or 0.0
            daily_hkd = (market.to_float(account.get("daily_pnl"), 0.0) or 0.0) + floating
            cum_hkd = (market.to_float(account.get("realized_total"), 0.0) or 0.0) + floating
        daily_usd, cum_usd = daily_hkd / config.HKD_PER_USD, cum_hkd / config.HKD_PER_USD
    else:
        daily_usd = paper.daily_pnl_usd(state, market.ny_day_start_ts(now), bar["close"])
        cum_usd = paper.cumulative_pnl_usd(state, bar["close"])
    own_equity = (principal + cum_usd * config.HKD_PER_USD) if principal else None
    if principal and control.get("principal_seen") != principal:      # 本金改咗（入金／出金／測試）：高水位重設為當時權益，免得回撤警報亂響
        control["principal_seen"] = principal
        control["equity_peak"] = round(own_equity, 2)
        log_event(f"ℹ️ [{config.TEAM_NAME}] 本金已更新，高水位重設", component="ladder")
    if own_equity is not None and own_equity > (control.get("equity_peak") or 0.0):
        control["equity_peak"] = round(own_equity, 2)
    lad = rules.ladder(principal_hkd=principal, own_equity=own_equity,
                       peak_equity=(control.get("equity_peak") if principal else None),
                       daily_pnl_hkd=daily_usd * config.HKD_PER_USD,
                       margin_level=market.to_float(account.get("margin_level")), night=market.is_night(now))
    own_daily = ((market.to_float(account.get("daily_pnl"), 0.0) or 0.0) + (market.to_float(account.get("floating"), 0.0) or 0.0)) if config.EXECUTE else None
    lad.update(own_equity_hkd=(round(own_equity, 2) if own_equity is not None else None),
               daily_pnl_hkd=round(daily_usd * config.HKD_PER_USD, 2), cum_pnl_usd=cum_usd, night=market.is_night(now),
               scope=scope, own_daily_pnl_hkd=(round(own_daily, 2) if own_daily is not None else None),
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
        closed = None
        if config.EXECUTE:
            rec["applied"] = (enqueue_cmd(state, "CLOSE", None, None, now, decision_id) if state.get("position") and not pending_has(state, "close") else "HOLD")
        else:
            closed = paper.force_close(state, bar, "日蝕 −" + f"{config.DAILY_LOSS_STOP_PCT:g}% 平倉停機", now)
        set_mode(control, "STOP", why, "ladder", now, auto_reset_day=next_day)
        rec.update(kind="ladder", action="CLOSE", final="CLOSE", reason=why,
                   paper_exit=({"reason": closed["reason"], "pnl_usd": closed["pnl_usd"]} if closed else rec.get("paper_exit")))
        notify.tg_send(f"🛑 {why}｜今日 {lad['daily_pnl_hkd']:+,.0f} 港幣｜紐約 17:00 換日自動重開")
        handled = True
    elif lad["pause"] and mode == "RUN":
        why = "；".join(lad["reasons"])
        set_mode(control, "PAUSE", why, "ladder", now, auto_reset_day=(next_day if lad["pause_kind"] == "daily" else None))
        notify.tg_send(f"⏸ {why}")
    # 只提示嘅警報：每個交易日每項一次（含 API key 到期前 KEY_WARN_DAYS 日）
    sent = control.setdefault("alerts_sent", {})
    if sent.get("day") != day:
        control["alerts_sent"] = sent = {"day": day}
    alerts = dict(lad.get("alerts") or {})
    _, days_left = market.key_expiry(now)
    if days_left is not None and days_left <= config.KEY_WARN_DAYS:
        alerts["api_key"] = (f"ANTHROPIC_API_KEY 仲有 {days_left:.0f} 日到期（{config.KEY_EXPIRES_UTC} UTC），請喺控制台換新 key"
                             if days_left > 0 else f"ANTHROPIC_API_KEY 已到期（{config.KEY_EXPIRES_UTC} UTC），決策會失敗")
    for key, text in alerts.items():
        if not sent.get(key):
            sent[key] = market.fmt_utc(now)
            notify.tg_send(f"⚠️ {text}（只提示，唔停唔鎖）")
            log_event(f"⚠️ [{config.TEAM_NAME}] {text}", severity="WARNING", component="ladder")
    return handled


# ---------------------------------------------------------------------------
# 決策
# ---------------------------------------------------------------------------
def compact(bars):
    return [[b["time"], b["open"], b["high"], b["low"], b["close"]] for b in bars]


def compact_live(bars, hour0):
    """本小時 M1：時間欄改「本小時第幾分鐘」（0–59），慳 10 位 epoch（③）；只送最近 M1_LIVE_MAX 根（④）。"""
    if config.M1_LIVE_MAX > 0:
        bars = bars[-config.M1_LIVE_MAX:]
    return [[int((b["time"] - hour0) // 60), b["open"], b["high"], b["low"], b["close"]] for b in bars]


def short_reason(text):
    n = config.REASON_MAX_CHARS
    return str(text or "")[:n] if n > 0 else ""


def decision_line(rec, price):
    """日誌行由 Python 組（使用者 10-23：Opus 唔講話）：動作｜價｜SL／TP｜信心｜標籤｜擋｜ms。"""
    nd = config.PRICE_DIGITS
    action, why = rec.get("final"), rec.get("rejected")
    parts = [f"{action}{' ← AI ' + str(rec.get('action')) if why else ''} @ {price:.{nd}f}"]
    if rec.get("stop") is not None:
        parts.append(f"SL {rec['stop']:.{nd}f}")
    if rec.get("target") is not None:
        parts.append(f"TP {rec['target']:.{nd}f}")
    if rec.get("confidence") is not None:
        parts.append(f"信心 {rec['confidence']:.2f}")
    if rec.get("reason"):
        parts.append(str(rec["reason"])[:80])
    if why:
        parts.append("擋：" + str(why))
    if rec.get("ms") is not None:
        parts.append(f"{rec['ms']} ms")
    return f"🧠 [{config.TEAM_NAME}] " + "｜".join(parts)


def build_context(state, m1, m15, account, now, day, ladder=None, control=None):
    # Prompt caching（使用者 10-21）：按「整點」切——上一個整點之前嘅 K 線一個鐘先變一次（可快取前段），本小時嘅先係即時部分
    hour0 = int(m1[-1]["time"]) // 3600 * 3600
    older, recent = [b for b in m15 if b["time"] < hour0][-config.M15_OLDER_MAX:], [b for b in m15 if b["time"] >= hour0]   # 固定根數 → 同一個鐘內內容唔變（慳成本 G）
    m1_older, m1_live = [b for b in m1[-180:] if b["time"] < hour0][-60:], [b for b in m1 if b["time"] >= hour0]   # 整點前最多 60 根（10-21 由 120 減，慳 token）；本小時嘅見 compact_live
    pos = state.get("position")
    last = m1[-1]["close"]
    position = None
    if pos:
        position = {"side": "LONG" if pos["side"] > 0 else "SHORT", "lots": pos["lots"], "entry": pos["entry"],
                    "stop": pos.get("stop"), "target": pos.get("target"),
                    "age_min": int((now - pos["opened_ts"]) / 60),
                    "unrealized_usd": round((last - pos["entry"]) * pos["side"] * config.CONTRACT_SIZE * pos["lots"] / (config.QUOTE_PER_USD or 1.0), 2)}
    return {
        "product": {"symbol": config.SYMBOL, "contract_size": config.CONTRACT_SIZE, "pip": config.PIP, "price_digits": config.PRICE_DIGITS,
                    "quote_currency": config.QUOTE_CCY, "description": config.PRODUCT_DESC,
                    "long_only": config.LONG_ONLY, "mode": "live" if config.EXECUTE else "shadow",
                    # ① 風控常數（10-23）：一日唔變，放入 1h 快取段；每分鐘變嘅留喺 risk
                    "risk_limits": {"lots": rules.lots(), "min_sl_price": config.MIN_SL_USD, "max_sl_price": config.MAX_SL_USD,
                                    "min_sl_pips": config.MIN_SL_PIPS, "max_sl_pips": config.MAX_SL_PIPS, "spread_price": config.SPREAD_USD,
                                    "min_confidence": config.MIN_CONFIDENCE, "max_trades_per_day": config.MAX_TRADES_PER_DAY,
                                    "max_hold_min": config.MAX_HOLD_MIN}},
        "bars_m15_older": compact(older),
        "time": market.session_text(now),
        "bars_m15_recent": compact(recent),
        "bars_m1_older": compact(m1_older),
        "bars_m1": compact_live(m1_live, hour0),
        "bars_m1_hour_utc": time.strftime("%H:%M", time.gmtime(hour0)),
        "atr": {"m1_14": market.wilder_atr(m1), "m15_14": market.wilder_atr(m15),
                "ea_m1": account.get("atr_m1"), "ea_m5": account.get("atr_m5"), "ea_m15": account.get("atr_m15")},
        "last_price": last,
        "account": {"currency": account.get("currency"), "equity": account.get("equity"),
                    "balance": account.get("balance"), "daily_pnl": account.get("daily_pnl")},
        "position": position,
        "risk": {"trades_today": paper.trades_today(state, day),
                 "ladder": {"level": (ladder or {}).get("level", "A"), "reasons": (ladder or {}).get("reasons", []),
                            "daily_pnl_hkd": (ladder or {}).get("daily_pnl_hkd"), "alerts": list((ladder or {}).get("alerts", {}).values())},
                 "mode": (control or {}).get("mode", "RUN"), "mode_reason": (control or {}).get("reason")},
        "recent_trades": [{"side": "LONG" if t["side"] > 0 else "SHORT", "entry": t["entry"], "exit": t["exit"],
                           "pnl_usd": t["pnl_usd"], "reason": t["reason"], "hold_min": t["hold_min"]}
                          for t in (state.get("trades") or [])[-5:]],
        "recent_decisions": [{"hkt": market.fmt_hkt(d["ts"]), "action": d.get("final"), "reason": short_reason(d.get("reason")),
                              **({"sid": d["signal_id"]} if d.get("signal_id") else {})}
                             for d in (state.get("decisions") or [])[-config.RECENT_DECISIONS:]],   # ② 6 → 3（10-23）
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
    return executor.enqueue(state, action, stop, target, now, decision_id)


def cmd_text(state, now):
    return executor.cmd_text(state, now)


def in_active_hours(now):
    """XAU_ACTIVE_HOURS_UTC="07-17" → 07:00–16:59 UTC 先問；空＝全日。"""
    spec = (config.ACTIVE_HOURS_UTC or "").strip()
    if not spec or "-" not in spec:
        return True
    try:
        a, b = (int(x) for x in spec.split("-", 1))
    except ValueError:
        return True
    h = int(now // 3600) % 24
    return a <= h < b if a <= b else (h >= a or h < b)


def reuse_hold(state, m1, m15, now):
    """慳成本 F：上次真正問 Claude 係 HOLD、仲未過 REUSE_MAX_MIN 分鐘、價格變動 < REUSE_ATR_MULT × M1 ATR、
    冇新 M15 收盤 → 回傳原因（可以沿用）；否則 None。"""
    anchor, last = state.get("reuse_anchor") or {}, state.get("last_decision") or {}
    if not anchor or last.get("final") != "HOLD" or last.get("kind") not in ("decide", "screen", "reuse"):
        return None
    if now - anchor.get("ts", 0) > config.REUSE_MAX_MIN * 60:
        return None
    if m15 and anchor.get("m15_time") != m15[-1]["time"]:
        return None
    atr = market.wilder_atr(m1) or 0
    move = abs(m1[-1]["close"] - (anchor.get("price") or 0))
    if not atr or move >= config.REUSE_ATR_MULT * atr:
        return None
    return f"價格變動 {move:.{config.PRICE_DIGITS}f} < {config.REUSE_ATR_MULT:g}×ATR {atr:.{config.PRICE_DIGITS}f}、冇新 M15"


def process_bar(state, bar, m1, m15, account, now):
    """新 M1 收盤。回傳 (決策紀錄或 None, 摘要)。"""
    day = market.ny_date(now)
    exit_rec = None
    if config.EXECUTE:
        prev_pos = state.get("position")
        state["position"] = live_position(account)       # 真倉：持倉以 EA 為準；止損止賺由伺服器端 SL／TP 執行
        pos_live = state["position"]
        moved = lots_ladder.live_close(state, prev_pos, pos_live, market.to_float(account.get("realized_total")), now=now, note="ea", **rules.lots_ladder_kw())   # [R346]
        if moved:
            log_event(f"🪜 [{config.TEAM_NAME}] 手數階梯 {moved[0]:.2f} → {moved[1]:.2f}（平倉 {state['lots_log'][-1]['pnl']:+.2f} HKD）", component="ea")
        if pos_live and rules.hold_expired(pos_live.get("opened_ts") or now, now) and not pending_has(state, "close"):
            enqueue_cmd(state, "CLOSE", None, None, now, uuid.uuid4().hex)
            log_event(f"⏱ [{config.TEAM_NAME}] 最長持倉 {config.MAX_HOLD_MIN} 分鐘到，排 close", severity="WARNING", component="ea")
    else:
        exit_rec = paper.on_bar(state, bar, now)
        if exit_rec:
            log_event(f"📕 [{config.TEAM_NAME}] 紙上平倉 {exit_rec['reason']} {exit_rec['pnl_usd']:+.2f} USD", component="paper")
    market_open = market.is_market_open(now)        # 黃金／外匯時段（market.py）；R253 後舊電閘已刪，舊規則只留 reference/legacy_rules.md
    control = load_control()
    ladder = risk_ladder(state, control, account, bar, now)
    state["ladder"] = ladder
    pos = state.get("position")
    decision_id = uuid.uuid4().hex
    rec = {"id": decision_id, "ts": now, "bar_time": bar["time"], "price": bar["close"],
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
        if config.EXECUTE and state.get("position") and not pending_has(state, "close"):   # 使用者／日蝕 STOP：真倉即排 close
            enqueue_cmd(state, "CLOSE", None, None, now, uuid.uuid4().hex)
            log_event(f"🛑 [{config.TEAM_NAME}] STOP 而有倉，排 close", severity="WARNING", component="ea")
        return None, f"STOP（{control.get('set_by')}）：{control.get('reason') or ''}"
    if not market_open:
        return None, "休市"
    if len(m15) < config.M15_MIN_BARS or len(m1) < 30:
        return None, f"歷史不足（M15 {len(m15)}／M1 {len(m1)} 根），累積中"

    can_open = control["mode"] == "RUN"
    block = None if can_open else f"PAUSE（{control.get('set_by')}）：{control.get('reason') or ''}"
    if pos is None and not in_active_hours(now):          # 慳成本 D：時段外空倉唔問 Claude（有倉照管）
        return None, f"時段外（XAU_ACTIVE_HOURS_UTC={config.ACTIVE_HOURS_UTC}），空倉唔問 Claude"
    reuse = reuse_hold(state, m1, m15, now) if pos is None and not config.SIGNAL_BOOK and config.REUSE_HOLD in ("on", "shadow") else None
    if reuse and config.REUSE_HOLD == "on":               # 慳成本 F：市況冇變沿用上次 HOLD
        rec.update(kind="reuse", action="HOLD", final="HOLD", reason=f"沿用上次 HOLD（{reuse}）")
        _record(state, rec, day)
        return rec, "沿用 HOLD"
    if not reuse:
        state["reuse_anchor"] = {"ts": now, "price": bar["close"], "m15_time": m15[-1]["time"] if m15 else None}
    if reuse:
        rec["reuse_shadow"] = reuse                       # shadow：照問，但記低「會沿用」，驗證有冇擋走開倉
    ps = None
    if pos is None and not config.SIGNAL_BOOK and prescreen.mode() != "off":   # 慳成本 S：空倉規則前篩（shadow 只記錄；on 時唔問 Opus）
        try:
            ps = prescreen.evaluate(m1, m15, bar["close"], state.get("prescreen_anchor"), account.get("server_offset"), now)
        except Exception as exc:                           # 前篩出錯唔可以阻住決策：當「要問」（fail-open），記 WARNING
            log_event(f"⚠️ [{config.TEAM_NAME}] prescreen 例外，當要問：{exc!r}", severity="WARNING", component="prescreen")
            ps = {"ask": True, "reasons": [f"prescreen 例外：{type(exc).__name__}"], "near": None}
        rec["prescreen"] = {"mode": prescreen.mode(), "ask": ps["ask"], "reasons": ps["reasons"], "near": ps["near"]}
        if prescreen.mode() == "on" and not ps["ask"]:
            state["prescreen_stats"] = prescreen.bump(state.get("prescreen_stats"), False)
            rec.update(kind="prescreen", action="HOLD", final="HOLD", reason="規則前篩：冇新 M15／價格冇變／唔貼關鍵位／冇急走，唔問", cost_usd=0.0, model="rules")
            rec["applied"] = "HOLD"
            _record(state, rec, day)
            return rec, "規則前篩：唔問"
        if ps["ask"]:                                      # 錨點只喺「規則會問」嗰分鐘更新（shadow 先模擬到 on 嘅行為）
            state["prescreen_anchor"] = {"ts": now, "price": bar["close"], "m15_time": m15[-1]["time"] if m15 else None}
    hr = hr_rule = None
    if pos is not None and hold_rules.mode() != "off":   # 慳成本 H：有倉時規則止損（shadow 只記錄；on 時規則處理、Opus 只喺特定分鐘問）
        hr = hold_rules.track(state.get("hold_rules"), pos, now)
        atr15 = market.wilder_atr(m15)
        hr_rule = hold_rules.suggest(pos, m1, atr15, bar["close"], hr.get("initial_stop"))
        r_hit_first = hr_rule.get("r_mult") is not None and hr_rule["r_mult"] >= hold_rules.BE_R and hr.get("r_hit_ts") is None
        if r_hit_first:
            hr["r_hit_ts"] = now
        ask = hold_rules.should_ask(hr, pos, bar["close"], atr15, m15[-1]["time"], now, r_hit_first)
        hr["last_m15_time"] = m15[-1]["time"]
        if ask:
            hr["last_ask_ts"] = now
        st = hr.setdefault("stats", {}); st["minutes"] = st.get("minutes", 0) + 1
        if not ask:
            st["rule_minutes"] = st.get("rule_minutes", 0) + 1       # on 模式下唔問 Opus 嘅分鐘（shadow＝估計可以慳幾多）
        rec["hold_rules"] = {"mode": hold_rules.mode(), "sl": hr_rule.get("sl"), "stage": hr_rule.get("stage"),
                             "r_mult": hr_rule.get("r_mult"), "reason": hr_rule.get("reason"), "ask": ask}
        state["hold_rules"] = hr
        if hold_rules.mode() == "on" and not ask:
            action, stop, target, why = "HOLD", None, None, None
            if hr_rule.get("sl") is not None:
                action, stop, target, why = rules.validate_decision(
                    {"action": "UPDATE_STOP", "stop_price": hr_rule["sl"], "target_price": None, "confidence": 1.0, "reason": "規則"},
                    position=pos, last=bar["close"], can_open=False, block_reason="規則", trades_today=paper.trades_today(state, day))
                if action == "UPDATE_STOP" and config.EXECUTE and pending_has(state, "modify"):
                    action, why = "HOLD", "上一個 modify 未 ack"
            rec.update(kind="hold_rules", action=action, final=action, stop=stop, target=target, rejected=why,
                       reason=f"規則止損（{hr_rule.get('reason')}）", cost_usd=0.0, model="rules")
            rec["applied"] = (enqueue_cmd(state, action, stop, target, now, decision_id) or "HOLD") if config.EXECUTE \
                else paper.apply(state, action, stop, target, bar, now, day, decision_id)
            _record(state, rec, day)
            if action == "UPDATE_STOP":
                log_event(f"📏 [{config.TEAM_NAME}] 規則移止損 → {stop:.{config.PRICE_DIGITS}f}（{hr_rule.get('reason')}）@ {bar['close']:.{config.PRICE_DIGITS}f}",
                          component="rules", action=action)
            return rec, rec["applied"]
    active = signals.active(now, price=bar["close"]) if config.SIGNAL_BOOK else None
    if config.SIGNAL_BOOK and pos is None and not active:
        return None, "冇有效訊號（訊號書唔問 Claude）"
    ctx = build_context(state, m1, m15, account, now, day, ladder, control)
    if config.SIGNAL_BOOK:
        ctx["signals"] = active
    b = get_brain()
    if pos is None and config.GATE_MODEL and not config.SIGNAL_BOOK:     # 訊號書：有效訊號本身就係「值得睇」，唔使 Haiku 篩
        sc = b.screen(ctx)
        _bump_usage(state, "screen", sc.get("_usage"), sc.get("_ms", 0), day)
        if not sc.get("look"):
            if ps is not None:
                state["prescreen_stats"] = prescreen.bump(state.get("prescreen_stats"), ps["ask"])
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
    cited = None
    if config.SIGNAL_BOOK and action in ("OPEN_LONG", "OPEN_SHORT"):
        cited = next((x for x in active or [] if x["sid"] == d.get("signal_id")), None)
        if cited is None:
            action, stop, target, why = "HOLD", None, None, f"訊號書開倉要引用有效訊號（signal_id={d.get('signal_id')!r}）"
    rec.update(kind="decide", action=str(d.get("action")), final=action, stop=stop, target=target,
               confidence=d.get("confidence"), reason=str(d.get("reason") or "")[:400], rejected=why,
               ai_stop=d.get("stop_price"), ai_target=d.get("target_price"),
               ms=d.get("_ms"), usage=d.get("_usage"), cost_usd=brain.cost_usd(d.get("_usage")),
               model=(d.get("_usage") or {}).get("model") or config.MODEL, lessons=d.get("_lessons"),
               error=bool(d.get("_error")))
    if ps is not None:                                    # S shadow／on：記規則會唔會問、開倉有冇落喺「唔問」分鐘
        state["prescreen_stats"] = prescreen.bump(state.get("prescreen_stats"), ps["ask"], opened=action in ("OPEN_LONG", "OPEN_SHORT"))
    if hr is not None:                                    # H shadow／on：Opus 實際移止損 vs 規則會移去邊
        hr["stats"] = hold_rules.compare(hr.get("stats"), hr_rule.get("sl"), action, stop, pos.get("stop"), config.HOLD_RULES_TOL)
        if action == "UPDATE_STOP":
            rec["hold_rules"]["ai_sl"] = stop
    if cited:
        rec["signal_id"] = cited["sid"]
        if cited["sid"] not in rec["reason"]:
            rec["reason"] = (rec["reason"] + signals.note(cited))[:480]
    if config.EXECUTE:
        rec["applied"] = enqueue_cmd(state, action, stop, target, now, decision_id) or "HOLD"
        if action in ("OPEN_LONG", "OPEN_SHORT"):
            paper.count_trade(state, day)
    else:
        rec["applied"] = paper.apply(state, action, stop, target, bar, now, day, decision_id)
    _record(state, rec, day)
    log_event(decision_line(rec, bar["close"]), component="brain",
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
    if config.ACCOUNT and str(payload.get("account") or "").strip() != config.ACCOUNT:   # 階段 B：只收指定登入號
        log_event(f"ℹ️ [{config.TEAM_NAME}] 非 XAU_ACCOUNT 嘅心跳，略過（account={str(payload.get('account') or '')[:12]}）", component="ea")
        return jsonify({"status": "ignored", "message": "account not allowed", "cmd_text": ""}), 200
    account = {k: market.to_float(payload.get(k)) for k in ("equity", "balance", "credit", "floating", "daily_pnl",
                                                             "buy_lots", "sell_lots", "net_lots", "margin_level", "realized_total",
                                                             "bots_daily_pnl", "bots_floating", "bots_realized_total")}   # bots_*：EA v0.35 戶口總階梯合計
    offset = server_offset(payload, now)
    account.update(account_id=str(payload.get("account") or "")[:24], server=str(payload.get("server") or "")[:40],
                   dry_run=bool(payload.get("dry_run")), positions=own_positions(payload, offset), server_offset=offset,
                   trade_allowed=(payload.get("trade_allowed") if isinstance(payload.get("trade_allowed"), dict) else None),
                   currency=str(payload.get("currency") or "HKD"), symbol=str(payload.get("symbol") or ""),
                   status=str(payload.get("status") or ""), received_utc=market.fmt_utc(now), received_ts=now,
                   atr_m1=market.to_float(m15_raw.get("atr_m1")), atr_m5=market.to_float(m15_raw.get("atr_m5")),
                   atr_m15=market.to_float(m15_raw.get("atr_m15")))
    try:
        storage.write_json(ACCOUNT_FILE, account)
    except StorageError as exc:
        log_event(f"⚠️ 戶口快照寫入失敗：{exc}", severity="WARNING")

    # EA v0.33 回填：首個心跳（或服務回 need_history）帶 m1_hist／m15_hist，合併入歷史，唔使等 5 小時累積 M15
    hist1, hist15 = market.parse_hist(payload.get("m1_hist")), market.parse_hist(payload.get("m15_hist"))
    if hist1 or hist15:
        try:
            if hist1:
                storage.update(M1_FILE, lambda h: (lambda n: (n, n))(market.merge_bars(h, hist1, config.M1_MAX)), default_factory=list)
            if hist15:
                storage.update(M15_FILE, lambda h: (lambda n: (n, n))(market.merge_bars(h, hist15, config.M15_MAX)), default_factory=list)
            log_event(f"📚 [{config.TEAM_NAME}] EA 回填歷史：M1 {len(hist1)} 根、M15 {len(hist15)} 根", component="ea")
            archive_bars(hist1, offset)                                  # [R345]
        except StorageError as exc:
            log_event(f"⚠️ 回填寫入失敗：{exc}", severity="WARNING")

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

    consume_test_file(now)                             # 階段 B：GCS xau/test_cmd.json 排測試指令（XAU_TEST_CMDS=1 先生效）
    state = load_state()
    if config.EXECUTE and state.get("position") is None:                 # [R346] 已存 state 有倉就留畀 process_bar 偵測平倉；冇倉先同步
        state["position"] = live_position(account)
    resp = {"status": "monitoring", "team": config.TEAM_NAME, "mode": "live" if config.EXECUTE else "shadow",
            "cmd_text": cmd_text(state, now), "need_history": need_history(m15), "lots": rules.lots(state)}
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
    archive_bars([bar], offset)                                       # [R345] 全日 M1 存檔
    if m15 is None:
        try:
            m15 = storage.read_json(M15_FILE, [])
        except StorageError:
            m15 = []
    if len(m15) < config.M15_MIN_BARS:                     # M15 唔夠：由已累積嘅 M1 砌完整嘅 15 分鐘 K 線補上（EA 送嘅優先）
        synth = market.m15_from_m1(m1)
        if synth:
            merged = market.merge_bars(synth, m15, config.M15_MAX)
            if len(merged) > len(m15):
                added = len(merged) - len(m15)
                try:
                    m15 = storage.update(M15_FILE, lambda h: (lambda n: (n, n))(market.merge_bars(merged, h, config.M15_MAX)), default_factory=list)
                    log_event(f"🧩 [{config.TEAM_NAME}] M15 唔夠，由 M1 砌咗 {added} 根（而家 {len(m15)} 根）", component="ea")
                except StorageError as exc:
                    log_event(f"⚠️ M15 合併寫入失敗：{exc}", severity="WARNING")
                    m15 = merged
    resp["need_history"] = need_history(m15)

    if config.SIGNAL_BOOK and student.enabled():                 # 學徒階段 1：影子學生先交卷（唔落單），再做 S1
        try:
            student.rule_tick(m1, offset, now, m15 or [])
            student.claude_tick(get_brain(), lambda: build_context(state, m1, m15 or [], account, now, market.ny_date(now)), now)
        except Exception as exc:  # noqa: BLE001
            log_event(f"⚠️ 影子學生出錯：{type(exc).__name__}: {str(exc)[:80]}", severity="WARNING", component="student")
    rec, summary = process_bar(state, bar, m1, m15 or [], account, now)
    try:
        save_state(state)
    except StorageError as exc:
        log_event(f"⚠️ 狀態寫入失敗：{exc}", severity="ERROR")
    resp.update(cmd_text=cmd_text(state, now), message=summary,
                decision=({k: rec.get(k) for k in ("final", "action", "reason", "rejected", "stop", "target", "ms")} if rec else None))
    return jsonify(resp), 200


def archive_bars(bars, offset):
    """[R345] 全日 M1 存檔：<PREFIX>bars/<UTC 日>.jsonl（JSON list，按 time 去重、排序；每根加 utc＝time−伺服器時差）。
    心跳每根新 M1 一次（同 decisions 日誌同頻率），EA 回填歷史時成批合併。EURUSD 即日回測（research/eurusd_rulesim）讀呢度。"""
    if not config.BARS_ARCHIVE or not bars:
        return
    by = {}
    for b in bars:
        if isinstance(b, dict) and b.get("time") is not None:
            by.setdefault(market.fmt_utc(b["time"] - offset, "%Y-%m-%d"), []).append(b)
    for day, rows in by.items():
        def mutate(cur, rows=rows):
            have = {x["time"]: x for x in (cur if isinstance(cur, list) else []) if isinstance(x, dict) and "time" in x}
            n0 = len(have)
            for b in rows:
                have[b["time"]] = {"time": b["time"], "utc": b["time"] - offset, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
            return ([have[k] for k in sorted(have)] if len(have) > n0 else None), None
        try:
            storage.update(f"{BARS_PREFIX}{day}.jsonl", mutate, default_factory=list)
        except Exception as exc:  # noqa: BLE001  [R345b] 存檔喺真倉心跳路徑：任何錯（缺欄位、儲存）都只記 WARNING，唔可以影響交易
            log_event(f"⚠️ M1 存檔寫入失敗 {day}：{type(exc).__name__}", severity="WARNING")


def need_history(m15):
    """M15 唔夠 20 根就叫 EA 下個心跳回填（EA v0.33 睇 need_history）。"""
    try:
        n = len(m15) if m15 is not None else len(storage.read_json(M15_FILE, []))
    except StorageError:
        return True
    return n < config.M15_MIN_BARS


def ack_account_ok(payload):
    """10-23 權杖公開（使用者決定 keep）：cmd_ack 帶 account（EA v0.38）就要同 XAU_ACCOUNT 一致；
    冇 account 時只有 XAU_ACK_REQUIRE_ACCOUNT=0 先接受（demo 舊 EA）。回傳 (ok, 原因)。"""
    if not config.ACCOUNT:
        return True, ""
    acct = str(payload.get("account") or "").strip()
    if acct:
        return (acct == config.ACCOUNT), ("" if acct == config.ACCOUNT else "account 唔係 XAU_ACCOUNT")
    return (not config.ACK_REQUIRE_ACCOUNT), ("" if not config.ACK_REQUIRE_ACCOUNT else "cmd_ack 冇 account（XAU_ACK_REQUIRE_ACCOUNT=1）")


def handle_cmd_ack(payload):
    """EA 執行完指令回報：{"action":"cmd_ack","id":...,"ok":true,"ticket":...,"message":...,"account":...}"""
    cid = str(payload.get("id") or "").strip()
    if not cid:
        return jsonify({"status": "error", "message": "missing id"}), 400
    ok_acct, why = ack_account_ok(payload)
    if not ok_acct:
        log_event(f"⚠️ [{config.TEAM_NAME}] 指令回報 {executor.mask_id(cid)} 略過：{why}", severity="WARNING", component="ea")
        return jsonify({"status": "ignored", "message": why, "id": executor.mask_id(cid)}), 200

    def mutate(state):
        found = executor.ack(state, cid, payload, now_ts())
        return (state if found else None), found
    try:
        found = storage.update(STATE_FILE, mutate, default_factory=paper.empty_state)
    except StorageError as exc:
        return jsonify({"status": "error", "message": str(exc)[:100]}), 500
    ok = bool(payload.get("ok"))
    log_event(f"📨 [{config.TEAM_NAME}] 指令回報 {cid} ok={payload.get('ok')} {'' if found else '（未知／已回報）'}"
              + ("" if ok else f"｜EA：{str(payload.get('message') or '')[:160]}"),            # 10-23：失敗原因（retcode 描述）要入日誌，之前只有 EA「專家」分頁先睇到
              severity="INFO" if ok else "WARNING", component="ea", cmd=cid, ok=ok)
    return jsonify({"status": "acked" if found else "unknown", "id": cid}), 200


def handle_test_cmd(payload):
    """HTTP 入口：排一條測試指令。要 XAU_TEST_CMDS=1 同權杖。"""
    body, code = queue_test_cmd(payload, now_ts())
    return jsonify(body), code


def consume_test_file(now):
    """階段 B 另一個入口（唔使權杖）：GCS `xau/test_cmd.json` 放 {"id":…,"op":"open|close|modify","side":…,"sl":…,"tp":…,"lots":…,"no_sl":…}，
    服務每個心跳讀一次，未用過就排指令，然後寫回 consumed＋result（同一個檔唔會排第二次）。只喺 XAU_TEST_CMDS=1 且 XAU_EXECUTE=1 生效。"""
    if not (config.TEST_CMDS and config.EXECUTE):
        return
    try:
        doc = storage.read_json(TEST_CMD_FILE, None)
    except StorageError as exc:
        log_event(f"⚠️ [{config.TEAM_NAME}] test_cmd.json 讀取失敗：{exc}", severity="WARNING", component="test")
        return
    if not isinstance(doc, dict) or not doc.get("op") or doc.get("consumed"):
        return
    ts = market.to_float(doc.get("ts"))
    if ts is None or abs(now - ts) > executor.CMD_TTL_SEC:        # 要帶 ts（UTC epoch 秒，`date +%s`）；放低超過 10 分鐘嘅檔唔排（部署後殘留檔唔會誤落單）
        body = {"status": "error", "message": f"ts missing or older than {executor.CMD_TTL_SEC}s (use date +%s)"}
    else:
        body, _ = queue_test_cmd(doc, now)
    try:
        storage.write_json(TEST_CMD_FILE, {**doc, "consumed": market.fmt_utc(now), "result": body})
    except StorageError as exc:
        log_event(f"🚨 [{config.TEAM_NAME}] test_cmd.json 寫回 consumed 失敗（可能重複排指令）：{exc}", severity="ERROR", component="test")


def queue_test_cmd(payload, now):
    """排一條指令（open／close／modify）畀 EA，測試清單用。回傳 (回應 dict, HTTP 狀態碼)。"""
    if not config.TEST_CMDS:
        return {"status": "error", "message": "XAU_TEST_CMDS=0"}, 403
    op = str(payload.get("op") or "").lower()
    side = str(payload.get("side") or "BUY").upper()
    action = {"open": ("OPEN_LONG" if side == "BUY" else "OPEN_SHORT"), "close": "CLOSE", "modify": "UPDATE_STOP"}.get(op)
    if not action:
        return {"status": "error", "message": "op must be open|close|modify"}, 400
    stop, target = market.to_float(payload.get("sl")), market.to_float(payload.get("tp"))
    lots = market.to_float(payload.get("lots"))
    if action != "CLOSE" and stop is None and not payload.get("no_sl"):
        return {"status": "error", "message": "sl required (or no_sl=true to test EA rejection)"}, 400
    cid = uuid.uuid4().hex

    def mutate(state):
        text = executor.enqueue(state, action, (stop if stop is not None else 0.0), target, now, cid,
                                lots=(lots if lots else None), tag="test")
        if payload.get("no_sl") and text:
            state["pending_cmds"][-1]["text"] = text.replace(f"sl={0.0:.{config.PRICE_DIGITS}f}", "sl=0")
            text = state["pending_cmds"][-1]["text"]
        if payload.get("resend") and text:                 # 測試清單第 5 項：ack 咗之後仍重送同一 id 180 秒，證明 EA 去重（只執行一次）
            state["pending_cmds"][-1]["resend_until"] = now + 180
        return state, text
    try:
        text = storage.update(STATE_FILE, mutate, default_factory=paper.empty_state)
    except StorageError as exc:
        return {"status": "error", "message": str(exc)[:100]}, 500
    log_event(f"🧪 [{config.TEAM_NAME}] test_cmd 排指令：{text}", severity="WARNING", component="test")
    return {"status": "queued", "id": cid[:8], "text": text, "will_send": config.EXECUTE}, 200


def rulesim_summary():
    """[R345] research/eurusd_rulesim 每日寫 <PREFIX>rulesim/summary.json；頁面只讀。"""
    try:
        sm = storage.read_json(config.PREFIX + "rulesim/summary.json", None)
    except StorageError:
        return None
    return sm if isinstance(sm, dict) else None


def build_status():
    state = load_state()
    try:
        m1 = storage.read_json(M1_FILE, [])
        m15 = storage.read_json(M15_FILE, [])
        account = storage.read_json(ACCOUNT_FILE, {})
    except StorageError:
        m1, m15, account = [], [], {}
    now = now_ts()
    _, key_days = market.key_expiry(now)
    u = state.get("usage_today") or {}
    ms = sorted(u.get("ms") or [])
    p95 = ms[int(len(ms) * 0.95) - 1] if len(ms) >= 2 else (ms[0] if ms else None)
    control = load_control()
    return {
        "team": config.TEAM_NAME, "symbol": config.SYMBOL, "execute": config.EXECUTE, "model": config.MODEL,
        "ladder": state.get("ladder") or {"level": "A", "reasons": []},
        "api_key": {"expires_utc": config.KEY_EXPIRES_UTC or None, "days_left": (round(key_days, 1) if key_days is not None else None),
                    "warn": bool(key_days is not None and key_days <= config.KEY_WARN_DAYS)},
        "control": {"mode": control.get("mode"), "reason": control.get("reason"), "set_by": control.get("set_by"),
                    "set_at_utc": control.get("set_at_utc"), "auto_reset_day": control.get("auto_reset_day"),
                    "principal_set": bool(control.get("principal_hkd"))},
        "effort": config.EFFORT, "gate_model": config.GATE_MODEL, "updated_hkt": market.fmt_hkt(now, "%m-%d %H:%M:%S"),
        "market_open": market.is_market_open(now), "session": market.session_text(now),
        "last_price": (m1[-1]["close"] if m1 else None), "m1_bars": len(m1), "m15_bars": len(m15),
        "account_received_utc": account.get("received_utc"), "account_id": executor.mask_account(account.get("account_id")), "server": account.get("server"),
        "ea_dry_run": account.get("dry_run"), "xau_account": executor.mask_account(config.ACCOUNT), "test_cmds": config.TEST_CMDS,
        "ack_require_account": config.ACK_REQUIRE_ACCOUNT,
        "trade_allowed": account.get("trade_allowed"), "server_offset": account.get("server_offset"),
        "live_positions": account.get("positions") or [],
        "position": state.get("position"), "stats": state.get("stats"), "trades": (state.get("trades") or [])[-40:],
        "hold_rules": {"mode": hold_rules.mode(), "ask_min": config.HOLD_RULES_ASK_MIN, "tol": config.HOLD_RULES_TOL, **(state.get("hold_rules") or {})},
        "prescreen": {"mode": prescreen.mode(), "near": config.PRESCREEN_NEAR, "move15": config.PRESCREEN_MOVE15, "atr_mult": config.PRESCREEN_ATR_MULT, **(state.get("prescreen_stats") or {})},
        "metrics": paper.metrics(state.get("trades") or [], day_key=market.ny_date),
        "trades_today": paper.trades_today(state, market.ny_date(now)),
        "decisions": (state.get("decisions") or [])[-60:],
        "usage_today": {"decide": u.get("decide", 0), "screen": u.get("screen", 0), "cost_usd": u.get("cost_usd", 0.0), "p95_ms": p95},
        "rulesim": rulesim_summary(),                                 # [R345] 即日回測（規則版）摘要，冇就 None
        "pending_cmds": [executor.mask_cmd(c) for c in (state.get("pending_cmds") or []) if not c.get("acked")],   # 10-23：id 遮罩，免假 cmd_ack
        "product": {"symbol": config.SYMBOL, "kind": config.PRODUCT_KIND, "pip": config.PIP, "digits": config.PRICE_DIGITS, "contract": config.CONTRACT_SIZE},
        "lots": {"current": rules.lots(state), "ladder": config.LOTS_LADDER, "start": round(config.LOTS, 2), "min": round(config.LOTS_MIN, 2), "max": round(config.MAX_LOTS, 2),
                 "step": round(config.LOTS_STEP, 2), "log": (state.get("lots_log") or [])[-10:]},            # [R346]
        "risk": {"XAU_LOTS": rules.lots(state), "手數階梯": (f"開：{config.LOTS_MIN:.2f}–{config.MAX_LOTS:.2f}，每次全部平倉賺 +{config.LOTS_STEP:.2f}／蝕 −{config.LOTS_STEP:.2f}" if config.LOTS_LADDER else "關（固定手數）"),
                 "止損距離 pip（下限／上限）": f"{config.MIN_SL_PIPS:g}／{config.MAX_SL_PIPS:g}",
                 "XAU_MIN_SL_USD": config.MIN_SL_USD, "XAU_MAX_SL_USD": config.MAX_SL_USD,
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
        status["book"] = config.BOOK
        if config.SIGNAL_BOOK:
            status["signals"] = signals.recent()
            if follower.enabled():
                status["follow"] = follower.status()
            if student.enabled():
                status["student"] = student.status()
        if req.args.get("format") == "json":
            return jsonify(status), 200
        return page.render(status), 200, {"Content-Type": "text/html; charset=utf-8"}
    if config.SIGNAL_BOOK:                             # 訊號書 S0：只收 HMAC 簽名嘅訊號／監聽心跳；EA 心跳等一律 ignored，唔問 Opus、唔落單
        if req.method == "POST" and req.headers.get("X-Sig-Signature"):
            return signals.handle_ingest(req.headers, req.get_data())
        if not config.SIG_DECIDE and not follower.enabled():
            return jsonify({"status": "ignored", "message": "signal book S0: ingest only"}), 200
    if req.args.get("tg") == "signal" and not config.SIGNAL_BOOK:   # [R290] 訊號確認 bot 嘅按鈕（訊號書唔用）
        return tgsignal.handle_callback(req)
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
    if config.SIGNAL_BOOK and follower.enabled():                      # 跟單（magic 932）：心跳按 magic 分流、回報按指令 id 前綴 f
        if action == "cmd_ack" and follower.is_follow_cmd(payload.get("id")):
            ok_acct, why = ack_account_ok(payload)
            if not ok_acct:
                log_event(f"⚠️ [{config.TEAM_NAME}] 跟單指令回報 {executor.mask_id(payload.get('id'))} 略過：{why}", severity="WARNING", component="follow")
                return jsonify({"status": "ignored", "message": why}), 200
            found = follower.ack(str(payload.get("id") or "")[:8], payload, now_ts())
            log_event(f"📨 [{config.TEAM_NAME}] 跟單指令回報 {str(payload.get('id') or '')[:8]} ok={payload.get('ok')} {'' if found else '（未知／已回報）'}"
                      + ("" if payload.get("ok") else f"｜EA：{str(payload.get('message') or '')[:160]}"),
                      severity="INFO" if payload.get("ok") else "WARNING", component="follow")
            return jsonify({"status": "acked" if found else "unknown", "id": str(payload.get("id") or "")[:8]}), 200
        if follower.is_follow_magic(payload) and ("equity" in payload or action in ("check_gate", "heartbeat")):
            return follower.handle_heartbeat(payload)
        if not config.SIG_DECIDE and ("equity" in payload or action in ("check_gate", "heartbeat")):
            return jsonify({"status": "ignored", "message": "signal book S0: ingest only", "cmd_text": ""}), 200
    if action == "cmd_ack":
        return handle_cmd_ack(payload)
    if action == "tg_signal" and not config.SIGNAL_BOOK:   # [R290] 舊入口（訊號書只收 HMAC 簽名入口）
        return tgsignal.handle_signal(payload)
    if action == "test_cmd" and not config.SIGNAL_BOOK:                           # 階段 B 測試清單：XAU_TEST_CMDS=1 先開放；真倉前要關
        return handle_test_cmd(payload)
    if "equity" in payload or action in ("check_gate", "heartbeat"):
        return handle_heartbeat(payload)
    return jsonify({"status": "ignored", "message": "No handler for this payload"}), 200


@functions_framework.http
def xau_entry(request):
    return entry(request)


app = Flask(__name__)
app.add_url_rule("/", "root", lambda: entry(flask_request), methods=["GET", "POST", "OPTIONS"])
app.add_url_rule("/<path:_p>", "any", lambda _p: entry(flask_request), methods=["GET", "POST", "OPTIONS"])
