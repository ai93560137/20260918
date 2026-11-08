"""[IDEAS #1015–#1018] 一批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1015 倫敦突破亞洲區間（順勢）；#1016 25 美元關口（…25／…75，唔包 50 關口）第一次觸及 E6S4 反向；
#1017 rev60：前 60 根走幅 ≥ 8 美元反向 E6S4（冷卻 120 分鐘）；#1018 亞洲時段做多（00:00 開市入、06:59 收市走、SL 8 美元）。
共同成功標準（每條獨立判）：① Duka n≥200、平均≥+0.10R、PF≥1.15；② Duka 8 年≥5 年正數；③ MT5 n≥100、平均≥+0.05R、PF≥1.10。
用法：python3 research/strategy_search/batch_1015.py → research/strategy_search/BATCH_1015.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import ai_entry_forward as af   # noqa: E402

fr = af.fr
COST = 0.5


def days(t):
    day = t // 86400
    st = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    return zip(st[:-1], st[1:])


def r1015(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    hour = (t // 3600) % 24
    out = []
    for s, e in days(t):
        hh = hour[s:e]
        ai = np.nonzero(hh < 7)[0] + s
        if len(ai) < 300:
            continue
        ah, al = h[ai].max(), l[ai].min()
        if not (2.0 <= ah - al <= 40.0):
            continue
        tr = None
        for j in range(ai[-1] + 1, e - 1):
            if hour[j] >= 12:
                break
            if c[j] > ah + 0.5:
                tr = (1, j + 1); break
            if c[j] < al - 0.5:
                tr = (-1, j + 1); break
        if tr is None:
            continue
        sg, ei = tr
        en = o[ei]; sl = (ah + al) / 2; risk = (en - sl) * sg
        if risk <= 0:
            continue
        tp = en + sg * 2 * risk; ex = None
        for j in range(ei, e):
            if hour[j] >= 20:
                ex = o[j]; break
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if sg > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        out.append((int(t[ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1016(d):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    day = t // 86400; hour = (t // 3600) % 24
    out, used = [], set()
    for i in range(1, len(t)):
        if not (1 <= hour[i] < 20):
            continue
        pc = c[i - 1]
        up = np.floor((pc - 25) / 50) * 50 + 75            # 上面最近 …25／…75
        dn = np.ceil((pc - 25) / 50) * 50 - 25             # 下面最近
        for sg, lvl, ht in ((-1, up, h[i] >= up), (1, dn, l[i] <= dn)):
            key = (int(day[i]), sg, lvl)
            if not ht or key in used:
                continue
            used.add(key)
            mid = lvl - sg * 6.0
            side = "BUY" if sg > 0 else "SELL"
            r = af.sim(d, int(t[i]) + 60, side, mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
            if r is not None:
                out.append((int(t[i]), sg, r))
    return out


def r1017(d):
    t, o, c = d["t"], d["o"], d["c"]
    n = len(t)
    mv = np.full(n, np.nan); mv[60:] = c[60:] - o[:-60]
    ok = (np.abs(mv) >= 8.0) & (np.arange(n) >= 74)
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 120, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), 6.0, 2.0, 4.0, 1.0)
    return [(int(t[i]) + 60, 1 if s == "BUY" else -1, float(x)) for (i, s), x in zip(sigs, r) if not np.isnan(x)]


def r1018(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    out = []
    for s, e in days(t):
        if t[s] % 86400 >= 300:                              # 要 00:00–00:04 有第一根
            continue
        en = o[s]; sl = en - 8.0; ex = None; last = s
        for j in range(s, e):
            if (t[j] % 86400) >= 7 * 3600:
                break
            last = j
            if l[j] <= sl:
                ex = sl; break
        if ex is None:
            ex = c[last]
        out.append((int(t[s]), 1, (ex - en - COST) / 8.0))
    return out


RULES = [("#1015 倫敦突破亞洲區間（順勢，SL 亞洲中位，TP 2R）", r1015),
         ("#1016 25 美元關口（…25／…75）E6S4 反向", r1016),
         ("#1017 rev60（60 分鐘走 ≥8 美元反向，E6S4，冷卻 120 分鐘）", r1017),
         ("#1018 亞洲時段做多（00:00→06:59 UTC，SL 8 美元）", r1018)]


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 一批四條規則（IDEAS #1015–#1018）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn in RULES:
        td, tm = fn(duka), fn(mt5)
        sd, sm = A.stats([x[2] for x in td]), A.stats([x[2] for x in tm])
        yd = A.by_year(td)
        pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
        ok = {"①Duka n≥200、平均≥+0.10R、PF≥1.15": sd["n"] >= 200 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
              "②Duka 8年≥5年正數": pos >= 5,
              "③MT5 n≥100、平均≥+0.05R、PF≥1.10": sm["n"] >= 100 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
        out += [f"## {name}", "", f"- Dukascopy 2015–2022：{A.fmt(sd)}", f"- MT5 2023-01→2026-10：{A.fmt(sm)}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**yd, **A.by_year(tm)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1015.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
