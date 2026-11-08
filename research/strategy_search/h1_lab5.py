"""[IDEAS #1103–#1105] Duka H1 長歷史第五批（A＝2005–2014、B＝2015–2026-10）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1103 基準（唔計做策略）：每週星期二第一根開市買、星期五最後一根收市走，SL 2×ATR14(D1)；用嚟睇 #1096／#1102 有冇好過純粹揸金；
#1104 金銀比率回歸：金銀比率（金收市／銀收市）20 日 z 分數 ≥ +2 → 翌日開市沽金（≤ −2 → 買金），5 日收，SL 2×ATR14(D1)；
#1105 52 週收市新高 → 翌日開市買，持 20 個交易日，SL 3×ATR14(D1)（52 週新低相反）。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab5.py → research/strategy_search/H1_LAB5.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402

B, A = L.B, L.A
COST = 0.5


def hold(d, ei, n, sg, en, sl):
    ex = None
    for j in range(ei, min(len(d["c"]), ei + n)):
        if (d["l"][j] <= sl) if sg > 0 else (d["h"][j] >= sl):
            ex = sl; break
    return d["c"][min(len(d["c"]), ei + n) - 1] if ex is None else ex


def r1103(g, s=None):
    d = B.resample(g, 86400); a = B.atr(d); out = []
    wd = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).weekday() for x in d["t"]])
    for i in range(15, len(d["c"]) - 4):
        if wd[i] != 1 or np.isnan(a[i - 1]) or a[i - 1] <= 0:
            continue
        j = i
        while j + 1 < len(wd) and wd[j + 1] <= 4 and wd[j + 1] > wd[j]:
            j += 1
        en = d["o"][i]; risk = 2 * a[i - 1]; sl = en - risk
        ex = hold(d, i, j - i + 1, 1, en, sl)
        out.append((int(d["t"][i]), 1, (ex - en - COST) / risk))
    return out


def r1104(g, s):
    gd, sd = B.resample(g, 86400), B.resample(s, 86400)
    smap = {int(t) // 86400: k for k, t in enumerate(sd["t"])}
    idx = [(i, smap.get(int(t) // 86400)) for i, t in enumerate(gd["t"])]
    ratio = np.array([gd["c"][i] / sd["c"][k] if k is not None else np.nan for i, k in idx])
    a = B.atr(gd); out, i = [], 25
    while i < len(ratio) - 1:
        w = ratio[i - 19:i + 1]
        if np.isnan(w).any() or np.isnan(a[i]) or a[i] <= 0 or w.std() == 0:
            i += 1; continue
        z = (ratio[i] - w.mean()) / w.std()
        sg = -1 if z >= 2 else (1 if z <= -2 else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = gd["o"][ei]; risk = 2 * a[i]
        ex = hold(gd, ei, 5, sg, en, en - sg * risk)
        out.append((int(gd["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); i = ei + 5
    return out


def r1105(g, s=None):
    d = B.resample(g, 86400); c = d["c"]; a = B.atr(d); out, i = [], 253
    while i < len(c) - 1:
        if np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        sg = 1 if c[i] > c[i - 252:i].max() else (-1 if c[i] < c[i - 252:i].min() else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = d["o"][ei]; risk = 3 * a[i]
        ex = hold(d, ei, 20, sg, en, en - sg * risk)
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); i = ei + 20
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    sA, sB = L.h1("xau/sig/duka_h1_xagusd/", 2005, 2014), L.h1("xau/sig/duka_h1_xagusd/", 2015, 2026)
    out = ["# Duka H1 長歷史第五批（IDEAS #1103–#1105）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10", ""]
    for name, fn, na, nb in (("#1103 基準：每週星期二買、星期五走（唔計做策略）", r1103, 300, 300),
                             ("#1104 金銀比率 z 分數回歸", r1104, 60, 60), ("#1105 52 週收市新高／低（持 20 日）", r1105, 30, 30)):
        ta, tb = fn(gA, sA), fn(gB, sB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                f"- 做多／做空 A：{A.fmt(A.stats([x[2] for x in ta if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in ta if x[1] < 0]))}",
                f"- 做多／做空 B：{A.fmt(A.stats([x[2] for x in tb if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tb if x[1] < 0]))}",
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("（基準，唔判）" if "基準" in name else ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達")) + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB5.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
