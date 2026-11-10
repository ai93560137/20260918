"""[11-10 使用者「揾多 5 條行真倉 69 戶口」→ 穩陣組] D1 收市規則（純計算，冇 I/O），同回測一致：
  spike（#1165，research/strategy_search/momo_strict_1164.r1165）：D1 收市升（跌）≥ 1.5×前一日 ATR14 而且收市喺 SMA50 上（下）→ 順勢；
        SL 2×前一日 ATR14；收市穿 5 日相反極端（做多：收市低過之前 5 日最低）即平；10 根 D1 到期。
  wide（#1174，momo_strict_1171.r1174）：D1 幅度 ≥ 2×前一日 ATR14、收陽（陰）→ 順勢；SL＝該日中位；5 根 D1 到期。
  kelt（#1178，momo_strict_1178.r1178）：收市 > EMA20＋2×ATR14（< EMA20−2×ATR14）→ 順勢；SL 2×ATR14；收市返過 EMA20 即平；20 根到期。
  ichi（#1224，strict_b_1220.st_ichimoku）：一目均衡表狀態（收市喺雲上＋轉換線 > 基準線＝+1，雲下＋轉換 < 基準＝−1，入雲＝0）由非 s 轉 s → 入；
        SL 2×ATR14；狀態離開 s 即平；120 根到期。
  turtle（#1116，h1_lab8.r1116）：收市 > 之前 55 日最高收市（< 最低）→ 順勢；SL 2×ATR20；收市穿之前 20 日相反極端即平；120 根到期。
共通（同 momo_strict_1157.trade_m1）：訊號用「已完成」D1（UTC 日）；下一根開市入（真倉＝新一日第一個心跳市價）；
最低止蝕＝max(3 美元, 0.3×訊號日前一日 ATR14)；一個 magic 一次一張；平倉嗰根（或者止蝕嗰日）之前嘅訊號唔入（busy）。
days：[(UTC 日, {"o","h","l","c"}), …]，只傳已完成嘅日線。"""

NAMES = {"spike": "D1 急動＋SMA50（#1165）", "wide": "D1 寬幅日（#1174）", "kelt": "D1 Keltner（#1178）",
         "ichi": "一目均衡表穿雲（#1224）", "turtle": "海龜系統 2（#1116）"}
MAX_BARS = {"spike": 10, "wide": 5, "kelt": 20, "ichi": 120, "turtle": 120}
RULES = tuple(NAMES)


def atr(days, n=14):
    """同 batch_1019.atr：TR 用上日收市（第一日用自己），ATR[i]＝最近 n 個 TR 平均（i ≥ n 先有）。"""
    out, tr = [], []
    for i, (_, r) in enumerate(days):
        pc = days[i - 1][1]["c"] if i else r["c"]
        tr.append(max(r["h"] - r["l"], abs(r["h"] - pc), abs(r["l"] - pc)))
        out.append(sum(tr[i - n + 1:i + 1]) / n if i >= n else None)
    return out


