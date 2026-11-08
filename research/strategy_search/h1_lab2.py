"""[IDEAS #1092–#1095] Duka H1 長歷史第二批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1092 D1 IBS 回歸：IBS＝(收市−低)/(高−低) < 0.15 → 翌日開市買、翌日收市走（> 0.85 → 沽），SL 1×ATR14(D1)；
#1093 H1 收喺 24 個鐘區間極端：H1 收市喺前 24 根（含今根）高低區間最低 10% → 下一根開市買（最高 10% → 沽），SL 1.5×ATR14(H1)，6 根收市走；
#1094 D1 趨勢內買 10 日低：收市高過 SMA200 而收市係 10 日最低收市 → 翌日開市買，收市係 5 日最高收市先走（最多 10 日），SL 2×ATR（下跌趨勢相反）；
#1095 H4 收窄突破：H4 ATR5／ATR50 < 0.6 之後，下一根 H4 穿上一根高 → 做多（穿低 → 做空），SL 上一根另一邊、TP 2R、6 根。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab2.py → research/strategy_search/H1_LAB2.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402

B, A = L.B, L.A
COST = 0.5


def r1092(g):
    d = B.resample(g, 86400); o, h, l, c = d["o"], d["h"], d["l"], d["c"]; a = B.atr(d); out = []
    for i in range(15, len(c) - 1):
        rg = h[i] - l[i]
        if rg <= 0 or np.isnan(a[i]) or a[i] <= 0:
            continue
        ibs = (c[i] - l[i]) / rg
        sg = 1 if ibs < 0.15 else (-1 if ibs > 0.85 else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; risk = a[i]; sl = en - sg * risk
        ex = sl if ((l[ei] <= sl) if sg > 0 else (h[ei] >= sl)) else c[ei]
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1093(g):
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]; a = B.atr(g); out = []; busy = -1
    for i in range(24, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        hh, ll = h[i - 23:i + 1].max(), l[i - 23:i + 1].min()
        if hh - ll <= 0:
            continue
        pos = (c[i] - ll) / (hh - ll)
        sg = 1 if pos <= 0.10 else (-1 if pos >= 0.90 else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; risk = 1.5 * a[i]
        ex = B.walk(g, ei, sg, en, en - sg * risk, None, 6)
        busy = ei + 5
        out.append((int(g["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1094(g):
    d = B.resample(g, 86400); o, h, l, c = d["o"], d["h"], d["l"], d["c"]; a = B.atr(d); s200 = B.sma(c, 200)
    out, i = [], 201
    while i < len(c) - 1:
        if np.isnan(s200[i]) or np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        sg = 1 if (c[i] > s200[i] and c[i] <= c[i - 9:i + 1].min()) else (-1 if (c[i] < s200[i] and c[i] >= c[i - 9:i + 1].max()) else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = o[ei]; risk = 2 * a[i]; sl = en - sg * risk; ex = None; j = ei
        while j < min(len(c), ei + 10):
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (c[j] >= c[j - 4:j + 1].max()) if sg > 0 else (c[j] <= c[j - 4:j + 1].min()):
                ex = c[j]; break
            j += 1
        if ex is None:
            j = min(len(c), ei + 10) - 1; ex = c[j]
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
        i = j + 1
    return out


def r1095(g):
    b = B.resample(g, 4 * 3600); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    a5, a50 = B.atr(b, 5), B.atr(b, 50); out, busy = [], -1
    for i in range(51, len(c) - 1):
        if i <= busy or np.isnan(a50[i - 1]) or a50[i - 1] <= 0 or a5[i - 1] / a50[i - 1] >= 0.6:
            continue
        up, dn = h[i] > h[i - 1], l[i] < l[i - 1]
        if up == dn:
            continue
        sg = 1 if up else -1; en = max(h[i - 1], o[i]) if up else min(l[i - 1], o[i])
        sl = l[i - 1] if sg > 0 else h[i - 1]; risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        tp = en + sg * 2 * risk
        if (l[i] <= sl) if sg > 0 else (h[i] >= sl):
            ex = sl
        else:
            ex = B.walk(b, i + 1, sg, en, sl, tp, 6)
        busy = i + 6
        out.append((int(b["t"][i]), sg, (sg * (ex - en) - COST) / risk))
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    out = ["# Duka H1 長歷史第二批（IDEAS #1092–#1095）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；每張扣 0.5 美元", ""]
    for name, fn, na, nb in (("#1092 D1 IBS 回歸", r1092, 300, 200), ("#1093 H1 收喺 24 個鐘區間極端反向", r1093, 300, 200),
                             ("#1094 D1 趨勢內買 10 日低", r1094, 60, 40), ("#1095 H4 收窄突破", r1095, 150, 100)):
        ta, tb = fn(gA), fn(gB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**ya, **A.by_year(tb)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB2.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
