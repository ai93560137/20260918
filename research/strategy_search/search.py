"""[IDEAS #161] XAUUSD 系統化策略搜尋。家族、參數格、三段切分、揀法同合格標準以 IDEAS #161 預先登記為準。

兩步（中間 commit 揀中名單先做最終測試，防止睇咗結果再改）：
  python3 research/strategy_search/search.py search   # 搜尋段＋驗證段 → selected.json＋SEARCH_out.md
  python3 research/strategy_search/search.py final    # 只讀 selected.json，最終測試段（Dukascopy＋PAXG）一次 → FINAL_out.md

成交模型：訊號喺 M1 收盤時判斷，下一根 M1 開盤市價入；SL＝k×M15 ATR(14)（判斷時已收盤嘅 M15）；TP＝R 倍；
時間止蝕＝入場後 T 小時嗰根收盤；同一根 SL／TP 都掂當 SL；每張扣 COST 美元；同一策略同時最多 1 張（後到訊號略過）。
數據：GCS xau/sig/duka/<日>.json（Dukascopy 現貨 M1）、xau/sig/alt/paxg/<日>.json（剔週末）。"""
import datetime as dt
import itertools
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "research", "gb_rulesim"))

COST = 0.5
CACHE = "/tmp/strategy_search_cache"
SEARCH = ("2023-01-01", "2026-01-01")
VALID = ("2026-01-01", "2026-07-24")
FINAL = ("2026-07-24", "2026-10-31")
MIN_SEARCH_N = 150
MAX_H = 24 * 60

EXITS = {"K": (1.0, 1.5, 2.0), "R": (1.0, 1.5, 2.0, 3.0), "T": (4, 24)}

FAMILIES = {
    "F1_orb": {"S": ("07:00", "13:30"), "N": (15, 30, 60), "DIR": ("follow", "fade")},
    "F2_asia": {"END": ("10:00", "12:00"), "DIR": ("follow", "fade")},
    "F3_donchian": {"TF": ("M15", "H1"), "N": (20, 55)},
    "F3_ema": {"FS": ((9, 21), (20, 50))},
    "F4_rsi": {"TH": (20, 25), "FILT": ("none", "h1trend")},
    "F5_prevday": {"DIR": ("follow", "fade")},
    "F6_round": {"STEP": (10, 25), "DIR": ("bounce", "break")},
    "F7_tod": {"H": tuple(range(0, 24, 2)), "DIR": ("long", "short")},
    "F8_squeeze": {"DIR": ("follow", "fade")},
}


def ts_of(d):
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp())


# ------------------------------------------------------------------ 數據
def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]


def _closed(t):
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    wd, h = d.weekday(), d.hour
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)


def load(src, a, b):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{src}_{a}_{b}.npz")
    if os.path.exists(f):
        z = np.load(f)
        return {k: z[k] for k in z.files}
    import gb_rulesim as gb
    g = gb.Gcs()
    prefix = "xau/sig/duka/" if src == "duka" else f"xau/sig/alt/{src}/"
    rows = {}
    for d in days_between(a, b):
        doc = g.read_json(f"{prefix}{d}.json")
        for r in doc or []:
            t = int(r[0])
            if src == "paxg" and _closed(t):
                continue
            rows[t] = r
    ks = sorted(rows)
    out = {"t": np.array(ks, dtype=np.int64)}
    for j, k in enumerate(("o", "h", "l", "c"), 1):
        out[k] = np.array([float(rows[t][j]) for t in ks])
    # Dukascopy 週末有平盤 K 線：剔走（high==low 而且同前一根收市一樣）
    flat = (out["h"] == out["l"]) & (np.r_[np.nan, out["c"][:-1]] == out["c"])
    for k in out:
        out[k] = out[k][~flat]
    np.savez(f, **out)
    return out


