"""[IDEAS #1272–#1322] 長線框架內 5 類 × 10 條（使用者 11-12「不同種類的策略，每種策略登記 10 條，一次過登記」→「甲，一路研究搵到三個合格先停」）。
框架定死：長線方向＝收市對 SMA200（高過只做多、低過只做空）。每條只改一樣嘢，其餘用固定預設（預設＝#1268 事件版：收市重新企返 SMA20 上入；
收市穿之前 20 日最低收市或者穿返 SMA200 平；SL 3×ATR14；最多 250 日；一次一張）。做空＝將價格反轉後用同一條做多規則（保證鏡像）。
規格同門檻以 IDEAS 預先登記為準（跑之前 commit；每條登記參數固定，鄰近參數只用嚟做穩健度關卡，唔會揀）。
用法：python3 research/strategy_search/frame_1272.py [--no-m1] → research/strategy_search/FRAME_1272.md"""
import datetime as dt
import os
import sys

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import fade_strict_1143 as F3   # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import oldgold_1260 as OG       # noqa: E402
import panel2_1252 as PN2       # noqa: E402
import pullback_1192 as P2      # noqa: E402
import robust_1270 as RB        # noqa: E402
import tsmom_1213 as TS         # noqa: E402

OUT = os.path.join(HERE, "FRAME_1272.md")
DIRS = (100, 150, 200, 250, 300)
SEGS = [("① Duka 2015–22", "duka", "2015-01-01", "2022-12-31"), ("② MT5 2023–26", "mt5", "2023-01-01", "2026-10-30"), ("③ Duka 2010–14", "duka", "2010-01-01", "2014-12-31")]


