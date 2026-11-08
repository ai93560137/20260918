"""[IDEAS #1079–#1081] 第十五批三條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1079 H1 幅擴張：H1 幅 ≥ 3×ATR14(H1) → 反向 E6S4（以嗰根收市為基準；冷卻 120 分鐘）；
#1080 M1 樓梯：連 4 根 M1 同方向、每根實體 ≥ 0.8 美元 → 反向 E6S4（以第 4 根收市為基準；冷卻 60 分鐘）；
#1081 紐約開市 15 分鐘急動反向：13:30–13:44 UTC 走 ≥ 5 美元 → E6S4 反向（以 13:44 收市為基準）。
（#1082 係 #1052 反向，只用 2010–2014 判，放喺 oos_rev_1075.py。）成本每張 0.5 美元。
用法：python3 research/strategy_search/batch_1079.py → research/strategy_search/BATCH_1079.md"""
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
import batch_1051 as B51        # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B.A
fr = af.fr


def e6s4_at(d, raw, cd):
    t = d["t"]
    sigs = fr.cooldown(sorted(raw), t, cd, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), 6.0, 2.0, 4.0, 1.0)
    return [(int(t[i]) + 60, 1 if s == "BUY" else -1, float(x)) for (i, s), x in zip(sigs, r) if not np.isnan(x)]


def r1079(d):
    b = B.resample(d, 3600); a = B.atr(b); t = d["t"]; raw = []
    for i in range(15, len(b["c"])):
        if np.isnan(a[i - 1]) or a[i - 1] <= 0 or (b["h"][i] - b["l"][i]) < 3 * a[i - 1] or b["c"][i] == b["o"][i]:
            continue
        k = int(np.searchsorted(t, b["t"][i] + 3600)) - 1        # 嗰個鐘最後一根 M1
        if k <= 0 or t[k] // 3600 != b["t"][i] // 3600:
            continue
        raw.append((k, "BUY" if b["c"][i] < b["o"][i] else "SELL"))
    return e6s4_at(d, raw, 120)


def r1080(d):
    o, c = d["o"], d["c"]; body = c - o; n = len(c); raw = []
    up = body >= 0.8; dn = body <= -0.8
    for i in range(30, n):
        if up[i - 3:i + 1].all():
            raw.append((i, "SELL"))
        elif dn[i - 3:i + 1].all():
            raw.append((i, "BUY"))
    return e6s4_at(d, raw, 60)


def r1081(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; raw = []
    for s, e in B37.days(t):
        a = B51.idx_at(sod, s, e, 13 * 3600 + 1800); b = B51.idx_at(sod, s, e, 13 * 3600 + 44 * 60)
        if a is None or b is None:
            continue
        mv = c[b] - o[a]
        if abs(mv) >= 5:
            raw.append((b, "SELL" if mv > 0 else "BUY"))
    return e6s4_at(d, raw, 60)


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十五批三條規則（IDEAS #1079–#1081）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1079 H1 幅擴張（≥ 3×ATR）反向 E6S4", r1079, 200, 100),
                             ("#1080 M1 樓梯（連 4 根同向實體 ≥ 0.8）反向 E6S4", r1080, 300, 150),
                             ("#1081 紐約開市 15 分鐘急動（≥ 5 美元）反向 E6S4", r1081, 100, 60)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1079.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
