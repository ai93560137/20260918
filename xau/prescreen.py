"""慳成本 S（使用者 10-23「開 S shadow」；xau/COST_PLAN.md §6）：空倉時規則前篩——只喺以下其中一樣先問 Opus：
(a) 新 M15 收盤；(b) 價格離上次真正問 Opus 嘅價 ≥ PRESCREEN_ATR_MULT × M1 ATR；
(c) 價格距最近 M1 擺動點／前日高低／亞洲盤高低 ≤ PRESCREEN_NEAR；(d) 前 15 分鐘走 ≥ PRESCREEN_MOVE15。
模式 XAU_PRESCREEN：off｜shadow（預設：照問 Opus，只記「規則會唔問」同開倉有冇落喺呢啲分鐘）｜on（唔問，kind=prescreen cost 0）。
純函數，冇 I/O。Haiku 篩選仍然喺後面（S 過咗先到 Haiku）。"""
import config
import features
import hold_rules
import market


def mode():
    m = (getattr(config, "PRESCREEN", "shadow") or "shadow").lower()
    return m if m in ("off", "shadow", "on") else "shadow"


def evaluate(m1, m15, price, anchor, offset, now, last_m15_time=None):
    """回傳 {"ask": bool, "reasons": [...], "near": 最近參考位距離}。anchor＝上次問 Opus 嘅 {price, m15_time}（冇就一定問）。"""
    out = {"ask": False, "reasons": [], "near": None}
    if not anchor or anchor.get("price") is None:
        out.update(ask=True, reasons=["冇上次決策"])
        return out
    m15_time = m15[-1]["time"] if m15 else None
    if m15_time is not None and anchor.get("m15_time") != m15_time:
        out["reasons"].append("新 M15")
    atr1 = market.wilder_atr(m1)
    if atr1 and abs(price - anchor["price"]) >= config.PRESCREEN_ATR_MULT * atr1:
        out["reasons"].append(f"價格變動 ≥ {config.PRESCREEN_ATR_MULT:g}×M1 ATR")
    recent = m1[-120:]
    pts = hold_rules.strict_swings(recent, 1) + hold_rules.strict_swings(recent, -1)
    try:
        b1 = features.utc(m1, offset or 0)
        lv = features.levels(b1, now)
        pts += [v for k, v in lv.items() if v is not None and k in ("prev_high", "prev_low", "asia_high", "asia_low")]
    except Exception:
        pass
    if pts:
        near = min(abs(price - p) for p in pts)
        out["near"] = round(near, config.PRICE_DIGITS)
        if near <= config.PRESCREEN_NEAR:
            out["reasons"].append(f"貼近擺動點／關鍵價位（{near:.{config.PRICE_DIGITS}f}）")
    if len(m1) >= 16:
        mv = m1[-1]["close"] - m1[-16]["open"]
        if abs(mv) >= config.PRESCREEN_MOVE15:
            out["reasons"].append(f"前 15 分鐘走 {mv:+.{config.PRICE_DIGITS}f}")
    out["ask"] = bool(out["reasons"])
    return out


def bump(stats, ask, opened=False):
    """shadow／on 統計：minutes、skip（規則唔問嘅分鐘）、opens（實際開倉）、opens_in_skip（開倉落喺規則唔問嘅分鐘＝漏單）。"""
    st = dict(stats or {})
    for k in ("minutes", "skip", "opens", "opens_in_skip"):
        st.setdefault(k, 0)
    st["minutes"] += 1
    if not ask:
        st["skip"] += 1
    if opened:
        st["opens"] += 1
        if not ask:
            st["opens_in_skip"] += 1
    st["skip_pct"] = round(100.0 * st["skip"] / st["minutes"], 1) if st["minutes"] else None
    st["opens_kept_pct"] = round(100.0 * (st["opens"] - st["opens_in_skip"]) / st["opens"], 1) if st["opens"] else None
    return st
