"""[IDEAS #159] 規則學生參數擬合（rev15／level／rev15x／swing）。網格、分段、揀法同成功標準以 IDEAS #159 預先登記為準。

快速引擎（numpy）重現 rev15_gap.py 嘅邏輯：
- 出區：同 features.rule_candidates（只用訊號分鐘之前已收盤嘅 K 線；level 用最近 W 根窗口）；冷卻由上次出區分鐘計
- 成交同結果：同 signals.evaluate（區 ±SIG_FILL_TOL、近邊／開盤成交、TTL 30 分鐘、同一根 SL／TP 都掂當 SL、24 小時內未完唔計）
- R：同 student.score_pending／rev15_gap.r_of：(出場 − 成交 − STUDENT_COST) ／ (中位 − SL)
規則全部用相對價（走幅、距離），所以 PAXG／期貨嘅基差唔使對齊。
用法：python3 research/student_offline/fit_rules.py [rev15 level rev15x swing] [--check]"""
import bisect
import datetime as dt
import itertools
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv_orig = list(sys.argv)
sys.argv = [sys.argv[0], "rev15"]
sys.path.insert(0, HERE)
import rev15_gap as g   # noqa: E402  （設好 XAU_BOOK=signal 先 import config，PREFIX＝xau/sig/）
sys.argv = sys.argv_orig
config = g.config

COST = config.STUDENT_COST
TOL = config.SIG_FILL_TOL
TTL = config.SIG_TTL_MIN * 60
HORIZON = 24 * 60
CACHE = "/tmp/fit_rules_cache"

IS = ("2026-07-24", "2026-10-01")          # 擬合段 [a, b)
OOS = ("2026-10-01", "2026-10-31")         # 時間樣本外
MIN_IS_N = 100

COMMON = {"E": (2.0, 4.0, 6.0), "Z": (0.5, 1.0, 2.0), "S": (4.0, 6.0, 8.0), "RT": (1.0, 1.5, 2.0), "CD": (30, 60)}
SPECIFIC = {
    "rev15": {"LB": (10, 15, 30), "TH": (3.0, 5.0, 8.0), "DIR": ("fade", "follow")},
    "rev15x": {"LB": (10, 15, 30), "TH": (3.0, 5.0, 8.0), "DIR": ("fade", "follow"), "HRS": ("cur", "all"), "AR": (0.9, 1.1)},
    "level": {"NEAR": (1.0, 2.0, 3.0), "W": (400, 1440)},
    "swing": {"NEAR": (1.0, 2.0, 3.0), "SW": (3, 5, 10)},
}
CURRENT = {
    "rev15": {"LB": 15, "TH": 3.0, "DIR": "fade"},
    "rev15x": {"LB": 15, "TH": 3.0, "DIR": "fade", "HRS": "cur", "AR": 0.9},
    "level": {"NEAR": 2.0, "W": 400},
    "swing": {"NEAR": 2.0, "SW": 5},
}
CUR_COMMON = {"E": 4.0, "Z": 2.0, "S": 6.0, "RT": 2.0, "CD": 60}


def ts_of(d):
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp())


# ---------------------------------------------------------------- 數據
def load_src(src):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{src}.npz")
    if os.path.exists(f):
        z = np.load(f)
        return {k: z[k] for k in ("t", "o", "h", "l", "c")}
    days = g.days_between("2026-07-20", "2026-10-31")
    if src == "duka":
        bars = g.load(g.config.PREFIX + "duka/", days, "json")
    elif src == "broker":
        bars = _broker(g)
    else:
        bars = g.load(f"{g.config.PREFIX}alt/{src}/", days, "json")
        if src == "paxg":
            bars = [b for b in bars if not _closed(b["time"])]
    d = {"t": np.array([b["time"] for b in bars], dtype=np.int64)}
    for k, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        d[k] = np.array([b[n] for b in bars], dtype=np.float64)
    np.savez(f, **d)
    return d


