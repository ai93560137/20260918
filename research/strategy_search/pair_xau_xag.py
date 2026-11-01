"""[IDEAS #176] XAUUSD／XAGUSD 一長一短（金銀比率）：
- 價差 = ln(金) − ln(銀)；z = (價差 − 過去 L 日平均) ÷ 過去 L 日標準差（D1 收市，22:00 UTC 日界，只用兩邊都有嘅日子）。
- P1 回歸：z > +zin → 沽金買銀；z < −zin → 買金沽銀；z 回到 0 平倉；|z| > 4 止蝕；最多 T 日。
- P2 比率趨勢：過去 L 日價差升 → 買金沽銀，跌 → 沽金買銀；持 20 日（到期再判）。
兩腳名義金額相等；訊號喺 D1 收市判，下一日開盤入／出；回報＝兩腳回報平均（佔總名義 %），扣成本：金 0.5 美元、銀 0.03 美元（每腳來回一次）。
滾動前向：前 4 年揀（≥ 10 張、PF ≥ 1.1，揀平均回報最高），測 1 年，2009→2026。網格寫死（預先登記，跑之前 commit）。
用法：python3 research/strategy_search/pair_xau_xag.py → PAIR.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robust_long as R  # noqa: E402
import silver_friday as F  # noqa: E402

COST_G, COST_S = 0.5, 0.03
SWAP_DAY = 0.0001                       # 敏感度：每日 0.01% 名義（兩腳合計）
FAMILIES = {
    "P1 比率回歸": [dict(L=L, zin=z, T=T) for L, z, T in itertools.product((20, 60, 120), (2.0, 2.5), (20, 60))],
    "P2 比率趨勢": [dict(L=L) for L in (20, 60, 120)],
}


def daily(arr):
    t, o, h, l, c = arr
    key = (t + 7200) // 86400
    ks, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(t)] - 1
    return ks, o[first], c[last]


def align(g, s):
    kg, og, cg = daily(g); ks, os_, cs = daily(s)
    common, ig, is_ = np.intersect1d(kg, ks, return_indices=True)
    return common, og[ig], cg[ig], os_[is_], cs[is_]


def trades(days, og, cg, osv, csv, fam, p):
    sp = np.log(cg) - np.log(csv); n = len(sp); out = []
    if fam.startswith("P1"):
        L = p["L"]
        mu = np.full(n, np.nan); sd = np.full(n, np.nan)
        for i in range(L, n):
            w = sp[i - L:i]; mu[i] = w.mean(); sd[i] = w.std()
        z = (sp - mu) / sd
        i = L
        while i < n - 1:
            if np.isnan(z[i]) or abs(z[i]) < p["zin"]:
                i += 1; continue
            side = -1 if z[i] > 0 else 1                   # +1＝買金沽銀
            a = i + 1; j = a
            while j < n - 1:
                zj = z[j]
                if (side > 0 and zj >= 0) or (side < 0 and zj <= 0) or abs(zj) > 4 or j - a + 1 >= p["T"]:
                    break
                j += 1
            x = j + 1 if j + 1 < n else j
            out.append(_ret(days, og, osv, a, x, side)); i = x
    else:
        L = p["L"]; i = L
        while i < n - 1:
            side = 1 if sp[i] > sp[i - L] else -1
            a = i + 1; x = min(a + 20, n - 1)
            out.append(_ret(days, og, osv, a, x, side)); i = x - 1 if x - 1 > i else i + 1
    return out


def _ret(days, og, osv, a, x, side):
    rg = og[x] / og[a] - 1; rs = osv[x] / osv[a] - 1
    gross = side * 0.5 * (rg - rs)
    cost = 0.5 * (COST_G / og[a] + COST_S / osv[a])
    nd = int(days[x] - days[a])
    return (int(days[a]) * 86400, side, gross - cost, nd)


def summ(rs):
    rs = np.asarray(rs, float)
    if not len(rs):
        return dict(n=0, avg=0.0, pf=0.0, sum=0.0)
    w, l = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return dict(n=len(rs), avg=float(rs.mean()), pf=float(w / l) if l else float("inf"), sum=float(rs.sum()))


def fmt(s):
    return f"{s['n']} 張 平均 {s['avg'] * 100:+.2f}% PF {s['pf']:.2f} 合計 {s['sum'] * 100:+.1f}%"


def mt5_pair():
    import import_mt5 as I
    gold = R.load_mt5_spliced(R.load_duka())
    rows = [l.strip().split(",") for l in open("/tmp/xag_mt5/XAGUSD_H1_MAX.csv").read().splitlines()[1:]]
    t = np.array([I.server_to_utc(r[0]) for r in rows]); a = np.array([[float(v) for v in r[1:5]] for r in rows])
    ds = F.load("xau/sig/duka_h1_xagusd/"); cut = t[0]
    pre = [x[ds[0] < cut] for x in ds]
    silver = [np.r_[pre[0], t], np.r_[pre[1], a[:, 0]], np.r_[pre[2], a[:, 1]], np.r_[pre[3], a[:, 2]], np.r_[pre[4], a[:, 3]]]
    return gold, silver


def main():
    g = R.load_duka(); s = F.load("xau/sig/duka_h1_xagusd/")
    days, og, cg, osv, csv = align(g, s)
    out = ["# XAUUSD／XAGUSD 一長一短（IDEAS #176）", "",
           f"- Dukascopy 兩邊共同 {len(days):,} 日；回報＝佔總名義 %，扣成本（金 0.5、銀 0.03 美元）；滾動前向 4 年揀、1 年測，2009→2026", "",
           "| 家族 | 樣本外 | 正數年 | 兩半 | 扣隔夜成本後 | 判 |", "|---|---|---|---|---|---|"]
    picks, verdict, allt = {}, {}, {}
    for fam, grid in FAMILIES.items():
        T = [trades(days, og, cg, osv, csv, fam, p) for p in grid]
        allt[fam] = T
        oos, yrs, pk = [], {}, {}
        for Y in range(2009, 2027):
            best = None
            for gi, tr in enumerate(T):
                st = summ([x[2] for x in tr if Y - 4 <= R.yr(x[0]) < Y])
                if st["n"] >= 10 and st["pf"] >= 1.1 and (best is None or st["avg"] > best[1]):
                    best = (gi, st["avg"])
            pk[Y] = None if best is None else best[0]
            yt = [] if best is None else [x for x in T[best[0]] if R.yr(x[0]) == Y]
            oos += yt; yrs[Y] = summ([x[2] for x in yt])
        picks[fam] = pk
        st = summ([x[2] for x in oos]); sw = summ([x[2] - SWAP_DAY * x[3] for x in oos])
        h1 = summ([x[2] for x in oos if R.yr(x[0]) <= 2017]); h2 = summ([x[2] for x in oos if R.yr(x[0]) >= 2018])
        pos = sum(1 for v in yrs.values() if v["n"] and v["avg"] > 0)
        ok = dict(n=st["n"] >= 80, avg=st["avg"] > 0, pf=st["pf"] >= 1.2, yrs=pos >= 11, halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0)
        verdict[fam] = ok
        out.append(f"| {fam} | {fmt(st)} | {pos}/18 | {h1['avg'] * 100:+.2f}%／{h2['avg'] * 100:+.2f}% | {sw['avg'] * 100:+.2f}% | "
                   f"{'✅（未核 MT5）' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, fmt(st), flush=True)
    out += ["", "## 全期每組（描述，唔算數）", ""]
    for fam, grid in FAMILIES.items():
        for gi, p in enumerate(grid):
            tr = allt[fam][gi]; yy = {}
            for x in tr:
                yy.setdefault(R.yr(x[0]), []).append(x[2])
            out.append(f"- {fam} {p}：{fmt(summ([x[2] for x in tr]))}，{sum(1 for v in yy.values() if np.mean(v) > 0)}/{len(yy)} 年正，"
                       f"買金沽銀 {fmt(summ([x[2] for x in tr if x[1] > 0]))}／沽金買銀 {fmt(summ([x[2] for x in tr if x[1] < 0]))}")
    out += ["", "## 券商 MT5 對照（2022-10→2026-10，用滾動前向揀出嘅組合）", ""]
    try:
        gm, sm = mt5_pair(); dm = align(gm, sm); a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
        for fam, grid in FAMILIES.items():
            rs = []
            for Y in range(2022, 2027):
                gidx = picks[fam][Y]
                if gidx is None:
                    continue
                rs += [x[2] for x in trades(*dm, fam, grid[gidx]) if R.yr(x[0]) == Y and x[0] >= a0]
            st = summ(rs); verdict[fam]["mt5"] = st["n"] > 0 and st["avg"] > 0
            out.append(f"- {fam}：MT5 {fmt(st)}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}（當未過）")
        for fam in FAMILIES:
            verdict[fam]["mt5"] = False
    passed = [f for f, ok in verdict.items() if all(ok.values())]
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}", "- 合格只開影子前向；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PAIR.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:12]))


if __name__ == "__main__":
    main()
