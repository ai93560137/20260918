"""[IDEAS #209] 935 加美元方向過濾：入場前一日（D1 收市）睇美元強弱，同方向先做。
  F0 唔過濾；F1–F3：EURUSD > SMA(N) ＝美元弱 → 只准做多黃金，< → 只准做空（N 50／100／200）；
  F4–F6：USDJPY < SMA(N) ＝美元弱 → 只准做多，> → 只准做空（N 50／100／200）。
每年用前 4 年單倉結果揀過濾（≥ 20 張、PF ≥ 1.1，揀平均 R 最高；F0 都喺候選），測 1 年（2009→2026）。MT5：券商黃金＋Dukascopy 外匯。
判「比 935 好」同 #192（平均 > +0.083R、PF > 1.24、最近 10 年 ≥ 7/10、回撤唔差過 −26.6R、MT5 > 0）；另列近 10 年正數月、每個過濾全期固定（描述）。
用法：python3 research/strategy_search/usd_filter_935.py → USD_FILTER_935.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import other_lead as OL  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

FILTERS = [("F0 唔過濾", None, 0, 0)] + [(f"F{i + 1} 歐元 SMA{n}", "EURUSD", n, 1) for i, n in enumerate((50, 100, 200))] + \
          [(f"F{i + 4} 日圓 SMA{n}", "USDJPY", n, -1) for i, n in enumerate((50, 100, 200))]
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def daily_close(arr):
    t, c = arr[0], arr[4]
    key = (t + 7200) // 86400
    ks, first = np.unique(key, return_index=True); last = np.r_[first[1:], len(t)] - 1
    return ks, c[last]


def make_ok(fx):
    tabs = {}
    for sym, arr in fx.items():
        ks, c = daily_close(arr); cs = np.r_[0, np.cumsum(c)]
        tabs[sym] = (ks, c, cs)
    def ok(fi, side, ts):
        _, sym, n, sgn = FILTERS[fi]
        if sym is None:
            return True
        ks, c, cs = tabs[sym]
        d = np.searchsorted(ks, (ts + 7200) // 86400, side="left") - 1      # 入場前最後一個已收市日
        if d < n:
            return True
        sma = (cs[d + 1] - cs[d + 1 - n]) / n
        weak_usd = (c[d] > sma) if sgn > 0 else (c[d] < sma)
        return weak_usd if side > 0 else not weak_usd
    return ok


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
    ok = make_ok({s: OL.load_mkt(s) for s in ("EURUSD", "USDJPY")})
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    filt = lambda d_, f: {k: [x for x in d_[k] if ok(f, x[1], x[0])] for k in keys}   # noqa: E731
    S = {f: PS.single(filt(ds, f), keys) for f in range(len(FILTERS))}
    Sm = {f: PS.single(filt(msA, f), keys) for f in range(len(FILTERS))}
    wf, wfm, picks = [], [], {}
    for Y in range(2009, 2027):
        best = None
        for f in range(len(FILTERS)):
            s = R.summ([x[3] for x in S[f] if Y - 4 <= R.yr(x[0]) < Y])
            if s["n"] >= 20 and s["pf"] >= 1.1 and (best is None or s["avg"] > best[1]):
                best = (f, s["avg"])
        picks[Y] = None if best is None else best[0]
        if best is not None:
            wf += [x for x in S[best[0]] if R.yr(x[0]) == Y]; wfm += [x for x in Sm[best[0]] if R.yr(x[0]) == Y]
    out = ["# 935 加美元方向過濾（IDEAS #209）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；單倉；每年用前 4 年揀過濾", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, trs, mt in [("主判：過濾交滾動揀", wf, wfm)] + [(f"描述：全期 {FILTERS[f][0]}", S[f], Sm[f]) for f in range(len(FILTERS))]:
        okr, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs); pm, nm = months(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(trs) else 0.0
        e1, m1, _, _ = P.equity(trs, 30000, 1.0)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{e1:,.0f}（{m1:.0%}） | {pm}/{nm} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 每年揀咗：" + "、".join(f"{Y} {FILTERS[g][0].split()[0] if g is not None else '唔做'}" for Y, g in picks.items()), ""]
    open(os.path.join(HERE, "USD_FILTER_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