def _broker(g):
    sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
    import gb_rulesim as gb   # noqa: E402
    bars = gb.fetch_broker_bars(gb.Gcs(), 10)
    return [{"time": b["utc"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in bars]


def _closed(t):
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    wd, h = d.weekday(), d.hour
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)


# ---------------------------------------------------------------- 區間極值（sparse table）
class RMQ:
    def __init__(self, a, fn):
        self.fn = fn
        self.t = [a]
        k = 1
        while (1 << k) <= len(a):
            p = self.t[-1]
            self.t.append(fn(p[:-(1 << (k - 1))], p[(1 << (k - 1)):]))
            k += 1

    def q(self, lo, hi):
        """[lo, hi) 向量化；lo>=hi 回 nan。"""
        lo = np.asarray(lo); hi = np.asarray(hi)
        ln = np.maximum(hi - lo, 1)
        k = np.floor(np.log2(ln)).astype(int)
        out = np.full(lo.shape, np.nan)
        ok = hi > lo
        for kk in np.unique(k[ok]):
            m = ok & (k == kk)
            tb = self.t[kk]
            out[m] = self.fn(tb[lo[m]], tb[hi[m] - (1 << kk)])
        return out


# ---------------------------------------------------------------- 出區（每分鐘 raw，未冷卻）
def raw_signals(d, rule, p):
    """回傳 list of (i, side)；i＝訊號 K 線索引（now＝t[i]+60）。"""
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t)
    idx = np.arange(n)
    out = []
    if rule in ("rev15", "rev15x"):
        lb = p["LB"]
        mv = np.full(n, np.nan)
        mv[lb:] = c[lb:] - o[:-lb]
        ok = (np.abs(mv) >= p["TH"]) & (idx >= 29)
        if rule == "rev15x":
            ok &= _rev15x_mask(d, p)
        fade = p["DIR"] == "fade"
        for i in np.nonzero(ok)[0]:
            down = mv[i] < 0
            out.append((int(i), ("BUY" if down else "SELL") if fade else ("SELL" if down else "BUY")))
        return out
    if rule == "level":
        return _level(d, p)
    if rule == "swing":
        return _swing(d, p)
    raise ValueError(rule)


_X = {}


