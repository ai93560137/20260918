"""[IDEAS #1422–#1426] 黃金日線框架（收市對 SMA200 定方向＋框架內入場）原封不動搬去外匯／貴金屬／利率／能源（使用者 11-12，經總指揮轉達）。
規格、成本、門檻以 IDEAS 預先登記為準（跑之前 commit；唔逐個品種調參）。只用手頭已有數據；只讀研究。
用法：python3 research/strategy_search/multi_1422.py → research/strategy_search/MULTI_1422.md"""
import csv
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC          # noqa: E402
import frame_1272 as FR          # noqa: E402
import oldgold_1260 as OG        # noqa: E402
import robust_1270 as RB         # noqa: E402

M3 = FR.M3
OUT = os.path.join(HERE, "MULTI_1422.md")
MD = OG.MD
_fr = lambda idea: (lambda d, nd: [(int(a), int(b), float(r)) for a, b, r in FR.simulate(M3.d1ctx(d), next(x for x in FR.RULES if x[0] == idea), nd=nd)])  # noqa: E731
RULES = [("#1422", "#1268 重拾 SMA20（狀態機）", lambda d, nd: RB.topdown(d, "pb", nd, 20)), ("#1423", "#1273 RSI14 升穿 40", _fr("#1273")),
         ("#1424", "#1285 單日升 ≥ 1.5×ATR", _fr("#1285")), ("#1425", "#1290 升穿 SMA50", _fr("#1290")), ("#1426", "#1300 只用 SMA200 反轉出場", _fr("#1300"))]
FX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY"]


