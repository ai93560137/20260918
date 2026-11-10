"""匯入總指揮 11-10 轉交嘅券商 MT5 全品種歷史（GCS xau/data/mt5/max/MAX.zip，16 品種 × 7 時框，伺服器時間）入研究快取。
只讀研究，唔改真倉；唔刪、唔覆寫 GCS 任何已有物件（已存在就跳過）。

時區（11-10 核實，見 MT5_MAX_IMPORT.md）：伺服器時間 = UTC+2（冬）／UTC+3（美國夏令期間）——同 import_mt5.py 一樣；
SUMMARY.csv 嘅「server_minus_utc_sec=7200」只係匯出嗰刻（11 月，冬令）嘅差，唔係全期固定，所以 export.zip 嘅 utc 欄喺夏令月份差 1 小時，唔用。

輸出（GCS，data_cache.put 格式 t/o/h/l/c）：
- xau/sig/cache/mt5x/<品種>_m1_<年>.npz（完整年份；2022 由開始日起）
- xau/sig/cache/mt5x/<品種>_m1_2026p.npz（2026-01-01 → 匯出時，未完整）
- xau/sig/mt5m1/<日>.json：黃金只補舊匯入之後、匯出日之前嘅完整日子（格式同 import_mt5.py）
用法：python3 research/student_offline/import_mt5_max.py <解壓後 MAX 目錄> [--dry-run] → research/student_offline/MT5_MAX_IMPORT.md"""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_cache as DC  # noqa: E402

OUT = os.path.join(HERE, "MT5_MAX_IMPORT.md")
SYMS = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY",
        "NAS100", "GER40", "UK100", "CL-OIL", "BTCUSD"]
SUB = "mt5x/"


def server_to_utc(ts):
    """ts＝伺服器時間（naive pandas Series）→ UTC 秒。伺服器＝紐約時間＋7 小時（跟美國夏令）。"""
    ny = (ts - pd.Timedelta(hours=7)).dt.tz_localize("America/New_York", ambiguous=np.ones(len(ts), bool), nonexistent="shift_forward")
    u = ny.dt.tz_convert("UTC").dt.tz_localize(None)
    return ((u - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)


def server_to_utc_rule(ts):
    """import_mt5.py 原本嘅規則（向量化）：先估 UTC+2，嗰刻紐約夏令就 +3。用嚟對照。"""
    g = (ts - pd.Timedelta(hours=2)).dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    off = np.where([bool(x.dst()) for x in g], 3, 2)
    return (((ts - pd.to_timedelta(off, unit="h")) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)


def load(path):
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["Time"], format="%Y.%m.%d %H:%M:%S")
    t = server_to_utc(ts)
    d = {"t": t.astype(np.int64), "o": df["Open"].to_numpy(float), "h": df["High"].to_numpy(float),
         "l": df["Low"].to_numpy(float), "c": df["Close"].to_numpy(float), "v": df["Volume"].to_numpy(np.int64)}
    order = np.argsort(d["t"], kind="stable"); d = {k: v[order] for k, v in d.items()}
    keep = np.r_[True, np.diff(d["t"]) > 0]
    return {k: v[keep] for k, v in d.items()}, ts


def year_of(t):
    return np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year for x in t[[0, -1]]])


def cmp(A, B):
    _, ia, ib = np.intersect1d(A["t"], B["t"], return_indices=True)
    if not len(ia):
        return 0, float("nan"), float("nan")
    d = np.abs(A["c"][ia] - B["c"][ib])
    return len(d), float(np.median(d)), float(np.quantile(d, 0.9))


