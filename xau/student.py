"""學徒計劃階段 1（使用者 10-22 批「階段 0 同 1 先開」；xau/DAN_APPRENTICE.md、IDEAS #122）：影子學生，唔落單。
規則學生（免費）：每根 M1 用 features.rule_candidates 睇三條規則會唔會入（每條規則 60 分鐘冷卻）；
Claude 學生：XAU_SHADOW=1 先開，活躍時段每 XAU_SHADOW_INTERVAL_MIN 分鐘問一次 Opus（冇訊號、有 lessons）「依家會唔會開」。
每個判斷先寫入 GCS（有時間戳）；參考頻道（SIG_REFERENCE_CHANNELS）新訊號到就對答案（方向／入場區 ±3／時間 30 分鐘內）；
學生自己嘅判斷亦用實際價計成績（DAN 結構＋2R 全平），睇「多手」有冇價值。全部只係數字，冇原文。"""
import uuid

import config
import features
import market
import storage
from storage import StorageError

PREFIX = config.PREFIX + "student/"
STATE_FILE = PREFIX + "state.json"
SCORES_FILE = PREFIX + "scores.json"
SNAP_PREFIX = config.PREFIX + "snapshots/"
STUDENTS = ("rule:swing", "rule:level", "rule:rev15", "claude")
MAX_PREDS = 300
COOLDOWN_SEC = 3600
now_ts = None   # tests 可以覆蓋；None 用 market.now_ts


def _now():
    import time
    return now_ts() if now_ts else time.time()


def log_event(message, severity="INFO", **fields):
    import json
    print(json.dumps({"severity": severity, "message": message, "component": "student", **fields}, ensure_ascii=False, default=str), flush=True)


def empty_state():
    return {"last_fired": {}, "claude_last_ts": 0, "preds": [], "usage": {"n": 0, "cost_usd": 0.0}}


def enabled():
    return config.SIGNAL_BOOK and config.STUDENT


def _pred(student, side, struct, now, price, **extra):
    mid = (struct["entry_low"] + struct["entry_high"]) / 2
    sgn = 1 if side == "BUY" else -1
    return {"id": uuid.uuid4().hex[:8], "student": student, "ts": now, "utc": market.fmt_utc(now), "side": side,
            "entry_low": struct["entry_low"], "entry_high": struct["entry_high"], "sl": struct["sl"],
            "tp": [round(mid + sgn * config.STUDENT_R_TARGET * features.STRUCT_SL, 2)],        # 自己成績：2R 全平
            "price": price, "outcome": None, "graded": None, **extra}


def rule_tick(m1, offset, now=None):
    """每根 M1 行一次：三條規則有冇觸發；觸發就記錄（60 分鐘冷卻）。回傳新觸發 list。"""
    now = now if now is not None else _now()
    cands = features.rule_candidates(m1, offset, now)
    if not cands:
        return []
    fired = []

    def mutate(st):
        st = st if isinstance(st, dict) and st.get("preds") is not None else empty_state()
        for c in cands:
            key = "rule:" + c["rule"]
            if now - (st["last_fired"].get(key) or 0) < COOLDOWN_SEC:
                continue
            p = _pred(key, c["side"], c, now, c["price"], ref=c.get("ref"))
            st["preds"] = [*st["preds"], p][-MAX_PREDS:]
            st["last_fired"][key] = now
            fired.append(p)
        return st, fired
    try:
        storage.update(STATE_FILE, mutate, default_factory=empty_state)
        for p in fired:
            storage.append_jsonl(f"{PREFIX}log/{market.ny_date(now)}.jsonl", p)
            log_event(f"🎓 [{config.TEAM_NAME}] 規則學生 {p['student']} {p['side']} 入場區 {p['entry_low']}–{p['entry_high']}（現價 {p['price']}，參考 {p.get('ref')}）", student=p["student"])
    except StorageError as exc:
        log_event(f"⚠️ 規則學生寫入失敗：{exc}", severity="WARNING")
    return fired


