"""[11-10 使用者「揾多 5 條行真倉 69 戶口」→ 穩陣組] D1 收市規則（純計算，冇 I/O），同回測一致：
  spike（#1165，research/strategy_search/momo_strict_1164.r1165）：D1 收市升（跌）≥ 1.5×前一日 ATR14 而且收市喺 SMA50 上（下）→ 順勢；
        SL 2×前一日 ATR14；收市穿 5 日相反極端（做多：收市低過之前 5 日最低）即平；10 根 D1 到期。
  wide（#1174，momo_strict_1171.r1174）：D1 幅度 ≥ 2×前一日 ATR14、收陽（陰）→ 順勢；SL＝該日中位；5 根 D1 到期。
  kelt（#1178，momo_strict_1178.r1178）：收市 > EMA20＋2×ATR14（< EMA20−2×ATR14）→ 順勢；SL 2×ATR14；收市返過 EMA20 即平；20 根到期。
  ichi（#1224，strict_b_1220.st_ichimoku）：一目均衡表狀態（收市喺雲上＋轉換線 > 基準線＝+1，雲下＋轉換 < 基準＝−1，入雲＝0）由非 s 轉 s → 入；
        SL 2×ATR14；狀態離開 s 即平；120 根到期。
  turtle（#1116，h1_lab8.r1116）：收市 > 之前 55 日最高收市（< 最低）→ 順勢；SL 2×ATR20；收市穿之前 20 日相反極端即平；120 根到期。
  td（#1268，research/strategy_search/topdown_1268.r1268；11-11 使用者「#1268 開真倉」）：由上而下——長線方向＝收市對 SMA200；
        方向向上而且收市由 SMA20 之下升返上去 → 買（向下相反）；SL 3×ATR14；收市穿之前 20 日相反極端收市、或者穿返 SMA200 → 平；250 根到期。
        狀態機同回測一樣（狀態維持期間唔再出訊號，止蝕之後要等狀態歸零再重新觸發）；用最多 420 日日線由頭計。
  長線框架四條（research/strategy_search/frame_1272.py；11-12 使用者「將另外五條都加真倉」→ 揀「取代證據弱嘅簿」）：
        全部先用收市對 SMA200 定方向（上面只做多、下面只做空）；SL 3×ATR14；250 根到期；做空＝將價格反轉後用同一條做多規則。
        tdrsi（#1273）：RSI(14) 由下升穿 40 → 入；收市穿之前 20 日相反極端收市或者穿返 SMA200 → 平。
        tdsurge（#1285）：單日收市升 ≥ 1.5×前一日 ATR14 → 入；收市穿之前 10 日相反極端收市或者穿返 SMA200 → 平。
        tdx50（#1290）：收市升穿 SMA50 → 入；出場同 tdsurge（10 日）。
        tdflip（#1300）：收市重新企返 SMA20 → 入；只喺收市穿返 SMA200 先平。
        呢四條係「事件版」：冇倉時每次觸發都可以入（唔似 td 要等狀態歸零）。
共通（同 momo_strict_1157.trade_m1）：訊號用「已完成」D1（UTC 日）；下一根開市入（真倉＝新一日第一個心跳市價）；
最低止蝕＝max(3 美元, 0.3×訊號日前一日 ATR14)；一個 magic 一次一張；平倉嗰根（或者止蝕嗰日）之前嘅訊號唔入（busy）。
days：[(UTC 日, {"o","h","l","c"}), …]，只傳已完成嘅日線。"""

NAMES = {"spike": "D1 急動＋SMA50（#1165）", "wide": "D1 寬幅日（#1174）", "kelt": "D1 Keltner（#1178）",
         "ichi": "一目均衡表穿雲（#1224）", "turtle": "海龜系統 2（#1116）", "td": "200 日線方向＋回調重拾 20 日線（#1268）",
         "tdrsi": "200 日線方向＋RSI(14) 升穿 40（#1273）", "tdsurge": "200 日線方向＋單日升 ≥ 1.5×ATR（#1285）",
         "tdx50": "200 日線方向＋升穿 SMA50（#1290）", "tdflip": "200 日線方向＋重拾 20 日線、只用方向反轉出場（#1300）"}
MAX_BARS = {"spike": 10, "wide": 5, "kelt": 20, "ichi": 120, "turtle": 120, "td": 250, "tdrsi": 250, "tdsurge": 250, "tdx50": 250, "tdflip": 250}
FRAME = ("tdrsi", "tdsurge", "tdx50", "tdflip")
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


def td_state(days, nd=200, ne=20):
    """#1268 狀態機（同 topdown_1268.r1268 build 一樣）：+1／−1／0。"""
    c = [r["c"] for _, r in days]; n = len(c); md, me = sma(c, nd), sma(c, ne); s = [0] * n; cur = 0
    for i in range(nd + 1, n):
        up, dn = c[i] > md[i], c[i] < md[i]
        if cur > 0 and (not up or c[i] < min(c[i - ne:i])):
            cur = 0
        elif cur < 0 and (not dn or c[i] > max(c[i - ne:i])):
            cur = 0
        if cur == 0:
            if up and c[i] > me[i] and c[i - 1] <= me[i - 1]:
                cur = 1
            elif dn and c[i] < me[i] and c[i - 1] >= me[i - 1]:
                cur = -1
        s[i] = cur
    return s


