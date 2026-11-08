"""[IDEAS #1008] 亞洲區間被倫敦開市「掃一掃」之後收返入區 → 反向做（規則全部固定，冇網格、冇擬合）。
規格、成功標準以 IDEAS #1008 預先登記為準（跑之前 commit）。數據：Dukascopy M1 2015–2022（主判）＋券商 MT5 M1 2023-01→2026-10（確認）。
用法：python3 research/strategy_search/asia_sweep.py → research/strategy_search/ASIA_SWEEP.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))

COST = 0.5
SWEEP = 0.5          # 掃過亞洲高／低至少幾多美元
RECLAIM_MIN = 30     # 掃完之後幾多分鐘內要收返入區
SL_BUF = 1.0         # 止蝕：掃嘅極端外 1 美元
RANGE = (2.0, 40.0)  # 亞洲區間闊度（美元）
ASIA = (0, 7)        # 00:00–06:59 UTC
LONDON = (7, 12)     # 07:00–11:59 UTC 先接受訊號
TIME_STOP = 16       # 16:00 UTC 未完就收


def load(src, a, b):
    sys.argv = [sys.argv[0], "--src", src]
    import rev15_history as rh
    rh.SRC = src
    rh.A, rh.B, rh.CACHE = a, b, f"/tmp/rev15_history_{src}_{a}_{b}.npz"
    return rh.load()


def run(d, scaled=False):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    day = t // 86400
    hour = (t // 3600) % 24
    out = []
    starts = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    for s, e in zip(starts[:-1], starts[1:]):
        hh = hour[s:e]
        ai = np.nonzero((hh >= ASIA[0]) & (hh < ASIA[1]))[0] + s
        if len(ai) < 300:
            continue
        ah, al = h[ai].max(), l[ai].min()
        rng = ah - al
        k = c[ai[-1]] / 4000.0 if scaled else 1.0               # 縮放版：所有美元參數 × 價格／4000
        if not (RANGE[0] * k <= rng <= RANGE[1] * k):
            continue
        li = np.nonzero((hh >= LONDON[0]) & (hh < LONDON[1]))[0] + s
        if not len(li):
            continue
        trade = None
        up_i = dn_i = None
        for j in range(li[0], e - 1):
            if hour[j] >= LONDON[1] and up_i is None and dn_i is None:
                break
            if up_i is None and h[j] >= ah + SWEEP * k and hour[j] < LONDON[1]:
                up_i = j
            if dn_i is None and l[j] <= al - SWEEP * k and hour[j] < LONDON[1]:
                dn_i = j
            if up_i is not None and j > up_i and j - up_i <= RECLAIM_MIN and c[j] < ah:
                ext = h[up_i:j + 1].max()
                trade = (-1, j + 1, ext + SL_BUF * k); break
            if dn_i is not None and j > dn_i and j - dn_i <= RECLAIM_MIN and c[j] > al:
                ext = l[dn_i:j + 1].min()
                trade = (1, j + 1, ext - SL_BUF * k); break
            if up_i is not None and j - up_i > RECLAIM_MIN:
                up_i = None if hour[j] < LONDON[1] else up_i
            if dn_i is not None and j - dn_i > RECLAIM_MIN:
                dn_i = None if hour[j] < LONDON[1] else dn_i
        if trade is None:
            continue
        sg, ei, sl = trade
        if ei >= e:
            continue
        en = o[ei]; tp = (ah + al) / 2.0; risk = (en - sl) * sg
        if risk <= 0 or (tp - en) * sg <= 0:
            continue
        ex = None
        for j in range(ei, e):
            if hour[j] >= TIME_STOP:
                ex = o[j]; break
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if sg > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            continue
        out.append((int(t[ei]), sg, (sg * (ex - en) - COST * k) / risk))
    return out


def stats(r):
    r = np.array(r, float)
    if not len(r):
        return {"n": 0}
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    s = mx = 0
    for x in r:
        s = s + 1 if x < 0 else 0; mx = max(mx, s)
    return {"n": len(r), "avg": r.mean(), "pf": w / ls if ls else float("inf"), "sum": r.sum(), "streak": mx, "win": (r > 0).mean()}


def fmt(s):
    return "n=0" if not s["n"] else f"n={s['n']} 平均 {s['avg']:+.3f}R ΣR {s['sum']:+.1f} PF {s['pf']:.2f} 勝率 {s['win']:.0%} 連敗 {s['streak']}"


def by_year(tr):
    ys = {}
    for ts, sg, r in tr:
        ys.setdefault(dt.datetime.fromtimestamp(ts, dt.timezone.utc).year, []).append(r)
    return {y: stats(v) for y, v in sorted(ys.items())}


def main():
    duka = load("duka", "2015-01-01", "2022-12-31")
    tr_d = run(duka); tr_ds = run(duka, scaled=True)
    mt5 = load("mt5", "2023-01-01", "2026-10-30")
    tr_m = run(mt5); tr_ms = run(mt5, scaled=True)
    sd, sm = stats([x[2] for x in tr_d]), stats([x[2] for x in tr_m])
    yd = by_year(tr_d)
    out = ["# 亞洲區間被掃後收返入區反向（IDEAS #1008）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；規則固定：亞洲 00–07 UTC 高低（闊 2–40 美元）；07–12 UTC 掃過 ≥0.5 美元、30 分鐘內收返入區 → 下一根開市反向；"
           "SL 掃嘅極端外 1 美元；TP 亞洲中位；16:00 UTC 未完收；每日最多一張；每張扣 0.5 美元", "",
           "| 數據 | 固定美元（主判） | 按價格縮放（描述） | 做多 | 做空 |", "|---|---|---|---|---|",
           f"| Dukascopy 2015–2022 | {fmt(sd)} | {fmt(stats([x[2] for x in tr_ds]))} | {fmt(stats([x[2] for x in tr_d if x[1] > 0]))} | {fmt(stats([x[2] for x in tr_d if x[1] < 0]))} |",
           f"| MT5 2023-01→2026-10 | {fmt(sm)} | {fmt(stats([x[2] for x in tr_ms]))} | {fmt(stats([x[2] for x in tr_m if x[1] > 0]))} | {fmt(stats([x[2] for x in tr_m if x[1] < 0]))} |",
           "", "## 每年（固定美元）", ""] + [f"- {y}：{fmt(v)}" for y, v in {**yd, **by_year(tr_m)}.items()]
    pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
    ok = {"①Duka n≥300、平均≥+0.10R、PF≥1.15": sd["n"] >= 300 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
          "②Duka 8年≥5年正數": pos >= 5,
          "③MT5 平均≥+0.05R、PF≥1.10": sm["n"] > 0 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
    out += ["", "## 判（預先登記 IDEAS #1008）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], f"- Duka 正數年份 {pos}／{len(yd)}",
            "- " + ("✅ 達標 → 提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "ASIA_SWEEP.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
