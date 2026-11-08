"""[IDEAS #1110–#1113] Duka H1 長歷史第七批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。冇未來函數。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1110 週內買回調：星期一收市高過上週收市（＝本週向上）→ 星期二至四第一次跌到星期一低位（掛單價）買，SL 入場下 1×ATR14(D1)，週尾收市走（向下相反）；
#1111 D1 5 日新高動量（順 SMA50）：收市係 5 日最高收市而高過 SMA50 → 翌日開市買，5 日收，SL 1.5×ATR（反之沽）；
#1112 週高低過衝反向：今週價位超過上週高 + 1×ATR14(D1)（掛單價）→ 做空，TP 上週高，SL 入場上 1×ATR，週尾收市走（低位相反）；
#1113 低波幅 20 日突破：ATR14(D1) 喺過去 250 日最低 20%（前一日計）→ 今日穿前 20 日高（掛單價）做多（低 → 做空），SL 20 日中位，10 日收。
每張扣 0.5 美元；一次一張。
用法：python3 research/strategy_search/h1_lab7.py → research/strategy_search/H1_LAB7.md"""
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


def limit_trade(g, s, e, lvl, sg, sl_dist, tp, allow):
    """掛單價 lvl（做多＝跌到 lvl 先買）；同根掂 SL 當 SL；由下一根查 TP；e 收市走。"""
    o, h, l, c, t = g["o"], g["h"], g["l"], g["c"], g["t"]
    for j in range(s, e):
        if not allow(j):
            continue
        hit = (l[j] <= lvl) if sg > 0 else (h[j] >= lvl)
        if not hit:
            continue
        en = min(lvl, o[j]) if sg > 0 else max(lvl, o[j]); sl = en - sg * sl_dist
        if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
            return (int(t[j]), sg, (sg * (sl - en) - COST) / sl_dist)
        ex = None
        for k in range(j + 1, e):
            if (l[k] <= sl) if sg > 0 else (h[k] >= sl):
                ex = sl; break
            if tp is not None and ((h[k] >= tp) if sg > 0 else (l[k] <= tp)):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        return (int(t[j]), sg, (sg * (ex - en) - COST) / sl_dist)
    return None


def datr(g):
    d = B.resample(g, 86400); a = B.atr(d)
    return {int(x) // 86400: a[k] for k, x in enumerate(d["t"])}


def r1110(g):
    t = g["t"]; am = datr(g); ss = L3.segs(np.array([L3.wkey(int(x)) for x in t])); out = []
    for (ps, pe), (s, e) in zip(ss[:-1], ss[1:]):
        mon = [j for j in range(s, e) if L3.wday(t[j]) == 0]
        if len(mon) < 12:
            continue
        up = g["c"][mon[-1]] > g["c"][pe - 1]; sg = 1 if up else -1
        lvl = g["l"][mon].min() if up else g["h"][mon].max()
        a = am.get(int(t[mon[-1]]) // 86400)
        if a is None or np.isnan(a) or a <= 0:
            continue
        x = limit_trade(g, mon[-1] + 1, e, lvl, sg, a, None, lambda j: L3.wday(t[j]) in (1, 2, 3))
        if x:
            out.append(x)
    return out


def r1111(g):
    d = B.resample(g, 86400); c = d["c"]; a = B.atr(d); s50 = B.sma(c, 50); out, i = [], 51
    while i < len(c) - 1:
        if np.isnan(a[i]) or a[i] <= 0 or np.isnan(s50[i]):
            i += 1; continue
        sg = 1 if (c[i] >= c[i - 4:i + 1].max() and c[i] > s50[i]) else (-1 if (c[i] <= c[i - 4:i + 1].min() and c[i] < s50[i]) else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = d["o"][ei]; risk = 1.5 * a[i]
        ex = L5.hold(d, ei, 5, sg, en, en - sg * risk)
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - COST) / risk)); i = ei + 5
    return out


def r1112(g):
    t = g["t"]; am = datr(g); ss = L3.segs(np.array([L3.wkey(int(x)) for x in t])); out = []
    for (ps, pe), (s, e) in zip(ss[:-1], ss[1:]):
        hi, lo = g["h"][ps:pe].max(), g["l"][ps:pe].min()
        a = am.get(int(t[pe - 1]) // 86400)
        if a is None or np.isnan(a) or a <= 0:
            continue
        xs = limit_trade(g, s, e, hi + a, -1, a, hi, lambda j: True)
        xl = limit_trade(g, s, e, lo - a, 1, a, lo, lambda j: True)
        cand = [x for x in (xs, xl) if x]
        if cand:
            out.append(min(cand))
    return out


def r1113(g):
    d = B.resample(g, 86400); a = B.atr(d); dk = {int(x) // 86400: k for k, x in enumerate(d["t"])}
    ds = L3.segs(g["t"] // 86400); out = []; busy_until = -1
    for i in range(260, len(ds)):
        s, e = ds[i]
        if int(g["t"][s]) < busy_until:
            continue
        k = dk.get(int(g["t"][ds[i - 1][0]]) // 86400)
        if k is None or k < 251 or np.isnan(a[k]):
            continue
        w = a[k - 249:k + 1]
        if np.isnan(w).any() or a[k] > np.quantile(w, 0.2):
            continue
        a0, b0 = ds[i - 20][0], ds[i - 1][1]
        hi, lo = g["h"][a0:b0].max(), g["l"][a0:b0].min(); mid = (hi + lo) / 2
        end = ds[min(len(ds) - 1, i + 9)][1]
        x = L3.trade_break(g, s, end, hi, lo, lambda sg: mid, None, lambda j, e=e: j < e)
        if x:
            out.append(x); busy_until = int(g["t"][end - 1])
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    out = ["# Duka H1 長歷史第七批（IDEAS #1110–#1113）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；冇未來函數", ""]
    for name, fn, na, nb in (("#1110 週內買回調（本週向上買星期一低）", r1110, 150, 150), ("#1111 D1 5 日新高動量（順 SMA50）", r1111, 150, 150),
                             ("#1112 週高低過衝 1×ATR 反向", r1112, 60, 60), ("#1113 低波幅 20 日突破", r1113, 30, 30)):
        ta, tb = fn(gA), fn(gB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                f"- 做多／做空 A：{A.fmt(A.stats([x[2] for x in ta if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in ta if x[1] < 0]))}",
                f"- 做多／做空 B：{A.fmt(A.stats([x[2] for x in tb if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tb if x[1] < 0]))}",
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB7.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