def _rev15x_mask(d, p):
    key = (id(d), p["HRS"], p["AR"])
    if key in _X:
        return _X[key]
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    now = t + 60
    hr = (now // 3600) % 24
    hours = ((hr >= 1) & (hr <= 6)) | ((hr >= 12) & (hr <= 15)) if p["HRS"] == "cur" else np.ones(len(t), bool)
    # M15
    k15 = t // 900 * 900
    keys, first = np.unique(k15, return_index=True)
    last = np.r_[first[1:], len(t)] - 1
    H = np.maximum.reduceat(h, first); L = np.minimum.reduceat(l, first); C = c[last]
    tr = np.r_[np.nan, np.maximum.reduce([H[1:] - L[1:], np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])])]
    cs = np.r_[0, np.nancumsum(np.nan_to_num(tr))]
    # ATR(14) 用到第 j 根（含）：mean(tr[j-13..j])，要 j>=14
    def atr_at(j):
        j = np.asarray(j)
        a = (cs[j + 1] - cs[j - 13]) / 14
        return np.where(j >= 14, a, np.nan)
    # 每分鐘：已收盤 M15 ＝ keys <= now-900 → 最後一根 jn；_m15_upto 只留最近 60 根，len>=35；ATR(b15[:-20]) 即 jn-20
    jn = np.searchsorted(keys, now - 900, side="right") - 1
    cnt = np.minimum(jn + 1, 60)
    ok = (jn >= 0) & (cnt >= 35)
    jn_c = np.clip(jn, 0, None)
    # _m15_upto 截咗最近 60 根，ATR 只睇最尾 15 根，所以同全序列一樣（只要窗口內夠 15 根）
    a_now = atr_at(np.clip(jn_c, 14, None)); a_old = atr_at(np.clip(jn_c - 20, 14, None))
    a_now = np.where(jn_c >= 14, a_now, np.nan); a_old = np.where(jn_c - 20 >= 14, a_old, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.round(a_now / a_old, 3)
    a_now = np.round(a_now, 3); a_old = np.round(a_old, 3)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.round(a_now / a_old, 3)
    ok &= (a_now > 0) & (a_old > 0)                        # features.atr_ratio：ATR 係 0（週末平盤）回 None
    m = hours & ok & (ratio >= p["AR"])
    _X[key] = m
    return m


_RMQ = {}


def _rmq(d):
    if id(d) not in _RMQ:
        _RMQ[id(d)] = (RMQ(d["h"], np.maximum), RMQ(d["l"], np.minimum))
    return _RMQ[id(d)]


def _level(d, p):
    t, c = d["t"], d["c"]
    n = len(t)
    W = p["W"]; near = p["NEAR"]
    rh, rl = _rmq(d)
    now = t + 60
    ds = (now - 22 * 3600) // 86400 * 86400 + 22 * 3600
    i = np.arange(n)
    j0 = np.maximum(0, i - W + 1)
    # 窗口內 K 線（只用 t+60<=now，即 <= i）
    a_prev = np.maximum(j0, np.searchsorted(t, ds - 86400, side="left"))
    b_prev = np.minimum(i + 1, np.searchsorted(t, ds, side="left"))
    a_as = np.maximum(j0, np.searchsorted(t, ds, side="left"))
    b_as = np.minimum(i + 1, np.searchsorted(t, ds + 9 * 3600, side="left"))
    ph, pl = rh.q(a_prev, b_prev), rl.q(a_prev, b_prev)
    ah, al = rh.q(a_as, b_as), rl.q(a_as, b_as)
    has_as = now >= ds + 9 * 3600
    ah = np.where(has_as, ah, np.nan); al = np.where(has_as, al, np.nan)
    valid = (i - j0 + 1) >= 30
    with np.errstate(invalid="ignore"):
        sell = valid & ((np.abs(c - ph) <= near) | (np.abs(c - ah) <= near))
        buy = valid & ((np.abs(c - pl) <= near) | (np.abs(c - al) <= near))
    out = []
    for k in np.nonzero(sell | buy)[0]:
        if sell[k]:
            out.append((int(k), "SELL"))
        if buy[k]:
            out.append((int(k), "BUY"))
    return out


def _swing(d, p):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    n = len(t)
    w = p["SW"]; near = p["NEAR"]
    from numpy.lib.stride_tricks import sliding_window_view as swv
    lowmin = np.full(n, np.nan); highmax = np.full(n, np.nan)
    lowmin[w:n - w] = swv(l, 2 * w + 1).min(axis=1)
    highmax[w:n - w] = swv(h, 2 * w + 1).max(axis=1)
    piv_lo = np.nonzero(l == lowmin)[0]; piv_hi = np.nonzero(h == highmax)[0]
    out = []
    for i in range(29, n):
        a, b = i - 119 + w, i - w      # pivot 位置要喺最近 120 根入面、左右各 w 根都喺窗口內
        price = c[i]
        s0, s1 = bisect.bisect_left(piv_lo, a), bisect.bisect_right(piv_lo, b)
        if s1 > s0:
            x = price - l[piv_lo[s0:s1]]
            if np.any((x > 0) & (x <= near)):
                out.append((i, "BUY"))
        s0, s1 = bisect.bisect_left(piv_hi, a), bisect.bisect_right(piv_hi, b)
        if s1 > s0:
            x = h[piv_hi[s0:s1]] - price
            if np.any((x > 0) & (x <= near)):
                out.append((i, "SELL"))
    return out


def cooldown(raw, t, cd_min, t_from, t_to):
    out, last = [], -10**12
    cur_i = None
    for i, side in raw:
        now = int(t[i]) + 60
        if not (t_from <= now < t_to):
            continue
        if i == cur_i:                       # 同一分鐘第二個方向（level 兩邊）：原腳本同一分鐘都收
            out.append((i, side)); continue
        if now - last < cd_min * 60:
            continue
        out.append((i, side)); last = now; cur_i = i
    return out


# ---------------------------------------------------------------- 成交同結果（矩陣，全部翻成 BUY）
def future_mats(d, sigs):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t)
    m = len(sigs)
    O = np.full((m, HORIZON), np.nan); H = O.copy(); L = O.copy(); T = np.full((m, HORIZON), 10**9, dtype=np.int64)
    for r, (i, side) in enumerate(sigs):
        a, b = i + 1, min(n, i + 1 + HORIZON)
        k = b - a
        if k <= 0:
            continue
        px = c[i]; now = t[i] + 60
        if side == "BUY":
            O[r, :k] = o[a:b] - px; H[r, :k] = h[a:b] - px; L[r, :k] = l[a:b] - px
        else:
            O[r, :k] = px - o[a:b]; H[r, :k] = px - l[a:b]; L[r, :k] = px - h[a:b]
        T[r, :k] = t[a:b] - now
    return O, H, L, T


