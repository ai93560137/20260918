"""[IDEAS #199] 935 加市況過濾：六個成份嘅樣本外成交（同 #186）入場前先睇入場前一日 D1 市況，唔符合就唔做，之後先做單倉選擇。
過濾（F0 唔過濾、F1 低波幅：ATR20／ATR250 < 1、F2 高波幅：> 1、F3 有趨勢：ADX14 > 20、F4 冇趨勢：ADX14 ≤ 20）；
每年用前 4 年單倉結果揀過濾（≥ 20 張、PF ≥ 1.1，揀平均 R 最高；F0 都喺候選），測嗰一年（2009→2026）。
判「比 935 好」同 #192：平均 > +0.083R、PF > 1.24、最近 10 年正數年 ≥ 7/10、最大回撤唔差過 −26.6R、MT5 > 0。另列每個過濾全期固定（描述）。
用法：python3 research/strategy_search/regime_935.py → REGIME_935.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import m5_indicators as M  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

FILTERS = ("F0 唔過濾", "F1 低波幅", "F2 高波幅", "F3 有趨勢", "F4 冇趨勢")
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def regime(D):
    a250 = M.rolling(np.nan_to_num(D.datr), 250, np.mean)
    with np.errstate(divide="ignore", invalid="ignore"):
        vr = D.datr / a250
    day_t = D.t[D.dfirst]
    def ok(f, ts):
        d = np.searchsorted(day_t, ts, side="right") - 2          # 入場前一日（已收市）
        if d < 0 or f == 0:
            return True
        v, a = vr[d], D.adx[d]
        if np.isnan(v) or np.isnan(a):
            return True
        return {1: v < 1, 2: v >= 1, 3: a > 20, 4: a <= 20}[f]
    return ok


def filt(ds, keys, ok, f):
    return {k: [x for x in ds[k] if ok(f, x[0])] for k in keys}


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    okd, okm = regime(Q.DI(*gd)), regime(Q.DI(*gm))
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    S = {f: PS.single(filt(ds, keys, okd, f), keys) for f in range(5)}
    Sm = {f: PS.single(filt(msA, keys, okm, f), keys) for f in range(5)}
    wf, wfm, picks = [], [], {}
    for Y in range(2009, 2027):
        best = None
        for f in range(5):
            s = R.summ([x[3] for x in S[f] if Y - 4 <= R.yr(x[0]) < Y])
            if s["n"] >= 20 and s["pf"] >= 1.1 and (best is None or s["avg"] > best[1]):
                best = (f, s["avg"])
        picks[Y] = None if best is None else best[0]
        if best is not None:
            wf += [x for x in S[best[0]] if R.yr(x[0]) == Y]
            wfm += [x for x in Sm[best[0]] if R.yr(x[0]) == Y]
    out = ["# 935 加市況過濾（IDEAS #199）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；單倉；每年用前 4 年揀過濾", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, trs, mt in [("主判：過濾交滾動揀", wf, wfm)] + [(f"描述：全期 {FILTERS[f]}", S[f], Sm[f]) for f in range(5)]:
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(trs) else 0.0
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 每年揀咗：" + "、".join(f"{Y} {FILTERS[g][:2] if g is not None else '唔做'}" for Y, g in picks.items()), ""]
    open(os.path.join(HERE, "REGIME_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
