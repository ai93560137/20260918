"""[IDEAS #1033–#1036] 第五批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1033 rev15 E6S4 只做順 D1 趨勢（前一日收市對 SMA50）嘅方向；#1034 倫敦收市反向（07:00→15:59 走 ≥ 15 美元，16:00 反向，SL＝TP＝0.4×走幅，20:00 收）；
#1035 M15 大陽／大陰燭順勢（幅 ≥ 2.5×ATR、實體 ≥ 70%；SL 燭中位、TP 1R、8 根）；#1036 W1 4 週收市突破順勢（SL 1×ATR10(W1)、TP 2R、4 週）。
成本每張 0.5 美元；一次一張。成功見 IDEAS（#1033 另要高過 rev15 全部 ≥ +0.03R）。
用法：python3 research/strategy_search/batch_1033.py → research/strategy_search/BATCH_1033.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import combo_1027 as C          # noqa: E402

A = B.A
COST = 0.5


def d1_trend(d):
    dd = B.resample(d, 86400); s50 = B.sma(dd["c"], 50)
    return {int(t) // 86400: (1 if dd["c"][k] > s50[k] else -1) for k, t in enumerate(dd["t"]) if not np.isnan(s50[k])}


def r1033(d):
    tr = C.rev15(d); tm = d1_trend(d)
    return [x for x in tr if tm.get(x[0] // 86400 - 1) == x[1]], tr


def r1034(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    sod = t % 86400; day = t // 86400; out = []
    st = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    for s, e in zip(st[:-1], st[1:]):
        a = np.nonzero(sod[s:e] == 7 * 3600)[0]; b = np.nonzero(sod[s:e] == 16 * 3600)[0]
        if not len(a) or not len(b):
            continue
        ia, ib = a[0] + s, b[0] + s
        mv = c[ib - 1] - o[ia]
        if abs(mv) < 15:
            continue
        sg = -1 if mv > 0 else 1; en = o[ib]; dist = 0.4 * abs(mv)
        sl, tp = en - sg * dist, en + sg * dist; ex = None
        for j in range(ib, e):
            if sod[j] >= 20 * 3600:
                ex = o[j]; break
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if sg > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        out.append((int(t[ib]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1035(d):
    b = B.resample(d, 900); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; a = B.atr(b)
    out, busy = [], -1
    for i in range(15, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        rg = h[i] - l[i]; body = c[i] - o[i]
        if rg < 2.5 * a[i] or abs(body) < 0.7 * rg:
            continue
        sg = 1 if body > 0 else -1
        ei = i + 1; en = o[ei]; sl = (h[i] + l[i]) / 2; risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 8)
        busy = ei + 7
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def weekly(d):
    k = (d["t"] // 86400 + 3) // 7
    st = np.r_[0, np.nonzero(np.diff(k))[0] + 1]; en = np.r_[st[1:], len(k)]
    return {"t": d["t"][st], "o": d["o"][st], "h": np.maximum.reduceat(d["h"], st), "l": np.minimum.reduceat(d["l"], st), "c": d["c"][en - 1]}


def r1036(d):
    b = weekly(d); c = b["c"]; a = B.atr(b, 10)
    out, busy = [], -1
    for i in range(12, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        sg = 1 if c[i] > c[i - 4:i].max() else (-1 if c[i] < c[i - 4:i].min() else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = a[i]
        ex = B.walk(b, ei, sg, en, en - sg * risk, en + sg * 2 * risk, 4)
        busy = ei + 3
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def judge(td, tm, n1, n2):
    sd, sm = A.stats([x[2] for x in td]), A.stats([x[2] for x in tm])
    yd = A.by_year(td); pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
    ok = {f"①Duka n≥{n1}、平均≥+0.10R、PF≥1.15": sd["n"] >= n1 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
          "②Duka 有交易年份 ≥5／8 正數": pos >= 5,
          f"③MT5 n≥{n2}、平均≥+0.05R、PF≥1.10": sm["n"] >= n2 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
    lines = [f"- Dukascopy 2015–2022：{A.fmt(sd)}", f"- MT5 2023-01→2026-10：{A.fmt(sm)}",
             "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**yd, **A.by_year(tm)}.items() if v["n"])]
    return ok, lines, sd, sm


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第五批四條規則（IDEAS #1033–#1036）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    (fd, ad), (fm, am) = r1033(duka), r1033(mt5)
    ok, lines, sd, sm = judge(fd, fm, 300, 150)
    bd, bm = A.stats([x[2] for x in ad]), A.stats([x[2] for x in am])
    ok["④Duka 高過 rev15 全部 ≥ +0.03R"] = sd["n"] > 0 and sd["avg"] - bd["avg"] >= 0.03
    ok["⑤MT5 高過 rev15 全部 ≥ +0.03R"] = sm["n"] > 0 and sm["avg"] - bm["avg"] >= 0.03
    out += ["## #1033 rev15 E6S4 只做順 D1 SMA50 方向", "", *lines, f"- 對照 rev15 全部：Duka {A.fmt(bd)}；MT5 {A.fmt(bm)}",
            *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    for name, fn, n1, n2 in (("#1034 倫敦收市反向（走 ≥ 15 美元；SL＝TP＝0.4×走幅；20:00 收）", r1034, 100, 60),
                             ("#1035 M15 大燭順勢（≥ 2.5×ATR、實體 ≥ 70%；SL 燭中位；TP 1R；8 根）", r1035, 300, 150),
                             ("#1036 W1 4 週收市突破順勢（SL 1×ATR10；TP 2R；4 週）", r1036, 40, 20)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1033.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
