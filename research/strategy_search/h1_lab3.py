"""[IDEAS #1096–#1098] Duka H1 長歷史第三批（A＝2005–2014、B＝2015–2026-10，兩段都要過）。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
冇未來函數：突破用掛單價入（穿咗先成交），同一根 H1 掂埋 SL 當 SL（保守），之後由下一根先查 TP。
#1096 上週高／低突破（星期二至四）：今週第一次穿上週高 → 做多（穿上週低 → 做空），SL 上週中位，週五最後一根收市走；
#1097 星期一區間突破：星期二至四第一次穿星期一高 → 做多（穿低 → 做空），SL 星期一區間另一邊，TP 2R，週五收市走；
#1098 上月高／低突破：今月第一次穿上月高 → 做多（穿上月低 → 做空），SL 上月中位，月尾收市走。
每張扣 0.5 美元；每段（週／月）最多一張。
用法：python3 research/strategy_search/h1_lab3.py → research/strategy_search/H1_LAB3.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402

B, A = L.B, L.A
COST = 0.5
MIN_RISK = 0.5        # 黃金美元下限；跨品種（panel_1251）按 ATR 比例改


def segs(keys):
    st = np.r_[0, np.nonzero(np.diff(keys))[0] + 1, len(keys)]
    return list(zip(st[:-1], st[1:]))


def trade_break(g, s, e, hi, lo, sl_fn, tp_mult, allow):
    o, h, l, c, t = g["o"], g["h"], g["l"], g["c"], g["t"]
    for j in range(s, e):
        if not allow(j):
            continue
        up, dn = h[j] >= hi, l[j] <= lo
        if not (up or dn):
            continue
        if up and dn:                                         # 唔知先後：保守當做多再止蝕
            sg = 1
        else:
            sg = 1 if up else -1
        en = max(hi, o[j]) if sg > 0 else min(lo, o[j]); sl = sl_fn(sg); risk = (en - sl) * sg
        if risk <= MIN_RISK:
            return None
        if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
            return (int(t[j]), sg, (sg * (sl - en) - COST) / risk)
        tp = None if tp_mult is None else en + sg * tp_mult * risk; ex = None
        for k in range(j + 1, e):
            if (l[k] <= sl) if sg > 0 else (h[k] >= sl):
                ex = sl; break
            if tp is not None and ((h[k] >= tp) if sg > 0 else (l[k] <= tp)):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        return (int(t[j]), sg, (sg * (ex - en) - COST) / risk)
    return None


def wkey(t):
    return (t // 86400 + 3) // 7


def wday(t):
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).weekday()


def r1096(g):
    t, h, l = g["t"], g["h"], g["l"]; ss = segs(np.array([wkey(x) for x in t])); out = []
    for (ps, pe), (s, e) in zip(ss[:-1], ss[1:]):
        hi, lo = h[ps:pe].max(), l[ps:pe].min(); mid = (hi + lo) / 2
        x = trade_break(g, s, e, hi, lo, lambda sg: mid, None, lambda j: wday(t[j]) in (1, 2, 3))
        if x:
            out.append(x)
    return out


def r1097(g):
    t, h, l = g["t"], g["h"], g["l"]; out = []
    for s, e in segs(np.array([wkey(x) for x in t])):
        mon = [j for j in range(s, e) if wday(t[j]) == 0]
        if len(mon) < 12:
            continue
        hi, lo = h[mon].max(), l[mon].min()
        x = trade_break(g, mon[-1] + 1, e, hi, lo, lambda sg: lo if sg > 0 else hi, 2.0, lambda j: wday(t[j]) in (1, 2, 3))
        if x:
            out.append(x)
    return out


def r1098(g):
    t, h, l = g["t"], g["h"], g["l"]
    mk = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year * 12 + dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in t])
    ss = segs(mk); out = []
    for (ps, pe), (s, e) in zip(ss[:-1], ss[1:]):
        hi, lo = h[ps:pe].max(), l[ps:pe].min(); mid = (hi + lo) / 2
        x = trade_break(g, s, e, hi, lo, lambda sg: mid, None, lambda j: True)
        if x:
            out.append(x)
    return out


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    out = ["# Duka H1 長歷史第三批（IDEAS #1096–#1098）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A＝2005–2014、B＝2015–2026-10；每張扣 0.5 美元；冇未來函數（掛單價入、同根掂 SL 當 SL）", ""]
    for name, fn, na, nb in (("#1096 上週高／低突破（星期二至四；SL 上週中位；週五收）", r1096, 150, 150),
                             ("#1097 星期一區間突破（星期二至四；SL 另一邊；TP 2R；週五收）", r1097, 150, 150),
                             ("#1098 上月高／低突破（SL 上月中位；月尾收）", r1098, 40, 40)):
        ta, tb = fn(gA), fn(gB)
        ok, sa, sb, ya, pos, ny = L.judge_ab(ta, tb, na, nb)
        out += [f"## {name}", "", f"- A 2005–2014：{A.fmt(sa)}；正數年份 {pos}／{ny}", f"- B 2015–2026：{A.fmt(sb)}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**ya, **A.by_year(tb)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "H1_LAB3.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
