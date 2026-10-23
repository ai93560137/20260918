"""學徒計劃（xau/DAN_APPRENTICE.md 階段 0／1）純函數：訊號特徵快照、候選規則。
K 線用主服務格式 {"time": 伺服器時間, open, high, low, close}；offset＝伺服器時間 − UTC（秒）。全部只係數字，冇原文。"""
import statistics

NEAR_USD = 2.0          # 「附近」＝ 2 美元內（§21）
ZONE_HALF = 2.0         # DAN 結構：入場區 ±2
STRUCT_SL = 6.0         # SL 6 美元
STRUCT_TP = 3.0         # 6 級 TP 每 3 美元
STRUCT_N_TP = 6
REV15_USD = 3.0         # 規則 R3：前 15 分鐘反向走 ≥3 美元


def utc(bars, offset):
    return [{**b, "t": b["time"] - offset} for b in bars]


def agg(bars, n_min):
    out = {}
    for b in bars:
        k = b["t"] // (60 * n_min) * (60 * n_min)
        o = out.setdefault(k, {"t": k, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
        o["high"] = max(o["high"], b["high"]); o["low"] = min(o["low"], b["low"]); o["close"] = b["close"]
    return [out[k] for k in sorted(out)]


def swings(bars, side, w=5):
    """擺動低（BUY）／高（SELL）：±w 根內最極端嘅價。"""
    pts = []
    for j in range(w, len(bars) - w):
        win = bars[j - w:j + w + 1]
        if side == "BUY" and bars[j]["low"] == min(b["low"] for b in win):
            pts.append(bars[j]["low"])
        if side == "SELL" and bars[j]["high"] == max(b["high"] for b in win):
            pts.append(bars[j]["high"])
    return pts


def atr(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])) for p, b in zip(bars, bars[1:])]
    return round(sum(trs[-n:]) / n, 3)