def _neg(days):
    """價格反轉（做空當做多計）。"""
    return [(d, {"o": -r["o"], "h": -r["l"], "l": -r["h"], "c": -r["c"]}) for d, r in days]


def rsi(c, n=14):
    """同 panel2_1252.rsi（Wilder）：頭 n 個變動平均做種子。"""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    up = [max(c[i] - c[i - 1], 0.0) if i else 0.0 for i in range(len(c))]; dn = [max(c[i - 1] - c[i], 0.0) if i else 0.0 for i in range(len(c))]
    au = sum(up[1:n + 1]) / n; ad = sum(dn[1:n + 1]) / n
    out[n] = 100 - 100 / (1 + au / (ad if ad else 1e-12))
    for i in range(n + 1, len(c)):
        au = (au * (n - 1) + up[i]) / n; ad = (ad * (n - 1) + dn[i]) / n
        out[i] = 100 - 100 / (1 + au / (ad if ad else 1e-12))
    return out


def _frame_long(rule, days):
    """做多視角：最後一日有冇入場觸發（已包方向：收市 > SMA200）。"""
    c = [r["c"] for _, r in days]; i = len(c) - 1
    if i < 202:
        return False
    md = sma(c, 200)
    if md[i] is None or not c[i] > md[i]:
        return False
    if rule == "tdrsi":
        r = rsi(c)
        return r[i] is not None and r[i - 1] is not None and r[i] > 40 and r[i - 1] <= 40
    if rule == "tdsurge":
        a = atr(days)
        return a[i - 1] is not None and (c[i] - c[i - 1]) >= 1.5 * a[i - 1]
    n = 50 if rule == "tdx50" else 20
    m = sma(c, n)
    return m[i] is not None and m[i - 1] is not None and c[i] > m[i] and c[i - 1] <= m[i - 1]


def _frame_exit_long(rule, days):
    c = [r["c"] for _, r in days]; k = len(c) - 1
    md = sma(c, 200)
    if md[k] is not None and c[k] < md[k]:
        return "收市穿返 SMA200"
    if rule == "tdflip":
        return None
    n = 20 if rule == "tdrsi" else 10
    if k >= n and c[k] < min(c[k - n:k]):
        return f"收市穿 {n} 日相反極端收市"
    return None


def floor(days, min_abs=3.0):
    """最低止蝕：max(min_abs, 0.3×訊號日前一日 ATR14)。min_abs 係價格單位（黃金 3 美元；白銀等其他產品由 config 畀，預設 0）。"""
    a = atr(days)
    prev = a[-2] if len(a) >= 2 else None
    return None if prev is None else max(float(min_abs), 0.3 * prev)


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
    if rule in FRAME:
        a = atr(days)
        if a[i] is None:
            return None
        sg = 1 if _frame_long(rule, days) else (-1 if _frame_long(rule, _neg(days)) else 0)
        return {"side": sg, "risk": 3 * a[i]} if sg else None
    if rule == "td":
        a = atr(days); st = td_state(days)
        if i < 202 or a[i] is None or st[i] == 0 or st[i] == st[i - 1]:
            return None
        return {"side": st[i], "risk": 3 * a[i]}
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
    elif rule in FRAME:
        return _frame_exit_long(rule, days if side > 0 else _neg(days))
    elif rule == "td":
        if td_state(days)[k] != side:
            return "收市穿 20 日相反極端／穿返 SMA200"
    elif rule == "turtle":
        if k >= 20 and ((c[k] < min(c[k - 20:k])) if side > 0 else (c[k] > max(c[k - 20:k]))):
            return "收市穿 20 日相反極端"
    return None


def plan_open(rule, days, price, long_only=False, min_abs=3.0, digits=2):
    """已完成日線＋現價 → 開倉 sig（{"rule","side","sl","period"}）或 None。period＝訊號日。止蝕距離用現價（真倉入場價）計。
    long_only（[IDEAS #1442] 白銀只做多）：做空訊號當冇；min_abs／digits：最低止蝕（價格單位）同報價小數位，預設＝黃金。"""
    sig = signal(rule, days)
    fl = floor(days, min_abs)
    if not sig or fl is None or price is None:
        return None
    sg = sig["side"]
    if long_only and sg < 0:
        return None
    risk = (price - sig["mid"]) * sg if rule == "wide" else sig["risk"]
    risk = max(risk or 0.0, fl)
    return {"rule": rule, "side": sg, "sl": round(price - sg * risk, digits), "period": days[-1][0], "risk": round(risk, digits)}


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
