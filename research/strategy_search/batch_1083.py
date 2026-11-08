"""[IDEAS #1083–#1086] 第十六批：急動家族嘅新觸發，全部用 E6S4（深回調入場、細目標），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1083 偏離均線：M1 收市 − EMA60(M1) ≥ 6 美元 → 反向；#1084 M15 收市出保力加 2.5σ（SMA20）→ 反向（以嗰根 M15 最後一分鐘收市為基準）；
#1085 急動創 4 個鐘新高／新低：M1 高（低）創前 240 根新高（低）而且前 15 根走 ≥ 2 美元同方向 → 反向；#1086 M5 RSI14 ≥ 85（≤ 15）→ 反向。
全部 E6 Z2 S4 1R（fit_rules.simulate）、冷卻 60 分鐘、每張扣 0.5 美元。
用法：python3 research/strategy_search/batch_1083.py → research/strategy_search/BATCH_1083.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1023 as B23        # noqa: E402
import batch_1029 as B29        # noqa: E402
import batch_1033 as B33        # noqa: E402
import batch_1079 as B79        # noqa: E402

A = B.A


def last_m1(d, bt, sec):
    t = d["t"]; out = []
    for x in bt:
        k = int(np.searchsorted(t, x + sec)) - 1
        out.append(k if k >= 0 and t[k] // sec == x // sec else -1)
    return np.array(out)


def r1083(d):
    c = d["c"]; e = B23.ema(c, 60); dev = c - e; n = len(c)
    raw = [(i, "SELL" if dev[i] > 0 else "BUY") for i in np.nonzero(np.abs(dev) >= 6.0)[0] if i >= 120]
    return B79.e6s4_at(d, raw, 60)


def r1084(d):
    b = B.resample(d, 900); c = b["c"]; m = B.sma(c, 20)
    sd = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        sd[i] = c[i - 19:i + 1].std()
    km = last_m1(d, b["t"], 900); raw = []
    for i in range(20, len(c)):
        if np.isnan(sd[i]) or km[i] < 0:
            continue
        if c[i] > m[i] + 2.5 * sd[i]:
            raw.append((int(km[i]), "SELL"))
        elif c[i] < m[i] - 2.5 * sd[i]:
            raw.append((int(km[i]), "BUY"))
    return B79.e6s4_at(d, raw, 60)


def r1085(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]; n = len(t); raw = []
    from numpy.lib.stride_tricks import sliding_window_view as sw
    hh = np.full(n, np.inf); ll = np.full(n, -np.inf)
    hh[240:] = sw(h, 240)[:-1].max(axis=1); ll[240:] = sw(l, 240)[:-1].min(axis=1)
    mv = np.full(n, 0.0); mv[15:] = c[15:] - o[:-15]
    for i in np.nonzero((h > hh) & (mv >= 2.0))[0]:
        raw.append((int(i), "SELL"))
    for i in np.nonzero((l < ll) & (mv <= -2.0))[0]:
        raw.append((int(i), "BUY"))
    return B79.e6s4_at(d, raw, 60)


def r1086(d):
    b = B.resample(d, 300); r = B29.rsi(b["c"]); km = last_m1(d, b["t"], 300); raw = []
    for i in range(20, len(r)):
        if np.isnan(r[i]) or km[i] < 0:
            continue
        if r[i] >= 85:
            raw.append((int(km[i]), "SELL"))
        elif r[i] <= 15:
            raw.append((int(km[i]), "BUY"))
    return B79.e6s4_at(d, raw, 60)


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十六批：急動家族新觸發（IDEAS #1083–#1086）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；全部 E6S4、冷卻 60 分鐘、每張扣 0.5 美元", ""]
    for name, fn in (("#1083 偏離 EMA60 ≥ 6 美元反向", r1083), ("#1084 M15 保力加 2.5σ 出界反向", r1084),
                     ("#1085 急動創 4 個鐘新高／新低反向", r1085), ("#1086 M5 RSI14 ≥ 85／≤ 15 反向", r1086)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, 300, 150)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1083.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
