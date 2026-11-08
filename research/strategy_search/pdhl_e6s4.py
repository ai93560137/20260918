"""[IDEAS #1009] 前日高／低（UTC 日）當日第一次觸及 → 用 E6S4 結構反向（入場區＝觸及價再過 6 美元 ±2、SL 再過 4、TP 1R、30 分鐘有效）。
規格、成功標準以 IDEAS #1009 預先登記為準（跑之前 commit）。規則固定、冇網格。
數據：Dukascopy M1 2015–2022（主判）＋MT5 M1 2023-01→2026-10（確認）。成交／計分同 ai_entry_forward.sim。
用法：python3 research/strategy_search/pdhl_e6s4.py → research/strategy_search/PDHL_E6S4.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402  （load／stats／fmt／by_year）
import ai_entry_forward as af   # noqa: E402

HOURS = (1, 20)     # 01:00–19:59 UTC 先接受觸及（避開換日同收市前）


def run(d, scaled=False):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    day = t // 86400; hour = (t // 3600) % 24
    starts = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    out = []
    for k in range(1, len(starts) - 1):
        ps, pe, s, e = starts[k - 1], starts[k], starts[k], starts[k + 1]
        if day[s] - day[ps] > 3 or pe - ps < 600:          # 前一個交易日唔齊就跳過
            continue
        pdh, pdl = h[ps:pe].max(), l[ps:pe].min()
        if h[s] >= pdh or l[s] <= pdl:                     # 開市已經喺區外就唔計「第一次觸及」
            pass
        m = c[s] / 4000.0 if scaled else 1.0
        for side, lvl, hit in (("SELL", pdh, h[s:e] >= pdh), ("BUY", pdl, l[s:e] <= pdl)):
            idx = np.nonzero(hit & (hour[s:e] >= HOURS[0]) & (hour[s:e] < HOURS[1]))[0]
            if not len(idx):
                continue
            i = s + idx[0]
            if i > s and ((h[s:i] >= pdh).any() if side == "SELL" else (l[s:i] <= pdl).any()):
                continue                                   # 唔係當日第一次（換日頭一個鐘已經掂過）
            sg = 1 if side == "BUY" else -1
            mid = lvl - sg * 6.0 * m
            r = af.sim(d, int(t[i]) + 60, side, mid, mid - sg * 4.0 * m, mid + sg * 4.0 * m, lo=mid - 2.0 * m, hi=mid + 2.0 * m)
            if r is not None:
                if scaled:
                    r = r + (af.COST - af.COST * m) / (4.0 * m)   # 縮放版：成本都按比例
                out.append((int(t[i]), sg, r))
    return sorted(out)


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    tr_d, tr_m = run(duka), run(mt5)
    sd, sm = A.stats([x[2] for x in tr_d]), A.stats([x[2] for x in tr_m])
    yd = A.by_year(tr_d)
    out = ["# 前日高低第一次觸及 → E6S4 結構反向（IDEAS #1009）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；前日＝上一個 UTC 交易日；01–20 UTC 第一次觸及；入場區觸及價再過 6 美元 ±2、SL 再過 4、TP 1R、30 分鐘有效；每張扣 0.5 美元", "",
           "| 數據 | 固定美元（主判） | 按價格縮放（描述） | 做多（前日低） | 做空（前日高） |", "|---|---|---|---|---|",
           f"| Dukascopy 2015–2022 | {A.fmt(sd)} | {A.fmt(A.stats([x[2] for x in run(duka, True)]))} | {A.fmt(A.stats([x[2] for x in tr_d if x[1] > 0]))} | {A.fmt(A.stats([x[2] for x in tr_d if x[1] < 0]))} |",
           f"| MT5 2023-01→2026-10 | {A.fmt(sm)} | {A.fmt(A.stats([x[2] for x in run(mt5, True)]))} | {A.fmt(A.stats([x[2] for x in tr_m if x[1] > 0]))} | {A.fmt(A.stats([x[2] for x in tr_m if x[1] < 0]))} |",
           "", "## 每年（固定美元）", ""] + [f"- {y}：{A.fmt(v)}" for y, v in {**yd, **A.by_year(tr_m)}.items()]
    pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
    ok = {"①Duka n≥300、平均≥+0.10R、PF≥1.15": sd["n"] >= 300 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
          "②Duka 8年≥5年正數": pos >= 5,
          "③MT5 平均≥+0.05R、PF≥1.10": sm["n"] > 0 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
    out += ["", "## 判（預先登記 IDEAS #1009）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], f"- Duka 正數年份 {pos}／{len(yd)}",
            "- " + ("✅ 達標 → 提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "PDHL_E6S4.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