# ---------- 指標（全部對「做多視角」嘅 q 計；做空用反轉價格） ----------
def neg(b):
    return {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"]}


def pmax(x, p):
    """之前 p 個（唔包今日）最大值；頭 p 個係 nan。"""
    out = np.full(len(x), np.nan)
    if len(x) > p:
        out[p:] = swv(x, p).max(axis=1)[:len(x) - p]
    return out


def pmin(x, p):
    return -pmax(-x, p)


def rstd(x, p):
    out = np.full(len(x), np.nan)
    if len(x) >= p:
        out[p - 1:] = swv(x, p).std(axis=1)
    return out


def sma(x, p):
    return F2.sma(x, int(p))


def crossup(x, y):
    """x 今日 > y 而尋日 ≤ y。"""
    out = np.zeros(len(x), bool); out[1:] = (x[1:] > y[1:]) & (x[:-1] <= y[:-1])
    return out & ~np.isnan(x) & ~np.isnan(y)


def stoch(q, n=14):
    hh = np.full(len(q["c"]), np.nan); ll = hh.copy()
    hh[n - 1:] = swv(q["h"], n).max(axis=1); ll[n - 1:] = swv(q["l"], n).min(axis=1)
    return 100 * (q["c"] - ll) / np.where(hh - ll == 0, np.nan, hh - ll)


# ---------- 入場觸發（做多視角；回傳 bool 陣列） ----------
def e_base(q, a, p=20):
    return crossup(q["c"], sma(q["c"], p))


def e1(q, a, p):                                   # RSI(2) 跌穿 p
    r = PN2.rsi(q["c"], 2); return crossup(-r, np.full(len(r), -float(p)))


def e2(q, a, p):                                   # RSI(14) 由下升穿 p
    r = PN2.rsi(q["c"], 14); return crossup(r, np.full(len(r), float(p)))


def e3(q, a, p):                                   # 重新企返 SMA p
    return crossup(q["c"], sma(q["c"], p))


def e4(q, a, p):                                   # 連跌 p 日後第一支陽
    c = q["c"]; d = np.r_[0, np.diff(c)]; out = np.zeros(len(c), bool); p = int(p)
    for i in range(p + 1, len(c)):
        out[i] = d[i] > 0 and (d[i - p:i] < 0).all()
    return out


def e5(q, a, p):                                   # 由 20 日最高收市回落 ≥ p×ATR 後第一支陽
    c = q["c"]; out = np.zeros(len(c), bool); hi = pmax(c, 20)
    out[1:] = ((hi[:-1] - c[:-1]) >= p * a[:-1]) & (c[1:] > c[:-1])
    return out & ~np.isnan(np.r_[np.nan, hi[:-1]]) & ~np.isnan(np.r_[np.nan, a[:-1]])


def e6(q, a, p):                                   # 收市跌穿布林下軌（20，pσ）後企返上去
    c = q["c"]; return crossup(c, sma(c, 20) - p * rstd(c, 20))


def e7(q, a, p):                                   # 尋日收市係 p 日最低收市，今日收市高過尋日高位
    c = q["c"]; out = np.zeros(len(c), bool); lo = pmin(c, int(p) - 1)      # 尋日收市 ≤ 再之前 p−1 日最低收市
    out[1:] = (c[:-1] <= lo[:-1]) & (c[1:] > q["h"][:-1])
    return out


def e8(q, a, p):                                   # 隨機指標 %K(14) 由下升穿 p
    k = stoch(q); return crossup(k, np.full(len(k), float(p)))


def e9(q, a, p):                                   # 連續 ≥ 3 日收喺 EMA p 之下後企返上去
    c = q["c"]; e = F3.ema(c, int(p)); x = crossup(c, e); out = np.zeros(len(c), bool)
    for i in np.flatnonzero(x):
        out[i] = i >= 3 and c[i - 2] <= e[i - 2] and c[i - 3] <= e[i - 3]
    return out


def e10(q, a, p):                                  # 近 10 日試過收喺 EMA20 − p×ATR 之下，今日企返 EMA20
    c = q["c"]; e = F3.ema(c, 20); deep = (c < e - p * a); x = crossup(c, e); out = np.zeros(len(c), bool)
    for i in np.flatnonzero(x):
        out[i] = deep[max(0, i - 10):i].any()
    return out


def b1(q, a, p):                                   # 收市破之前 p 日最高收市
    return q["c"] > pmax(q["c"], int(p))


def b2(q, a, p):                                   # 尋日係 p 日最窄波幅日，今日收市高過尋日高位
    rg = q["h"] - q["l"]; out = np.zeros(len(rg), bool); p = int(p); mn = pmin(rg, p - 1)
    out[1:] = (rg[:-1] <= mn[:-1]) & (q["c"][1:] > q["h"][:-1])
    return out


def b3(q, a, p):                                   # 尋日布林帶闊度係 p 日最窄，今日收市破上軌
    c = q["c"]; sd = rstd(c, 20); mid = sma(c, 20); out = np.zeros(len(c), bool); mn = pmin(sd, int(p))
    out[1:] = (sd[:-1] <= mn[:-1]) & (c[1:] > (mid + 2 * sd)[1:])
    return out


def b4(q, a, p):                                   # 單日升 ≥ p×ATR
    c = q["c"]; out = np.zeros(len(c), bool); out[1:] = (c[1:] - c[:-1]) >= p * a[:-1]
    return out


def b5(q, a, p):                                   # 收市破之前 p 日最高位（高位，唔係收市）
    return q["c"] > pmax(q["h"], int(p))


def b6(q, a, p):                                   # 收市 > EMA20 ＋ p×ATR
    return q["c"] > F3.ema(q["c"], 20) + p * a


def b7(q, a, p):                                   # 週尾收市破之前 p 個週尾收市
    c = q["c"]; n = len(c); wk = np.array([TS.wkey(x) for x in q["t"]]); ends = [j for j in range(n) if j + 1 == n or wk[j + 1] != wk[j]]
    out = np.zeros(n, bool); wc = c[ends]; p = int(p)
    for k in range(p, len(ends)):
        out[ends[k]] = wc[k] > wc[k - p:k].max()
    return out


def b8(q, a, p):                                   # 連升 p 日（啱啱夠 p 日嗰日）
    c = q["c"]; d = np.r_[0, np.diff(c)]; out = np.zeros(len(c), bool); p = int(p)
    for i in range(p + 1, len(c)):
        out[i] = (d[i - p + 1:i + 1] > 0).all() and not d[i - p] > 0
    return out


def b9(q, a, p):                                   # 收市升穿 SMA p
    return crossup(q["c"], sma(q["c"], p))


def b10(q, a, p):                                  # ADX(14) 升穿 p 而且 +DI > −DI
    adx, pdi, mdi = P2.adx(q); return crossup(adx, np.full(len(adx), float(p))) & (pdi > mdi)


# ---------- 出場（做多視角；回傳 make(i)→ex(k)） ----------
def x_base(q, a, md, p=20):
    c = q["c"]; lo = pmin(c, int(p))
    return lambda i: (lambda k: c[k] < md[k] or c[k] < lo[k])


def x1(q, a, md, p):                               # 吊燈：收市 < 入場後最高收市 − p×ATR
    c = q["c"]
    return lambda i: (lambda k: c[k] < md[k] or c[k] < c[i + 1:k + 1].max() - p * a[k])


def x2(q, a, md, p):                               # 固定揸 p 日（mb 另設）
    c = q["c"]
    return lambda i: (lambda k: c[k] < md[k])


def x3(q, a, md, p):                               # 收市 < SMA p
    c = q["c"]; m = sma(c, p)
    return lambda i: (lambda k: c[k] < md[k] or c[k] < m[k])


def x4(q, a, md, p):                               # 收市穿之前 p 日最低收市
    return x_base(q, a, md, p)


def x5(q, a, md, p):                               # 止賺 p×R（tp 另設）＋預設出場
    return x_base(q, a, md)


def x6(q, a, md, p):                               # 收市 < EMA p
    c = q["c"]; e = F3.ema(c, int(p))
    return lambda i: (lambda k: c[k] < md[k] or c[k] < e[k])


def x7(q, a, md, p):                               # 連續 p 日收喺 SMA20 之下
    c = q["c"]; m = sma(c, 20); p = int(p)
    return lambda i: (lambda k: c[k] < md[k] or (k - p + 1 > i and (c[k - p + 1:k + 1] < m[k - p + 1:k + 1]).all()))


def x8(q, a, md, p):                               # ATR 棘輪：止蝕線＝max(之前, 收市 − p×ATR)，收市穿就走
    c = q["c"]

    def make(i):
        st = {"s": -np.inf}

        def ex(k):
            hit = c[k] < md[k] or c[k] < st["s"]
            st["s"] = max(st["s"], c[k] - p * a[k])
            return hit
        return ex
    return make


def x9(q, a, md, p):                               # 只用方向反轉（收市 < SMA200 − p×ATR）
    c = q["c"]
    return lambda i: (lambda k: c[k] < md[k] - p * a[k])


def x10(q, a, md, p):                              # RSI(14) > p 止賺＋預設出場
    c = q["c"]; r = PN2.rsi(c, 14); base = x_base(q, a, md)
    return lambda i: (lambda k, f=base(i): f(k) or r[k] > p)


# ---------- 過濾（做多視角；回傳 bool 陣列） ----------
def f1(q, a, md, p):                               # SMA200 向上（高過 p 日前）
    out = np.zeros(len(md), bool); p = int(p); out[p:] = md[p:] > md[:-p]; return out


def f2(q, a, md, p):                               # 離 SMA200 ≥ p×ATR
    return (q["c"] - md) >= p * a


def f3(q, a, md, p):                               # 離 SMA200 ≤ p×ATR（未過熱）
    return (q["c"] - md) <= p * a


def f4(q, a, md, p):                               # ADX(14) ≥ p
    return P2.adx(q)[0] >= p


def f5(q, a, md, p):                               # ATR／價 喺 250 日入面嘅百分位 ≤ p
    v = a / np.abs(q["c"]); out = np.zeros(len(v), bool)
    for i in range(250, len(v)):
        w = v[i - 249:i + 1]
        out[i] = not np.isnan(w).any() and (w <= v[i]).mean() * 100 <= p
    return out


def f6(q, a, md, p):                               # SMA p 都喺 SMA200 之上
    return sma(q["c"], p) > md


def f7(q, a, md, p):                               # 收市高過 p 日前
    c = q["c"]; out = np.zeros(len(c), bool); p = int(p); out[p:] = c[p:] > c[:-p]; return out


def f8(q, a, md, p):                               # 已經連續 p 日收喺 SMA200 之上
    ok = (q["c"] > md).astype(float); out = np.zeros(len(ok), bool); p = int(p)
    out[p - 1:] = swv(ok, p).min(axis=1) > 0
    return out


def f9(q, a, md, p):                               # 之前 5 日冇單日跌 ≥ p×ATR
    c = q["c"]; d = np.r_[0, np.diff(c)]; bad = d <= -p * np.r_[np.nan, a[:-1]]; out = np.ones(len(c), bool)
    for i in range(5, len(c)):
        out[i] = not bad[i - 5:i].any()
    return out


def f10(q, a, md, p):                              # RSI(14) > p
    return PN2.rsi(q["c"], 14) > p


# ---------- 規則表：(編號, 類, 名, 種類鍵, 函數, 登記參數, 鄰近 4 個參數) ----------
RULES = [
    ("#1272", "回調", "RSI(2) 跌穿 10", "E", e1, 10, (5, 10, 15, 20)),
    ("#1273", "回調", "RSI(14) 由下升穿 40", "E", e2, 40, (35, 40, 45, 50)),
    ("#1274", "回調", "重新企返 SMA50", "E", e3, 50, (30, 50, 70, 100)),
    ("#1275", "回調", "連跌 3 日後第一支陽", "E", e4, 3, (2, 3, 4, 5)),
    ("#1276", "回調", "由 20 日高回落 ≥ 2×ATR 後第一支陽", "E", e5, 2, (1, 2, 3, 4)),
    ("#1277", "回調", "跌穿布林下軌（1σ）後企返", "E", e6, 1, (0.5, 1, 1.5, 2)),
    ("#1278", "回調", "5 日最低收市後收市高過尋日高位", "E", e7, 5, (3, 5, 8, 10)),
    ("#1279", "回調", "隨機指標 %K 由下升穿 20", "E", e8, 20, (10, 20, 30, 40)),
    ("#1280", "回調", "連 3 日收喺 EMA10 下後企返", "E", e9, 10, (5, 10, 15, 20)),
    ("#1281", "回調", "深回調（EMA20 − 1×ATR）後企返 EMA20", "E", e10, 1, (0.5, 1, 1.5, 2)),
    ("#1282", "突破", "55 日收市新高", "B", b1, 55, (30, 55, 80, 110)),
    ("#1283", "突破", "NR7 後收市破尋日高位", "B", b2, 7, (4, 7, 10, 14)),
    ("#1284", "突破", "布林收窄（60 日最窄）後破上軌", "B", b3, 60, (30, 60, 90, 120)),
    ("#1285", "突破", "單日升 ≥ 1.5×ATR", "B", b4, 1.5, (1, 1.5, 2, 2.5)),
    ("#1286", "突破", "收市破 20 日最高位", "B", b5, 20, (10, 20, 30, 40)),
    ("#1287", "突破", "收市 > EMA20＋2×ATR", "B", b6, 2, (1, 1.5, 2, 2.5)),
    ("#1288", "突破", "週尾收市破之前 4 週", "B", b7, 4, (2, 4, 6, 8)),
    ("#1289", "突破", "連升 3 日", "B", b8, 3, (2, 3, 4, 5)),
    ("#1290", "突破", "收市升穿 SMA50", "B", b9, 50, (30, 50, 70, 100)),
    ("#1291", "突破", "ADX 升穿 25 而且同向", "B", b10, 25, (20, 25, 30, 35)),
    ("#1292", "出場", "吊燈 3×ATR", "X", x1, 3, (2, 3, 4, 5)),
    ("#1293", "出場", "固定揸 20 日", "X", x2, 20, (10, 20, 40, 60)),
    ("#1294", "出場", "收市 < SMA50", "X", x3, 50, (30, 50, 100, 150)),
    ("#1295", "出場", "收市穿 10 日最低收市", "X", x4, 10, (5, 10, 30, 40)),
    ("#1296", "出場", "止賺 3R", "X", x5, 3, (2, 3, 4, 6)),
    ("#1297", "出場", "收市 < EMA20", "X", x6, 20, (10, 20, 30, 50)),
    ("#1298", "出場", "連 2 日收喺 SMA20 下", "X", x7, 2, (1, 2, 3, 4)),
    ("#1299", "出場", "ATR 棘輪 2.5×", "X", x8, 2.5, (1.5, 2.5, 3.5, 4.5)),
    ("#1300", "出場", "只用方向反轉", "X", x9, 0, (0, 0.5, 1, 1.5)),
    ("#1301", "出場", "RSI(14) > 70 止賺", "X", x10, 70, (65, 70, 75, 80)),
    ("#1302", "過濾", "SMA200 高過 20 日前", "F", f1, 20, (10, 20, 40, 60)),
    ("#1303", "過濾", "離 SMA200 ≥ 1×ATR", "F", f2, 1, (0.5, 1, 2, 3)),
    ("#1304", "過濾", "離 SMA200 ≤ 10×ATR", "F", f3, 10, (6, 10, 14, 18)),
    ("#1305", "過濾", "ADX(14) ≥ 20", "F", f4, 20, (15, 20, 25, 30)),
    ("#1306", "過濾", "波幅百分位 ≤ 50", "F", f5, 50, (30, 50, 70, 90)),
    ("#1307", "過濾", "SMA50 都喺 SMA200 上", "F", f6, 50, (20, 30, 50, 70)),
    ("#1308", "過濾", "收市高過 252 日前", "F", f7, 252, (126, 189, 252, 315)),
    ("#1309", "過濾", "已連續 20 日喺 SMA200 上", "F", f8, 20, (10, 20, 40, 60)),
    ("#1310", "過濾", "之前 5 日冇單日逆向 ≥ 2.5×ATR", "F", f9, 2.5, (1.5, 2, 2.5, 3)),
    ("#1311", "過濾", "RSI(14) > 50", "F", f10, 50, (45, 50, 55, 60)),
    ("#1312", "倉位", "賺 1×ATR 加一張", "P", "add_atr", 1, (0.5, 1, 1.5, 2)),
    ("#1313", "倉位", "賺 2×ATR 加一張", "P", "add_atr", 2, (1.5, 2, 2.5, 3)),
    ("#1314", "倉位", "持倉中收市破 20 日新高加一張", "P", "add_high", 20, (10, 20, 30, 40)),
    ("#1315", "倉位", "一半 2R 止賺", "P", "partial", 2, (1.5, 2, 2.5, 3)),
    ("#1316", "倉位", "一半 3R 止賺", "P", "partial", 3, (2.5, 3, 4, 5)),
    ("#1317", "倉位", "賺過 1R 後收市返到入場價就走", "P", "be", 1, (0.5, 1, 1.5, 2)),
    ("#1318", "倉位", "10 日後仲未賺就走", "P", "timestop", 10, (5, 10, 15, 20)),
    ("#1319", "倉位", "止蝕收窄到 2×ATR", "P", "ksl", 2, (1.5, 2, 2.5, 3.5)),
    ("#1320", "倉位", "止蝕放闊到 4×ATR", "P", "ksl", 4, (3.5, 4, 5, 6)),
    ("#1321", "倉位", "蝕完一張之後跳過下一個訊號", "P", "skip", 1, (1, 2, 3, 4)),
]
BASE = ("#1268e", "基準", "#1268 事件版（預設）", "E", e_base, 20, (20,))


def simulate(cx, rule, nd=200, p=None):
    """回傳 [(入場 ts, 方向, R)]。"""
    key, fn = rule[3], rule[4]; p = rule[5] if p is None else p
    b = cx.b; a = B.atr(b); n = len(b["c"]); out = []; busy = -1; skip = 0
    side = {}
    for sg, q in ((1, b), (-1, neg(b))):
        md = sma(q["c"], nd)
        trig = fn(q, a, p) if key in ("E", "B") else e_base(q, a)
        filt = fn(q, a, md, p) if key == "F" else None
        if key == "X":
            mk = fn(q, a, md, p)
        elif key == "B":
            mk = x_base(q, a, md, 10)
        else:
            mk = x_base(q, a, md)
        side[sg] = (q, md, trig, filt, mk)
    k_sl = float(p) if (key == "P" and fn == "ksl") else 3.0
    mb = int(p) if (key == "X" and fn is x2) else 250
    tp = float(p) if (key == "X" and fn is x5) else None
    for i in range(max(nd, 60) + 1, n - 1):
        if i <= busy or np.isnan(a[i]):
            continue
        sg = 0
        for s in (1, -1):
            q, md, trig, filt, mk = side[s]
            if not np.isnan(md[i]) and q["c"][i] > md[i] and trig[i] and (filt is None or filt[i]):
                sg = s; break
        if not sg:
            continue
        if skip > 0:
            skip -= 1; continue
        q, md, trig, filt, mk = side[sg]; ex0 = mk(i); en = q["o"][i + 1]; risk = k_sl * a[i]
        ex = ex0
        if key == "P" and fn == "be":
            ex = lambda k, f=ex0, i=i, en=en, risk=risk, q=q: f(k) or (q["c"][i + 1:k + 1].max() >= en + p * risk and q["c"][k] <= en)  # noqa: E731
        elif key == "P" and fn == "timestop":
            ex = lambda k, f=ex0, i=i, en=en, q=q: f(k) or (k - i >= p and q["c"][k] <= en)  # noqa: E731
        x = M.trade_m1(cx, i, sg, risk, tp, mb, (lambda k, s, ex=ex: ex(k)))
        if not x:
            continue
        r = x[2]; kx = x[3]
        if key == "P" and fn == "partial":
            ex2 = mk(i)
            y = M.trade_m1(cx, i, sg, risk, float(p), mb, (lambda k, s, ex=ex2: ex(k)))
            r = (r + y[2]) / 2 if y else r
        out.append((x[0], sg, r)); busy = kx
        if key == "P" and fn in ("add_atr", "add_high"):
            c = q["c"]; hi = pmax(c, int(p)) if fn == "add_high" else None
            for j in range(i + 1, kx):
                if (c[j] >= en + p * a[i]) if fn == "add_atr" else (c[j] > hi[j]):
                    if kx - j >= 1 and not np.isnan(a[j]):
                        ex3 = mk(i)
                        z = M.trade_m1(cx, j, sg, 3.0 * a[j], None, kx - j, (lambda k, s, ex=ex3: ex(k)))
                        if z:
                            out.append((z[0], sg, z[2]))
                    break
        if key == "P" and fn == "skip" and r < 0:
            skip = int(p)
    return sorted(out)


def st(tr):
    return OG.stats(tr)


def seg(tr, y0, y1):
    return [x for x in tr if y0 <= OG.year(x[0]) <= y1]


def main():
    no_m1 = "--no-m1" in ARGV
    restore = OG.patch("gold"); gd = RB.load(); cxg = M3.d1ctx(gd)
    res, nb = {}, {}
    try:
        for rule in [BASE] + RULES:
            res[rule[0]] = simulate(cxg, rule)
            if rule is not BASE:
                cnt = 0
                for nd in DIRS:
                    for p in rule[6]:
                        tr = simulate(cxg, rule, nd, p)
                        cnt += st(seg(tr, 1975, 2004))[1] > 0 and st(seg(tr, 2005, 2026))[1] > 0
                nb[rule[0]] = cnt
            print(rule[0], len(res[rule[0]]), nb.get(rule[0]), flush=True)
    finally:
        restore()
    restore = OG.patch("silver"); cxs = M3.d1ctx(OG.load("xagusd", "1968-01-01"))
    try:
        sil = {rule[0]: [x for x in simulate(cxs, rule) if OG.year(x[0]) >= 1970] for rule in [BASE] + RULES}
    finally:
        restore()
    base_old = st(seg(res[BASE[0]], 1975, 2004)); mk = lambda v: "✅" if v else "❌"  # noqa: E731
    g_old = {}
    for rule in RULES:
        tr = seg(res[rule[0]], 1975, 2004); n, avg, pf = st(tr)
        a1 = st(seg(tr, 1975, 1989))[1]; a2 = st(seg(tr, 1990, 2004))[1]
        lo = st([x for x in tr if x[1] > 0])[1]; sh = st([x for x in tr if x[1] < 0])[1]; sa = st(sil[rule[0]])[1]
        nmin = 40 if rule[3] == "F" else 60
        g1 = a1 > 0 and a2 > 0 and lo > 0 and sh > 0 and pf >= 1.15 and n >= nmin and sa > 0
        g3 = nb[rule[0]] >= 16
        g4o = rule[3] in ("E", "B") or pf > base_old[2]
        g_old[rule[0]] = (n, avg, pf, a1, a2, lo, sh, sa, g1, g3, g4o)
    cand = [r for r in RULES if all(g_old[r[0]][8:])]
    new = {}; base_new = None
    if not no_m1 and cand:
        data = [A.load(src, a_, b_) for _, src, a_, b_ in SEGS]; cxs_ = [M3.d1ctx(d) for d in data]
        for rule in [BASE] + cand:
            cells, ok, allr, allsg = [], True, [], []
            for cx in cxs_:
                tr = simulate(cx, rule); r = np.array([x[2] for x in tr]); good = len(r) >= 5 and r.mean() > 0; ok = ok and good
                allr += list(r); allsg += [x[1] for x in tr]; cells.append(f"{len(r)} 張 {r.mean() if len(r) else 0:+.2f}{mk(good)}")
            r = np.array(allr); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()) if len(r) else 0.0
            new[rule[0]] = (cells, ok and pf >= 1.15, pf, float(r.mean()) if len(r) else 0.0, len(r))
            print("M1", rule[0], cells, f"PF {pf:.2f}", flush=True)
        base_new = new[BASE[0]]
    L = ["# 長線框架內 5 類 × 10 條（IDEAS #1272–#1321）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；框架：收市對 SMA200 定方向；每條只改一樣，其餘用預設（#1268 事件版）",
         "- 關 1（舊黃金 1975–2004 日線）：前後兩半、多空每張平均都 > 0、PF ≥ 1.15、張數 ≥ 60（過濾類 ≥ 40）、白銀 1970–2004 > 0",
         "- 關 3（鄰近參數）：方向均線 100／150／200／250／300 × 4 個參數＝20 組，1975–2004 同 2005–2026 每張平均都 > 0 嘅 ≥ 16 組",
         "- 關 4（出場／過濾／倉位三類）：PF 要高過基準（舊黃金同新黃金各自比）",
         "- 關 2（新黃金 2010–2026 M1 嚴格版；只跑過咗關 1、3、4 舊黃金部分嘅）：三段每段平均 > 0（≥ 5 張）、合併 PF ≥ 1.15",
         f"- 基準（#1268 事件版）：舊黃金 {base_old[0]} 張 {base_old[1]:+.3f}R PF {base_old[2]:.2f}" + (f"；新黃金合併 {base_new[4]} 張 {base_new[3]:+.3f}R PF {base_new[2]:.2f}" if base_new else ""), "",
         "| IDEAS | 類 | 規則 | 舊黃金 張／平均／PF | 前半／後半 | 多／空 | 白銀 | 關 1 | 鄰近 | 關 3 | 關 4 舊 | 新黃金三段／合併 PF | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    passed = []
    for rule in RULES:
        n, avg, pf, a1, a2, lo, sh, sa, g1, g3, g4o = g_old[rule[0]]
        if rule[0] in new:
            cells, ok2, pf2, _, _ = new[rule[0]]; g4n = rule[3] in ("E", "B") or pf2 > base_new[2]
            ntxt = " ".join(cells) + f"／{pf2:.2f}{mk(ok2)}" + ("" if rule[3] in ("E", "B") else f"（對基準 {mk(g4n)}）"); final = ok2 and g4n
        else:
            ntxt, final = ("未跑（--no-m1）" if (no_m1 and g1 and g3 and g4o) else "—"), False
        L.append(f"| {rule[0]} | {rule[1]} | {rule[2]} | {n}／{avg:+.3f}／{pf:.2f} | {a1:+.2f}／{a2:+.2f} | {lo:+.2f}／{sh:+.2f} | {sa:+.3f} | {mk(g1)} | {nb[rule[0]]}／20 | {mk(g3)} | "
                 f"{'—' if rule[3] in ('E', 'B') else mk(g4o)} | {ntxt} | {'✅ 合格' if final else '❌'} |")
        if final:
            passed.append(rule[0])
    L += ["", f"- 過關 1：{sum(1 for r in RULES if g_old[r[0]][8])}／50；過關 3：{sum(1 for r in RULES if g_old[r[0]][9])}／50；入到新黃金確認：{len(cand)} 條",
          f"- **合格：{'、'.join(passed) if passed else '冇'}**（共 {len(passed)} 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L[-4:]))


if __name__ == "__main__":
    main()
