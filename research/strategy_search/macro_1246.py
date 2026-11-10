"""[IDEAS #1246–#1250] 宏觀數據（價格以外嘅資料）＋C 門檻。規格以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
數據：research/macro_data/（FRED DFII10、DTWEXBGS；CFTC COT 黃金 088691、白銀 084691）。
冇偷睇：FRED 用訊號日之前（< 訊號日）最後一個數值；COT 星期二數據要訊號日 ≥ 報告日＋4（星期五公布之後）先用。
用法：python3 research/strategy_search/macro_1246.py → research/strategy_search/MACRO_1246.md"""
import csv
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import fade_strict_1129 as F    # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import gate_c_1240 as GC        # noqa: E402
import h1_lab as HL             # noqa: E402
import indep_1235 as I1         # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402

OUT = os.path.join(HERE, "MACRO_1246.md")
MD = os.path.join(HERE, "..", "macro_data")
MAXB = 120


def day_of(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) // 86400


def fred(name):
    out = []
    with open(os.path.join(MD, f"fred_{name}.csv")) as fh:
        r = csv.reader(fh); next(r)
        for row in r:
            if len(row) == 2 and row[1] not in (".", ""):
                out.append((day_of(row[0]), float(row[1])))
    return out


def cot(code):
    out = []
    with open(os.path.join(MD, "cot_gold_silver.csv")) as fh:
        for d in csv.DictReader(fh):
            if d["CFTC_Contract_Market_Code"] == code:
                oi = float(d["Open_Interest_All"]); net = float(d["M_Money_Positions_Long_All"]) - float(d["M_Money_Positions_Short_All"])
                out.append((day_of(d["Report_Date_as_YYYY-MM-DD"]), net, net / oi if oi else 0.0))
    return sorted(out)


def asof(series, day, lag):
    """series＝[(日, …)] 已排序；回傳 日 ≤ day − lag 嘅最後一個 index（冇就 −1）。"""
    days = asof.cache.get(id(series))
    if days is None:
        days = np.array([x[0] for x in series]); asof.cache[id(series)] = days
    return int(np.searchsorted(days, day - lag, side="right")) - 1


asof.cache = {}


def run(d, cond_fn, k_sl, mb, ex_fn=None):
    cx = M3.d1ctx(d); b = cx.b; days = (b["t"] // 86400).astype(int); cond, ex = cond_fn(b, days)
    return GC.edge_sigs(cx, cond, k_sl, mb, ex_fn(cond, b, days) if ex_fn else None)


DFII = fred("DFII10"); USD = fred("DTWEXBGS")
COT = {False: cot("088691"), True: cot("084691")}


def r1246(d, silver=False):
    def cond(b, days):
        c = np.zeros(len(days))
        for i, dd in enumerate(days):
            j = asof(DFII, dd, 1)
            if j < 20:
                continue
            ch = DFII[j][1] - DFII[j - 20][1]
            c[i] = 1 if ch <= -0.15 else (-1 if ch >= 0.15 else 0)
        return c, None
    return run(d, cond, 2.5, 20)


def r1247(d, silver=False):
    def cond(b, days):
        c = np.zeros(len(days))
        for i, dd in enumerate(days):
            j = asof(USD, dd, 1)
            if j < 20:
                continue
            r = USD[j][1] / USD[j - 20][1] - 1
            c[i] = 1 if r <= -0.015 else (-1 if r >= 0.015 else 0)
        return c, None
    return run(d, cond, 2.5, 20)


def r1248(d, silver=False):
    S = COT[silver]; pct = [x[2] for x in S]

    def cond(b, days):
        c = np.zeros(len(days))
        for i, dd in enumerate(days):
            j = asof(S, dd, 4)
            if j < 156:
                continue
            w = pct[j - 155:j + 1]; p = float(np.mean(np.array(w) <= pct[j]))
            c[i] = 1 if p <= 0.10 else (-1 if p >= 0.90 else 0)
        return c, None
    return run(d, cond, 2.5, 20)


def r1249(d, silver=False):
    S = COT[silver]

    def cond(b, days):
        cl = b["c"]; m = F2.sma(cl, 50); c = np.zeros(len(days))
        for i, dd in enumerate(days):
            j = asof(S, dd, 4)
            if j < 4 or np.isnan(m[i]):
                continue
            ch = S[j][1] - S[j - 4][1]
            c[i] = 1 if (ch > 0 and cl[i] > m[i]) else (-1 if (ch < 0 and cl[i] < m[i]) else 0)
        return c, None
    return run(d, cond, 2.5, 20)


def r1250(d, silver=False):
    def cond(b, days):
        cl = b["c"]; m = F2.sma(cl, 100); c = np.zeros(len(days))
        for i, dd in enumerate(days):
            j = asof(DFII, dd, 1)
            if j < 60 or np.isnan(m[i]):
                continue
            ry = DFII[j][1]; ry60 = np.mean([x[1] for x in DFII[j - 59:j + 1]])
            c[i] = 1 if (cl[i] > m[i] and ry < ry60) else (-1 if (cl[i] < m[i] and ry > ry60) else 0)
        return c, None

    def ex_fn(cond_arr, b, days):
        return lambda k, sg: cond_arr[k] != sg
    return run(d, cond, 3.0, MAXB, ex_fn)


RULES = [("#1246", "實質利率急跌做多", r1246), ("#1247", "美元急跌做多", r1247), ("#1248", "COT 投機盤極端反向", r1248),
         ("#1249", "COT 資金流＋趨勢", r1249), ("#1250", "實質利率＋價格趨勢共振", r1250)]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    g05 = HL.h1("xau/sig/duka_h1/", 2005, 2009); s10 = HL.h1("xau/sig/duka_h1_xagusd/", 2010, 2025)
    L = ["# 宏觀數據＋C 門檻（IDEAS #1246–#1250）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；FRED 延遲 1 日、COT 公布後先用；C 門檻同 #1240", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | ④ 黃金 2005–09 | ⑤ 白銀 2010–25 | 判 |", "|---|---|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn in RULES:
        cells, ok = [], True
        for seg, nmin in (("d15", 20), ("m23", 10), ("d10", 15)):
            tr = fn(sets[seg]); n, avg, pf, rob = GC.stats(tr)
            good = n >= nmin and avg > 0 and pf >= 1.15 and rob > 0; extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra}；剔 5% {rob:+.3f} {'✅' if good else '❌'}")
        tr = fn(g05); n, avg, pf, _ = GC.stats(tr); good = n >= 15 and avg > 0 and pf >= 1.10; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        I1.silver_mode(True)
        try:
            tr = fn(s10, silver=True)
        finally:
            I1.silver_mode(False)
        n, avg, pf, _ = GC.stats(tr); good = n >= 30 and avg > 0 and pf >= 1.10; ok = ok and good
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f} {'✅' if good else '❌'}")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    L += ["", f"- C 門檻合格：{'、'.join(passed) if passed else '冇'}（同批 5 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