def in_shadow_hours(now):
    spec = (config.SHADOW_HOURS_UTC or "").strip()
    if not spec:
        return True
    h = int(now // 3600) % 24
    for part in spec.split(","):
        if "-" not in part:
            continue
        try:
            a, b = (int(x) for x in part.strip().split("-", 1))
        except ValueError:
            continue
        if (a <= h < b) if a <= b else (h >= a or h < b):
            return True
    return False


def claude_tick(brain_obj, ctx_builder, now=None):
    """XAU_SHADOW=1、活躍時段、隔 XAU_SHADOW_INTERVAL_MIN 分鐘先問一次。回傳判斷或 None。"""
    now = now if now is not None else _now()
    if not config.SHADOW or not in_shadow_hours(now):
        return None
    try:
        st = storage.read_json(STATE_FILE, None) or empty_state()
    except StorageError:
        return None
    if now - (st.get("claude_last_ts") or 0) < config.SHADOW_INTERVAL_MIN * 60:
        return None
    ctx = {k: v for k, v in ctx_builder().items() if k != "signals"}
    ctx["student_task"] = ("STUDENT MODE (shadow, nothing is executed): there are NO channel signals in this call. Answer as if you were "
                           "the signal provider: would you open a position RIGHT NOW? If yes, return OPEN_LONG or OPEN_SHORT with "
                           "stop_price and target_price; signal_id may be null in this mode. If no, HOLD. Your answer is graded later "
                           "against the real signal that may arrive within 30 minutes.")
    d = brain_obj.decide(ctx, student=True)                      # 用 921 原版 tools＋system，共用快取前綴（使用者 10-22 用 prompt caching）
    import brain as _brain
    cost = _brain.cost_usd(d.get("_usage"))
    action = str(d.get("action") or "HOLD")
    side = "BUY" if action == "OPEN_LONG" else ("SELL" if action == "OPEN_SHORT" else None)
    price = ctx.get("last_price")
    if side:
        struct = features.structure(price + (4.0 if side == "BUY" else -4.0), side)      # 學生話即刻入：入場區就係現價 ±2
        p = _pred("claude", side, struct, now, price, reason=str(d.get("reason") or "")[:200], ai_stop=d.get("stop_price"), ai_target=d.get("target_price"),
                  confidence=d.get("confidence"), cost_usd=cost, error=bool(d.get("_error")), usage=d.get("_usage"))
    else:
        p = {"id": uuid.uuid4().hex[:8], "student": "claude", "ts": now, "utc": market.fmt_utc(now), "side": None, "price": price,
             "reason": str(d.get("reason") or "")[:200], "cost_usd": cost, "outcome": "hold", "graded": None, "error": bool(d.get("_error")), "usage": d.get("_usage")}

    def mutate(s):
        s = s if isinstance(s, dict) and s.get("preds") is not None else empty_state()
        s["preds"] = [*s["preds"], p][-MAX_PREDS:]
        s["claude_last_ts"] = now
        u = s.setdefault("usage", {"n": 0, "cost_usd": 0.0}); u["n"] += 1; u["cost_usd"] = round(u["cost_usd"] + cost, 4)
        return s, None
    try:
        storage.update(STATE_FILE, mutate, default_factory=empty_state)
        storage.append_jsonl(f"{PREFIX}log/{market.ny_date(now)}.jsonl", p)
    except StorageError as exc:
        log_event(f"⚠️ Claude 學生寫入失敗：{exc}", severity="WARNING")
    log_event(f"🎓 [{config.TEAM_NAME}] Claude 學生：{action} @ {price}｜{p.get('reason')}｜${cost:.4f}", action=action)
    return p


def grade(sig_view):
    """參考頻道新訊號到：對答案。sig_view 要有 sid、side、entry_low／entry_high（冇就用 price）、msg_ts。回傳成績 row 或 None。"""
    sid, side, ts = sig_view.get("sid"), sig_view.get("side"), sig_view.get("msg_ts")
    if side not in ("BUY", "SELL") or not ts:
        return None
    lo, hi = sig_view.get("entry_low"), sig_view.get("entry_high")
    mid = (lo + hi) / 2 if lo is not None and hi is not None else sig_view.get("price")
    if mid is None:
        return None
    row = {"sid": sid, "ts": ts, "utc": market.fmt_utc(ts), "side": side, "mid": mid, "students": {}}

    def mutate(st):
        st = st if isinstance(st, dict) and st.get("preds") is not None else empty_state()
        win = [p for p in st["preds"] if ts - config.STUDENT_WINDOW_MIN * 60 <= p["ts"] <= ts and not p.get("graded")]
        for s in STUDENTS:
            ps = [p for p in win if p["student"] == s]
            if not ps:
                row["students"][s] = {"time": False, "dir": False, "zone": False}
                continue
            p = ps[-1]
            if p.get("side"):
                g = features.grade(p, side, mid, ts, config.STUDENT_ZONE_TOL)
                row["students"][s] = {"time": True, "dir": g["dir"], "zone": g["dir"] and g["zone"], "lead_min": g["lead_min"], "pred_id": p["id"]}
            else:
                row["students"][s] = {"time": False, "dir": False, "zone": False, "pred_id": p["id"], "said": "hold"}
            for q in ps:
                q["graded"] = sid
        return st, None

    def add(sc):
        sc = sc if isinstance(sc, dict) else {}
        g = sc.setdefault("grade", {})
        for s, r in row["students"].items():
            c = g.setdefault(s, {"n": 0, "time": 0, "dir": 0, "zone": 0})
            c["n"] += 1; c["time"] += 1 if r["time"] else 0; c["dir"] += 1 if r["dir"] else 0; c["zone"] += 1 if r["zone"] else 0
        return sc, None
    try:
        storage.update(STATE_FILE, mutate, default_factory=empty_state)
        storage.update(SCORES_FILE, add, default_factory=dict)
        storage.append_jsonl(f"{PREFIX}grades/{market.ny_date(ts)}.jsonl", row)
    except StorageError as exc:
        log_event(f"⚠️ 對答案寫入失敗：{exc}", severity="WARNING")
        return None
    log_event(f"🎓 [{config.TEAM_NAME}] 對答案 {sid}：" + "、".join(f"{s.split(':')[-1]}={'✓' if r['dir'] else ('✗' if r['time'] else '—')}" for s, r in row["students"].items()), sid=sid)
    return row


def score_pending(bars, offset, now=None):
    """學生自己嘅判斷用實際價計（DAN 結構，2R 全平）；完結就入 scores.own。"""
    import signals
    now = now if now is not None else _now()
    if not bars:
        return 0
    finals = []

    def mutate(st):
        st = st if isinstance(st, dict) and st.get("preds") is not None else empty_state()
        for p in st["preds"]:
            if not p.get("side") or (isinstance(p.get("outcome"), dict) and p["outcome"].get("final")) or p.get("outcome") == "hold":
                continue
            view = {"side": p["side"], "entry_low": p["entry_low"], "entry_high": p["entry_high"], "sl": p["sl"], "tp": p["tp"], "msg_ts": p["ts"], "order_type": None}
            o = signals.evaluate(view, bars, offset, p.get("outcome") or None, now)
            p["outcome"] = o
            if o.get("final"):
                finals.append(p)
        return st, None

    def add(sc):
        sc = sc if isinstance(sc, dict) else {}
        own = sc.setdefault("own", {})
        for p in finals:
            c = own.setdefault(p["student"], {"n": 0, "filled": 0, "win": 0, "sl": 0, "r_sum": 0.0})
            o = p["outcome"]; c["n"] += 1
            if o.get("filled_ts"):
                c["filled"] += 1
                if o["final"] == "all_tp":
                    c["win"] += 1; c["r_sum"] = round(c["r_sum"] + config.STUDENT_R_TARGET, 2)
                elif o["final"] == "sl":
                    c["sl"] += 1; c["r_sum"] = round(c["r_sum"] - 1.0, 2)
        return sc, None
    try:
        storage.update(STATE_FILE, mutate, default_factory=empty_state)
        if finals:
            storage.update(SCORES_FILE, add, default_factory=dict)
    except StorageError as exc:
        log_event(f"⚠️ 學生成績寫入失敗：{exc}", severity="WARNING")
    return len(finals)


def status():
    try:
        st = storage.read_json(STATE_FILE, None) or empty_state()
        sc = storage.read_json(SCORES_FILE, {}) or {}
    except StorageError:
        st, sc = empty_state(), {}
    preds = st.get("preds") or []
    by = {s: [p for p in preds if p["student"] == s] for s in STUDENTS}
    return {"enabled": enabled(), "shadow": config.SHADOW, "shadow_hours": config.SHADOW_HOURS_UTC, "interval_min": config.SHADOW_INTERVAL_MIN,
            "counts": {s: len(v) for s, v in by.items()}, "last": {s: (v[-1] if v else None) for s, v in by.items()},
            "usage": st.get("usage"), "scores": sc, "recent": preds[-15:][::-1]}
