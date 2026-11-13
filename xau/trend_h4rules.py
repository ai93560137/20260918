"""[IDEAS #1421，使用者 11-13「#1421 轉真倉」] H4 收市規則（純計算，冇 I/O），同回測 research/strategy_search/h4wide_1402.py（MACD／X4）一致：
  h4macd（#1421）：方向＝日線 #1268 狀態機（trend_d1rules.td_state）喺「上一個已完成 UTC 日」嘅狀態（+1 只做多、−1 只做空、0 唔做）；
        入場＝H4（UTC 0／4／8／12／16／20 時開）收市時 MACD(12,26,9) 柱由 ≤ 0 轉 > 0（做空鏡像），只睇 08:00／12:00／16:00 UTC 開嗰三根，
        下一根 H4 開市市價入；SL＝max(2×ATR14(H4), 3 美元, 0.3×上一日 D1 ATR14)，伺服器端，冇 TP；
        出場＝入場後任何一根 H4 收市穿之前 20 根最低（做空：最高）收市 → 下一根開市平；或者新一日嘅日線狀態唔再係持倉方向 → 新一日第一個心跳平。
        一次一張；冇時間上限。回測：2010–2026 共 273 張、勝率 34%、平均 +0.505R、PF 1.89、每月最大回撤 13.3R。"""
import trend_d1rules as D1R

H4 = 14400
NAMES = {"h4macd": "日線 #1268 狀態方向＋H4 MACD 柱轉正（#1421）"}
RULES = tuple(NAMES)
KEEP = 400            # 狀態保留幾多根 H4（MACD 要夠長先同全歷史一致；400 根約 67 日）
MIN_BARS = 150        # 少過呢個數唔出訊號
LATE_SEC = 900        # 新一根 H4 開咗超過 15 分鐘先見到訊號＝唔追


def h4_merge(h4, bars, keep=KEEP):
    """bars：UTC K 線 [{"t","open","high","low","close"}] → 合併入 h4（key＝t // 14400 字串）。同 trend_live.d1_merge 一樣嘅合併規則。純函數。"""
    h4 = {k: dict(v) for k, v in (h4 or {}).items()}
    for b in bars:
        k = str(int(b["t"]) // H4)
        r = h4.get(k)
        if r is None:
            h4[k] = {"o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "t0": int(b["t"]), "t1": int(b["t"])}
            continue
        r["h"], r["l"] = max(r["h"], b["high"]), min(r["l"], b["low"])
        if b["t"] < r["t0"]:
            r["o"], r["t0"] = b["open"], int(b["t"])
        if b["t"] >= r["t1"]:
            r["c"], r["t1"] = b["close"], int(b["t"])
    if len(h4) > keep:
        for k in sorted(h4, key=int)[:-keep]:
            h4.pop(k)
    return h4


def bars_of(h4):
    return [(int(k), h4[k]) for k in sorted(h4 or {}, key=int)]


def ema(xs, span):
    a = 2.0 / (span + 1.0); out = []; e = None
    for x in xs:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def macd_hist(c):
    m = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    return [a - b for a, b in zip(m, ema(m, 9))]


def atr(bars, n=14):
    """同 intraday_1323.atr：TR 用上一根收市（第一根用自己），ATR[i]＝最近 n 個 TR 平均（i ≥ n−1 先有）。"""
    tr = []
    for i, (_, r) in enumerate(bars):
        pc = bars[i - 1][1]["c"] if i else r["c"]
        tr.append(max(r["h"] - r["l"], abs(r["h"] - pc), abs(r["l"] - pc)))
    return [None if i < n - 1 else sum(tr[i - n + 1:i + 1]) / n for i in range(len(tr))]


def day_ctx(days_done):
    """已完成日線 → (今日適用嘅 #1268 狀態, 上一日 D1 ATR14)。日線唔夠就 (0, None)。"""
    if len(days_done) < 203:
        return 0, None
    a = D1R.atr(days_done)
    return int(D1R.td_state(days_done)[-1]), a[-1]


def eligible(key):
    sod = (int(key) * H4) % 86400
    return 7 * 3600 <= sod < 20 * 3600


def signal(rule, done, st, fa):
    """最後一根已完成 H4 有冇訊號 → {"side","risk"} 或 None。st／fa 由 day_ctx 畀。"""
    if rule != "h4macd" or len(done) < MIN_BARS or not st or fa is None or not eligible(done[-1][0]):
        return None
    c = [r["c"] for _, r in done]; h = macd_hist(c); a = atr(done)
    if a[-1] is None or not (st * h[-1] > 0 and st * h[-2] <= 0):
        return None
    return {"side": int(st), "risk": max(2.0 * a[-1], 3.0, 0.3 * fa)}


def plan_open(rule, done, st, fa, price, digits=2):
    """→ 開倉 sig（period＝入場嗰根 H4 嘅 key＝訊號根 +1）或 None。止蝕距離用現價（真倉入場價）計。"""
    sig = signal(rule, done, st, fa)
    if not sig or price is None:
        return None
    sg = sig["side"]
    return {"rule": rule, "side": sg, "sl": round(price - sg * sig["risk"], digits), "period": done[-1][0] + 1, "risk": round(sig["risk"], digits)}


def trail_hit(side, done, entry_key):
    """入場嗰根（含）之後，有冇任何一根已完成 H4 收市穿之前 20 根相反極端收市。"""
    q = [side * r["c"] for _, r in done]
    for j in range(len(done) - 1, -1, -1):
        if done[j][0] < int(entry_key):
            break
        if j >= 20 and q[j] < min(q[j - 20:j]):
            return True
    return False


def plan_exit(pos, done, st, today):
    """持倉中 → 平倉原因或 None。pos 要有 rule、side、period（入場 H4 key）。st＝今日適用嘅日線狀態；today＝UTC 日數。"""
    if pos.get("rule") not in RULES:
        return None
    side, e = int(pos.get("side") or 0), int(pos.get("period") or 0)
    if int(today) > (e * H4) // 86400 and st != side:
        return "日線 #1268 狀態唔再係持倉方向"
    if trail_hit(side, done, e):
        return "H4 收市穿 20 根相反極端收市"
    return None
