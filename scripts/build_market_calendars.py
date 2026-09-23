#!/usr/bin/env python3
"""三地交易所休市日曆 → universes/calendars/<market>.csv（檢入 git，執行時不需要額外套件）。

    pip install exchange_calendars && python3 scripts/build_market_calendars.py   # 每年年底重跑一次

來源：exchange_calendars（XHKG 港交所、XTKS 東證、XNYS 紐交所；按各交易所公布的假期規則整理），
再加 ADHOC 裡人工登記的臨時休市（颱風／黑雨等不可預先排定、套件沒有的）。
只記「平日休市」（週末本來就不開）。欄位：date,name_zh,name,kind（holiday 假期 / adhoc 臨時休市）；
name 是套件的英文名（農曆假期、日本春秋分等套件沒名字的留空，name_zh 按節日日期表補上，節後幾天內的是補假）。

驗證（2026-09-23）：拿 2015-01 ~ 2026-09 的實際價格比對——港股只差下面兩個臨時休市、美股只差
2026-09-22（Yahoo 缺數據，不是休市）；日股 2018 年有 22 個假期 Yahoo 仍有列（垃圾列，日曆正確）。
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "universes" / "calendars"
CODES = {"hk": "XHKG", "jp": "XTKS", "us": "XNYS"}
START, END = "2010-01-04", "2027-12-31"
NAME_ZH = {
    "New Year's Day": "元旦", "Christmas": "聖誕節", "Weekend Christmas": "聖誕節補假", "Boxing Day": "聖誕節翌日",
    "Good Friday": "耶穌受難節", "Easter Monday": "復活節星期一", "Labour Day": "勞動節", "Labor Day": "勞動節",
    "National Day": "國慶日", "Hong Kong Special Region Establishment Day": "香港特區成立紀念日",
    "Children's Day": "兒童節（こどもの日）", "Coming of Age Day": "成人之日", "Constitution Memorial Day": "憲法紀念日",
    "Culture Day": "文化之日", "Emperor Naruhito's Birthday": "天皇誕生日", "Emperor's Birthday": "天皇誕生日",
    "Greenery Day": "綠之日", "Health and Sports Day": "體育之日", "Sports Day": "體育之日",
    "Labor Thanksgiving Day": "勤勞感謝之日", "Marine Day": "海之日", "Mountain Day": "山之日",
    "National Foundation Day": "建國紀念之日", "New Year's Holiday": "新年假期", "Respect for the Aged Day": "敬老之日",
    "Showa Day": "昭和之日", "Dr. Martin Luther King Jr. Day": "馬丁路德金紀念日", "July 4th": "美國獨立日",
    "Juneteenth National Independence Day": "六月節", "Memorial Day": "陣亡將士紀念日", "President's Day": "總統日",
    "Thanksgiving": "感恩節",
}
ADHOC = {   # 套件沒有、人工查證的臨時休市（全日）
    "hk": [("2023-09-01", "颱風蘇拉（八號風球）全日休市"),
           ("2023-09-08", "黑色暴雨全日休市")],
}


def main() -> None:
    import exchange_calendars as xc
    import pandas as pd
    OUT.mkdir(parents=True, exist_ok=True)
    for m, code in CODES.items():
        cal = xc.get_calendar(code, start=START, end=END)
        sessions = {d.date() for d in cal.sessions}
        names = {}
        try:
            for d, n in cal.regular_holidays.holidays(START, END, return_name=True).items():
                names[d.date()] = str(n)
        except Exception:
            pass
        # 套件沒名字的假期：按農曆節日／日本春秋分等日期表補名（節日後 1–3 天內的休市 = 補假或連假）
        lunar = []
        if m == "hk":
            import exchange_calendars.exchange_calendar_xhkg as h
            lunar = [(h.chinese_lunar_new_year_dates, "農曆新年"), (h.qingming_festival_dates, "清明節"),
                     (h.chinese_buddhas_birthday_dates, "佛誕"), (h.dragon_boat_festival_dates, "端午節"),
                     (h.day_after_mid_autumn_festival_dates, "中秋節翌日"), (h.double_ninth_festival_dates, "重陽節")]
        elif m == "jp":
            import exchange_calendars.exchange_calendar_xtks as j
            lunar = [(j.VernalEquinoxes, "春分之日"), (j.AutumnalEquinoxes, "秋分之日"),
                     (j.CitizensHolidaySilverWeek, "國民休日"), (j.CitizensHolidayGoldenWeek, "國民休日")]
        lunar = [({pd.Timestamp(x).date() for x in (ds.dates(START, END) if hasattr(ds, "dates") else ds)}, n)
                 for ds, n in lunar]

        def guess(d):
            for back in range(0, 4):
                x = d - pd.Timedelta(days=back).to_pytimedelta()
                for ds, n in lunar:
                    if x in ds:
                        return n if back == 0 or n == "農曆新年" else f"{n}補假"
            return "補假" if m == "jp" else "公眾假期"

        rows = {}
        for d in pd.bdate_range(max(pd.Timestamp(START), cal.first_session), END):
            d = d.date()
            if d not in sessions:
                en = names.get(d, "")
                zh = NAME_ZH.get(re.sub(r"\s*\(.*", "", en)) or guess(d)
                rows[d.isoformat()] = (zh, en, "holiday")
        for d, n in ADHOC.get(m, []):
            rows[d] = (n, "", "adhoc")
        with open(OUT / f"{m}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["date", "name_zh", "name", "kind"])
            for d in sorted(rows):
                w.writerow([d, *rows[d]])
        print(f"{m}（{code}）：{len(rows)} 個平日休市 {START} ~ {END} -> {OUT / (m + '.csv')}", file=sys.stderr)


if __name__ == "__main__":
    main()
