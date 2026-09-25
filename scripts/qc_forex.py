#!/usr/bin/env python3
"""外匯數據品質檢查（data_forex/<PAIR>/ → forex_research/data_qc/<PAIR>_qc.md + .json；--summary 彙總成 DATA_QC.md）。

    python3 scripts/qc_forex.py --pair EURUSD USDJPY        # 指定商品
    python3 scripts/qc_forex.py --all                       # data_forex/ 裡全部
    python3 scripts/qc_forex.py --summary                   # 只重建 forex_research/DATA_QC.md（讀已有的 .json）

檢查項目（全部不用外網；第二來源已由 fetch_forex.py 一併存在資料夾裡）：
1. 覆蓋：起迄、各框架根數、逐年 M1 根數與交易日數
2. 結構：重複、OHLC 矛盾（高 < max(開,收)、低 > min(開,收)）、非正價、零波幅 K 線比例
3. 尖刺：M1 相鄰收市價變動 > 1%（貴金屬 2%）的根數與最大幾筆
4. 缺口：平日（週一 00:00 → 週五 21:00 UTC）沒有任何 M1 的小時數、最長缺口
5. 內部一致：M1 按 UTC 日聚合的日線 vs Dukascopy 自己的 D1（開高低收各自吻合率）——看 D1 的日界是否 UTC
6. 點差：H1 賣價收市 − 買價收市（pips），按年中位、按時段中位、95 百分位；入場券指標 = 日均波幅 ÷ 點差（手冊鐵律 2）
7. 第二來源：Yahoo 日線收市 vs D1 收市；FRED 紐約中午匯率 vs H1 16:00／17:00 UTC 收市（取較近者）
8. XAUUSD 另外對 data/ 的券商 MT5 H1（券商時間 UTC+2／+3，逐月自動判斷）
"""
import argparse
import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_forex"
REPORT = ROOT / "forex_research" / "data_qc"
SUMMARY = ROOT / "forex_research" / "DATA_QC.md"


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.read_csv(path, parse_dates=["Time"]).set_index("Time")
    return df[~df.index.duplicated()].sort_index()


def load_m1(d: Path, pair: str) -> tuple[pd.DataFrame, dict, int, pd.DataFrame]:
    """HistData 年檔（<PAIR>_M1_<YYYY>，5 欄）+ Dukascopy 近期檔（<PAIR>_M1_recent）；回傳合併 M1、逐年根數、重複數、近期檔。"""
    parts, per_year, dup = [], {}, 0
    for p in sorted(d.glob(f"{pair}_M1_*.csv.gz")):
        m = re.fullmatch(rf"{pair}_M1_(\d{{4}})\.csv\.gz", p.name)
        if not m:
            continue
        df = pd.read_csv(p, parse_dates=["Time"]).set_index("Time")
        dup += int(df.index.duplicated().sum())
        df = df[~df.index.duplicated()]
        per_year[int(m.group(1))] = len(df)
        parts.append(df)
    recent = load(d / f"{pair}_M1_recent.csv.gz")
    if not recent.empty:
        parts.append(recent)
    if not parts:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]), {}, 0, recent
    m1 = pd.concat(parts)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()      # HistData 優先，近期檔補尾
    return m1, per_year, dup, recent


def structure(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"rows": 0}
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    return {"rows": int(len(df)),
            "bad_high": int((h < np.maximum(o, c) - 1e-12).sum()),
            "bad_low": int((l > np.minimum(o, c) + 1e-12).sum()),
            "nonpositive": int((np.minimum.reduce([o, h, l, c]) <= 0).sum()),
            "zero_range_pct": round(float((h == l).mean() * 100), 2)}


def pct(a, b):
    return (np.asarray(a, float) / np.asarray(b, float) - 1) * 100


