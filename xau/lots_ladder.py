"""[R346] 手數階梯（使用者 10-27：「作為一個專業黃金操盤手，我要一個里程碑；每次下注由 0.05 開始返到 0.1」，揀「同龍飛一樣逐張升降」）。
[R349] 使用者 10-28：「手數升降規則要達到里程碑先增加」→ 升級**上限由已達成嘅里程碑決定**（MILESTONES M1→0.06、M2→0.07、M3→0.08、M4→0.10；未達 M1 ＝ 起點 0.05）：
    每次全部平倉：賺 → +step 但**唔超過上限**；蝕 → −step，最少 lo；上限降低（里程碑收回）時級數即時夾返落上限。
    上限由 env XAU_LOTS_MILESTONE（921）／SIG_FOLLOW_LOTS_MILESTONE（932）＝已達成里程碑數（0–4）同 XAU_LOTS_MILESTONE_CAPS 決定，由總指揮 env set、使用者批。
純函數，級數存喺各本自己嘅 state（921 同 932 各自一個級數）。
真倉嘅「平倉」＝EA 心跳由有倉變冇倉，盈虧符號用 EA 回報嘅 realized_total（自 InpLedgerStart 累計）差額；紙上＝paper._close 嘅 pnl。
開關：XAU_LOTS_LADDER（921／922 本）、SIG_FOLLOW_LOTS_LADDER（932 跟單）。關＝固定手數（舊行為）。"""
import time


def _r(v):
    return round(float(v) + 1e-9, 2)


def clamp(v, lo, hi):
    """hi（XAU_MAX_LOTS 硬上限）優先：lo > hi（env 未同步）時照用 hi，唔會超過上限。"""
    return _r(min(hi, max(lo, v)))


def cap_for(start, caps, milestone, hi):
    """[R349] 升級上限：已達成 milestone 個里程碑 → caps[milestone-1]（超出表尾用最後一個）；0 ＝ 起點 start。永遠唔超硬上限 hi。"""
    try:
        n = int(milestone or 0)
    except (TypeError, ValueError):
        n = 0
    caps = [float(c) for c in (caps or ()) if c is not None]
    if n <= 0 or not caps:
        cap = float(start)
    else:
        cap = caps[min(n, len(caps)) - 1]
    return _r(min(float(hi), cap))


def _hi(hi, cap):
    return hi if cap is None else min(hi, cap)


def current(state, *, start, lo, hi, on, cap=None):
    """而家應該用幾多手。關＝start（夾喺 lo–hi）；開＝state["lots_level"]（冇就 start），夾喺 lo 同 min(hi, cap)。"""
    if not on:
        return _r(min(hi, start))                     # 關：固定 start，但唔超硬上限
    lvl = (state or {}).get("lots_level")
    return clamp(start if lvl is None else lvl, lo, _hi(hi, cap))


def step(state, pnl, *, start, lo, hi, step, on, cap=None, now=None, note=""):
    """一次全部平倉後：pnl>0 升一級（唔超 cap）、<0 跌一級、0／None 唔郁。回傳 (舊, 新) 或 None（關／冇變）。寫 state["lots_level"]、state["lots_log"]（最近 50 次）。"""
    if not on or pnl is None or pnl == 0 or state is None:
        return None
    cur = current(state, start=start, lo=lo, hi=hi, on=True, cap=cap)
    new = clamp(cur + step if pnl > 0 else cur - step, lo, _hi(hi, cap))
    state["lots_level"] = new
    state["lots_log"] = [*(state.get("lots_log") or []), {"ts": now if now is not None else time.time(), "from": cur, "to": new, "pnl": round(float(pnl), 2), "note": note[:80]}][-50:]
    return cur, new


def live_close(state, prev_pos, new_pos, realized, **kw):
    """真倉：上個已存 state 有倉、而家 EA 話冇 → 當一次全部平倉；盈虧＝realized_total 而家 − 上次冇倉時嘅 realized_total（state["lots_realized_ref"]）。
    冇倉時（含平倉後）把 realized_total 記做參考點。realized 缺就唔郁（唔亂升降）。回傳 step() 結果或 None。"""
    if state is None:
        return None
    out = None
    if prev_pos and not new_pos and realized is not None:
        ref = state.get("lots_realized_ref")
        if ref is not None:
            out = step(state, round(float(realized) - float(ref), 2), **kw)
    if not new_pos and realized is not None:
        state["lots_realized_ref"] = float(realized)
    return out
