"""[IDEAS #1114–#1117] Duka H1 長歷史第八批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。冇未來函數。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1114 月初三日區間突破：每月頭 3 個交易日高低；之後第一次穿 → 順勢，SL 區間另一邊，月尾收市走；
#1115 內包月突破：上月高低都喺再上一個月之內 → 今月第一次穿上月高／低順勢，SL 上月中位，月尾收市走；
#1116 海龜系統 2：D1 收市穿前 55 日最高收市 → 翌日開市買，SL 2×ATR20(D1)，收市跌穿前 20 日最低收市走（做空相反），最多 120 日；
#1117 D1 保力加突破：收市高過 SMA20 + 2σ 而且帶寬（4σ／SMA）高過前一日 → 翌日開市買，SL SMA20，10 日收（相反做空）。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab8.py → research/strategy_search/H1_LAB8.md"""
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


def mkeys(t):
    return np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year * 12 + dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in t])


def r1114(g):
    t = g["t"]; out = []
    for s, e in L3.segs(mkeys(t)):
        days = L3.segs(t[s:e] // 86400)
        if len(days) < 6:
            continue
        b3 = s + days[2][1]
        hi, lo = g["h"][s:b3].max(), g["l"][s:b3].min()
        x = L3.trade_break(g, b3, e, hi, lo, lambda sg: lo if sg > 0 else hi, None, lambda j: True)
        if x:
            out.append(x)
    return out


def r1115(g):
    t = g["t"]; ss = L3.segs(mkeys(t)); out = []
    for (qs, qe), (ps, pe), (s, e) in zip(ss[:-2], ss[1:-1], ss[2:]):
        if not (g["h"][ps:pe].max() < g["h"][qs:qe].max() and g["l"][ps:pe].min() > g["l"][qs:qe].min()):
            continue
        hi, lo = g["h"][ps:pe].max(), g["l"][ps:pe].min(); mid = (hi + lo) / 2
        x = L3.trade_break(g, s, e, hi, lo, lambda sg: mid, None, lambda j: True)
        if x:
            out.append(x)
    return out


def r1116(g):
    d = B.resample(g, 86400); c = d["c"]; a = B.atr(d, 20); out, i = [], 56
    while i < len(c) - 1:
        if np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        sg = 1 if c[i] > c[i - 55:i].max() else (-1 if c[i] < c[i - 55:i].min() else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = d["o"][ei]; risk = 2 * a[i]; sl = en - sg * risk; ex = None; j = ei
        while j < min(len(c), ei + 120):
            if (d["l"][j] <= sl) if sg > 0 else (d["h"][j] >= sl):
                ex = sl; break
            if j >= 20 and ((c[j] < c[j - 20:j].min()) if sg > 0 else (c[j] > c[j - 20:j].max())):
                ex = c[j]; break
            j += 1
        if ex is None:
            j = min(len(c), ei + 120) - 1; ex = c[j]
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); i = j + 1
    return out


def r1117(g):
    d = B.resample(g, 86400); c = d["c"]; m = B.sma(c, 20)
    sd = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        sd[i] = c[i - 19:i + 1].std()
    bw = 4 * sd / m; out, i = [], 21
    while i < len(c) - 1:
        if np.isnan(bw[i]) or np.isnan(bw[i - 1]) or bw[i] <= bw[i - 1]:
            i += 1; continue
        sg = 1 if c[i] > m[i] + 2 * sd[i] else (-1 if c[i] < m[i] - 2 * sd[i] else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = d["o"][ei]; sl = m[i]; risk = (en - sl) * sg
        if risk <= 0.5:
            i += 1; continue
        ex = L5.hold(d, ei, 10, sg, en, sl)
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); i = ei + 10
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    out = ["# Duka H1 長歷史第八批（IDEAS #1114–#1117）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；冇未來函數", ""]
    for name, fn, na, nb in (("#1114 月初三日區間突破", r1114, 60, 60), ("#1115 內包月突破", r1115, 15, 15),
                             ("#1116 海龜系統 2（55 日突破、20 日出場）", r1116, 30, 30), ("#1117 D1 保力加突破（帶寬擴張）", r1117, 60, 60)):
        ta, tb = fn(gA), fn(gB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                f"- 做多／做空 A：{A.fmt(A.stats([x[2] for x in ta if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in ta if x[1] < 0]))}",
                f"- 做多／做空 B：{A.fmt(A.stats([x[2] for x in tb if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tb if x[1] < 0]))}",
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB8.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