def simulate(mats, E, Z, S, RT):
    O, H, L, T = mats
    m = O.shape[0]
    if m == 0:
        return np.array([])
    mid = -E; lo, hi = mid - Z, mid + Z; sl = mid - S; tp = mid + RT * S
    fm = (L <= hi + TOL) & (H >= lo - TOL) & (T <= TTL)          # evaluate：t > msg_ts+TTL 就唔成交（t 係開盤；T＝t−now，now＝msg_ts）
    has = fm.any(axis=1)
    f = fm.argmax(axis=1)
    rows = np.arange(m)
    fill = np.minimum(O[rows, f], np.maximum(hi, L[rows, f]))
    cols = np.arange(O.shape[1])[None, :]
    after = cols >= f[:, None]
    slh = (L <= sl) & after
    tph = (H >= tp) & after
    s_any, t_any = slh.any(axis=1), tph.any(axis=1)
    si = np.where(s_any, slh.argmax(axis=1), 10**9); ti = np.where(t_any, tph.argmax(axis=1), 10**9)
    done = has & (s_any | t_any)
    is_sl = si <= ti
    ex = np.where(is_sl, sl, tp)
    r = (ex - fill - COST) / S
    return np.where(done, r, np.nan)


def stats(r):
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return {"n": 0, "avg": None, "pf": None, "streak": 0, "sum": 0.0}
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    s = mx = 0
    for x in r:
        s = s + 1 if x < 0 else 0; mx = max(mx, s)
    return {"n": int(len(r)), "avg": float(r.mean()), "pf": float(w / ls) if ls > 0 else float("inf"), "streak": mx, "sum": float(r.sum())}


def fmt(s):
    if not s["n"]:
        return "n=0"
    return f"n={s['n']} 平均 {s['avg']:+.3f}R ΣR {s['sum']:+.1f} PF {s['pf']:.2f} 連敗 {s['streak']}"


# ---------------------------------------------------------------- 主流程
def evaluate_rule(d, rule, sp, cp, t_from, t_to):
    raw = raw_signals(d, rule, sp)
    sigs = cooldown(raw, d["t"], cp["CD"], t_from, t_to)
    mats = future_mats(d, sigs)
    r = simulate(mats, cp["E"], cp["Z"], cp["S"], cp["RT"])
    ts = np.array([int(d["t"][i]) + 60 for i, _ in sigs])
    return r, ts


def grid(rule):
    sk = list(SPECIFIC[rule]); ck = list(COMMON)
    for sv in itertools.product(*[SPECIFIC[rule][k] for k in sk]):
        for cv in itertools.product(*[COMMON[k] for k in ck]):
            yield dict(zip(sk, sv)), dict(zip(ck, cv))


def key_of(rule, sp, cp):
    return tuple(SPECIFIC[rule][k].index(sp[k]) for k in SPECIFIC[rule]) + tuple(COMMON[k].index(cp[k]) for k in COMMON)


