"""[IDEAS #162] XAUUSD 較高時框（H1／H4／D1）策略＋滾動前向（walk-forward）。家族、格、方法同合格標準以 IDEAS #162 預先登記為準。
底層 M5（由券商 MT5 M1 合成）；訊號喺 M5 收盤判斷，下一根 M5 開盤入；SL＝K×家族時框 ATR(14)；TP＝R 倍；時間止蝕 T 小時；
同一根 SL／TP 都掂當 SL；跳空過 SL 用開盤；每張扣 COST；同一策略同時最多 1 張。
滾動前向：訓練 12 個月 → 揀一組（平台分）→ 交易下一個 3 個月；測試窗串連＝樣本外。
用法：python3 research/strategy_search/search2.py"""
import datetime as dt
import itertools
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import search as S   # noqa: E402

COST = 0.5
BASE = 300
MAX_H = 120 * 12                      # 120 小時（M5 根數）
MIN_TRAIN_N = 30
WF_FIRST = "2023-09-01"
WF_END = "2026-10-31"
DUKA_FROM = "2026-07-24"

EXITS = {"K": (1.0, 1.5, 2.0, 3.0), "R": (1.0, 2.0, 3.0), "T": (24, 72, 120)}
FAMILIES = {
    "G1_h4_donchian": {"N": (10, 20, 55), "DIR": ("follow", "fade")},
    "G2_d1_sma": {"N": (20, 50, 100)},
    "G3_tsmom": {"L": (5, 20, 60)},
    "G4_rsi2": {"TH": (5, 10), "FILT": ("none", "sma200")},
    "G5_dow": {"W": (0, 1, 2, 3, 4), "DIR": ("long", "short")},
    "G6_prevweek": {"DIR": ("follow", "fade")},
    "G7_h1_pullback": {"TH": (30, 35)},
    "G8_volbreak": {"KR": (0.3, 0.5, 0.7)},
}
ATR_TF = {"G1_h4_donchian": "h4", "G7_h1_pullback": "h1"}   # 其餘用 D1


def to_m5(d):
    key = d["t"] // BASE * BASE
    keys, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(key)] - 1
    return {"t": keys, "o": d["o"][first], "h": np.maximum.reduceat(d["h"], first),
            "l": np.minimum.reduceat(d["l"], first), "c": d["c"][last]}


class TF:
    def __init__(self, d, sec, shift=0):
        t = d["t"]
        key = (t - shift) // sec * sec + shift
        self.keys, first = np.unique(key, return_index=True)
        last = np.r_[first[1:], len(t)] - 1
        self.o = d["o"][first]; self.c = d["c"][last]
        self.h = np.maximum.reduceat(d["h"], first); self.l = np.minimum.reduceat(d["l"], first)
        self.first = first
        self.j = np.searchsorted(self.keys, t + BASE - sec, side="right") - 1     # 已收盤嘅最後一根
        self.new = np.r_[True, self.j[1:] != self.j[:-1]]
        tr = np.r_[self.h[0] - self.l[0], np.maximum.reduce([self.h[1:] - self.l[1:], np.abs(self.h[1:] - self.c[:-1]), np.abs(self.l[1:] - self.c[:-1])])]
        cs = np.r_[0, np.cumsum(tr)]
        self.atr = np.full(len(tr), np.nan)
        self.atr[13:] = (cs[14:] - cs[:-14]) / 14
        self.cur = np.searchsorted(self.keys, t, side="right") - 1                 # 而家所屬（未收）嘅一根


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.r_[0, np.cumsum(x)]
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


class Ctx:
    def __init__(self, d):
        self.d = d
        self.h1 = TF(d, 3600)
        self.h4 = TF(d, 4 * 3600, 22 * 3600 % (4 * 3600))
        self.d1 = TF(d, 86400, 22 * 3600)
        self.w1 = TF(d, 7 * 86400, 3 * 86400 + 22 * 3600)

    def atr_at(self, fam, idx):
        tf = {"h4": self.h4, "h1": self.h1}.get(ATR_TF.get(fam), self.d1)
        j = tf.j[idx]
        return np.where(j >= 0, tf.atr[np.clip(j, 0, None)], np.nan)


def at_close(tf, arr_b, arr_s, n, minj=0):
    ob = np.zeros(n, bool); os_ = np.zeros(n, bool)
    i = np.nonzero(tf.new)[0]; j = tf.j[i]; ok = j >= minj
    ob[i[ok]] = arr_b[j[ok]]; os_[i[ok]] = arr_s[j[ok]]
    return ob, os_


