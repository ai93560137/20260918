"""[IDEAS #1067–#1070] 第十三批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1067 M1 單根急動：一根 M1 幅 ≥ 4 美元 → 反向 E6S4（以嗰根收市為基準；冷卻 60 分鐘）；
#1068 H1 連 3 根更高高位＋更高收市（或連 3 根更低）→ 下一根開市反向，SL 第 3 根極端外 0.5、TP 1R、6 根；
#1069 大日幅翌日反向：前日幅 ≥ 2×ATR14(D1) → 今日開市反向前日方向，SL 1×ATR、今日收市走；
#1070 紐約收市後做多：20:00 UTC 開市價買、21:55 前最後收市走，SL 5 美元。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1067.py → research/strategy_search/BATCH_1067.md"""
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
COST = 0.5


def r1067(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]; n = len(t)
    ok = ((h - l) >= 4.0) & (np.arange(n) >= 30)
    raw = [(int(i), "BUY" if c[i] < o[i] else "SELL") for i in np.nonzero(ok)[0] if c[i] != o[i]]
    sigs = fr.cooldown(raw, t, 60, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), 6.0, 2.0, 4.0, 1.0)
    return [(int(t[i]) + 60, 1 if s == "BUY" else -1, float(x)) for (i, s), x in zip(sigs, r) if not np.isnan(x)]


def r1068(d):
    b = B.resample(d, 3600); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(4, len(c) - 1):
        if i <= busy:
            continue
        up = all(h[i - k] > h[i - k - 1] and c[i - k] > c[i - k - 1] for k in range(3))
        dn = all(l[i - k] < l[i - k - 1] and c[i - k] < c[i - k - 1] for k in range(3))
        sg = -1 if up else (1 if dn else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; sl = (h[i] + 0.5) if sg < 0 else (l[i] - 0.5); risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 6)
        busy = ei + 5
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1069(d):
    b = B.resample(d, 86400); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; a = B.atr(b)
    out = []
    for i in range(15, len(c) - 1):
        if np.isnan(a[i - 1]) or a[i - 1] <= 0 or (h[i] - l[i]) < 2 * a[i - 1] or c[i] == o[i]:
            continue
        sg = -1 if c[i] > o[i] else 1
        ei = i + 1; en = o[ei]; risk = a[i]; sl = en - sg * risk
        ex = sl if ((l[ei] <= sl) if sg > 0 else (h[ei] >= sl)) else c[ei]
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1070(d):
    t, o, h, c = d["t"], d["o"], d["h"], d["c"]; l = d["l"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        g = B51.idx_at(sod, s, e, 20 * 3600)
        if g is None:
            continue
        en = o[g]; sl = en - 5.0; ex = None; last = g
        for j in range(g, e):
            if sod[j] >= 21 * 3600 + 56 * 60:
                break
            last = j
            if l[j] <= sl:
                ex = sl; break
        if ex is None:
            ex = c[last]
        out.append((int(t[g]), 1, (ex - en - COST) / 5.0))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十三批四條規則（IDEAS #1067–#1070）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1067 M1 單根急動（幅 ≥ 4 美元）反向 E6S4", r1067, 300, 150),
                             ("#1068 H1 連 3 根更高高位＋收市反向（SL 極端外 0.5；TP 1R；6 根）", r1068, 300, 150),
                             ("#1069 大日幅（≥ 2×ATR）翌日反向（SL 1×ATR；收市走）", r1069, 60, 30),
                             ("#1070 紐約收市後做多（20:00→21:55，SL 5）", r1070, 300, 150)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1067.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
