"""[R352] 真倉成交簿（使用者 10-30「真倉績效／模擬倉績效分開」）：EA 心跳冇逐筆成交，只有 positions 同 realized_total（自 InpLedgerStart 累計，按 magic）。
每個心跳：見到新倉就記開倉快照（初始止損畀 R 用）；有倉 → 冇倉（或換咗 ticket）就用 realized_total 差額記一筆（HKD，含佣金／隔夜息）。
出場價由 HKD 盈虧反推（÷ HKD_PER_USD ÷ 手數 ÷ 合約），標「估」。純函數＋state dict，921（main）同 932（follower）共用。
部署前嘅單由 GCS <prefix>book_seed.json 補（list，欄位同下面 make 一樣；只喺 GCS，唔入 repo）。"""
import time

import config

MAX = 300
KEYS = ("ticket", "side", "lots", "entry", "stop", "target", "opened_ts")


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def make(o, pnl_hkd, closed_ts, contract=None, hkd_per_usd=None):
    """一筆已平倉紀錄。o＝開倉快照（side／lots／entry／stop 初始止損／opened_ts／ticket，可加 ch 等）。"""
    contract = contract or config.CONTRACT_SIZE
    hkd_per_usd = hkd_per_usd or config.HKD_PER_USD
    side, lots, entry, stop0 = int(o.get("side") or 0), _f(o.get("lots")), _f(o.get("entry")), _f(o.get("stop"))
    exit_ = r = None
    if side and lots and entry is not None:
        move = pnl_hkd / hkd_per_usd * (config.QUOTE_PER_USD or 1.0) / (lots * contract)      # HKD → 美元 → 報價貨幣 → 每單位價差
        exit_ = round(entry + side * move, config.PRICE_DIGITS)
        base = _f(o.get("decision_price"))
        base = entry if base is None else base                       # R 分母同 TEST_RESULTS 一致：AI 決策價（跟單＝訊號價）到初始止損；冇就用成交價
        if stop0 is not None and abs(base - stop0) > 0:
            r = round(side * (exit_ - entry) / abs(base - stop0), 2)
    rec = {"ticket": o.get("ticket"), "side": side, "lots": lots, "entry": entry, "stop0": stop0, "exit_est": exit_,
           "opened_ts": o.get("opened_ts"), "closed_ts": closed_ts, "pnl_hkd": round(float(pnl_hkd), 2), "r": r}
    for k in ("ch", "id", "decision_price"):
        if o.get(k) is not None:
            rec[k] = o[k]
    return rec


def track(state, prev_pos, pos, realized, now=None, extra=None):
    """每個心跳叫一次（要喺 lots_ladder.live_close 之前，借佢嘅 lots_realized_ref 做後備參考點）。
    extra(pos) → dict：開倉快照額外欄位（例如跟單頻道）。回傳新記錄 list（通常 0 或 1 筆）。"""
    if state is None:
        return []
    now = time.time() if now is None else now
    out = []
    realized = _f(realized)
    prev_t, cur_t = (prev_pos or {}).get("ticket"), (pos or {}).get("ticket")
    closed = bool(prev_pos) and (not pos or (prev_t is not None and cur_t is not None and prev_t != cur_t))
    if closed and realized is not None:
        ref = state.get("book_ref")
        ref = state.get("lots_realized_ref") if ref is None else ref
        if ref is not None:
            o = state.get("book_open") or {}
            if o.get("ticket") != prev_t:
                o = {**{k: prev_pos.get(k) for k in KEYS}, **((extra(prev_pos) if extra else None) or {})}
            out.append(make(o, round(realized - float(ref), 2), now))
            state["book"] = [*(state.get("book") or []), *out][-MAX:]
        state.pop("book_open", None)
        state["book_ref"] = realized
    if pos:
        o = state.get("book_open")
        if not o or o.get("ticket") != cur_t:
            state["book_open"] = {**{k: pos.get(k) for k in KEYS}, **((extra(pos) if extra else None) or {})}
        elif extra and any(o.get(k) is None for k in ("ch", "decision_price")):      # 跟單 ack／決策可能遲過第一個有倉心跳：補返
            o.update({k: v for k, v in ((extra(pos) or {}).items()) if o.get(k) is None and v is not None})
    elif realized is not None:
        state["book_ref"] = realized
    return out


def merged(book, seed):
    """seed（部署前）＋成交簿；成交簿只取 seed 最後一筆之後平倉嘅，按平倉時間排。"""
    seed = [x for x in (seed or []) if isinstance(x, dict) and x.get("closed_ts")]
    last = max((x["closed_ts"] for x in seed), default=0)
    rows = seed + [x for x in (book or []) if (x.get("closed_ts") or 0) > last]
    return sorted(rows, key=lambda x: x.get("closed_ts") or 0)


def summary(rows, now=None, day_key=None, week_key=None):
    """HKD 指標：筆數、勝負、勝率、獲利因子、最大回撤、平均 R、累計、今日、本週（按 day_key／week_key，預設 HKT）。"""
    import market
    now = time.time() if now is None else now
    day_key = day_key or (lambda ts: market.fmt_hkt(ts, "%Y-%m-%d"))
    week_key = week_key or (lambda ts: time.strftime("%G-W%V", time.gmtime(ts + 8 * 3600)))
    pnls = [float(x.get("pnl_hkd") or 0.0) for x in rows]
    wins, losses = [p for p in pnls if p > 0], [-p for p in pnls if p < 0]
    cum = peak = dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    rs = [x["r"] for x in rows if x.get("r") is not None]
    today, week = day_key(now), week_key(now)
    return {"n": len(pnls), "wins": len(wins), "losses": len(losses), "flat": len(pnls) - len(wins) - len(losses),
            "win_rate": (len(wins) / len(pnls)) if pnls else None,
            "pf": (round(sum(wins) / sum(losses), 2) if wins and losses else None),
            "max_dd": round(dd, 2) if pnls else None, "avg_r": (round(sum(rs) / len(rs), 2) if rs else None),
            "total": round(sum(pnls), 2),
            "today": round(sum(float(x.get("pnl_hkd") or 0) for x in rows if day_key(x["closed_ts"]) == today), 2),
            "week": round(sum(float(x.get("pnl_hkd") or 0) for x in rows if week_key(x["closed_ts"]) == week), 2),
            "first_ts": rows[0]["closed_ts"] if rows else None}


def view(state, seed, account=None, now=None):
    """status／頁面用：逐筆（最新 40）＋指標＋EA 自己 magic 今日／累計（HKD）。"""
    rows = merged((state or {}).get("book"), seed)
    acct = account or {}
    return {"rows": rows[-40:][::-1], "summary": summary(rows, now), "seeded": len(seed or []),
            "ea_daily_hkd": _f(acct.get("daily_pnl")), "ea_realized_hkd": _f(acct.get("realized_total")),
            "open": (state or {}).get("book_open")}