def signals(ctx, fam, p):
    d = ctx.d
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t)
    ob = np.zeros(n, bool); os_ = np.zeros(n, bool)
    if fam == "G1_h4_donchian":
        tf = ctx.h4; N = p["N"]
        from numpy.lib.stride_tricks import sliding_window_view as swv
        hh = np.full(len(tf.c), np.nan); ll = hh.copy()
        if len(tf.c) > N:
            hh[N:] = swv(tf.h[:-1], N).max(axis=1)[: len(tf.c) - N]
            ll[N:] = swv(tf.l[:-1], N).min(axis=1)[: len(tf.c) - N]
        bu, se = S.edges(tf.c > hh), S.edges(tf.c < ll)
        if p["DIR"] == "fade":
            bu, se = se, bu
        ob, os_ = at_close(tf, bu, se, n, N)
    elif fam == "G2_d1_sma":
        tf = ctx.d1; m = sma(tf.c, p["N"])
        up = tf.c > m
        bu = up & ~np.r_[True, up[:-1]] & ~np.isnan(m); se = ~up & np.r_[False, up[:-1]] & ~np.isnan(m)
        ob, os_ = at_close(tf, bu, se, n, p["N"])
    elif fam == "G3_tsmom":
        tf = ctx.d1; L = p["L"]
        past = np.r_[np.full(L, np.nan), tf.c[:-L]]
        ob, os_ = at_close(tf, tf.c > past, tf.c < past, n, L)
    elif fam == "G4_rsi2":
        tf = ctx.d1; r = S.rsi(tf.c, 2)
        bu, se = r <= p["TH"], r >= 100 - p["TH"]
        if p["FILT"] == "sma200":
            m = sma(tf.c, 200); bu &= tf.c > m; se &= tf.c < m
        ob, os_ = at_close(tf, bu, se, n, 5)
    elif fam == "G5_dow":
        tf = ctx.d1
        # 交易日（22:00 UTC 開）對應嘅日曆日＝開始 +2 小時嗰日；喺嗰日第一根 M5 入
        first_bar = np.zeros(n, bool); first_bar[tf.first] = True
        wd = np.array([dt.datetime.fromtimestamp(int(k) + 7200, dt.timezone.utc).weekday() for k in tf.keys])
        hit = first_bar & (wd[np.clip(tf.cur, 0, None)] == p["W"])
        # 「下一根開盤入」：訊號放喺前一根
        sig = np.r_[hit[1:], False]
        if p["DIR"] == "long":
            ob = sig
        else:
            os_ = sig
    elif fam == "G6_prevweek":
        tf = ctx.w1
        cur = tf.cur
        ph = np.where(cur >= 1, tf.h[np.clip(cur - 1, 0, None)], np.nan); pl = np.where(cur >= 1, tf.l[np.clip(cur - 1, 0, None)], np.nan)
        cp = np.r_[np.nan, c[:-1]]
        up = (c > ph) & ~(cp > ph); dn = (c < pl) & ~(cp < pl)
        seen = set()
        for i in np.nonzero(up | dn)[0]:
            k = (int(cur[i]), bool(up[i]))
            if k in seen:
                continue
            seen.add(k)
            isup = bool(up[i]) if p["DIR"] == "follow" else not bool(up[i])
            (ob if isup else os_)[i] = True
    elif fam == "G7_h1_pullback":
        h1, h4 = ctx.h1, ctx.h4
        e = S.ema(h4.c, 50); slope = np.r_[0, np.diff(e)]
        r = S.rsi(h1.c, 14)
        h4j = np.searchsorted(h4.keys, h1.keys + 3600 - 4 * 3600, side="right") - 1    # H1 收盤時已收嘅 H4
        sl = np.where(h4j >= 50, slope[np.clip(h4j, 0, None)], 0)
        bu = S.edges(r <= p["TH"]) & (sl > 0); se = S.edges(r >= 100 - p["TH"]) & (sl < 0)
        ob, os_ = at_close(h1, bu, se, n, 20)
    elif fam == "G8_volbreak":
        tf = ctx.d1; cur = tf.cur
        dopen = tf.o[np.clip(cur, 0, None)]
        prng = np.where(cur >= 1, (tf.h - tf.l)[np.clip(cur - 1, 0, None)], np.nan)
        up = c >= dopen + p["KR"] * prng; dn = c <= dopen - p["KR"] * prng
        seen = set()
        for i in np.nonzero(up | dn)[0]:
            k = int(cur[i])
            if k in seen:
                continue
            seen.add(k)
            (ob if up[i] else os_)[i] = True
    else:
        raise ValueError(fam)
    return sorted([(int(i), 1) for i in np.nonzero(ob)[0]] + [(int(i), -1) for i in np.nonzero(os_)[0]])


