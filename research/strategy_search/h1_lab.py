"""[IDEAS #1087–#1091] Dukascopy H1（黃金 xau/sig/duka_h1/、白銀 xau/sig/duka_h1_xagusd/，2005 起）研究。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1087 驗證（唔係新策略）：#1022 D1 20 日突破、#1026 月尾做多，用 2005–2014（之前從未用過）嘅 H1 合成日線再跑，規則同原版一樣。
新規則（兩段都要過：A＝2005–2014、B＝2015–2026-10；全部用 Duka H1）：
#1088 金銀日線背離：白銀當日（UTC）回報減黃金當日回報 ≥ +2%（白銀強好多）→ 翌日開市買金（≤ −2% 沽金），SL 1×ATR14(D1)，翌日收市走；
#1089 白銀領先（H1）：白銀 H1 回報 ≥ +1% 而黃金同一個鐘 ≤ +0.2%（反之）→ 下一個鐘開市跟白銀方向做金，SL 1.5×ATR14(H1)，4 個鐘收市走；
#1090 月度動量：上個月黃金回報 > 0 → 本月第一個交易日開市買、月尾收市走（< 0 沽）；SL 3×ATR14(D1)；R 以 3×ATR 計；
#1091 週度動量：上週回報 > 0 → 本週第一根開市買、週尾收市走（< 0 沽）；SL 2×ATR14(D1)。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab.py → research/strategy_search/H1_LAB.md"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1023 as B23        # noqa: E402

A = B.A
COST = 0.5
_CACHE = {}


def h1(prefix, y0, y1):
    key = (prefix, y0, y1)
    if key in _CACHE:
        return _CACHE[key]
    cf = f"/tmp/h1lab_{prefix.strip('/').replace('/', '_')}_{y0}_{y1}.npz"
    if os.path.exists(cf):
        z = np.load(cf); d = {k: z[k] for k in z.files}
    else:
        import gb_rulesim as gb
        g = gb.Gcs(); rows = {}
        for y in range(y0, y1 + 1):
            for m in range(1, 13):
                txt = g.read_text(f"{prefix}{y}-{m:02d}.json")
                if not txt:
                    continue
                for r in json.loads(txt):
                    rows[int(r[0])] = r
        ks = sorted(rows)
        d = {"t": np.array(ks, dtype=np.int64)}
        for j, k in enumerate(("o", "h", "l", "c"), 1):
            d[k] = np.array([float(rows[t][j]) for t in ks])
        m = d["h"] > d["l"]                                  # 剔走平盤（休市）K 線
        d = {k: v[m] for k, v in d.items()}
        np.savez(cf, **d)
    _CACHE[key] = d
    return d


def daily(d):
    return B.resample(d, 86400)


def r1088(g, s):
    gd, sd = daily(g), daily(s)
    smap = {int(t) // 86400: k for k, t in enumerate(sd["t"])}
    a = B.atr(gd); out = []
    for i in range(15, len(gd["c"]) - 1):
        k = smap.get(int(gd["t"][i]) // 86400)
        if k is None or np.isnan(a[i]) or a[i] <= 0:
            continue
        gr = gd["c"][i] / gd["o"][i] - 1; sr = sd["c"][k] / sd["o"][k] - 1
        diff = sr - gr
        sg = 1 if diff >= 0.02 else (-1 if diff <= -0.02 else 0)
        if not sg:
            continue
        ei = i + 1; en = gd["o"][ei]; risk = a[i]; sl = en - sg * risk
        ex = sl if ((gd["l"][ei] <= sl) if sg > 0 else (gd["h"][ei] >= sl)) else gd["c"][ei]
        out.append((int(gd["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1089(g, s):
    smap = {int(t): k for k, t in enumerate(s["t"])}
    a = B.atr(g); out = []; busy = -1
    for i in range(15, len(g["c"]) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        k = smap.get(int(g["t"][i]))
        if k is None:
            continue
        sr = s["c"][k] / s["o"][k] - 1; gr = g["c"][i] / g["o"][i] - 1
        sg = 1 if (sr >= 0.01 and gr <= 0.002) else (-1 if (sr <= -0.01 and gr >= -0.002) else 0)
        if not sg:
            continue
        ei = i + 1; en = g["o"][ei]; risk = 1.5 * a[i]
        ex = B.walk(g, ei, sg, en, en - sg * risk, None, 4)
        busy = ei + 3
        out.append((int(g["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def period_mom(g, key_fn, atr_mult):
    gd = daily(g); a = B.atr(gd)
    keys = np.array([key_fn(int(t)) for t in gd["t"]])
    st = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
    out = []
    for p in range(1, len(st) - 1):
        ps, pe = st[p - 1], st[p]; s, e = st[p], st[p + 1]
        ret = gd["c"][pe - 1] - gd["o"][ps]
        if ret == 0 or np.isnan(a[pe - 1]) or a[pe - 1] <= 0:
            continue
        sg = 1 if ret > 0 else -1; en = gd["o"][s]; risk = atr_mult * a[pe - 1]; sl = en - sg * risk; ex = None
        for j in range(s, e):
            if (gd["l"][j] <= sl) if sg > 0 else (gd["h"][j] >= sl):
                ex = sl; break
        if ex is None:
            ex = gd["c"][e - 1]
        out.append((int(gd["t"][s]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1090(g, s=None):
    return period_mom(g, lambda t: (dt.datetime.fromtimestamp(t, dt.timezone.utc).year * 12 + dt.datetime.fromtimestamp(t, dt.timezone.utc).month), 3.0)


def r1091(g, s=None):
    return period_mom(g, lambda t: (t // 86400 + 3) // 7, 2.0)


def judge_ab(ta, tb, na, nb):
    sa, sb = A.stats([x[2] for x in ta]), A.stats([x[2] for x in tb])
    ya = A.by_year(ta); pos = sum(1 for v in ya.values() if v["n"] and v["avg"] > 0); ny = sum(1 for v in ya.values() if v["n"])
    ok = {f"①A（2005–2014）n≥{na}、平均≥+0.10R、PF≥1.15": sa["n"] >= na and sa["avg"] >= 0.10 and sa["pf"] >= 1.15,
          "②A 有交易年份 ≥ 60% 正數": ny > 0 and pos >= 0.6 * ny,
          f"③B（2015–2026）n≥{nb}、平均≥+0.05R、PF≥1.10": sb["n"] >= nb and sb["avg"] >= 0.05 and sb["pf"] >= 1.10}
    return ok, sa, sb, ya, pos, ny


def main():
    gA, gB = h1("xau/sig/duka_h1/", 2005, 2014), h1("xau/sig/duka_h1/", 2015, 2026)
    sA, sB = h1("xau/sig/duka_h1_xagusd/", 2005, 2014), h1("xau/sig/duka_h1_xagusd/", 2015, 2026)
    out = ["# Dukascopy H1 研究（IDEAS #1087–#1091）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；每張扣 0.5 美元", ""]
    out += ["## #1087 驗證：已合格日線規則喺 2005–2014（從未用過）", ""]
    for name, fn, nmin in (("#1022 D1 20 日突破", B.r1022, 100), ("#1026 月尾做多", B23.r1026, 60)):
        tr = fn(gA); st = A.stats([x[2] for x in tr]); yd = A.by_year(tr)
        pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0); ny = sum(1 for v in yd.values() if v["n"])
        ok = st["n"] >= nmin and st["avg"] >= 0.05 and st["pf"] >= 1.10 and pos >= 6
        out += [f"- {name}：{A.fmt(st)}；正數年份 {pos}／{ny}；每年 " + "；".join(f"{y} {v['avg']:+.2f}" for y, v in yd.items() if v["n"]) + f" → **{'✅ 確認' if ok else '⚠ 未見數據唔確認'}**"]
    out.append("")
    for name, fn, na, nb in (("#1088 金銀日線背離（白銀強／弱 ≥ 2%）", r1088, 100, 60), ("#1089 白銀 H1 領先", r1089, 150, 80),
                             ("#1090 月度動量", r1090, 60, 60), ("#1091 週度動量", r1091, 200, 200)):
        ta, tb = fn(gA, sA), fn(gB, sB)
        ok, sa, sb, ya, pos, ny = judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**ya, **A.by_year(tb)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
