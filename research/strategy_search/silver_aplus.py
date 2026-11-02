"""[IDEAS #215] A+ 七個成份套用 XAGUSD（白銀，券商 MT5 有得做），參數用白銀自己滾動前向揀（4 年揀 1 年測，2009→2026）；
白銀數據：Dukascopy H1（GCS xau/sig/duka_h1_xagusd/）；MT5 對照＝券商 XAGUSD H1 2022-10→；每張扣 0.03 美元（點差＋滑價）。
單倉（同時 1 張，成份次序同 A+）。判（預先登記）：
  ① 白銀 A+ 單獨：≥ 200 張、平均 ≥ +0.05R、PF ≥ 1.15、最近 10 年 ≥ 6/10 年正、2009–17／2018–26 兩半都正、扣隔夜息後 > 0、MT5 > 0；
  ② 金＋銀兩本書（各自單倉、同時最多各 1 張、每張同樣風險）：2009→2026 每月 R 合計嘅「平均 ÷ 標準差」高過黃金 A+ 單獨，而且最近 10 年正數月比例唔低過黃金單獨。
兩樣都達 → 提案先影子前向；真倉要改程式（白銀 K 線＋新 magic）＋使用者經總指揮批。
用法：python3 research/strategy_search/silver_aplus.py → SILVER_APLUS.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candle_ind as CI  # noqa: E402
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

COST_XAG, COST_XAU = 0.03, 0.5


def streams(arrs, cost, mt5_picks=None):
    R.COST = cost
    D1 = Q.DI(*arrs); D4 = H.H4I(*arrs); DW = S2.D2(*arrs)
    defs = [("1 D1 Keltner 突破", "J5", D1, 480, Q.FAMILIES["J5 Keltner 突破"]),
            ("2 D1 拋物線 SAR", "J7", D1, 480, Q.FAMILIES["J7 拋物線 SAR 轉向"]),
            ("3 D1 威廉 %R", "J8", D1, 480, Q.FAMILIES["J8 威廉 %R 極端回歸"]),
            ("4 H4 MACD", "J2", D4, 80, Q.FAMILIES["J2 MACD 交叉"]),
            ("5 H4 拋物線 SAR", "J7", D4, 80, Q.FAMILIES["J7 拋物線 SAR 轉向"])]
    out, picks = {}, {}

    def per(name, fn, grid):
        if mt5_picks is None:
            out[name], picks[name] = P.wf_stream(fn, grid)
        else:
            out[name] = [x for Y, g in mt5_picks[name].items() if g is not None and Y >= 2022 for x in fn(grid[g]) if R.yr(x[0]) == Y and x[0] >= P.A0]

    for name, key, D, th, grid in defs:
        def fn(p, D=D, key=key, th=th):
            Q.T_H = th; R.COST = cost
            return Q.run(D, key, p)
        per(name, fn, grid)
    per("6 星期效應", lambda p: (setattr(R, "COST", cost), S2.s2(DW, p))[1], S2.FAMILIES["S2 星期效應"])

    def c3(p):
        Q.T_H = 480; R.COST = cost
        return CI.run(D1, "C3 內包線突破", p, 480)
    per("7 D1 內包線突破", c3, CI.GRID)
    return out, picks


def monthly(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if t.year >= 2009:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return mm


def mstats(mm, months):
    v = np.array([mm.get(k, 0.0) for k in months])
    r10 = [mm.get(k, 0.0) for k in months if k[0] >= 2017]
    return float(v.mean()), float(v.std()), float(v.mean() / v.std()) if v.std() > 0 else 0.0, sum(r > 0 for r in r10), sum(1 for r in r10 if r != 0)


def book(arrs_d, arrs_m, cost):
    ds, pk = streams(arrs_d, cost); ms, _ = streams(arrs_m, cost, pk)
    keys = list(ds.keys())
    return PS.single(ds, keys), PS.single(ms, keys), pk


def main():
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    sd = XL.load_xag(); sm = XL.mt5_silver()
    g_tr, g_mt, _ = book(gd, gm, COST_XAU)
    s_tr, s_mt, s_pk = book(sd, sm, COST_XAG)
    out = ["# A+ 套用白銀（IDEAS #215）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；白銀 Dukascopy H1，每張扣 0.03 美元；黃金扣 0.5；單倉；滾動前向 2009→2026", "",
           "| 書 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for label, tr, mt in (("黃金 A+", g_tr, g_mt), ("白銀 A+", s_tr, s_mt)):
        s = R.summ([x[3] for x in tr]); sw = R.summ(R.swap_r(tr)); m = R.summ([x[3] for x in mt]); p10, _ = XL.pos10(tr)
        h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2018])
        eq = np.cumsum([x[3] for x in tr]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(eq) else 0.0
        res[label] = dict(s=s, sw=sw, m=m, p10=p10, h1=h1, h2=h2, dd=dd)
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} |")
        print(label, s, p10, m, flush=True)
    months = [(y, mo) for y in range(2009, 2027) for mo in range(1, 13) if (y, mo) <= (2026, 10)]
    gm_, sm_ = monthly(g_tr), monthly(s_tr); cm = {k: gm_.get(k, 0) + sm_.get(k, 0) for k in set(gm_) | set(sm_)}
    out += ["", "## 每月 R（2009-01→2026-10）", "", "| 書 | 每月平均 R | 標準差 | 平均÷標準差 | 近 10 年正數月 |", "|---|---|---|---|---|"]
    st = {}
    for label, mm in (("黃金 A+", gm_), ("白銀 A+", sm_), ("金＋銀", cm)):
        a, sd_, ratio, pos, nz = mstats(mm, months); st[label] = (ratio, pos / nz if nz else 0)
        out.append(f"| {label} | {a:+.3f} | {sd_:.3f} | {ratio:.3f} | {pos}/{nz}（{pos / nz if nz else 0:.0%}） |")
    va = np.array([gm_.get(k, 0) for k in months]); vb = np.array([sm_.get(k, 0) for k in months])
    corr = float(np.corrcoef(va, vb)[0, 1]) if va.std() > 0 and vb.std() > 0 else float("nan")
    r = res["白銀 A+"]
    ok1 = dict(n=r["s"]["n"] >= 200, avg=r["s"]["avg"] >= 0.05, pf=r["s"]["pf"] >= 1.15, yrs10=r["p10"] >= 6,
               halves=r["h1"]["avg"] > 0 and r["h2"]["avg"] > 0, swap=r["sw"]["avg"] > 0, mt5=r["m"]["n"] > 0 and r["m"]["avg"] > 0)
    ok2 = dict(ratio=st["金＋銀"][0] > st["黃金 A+"][0], posm=st["金＋銀"][1] >= st["黃金 A+"][1])
    out += ["", f"- 金、銀每月 R 相關系數：{corr:+.2f}", "", "## 判（預先登記 IDEAS #215）", "",
            f"- ① 白銀 A+ 單獨：{'✅' if all(ok1.values()) else '❌ ' + '、'.join(k for k, v in ok1.items() if not v)}",
            f"- ② 金＋銀好過黃金單獨：{'✅' if all(ok2.values()) else '❌ ' + '、'.join(k for k, v in ok2.items() if not v)}",
            f"- 結論：{'兩樣都達 → 提案影子前向' if all(ok1.values()) and all(ok2.values()) else '唔達 → 唔加白銀'}", "",
            "## 白銀 2026 揀法", ""] + [f"- {k}：{v.get(2026)}" for k, v in s_pk.items()]
    open(os.path.join(HERE, "SILVER_APLUS.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