def trade_mats(d, sig):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    n = len(t); m = len(sig)
    H = np.full((m, MAX_H), np.nan, np.float32); L = H.copy(); C = H.copy(); O = H.copy()
    E = np.full((m, MAX_H), 10**9, np.int64); ent = np.zeros(m, np.int64)
    for r, (i, s) in enumerate(sig):
        a = i + 1
        if a >= n:
            continue
        b = min(n, a + MAX_H); px = o[a]; ent[r] = a
        if s > 0:
            H[r, :b - a] = h[a:b] - px; L[r, :b - a] = l[a:b] - px; C[r, :b - a] = c[a:b] - px; O[r, :b - a] = o[a:b] - px
        else:
            H[r, :b - a] = px - l[a:b]; L[r, :b - a] = px - h[a:b]; C[r, :b - a] = px - c[a:b]; O[r, :b - a] = px - o[a:b]
        E[r, :b - a] = t[a:b] - t[a]
    return H, L, C, E, ent, O


def simulate(sl, mats, R, T):
    H, L, C, E, ent, O = mats
    m = len(sl)
    if m == 0:
        return np.array([]), ent, ent
    tp = R * sl
    tmask = E < T * 3600
    slh = (L <= -sl[:, None]) & tmask; tph = (H >= tp[:, None]) & tmask
    big = 10**9
    si = np.where(slh.any(1), slh.argmax(1), big); ti = np.where(tph.any(1), tph.argmax(1), big)
    after = (E >= T * 3600) & ~np.isnan(C)
    te = np.where(after.any(1), after.argmax(1) - 1, big)
    rows = np.arange(m)
    first = np.minimum(np.minimum(si, ti), te)
    valid = ~np.isnan(sl) & (sl > 0) & (first < big)
    sl_px = np.minimum(-sl, O[rows, np.clip(si, 0, MAX_H - 1)])
    ex = np.where(si <= np.minimum(ti, te), sl_px, np.where(ti <= te, tp, C[rows, np.clip(te, 0, MAX_H - 1)]))
    r = np.where(valid, (ex - COST) / np.where(sl > 0, sl, 1), np.nan)
    return r, ent, ent + np.where(valid, first, 0)


def grid(fam):
    ks = list(FAMILIES[fam])
    for v in itertools.product(*[FAMILIES[fam][k] for k in ks]):
        yield dict(zip(ks, v))


def exits():
    for k, r, t in itertools.product(EXITS["K"], EXITS["R"], EXITS["T"]):
        yield {"K": k, "R": r, "T": t}


def gkey(fam, p, e):
    return tuple(FAMILIES[fam][k].index(p[k]) for k in FAMILIES[fam]) + tuple(EXITS[k].index(e[k]) for k in EXITS)


def all_trades(ctx, fam):
    """每組參數全期成交（一次一張）→ {key: (p, e, ts 陣列, r 陣列)}。"""
    d = ctx.d
    out = {}
    for p in grid(fam):
        sig = signals(ctx, fam, p)
        mats = trade_mats(d, sig)
        atr = ctx.atr_at(fam, np.array([i for i, _ in sig], dtype=np.int64)) if sig else np.array([])
        for e in exits():
            r, ei, xi = simulate(e["K"] * atr, mats, e["R"], e["T"])
            keep = S.one_at_a_time(r, ei, xi)
            ts = d["t"][ei[keep]] if len(ei) else np.array([], np.int64)
            out[gkey(fam, p, e)] = (p, e, ts, r[keep])
    return out


