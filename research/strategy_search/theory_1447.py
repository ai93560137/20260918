"""[IDEAS #1447–#1449] 回看之前研究：三條「有道理＋有苗頭」嘅線索用未用過嘅數據正式驗證（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準。
用法：python3 research/strategy_search/theory_1447.py → research/strategy_search/THEORY_1447.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv); sys.argv = [sys.argv[0]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import canary_1446 as CN       # noqa: E402
import direction_1445 as DR    # noqa: E402
import index_1427 as IX        # noqa: E402

MU, I, SB = CN.MU, CN.I, CN.SB
OUT = os.path.join(HERE, "THEORY_1447.md")
NR = 1000
lit = lambda x: x[3] or x[4] or x[5]  # noqa: E731


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))) if len(a) > 5 and len(b) > 5 else float("nan")


def rnd_pct(r, mask, rng):
    """剔走 mask 嘅單之後留低嘅平均 R，喺「隨機剔走同樣張數」入面嘅百分位。"""
    r = np.asarray(r, float); n = len(r); keep = r[~mask].mean()
    rs = np.array([np.delete(r, rng.choice(n, size=int(mask.sum()), replace=False)).mean() for _ in range(NR)])
    return 100.0 * float((rs < keep).mean())


def t1447(L, days, rows, rng):
    gold = MU.stooq("xauusd", "1990-01-01"); d = I.load(); S = {s[0]: s for s in SB.STRATS}
    src = {"#1273（日線）": IX.sim(gold, IX.CFG[1], 0.0005)[0], "#1285（日線）": IX.sim(gold, IX.CFG[2], 0.0005)[0], "#1290（日線）": IX.sim(gold, IX.CFG[3], 0.0005)[0],
           "#1114（M1）": S["mobrk"][3](d), "#1165（M1）": S["mom1165"][3](d), "#1178（M1）": S["mom1178"][3](d)}
    T = {k: [x for x in CN.tag(v, days, rows) if x[1] < 0] for k, v in src.items()}; allT = [x for v in T.values() for x in v]
    a = [x[2] for x in allT if lit(x)]; b = [x[2] for x in allT if not lit(x)]; ts_ = np.array([x[0] for x in allT]); mid = np.median(ts_)
    h = lambda f: (np.mean([x[2] for x in allT if f(x[0]) and lit(x)]), np.mean([x[2] for x in allT if f(x[0]) and not lit(x)]))  # noqa: E731
    h1, h2 = h(lambda t: t < mid), h(lambda t: t >= mid); tt = welch(a, b)
    pct = rnd_pct([x[2] for x in allT], np.array([lit(x) for x in allT]), rng)
    cons = sum(1 for v in T.values() if [x for x in v if lit(x)] and np.mean([x[2] for x in v if lit(x)]) < np.mean([x[2] for x in v if not lit(x)]))
    g = [np.mean(a) < np.mean(b) and tt <= -2.0, h1[0] < h1[1] and h2[0] < h2[1], pct >= 95, cons >= 4]
    L += ["## #1447 避險期唔沽黃金（6 條未用過嘅規則嘅做空單）", "", "| 規則 | 做空張數 | 亮燈張數 | 冇燈做空平均 R | 亮燈做空平均 R |", "|---|---|---|---|---|"]
    for k, v in T.items():
        x1 = [x[2] for x in v if lit(x)]; x0 = [x[2] for x in v if not lit(x)]
        L.append(f"| {k} | {len(v)} | {len(x1)} | {np.mean(x0):+.3f} | {np.mean(x1) if x1 else float('nan'):+.3f} |")
    L += [f"| **合併** | {len(allT)} | {len(a)} | {np.mean(b):+.3f} | {np.mean(a):+.3f} |", "",
          f"- 差值 {np.mean(a) - np.mean(b):+.3f}R，Welch t {tt:+.2f}；前半 亮 {h1[0]:+.3f}／冇 {h1[1]:+.3f}、後半 亮 {h2[0]:+.3f}／冇 {h2[1]:+.3f}；剔走亮燈做空後對隨機剔走第 {pct:.0f} 百分位；方向一致 {cons}／6",
          f"- 四關（t ≤ −2｜前後半｜≥95 百分位｜≥4／6）：{''.join('✓' if x else '✗' for x in g)} → **{'✅ 合格' if all(g) else '❌ 唔合格'}**", ""]
    return all(g)


def t1448(L, days, rows, rng):
    mk = [("納指期貨 NQ=F", lambda: IX.load("NQ_F"))] + [(nm, (lambda tk=tk: (lambda t, c, d: d)(*(DR.load(tk) + (DR.DC.get("yahood/x_" + "".join(ch if ch.isalnum() else "_" for ch in tk) + "_d.npz"),)))))
                                                     for nm, tk in (("日經", "^N225"), ("德國 DAX", "^GDAXI"), ("英國富時", "^FTSE"), ("歐元區 50", "^STOXX50E"), ("澳洲", "^AXJO"), ("韓國", "^KS11"), ("台灣", "^TWII"), ("印度", "^BSESN"), ("巴西", "^BVSP"))]
    T = {}
    for nm, fn in mk:
        d = fn(); d = {k: d[k] for k in ("t", "o", "h", "l", "c")}; T[nm] = CN.tag(IX.sim(d, IX.CFG[0], 0.0002)[0], days, rows)
    allT = [x for v in T.values() for x in v]; r = np.array([x[2] for x in allT]); m = np.array([lit(x) for x in allT]); ts_ = np.array([x[0] for x in allT]); mid = np.median(ts_)
    pct = rnd_pct(r, m, rng); h1 = (r[m & (ts_ < mid)].mean(), r[~m & (ts_ < mid)].mean()); h2 = (r[m & (ts_ >= mid)].mean(), r[~m & (ts_ >= mid)].mean())
    cons = sum(1 for v in T.values() if np.mean([x[2] for x in v if lit(x)]) < np.mean([x[2] for x in v if not lit(x)]))
    am = CN.monthly(list(zip(ts_, r))); km = CN.monthly(list(zip(ts_[~m], r[~m]))); ra, rk = am.sum() / CN.dd(am), km.sum() / CN.dd(km)
    g = [r[m].mean() < r[~m].mean(), pct >= 95, h1[0] < h1[1] and h2[0] < h2[1], cons >= 7, rk > ra]
    L += ["## #1448 波動率期限結構倒掛時，股指趨勢單唔好開（10 個未用過嘅股指，#1427 規則原封不動）", "", "| 股指 | 張 | 亮燈張數 | 冇燈平均 R | 亮燈平均 R |", "|---|---|---|---|---|"]
    for k, v in T.items():
        x1 = [x[2] for x in v if lit(x)]; x0 = [x[2] for x in v if not lit(x)]
        L.append(f"| {k} | {len(v)} | {len(x1)} | {np.mean(x0):+.3f} | {np.mean(x1):+.3f} |")
    L += [f"| **合併** | {len(r)} | {int(m.sum())} | {r[~m].mean():+.3f} | {r[m].mean():+.3f} |", "",
          f"- Welch t {welch(r[m], r[~m]):+.2f}；留低嘅單對隨機剔走第 {pct:.0f} 百分位；前半 亮 {h1[0]:+.3f}／冇 {h1[1]:+.3f}、後半 亮 {h2[0]:+.3f}／冇 {h2[1]:+.3f}；方向一致 {cons}／10；每月 ΣR÷回落 {ra:.2f} → {rk:.2f}（回落 {CN.dd(am):.1f} → {CN.dd(km):.1f}R、ΣR {am.sum():+.1f} → {km.sum():+.1f}）",
          f"- 五關（亮 < 冇｜≥95 百分位｜前後半｜≥7／10｜ΣR÷回落改善）：{''.join('✓' if x else '✗' for x in g)} → **{'✅ 合格' if all(g) else '❌ 唔合格'}**", ""]
    return all(g)


def t1449(L, days, rows):
    g = MU.stooq("xauusd", "2006-06-01", "2026-11-11"); gd = g["t"] // 86400; ret = np.diff(g["c"]) / g["c"][:-1]; gd = gd[1:]
    def state(lag):
        j = np.searchsorted(days, gd) - lag; ok = j >= 0
        return ok, np.where(ok[:, None], rows[np.maximum(j, 0)], False)
    ok1, s1 = state(1); ok2, s2 = state(2)
    L += ["## #1449 災難軸亮（深紅）之後，黃金日回報較高（黃金 stooq 日線 2006–2026 每日回報）", "", "| 燈 | lag | 亮燈日數 | 亮燈日均 | 其他日均 | 差值 | Welch t |", "|---|---|---|---|---|---|---|"]
    res = {}
    for nm, col in (("深紅", lambda s: s[:, 1]), ("紅", lambda s: s[:, 0]), ("黃×2", lambda s: s[:, 2]), ("任何亮燈", lambda s: s.any(axis=1))):
        for lag, ok, s in ((1, ok1, s1), (2, ok2, s2)):
            m = col(s)[ok]; r = ret[ok]; a, b = r[m], r[~m]; res[(nm, lag)] = (a.mean() - b.mean(), welch(a, b), m, r)
            L.append(f"| {nm} | {lag} | {int(m.sum())} | {1e4 * a.mean():+.1f}bp | {1e4 * b.mean():+.1f}bp | {1e4 * (a.mean() - b.mean()):+.1f}bp | {welch(a, b):+.2f} |")
    d1, t1, m, r = res[("深紅", 1)]; h = len(r) // 2
    hd = [r[:h][m[:h]].mean() - r[:h][~m[:h]].mean(), r[h:][m[h:]].mean() - r[h:][~m[h:]].mean()]
    tim = np.where(m, r, 0.0); yrs = len(r) / 252
    gates = [d1 > 0 and t1 >= 2.0, hd[0] > 0 and hd[1] > 0, res[("深紅", 2)][0] > 0]
    L += ["", f"- 深紅 lag 1：前半差值 {1e4 * hd[0]:+.1f}bp、後半 {1e4 * hd[1]:+.1f}bp；lag 2 差值 {1e4 * res[('深紅', 2)][0]:+.1f}bp",
          f"- 描述：只喺尋日深紅嘅日子揸黃金——在場 {100 * m.mean():.0f}% 日子、年化 {100 * (np.prod(1 + tim) ** (1 / yrs) - 1):+.1f}%（長揸 {100 * (np.prod(1 + r) ** (1 / yrs) - 1):+.1f}%）、在場日 Sharpe {r[m].mean() / r[m].std() * np.sqrt(252):.2f}（長揸 {r.mean() / r.std() * np.sqrt(252):.2f}）",
          f"- 三關（t ≥ 2｜前後半｜lag 2）：{''.join('✓' if x else '✗' for x in gates)} → **{'✅ 合格' if all(gates) else '❌ 唔合格'}**", ""]
    return all(gates)


def main():
    days, rows = CN.lights(); rng = np.random.default_rng(1447)
    L = ["# #1447–#1449：回看之前研究——三條「有道理＋有苗頭」嘅線索正式驗證", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；燈＝`canary/canary_daily.csv`（定義唔改；「亮燈」＝紅或深紅或黃×2；D 日燈只用喺之後）；只讀研究，唔落單", ""]
    r1 = t1447(L, days, rows, rng); r2 = t1448(L, days, rows, rng); r3 = t1449(L, days, rows)
    L += ["## 總結", "", f"- #1447 {'✅' if r1 else '❌'}、#1448 {'✅' if r2 else '❌'}、#1449 {'✅' if r3 else '❌'} → 合格 {sum((r1, r2, r3))}／3", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
