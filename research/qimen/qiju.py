"""時家奇門起局（拆補法・轉盤）：由 UTC 時刻同經度計真太陽時、四柱、節氣、三元、局數，再用 paipan 排盤。

方法見 handoff/奇門遁甲.md 第五節：真太陽時＝UTC＋經度×4 分鐘＋均時差；真太陽時 23:00 換日；節氣用太陽視黃經
（Meeus 低精度公式，誤差約 0.01°≈15 分鐘；離交節 2 小時內會出警告，要人手核對）。

用法：python3 research/qimen/qiju.py [YYYY-MM-DDTHH:MM（UTC）] [經度，東正西負，預設 0.25]
"""
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paipan import GAN, ZHI, paipan, show

JIEQI = ["春分", "清明", "穀雨", "立夏", "小滿", "芒種", "夏至", "小暑", "大暑", "立秋", "處暑", "白露",
         "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒", "立春", "雨水", "驚蟄"]
JU = {"冬至": (1, 7, 4), "小寒": (2, 8, 5), "大寒": (3, 9, 6), "立春": (8, 5, 2), "雨水": (9, 6, 3), "驚蟄": (1, 7, 4),
      "春分": (3, 9, 6), "清明": (4, 1, 7), "穀雨": (5, 2, 8), "立夏": (4, 1, 7), "小滿": (5, 2, 8), "芒種": (6, 3, 9),
      "夏至": (9, 3, 6), "小暑": (8, 2, 5), "大暑": (7, 1, 4), "立秋": (2, 5, 8), "處暑": (1, 4, 7), "白露": (9, 3, 6),
      "秋分": (7, 1, 4), "寒露": (6, 9, 3), "霜降": (5, 8, 2), "立冬": (6, 9, 3), "小雪": (5, 8, 2), "大雪": (4, 7, 1)}
YANG = set(JIEQI[18:] + JIEQI[:6])                 # 冬至…芒種


def gz(i):
    return GAN[i % 10] + ZHI[i % 12]


def sun(utc):
    """回傳（太陽視黃經 度，均時差 分鐘）。Meeus 低精度。"""
    jd = utc.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545.0) / 36525
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360
    m = math.radians((357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360)
    e = 0.016708634 - 0.000042037 * t
    c = ((1.914602 - 0.004817 * t) * math.sin(m) + (0.019993 - 0.000101 * t) * math.sin(2 * m) + 0.000289 * math.sin(3 * m))
    om = math.radians(125.04 - 1934.136 * t)
    lam = (l0 + c - 0.00569 - 0.00478 * math.sin(om)) % 360
    eps = math.radians(23.439291 - 0.0130042 * t + 0.00256 * math.cos(om))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eot = y * math.sin(2 * l0r) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0r) \
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * m)
    return lam, math.degrees(eot) * 4


def qiju(utc, lon):
    lam, eot = sun(utc)
    tst = utc.replace(tzinfo=None) + timedelta(minutes=lon * 4 + eot)
    day = (tst + timedelta(hours=1)).date()        # 23:00 換日
    jdn = day.toordinal() + 1721425
    d = (jdn + 49) % 60
    zhi = ((tst.hour + 1) // 2) % 12
    h_gan = (d % 10 % 5 * 2 + zhi) % 10
    shi = GAN[h_gan] + ZHI[zhi]
    y = utc.year - (1 if utc.month <= 2 and 270 <= lam < 315 else 0)
    yi = (y - 4) % 60
    mz = int(((lam - 315) % 360) // 30)             # 0＝寅月
    month = GAN[(yi % 10 % 5 * 2 + 2 + mz) % 10] + ZHI[(mz + 2) % 12]
    jq = JIEQI[int(lam // 15)]
    to_next = (15 - lam % 15) / 0.9856 * 24         # 距下個節氣（小時，約數）
    since = (lam % 15) / 0.9856 * 24
    futou = d - d % 5
    yuan = "上中下"[{0: 0, 6: 0, 3: 0, 9: 0, 2: 1, 8: 1, 5: 1, 11: 1}.get(futou % 12, 2)]
    yang = jq in YANG
    ju = JU[jq]["上中下".index(yuan)]
    warn = []
    if min(to_next, since) < 2:
        warn.append(f"離交節約 {min(to_next, since):.1f} 小時，節氣要人手核對")
    mins = tst.hour * 60 + tst.minute
    edge = min((mins - 60) % 120, 120 - (mins - 60) % 120)
    if edge < 5:
        warn.append(f"離時辰交界 {edge} 分鐘，時辰要人手核對")
    # 使用者排盤 App 用英國時鐘時間定時辰（冇真太陽時）；時辰或日柱唔同就要另外同使用者講（使用者 2026-11-13）
    clock = utc.astimezone(ZoneInfo("Europe/London")).replace(tzinfo=None)
    c_day = (clock + timedelta(hours=1)).date()
    c_zhi = ((clock.hour + 1) // 2) % 12
    c_d = (c_day.toordinal() + 1721425 + 49) % 60
    c_shi = GAN[(c_d % 10 % 5 * 2 + c_zhi) % 10] + ZHI[c_zhi]
    app = None
    if (c_d, c_shi) != (d, shi):
        c_futou = c_d - c_d % 5
        c_ju = JU[jq]["上中下".index("上中下"[{0: 0, 6: 0, 3: 0, 9: 0, 2: 1, 8: 1, 5: 1, 11: 1}.get(c_futou % 12, 2)])]
        app = {"英國時鐘": clock.strftime("%Y-%m-%d %H:%M"), "日時": f"{gz(c_d)}日 {c_shi}時",
               "局": f"{'陽' if yang else '陰'}遁{c_ju}局", "盤": paipan(yang, c_ju, c_shi)}
        warn.append(f"同 App（時鐘時間）唔同：App 會用 {gz(c_d)}日 {c_shi}時，本陣用 {gz(d)}日 {shi}時 → 要另外同使用者講")
    return {"App盤": app, "英國時鐘": clock.strftime("%Y-%m-%d %H:%M"), "utc": utc.strftime("%Y-%m-%d %H:%M"), "真太陽時": tst.strftime("%Y-%m-%d %H:%M"), "均時差分鐘": round(eot, 1),
            "四柱": f"{gz(yi)}年 {month}月 {gz(d)}日 {shi}時", "節氣": jq, "符頭": gz(futou), "元": yuan + "元",
            "局": f"{'陽' if yang else '陰'}遁{ju}局", "警告": warn, "盤": paipan(yang, ju, shi)}


if __name__ == "__main__":
    t = (datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc) if len(sys.argv) > 1
         else datetime.now(timezone.utc))
    r = qiju(t, float(sys.argv[2]) if len(sys.argv) > 2 else 0.25)
    for k in ("utc", "英國時鐘", "真太陽時", "均時差分鐘", "四柱", "節氣", "符頭", "元", "局"):
        print(f"{k}：{r[k]}")
    for w in r["警告"]:
        print("⚠", w)
    show(r["盤"])
    if r["App盤"]:
        a = r["App盤"]
        print(f"—— App（時鐘時間 {a['英國時鐘']}）會出：{a['日時']} {a['局']} ——")
        show(a["盤"])