def fit(rule, duka, paxg, out):
    t0 = int(duka["t"][0]) + 2 * 86400
    tis0, tis1 = max(t0, ts_of(IS[0])), ts_of(IS[1])
    toos0, toos1 = ts_of(OOS[0]), ts_of(OOS[1])
    res = {}
    sk = list(SPECIFIC[rule])
    raw_cache = {}
    for sv in itertools.product(*[SPECIFIC[rule][k] for k in sk]):
        sp = dict(zip(sk, sv))
        raw = raw_signals(duka, rule, sp)
        for cd in COMMON["CD"]:
            sigs = cooldown(raw, duka["t"], cd, t0, toos1)
            mats = future_mats(duka, sigs)
            ts = np.array([int(duka["t"][i]) + 60 for i, _ in sigs])
            is_m = (ts >= tis0) & (ts < tis1)
            for E, Z, S, RT in itertools.product(COMMON["E"], COMMON["Z"], COMMON["S"], COMMON["RT"]):
                cp = {"E": E, "Z": Z, "S": S, "RT": RT, "CD": cd}
                r = simulate(mats, E, Z, S, RT)
                res[key_of(rule, sp, cp)] = (sp, cp, stats(r[is_m]))
    # 平台分
    keys = list(res)
    dims = [len(SPECIFIC[rule][k]) for k in sk] + [len(COMMON[k]) for k in COMMON]
    plateau = {}
    for k, (sp, cp, s) in res.items():
        if s["n"] < MIN_IS_N:
            continue
        vals = [s["avg"]]
        for dpos in range(len(dims)):
            for step in (-1, 1):
                nk = list(k); nk[dpos] += step
                nk = tuple(nk)
                if nk in res and res[nk][2]["n"] >= MIN_IS_N:
                    vals.append(res[nk][2]["avg"])
        plateau[k] = statistics.median(vals)
    ranked = sorted(plateau, key=lambda k: -plateau[k])
    out.append(f"## {rule}")
    out.append(f"- 網格：{len(res)} 組（擬合段成交 ≥ {MIN_IS_N} 張嘅有 {len(plateau)} 組）")
    # 現行參數
    cur_k = key_of(rule, CURRENT[rule], CUR_COMMON)
    sp, cp, s = res[cur_k]
    out.append(f"- 現行參數 擬合段：{fmt(s)}")
    # 樣本外評估：所有合資格組合 → 過關比例（隨機對照）
    def oos(sp, cp):
        rd, tsd = evaluate_rule(duka, rule, sp, cp, t0, toos1)
        rp, tsp = evaluate_rule(paxg, rule, sp, cp, int(paxg["t"][0]) + 2 * 86400, toos1)
        full = stats(rd)
        octo = stats(rd[(tsd >= toos0) & (tsd < toos1)])
        pax = stats(rp)
        months = {}
        for mth in ("2026-07", "2026-08", "2026-09", "2026-10"):
            a = ts_of(mth + "-01"); b = ts_of({"2026-07": "2026-08", "2026-08": "2026-09", "2026-09": "2026-10", "2026-10": "2026-11"}[mth] + "-01")
            months[mth] = stats(rd[(tsd >= a) & (tsd < b)])
        pos_m = sum(1 for v in months.values() if v["n"] and v["avg"] > 0)
        ok = {"①10月≥30張+0.2R PF1.3": octo["n"] >= 30 and (octo["avg"] or -9) >= 0.2 and (octo["pf"] or 0) >= 1.3,
              "②PAXG +0.1R PF1.15": pax["n"] > 0 and pax["avg"] >= 0.1 and pax["pf"] >= 1.15,
              "③全期連敗≤6": full["streak"] <= 6,
              "④≥3個月正": pos_m >= 3}
        return full, octo, pax, months, ok
    cur = oos(CURRENT[rule], CUR_COMMON)
    out.append(f"- 現行參數 Dukascopy 全期：{fmt(cur[0])}｜10 月：{fmt(cur[1])}｜PAXG：{fmt(cur[2])}")
    best = ranked[0] if ranked else None
    verdict = None
    if best is not None:
        sp, cp, s = res[best]
        full, octo, pax, months, ok = oos(sp, cp)
        verdict = all(ok.values())
        out.append(f"- **揀中（平台分 {plateau[best]:+.3f}R）**：{json.dumps({**sp, **cp}, ensure_ascii=False)}")
        out.append(f"  - 擬合段：{fmt(s)}")
        out.append(f"  - 樣本外 10 月（Dukascopy）：{fmt(octo)}")
        out.append(f"  - 樣本外 PAXG 全期：{fmt(pax)}")
        out.append(f"  - Dukascopy 全期：{fmt(full)}；每月：" + "、".join(f"{k[5:]}月 {v['avg']:+.2f}R（{v['n']}）" if v["n"] else f"{k[5:]}月 n=0" for k, v in months.items()))
        out.append(f"  - 判斷：" + "；".join(f"{k} {'✓' if v else '✗'}" for k, v in ok.items()) + f" → **{'達標' if verdict else '唔達標'}**")
    # 前 10 名 + 隨機對照（前 50 名平台分組合入面，樣本外過關比例）
    out.append("- 平台分前 5：")
    for k in ranked[:5]:
        sp, cp, s = res[k]
        out.append(f"  - {plateau[k]:+.3f}R｜{json.dumps({**sp, **cp}, ensure_ascii=False)}｜擬合段 {fmt(s)}")
    top = ranked[:50]
    passed = 0
    oct_avgs = []
    for k in top:
        sp, cp, _ = res[k]
        r = oos(sp, cp)
        passed += all(r[4].values())
        if r[1]["n"]:
            oct_avgs.append(r[1]["avg"])
    if top:
        out.append(f"- 平台分前 {len(top)} 組：樣本外四項全過 {passed} 組；10 月平均 R 中位 {statistics.median(oct_avgs):+.3f}（擬合段排名同樣本外有冇關係嘅參考）")
    # 全部合資格組合 10 月平均 R 分佈（隨機對照）
    sample = ranked[::max(1, len(ranked) // 60)]
    rnd = []
    for k in sample:
        sp, cp, _ = res[k]
        rd, tsd = evaluate_rule(duka, rule, sp, cp, t0, toos1)
        s = stats(rd[(tsd >= toos0) & (tsd < toos1)])
        if s["n"]:
            rnd.append(s["avg"])
    if rnd:
        out.append(f"- 隨機對照（合資格組合均勻抽 {len(rnd)} 組）：10 月平均 R 中位 {statistics.median(rnd):+.3f}，> +0.2R 嘅佔 {sum(1 for x in rnd if x >= 0.2) / len(rnd):.0%}")
    out.append("")
    return verdict


def check(duka):
    """用現行參數核快速引擎 vs rev15_gap.py 已發佈結果（Dukascopy 全期）。"""
    ref = {"rev15": (1137, -0.072), "level": (333, 0.151), "swing": (1414, -0.072), "rev15x": (486, 0.040)}
    t0 = int(duka["t"][0]) + 2 * 86400
    t1 = int(duka["t"][-1]) + 60
    lines = []
    for rule, (n, a) in ref.items():
        r, _ = evaluate_rule(duka, rule, CURRENT[rule], CUR_COMMON, t0, min(t1, ts_of("2026-10-29")))
        s = stats(r)
        lines.append(f"- {rule}：快速引擎 {fmt(s)}；rev15_gap.py n={n} 平均 {a:+.3f}R；差 {s['avg'] - a:+.3f}R")
    return lines


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rules = args or ["rev15", "level", "rev15x", "swing"]
    duka = load_src("duka")
    paxg = load_src("paxg")
    out = ["# 規則學生參數擬合（IDEAS #159，預先登記）", "",
           f"- 擬合段 Dukascopy {IS[0]}→{IS[1]}（不含）；時間樣本外 {OOS[0]}→{OOS[1]}；數據源樣本外 PAXG 全期",
           f"- 成本 {COST} 美元／張；成交容差 ±{TOL}；TTL {TTL // 60} 分鐘；24 小時未完唔計", "", "## 引擎核對（現行參數，Dukascopy 07-26→10-29）"]
    out += check(duka)
    out.append("")
    if "--check" in sys.argv:
        print("\n".join(out)); return
    for rule in rules:
        fit(rule, duka, paxg, out)
        print("\n".join(out[-25:]), flush=True)
    path = os.path.join(HERE, "FIT_RULES_out.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"寫咗 {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