# ------------------------------------------------------------------ 指標
class TF:
    """較高時框（秒數 sec）：每根 M1 對應「判斷時已收盤」嘅最後一根索引 j[i]。"""

    def __init__(self, d, sec):
        t = d["t"]
        key = t // sec * sec
        self.keys, first = np.unique(key, return_index=True)
        last = np.r_[first[1:], len(t)] - 1
        self.o = d["o"][first]; self.c = d["c"][last]
        self.h = np.maximum.reduceat(d["h"], first); self.l = np.minimum.reduceat(d["l"], first)
        self.j = np.searchsorted(self.keys, t + 60 - sec, side="right") - 1      # start+sec <= t+60
        self.new = np.r_[True, self.j[1:] != self.j[:-1]]                       # 啱啱收咗一根新嘅
        tr = np.r_[self.h[0] - self.l[0], np.maximum.reduce([self.h[1:] - self.l[1:], np.abs(self.h[1:] - self.c[:-1]), np.abs(self.l[1:] - self.c[:-1])])]
        cs = np.r_[0, np.cumsum(tr)]
        n = 14
        self.atr = np.full(len(tr), np.nan)
        self.atr[n - 1:] = (cs[n:] - cs[:-n]) / n

    def at(self, arr, i, back=0):
        j = self.j[i] - back
        return np.where(j >= 0, arr[np.clip(j, 0, None)], np.nan)


def ema(x, n):
    a = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for k in range(1, len(x)):
        out[k] = a * x[k] + (1 - a) * out[k - 1]
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = ema(up, 2 * n - 1), ema(dn, 2 * n - 1)       # Wilder ≈ EMA(2n−1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + au / ad)


def edges(mask):
    return mask & ~np.r_[False, mask[:-1]]


class Ctx:
    def __init__(self, d):
        self.d = d
        self.m15 = TF(d, 900)
        self.h1 = TF(d, 3600)
        t = d["t"]
        self.sec = t % 86400
        self.gday = (t - 22 * 3600) // 86400          # 黃金交易日（22:00 UTC 開始）
        self._cache = {}

    def atr15(self):
        if "atr" not in self._cache:
            self._cache["atr"] = self.m15.at(self.m15.atr, np.arange(len(self.d["t"])))
        return self._cache["atr"]


def hm(s):
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


