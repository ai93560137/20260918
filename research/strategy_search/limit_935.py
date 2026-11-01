"""[IDEAS #202] 935 用限價單入場：訊號同 935 一樣，但唔係下一根開盤市價入，改喺開盤價退後 k × 訊號 ATR 掛限價（做多＝開盤 − k×ATR），
N 小時內成交先算（成交價＝限價；如果開盤已經跳過限價就用開盤價），唔成交就放棄。SL／TP 距離由成交價起計（R 照用原本 SL 距離）。
每個成份每年用前 4 年揀（參數 × 入場方式 {市價, k∈{0.25,0.5} × N∈{4,24}}，同 935 一樣嘅滾動前向規則），星期效應照用市價（唔改）。
判「比 935 好」同 #192（平均 > +0.083R、PF > 1.24、最近 10 年 ≥ 7/10、回撤唔差過 −26.6R、MT5 > 0）；另列全部固定一種入場做描述同近 10 年正數月。
用法：python3 research/strategy_search/limit_935.py → LIMIT_935.md"""
import datetime as dt
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import exits_a as X  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

ENTRY = [dict(k=0.0, N=0)] + [dict(k=k, N=n) for k in (0.25, 0.5) for n in (4, 24)]
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def sim_limit(D, entries, k, N):
    """entries：(a, s, d, tpd, mh, atr)。k=0 ＝ 市價（同 R.simulate）。"""
    t, o, h, l = D.t, D.o, D.h, D.l
    n = len(t); out = []; busy = -1
    for a, s, d, tpd, mh, atr in entries:
        if a <= busy or a >= n or not d or d <= 0 or math.isnan(d):
            continue
        if k > 0:
            lim = o[a] - s * k * atr; f = None
            for j in range(a, n):
                if t[j] - t[a] >= N * 3600:
                    break
                if (o[j] - lim) * s <= 0:
                    f, px = j, o[j]; break
                if (l[j] <= lim) if s > 0 else (h[j] >= lim):
                    f, px = j, lim; break
            if f is None:
                continue
            a0 = f
        else:
            a0, px = a, o[a]
        sl = px - s * d; tp = None if tpd is None else px + s * tpd; ex = None
        for j in range(a0, n):
            if t[j] - t[a] >= mh * 3600:
                ex, xi = o[j], j - 1; break
            if j > a0 and (o[j] - sl) * s <= 0:
                ex, xi = o[j], j; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex, xi = sl, j; break
            if tp is not None and ((h[j] >= tp) if s > 0 else (l[j] <= tp)):
                ex, xi = tp, j; break
        if ex is None:
            break
        out.append((int(t[a0]), s, float(d), float((s * (ex - px) - R.COST) / d), int(t[min(max(xi, a0) + 1, n - 1)])))
        busy = max(xi, a0)
    return out


def run(D, fam, p, th):
    b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th, D.datr[d])
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    return sim_limit(D, ent, p["k"], p["N"])


def months(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if 2017 <= t.year <= 2026:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return sum(v > 0 for v in mm.values()), len(mm)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    fr = {"D1": (Q.DI(*gd), Q.DI(*gm)), "H4": (H.H4I(*gd), H.H4I(*gm))}
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    new_d, new_m = dict(ds), dict(msA)
    forced = {i: (dict(ds), dict(msA)) for i in range(1, len(ENTRY))}
    rows = []
    for name, fam, tf, th in X.COMPS:
        D, Mx = fr[tf]
        grid = [dict(p, **e) for p in Q.FAMILIES[fam] for e in ENTRY]
        T = [run(D, fam, p, th) for p in grid]
        oos, pk = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
        cache, mt = {}, []
        for Y, g in pk.items():
            if g is not None and Y >= 2022:
                if g not in cache:
                    cache[g] = run(Mx, fam, grid[g], th)
                mt += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
        new_d[name] = [x for x in oos if R.yr(x[0]) >= 2009]; new_m[name] = mt
        rows.append(f"| {name} | {R.fmt(R.summ([x[3] for x in new_d[name]]))} | {grid[pk[2026]] if pk.get(2026) is not None else '唔做'} |")
        for i in range(1, len(ENTRY)):
            sub = [p for p in grid if p["k"] == ENTRY[i]["k"] and p["N"] == ENTRY[i]["N"]]; Ts = [T[grid.index(p)] for p in sub]
            o2, pk2 = P.wf_stream(lambda p, Ts=Ts, sub=sub: Ts[sub.index(p)], sub)
            forced[i][0][name] = [x for x in o2 if R.yr(x[0]) >= 2009]
            mm = []
            for Y, g in pk2.items():
                if g is not None and Y >= 2022:
                    mm += [x for x in run(Mx, fam, sub[g], th) if R.yr(x[0]) == Y and x[0] >= P.A0]
            forced[i][1][name] = mm
        print(name, flush=True)
    out = ["# 935 限價單入場（IDEAS #202）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；星期效應照市價", "",
           "## 各成份（新揀法，樣本外）", "", "| 成份 | 樣本外 | 2026 揀 |", "|---|---|---|", *rows, "",
           "## 單倉", "", "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 18 年正 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 比 935 好？ |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    vers = [("935 現行（市價）", ds, msA), ("主判：入場方式交滾動揀", new_d, new_m)] + [(f"描述：全部限價 k={ENTRY[i]['k']} N={ENTRY[i]['N']}h", *forced[i]) for i in range(1, len(ENTRY))]
    for label, d_, m_ in vers:
        trs = PS.single(d_, keys); mt = PS.single(m_, keys)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0); pm, nm = months(trs)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pos}/{ny} | {sw['avg']:+.3f} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{e1:,.0f}（{m1:.0%}） | {pm}/{nm} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 限價成交假設：掂到限價就成交（冇計排隊／滑價）；開盤跳過限價用開盤價。", ""]
    open(os.path.join(HERE, "LIMIT_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