def qc_pair(pair: str, decimals: int) -> dict:
    d = DATA / pair
    res = {"pair": pair, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    d1, d1a = load(d / f"{pair}_D1.csv.gz"), load(d / f"{pair}_D1_ask.csv.gz")
    h1, h1a = load(d / f"{pair}_H1.csv.gz"), load(d / f"{pair}_H1_ask.csv.gz")
    m1, per_year, m1_dup, recent = load_m1(d, pair)
    if d1.empty:
        res["error"] = "沒有 D1"
        return res
    pip = 10.0 ** -(decimals - 1)
    res["first"], res["last"] = str(d1.index[0].date()), str(d1.index[-1].date())
    res["d1_rows"], res["h1_rows"], res["m1_rows"] = len(d1), len(h1), len(m1)
    res["m1_first"] = str(m1.index[0]) if not m1.empty else None
    res["m1_last"] = str(m1.index[-1]) if not m1.empty else None
    res["m1_per_year"] = {str(y): n for y, n in per_year.items()}
    res["m1_recent"] = {"rows": int(len(recent)), "first": str(recent.index[0]) if len(recent) else None,
                        "last": str(recent.index[-1]) if len(recent) else None}
    hd = m1[m1["Volume"].isna()] if "Volume" in m1 else m1.iloc[0:0]      # HistData 沒有成交量欄 → 用來辨認來源
    if not hd.empty and not h1.empty:
        hc = hd["Close"].groupby(hd.index.floor("h")).last()
        tries = {}
        for shift in (-1, 0, 1):
            s2 = hc.copy()
            s2.index = s2.index + pd.Timedelta(hours=shift)
            j = s2.to_frame("hd").join(h1["Close"].to_frame("duka"), how="inner")
            ad = np.abs(pct(j["hd"], j["duka"]))
            tries[shift] = {"hours": int(len(j)), "median_abs_pct": round(float(np.median(ad)), 4) if len(j) else None,
                            "within_0.05pct": round(float((ad <= 0.05).mean() * 100), 1) if len(j) else None}
        best = min((k for k in tries if tries[k]["hours"]), key=lambda k: tries[k]["median_abs_pct"], default=0)
        j = hc.to_frame("hd").join(h1["Close"].to_frame("duka"), how="inner")
        ad = pd.Series(np.abs(pct(j["hd"], j["duka"])), index=j.index)
        by_year = ad.groupby(ad.index.year).median().round(4)
        res["hd_vs_duka"] = {"hours": int(len(j)), "median_abs_pct": tries[0]["median_abs_pct"], "p99_abs_pct": round(float(ad.quantile(0.99)), 3) if len(j) else None,
                             "within_0.05pct": tries[0]["within_0.05pct"], "best_shift_h": int(best), "shifts": tries,
                             "by_year": {str(k): float(v) for k, v in by_year.items()},
                             "worst": [(str(t), round(float(v), 2)) for t, v in ad.sort_values(ascending=False).head(5).items()]}
    res["m1_days_per_year"] = {str(y): int(n) for y, n in m1.groupby(m1.index.year).apply(
        lambda g: g.index.normalize().nunique()).items()} if not m1.empty else {}
    res["struct"] = {"D1": structure(d1), "H1": structure(h1), "M1": structure(m1) | {"dup": m1_dup}}

    # 尖刺
    if not m1.empty:
        thr = 2.0 if pair.startswith("XA") else 1.0
        r = m1["Close"].pct_change().abs() * 100
        big = r[r > thr].sort_values(ascending=False)
        res["spikes"] = {"threshold_pct": thr, "count": int(len(big)),
                         "top": [(str(t), round(float(v), 3)) for t, v in big.head(8).items()]}
        # 缺口：平日小時沒有 M1
        hours = pd.Series(1, index=m1.index.floor("h")).groupby(level=0).size()
        full = pd.date_range(m1.index[0].floor("h"), m1.index[-1].floor("h"), freq="h")
        wk = full[(full.weekday < 5) & ~((full.weekday == 4) & (full.hour >= 21))]
        missing = wk.difference(hours.index)
        gaps = []
        if len(missing):
            start = prev = missing[0]
            for t in missing[1:]:
                if (t - prev) != pd.Timedelta(hours=1):
                    gaps.append((start, prev))
                    start = t
                prev = t
            gaps.append((start, prev))
        gaps = sorted(gaps, key=lambda g: g[0] - g[1])
        res["gaps"] = {"weekday_hours_missing": int(len(missing)), "weekday_hours_total": int(len(wk)),
                       "runs": int(len(gaps)),
                       "longest": [(str(a), str(b), int((b - a) / pd.Timedelta(hours=1)) + 1) for a, b in gaps[:8]]}
        # M1 聚合日線 vs D1（UTC 日界）
        agg = m1.groupby(m1.index.normalize()).agg(Open=("Open", "first"), High=("High", "max"),
                                                    Low=("Low", "min"), Close=("Close", "last"))
        j = agg.join(d1, how="inner", lsuffix="_m", rsuffix="_d")
        res["d1_vs_m1"] = {"days": int(len(j))} | {k: round(float((abs(j[f"{k}_m"] / j[f"{k}_d"] - 1) <= 0.0005).mean() * 100), 1)
                                                  for k in ("Open", "High", "Low", "Close")} if len(j) else {"days": 0}

    # 點差（H1 ask − bid 收市，pips）
    if not h1.empty and not h1a.empty:
        sp = (h1a["Close"] - h1["Close"]).dropna() / pip
        sp = sp[sp > -1]                                        # 極少數負值＝檔案錯位，剔除後另計
        by_year = sp.groupby(sp.index.year).median().round(2)
        by_hour = sp.groupby(sp.index.hour).median().round(2)
        recent = sp[sp.index >= sp.index[-1] - pd.Timedelta(days=365 * 3)]
        rng = ((d1["High"] - d1["Low"]) / pip)
        rng3 = rng[rng.index >= rng.index[-1] - pd.Timedelta(days=365 * 3)]
        res["spread"] = {"pip": pip, "median_all": round(float(sp.median()), 2), "median_3y": round(float(recent.median()), 2),
                         "p95_3y": round(float(recent.quantile(0.95)), 2), "negative": int(((h1a["Close"] - h1["Close"]) < 0).sum()),
                         "by_year": {str(k): float(v) for k, v in by_year.items()},
                         "by_hour": {str(k): float(v) for k, v in by_hour.items()},
                         "daily_range_3y_pips": round(float(rng3.median()), 1),
                         "range_over_spread_3y": round(float(rng3.median() / max(recent.median(), 1e-9)), 1)}

    # 第二來源
    y = d / "_ref_yahoo.csv.gz"
    if y.exists():
        ref = pd.read_csv(y, parse_dates=["Date"]).set_index("Date")["Close"].dropna()
        j = d1["Close"].to_frame("duka").join(ref.to_frame("yahoo"), how="inner")
        j = j[j["yahoo"] > 0]
        if len(j):
            diff = pct(j["yahoo"], j["duka"]).astype(float)
            ad = np.abs(diff)
            worst = j.assign(diff=diff).iloc[np.argsort(-ad)[:5]]
            res["yahoo"] = {"days": int(len(j)), "first": str(j.index[0].date()), "last": str(j.index[-1].date()),
                            "median_abs_pct": round(float(np.median(ad)), 3), "p99_abs_pct": round(float(np.percentile(ad, 99)), 3),
                            "over_0.5pct": int((ad > 0.5).sum()), "over_2pct": int((ad > 2).sum()),
                            "worst": [(str(t.date()), round(float(v), 2)) for t, v in worst["diff"].items()]}
    f = d / "_ref_fred.csv.gz"
    if f.exists() and not h1.empty:
        ref = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Close"].dropna()
        c16 = h1["Close"][h1.index.hour == 16]
        c17 = h1["Close"][h1.index.hour == 17]
        c16.index, c17.index = c16.index.normalize(), c17.index.normalize()
        j = ref.to_frame("fred").join(c16.to_frame("h16"), how="inner").join(c17.to_frame("h17"), how="left")
        if len(j):
            d16, d17 = np.abs(pct(j["fred"], j["h16"])), np.abs(pct(j["fred"], j["h17"].fillna(j["h16"])))
            ad = np.minimum(d16, d17)
            res["fred"] = {"days": int(len(j)), "first": str(j.index[0].date()), "last": str(j.index[-1].date()),
                           "median_abs_pct": round(float(np.median(ad)), 3), "p99_abs_pct": round(float(np.percentile(ad, 99)), 3),
                           "over_0.5pct": int((ad > 0.5).sum()), "over_2pct": int((ad > 2).sum()),
                           "worst": [(str(j.index[i].date()), round(float(ad[i]), 2)) for i in np.argsort(-ad)[:5]]}

    # XAUUSD：對券商 MT5 H1（data/XAUUSD_H1.csv.gz，券商時間；逐月試 UTC+2／+3）
    bp = ROOT / "data" / f"{pair}_H1.csv.gz"
    if bp.exists() and not h1.empty:
        with gzip.open(bp, "rt") as fh:
            b = pd.read_csv(fh)
        b["Time"] = pd.to_datetime(b["Time"], format="%Y.%m.%d %H:%M:%S")
        b = b.set_index("Time")["Close"]
        months = {}
        for off in (2, 3):
            s = b.copy()
            s.index = s.index - pd.Timedelta(hours=off)
            j = s.to_frame("broker").join(h1["Close"].to_frame("duka"), how="inner")
            ad = np.abs(pct(j["broker"], j["duka"]))
            for m, v in pd.Series(ad, index=j.index).groupby(j.index.to_period("M")):
                months.setdefault(str(m), {})[off] = (float(v.median()), int(len(v)))
        pick = {m: min(v, key=lambda o: v[o][0]) for m, v in months.items()}
        med = [months[m][pick[m]][0] for m in months]
        n = sum(months[m][pick[m]][1] for m in months)
        res["broker"] = {"hours": n, "median_abs_pct": round(float(np.median(med)), 4) if med else None,
                         "worst_month_pct": round(float(max(med)), 3) if med else None,
                         "offset_by_month": pick}
    return res


def render(r: dict) -> str:
    L = [f"# {r['pair']} 數據品質（{r['generated']}）", ""]
    if "error" in r:
        return "\n".join(L + [r["error"], ""])
    rc = r.get("m1_recent", {})
    L += [f"- 覆蓋：Dukascopy D1 {r['first']} → {r['last']}（{r['d1_rows']} 根）、H1 {r['h1_rows']} 根；"
          f"M1 {r['m1_rows']} 根（{r['m1_first']} → {r['m1_last']}；HistData 年檔 {len(r['m1_per_year'])} 個 + "
          f"Dukascopy 近期檔 {rc.get('rows', 0)} 根 {rc.get('first')} → {rc.get('last')}）", "",
          "## 1. 逐年 M1", "", "| 年 | M1 根數 | 有數據的日數 |", "|---|---:|---:|"]
    for y in sorted(r["m1_per_year"]):
        L.append(f"| {y} | {r['m1_per_year'][y]:,} | {r['m1_days_per_year'].get(y, 0)} |")
    L += ["", "## 2. 結構", "", "| 框架 | 根數 | 高<max(開收) | 低>min(開收) | 非正價 | 零波幅 % | 重複 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, s in r["struct"].items():
        if s.get("rows"):
            L.append(f"| {k} | {s['rows']:,} | {s['bad_high']} | {s['bad_low']} | {s['nonpositive']} | {s['zero_range_pct']} | {s.get('dup', 0)} |")
    if "spikes" in r:
        s = r["spikes"]
        L += ["", f"## 3. 尖刺（M1 相鄰收市變動 > {s['threshold_pct']}%）：{s['count']} 根", ""]
        L += [f"- {t}：{v:+.3f}%" for t, v in s["top"]]
    if "gaps" in r:
        g = r["gaps"]
        L += ["", f"## 4. 缺口：平日 {g['weekday_hours_total']:,} 小時中 {g['weekday_hours_missing']:,} 小時沒有 M1"
              f"（{g['weekday_hours_missing'] / max(g['weekday_hours_total'], 1) * 100:.2f}%，{g['runs']} 段）", ""]
        L += [f"- {a} → {b}（{n} 小時）" for a, b, n in g["longest"]]
    if "d1_vs_m1" in r:
        v = r["d1_vs_m1"]
        L += ["", f"## 5. M1（HistData）按 UTC 日聚合 vs Dukascopy D1（{v['days']} 天，容差 0.05%）", ""]
        if v["days"]:
            L.append(f"- 開 {v['Open']}%、高 {v['High']}%、低 {v['Low']}%、收 {v['Close']}% 吻合")
    if "hd_vs_duka" in r:
        v = r["hd_vs_duka"]
        L += ["", f"## 5b. HistData M1 聚合 vs Dukascopy H1 收市（{v['hours']:,} 小時）", "",
              f"- 絕對差中位 {v['median_abs_pct']}%、99 百分位 {v['p99_abs_pct']}%、{v['within_0.05pct']}% 小時在 0.05% 內；"
              f"時差試 −1／0／+1 小時最佳為 {v['best_shift_h']:+d}（0 = HistData 紐約當地時間含夏令轉 UTC 正確）",
              "- 逐年中位差%：" + "、".join(f"{k} {x}" for k, x in v["by_year"].items()),
              "- 最大：" + "、".join(f"{t} {x}%" for t, x in v["worst"])]
    if "spread" in r:
        s = r["spread"]
        L += ["", "## 6. 點差（H1 賣價收市 − 買價收市，pips；1 pip = " + f"{s['pip']:g}）", "",
              f"- 全期中位 {s['median_all']}、近 3 年中位 {s['median_3y']}、近 3 年 95 百分位 {s['p95_3y']}；負值 {s['negative']} 根",
              f"- 近 3 年日均波幅中位 {s['daily_range_3y_pips']} pips → **波幅 ÷ 點差 = {s['range_over_spread_3y']} 倍**（手冊鐵律 2：> 80 才夠格）",
              "", "| 年 | " + " | ".join(sorted(s["by_year"])) + " |", "|---|" + "---:|" * len(s["by_year"]),
              "| 點差中位 | " + " | ".join(f"{s['by_year'][k]}" for k in sorted(s["by_year"])) + " |", "",
              "| UTC 時 | " + " | ".join(f"{h:0>2}" for h in sorted(s["by_hour"], key=int)) + " |",
              "|---|" + "---:|" * len(s["by_hour"]),
              "| 點差中位 | " + " | ".join(f"{s['by_hour'][k]}" for k in sorted(s["by_hour"], key=int)) + " |"]
    for key, title in (("yahoo", "Yahoo 日線收市 vs D1 收市"), ("fred", "FRED 紐約中午匯率 vs H1 16／17 時收市")):
        if key in r:
            v = r[key]
            L += ["", f"## 7. {title}（{v['days']} 天，{v['first']} → {v['last']}）", "",
                  f"- 絕對差中位 {v['median_abs_pct']}%、99 百分位 {v['p99_abs_pct']}%；> 0.5% 有 {v['over_0.5pct']} 天、> 2% 有 {v['over_2pct']} 天",
                  "- 最大：" + "、".join(f"{t} {x:+.2f}%" for t, x in v["worst"])]
    if "broker" in r:
        b = r["broker"]
        offs = pd.Series(b["offset_by_month"])
        L += ["", f"## 8. 對券商 MT5 H1（data/）：{b['hours']:,} 小時，收市絕對差中位 {b['median_abs_pct']}%、最差月 {b['worst_month_pct']}%", "",
              f"- 券商時差逐月判斷：UTC+2 {int((offs == 2).sum())} 個月、UTC+3 {int((offs == 3).sum())} 個月"]
    return "\n".join(L) + "\n"


def summary() -> None:
    rows = []
    for p in sorted(REPORT.glob("*_qc.json")):
        rows.append(json.loads(p.read_text()))
    L = ["# 外匯數據品質總表（DATA_QC.md）", "",
         f"由 `scripts/qc_forex.py --summary` 於 {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC 重建；逐商品細節在 `data_qc/<PAIR>_qc.md`。",
         "數據取得：`python3 scripts/get_forex_data.py`；目錄與注意事項：FOREX_DATA_CATALOG.md。", "",
         "| 商品 | 起 | M1 起 | M1 根數 | 缺口小時% | 尖刺 | D1 收吻合% | HistData vs Duka H1 中位差% | 點差中位(3年) | 波幅÷點差 | Yahoo 中位差% | FRED 中位差% | Yahoo>0.5% 天 |",
         "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        if "error" in r:
            L.append(f"| {r['pair']} | — | — | — | — | — | — | — | — | — | — | — | {r['error']} |")
            continue
        g, s, v = r.get("gaps", {}), r.get("spread", {}), r.get("d1_vs_m1", {})
        L.append(f"| {r['pair']} | {r['first']} | {(r.get('m1_first') or '—')[:10]} | {r['m1_rows']:,} | "
                 f"{g.get('weekday_hours_missing', 0) / max(g.get('weekday_hours_total', 1), 1) * 100:.2f} | "
                 f"{r.get('spikes', {}).get('count', '—')} | {v.get('Close', '—')} | {r.get('hd_vs_duka', {}).get('median_abs_pct', '—')} | {s.get('median_3y', '—')} | "
                 f"{s.get('range_over_spread_3y', '—')} | {r.get('yahoo', {}).get('median_abs_pct', '—')} | "
                 f"{r.get('fred', {}).get('median_abs_pct', '—')} | {r.get('yahoo', {}).get('over_0.5pct', '—')} |")
    L += ["", "- M1 = HistData 年檔（紐約當地時間含夏令已轉 UTC，沒有成交量，壞 tick 已丟）+ Dukascopy 近期檔；HistData vs Duka H1 = HistData M1 按 UTC 小時取收市 vs Dukascopy H1 收市的絕對差中位（兩個獨立來源互相核對）",
          "- 缺口小時% = 平日（週一 00:00 → 週五 21:00 UTC）沒有任何 M1 的小時比例（含假期，不代表數據錯）",
          "- D1 收吻合% = HistData M1 按 UTC 日聚合的收市 vs Dukascopy D1 收市在 0.05% 內的比例（兩個來源；低 → 時區或日界有問題）",
          "- 波幅÷點差 = 近 3 年日均高低差中位 ÷ H1 點差中位（手冊鐵律 2 的入場券：> 80 倍；CFD 實際點差通常比 Dukascopy 寬，要按自己券商換算）",
          "- Yahoo／FRED 差 = 收市（或紐約中午）價與 Dukascopy 對應時點的絕對百分比差中位；Yahoo 日界與 Dukascopy 不同，0.1–0.3% 屬正常，只看 > 2% 的離群天", ""]
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text("\n".join(L), encoding="utf-8")
    print(f"總表：{SUMMARY}（{len(rows)} 個商品）")


def main() -> None:
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from fetch_forex import INSTRUMENTS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--report-dir", type=Path, default=REPORT)
    args = ap.parse_args()
    pairs = args.pair or ([p.name for p in sorted(DATA.iterdir()) if p.is_dir() and p.name in INSTRUMENTS] if args.all else [])
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for p in pairs:
        dec = INSTRUMENTS[p][1]
        if dec is None:                                   # em 組：小數位由 fetch_forex.py 首次抓時判定、記在 _done.json
            done_p = DATA / p / "_done.json"
            dec = (json.loads(done_p.read_text()).get("decimals") if done_p.exists() else None) or 5
        r = qc_pair(p, dec)
        (args.report_dir / f"{p}_qc.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        (args.report_dir / f"{p}_qc.md").write_text(render(r), encoding="utf-8")
        msg = "錯誤 " + r["error"] if "error" in r else f"M1 {r['m1_rows']:,} 根、{r['first']} → {r['last']}"
        print(f"{p}：{msg}")
    if args.summary or (pairs and args.report_dir == REPORT):
        summary()


if __name__ == "__main__":
    main()
