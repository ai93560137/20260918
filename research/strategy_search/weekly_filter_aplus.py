"""[IDEAS #216] A+ 加週線趨勢過濾：入場前最後一個已收市週（週界＝星期日 22:00 UTC），黃金自己嘅週線方向同入場方向一致先做。
  F0 唔過濾；F1–F3：週收市 > 週 SMA(N) → 只准做多、< → 只准做空（N＝10／20／40 週）；F4：週 SMA10 比 4 週前高 → 只准做多、低 → 只准做空。
過濾套落 A+ 七個成份（各自滾動前向揀咗嘅樣本外成交）之後再做單倉；每年用前 4 年單倉結果揀過濾（≥ 20 張、PF ≥ 1.1、揀平均 R 最高；F0 都喺候選），測 1 年 2009→2026。
判「比 A+ 好」（預先登記）：平均 > +0.101R、PF > 1.30、近 10 年正 ≥ 7/10、回撤唔差過 −25.7R、MT5 > 0。另列每個過濾全期固定（描述）。
用法：python3 research/strategy_search/weekly_filter_aplus.py → WEEKLY_FILTER_APLUS.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candle_ind as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import vol2 as V2  # noqa: E402
import vol_ind as V  # noqa: E402
import xag_lead as XL  # noqa: E402

FILTERS = [("F0 唔過濾", None)] + [(f"F{i + 1} 週收市對 SMA{n}", ("lvl", n)) for i, n in enumerate((10, 20, 40))] + [("F4 週 SMA10 斜率", ("slope", 10))]


def weekly(arr):
    t, c = arr[0], arr[4]
    day = (t + 7200) // 86400                      # 券商日（22:00 UTC 日界）
    wk = (day + 3) // 7                            # 1970-01-01 係星期四 → 星期一開始嘅週
    ks, first = np.unique(wk, return_index=True); last = np.r_[first[1:], len(t)] - 1
    return ks, c[last]


def make_ok(arr):
    ks, c = weekly(arr); cs = np.r_[0, np.cumsum(c)]

    def sma(i, n):
        return (cs[i + 1] - cs[i + 1 - n]) / n

    def ok(fi, side, ts):
        spec = FILTERS[fi][1]
        if spec is None:
            return True
        w = np.searchsorted(ks, ((ts + 7200) // 86400 + 3) // 7, side="left") - 1   # 入場前最後一個已收市週
        kind, n = spec
        if w < n + 4:
            return True
        up = c[w] > sma(w, n) if kind == "lvl" else sma(w, n) > sma(w - 4, n)
        return up if side > 0 else not up
    return ok


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    okd, okm = make_ok(gd), make_ok(gm)
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    D1, M1 = Q.DI(*gd), Q.DI(*gm); Q.T_H = 480
    c3, c3m, _ = V2.wf_family(D1, M1, "C3 內包線突破", C.GRID, 480, C._orig_signals)
    ds["C3"] = c3; ms["C3"] = c3m; keys = keys + ["C3"]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    filt = lambda d_, f, ok: {k: [x for x in d_[k] if ok(f, x[1], x[0])] for k in keys}   # noqa: E731
    S = {f: PS.single(filt(ds, f, okd), keys) for f in range(len(FILTERS))}
    Sm = {f: PS.single(filt(msA, f, okm), keys) for f in range(len(FILTERS))}
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
    out = ["# A+ 加週線趨勢過濾（IDEAS #216）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；單倉；每年用前 4 年揀過濾；A+ 現行＝描述 F0", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 近 10 年正數月 | 比 A+ 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    A = V.APLUS
    for label, trs, mt in [("主判：過濾交滾動揀", wf, wfm)] + [(f"描述：全期 {FILTERS[f][0]}", S[f], Sm[f]) for f in range(len(FILTERS))]:
        okr, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs); pm, nm = C.months(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(trs) else 0.0
        better = s["avg"] > A["avg"] and s["pf"] > A["pf"] and p10 >= A["yrs10"] and dd >= A["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{pm}/{nm} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s["n"], round(s["avg"], 3), round(s["pf"], 2), p10, round(dd, 1), flush=True)
    out += ["", "- 每年揀咗：" + "、".join(f"{Y} {FILTERS[g][0].split()[0] if g is not None else '唔做'}" for Y, g in picks.items()), ""]
    open(os.path.join(HERE, "WEEKLY_FILTER_APLUS.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
