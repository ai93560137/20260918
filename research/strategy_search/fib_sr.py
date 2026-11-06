"""[IDEAS #230] 斐波那契回撤做支持／壓力（月線主判；magic 926 測試）。規格見 IDEAS #230（預先登記，跑之前 commit）。
數據：Dukascopy H1（GCS xau/sig/duka_h1/），MT5 伺服器時間（紐約 +7）砌月／週／日／H4；只用已收市 K 線計回撤位同日線 ATR。
用法：python3 research/strategy_search/fib_sr.py → FIB_SR.md"""
import datetime as dt
import os
import random
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G7  # noqa: E402

NY = ZoneInfo("America/New_York")
COST = 0.5
TRADE_R = (0.236, 0.382, 0.5, 0.618, 0.786)
ALL_R = (0.0,) + TRADE_R + (1.0,)
LOOK = {"M": 120, "W": 104, "D": 180, "H4": 180}
HOLD_H = {"M": 20 * 24, "W": 10 * 24, "D": 5 * 24, "H4": 3 * 24}
SEGS = [("2010-01→2022-12", dt.datetime(2010, 1, 1), dt.datetime(2023, 1, 1)),
        ("2023-01→2024-12", dt.datetime(2023, 1, 1), dt.datetime(2025, 1, 1)),
        ("2025-01→2026-10", dt.datetime(2025, 1, 1), dt.datetime(2026, 11, 1))]
N_RAND = 20


def server_dt(ts):
    return (dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).astimezone(NY) + dt.timedelta(hours=7)).replace(tzinfo=None)