def stooq(name, a="1968-01-01", b="2026-10-30"):
    t, o, h, l, c = [], [], [], [], []
    with open(os.path.join(MD, f"stooq_{name}_d.csv")) as fh:
        r = csv.reader(fh); next(r)
        for row in r:
            if a <= row[0] <= b:
                t.append(OG.ts(row[0])); o.append(float(row[1])); h.append(float(row[2])); l.append(float(row[3])); c.append(float(row[4]))
    return {"t": np.array(t, np.int64), "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c)}


def fred(name):
    t, c = [], []
    with open(os.path.join(MD, f"fred_{name}.csv")) as fh:
        r = csv.reader(fh); next(r)
        for row in r:
            try:
                v = float(row[1])
            except ValueError:
                continue
            t.append(OG.ts(row[0])); c.append(v)
    c = np.array(c)
    return {"t": np.array(t, np.int64), "o": c, "h": c, "l": c, "c": c}


def mt5(sym):
    parts = [DC.get(f"mt5x/{sym}_m1_{y}.npz") for y in ("2022", "2023", "2024", "2025", "2026p")]
    d = {k: np.concatenate([p[k] for p in parts if p is not None]) for k in ("t", "o", "h", "l", "c")}
    ny = pd.to_datetime(d["t"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)   # 紐約 17:00 換日
    day = ((ny.normalize() - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy()
    st = np.r_[0, np.nonzero(np.diff(day))[0] + 1]; en = np.r_[st[1:], len(day)]
    return {"t": day[st].astype(np.int64) * 86400, "o": d["o"][st], "h": np.maximum.reduceat(d["h"], st), "l": np.minimum.reduceat(d["l"], st), "c": d["c"][en - 1]}


def run(d, cost, nd=200):
    restore = OG.patch("gold"); OG._rate[0] = cost
    try:
        return {rid: fn(d, nd) for rid, _, fn in RULES}
    finally:
        restore()


def st(tr):
    r = np.array([x[2] for x in tr], float)
    if not len(r):
        return 0, float("nan"), float("nan")
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return len(r), float(r.mean()), float(w / ls) if ls else 99.0


def mean(v):
    return float(np.mean(v)) if len(v) else float("nan")


def month(t):
    x = dt.datetime.fromtimestamp(int(t), dt.timezone.utc); return x.year * 12 + x.month


def corr(a, b):
    ma, mb = {}, {}
    for t, _, r in a:
        ma[month(t)] = ma.get(month(t), 0) + r
    for t, _, r in b:
        mb[month(t)] = mb.get(month(t), 0) + r
    ts_ = [x[0] for x in a + b]
    if not ts_:
        return float("nan")
    ks = range(max(min(month(x[0]) for x in a), min(month(x[0]) for x in b)), min(max(month(x[0]) for x in a), max(month(x[0]) for x in b)) + 1) if a and b else []
    x = np.array([ma.get(k, 0) for k in ks]); y = np.array([mb.get(k, 0) for k in ks])
    return float(np.corrcoef(x, y)[0, 1]) if len(x) > 12 and x.std() > 0 and y.std() > 0 else float("nan")


def split_t(tr):
    ts_ = sorted(x[0] for x in tr); return ts_[len(ts_) // 2] if ts_ else 0


def long_block(L, title, d, cost, gold_tr, dec=10):
    base = run(d, cost); nb = {nd: run(d, cost, nd) for nd in (150, 250)}; verdicts = {}
    y0 = OG.year(d["t"][0]) + 1; y1 = OG.year(d["t"][-1])
    L += [f"### {title}（{dt.datetime.fromtimestamp(int(d['t'][0]), dt.timezone.utc):%Y-%m} → {dt.datetime.fromtimestamp(int(d['t'][-1]), dt.timezone.utc):%Y-%m}，{len(d['t']):,} 日；成本 {cost * 100:.3f}%）", "",
          "| # | 規則 | 張 | 平均 R | PF | 前半 | 後半 | 多 | 空 | SMA150 | SMA250 | 同黃金每月相關 | 每十年 ΣR | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for rid, nm, _ in RULES:
        tr = base[rid]; n, m, pf = st(tr); sp = split_t(tr)
        h1, h2 = mean([x[2] for x in tr if x[0] < sp]), mean([x[2] for x in tr if x[0] >= sp])
        lo, sh = mean([x[2] for x in tr if x[1] > 0]), mean([x[2] for x in tr if x[1] < 0])
        n1, n2 = st(nb[150][rid])[1], st(nb[250][rid])[1]
        decs = {}
        for t, _, r in tr:
            decs[OG.year(t) // dec * dec] = decs.get(OG.year(t) // dec * dec, 0) + r
        ok = all(v > 0 for v in (m, h1, h2, lo, sh, n1, n2)) and pf >= 1.15; verdicts[rid] = ok
        L.append(f"| {rid} | {nm} | {n} | {m:+.3f} | {pf:.2f} | {h1:+.3f} | {h2:+.3f} | {lo:+.3f} | {sh:+.3f} | {n1:+.3f} | {n2:+.3f} | {corr(tr, gold_tr[rid]):+.2f} | "
                 + "、".join(f"{k}s {v:+.0f}" for k, v in sorted(decs.items())) + f" | {'✅' if ok else '❌'} |")
    L.append(""); return verdicts, base


def main():
    L = ["# #1422–#1426：黃金日線框架搬去外匯／貴金屬／利率／能源", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只用手頭已有數據；只讀研究，唔落單、唔改服務",
         "- 規則原封不動（SMA200 定方向、SL 3×ATR14、250 日到期、做空鏡像）；日線執行模擬（下一日開市入、跳空穿止蝕用開市價、最低止蝕 0.3×ATR）",
         "- 「判」＝平均、前後半、多、空、SMA150／250 鄰近全部 > 0 而且 PF ≥ 1.15（黃金嗰套「方向一致」）", ""]
    gold_long = run(stooq("xauusd", "1973-01-01"), 0.0005); xau = mt5("XAUUSD"); gold_short = run(xau, 0.0005)
    L += ["## 參考：黃金同一套程式", ""]
    long_block(L, "黃金 stooq 日線", stooq("xauusd", "1973-01-01"), 0.0005, gold_long)
    summary = {}

    L += ["## ② 貴金屬：白銀（手頭冇鉑、鈀）", ""]
    v, _ = long_block(L, "白銀 stooq 日線（可買賣價，OHLC）", stooq("xagusd"), 0.0012, gold_long); summary["白銀（長歷史）"] = v

    L += ["## ① 外匯", "", "### 長歷史代理：FRED 美元指數（只有收市；指數本身唔可以直接買賣）", ""]
    v, _ = long_block(L, "DTWEXM 美元對主要貨幣指數", fred("DTWEXM"), 0.0002, gold_long); summary["美元指數 1973–2019（代理）"] = v
    v, _ = long_block(L, "DTWEXBGS 美元廣義指數", fred("DTWEXBGS"), 0.0002, gold_long); summary["美元指數 2006–2026（代理）"] = v

    def short_table(title, syms, cost_fn):
        res = {s: run(mt5(s), cost_fn(s)) for s in syms}
        L.extend([f"### {title}", "", "| # | 規則 | 張 | 平均 R | PF | 多 | 空 | 為正品種 | 同黃金每月相關 | 每年 ΣR | 各品種平均 R | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        out = {}
        for rid, nm, _ in RULES:
            tr = [x for s in syms for x in res[s][rid]]; n, m, pf = st(tr)
            lo, sh = mean([x[2] for x in tr if x[1] > 0]), mean([x[2] for x in tr if x[1] < 0])
            pos = sum(1 for s in syms if st(res[s][rid])[1] > 0); yrs = {}
            for t, _, r in tr:
                yrs[OG.year(t)] = yrs.get(OG.year(t), 0) + r
            ok = m > 0 and pf >= 1.15 and lo > 0 and sh > 0 and pos >= (6 if len(syms) == 9 else 1); out[rid] = ok
            L.append(f"| {rid} | {nm} | {n} | {m:+.3f} | {pf:.2f} | {lo:+.3f} | {sh:+.3f} | {pos}／{len(syms)} | {corr(tr, gold_short[rid]):+.2f} | "
                     + "、".join(f"{k} {v:+.1f}" for k, v in sorted(yrs.items())) + " | " + "、".join(f"{s} {st(res[s][rid])[1]:+.2f}（{st(res[s][rid])[0]}）" for s in syms) + f" | {'✅' if ok else '❌'} |")
        L.append(""); return out

    summary["外匯 9 對 MT5（約 3.4 年）"] = short_table("可買賣價：券商 MT5 9 對合併（2022-08→2026-11，預熱後約 3.4 年；低證據力）", FX, lambda s: 0.0002 if s.endswith("JPY") and s != "USDJPY" else 0.00015)
    summary["白銀 MT5（約 3.4 年）"] = short_table("（貴金屬補充）白銀 MT5（同期）", ["XAGUSD"], lambda s: 0.0012)

    L += ["## ③ 利率（手頭冇可買賣價格；只有 FRED 孳息，當代理）", ""]
    v, _ = long_block(L, "DGS10 美國 10 年期孳息（只有收市；係孳息唔係債價）", fred("DGS10"), 0.0025, gold_long); summary["10 年孳息 1962–2026（代理）"] = v
    v, _ = long_block(L, "T10YIE 10 年期通脹預期（只有收市）", fred("T10YIE"), 0.0025, gold_long); summary["通脹預期 2003–2026（代理）"] = v
    L += ["- DFII10（實質孳息）冇跑：數值長期貼近 0 甚至負數，按比例計成本同 ATR 冇意義。", ""]

    L += ["## ④ 能源：原油（手頭只有一個品種；冇天然氣、布蘭特）", ""]
    summary["原油 MT5（約 3.4 年）"] = short_table("CL-OIL 券商 MT5（2022-08→2026-10-30，預熱後約 3.4 年；低證據力）", ["CL-OIL"], lambda s: 0.0008)

    L += ["## 總表", "", "| 序列 | " + " | ".join(r[0] for r in RULES) + " | 過幾多條 |", "|---|" + "---|" * (len(RULES) + 1)]
    for k, v in summary.items():
        L.append(f"| {k} | " + " | ".join("✅" if v[r[0]] else "❌" for r in RULES) + f" | {sum(v.values())}／5 |")
    L.append("")
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