# ------------------------------------------------------------------ 家族 → 訊號 (i, +1/−1)
def signals(ctx, fam, p):
    d = ctx.d
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t)
    sec = ctx.sec
    out_b = np.zeros(n, bool); out_s = np.zeros(n, bool)
    if fam == "F1_orb":
        s0 = hm(p["S"]); s1 = s0 + p["N"] * 60
        day = t // 86400
        in_rng = (sec >= s0) & (sec < s1)
        after = (sec >= s1 - 60) & (sec < s1 + 180 * 60)
        hi = np.full(n, np.nan); lo = np.full(n, np.nan)
        # 每日區間高低
        ud = np.unique(day[in_rng])
        rh = {int(k): v for k, v in zip(ud, [h[in_rng & (day == k)].max() for k in ud])} if len(ud) else {}
        rl = {int(k): v for k, v in zip(ud, [l[in_rng & (day == k)].min() for k in ud])} if len(ud) else {}
        idx = np.nonzero(after & (sec >= s1 - 60))[0]
        idx = idx[sec[idx] >= s1 - 60]
        for i in idx:
            k = int(day[i])
            if k in rh and sec[i] + 60 > s1:
                hi[i], lo[i] = rh[k], rl[k]
        up = after & (c > hi); dn = after & (c < lo)
        first = {}
        for i in np.nonzero(up | dn)[0]:
            k = int(day[i])
            if k in first:
                continue
            first[k] = i
            isup = bool(up[i])
            if p["DIR"] == "fade":
                isup = not isup
            (out_b if isup else out_s)[i] = True
    elif fam == "F2_asia":
        gd = ctx.gday
        asia = sec >= 22 * 3600
        asia |= sec < 7 * 3600
        end = hm(p["END"])
        win = (sec >= 7 * 3600) & (sec < end)
        keys = np.unique(gd)
        ah = {}; al = {}
        for k in keys:
            m = (gd == k) & asia
            if m.any():
                ah[int(k)], al[int(k)] = h[m].max(), l[m].min()
        first = set()
        for i in np.nonzero(win)[0]:
            k = int(gd[i])
            if k in first or k not in ah:
                continue
            if c[i] > ah[k] or c[i] < al[k]:
                first.add(k)
                isup = c[i] > ah[k]
                if p["DIR"] == "fade":
                    isup = not isup
                (out_b if isup else out_s)[i] = True
    elif fam == "F3_donchian":
        tf = ctx.m15 if p["TF"] == "M15" else ctx.h1
        N = p["N"]
        from numpy.lib.stride_tricks import sliding_window_view as swv
        hh = np.full(len(tf.c), np.nan); ll = np.full(len(tf.c), np.nan)
        if len(tf.c) > N:
            hh[N:] = swv(tf.h[:-1], N).max(axis=1)[: len(tf.c) - N]
            ll[N:] = swv(tf.l[:-1], N).min(axis=1)[: len(tf.c) - N]
        bu = tf.c > hh; se = tf.c < ll
        bu, se = edges(bu), edges(se)
        i = np.nonzero(tf.new)[0]
        j = tf.j[i]
        ok = j >= 0
        out_b[i[ok]] = bu[j[ok]]; out_s[i[ok]] = se[j[ok]]
    elif fam == "F3_ema":
        f, s = p["FS"]
        tf = ctx.h1
        ef, es = ema(tf.c, f), ema(tf.c, s)
        up = ef > es
        cu = up & ~np.r_[True, up[:-1]]; cd = ~up & np.r_[False, up[:-1]]
        i = np.nonzero(tf.new)[0]; j = tf.j[i]; ok = j >= s
        out_b[i[ok]] = cu[j[ok]]; out_s[i[ok]] = cd[j[ok]]
    elif fam == "F4_rsi":
        tf = ctx.m15
        r = rsi(tf.c)
        lo_x = edges(r <= p["TH"]); hi_x = edges(r >= 100 - p["TH"])
        if p["FILT"] == "h1trend":
            e = ema(ctx.h1.c, 50)
            slope = np.r_[0, np.diff(e)]
            # M15 索引 → 已收盤 H1
            h1j = np.searchsorted(ctx.h1.keys, tf.keys + 900 - 3600, side="right") - 1
            sl = np.where(h1j >= 0, slope[np.clip(h1j, 0, None)], 0)
            lo_x &= sl > 0; hi_x &= sl < 0
        i = np.nonzero(tf.new)[0]; j = tf.j[i]; ok = j >= 30
        out_b[i[ok]] = lo_x[j[ok]]; out_s[i[ok]] = hi_x[j[ok]]
    elif fam == "F5_prevday":
        gd = ctx.gday
        keys = np.unique(gd)
        dh = {int(k): h[gd == k].max() for k in keys}; dl = {int(k): l[gd == k].min() for k in keys}
        ph = np.array([dh.get(int(k) - 1, np.nan) for k in gd]); pl = np.array([dl.get(int(k) - 1, np.nan) for k in gd])
        cp = np.r_[np.nan, c[:-1]]
        up = (c > ph) & ~(cp > ph); dn = (c < pl) & ~(cp < pl)
        if p["DIR"] == "fade":
            up, dn = dn, up
        # 每日每方向第一次
        seen = set()
        for i in np.nonzero(up | dn)[0]:
            key = (int(gd[i]), bool(up[i]))
            if key in seen:
                continue
            seen.add(key)
            (out_b if up[i] else out_s)[i] = True
    elif fam == "F6_round":
        st = p["STEP"]
        lvl_dn = np.floor(c / st) * st          # 下面最近關口
        lvl_up = np.ceil(c / st) * st
        hi15 = np.full(n, np.nan); lo15 = np.full(n, np.nan)
        from numpy.lib.stride_tricks import sliding_window_view as swv
        hi15[14:] = swv(h, 15).max(axis=1); lo15[14:] = swv(l, 15).min(axis=1)
        near_dn = (c - lvl_dn <= 0.5) & (hi15 - lvl_dn >= 3)      # 由上面跌埋關口
        near_up = (lvl_up - c <= 0.5) & (lvl_up - lo15 >= 3)      # 由下面升埋關口
        near_dn, near_up = edges(near_dn), edges(near_up)
        if p["DIR"] == "bounce":
            out_b, out_s = near_dn, near_up
        else:
            out_b, out_s = near_up, near_dn
    elif fam == "F7_tod":
        hh = p["H"] * 3600
        m = (sec == hh)
        if p["DIR"] == "long":
            out_b = m
        else:
            out_s = m
    elif fam == "F8_squeeze":
        tf = ctx.m15
        from numpy.lib.stride_tricks import sliding_window_view as swv
        N = 20
        mu = np.full(len(tf.c), np.nan); sd = np.full(len(tf.c), np.nan)
        if len(tf.c) >= N:
            w = swv(tf.c, N)
            mu[N - 1:] = w.mean(axis=1); sd[N - 1:] = w.std(axis=1)
        width = 4 * sd / mu
        pct = np.full(len(tf.c), np.nan)
        if len(tf.c) >= 120:
            ww = swv(width, 100)
            pct[99:] = (ww <= ww[:, -1:]).mean(axis=1)
        sq = np.r_[False, (pct[:-1] <= 0.2)]                         # 上一根仲收縮
        bu = edges(sq & (tf.c > mu + 2 * sd)); se = edges(sq & (tf.c < mu - 2 * sd))
        if p["DIR"] == "fade":
            bu, se = se, bu
        i = np.nonzero(tf.new)[0]; j = tf.j[i]; ok = j >= 120
        out_b[i[ok]] = bu[j[ok]]; out_s[i[ok]] = se[j[ok]]
    else:
        raise ValueError(fam)
    sig = [(int(i), 1) for i in np.nonzero(out_b)[0]] + [(int(i), -1) for i in np.nonzero(out_s)[0]]
    sig.sort()
    return sig


