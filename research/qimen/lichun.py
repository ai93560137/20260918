"""立春年局：每年立春精確交節一刻起時家局（使用者 2026-11-14 定）。

交節時刻用 ephem（VSOP87，同排盤 App 顯示嘅節氣時刻相差 1 分鐘內）搵太陽視黃經 315°；
起局照本陣方法：英國真太陽時（經度 0.25°E）、23:00 換日、拆補、轉盤。需要 `pip install ephem`。

用法：python3 research/qimen/lichun.py [起始年 1987] [結束年 2026]  → research/qimen/lichun_charts.csv
"""
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import ephem

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiju import qiju

HERE = os.path.dirname(os.path.abspath(__file__))
LON = 0.25


def sun_lon(dt):
    d = ephem.Date(dt)
    s = ephem.Sun(d)
    return math.degrees(ephem.Ecliptic(ephem.Equatorial(s.ra, s.dec, epoch=d)).lon) % 360


def lichun_utc(year):
    a, b = datetime(year, 2, 2), datetime(year, 2, 6)
    for _ in range(60):
        m = a + (b - a) / 2
        if (sun_lon(m) - 315 + 180) % 360 - 180 < 0:
            a = m
        else:
            b = m
    return b.replace(tzinfo=timezone.utc)


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 1987
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    rows = []
    for y in range(y0, y1 + 1):
        t = lichun_utc(y)
        q = qiju(t, LON, lam=315.0)
        assert q["節氣"] == "立春" and q["四柱"][2] == "年", q
        tst = datetime.strptime(q["真太陽時"], "%Y-%m-%d %H:%M")
        tst_s = t.replace(tzinfo=None) + timedelta(minutes=LON * 4 + q["均時差分鐘"])
        mins = tst_s.hour * 60 + tst_s.minute + tst_s.second / 60
        edge = min((mins - 60) % 120, 120 - (mins - 60) % 120)
        pan = q["盤"]
        rows.append({"year": y, "lichun_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
                     "lichun_beijing": (t + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
                     "true_solar_uk": tst_s.strftime("%Y-%m-%d %H:%M:%S"), "mins_to_shichen_edge": round(edge, 1),
                     "ganzhi": q["四柱"], "yuan": q["元"], "ju": q["局"], "xunshou": pan["旬首"], "kongwang": pan["空亡"],
                     "maxing": pan["馬星"], "zhifu": pan["值符"], "zhishi": pan["值使"],
                     "pan": ";".join(f"{p}:{pan['盤'][p]}" for p in (4, 9, 2, 3, 5, 7, 8, 1, 6))})
    with open(os.path.join(HERE, "lichun_charts.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        flag = " ⚠近時辰交界" if r["mins_to_shichen_edge"] < 3 else ""
        print(r["year"], r["lichun_beijing"], "｜真太陽時", r["true_solar_uk"][5:], "｜", r["ganzhi"], r["ju"], flag)


if __name__ == "__main__":
    main()