def main():
    src = sys.argv[1]; dry = "--dry-run" in sys.argv
    now = dt.datetime.now(dt.timezone.utc)
    L = ["# 券商 MT5 全品種歷史匯入（總指揮 11-10 轉交 MAX.zip）", "",
         f"- 更新 {now:%Y-%m-%d %H:%M} UTC；來源 GCS `xau/data/mt5/max/MAX.zip`（原檔保留，冇刪）；只讀研究，唔改真倉",
         "- 時區：伺服器＝UTC+2（冬）／UTC+3（美國夏令）。SUMMARY 寫嘅 7200 秒只係匯出嗰刻（冬令）；`export.zip` 嘅 utc 欄夏令月差 1 小時 → **唔用**",
         f"- 快取：GCS `xau/sig/cache/{SUB}<品種>_m1_<年>.npz`（t／o／h／l／c；2026 未完整年叫 `_2026p`）；已存在嘅物件唔覆寫", "",
         "| 品種 | 根數 | 由（UTC） | 到（UTC） | 寫入快取 |", "|---|---|---|---|---|"]
    gold = silver = None
    for sym in SYMS:
        p = os.path.join(src, f"{sym}_M1_MAX.csv")
        if not os.path.exists(p):
            L.append(f"| {sym} | — | — | — | 冇檔 |"); continue
        d, ts = load(p)
        if sym == "XAUUSD":
            gold = d
            rule = server_to_utc_rule(ts.iloc[::997].reset_index(drop=True))
            vec = server_to_utc(ts.iloc[::997].reset_index(drop=True))
            L_rule = int((rule != vec).sum())
        if sym == "XAGUSD":
            silver = d
        y0, y1 = year_of(d["t"]); wrote = []
        yrs = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year for x in d["t"]])
        for y in range(y0, y1 + 1):
            m = yrs == y
            if not m.any():
                continue
            name = f"{SUB}{sym}_m1_{y}{'p' if y == now.year else ''}.npz"
            part = {k: v[m] for k, v in d.items()}
            if dry:
                wrote.append(f"{y}（dry）"); continue
            if DC.exists(name):
                wrote.append(f"{y} 已有"); continue
            DC.put(name, part); wrote.append(str(y))
        f = lambda x: dt.datetime.fromtimestamp(int(x), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")  # noqa: E731
        L.append(f"| {sym} | {len(d['t']):,} | {f(d['t'][0])} | {f(d['t'][-1])} | {'、'.join(wrote)} |")
        print(sym, len(d["t"]), flush=True)

    L += ["", "## 黃金核對", "", "| 對照 | 重疊根數 | 收市差中位 | 90% |", "|---|---|---|---|"]
    for y in (2022, 2023, 2024, 2025):
        old = DC.get(f"m1_mt5_{y}.npz")
        if old is not None:
            n, med, q = cmp(gold, old); L.append(f"| 新匯出 vs 舊 mt5m1 快取 {y} | {n:,} | {med:.3f} | {q:.3f} |")
    for y in range(2022, 2023):
        du = DC.get(f"m1_duka_{y}.npz")
        if du is not None:
            n, med, q = cmp(gold, du); L.append(f"| 新匯出 vs Dukascopy M1 {y} | {n:,} | {med:.3f} | {q:.3f} |")
    L += ["", "## 時區核對（M1 合成 H1 收市 vs Dukascopy H1；「固定 +2」＝SUMMARY 寫嘅 7200 秒全期套用）", "",
          "| 品種 | 年 | 重疊小時 | 夏令規則差中位 | 固定 +2 差中位 |", "|---|---|---|---|---|"]
    for sym, d, dk in (("XAUUSD", gold, "gold"), ("XAGUSD", silver, "silver")):
        hk = d["t"] // 3600; last = np.r_[hk[1:] != hk[:-1], True]
        H = {"t": hk[last] * 3600, "c": d["c"][last]}
        for y in (2022, 2023, 2024, 2025):
            du = DC.get(f"h1_{dk}_{y}.npz")
            if du is None:
                continue
            n, med, _ = cmp(H, du)
            # 固定 +2：夏令月份等於將 UTC 時間推後 1 小時
            summer = np.array([bool(dt.datetime.fromtimestamp(int(x), dt.timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).dst()) for x in H["t"]])
            F = {"t": H["t"] + 3600 * summer, "c": H["c"]}
            _, med2, _ = cmp(F, du)
            L.append(f"| {sym} | {y} | {n:,} | {med:.3f} | {med2:.3f} |")
    L += ["", f"- 向量化時區轉換同 import_mt5.py 原規則抽樣比較：{L_rule} 根唔同（應該係 0）", ""]

    # 黃金每日 JSON：補舊匯入（到 10-30）之後、匯出當日之前嘅完整日子
    days = {}
    for row in zip(gold["t"], gold["o"], gold["h"], gold["l"], gold["c"], gold["v"]):
        k = dt.datetime.fromtimestamp(int(row[0]), dt.timezone.utc).date().isoformat()
        if "2026-10-31" <= k < now.date().isoformat() and k < f"{dt.datetime.fromtimestamp(int(gold['t'][-1]), dt.timezone.utc).date()}":
            days.setdefault(k, []).append([int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(row[5])])
    added = []
    if not dry:
        b = DC._bucket()
        for k, rows in sorted(days.items()):
            bl = b.blob(f"xau/sig/mt5m1/{k}.json")
            if bl.exists():
                continue
            bl.upload_from_string(json.dumps(rows), content_type="application/json"); added.append(f"{k}（{len(rows)}）")
    L += [f"- 黃金每日 `xau/sig/mt5m1/` 補：{'、'.join(added) if added else ('dry-run 未寫' if dry else '冇')}", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