def sma(xs, n):
    return [sum(xs[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(xs))]


def ema(xs, n):
    """同 fade_strict_1143.ema：頭 n 個平均做種子。"""
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2 / (n + 1); out[n - 1] = sum(xs[:n]) / n
    for i in range(n, len(xs)):
        out[i] = out[i - 1] + k * (xs[i] - out[i - 1])
    return out


def ichi_state(days):
    h = [r["h"] for _, r in days]; l = [r["l"] for _, r in days]; c = [r["c"] for _, r in days]; n = len(c); s = [0] * n

    def mid(k, p):
        a = max(0, k - p + 1)
        return (max(h[a:k + 1]) + min(l[a:k + 1])) / 2
    for i in range(78, n):
        ten, kij = mid(i, 9), mid(i, 26); j = i - 26
        sa = (mid(j, 9) + mid(j, 26)) / 2; sb = mid(j, 52); top, bot = max(sa, sb), min(sa, sb)
        if c[i] > top:
            s[i] = 1 if ten > kij else (1 if s[i - 1] == 1 else 0)
        elif c[i] < bot:
            s[i] = -1 if ten < kij else (-1 if s[i - 1] == -1 else 0)
    return s


def floor(days):
    """最低止蝕：max(3, 0.3×訊號日前一日 ATR14)。"""
    a = atr(days)
    prev = a[-2] if len(a) >= 2 else None
    return None if prev is None else max(3.0, 0.3 * prev)


def signal(rule, days):
    """最後一根已完成 D1 有冇訊號 → {"side", "risk"（未計最低止蝕）, "mid"（wide 用）} 或 None。"""
    if len(days) < 2:
        return None
    o = [r["o"] for _, r in days]; h = [r["h"] for _, r in days]; l = [r["l"] for _, r in days]; c = [r["c"] for _, r in days]
    i = len(c) - 1
    if rule == "spike":
        a = atr(days); m = sma(c, 50)
        if i < 51 or a[i - 1] is None or a[i - 1] <= 0 or m[i] is None:
            return None
        mv = c[i] - c[i - 1]
        sg = 1 if (mv >= 1.5 * a[i - 1] and c[i] > m[i]) else (-1 if (mv <= -1.5 * a[i - 1] and c[i] < m[i]) else 0)
        return {"side": sg, "risk": 2 * a[i - 1]} if sg else None
    if rule == "wide":
        a = atr(days)
        if i < 15 or a[i - 1] is None or a[i - 1] <= 0 or (h[i] - l[i]) < 2 * a[i - 1] or c[i] == o[i]:
            return None
        return {"side": 1 if c[i] > o[i] else -1, "risk": None, "mid": (h[i] + l[i]) / 2}
    if rule == "kelt":
        a = atr(days); e = ema(c, 20)
        if i < 21 or a[i] is None or e[i] is None:
            return None
        sg = 1 if c[i] > e[i] + 2 * a[i] else (-1 if c[i] < e[i] - 2 * a[i] else 0)
        return {"side": sg, "risk": 2 * a[i]} if sg else None
    if rule == "ichi":
        a = atr(days); s = ichi_state(days)
        if a[i] is None or s[i] == 0 or s[i] == s[i - 1]:
            return None
        return {"side": s[i], "risk": 2 * a[i]}
    if rule == "turtle":
        a = atr(days, 20)
        if i < 56 or a[i] is None or a[i] <= 0:
            return None
        sg = 1 if c[i] > max(c[i - 55:i]) else (-1 if c[i] < min(c[i - 55:i]) else 0)
        return {"side": sg, "risk": 2 * a[i]} if sg else None
    return None


def exit_hit(rule, side, days):
    """最後一根已完成 D1 收市有冇觸發規則出場 → 原因或 None（到期另計）。"""
    if len(days) < 2:
        return None
    h = [r["h"] for _, r in days]; l = [r["l"] for _, r in days]; c = [r["c"] for _, r in days]; k = len(c) - 1
    if rule == "spike":
        if k >= 5 and ((c[k] < min(l[k - 5:k])) if side > 0 else (c[k] > max(h[k - 5:k]))):
            return "收市穿 5 日相反極端"
    elif rule == "kelt":
        e = ema(c, 20)
        if e[k] is not None and ((c[k] < e[k]) if side > 0 else (c[k] > e[k])):
            return "收市返過 EMA20"
    elif rule == "ichi":
        if ichi_state(days)[k] != side:
            return "一目狀態離開"
    elif rule == "turtle":
        if k >= 20 and ((c[k] < min(c[k - 20:k])) if side > 0 else (c[k] > max(c[k - 20:k]))):
            return "收市穿 20 日相反極端"
    return None


def plan_open(rule, days, price):
    """已完成日線＋現價 → 開倉 sig（{"rule","side","sl","period"}）或 None。period＝訊號日。止蝕距離用現價（真倉入場價）計。"""
    sig = signal(rule, days)
    fl = floor(days)
    if not sig or fl is None or price is None:
        return None
    sg = sig["side"]
    risk = (price - sig["mid"]) * sg if rule == "wide" else sig["risk"]
    risk = max(risk or 0.0, fl)
    return {"rule": rule, "side": sg, "sl": round(price - sg * risk, 2), "period": days[-1][0], "risk": round(risk, 2)}


def plan_exit(pos, days):
    """持倉中：已完成日線 → 平倉原因或 None。pos 要有 rule、side、period（訊號日）。入場嗰根＝訊號日後第一根。"""
    rule = pos.get("rule")
    if rule not in RULES:
        return None
    held = [d for d, _ in days if d > int(pos.get("period") or 0)]
    if not held:
        return None
    if len(held) >= MAX_BARS[rule]:
        return f"{MAX_BARS[rule]} 根 D1 到期"
    return exit_hit(rule, int(pos.get("side") or 0), days)