def tf_key(t, tf):
    if tf == "H4":
        return (t.year, t.month, t.day, t.hour // 4)
    d = dt.date(t.year, t.month, t.day)
    if tf == "D":
        return d.toordinal()
    if tf == "W":
        return d.toordinal() - d.weekday()
    return (t.year, t.month)


def fib_levels(bars, look):
    """bars：已收市 (h, l) list。回傳 {ratio: price} 或 None。"""
    if len(bars) < 20:
        return None
    seg = bars[-look:]
    hi_i = max(range(len(seg)), key=lambda i: seg[i][0])
    lo_i = min(range(len(seg)), key=lambda i: seg[i][1])
    hi, lo = seg[hi_i][0], seg[lo_i][1]
    if hi <= lo:
        return None
    up = hi_i > lo_i
    return {r: (hi - (hi - lo) * r) if up else (lo + (hi - lo) * r) for r in ALL_R}


def build(t, o, h, l, c):
    """逐根 H1：回傳每根嘅 (各時間框回撤位, 日線 ATR)，全部只用該根之前已收市嘅時間框 K 線。"""
    n = len(t)
    st = [server_dt(x) for x in t]
    closed = {tf: [] for tf in LOOK}
    cur = {tf: None for tf in LOOK}
    lv = {tf: None for tf in LOOK}
    dcl = []                      # 已收市日線 (h, l, c)
    levels, atr = [None] * n, np.full(n, np.nan)
    for i in range(n):
        for tf in LOOK:
            k = tf_key(st[i], tf)
            cb = cur[tf]
            if cb is None or cb[0] != k:
                if cb is not None:
                    closed[tf].append((cb[1], cb[2]))
                    lv[tf] = fib_levels(closed[tf], LOOK[tf])
                    if tf == "D":
                        dcl.append((cb[1], cb[2], cb[3]))
                cur[tf] = [k, h[i], l[i], c[i]]
            else:
                cb[1] = max(cb[1], h[i]); cb[2] = min(cb[2], l[i]); cb[3] = c[i]
        if len(dcl) >= 15:
            trs = [max(dcl[j][0], dcl[j - 1][2]) - min(dcl[j][1], dcl[j - 1][2]) for j in range(len(dcl) - 14, len(dcl))]
            atr[i] = sum(trs) / 14
        levels[i] = dict(lv)
    return st, levels, atr


def simulate(t, o, h, l, c, st, levels, atr, variant, offsets=None):
    """variant：'M'／'W'／'D'／'H4'／'conf'；offsets：{月線位版本 id: 移位}（隨機基準）。回傳 [(入場 server_dt, R)]。"""
    tf = "M" if variant == "conf" else variant
    n = len(t)
    out, pos, pend = [], None, None
    last_exit = {}
    for i in range(1, n):
        A = atr[i]
        if pend is not None:                                      # 上一根訊號 → 今根開市入
            s, L, tgt_set, sl_off = pend; pend = None
            e = o[i]; sl = L - s * sl_off; risk = (e - sl) * s
            if risk > 0:
                nxt = [p for p in tgt_set if (p - e) * s > 0]
                tp = (min(nxt) if s > 0 else max(nxt)) if nxt else None
                if tp is None or (tp - e) * s < 2 * risk:
                    tp = e + s * 2 * risk
                pos = (s, e, sl, tp, i, L)
        if pos is not None:
            s, e, sl, tp, ei, L = pos
            ex = None
            if i - ei >= HOLD_H[tf]:
                ex = o[i]
            elif (l[i] <= sl) if s > 0 else (h[i] >= sl):
                ex = sl
            elif (h[i] >= tp) if s > 0 else (l[i] <= tp):
                ex = tp
            if ex is not None:
                out.append((st[ei], (s * (ex - e) - COST) / ((e - sl) * s)))
                last_exit[round(L, 1)] = t[i]
                pos = None
            if pos is not None:
                continue
        if np.isnan(A) or i + 1 >= n:
            continue
        base = levels[i].get(tf)
        if not base:
            continue
        if offsets is not None:
            off = offsets(id(base), A)
            base = {r: p + off for r, p in base.items()}
        cands = [base[r] for r in TRADE_R]
        if variant == "conf":
            others = [lvp[r] for k2 in ("W", "D", "H4") for lvp in [levels[i].get(k2)] if lvp for r in TRADE_R]
            cands = [p for p in cands if any(abs(p - q) <= 0.3 * A for q in others)]
        best = None
        for L in cands:
            if t[i] - last_exit.get(round(L, 1), -1e18) < 86400:
                continue
            if c[i - 1] > L and l[i] <= L + 0.1 * A and c[i] > L:
                s = 1
            elif c[i - 1] < L and h[i] >= L - 0.1 * A and c[i] < L:
                s = -1
            else:
                continue
            if best is None or abs(c[i] - L) < abs(c[i] - best[1]):
                best = (s, L)
        if best:
            pend = (best[0], best[1], list(base.values()), 0.35 * A)
    return out


def summ(rs):
    if not rs:
        return {"n": 0, "avg": 0.0, "pf": 0.0, "sum": 0.0}
    a = np.array(rs); g = a[a > 0].sum(); b = -a[a < 0].sum()
    return {"n": len(a), "avg": float(a.mean()), "pf": float(g / b) if b > 0 else float("inf"), "sum": float(a.sum())}


def fmt(s):
    return "0 張" if not s["n"] else f"{s['n']} 張 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.1f}"


def segs(tr):
    return [summ([r for d, r in tr if a <= d < b]) for _, a, b in SEGS]


def main():
    t, o, h, l, c = G7.load_h1_duka()
    print("H1", len(t), dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc), dt.datetime.fromtimestamp(int(t[-1]), dt.timezone.utc), flush=True)
    st, levels, atr = build(t, o, h, l, c)
    end = dt.datetime(2026, 11, 1)
    res = {}
    for v in ("M", "W", "D", "H4", "conf"):
        tr = [(d, r) for d, r in simulate(t, o, h, l, c, st, levels, atr, v) if SEGS[0][1] <= d < end]
        res[v] = tr
        print(v, fmt(summ([r for _, r in tr])), flush=True)
    rand_all, rand_segs = [], []
    for seed in range(N_RAND):
        rng = random.Random(seed); memo = {}

        def offsets(key, A, rng=rng, memo=memo):
            if key not in memo:
                memo[key] = rng.uniform(1, 3) * rng.choice((-1, 1))
            return memo[key] * A
        tr = [(d, r) for d, r in simulate(t, o, h, l, c, st, levels, atr, "M", offsets) if SEGS[0][1] <= d < end]
        rand_all.append(summ([r for _, r in tr])); rand_segs.append(segs(tr))
    ravg = float(np.mean([s["avg"] for s in rand_all])); rn = float(np.mean([s["n"] for s in rand_all]))
    print("rand", ravg, rn, flush=True)

    names = {"M": "Vm 月線（主判）", "W": "Vw 週線", "D": "Vd 日線", "H4": "Vh4 H4", "conf": "Vconf 月線＋其他時間框共振"}
    out = ["# 斐波那契回撤做支持／壓力（IDEAS #230，magic 926 測試）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy H1 {len(t)} 根；MT5 伺服器時間；規格見 IDEAS #230（預先登記）", "",
           "| 組 | 全期 | " + " | ".join(s[0] for s in SEGS) + " |", "|---|---|---|---|---|"]
    for v in res:
        sg = segs(res[v])
        out.append(f"| {names[v]} | {fmt(summ([r for _, r in res[v]]))} | " + " | ".join(fmt(x) for x in sg) + " |")
    rs = [float(np.mean([x[k]["avg"] for x in rand_segs])) for k in range(3)]
    out.append(f"| Vrand 月線位隨機移 ±1–3A（{N_RAND} 種子平均） | 平均 {rn:.0f} 張 平均 {ravg:+.3f}R | "
               + " | ".join(f"平均 {x:+.3f}R" for x in rs) + " |")
    m_all = summ([r for _, r in res["M"]]); m_sg = segs(res["M"])
    ok = {"①最後一段≥30張": m_sg[2]["n"] >= 30, "②最後一段平均R≥+0.15": m_sg[2]["avg"] >= 0.15,
          "③最後一段PF≥1.3": m_sg[2]["pf"] >= 1.3, "④三段平均R都>0": all(x["avg"] > 0 and x["n"] > 0 for x in m_sg),
          "⑤全期高過隨機≥0.10R": m_all["avg"] - ravg >= 0.10}
    out += ["", "## 判（預先登記 IDEAS #230；主判 Vm）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            "- " + ("✅ 合格 → magic 926 影子前向 30 張，達標先提案真倉（固定細注、一次一條；PR＋總指揮 dry-run＋使用者批）"
                    if all(ok.values()) else "❌ 唔合格：" + "、".join(k for k, v in ok.items() if not v)
                    + "；照登記唔做、唔准改參數再試同一批數據；對照組只作描述"), ""]
    open(os.path.join(HERE, "FIB_SR.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
