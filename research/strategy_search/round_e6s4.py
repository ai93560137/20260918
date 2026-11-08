"""[IDEAS #1011] 50 美元整數關口（…00、…50）當日第一次由下面（或上面）掂到 → E6S4 結構反向。
規格、成功標準以 IDEAS #1011 預先登記為準（跑之前 commit）。規則固定、冇網格。計法同 #1009（ai_entry_forward.sim）。
用法：python3 research/strategy_search/round_e6s4.py → research/strategy_search/ROUND_E6S4.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import ai_entry_forward as af   # noqa: E402

STEP = 50.0
HOURS = (1, 20)


def run(d):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    day = t // 86400; hour = (t // 3600) % 24
    out, used = [], set()
    for i in range(1, len(t)):
        if not (HOURS[0] <= hour[i] < HOURS[1]):
            continue
        pc = c[i - 1]
        up = np.floor(pc / STEP) * STEP + STEP            # 上面最近關口
        dn = np.ceil(pc / STEP) * STEP - STEP             # 下面最近關口
        for side, lvl, hit in (("SELL", up, h[i] >= up), ("BUY", dn, l[i] <= dn)):
            key = (int(day[i]), side, lvl)
            if not hit or key in used:
                continue
            used.add(key)
            sg = 1 if side == "BUY" else -1
            mid = lvl - sg * 6.0
            r = af.sim(d, int(t[i]) + 60, side, mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
            if r is not None:
                out.append((int(t[i]), sg, r))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    tr_d, tr_m = run(duka), run(mt5)
    sd, sm = A.stats([x[2] for x in tr_d]), A.stats([x[2] for x in tr_m])
    yd = A.by_year(tr_d)
    out = ["# 50 美元整數關口第一次觸及 → E6S4 反向（IDEAS #1011）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；01–20 UTC；每個關口每日每邊最多一次；入場區再過 6 ±2、SL 再過 4、TP 1R、30 分鐘有效；每張扣 0.5 美元", "",
           "| 數據 | 成績 | 做多（由上跌到關口） | 做空（由下升到關口） |", "|---|---|---|---|",
           f"| Dukascopy 2015–2022 | {A.fmt(sd)} | {A.fmt(A.stats([x[2] for x in tr_d if x[1] > 0]))} | {A.fmt(A.stats([x[2] for x in tr_d if x[1] < 0]))} |",
           f"| MT5 2023-01→2026-10 | {A.fmt(sm)} | {A.fmt(A.stats([x[2] for x in tr_m if x[1] > 0]))} | {A.fmt(A.stats([x[2] for x in tr_m if x[1] < 0]))} |",
           "", "## 每年", ""] + [f"- {y}：{A.fmt(v)}" for y, v in {**yd, **A.by_year(tr_m)}.items()]
    pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
    ok = {"①Duka n≥200、平均≥+0.10R、PF≥1.15": sd["n"] >= 200 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
          "②Duka 8年≥5年正數": pos >= 5,
          "③MT5 平均≥+0.05R、PF≥1.10": sm["n"] > 0 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
    out += ["", "## 判（預先登記 IDEAS #1011）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], f"- Duka 正數年份 {pos}／{len(yd)}",
            "- " + ("✅ 達標 → 提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "ROUND_E6S4.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
