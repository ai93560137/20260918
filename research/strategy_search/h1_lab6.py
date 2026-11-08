"""[IDEAS #1106–#1109] Duka H1 長歷史第六批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。冇未來函數。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1106 週收市強弱：上週收市喺上週高低區間頂 25% → 本週星期二開市買、週尾收市走（底 25% → 沽），SL 2×ATR14(D1)；
#1107 上季高／低突破：今季第一次穿上季高 → 做多（低 → 做空），SL 上季中位，季尾收市走；
#1108 H4 Donchian 20 突破：H4 穿前 20 根高（掛單價）→ 做多（低 → 做空），SL 20 根中位，6 根 H4 收（同根掂 SL 當 SL）；
#1109 白銀 20 日新高 → 翌日開市買金（新低 → 沽金），SL 1.5×ATR14(D1)，5 日收。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab6.py → research/strategy_search/H1_LAB6.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402
import h1_lab3 as L3            # noqa: E402
import h1_lab5 as L5            # noqa: E402

B, A = L.B, L.A
COST = 0.5


def r1106(g, s=None):
    d = B.resample(g, 86400); a = B.atr(d); t = d["t"]
    wk = np.array([L3.wkey(int(x)) for x in t]); wd = np.array([L3.wday(int(x)) for x in t])
    ss = L3.segs(wk); out = []
    for (ps, pe), (s0, e) in zip(ss[:-1], ss[1:]):
        hi, lo, c = d["h"][ps:pe].max(), d["l"][ps:pe].min(), d["c"][pe - 1]
        if hi - lo <= 0 or np.isnan(a[pe - 1]) or a[pe - 1] <= 0:
            continue
        pos = (c - lo) / (hi - lo)
        sg = 1 if pos >= 0.75 else (-1 if pos <= 0.25 else 0)
        tue = [j for j in range(s0, e) if wd[j] == 1]
        if not sg or not tue:
            continue
        i = tue[0]; en = d["o"][i]; risk = 2 * a[pe - 1]
        ex = L5.hold(d, i, e - i, sg, en, en - sg * risk)
        out.append((int(t[i]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1107(g, s=None):
    t = g["t"]
    qk = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year * 4 + (dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month - 1) // 3 for x in t])
    ss = L3.segs(qk); out = []
    for (ps, pe), (s0, e) in zip(ss[:-1], ss[1:]):
        hi, lo = g["h"][ps:pe].max(), g["l"][ps:pe].min(); mid = (hi + lo) / 2
        x = L3.trade_break(g, s0, e, hi, lo, lambda sg: mid, None, lambda j: True)
        if x:
            out.append(x)
    return out


def r1108(g, s=None):
    b = B.resample(g, 4 * 3600); o, h, l, c, t = b["o"], b["h"], b["l"], b["c"], b["t"]; out, busy = [], -1
    for i in range(21, len(c) - 1):
        if i <= busy:
            continue
        hi, lo = h[i - 20:i].max(), l[i - 20:i].min(); mid = (hi + lo) / 2
        up, dn = h[i] >= hi, l[i] <= lo
        if not (up or dn):
            continue
        sg = 1 if up else -1
        en = max(hi, o[i]) if sg > 0 else min(lo, o[i]); sl = mid; risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        if (up and dn) or ((l[i] <= sl) if sg > 0 else (h[i] >= sl)):
            ex = sl
        else:
            ex = B.walk(b, i + 1, sg, en, sl, None, 6)
        busy = i + 6
        out.append((int(t[i]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1109(g, s):
    gd, sd = B.resample(g, 86400), B.resample(s, 86400); a = B.atr(gd)
    gmap = {int(x) // 86400: k for k, x in enumerate(gd["t"])}; out = []; busy_until = -1
    for k in range(21, len(sd["c"]) - 1):
        sg = 1 if sd["c"][k] > sd["c"][k - 20:k].max() else (-1 if sd["c"][k] < sd["c"][k - 20:k].min() else 0)
        if not sg:
            continue
        i = gmap.get(int(sd["t"][k]) // 86400)
        if i is None or i + 1 >= len(gd["c"]) or np.isnan(a[i]) or a[i] <= 0 or int(gd["t"][i + 1]) <= busy_until:
            continue
        ei = i + 1; en = gd["o"][ei]; risk = 1.5 * a[i]
        ex = L5.hold(gd, ei, 5, sg, en, en - sg * risk)
        out.append((int(gd["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); busy_until = int(gd["t"][min(len(gd["t"]) - 1, ei + 4)])
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    sA, sB = L.h1("xau/sig/duka_h1_xagusd/", 2005, 2014), L.h1("xau/sig/duka_h1_xagusd/", 2015, 2026)
    out = ["# Duka H1 長歷史第六批（IDEAS #1106–#1109）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；冇未來函數", ""]
    for name, fn, na, nb in (("#1106 週收市強弱動量", r1106, 150, 150), ("#1107 上季高／低突破", r1107, 20, 20),
                             ("#1108 H4 Donchian 20 突破", r1108, 300, 300), ("#1109 白銀 20 日新高／低 → 跟住做金", r1109, 100, 100)):
        ta, tb = fn(gA, sA), fn(gB, sB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                f"- 做多／做空 A：{A.fmt(A.stats([x[2] for x in ta if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in ta if x[1] < 0]))}",
                f"- 做多／做空 B：{A.fmt(A.stats([x[2] for x in tb if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tb if x[1] < 0]))}",
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB6.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
