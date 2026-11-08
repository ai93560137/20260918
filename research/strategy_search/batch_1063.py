"""[IDEAS #1063–#1066] 第十二批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1063 倫敦下午定盤（倫敦時間 15:00，夏令 14:00 UTC／冬令 15:00 UTC）前一個鐘走 ≥ 4 美元 → 定盤時反向，SL＝TP＝0.5×走幅，3 個鐘收；
#1064 D1 吞噬喺 20 日極端：今日創 20 日新高（低）而收市低過（高過）昨日開市、實體包住昨日實體 → 下一日開市反向，SL 今日極端外 0.5、TP 1R、5 日；
#1065 倫敦開市衝刺：07:00–07:14 UTC 走 ≥ 3 美元 → 07:15 開市價順勢，SL 15 分鐘區間另一邊、TP 2R、11:00 收；
#1066 美國時段走勢亞洲反向：13:30→20:59 UTC 走 ≥ 15 美元 → 下一個交易日第一根開市價反向，SL＝TP＝0.4×走幅，06:59 收。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1063.py → research/strategy_search/BATCH_1063.md"""
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

A = B.A
COST = 0.5


def uk_dst(day):
    """英國夏令：三月最後一個星期日到十月最後一個星期日（UTC 日期近似）。"""
    y = day.year
    def last_sun(m):
        d = dt.date(y, m, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return last_sun(3) <= day < last_sun(10)


def r1063(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        day = dt.datetime.fromtimestamp(int(t[s]), dt.timezone.utc).date()
        fx = (14 if uk_dst(day) else 15) * 3600
        g = B51.idx_at(sod, s, e, fx); a = B51.idx_at(sod, s, e, fx - 3600)
        if g is None or a is None:
            continue
        mv = c[g - 1] - o[a]
        if abs(mv) < 4:
            continue
        sg = -1 if mv > 0 else 1; en = o[g]; dist = 0.5 * abs(mv)
        ex = B51.run_exit(d, g, e, sg, en, en - sg * dist, en + sg * dist, fx + 3 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1064(d):
    b = B.resample(d, 86400); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(21, len(c) - 1):
        if i <= busy:
            continue
        top = h[i] > h[i - 20:i].max() and c[i] < o[i - 1] and o[i] > c[i - 1] and c[i] < o[i]
        bot = l[i] < l[i - 20:i].min() and c[i] > o[i - 1] and o[i] < c[i - 1] and c[i] > o[i]
        sg = -1 if top else (1 if bot else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; sl = (h[i] + 0.5) if sg < 0 else (l[i] - 0.5); risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 5)
        busy = ei + 4
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1065(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        a = B51.idx_at(sod, s, e, 7 * 3600); g = B51.idx_at(sod, s, e, 7 * 3600 + 900)
        if a is None or g is None or g - a < 10:
            continue
        mv = c[g - 1] - o[a]
        if abs(mv) < 3:
            continue
        sg = 1 if mv > 0 else -1; en = o[g]; hi, lo = h[a:g].max(), l[a:g].min()
        sl = lo if sg > 0 else hi; risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B51.run_exit(d, g, e, sg, en, sl, en + sg * 2 * risk, 11 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1066(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    ds = B37.days(t)
    for (s, e), (ns, ne) in zip(ds[:-1], ds[1:]):
        a = B51.idx_at(sod, s, e, 13 * 3600 + 1800)
        if a is None:
            continue
        mv = c[e - 1] - o[a]
        if abs(mv) < 15 or t[ns] - t[e - 1] > 3 * 86400:
            continue
        sg = -1 if mv > 0 else 1; en = o[ns]; dist = 0.4 * abs(mv)
        ex = B51.run_exit(d, ns, ne, sg, en, en - sg * dist, en + sg * dist, 7 * 3600)
        out.append((int(t[ns]), sg, (sg * (ex - en) - COST) / dist))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十二批四條規則（IDEAS #1063–#1066）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1063 倫敦下午定盤前走勢反向（≥ 4 美元；SL＝TP＝0.5×；3 個鐘）", r1063, 200, 100),
                             ("#1064 D1 吞噬喺 20 日極端反向（SL 極端外 0.5；TP 1R；5 日）", r1064, 40, 20),
                             ("#1065 倫敦開市衝刺（07:00–07:14 ≥ 3 美元順勢；SL 區間另一邊；TP 2R；11:00）", r1065, 200, 100),
                             ("#1066 美國時段走勢亞洲反向（≥ 15 美元；SL＝TP＝0.4×；06:59）", r1066, 150, 80)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1063.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