# ------------------------------------------------------------------ 成交
def trade_mats(ctx, sig):
    """每個訊號：入場價＝下一根開盤；未來 MAX_H 根相對入場價嘅 H／L／C（已按方向翻成 BUY）。"""
    d = ctx.d
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t)
    m = len(sig)
    H = np.full((m, MAX_H), np.nan, np.float32); L = H.copy(); C = H.copy()
    E = np.full((m, MAX_H), 10**9, np.int64)
    ent_i = np.zeros(m, np.int64); ent_px = np.zeros(m)
    for r, (i, s) in enumerate(sig):
        a = i + 1
        if a >= n:
            continue
        b = min(n, a + MAX_H)
        px = o[a]
        ent_i[r] = a; ent_px[r] = px
        if s > 0:
            H[r, :b - a] = h[a:b] - px; L[r, :b - a] = l[a:b] - px; C[r, :b - a] = c[a:b] - px
        else:
            H[r, :b - a] = px - l[a:b]; L[r, :b - a] = px - h[a:b]; C[r, :b - a] = px - c[a:b]
        E[r, :b - a] = t[a:b] - t[a]
    return H, L, C, E, ent_i


def simulate(ctx, sig, mats, K, R, T):
    """回傳每個訊號 (R, 入場索引, 出場索引)；冇數／未完 R＝nan。"""
    H, L, C, E, ent_i = mats
    m = len(sig)
    if m == 0:
        return np.array([]), ent_i, ent_i
    atr = ctx.atr15()
    sl = K * np.array([atr[i] for i, _ in sig])
    tp = R * sl
    tmask = E < T * 3600                                   # 時間止蝕之前嘅 K 線
    slh = (L <= -sl[:, None]) & tmask
    tph = (H >= tp[:, None]) & tmask
    big = 10**9
    si = np.where(slh.any(1), slh.argmax(1), big); ti = np.where(tph.any(1), tph.argmax(1), big)
    # 時間止蝕：最後一根 E < T*3600 嘅 K 線收盤（之後要有一根 ≥ T 證明時間到咗）
    after = (E >= T * 3600) & ~np.isnan(C)
    has_after = after.any(1)
    te = np.where(has_after, after.argmax(1) - 1, big)
    rows = np.arange(m)
    first = np.minimum(np.minimum(si, ti), te)
    valid = ~np.isnan(sl) & (sl > 0) & (first < big)
    exit_px = np.where(si <= np.minimum(ti, te), -sl, np.where(ti <= te, tp, C[rows, np.clip(te, 0, MAX_H - 1)]))
    r = np.where(valid, (exit_px - COST) / np.where(sl > 0, sl, 1), np.nan)
    ex_i = ent_i + np.where(valid, first, 0)
    return r, ent_i, ex_i


def one_at_a_time(r, ent_i, ex_i):
    keep = np.zeros(len(r), bool)
    last = -1
    for k in np.argsort(ent_i, kind="stable"):
        if np.isnan(r[k]) or ent_i[k] <= last:
            continue
        keep[k] = True
        last = ex_i[k]
    return keep