def session_day_start(ts):
    """黃金交易日由 22:00 UTC 開始。"""
    return ((ts - 22 * 3600) // 86400) * 86400 + 22 * 3600


def session(ts):
    h = int(ts // 3600) % 24
    return "asia" if 0 <= h < 7 else ("london" if h < 12 else ("ny" if h < 17 else "late"))


def levels(bars_utc, ts):
    """前日高低、亞洲盤（22:00–07:00 UTC）高低、日開盤（22:00）、倫敦開盤（07:00）。bars 只有約 6.7 小時，攞唔到嘅係 None。"""
    ds = session_day_start(ts)
    def hl(a, b):
        xs = [x for x in bars_utc if a <= x["t"] < b]
        return (max(x["high"] for x in xs), min(x["low"] for x in xs)) if xs else (None, None)
    ph, pl = hl(ds - 86400, ds)
    ah, al = hl(ds, ds + 9 * 3600) if ts >= ds + 9 * 3600 else (None, None)
    def open_at(t0):
        xs = [x for x in bars_utc if t0 <= x["t"] < t0 + 300]
        return xs[0]["open"] if xs else None
    return {"prev_high": ph, "prev_low": pl, "asia_high": ah, "asia_low": al, "day_open": open_at(ds),
            "london_open": open_at(ds + 9 * 3600) if ts >= ds + 9 * 3600 else None}


def lag_in_zone(bars_utc, ts, lo, hi, tol, lookback_min=360):
    """訊息前最近一根碰到入場區（±tol）嘅 K 線距訊息幾多分鐘；6 小時內冇就 None（純掛單）。"""
    for b in reversed([x for x in bars_utc if x["t"] + 60 <= ts and x["t"] >= ts - lookback_min * 60]):
        if b["low"] <= hi + tol and b["high"] >= lo - tol:
            return round((ts - b["t"]) / 60)
    return None


def snapshot(m1, m15, offset, ts, side, mid, sl, tps, price, tol=0.3):
    """一條入場訊號收到時嘅特徵（階段 0）。m1／m15 係主服務格式。"""
    b1 = [b for b in utc(m1, offset) if b["t"] + 60 <= ts]          # 只用訊號前已收盤嘅 K 線
    b15 = [b for b in utc(m15, offset) if b["t"] + 900 <= ts]
    sgn = 1 if side == "BUY" else -1
    f = {"hour": int(ts // 3600) % 24, "sess": session(ts), "n_m1": len(b1), "n_m15": len(b15)}
    if not b1:
        return f
    f["atr15"] = atr(b15 if len(b15) >= 15 else agg(b1, 15))
    f["atr1"] = atr(b1)
    s1 = swings(b1[-120:], side); s5 = swings(agg(b1[-600:], 5), side, 3)
    f["d_swing_m1"] = round(min((abs(mid - p) for p in s1), default=99), 2); f["d_swing_m5"] = round(min((abs(mid - p) for p in s5), default=99), 2)
    f["near_swing_m1"] = f["d_swing_m1"] <= NEAR_USD
    f["swing_behind"] = any((p < mid if side == "BUY" else p > mid) and abs(mid - p) <= STRUCT_SL for p in s1)
    lv = levels(b1, ts); f["levels"] = lv
    near = {k: (v is not None and abs(mid - v) <= NEAR_USD) for k, v in lv.items()}
    f["near_level"] = [k for k, v in near.items() if v]
    f["d_round5"] = round(min(mid % 5, 5 - mid % 5), 2)
    f["move15"] = round((b1[-1]["close"] - b1[-16]["open"]) * sgn, 2) if len(b1) >= 16 else None      # 前 15 分鐘向訊號方向走咗幾多
    pre = b1[-60:]
    hh, ll = max(b["high"] for b in pre), min(b["low"] for b in pre); rng = (hh - ll) or 1e-9
    f["pos60"] = round((mid - ll) / rng, 2)
    f["m15_trend"] = ("with" if (b15[-1]["close"] - b15[-21]["close"]) * sgn > 0 else "against") if len(b15) >= 21 else None
    if sl is not None:
        f["sl_usd"] = round(abs(mid - sl), 2); f["sl_atr15"] = round(abs(mid - sl) / f["atr15"], 2) if f.get("atr15") else None
    if tps:
        f["tp1_usd"] = round(abs(tps[0] - mid), 2); f["n_tp"] = len(tps)
    if price is not None:
        f["moved_usd"] = round((price - mid) * sgn, 2)                                 # 收到時價已向有利方向走咗幾多
    lo, hi = mid - ZONE_HALF, mid + ZONE_HALF
    f["lag_min"] = lag_in_zone(b1, ts, lo, hi, tol)
    return f


def structure(price, side):
    """DAN 結構：現價反向 4 美元 ±2 入場、SL 6、6 級 TP 每 3。"""
    sgn = 1 if side == "BUY" else -1
    mid = round(price - sgn * 4.0, 2)
    return {"side": side, "entry_low": round(mid - ZONE_HALF, 2), "entry_high": round(mid + ZONE_HALF, 2),
            "sl": round(mid - sgn * STRUCT_SL, 2), "tp": [round(mid + sgn * STRUCT_TP * k, 2) for k in range(1, STRUCT_N_TP + 1)]}


def rule_candidates(m1, offset, now):
    """規則學生（階段 1）：三條候選規則喺「依家」會唔會入、邊個方向。純函數，回傳 list。
    swing：現價 2 美元內有 M1 擺動低（→BUY）／高（→SELL）且擺動點喺現價後面；
    level：現價 2 美元內有前日高／亞洲高（→SELL）或前日低／亞洲低（→BUY）；
    rev15：前 15 分鐘走 ≥3 美元 → 反向。"""
    b1 = [b for b in utc(m1, offset) if b["t"] + 60 <= now]
    if len(b1) < 30:
        return []
    price = b1[-1]["close"]; out = []
    for side, sgn in (("BUY", 1), ("SELL", -1)):
        pts = [p for p in swings(b1[-120:], side) if (price - p) * sgn > 0 and abs(price - p) <= NEAR_USD]
        if pts:
            out.append({"rule": "swing", **structure(price, side), "ref": round(min(pts, key=lambda p: abs(price - p)), 2), "price": price})
    lv = levels(b1, now)
    for k in ("prev_high", "asia_high"):
        if lv.get(k) is not None and abs(price - lv[k]) <= NEAR_USD:
            out.append({"rule": "level", **structure(price, "SELL"), "ref": k, "price": price}); break
    for k in ("prev_low", "asia_low"):
        if lv.get(k) is not None and abs(price - lv[k]) <= NEAR_USD:
            out.append({"rule": "level", **structure(price, "BUY"), "ref": k, "price": price}); break
    if len(b1) >= 16:
        mv = b1[-1]["close"] - b1[-16]["open"]
        if abs(mv) >= REV15_USD:
            out.append({"rule": "rev15", **structure(price, "BUY" if mv < 0 else "SELL"), "ref": round(mv, 2), "price": price})
    return out


def grade(pred, sig_side, sig_mid, sig_ts, zone_tol=3.0):
    """對答案：方向、入場區（中位差 ≤ zone_tol）、時間（pred 早過訊號）。"""
    pmid = (pred["entry_low"] + pred["entry_high"]) / 2
    return {"dir": pred["side"] == sig_side, "zone": abs(pmid - sig_mid) <= zone_tol, "lead_min": round((sig_ts - pred["ts"]) / 60)}


def pct(a, b):
    return round(a / b, 3) if b else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None