def add_months(d, k):
    y, m = d.year, d.month - 1 + k
    return dt.date(y + m // 12, m % 12 + 1, 1)


def windows():
    s = dt.date.fromisoformat(WF_FIRST); end = dt.date.fromisoformat(WF_END)
    out = []
    while s < end:
        out.append((add_months(s, -12), s, min(add_months(s, 3), end)))
        s = add_months(s, 3)
    return out


def walk_forward(fam, trades):
    dims = [len(FAMILIES[fam][k]) for k in FAMILIES[fam]] + [len(EXITS[k]) for k in EXITS]
    oos_r, oos_ts, picks = [], [], []
    for tr0, te0, te1 in windows():
        a, b, c_ = (S.ts_of(x.isoformat()) for x in (tr0, te0, te1))
        avg = {}
        for k, (p, e, ts, r) in trades.items():
            m = (ts >= a) & (ts < b)
            rr = r[m]
            if len(rr) >= MIN_TRAIN_N:
                avg[k] = float(rr.mean())
        plat = {}
        for k in avg:
            vals = [avg[k]]
            for dp in range(len(dims)):
                for st in (-1, 1):
                    nk = list(k); nk[dp] += st; nk = tuple(nk)
                    if nk in avg:
                        vals.append(avg[nk])
            plat[k] = statistics.median(vals)
        if not plat:
            picks.append((te0.isoformat(), None, None, S.stats(np.array([]))))
            continue
        best = max(plat, key=lambda k: plat[k])
        p, e, ts, r = trades[best]
        m = (ts >= b) & (ts < c_)
        oos_r.append(r[m]); oos_ts.append(ts[m])
        picks.append((te0.isoformat(), {**p, **e}, plat[best], S.stats(r[m])))
    rr = np.concatenate(oos_r) if oos_r else np.array([])
    tt = np.concatenate(oos_ts) if oos_ts else np.array([])
    return rr, tt, picks


def main():
    m1 = S.load("mt5", "2022-08-03", "2026-10-30")
    d = to_m5(m1)
    ctx = Ctx(d)
    # Dukascopy 旁證：07-24 之前用 MT5（指標預熱），之後用 Dukascopy
    duka1 = S.load("duka", "2026-07-24", "2026-10-31")
    cut = S.ts_of(DUKA_FROM)
    dk5 = to_m5(duka1)
    mix = {k: np.r_[d[k][d["t"] < cut], dk5[k][dk5["t"] >= cut]] for k in d}
    ctx_dk = Ctx(mix)
    out = ["# IDEAS #162 較高時框＋滾動前向（樣本外串連 2023-09→2026-10）", "",
           f"- 數據：券商 MT5 M1 → M5 {len(d['t'])} 根；訓練 12 個月、測試 3 個月、推 3 個月；共 {len(windows())} 個測試窗；成本 {COST} 美元／張", ""]
    total = 0
    passed = []
    for fam in FAMILIES:
        tr = all_trades(ctx, fam)
        total += len(tr)
        rr, tt, picks = walk_forward(fam, tr)
        s = S.stats(rr)
        qpos = sum(1 for _, _, _, st in picks if st["n"] and st["avg"] > 0)
        qn = sum(1 for _, _, _, st in picks if st["n"])
        # ⑤ Dukascopy：涵蓋 07-24→10-30 嘅測試窗用返佢揀嘅參數
        dk_r = []
        for (w0, pe, _, _), (tr0, te0, te1) in zip(picks, windows()):
            if pe is None or S.ts_of(te1.isoformat()) <= cut:
                continue
            p = {k: pe[k] for k in FAMILIES[fam]}; e = {k: pe[k] for k in EXITS}
            sig = signals(ctx_dk, fam, p)
            mats = trade_mats(mix, sig)
            atr = ctx_dk.atr_at(fam, np.array([i for i, _ in sig], dtype=np.int64)) if sig else np.array([])
            r, ei, xi = simulate(e["K"] * atr, mats, e["R"], e["T"])
            keep = S.one_at_a_time(r, ei, xi)
            ts = mix["t"][ei[keep]] if len(ei) else np.array([])
            mm = (ts >= max(cut, S.ts_of(te0.isoformat()))) & (ts < S.ts_of(te1.isoformat()))
            dk_r.append(r[keep][mm])
        dks = S.stats(np.concatenate(dk_r)) if dk_r else S.stats(np.array([]))
        ok = {"①≥100張": s["n"] >= 100,
              "②+0.15R PF1.3": s["n"] > 0 and s["avg"] >= 0.15 and s["pf"] >= 1.3,
              "③≥60%季正": qn > 0 and qpos / qn >= 0.6,
              "④連敗≤8": s["streak"] <= 8,
              "⑤Dukascopy>0": dks["n"] > 0 and dks["avg"] > 0}
        verdict = all(ok.values())
        if verdict:
            passed.append(fam)
        out.append(f"## {fam}（{len(tr)} 組）")
        out.append(f"- 樣本外串連：{S.fmt(s)}；正數季 {qpos}／{qn}；Dukascopy 07-24→10-30：{S.fmt(dks)}")
        out.append("- 判斷：" + "；".join(f"{k} {'✓' if v else '✗'}" for k, v in ok.items()) + f" → **{'合格' if verdict else '唔合格'}**")
        for w0, pe, pl, st in picks:
            out.append(f"  - 測試窗 {w0}：{json.dumps(pe, ensure_ascii=False) if pe else '冇（訓練窗唔夠張數）'}" + (f"（訓練平台 {pl:+.3f}R）→ {S.fmt(st)}" if pe else ""))
        out.append("")
        print("\n".join(out[-(len(picks) + 4):]), flush=True)
    out.append(f"## 總結：8 個家族共 {total} 組；合格 {len(passed)} 個：{passed or '冇'}")
    md = "\n".join(out) + "\n"
    open(os.path.join(HERE, "WF_out.md"), "w", encoding="utf-8").write(md)
    print(md[-1500:])


if __name__ == "__main__":
    main()