def stats(r):
    r = r[~np.isnan(r)]
    if not len(r):
        return {"n": 0, "avg": None, "pf": None, "streak": 0, "sum": 0.0}
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    s = mx = 0
    for x in r:
        s = s + 1 if x < 0 else 0
        mx = max(mx, s)
    return {"n": int(len(r)), "avg": float(r.mean()), "pf": float(w / ls) if ls > 0 else float("inf"), "streak": mx, "sum": float(r.sum())}


def fmt(s):
    return "n=0" if not s["n"] else f"n={s['n']} 平均 {s['avg']:+.3f}R ΣR {s['sum']:+.1f} PF {s['pf']:.2f} 連敗 {s['streak']}"


def months(r, ts):
    out = {}
    for x, t in zip(r, ts):
        if np.isnan(x):
            continue
        out.setdefault(dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m"), []).append(x)
    return {k: stats(np.array(v)) for k, v in sorted(out.items())}


def run_strategy(ctx, fam, p, e, lo, hi, sig_cache=None):
    key = (fam, json.dumps(p, sort_keys=True))
    if sig_cache is not None and key in sig_cache:
        sig, mats = sig_cache[key]
    else:
        sig = signals(ctx, fam, p)
        t = ctx.d["t"]
        sig = [(i, s) for i, s in sig if lo <= t[i] + 60 < hi]
        mats = trade_mats(ctx, sig)
        if sig_cache is not None:
            sig_cache[key] = (sig, mats)
    r, ei, xi = simulate(ctx, sig, mats, e["K"], e["R"], e["T"])
    keep = one_at_a_time(r, ei, xi)
    ts = np.array([int(ctx.d["t"][i]) for i in ei]) if len(ei) else np.array([])
    return r[keep], ts[keep] if len(ts) else ts


def grid(fam):
    ks = list(FAMILIES[fam])
    for v in itertools.product(*[FAMILIES[fam][k] for k in ks]):
        yield dict(zip(ks, v))


def exits():
    for k, r, t in itertools.product(EXITS["K"], EXITS["R"], EXITS["T"]):
        yield {"K": k, "R": r, "T": t}


def gkey(fam, p, e):
    return tuple(FAMILIES[fam][k].index(p[k]) for k in FAMILIES[fam]) + tuple(EXITS[k].index(e[k]) for k in EXITS)


def cmd_search():
    duka = load("duka", "2022-12-25", "2026-07-23")
    ctx = Ctx(duka)
    s0, s1 = ts_of(SEARCH[0]), ts_of(SEARCH[1])
    v0, v1 = ts_of(VALID[0]), ts_of(VALID[1])
    out = ["# IDEAS #161 策略搜尋：搜尋段＋驗證段", "",
           f"- 數據：Dukascopy M1 {len(duka['t'])} 根（{dt.datetime.fromtimestamp(int(duka['t'][0]), dt.timezone.utc):%Y-%m-%d}→{dt.datetime.fromtimestamp(int(duka['t'][-1]), dt.timezone.utc):%Y-%m-%d}）",
           f"- 搜尋段 {SEARCH[0]}→{SEARCH[1]}；驗證段 {VALID[0]}→{VALID[1]}；成本 {COST} 美元／張；入場＝下一根開盤", ""]
    total = 0
    cands = []
    for fam in FAMILIES:
        res = {}
        cache = {}
        for p in grid(fam):
            for e in exits():
                r, ts = run_strategy(ctx, fam, p, e, s0, v1, cache)
                m = ts < s1
                res[gkey(fam, p, e)] = (p, e, stats(r[m]))
                total += 1
        dims = [len(FAMILIES[fam][k]) for k in FAMILIES[fam]] + [len(EXITS[k]) for k in EXITS]
        plat = {}
        for k, (p, e, s) in res.items():
            if s["n"] < MIN_SEARCH_N:
                continue
            vals = [s["avg"]]
            for dp in range(len(dims)):
                for st in (-1, 1):
                    nk = list(k); nk[dp] += st; nk = tuple(nk)
                    if nk in res and res[nk][2]["n"] >= MIN_SEARCH_N:
                        vals.append(res[nk][2]["avg"])
            plat[k] = statistics.median(vals)
        top = sorted(plat, key=lambda k: -plat[k])[:3]
        out.append(f"## {fam}（{len(res)} 組；搜尋段 ≥ {MIN_SEARCH_N} 張 {len(plat)} 組）")
        for k in top:
            p, e, s = res[k]
            r, ts = run_strategy(ctx, fam, p, e, s0, v1, cache)
            vm = (ts >= v0) & (ts < v1)
            vs = stats(r[vm])
            mo = months(r[vm], ts[vm])
            pos = sum(1 for v in mo.values() if v["n"] and v["avg"] > 0)
            ok = vs["n"] > 0 and vs["avg"] >= 0.10 and vs["pf"] >= 1.15 and pos >= 4
            out.append(f"- 平台 {plat[k]:+.3f}R｜{json.dumps({**p, **e}, ensure_ascii=False)}")
            out.append(f"  - 搜尋段：{fmt(s)}")
            out.append(f"  - 驗證段：{fmt(vs)}；正數月 {pos}／{len(mo)} → {'入圍' if ok else '唔入圍'}")
            if ok:
                cands.append({"fam": fam, "p": p, "e": e, "plateau": plat[k], "search": s, "valid": vs, "pos_months": pos})
        out.append("")
        print("\n".join(out[-8:]), flush=True)
    cands.sort(key=lambda c: -c["valid"]["avg"])
    sel = cands[:3]
    out.append(f"## 揀中（驗證段入圍 {len(cands)} 個，按驗證段平均 R 取頭 3）；全部試咗 {total} 組")
    for c in sel:
        out.append(f"- {c['fam']} {json.dumps({**c['p'], **c['e']}, ensure_ascii=False)}：搜尋 {fmt(c['search'])}｜驗證 {fmt(c['valid'])}")
    if not sel:
        out.append("- 冇策略入圍 → 唔做最終測試，#161 唔達標")
    md = "\n".join(out) + "\n"
    open(os.path.join(HERE, "SEARCH_out.md"), "w", encoding="utf-8").write(md)
    json.dump({"total_tested": total, "selected": sel}, open(os.path.join(HERE, "selected.json"), "w"), ensure_ascii=False, indent=1, default=str)
    print(md[-3000:])


def cmd_final():
    sel = json.load(open(os.path.join(HERE, "selected.json")))
    out = ["# IDEAS #161 最終測試（一次過；Dukascopy＋PAXG 2026-07-24→10-30）", "", f"- 搜尋＋驗證總共試咗 {sel['total_tested']} 組；揀中 {len(sel['selected'])} 個", ""]
    if not sel["selected"]:
        out.append("- 冇揀中策略")
    else:
        duka = load("duka", "2026-07-17", "2026-10-31")
        paxg = load("paxg", "2026-07-20", "2026-10-31")
        f0, f1 = ts_of(FINAL[0]), ts_of(FINAL[1])
        for c in sel["selected"]:
            res = {}
            for name, d in (("Dukascopy", duka), ("PAXG", paxg)):
                ctx = Ctx(d)
                r, ts = run_strategy(ctx, c["fam"], c["p"], c["e"], f0, f1)
                res[name] = (stats(r), months(r, ts))
            fd, fp = res["Dukascopy"][0], res["PAXG"][0]
            ok = {"①≥50張 +0.2R PF1.3": fd["n"] >= 50 and fd["avg"] >= 0.2 and fd["pf"] >= 1.3,
                  "②連敗≤6": fd["streak"] <= 6,
                  "③PAXG≥+0.1R": fp["n"] > 0 and fp["avg"] >= 0.1,
                  "④三段都正": fd["n"] > 0 and fd["avg"] > 0 and c["search"]["avg"] > 0 and c["valid"]["avg"] > 0}
            out.append(f"## {c['fam']} {json.dumps({**c['p'], **c['e']}, ensure_ascii=False)}")
            out.append(f"- 搜尋 {fmt(c['search'])}｜驗證 {fmt(c['valid'])}")
            out.append(f"- 最終 Dukascopy：{fmt(fd)}；每月 " + "、".join(f"{k} {v['avg']:+.2f}R（{v['n']}）" for k, v in res['Dukascopy'][1].items() if v['n']))
            out.append(f"- 最終 PAXG：{fmt(fp)}")
            out.append("- 判斷：" + "；".join(f"{k} {'✓' if v else '✗'}" for k, v in ok.items()) + f" → **{'合格' if all(ok.values()) else '唔合格'}**")
            out.append("")
    md = "\n".join(out) + "\n"
    open(os.path.join(HERE, "FINAL_out.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    {"search": cmd_search, "final": cmd_final}[sys.argv[1] if len(sys.argv) > 1 else "search"]()
