#!/usr/bin/env python3
# 財政部每日實質殖利率曲線（TIPS，2003 起）+ 名目 10Y → data/vol/real_yield.csv
# 欄位：date, real5, real10, real30, nom10, be10（10 年期通膨預期 = 名目 − 實質）
# 沙箱連不到 home.treasury.gov，所以由 GitHub Actions（.github/workflows/fetch_real_yield.yml）執行。
import csv
import io
import os
import sys
import time
from datetime import date, datetime

import requests

URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
       "daily-treasury-rates.csv/{y}/all?type={k}&field_tdr_date_value={y}&page&_format=csv")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
OUT = "data/vol/real_yield.csv"


def year_rows(kind, year):
    for i in range(4):
        try:
            r = requests.get(URL.format(y=year, k=kind), headers=UA, timeout=(10, 40))
            r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        except requests.RequestException as e:
            if i == 3:
                print(f"::warning::{kind} {year} 失敗：{e}")
                return []
            time.sleep(2 ** i)


def main():
    real, nom = {}, {}
    for y in range(2003, date.today().year + 1):
        for r in year_rows("daily_treasury_real_yield_curve", y):
            d = datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
            real[d] = {k: r.get(c) for k, c in (("real5", "5 YR"), ("real10", "10 YR"), ("real30", "30 YR"))}
        for r in year_rows("daily_treasury_yield_curve", y):
            d = datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
            nom[d] = r.get("10 Yr")
    rows = []
    for d in sorted(real):
        v = real[d]
        if not v["real10"] or d not in nom or not nom[d]:
            continue
        r10, n10 = float(v["real10"]), float(nom[d])
        rows.append({"date": d, "real5": v["real5"] or "", "real10": r10, "real30": v["real30"] or "",
                     "nom10": n10, "be10": round(n10 - r10, 3)})
    if len(rows) < 1000:
        sys.exit(f"資料太少（{len(rows)} 筆），不寫檔")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "real5", "real10", "real30", "nom10", "be10"])
        w.writeheader()
        w.writerows(rows)
    print(f"{OUT}：{rows[0]['date']} ～ {rows[-1]['date']}，{len(rows)} 筆")


if __name__ == "__main__":
    main()
