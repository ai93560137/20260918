"""[IDEAS #1099–#1102] Duka H1 長歷史第四批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。冇未來函數（同 h1_lab3.trade_break）。
規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1099 前日高／低突破（兩邊）：今日第一次穿前日高 → 做多（低 → 做空），SL 前日中位，當日最後一根收市走；
#1100 同 #1099，但只做 D1 趨勢方向（前日收市高過 SMA100 只做多；低過只做空）；
#1101 D1 趨勢內回踩 EMA20：前日收市高過 SMA100、今日低位掂到前日 EMA20（掛單價＝EMA20）→ 做多，SL 入場下 1.5×ATR、TP 2×ATR、5 日收（下跌相反）；
#1102 10 日高／低突破：第一次穿前 10 日高 → 做多（低 → 做空），SL 10 日中位，5 個交易日收。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab4.py → research/strategy_search/H1_LAB4.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402
import h1_lab3 as L3            # noqa: E402
import batch_1023 as B23        # noqa: E402

B, A = L.B, L.A
COST = 0.5


def day_segs(g):
    return L3.segs(g["t"] // 86400)


def r1099(g, trend=False):
    d = B.resample(g, 86400); s100 = B.sma(d["c"], 100); ds = day_segs(g); out = []
    dk = {int(x) // 86400: k for k, x in enumerate(d["t"])}
    for (ps, pe), (s, e) in zip(ds[:-1], ds[1:]):
        hi, lo = g["h"][ps:pe].max(), g["l"][ps:pe].min(); mid = (hi + lo) / 2
        k = dk.get(int(g["t"][ps]) // 86400)
        if trend:
            if k is None or np.isnan(s100[k]):
                continue
            up = d["c"][k] > s100[k]
            hi2, lo2 = (hi, -1e18) if up else (1e18, lo)
        else:
            hi2, lo2 = hi, lo
        x = L3.trade_break(g, s, e, hi2, lo2, lambda sg: mid, None, lambda j: True)
        if x:
            out.append(x)
    return out


def r1100(g):
    return r1099(g, trend=True)


def r1101(g):
    d = B.resample(g, 86400); c = d["c"]; s100 = B.sma(c, 100); e20 = B23.ema(c, 20); a = B.atr(d)
    ds = day_segs(g); dk = {int(x) // 86400: k for k, x in enumerate(d["t"])}; out = []; busy_until = -1
    for idx, ((ps, pe), (s, e)) in enumerate(zip(ds[:-1], ds[1:])):
        k = dk.get(int(g["t"][ps]) // 86400)
        if k is None or np.isnan(s100[k]) or np.isnan(a[k]) or int(g["t"][s]) < busy_until:
            continue
        sg = 1 if c[k] > s100[k] else -1; lvl = e20[k]
        for j in range(s, e):
            hit = (g["l"][j] <= lvl) if sg > 0 else (g["h"][j] >= lvl)
            if not hit:
                continue
            en = min(lvl, g["o"][j]) if sg > 0 else max(lvl, g["o"][j]); risk = 1.5 * a[k]; sl = en - sg * risk; tp = en + sg * 2 * a[k]
            end = min(len(g["t"]), int(np.searchsorted(g["t"], g["t"][s] + 5 * 86400)))
            ex = None
            if (g["l"][j] <= sl) if sg > 0 else (g["h"][j] >= sl):
                ex = sl
            else:
                for q in range(j + 1, end):
                    if (g["l"][q] <= sl) if sg > 0 else (g["h"][q] >= sl):
                        ex = sl; break
                    if (g["h"][q] >= tp) if sg > 0 else (g["l"][q] <= tp):
                        ex = tp; break
            if ex is None:
                ex = g["c"][end - 1]
            out.append((int(g["t"][j]), sg, (sg * (ex - en) - COST) / risk)); busy_until = int(g["t"][end - 1])
            break
    return out


def r1102(g):
    ds = day_segs(g); out = []; busy_until = -1
    for i in range(10, len(ds)):
        s, e = ds[i]
        if int(g["t"][s]) < busy_until:
            continue
        a0 = ds[i - 10][0]; b0 = ds[i - 1][1]
        hi, lo = g["h"][a0:b0].max(), g["l"][a0:b0].min(); mid = (hi + lo) / 2
        end = ds[min(len(ds) - 1, i + 4)][1]
        x = L3.trade_break(g, s, end, hi, lo, lambda sg: mid, None, lambda j, e=e: j < e)
        if x:
            out.append(x); busy_until = int(g["t"][end - 1])
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    out = ["# Duka H1 長歷史第四批（IDEAS #1099–#1102）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；冇未來函數", ""]
    for name, fn, na, nb in (("#1099 前日高／低突破（SL 前日中位；收市走）", r1099, 500, 500), ("#1100 前日高／低突破只做 D1 趨勢方向", r1100, 300, 300),
                             ("#1101 D1 趨勢內回踩 EMA20", r1101, 100, 100), ("#1102 10 日高／低突破（SL 中位；5 日）", r1102, 100, 100)):
        ta, tb = fn(gA), fn(gB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                f"- 做多／做空 A：{A.fmt(A.stats([x[2] for x in ta if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in ta if x[1] < 0]))}",
                f"- 做多／做空 B：{A.fmt(A.stats([x[2] for x in tb if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tb if x[1] < 0]))}",
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB4.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
