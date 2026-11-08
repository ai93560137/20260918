"""[IDEAS #1120–#1123] 急動家族新觸發（全部 E6S4、冷卻 60 分鐘、每張扣 0.5 美元），三段數據都要過。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1120 rev30：前 30 根走幅 ≥ 5 美元反向（rev15／rev60 之間，接近內插，預先寫明）；
#1121 M5 單根急動：一根 M5 幅 ≥ 6 美元 → 反向（以嗰根 M5 最後一分鐘收市為基準）；
#1122 離當日開市價 ≥ 15 美元：當日（UTC）第一次收市離 00:00 開市價 ≥ 15 美元 → 反向（每日一次）；
#1123 兩根 M1 急動：連 2 根 M1 同方向、兩根合計走 ≥ 5 美元 → 反向。
成功（全部要達到）：① Duka 2015–2022 張數 ≥ 200、平均 ≥ +0.10R、PF ≥ 1.15、有交易年份 ≥ 5／8 正；② MT5 2023–2026 張數 ≥ 100、平均 ≥ +0.05R、PF ≥ 1.10；③ Duka 2010–2014 張數 ≥ 100、平均 ≥ +0.05R、PF ≥ 1.10。
用法：python3 research/strategy_search/batch_1120.py → research/strategy_search/BATCH_1120.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402
import batch_1079 as B79        # noqa: E402
import batch_1083 as B83        # noqa: E402

A = B.A


def r1120(d):
    t, o, c = d["t"], d["o"], d["c"]; n = len(t)
    mv = np.full(n, np.nan); mv[30:] = c[30:] - o[:-30]
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero((np.abs(mv) >= 5.0) & (np.arange(n) >= 44))[0]]
    return B79.e6s4_at(d, raw, 60)


def r1121(d):
    b = B.resample(d, 300); km = B83.last_m1(d, b["t"], 300); raw = []
    for i in range(len(b["c"])):
        if km[i] < 30 or (b["h"][i] - b["l"][i]) < 6.0 or b["c"][i] == b["o"][i]:
            continue
        raw.append((int(km[i]), "BUY" if b["c"][i] < b["o"][i] else "SELL"))
    return B79.e6s4_at(d, raw, 60)


def r1122(d):
    t, o, c = d["t"], d["o"], d["c"]; raw = []
    for s, e in B37.days(t):
        if t[s] % 86400 >= 300:
            continue
        op = o[s]
        for i in range(s + 1, e):
            if abs(c[i] - op) >= 15.0:
                raw.append((i, "SELL" if c[i] > op else "BUY")); break
    return B79.e6s4_at(d, raw, 60)


def r1123(d):
    o, c = d["o"], d["c"]; body = c - o; n = len(c); raw = []
    for i in range(30, n):
        a, b2 = body[i - 1], body[i]
        if a > 0 and b2 > 0 and a + b2 >= 5.0:
            raw.append((i, "SELL"))
        elif a < 0 and b2 < 0 and a + b2 <= -5.0:
            raw.append((i, "BUY"))
    return B79.e6s4_at(d, raw, 60)


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    out = ["# 急動家族新觸發（IDEAS #1120–#1123；三段數據）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；全部 E6S4、冷卻 60、每張扣 0.5 美元", ""]
    for name, fn in (("#1120 rev30（30 分鐘走 ≥ 5 美元）", r1120), ("#1121 M5 單根急動（≥ 6 美元）", r1121),
                     ("#1122 離當日開市價 ≥ 15 美元", r1122), ("#1123 兩根 M1 急動（合計 ≥ 5 美元）", r1123)):
        td, tm, to = fn(sets["d15"]), fn(sets["m23"]), fn(sets["d10"])
        ok, lines, _, _ = B33.judge(td, tm, 200, 100)
        so = A.stats([x[2] for x in to])
        ok["④Duka 2010–2014 n≥100、平均≥+0.05R、PF≥1.10"] = so["n"] >= 100 and so["avg"] >= 0.05 and so["pf"] >= 1.10
        out += [f"## {name}", "", *lines, f"- Dukascopy 2010–2014：{A.fmt(so)}", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1120.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
