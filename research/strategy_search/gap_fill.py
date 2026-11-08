"""[IDEAS #1014] 開市跳空回補：每日休市（含週末）之後開市，開市價同休市前收市相差 ≥ 3 美元 → 開市後第 6 根 M1 開市價反向入，
TP＝休市前收市（補晒個缺口），SL＝入場再向跳空方向推「入場到 TP 嘅距離」（1:1），12 小時未完用收市平。規則固定、冇網格。
休市定義：兩根 M1 相隔 ≥ 45 分鐘，而且休市前最後一根喺 20:00–23:59 UTC（剔走數據洞）。
入場時已經補咗（第 6 根開市已經越過休市前收市）或者入場到 TP 距離 < 2 美元 → 唔做。每張扣 1.0 美元（開市點差闊，保守）。
規格、成功標準以 IDEAS #1014 預先登記為準（跑之前 commit）。
用法：python3 research/strategy_search/gap_fill.py → research/strategy_search/GAP_FILL.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402

GAP_MIN, BREAK_SEC, ENTRY_BAR, MIN_D, COST, TIME_STOP = 3.0, 45 * 60, 5, 2.0, 1.0, 12 * 3600


def run(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    out = []
    brk = np.nonzero(np.diff(t) >= BREAK_SEC)[0] + 1          # 開市第一根
    for s in brk:
        if not (20 <= (t[s - 1] // 3600) % 24 <= 23):
            continue
        pc = c[s - 1]; gap = o[s] - pc
        if abs(gap) < GAP_MIN:
            continue
        ei = s + ENTRY_BAR
        if ei >= len(t) or t[ei] - t[s] > 3600:
            continue
        sg = -1 if gap > 0 else 1                               # 向上跳 → 做空補返落去
        en = o[ei]
        dist = (pc - en) * sg
        if dist < MIN_D:
            continue
        tp, sl = pc, en - sg * dist
        ex = None; last = ei
        for j in range(ei, len(t)):
            if t[j] - t[ei] > TIME_STOP:
                break
            last = j
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if sg > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            ex = c[last]
        wk = (t[s] - t[s - 1]) > 24 * 3600
        out.append((int(t[ei]), sg, (sg * (ex - en) - COST) / dist, wk, abs(gap)))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    tr_d, tr_m = run(duka), run(mt5)
    sd, sm = A.stats([x[2] for x in tr_d]), A.stats([x[2] for x in tr_m])
    yd = A.by_year([(x[0], x[1], x[2]) for x in tr_d])
    sub = lambda tr, f: A.fmt(A.stats([x[2] for x in tr if f(x)]))
    out = ["# 開市跳空回補（IDEAS #1014）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；休市 ≥45 分鐘（休市前 20–23 UTC）；跳空 ≥3 美元；開市後第 6 根開市價反向；"
           "TP 休市前收市、SL 1:1、12 小時時間止；每張扣 1.0 美元", "",
           "| 數據 | 全部（主判） | 週末跳空 | 每日跳空 | 跳空 ≥6 美元 |", "|---|---|---|---|---|"]
    for name, tr, st in (("Dukascopy 2015–2022", tr_d, sd), ("MT5 2023-01→2026-10", tr_m, sm)):
        out.append(f"| {name} | {A.fmt(st)} | {sub(tr, lambda x: x[3])} | {sub(tr, lambda x: not x[3])} | {sub(tr, lambda x: x[4] >= 6)} |")
    out += ["", "## 每年", ""] + [f"- {y}：{A.fmt(v)}" for y, v in {**yd, **A.by_year([(x[0], x[1], x[2]) for x in tr_m])}.items()]
    pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
    ok = {"①Duka n≥60、平均≥+0.10R、PF≥1.2": sd["n"] >= 60 and sd["avg"] >= 0.10 and sd["pf"] >= 1.2,
          "②Duka 有交易嘅年份 ≥ 一半正數": pos * 2 >= sum(1 for v in yd.values() if v["n"]),
          "③MT5 n≥60、平均≥+0.05R、PF≥1.1": sm["n"] >= 60 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
    out += ["", "## 判（預先登記 IDEAS #1014）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], f"- Duka 正數年份 {pos}／{len(yd)}",
            "- " + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改門檻再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "GAP_FILL.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
