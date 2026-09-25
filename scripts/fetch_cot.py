#!/usr/bin/env python3
"""CFTC 持倉報告（COT，legacy futures-only，每週二持倉、週五公布）：貨幣期貨的非商業／商業／未報告多空與未平倉量。
來源 https://www.cftc.gov/files/dea/history/deacot1986_2016.zip 與 deacot<年>.zip（annual.txt）。
輸出 data_forex_rates/cot/cot_currencies.csv（只留貨幣與美元指數合約；小檔，進 git）。沙盒連不到 CFTC，在 Actions 跑。

    python3 scripts/fetch_cot.py
"""
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_rates" / "cot"
BASE = "https://www.cftc.gov/files/dea/history"
KEYWORDS = ["EURO FX", "JAPANESE YEN", "BRITISH POUND", "SWISS FRANC", "CANADIAN DOLLAR", "AUSTRALIAN DOLLAR",
            "NZ DOLLAR", "NEW ZEALAND DOLLAR", "MEXICAN PESO", "BRAZILIAN REAL", "RUSSIAN RUBLE", "SO AFRICAN RAND",
            "SOUTH AFRICAN RAND", "U.S. DOLLAR INDEX", "USD INDEX", "DOLLAR INDEX"]
KEEP = {"Market and Exchange Names": "market", "As of Date in Form YYYY-MM-DD": "date", "CFTC Contract Market Code": "code",
        "Open Interest (All)": "oi", "Noncommercial Positions-Long (All)": "nc_long", "Noncommercial Positions-Short (All)": "nc_short",
        "Noncommercial Positions-Spreading (All)": "nc_spread", "Commercial Positions-Long (All)": "c_long",
        "Commercial Positions-Short (All)": "c_short", "Nonreportable Positions-Long (All)": "nr_long",
        "Nonreportable Positions-Short (All)": "nr_short"}


def fetch_zip(name: str) -> pd.DataFrame | None:
    r = requests.get(f"{BASE}/{name}", timeout=120)
    if r.status_code != 200:
        print(f"{name}: HTTP {r.status_code}")
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    txt = [n for n in z.namelist() if n.lower().endswith(".txt")][0]
    df = pd.read_csv(z.open(txt), low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in KEEP if c not in df.columns]
    if missing:
        print(f"{name}: 缺欄 {missing}；有的欄：{list(df.columns)[:12]}")
        return None
    df = df[list(KEEP)].rename(columns=KEEP)
    df["market"] = df["market"].str.strip().str.upper()
    df = df[df["market"].apply(lambda m: any(k in m for k in KEYWORDS))]
    print(f"{name}: {len(df)} 列貨幣合約")
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    year = datetime.now(timezone.utc).year
    parts = []
    for name in ["deacot1986_2016.zip"] + [f"deacot{y}.zip" for y in range(2017, year + 1)]:
        try:
            df = fetch_zip(name)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: {exc!r}")
            df = None
        if df is not None:
            parts.append(df)
    if not parts:
        sys.exit(1)
    df = pd.concat(parts).drop_duplicates(["date", "code"]).sort_values(["date", "code"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.to_csv(OUT / "cot_currencies.csv", index=False)
    summary = df.groupby(["code", "market"]).agg(first=("date", "min"), last=("date", "max"), n=("date", "size")).reset_index()
    summary.to_csv(OUT / "_markets.csv", index=False)
    print(summary.to_string())


if __name__ == "__main__":
    main()
