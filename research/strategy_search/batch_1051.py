"""[IDEAS #1051–#1054] 第九批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1051 紐約日內動量：13:30–13:59 UTC 走勢方向 → 19:00 開市價順勢入、19:59 收市走，SL 5 美元；
#1052 亞洲趨勢喺倫敦開市反向：00:00→06:59 走 ≥ 8 美元 → 07:00 開市價反向，SL＝TP＝0.5×走幅，12:00 收；
#1053 星期五紐約走勢星期一反向：星期五 13:30→20:59 走 ≥ 10 美元 → 星期一第一根開市價反向，SL＝TP＝0.5×走幅，星期一 12:00 收；
#1054 H1 Keltner（EMA20 ± 2×ATR14）收市出界順勢：SL＝EMA20、TP 2R、24 根。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1051.py → research/strategy_search/BATCH_1051.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1023 as B23        # noqa: E402
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402

A = B.A
COST = 0.5


def idx_at(sod, s, e, sec):
    a = np.nonzero(sod[s:e] == sec)[0]
    return a[0] + s if len(a) else None


def run_exit(d, i0, e, sg, en, sl, tp, stop_sec):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    sod = t % 86400; last = i0
    for j in range(i0, e):
        if stop_sec is not None and sod[j] >= stop_sec:
            return o[j]
        last = j
        if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
            return sl
        if tp is not None and ((h[j] >= tp) if sg > 0 else (l[j] <= tp)):
            return tp
    return c[last]


def r1051(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        a, b, g = idx_at(sod, s, e, 13 * 3600 + 1800), idx_at(sod, s, e, 13 * 3600 + 59 * 60), idx_at(sod, s, e, 19 * 3600)
        if a is None or b is None or g is None:
            continue
        mv = c[b] - o[a]
        if mv == 0:
            continue
        sg = 1 if mv > 0 else -1; en = o[g]; sl = en - sg * 5.0
        ex = run_exit(d, g, e, sg, en, sl, None, 20 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / 5.0))
    return out


def r1052(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        if sod[s] >= 300:
            continue
        g = idx_at(sod, s, e, 7 * 3600)
        if g is None:
            continue
        mv = c[g - 1] - o[s]
        if abs(mv) < 8:
            continue
        sg = -1 if mv > 0 else 1; en = o[g]; dist = 0.5 * abs(mv)
        ex = run_exit(d, g, e, sg, en, en - sg * dist, en + sg * dist, 12 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1053(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    ds = B37.days(t)
    for k, (s, e) in enumerate(ds[:-1]):
        if dt.datetime.fromtimestamp(int(t[s]), dt.timezone.utc).weekday() != 4:
            continue
        a = idx_at(sod, s, e, 13 * 3600 + 1800)
        if a is None:
            continue
        mv = c[e - 1] - o[a]
        if abs(mv) < 10:
            continue
        ns, ne = ds[k + 1]
        # 下一個交易段：星期日晚開市（UTC 星期日）同星期一一齊計到星期一 12:00
        j_end = ne
        if dt.datetime.fromtimestamp(int(t[ns]), dt.timezone.utc).weekday() == 6 and k + 2 < len(ds):
            j_end = ds[k + 2][1]
        sg = -1 if mv > 0 else 1; en = o[ns]; dist = 0.5 * abs(mv)
        sl, tp = en - sg * dist, en + sg * dist; ex = None; last = ns
        for j in range(ns, j_end):
            u = dt.datetime.fromtimestamp(int(t[j]), dt.timezone.utc)
            if u.weekday() == 0 and u.hour >= 12:
                ex = o[j]; break
            last = j
            if (d["l"][j] <= sl) if sg > 0 else (d["h"][j] >= sl):
                ex = sl; break
            if (d["h"][j] >= tp) if sg > 0 else (d["l"][j] <= tp):
                ex = tp; break
        if ex is None:
            ex = c[last]
        out.append((int(t[ns]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1054(d):
    b = B.resample(d, 3600); c = b["c"]; a = B.atr(b); m = B23.ema(c, 20)
    out, busy = [], -1
    for i in range(30, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        sg = 1 if c[i] > m[i] + 2 * a[i] else (-1 if c[i] < m[i] - 2 * a[i] else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; sl = m[i]; risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * 2 * risk, 24)
        busy = ei + 23
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第九批四條規則（IDEAS #1051–#1054）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1051 紐約日內動量（13:30–13:59 方向 → 19:00 入、19:59 走；SL 5）", r1051, 300, 150),
                             ("#1052 亞洲趨勢倫敦開市反向（≥ 8 美元；SL＝TP＝0.5×；12:00 收）", r1052, 200, 100),
                             ("#1053 星期五紐約走勢星期一反向（≥ 10 美元；SL＝TP＝0.5×；星期一 12:00 收）", r1053, 60, 30),
                             ("#1054 H1 Keltner 收市出界順勢（SL EMA20；TP 2R；24 根）", r1054, 200, 100)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1051.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
