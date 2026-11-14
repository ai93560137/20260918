"""節氣局：每個節氣精確交節一刻起時家局（立春嗰個即係「立春年局」）。

使用者 2026-11-14：「用每年立春精確交節那一分那一秒的時間來起局」「用北京時間」「節氣局都做」。
- 交節時刻：ephem（VSOP87）搵太陽視黃經每 15°；同排盤 App 顯示嘅節氣時刻相差 1 分鐘內。需要 `pip install ephem`。
- 日柱、時柱：**北京時間（UTC+8）時鐘時間**，23:00 起算翌日；唔做真太陽時修正（只限呢個大股災測試；平時起局照用英國真太陽時）。
- 定局：拆補、轉盤（paipan.py）。

用法：python3 research/qimen/jieqi_ju.py [起始年 1987] [結束年 2026]
輸出：research/qimen/jieqi_charts.csv（全部節氣局）、research/qimen/lichun_charts.csv（只係立春）
"""
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import ephem

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiju import JIEQI, qiju

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = 8                                             # 北京時間


def sun_lon(dt):
    d = ephem.Date(dt)
    s = ephem.Sun(d)
    return math.degrees(ephem.Ecliptic(ephem.Equatorial(s.ra, s.dec, epoch=d)).lon) % 360


def crossing(a, b, target):
    for _ in range(60):
        m = a + (b - a) / 2
        if (sun_lon(m) - target + 180) % 360 - 180 < 0:
            a = m
        else:
            b = m
    return b.replace(tzinfo=timezone.utc)


def terms(y0, y1):
    """由 y0 年立春到 y1 年尾，每個交節時刻（UTC）同節氣名。"""
    out = []
    t = datetime(y0, 2, 1)
    k = 21                                         # JIEQI[21]＝立春（315°）
    while True:
        target = (k % 24) * 15
        a = t
        while (sun_lon(a + timedelta(days=1)) - target + 180) % 360 - 180 < 0:
            a += timedelta(days=1)
        c = crossing(a, a + timedelta(days=1), target)
        if c.year > y1:
            return out
        out.append((c, JIEQI[k % 24], float(target)))
        t = c.replace(tzinfo=None) + timedelta(days=13)
        k += 1


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 1987
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    rows = []
    for t, name, lam in terms(y0, y1):
        q = qiju(t, 0, lam=lam, clock_offset_hours=TZ)
        assert q["節氣"] == name, (t, name, q["節氣"])
        bj = t.replace(tzinfo=None) + timedelta(hours=TZ)
        mins = bj.hour * 60 + bj.minute + bj.second / 60
        edge = min((mins - 60) % 120, 120 - (mins - 60) % 120)
        pan = q["盤"]
        rows.append({"jieqi": name, "utc": t.strftime("%Y-%m-%d %H:%M:%S"), "beijing": bj.strftime("%Y-%m-%d %H:%M:%S"),
                     "mins_to_shichen_edge": round(edge, 1), "ganzhi": q["四柱"], "yuan": q["元"], "ju": q["局"],
                     "xunshou": pan["旬首"], "kongwang": pan["空亡"], "maxing": pan["馬星"], "zhifu": pan["值符"], "zhishi": pan["值使"],
                     "pan": ";".join(f"{p}:{pan['盤'][p]}" for p in (4, 9, 2, 3, 5, 7, 8, 1, 6))})
    for fn, sub in (("jieqi_charts.csv", rows), ("lichun_charts.csv", [r for r in rows if r["jieqi"] == "立春"])):
        with open(os.path.join(HERE, fn), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(sub)
    near = [r for r in rows if r["mins_to_shichen_edge"] < 2]
    print(f"節氣局 {len(rows)} 個；立春 {sum(r['jieqi'] == '立春' for r in rows)} 個；離時辰交界 < 2 分鐘：{len(near)} 個")
    for r in near:
        print("  ⚠", r["jieqi"], r["beijing"], r["ganzhi"], f"離交界 {r['mins_to_shichen_edge']} 分鐘")


if __name__ == "__main__":
    main()
