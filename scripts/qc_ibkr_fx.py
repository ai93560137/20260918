#!/usr/bin/env python3
"""驗收雲垂分支交付的 IBKR 外匯數據（data_forex_ibkr/）。需求與驗收項目：forex_research/IBKR_DATA_REQUEST.md 第 4 節。

    git checkout origin/claude/dazzling-curie-f3xzb8 -- data_forex_ibkr     # 取數據（工作樹，不必 commit）
    python3 scripts/qc_ibkr_fx.py                                            # → forex_research/data_qc/ibkr_qc_tables.md、ibkr_qc.json（結論另寫 IBKR_DATA_QC.md）

只做數據完整性與跨來源核對，**刻意不計算「隱含波動 − 之後的實現波動」**：那是波動溢價的檢定本身，
要等預先登記之後才能看（見報告第 0 節）。
"""
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IB = ROOT / "data_forex_ibkr"
DK = ROOT / "data_forex"
RATES = ROOT / "data_forex_rates"
OUT_TABLES = ROOT / "forex_research" / "data_qc" / "ibkr_qc_tables.md"   # 自動產生的表；結論寫在 forex_research/IBKR_DATA_QC.md
OUT_JSON = ROOT / "forex_research" / "data_qc" / "ibkr_qc.json"
SPOTS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
PIP = {p: (0.01 if p.endswith("JPY") else 0.0001) for p in SPOTS}
# 期貨貨幣 → (現貨對, 期貨報價 = 每單位外幣多少美元時現貨要不要取倒數, FRED 利率貨幣)
FUT = {"EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False), "NZD": ("NZDUSD", False),
       "JPY": ("USDJPY", True), "CHF": ("USDCHF", True), "CAD": ("USDCAD", True), "MXN": ("USDMXN", True)}
RATE_ID = {"USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N", "AUD": "IR3TIB01AUM156N",
           "NZD": "IR3TIB01NZM156N", "JPY": "IR3TIB01JPM156N", "CHF": "IR3TIB01CHM156N", "CAD": "IR3TIB01CAM156N",
           "MXN": "IR3TIB01MXM156N"}
CT = ZoneInfo("America/Chicago")


def rd(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["Time"]).set_index("Time").sort_index()


def histdata_m1(pair: str, start: str, end: str) -> pd.Series:
    """HistData M1 買價收市（UTC）。"""
    parts = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        f = DK / pair / f"{pair}_M1_{y}.csv.gz"
        if f.exists():
            parts.append(pd.read_csv(f, parse_dates=["Time"]).set_index("Time")["Close"])
    s = pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)
    return s[(s.index >= start) & (s.index <= end)]


def next_imm(d: pd.Timestamp) -> pd.Timestamp:
    """d 之後（含）最近一個 CME 外匯期貨最後交易日 = 3、6、9、12 月第三個星期三之前兩個營業日。"""
    for k in range(0, 15):
        y, m = d.year + (d.month - 1 + k) // 12, (d.month - 1 + k) % 12 + 1
        if m not in (3, 6, 9, 12):
            continue
        first = pd.Timestamp(y, m, 1)
        third_wed = first + pd.Timedelta(days=(2 - first.weekday()) % 7 + 14)
        ltd = third_wed - pd.offsets.BDay(2)
        if ltd >= d.normalize():
            return ltd
    raise RuntimeError


def spot_checks(res: dict) -> list[str]:
    L = ["## 2. 現貨 IDEALPRO 5 分鐘 BID_ASK（P1）", "",
         "IB 的 BID_ASK K 線：Open = 時段平均買價、Close = 時段平均賣價。點差 = Close − Open。",
         "對照 = HistData M1 買價（`data_forex/<PAIR>/`，2024-09 → 2026-08），按 5 分鐘取時段平均；位移測試 −5／0／+5 分鐘取差最小者。", "",
         "| 對 | 根數 | 起 → 迄 | 平日缺 5 分鐘比例 | 與 HistData 買價中位差（pip） | 最佳位移 | 價格最小跳動（pip） | IB 點差中位／平均（pip） | 12–16 UTC 平均 | 21–22 UTC 中位（換日） | 負點差根數 | Dukascopy 近 3 年點差中位（pip） |",
         "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in SPOTS:
        d = rd(IB / f"spot_{p}_M5_bid_ask.csv.gz")
        d = d[~d.index.duplicated()]
        bid, ask = d["Open"], d["Close"]
        sp = (ask - bid) / PIP[p]
        # 平日缺口：週一 00:00 → 週五 20:55 UTC 之間應有的 5 分鐘格
        full = pd.date_range(d.index[0].ceil("D"), d.index[-1].floor("D"), freq="5min")
        wk = full[(full.weekday < 4) | ((full.weekday == 4) & (full.hour < 21))]
        wk = wk[~((wk.weekday == 0) & (wk.hour < 1))]
        miss = 1 - len(wk.intersection(d.index)) / len(wk)
        hd = histdata_m1(p, str(d.index[0]), "2026-08-31")
        best = None
        for shift in (-5, 0, 5):
            hd5 = hd.resample("5min").mean()
            hd5.index = hd5.index + pd.Timedelta(minutes=shift)
            j = pd.concat([bid.rename("ib"), hd5.rename("hd")], axis=1, sort=True).dropna()
            diff = float((j.ib - j.hd).abs().median() / PIP[p])
            if best is None or diff < best[1]:
                best = (shift, diff, len(j))
        hr = sp.groupby(sp.index.hour).median()
        dq = json.loads((ROOT / "forex_research" / "data_qc" / f"{p}_qc.json").read_text())["spread"]["median_3y"]
        r = {"rows": len(d), "first": str(d.index[0]), "last": str(d.index[-1]), "weekday_missing": round(miss, 4),
             "hd_median_diff_pip": round(best[1], 2), "best_shift_min": best[0], "overlap_rows": best[2],
             "spread_median_pip": round(float(sp.median()), 2), "spread_mean_pip": round(float(sp.mean()), 3),
             "spread_mean_12_16": round(float(sp[(sp.index.hour >= 12) & (sp.index.hour < 16)].mean()), 3),
             "price_grid_pip": round(float(pd.Series(np.round(bid.diff().abs()[bid.diff().abs() > 0] / PIP[p], 3)).min()), 3),
             "spread_12_16": round(float(sp[(sp.index.hour >= 12) & (sp.index.hour < 16)].median()), 2),
             "spread_21_22": round(float(sp[(sp.index.hour >= 21) & (sp.index.hour < 23)].median()), 2),
             "spread_p95_pip": round(float(sp.quantile(0.95)), 2), "negative": int((sp < 0).sum()),
             "spread_by_hour": {int(k): round(float(v), 2) for k, v in hr.items()},
             "spread_by_year": {int(k): round(float(v), 2) for k, v in sp.groupby(sp.index.year).median().items()},
             "dukascopy_median_3y": dq}
        res["spot"][p] = r
        L.append(f"| {p} | {r['rows']:,} | {r['first'][:10]} → {r['last'][:10]} | {r['weekday_missing'] * 100:.2f}% | {r['hd_median_diff_pip']} | "
                 f"{r['best_shift_min']:+d} 分 | {r['price_grid_pip']} | {r['spread_median_pip']}／{r['spread_mean_pip']} | {r['spread_mean_12_16']} | {r['spread_21_22']} | {r['negative']} | {dq} |")
    return L


def fut_checks(res: dict) -> list[str]:
    rates = {c: pd.read_csv(RATES / f"{sid}.csv", parse_dates=["Date"]).set_index("Date")["Value"] for c, sid in RATE_ID.items()}
    L = ["## 3. 期貨連續合約日線（P0：TRADES、BID_ASK）與滾動收益", "",
         "**IB 的 ContFuture 歷史價是回溯調整過的連續價**：每次換月把價差加到之前所有價格上，所以「期貨 ÷ 現貨 − 1」不是當時的基差，"
         "而是當時的基差加上之後所有換月價差的累計（見 EUR、JPY 在一年內平滑下降、換月日沒有跳動）。基差水平不能用；"
         "但它的**斜率 = 這一年持有期貨實際拿到的滾動收益（年化）**，正是「期貨路徑的實際利差」。"
         "做法：調整後 (F/S − 1) 對時間（年）回歸，斜率取負號 = 年化滾動收益；現貨 = IB 5 分鐘 BID_ASK 在芝加哥 15:55 那根的中價（期貨日盤收市）。"
         "無套利下應 ≈ 美元三個月利率 − 外幣三個月利率（FRED，同期平均）；差額 = 期貨路徑相對利差的成本或收益（含跨幣基差）。", "",
         "| 貨幣 | 根數 | 起 → 迄 | 調整後 F/S−1 期初 → 期末（bp） | 年化滾動收益 %（斜率） | 擬合 R² | FRED 利差同期平均 % | 差（滾動收益 − 利差）% |",
         "|---|---:|---|---|---:|---:|---:|---:|"]
    for c, (pair, inv) in FUT.items():
        tr = rd(IB / f"fut_{c}_D1_trades.csv.gz")
        if c == "MXN":
            r = {"rows": len(tr), "invalid": "IB 的 MXP 連續合約解析成價格 1–3 的另一個商品（墨西哥披索期貨約 0.055），整組 MXN 檔作廢"}
            res["fut"][c] = r
            L.append(f"| MXN | {len(tr)} | — | — | — | — | — | **作廢**：{r['invalid']} |")
            continue
        s_ = rd(IB / f"spot_{pair}_M5_bid_ask.csv.gz")
        mid = (s_["Open"] + s_["Close"]) / 2
        loc = mid.index.tz_localize("UTC").tz_convert(CT)
        m = (loc.hour == 15) & (loc.minute == 55)
        pick = pd.Series(mid[m].values, index=pd.DatetimeIndex(loc[m].date))
        spot = (1.0 / pick) if inv else pick
        j = pd.concat([tr["Close"].rename("f"), spot.rename("s")], axis=1, sort=True).dropna()
        b = (j.f / j.s - 1) * 1e4
        t = np.asarray((j.index - j.index[0]).days, dtype=float) / 365.25
        slope, icpt = np.polyfit(t, b.values, 1)
        r2 = 1 - ((b.values - (slope * t + icpt)) ** 2).sum() / ((b.values - b.values.mean()) ** 2).sum()
        dr = float(np.mean([rates["USD"].asof(x) - rates[c].asof(x) for x in j.index]))
        carry = -slope / 100
        r = {"rows": len(tr), "first": str(tr.index[0])[:10], "last": str(tr.index[-1])[:10], "basis_start_bp": round(float(b.iloc[:5].mean()), 1),
             "basis_end_bp": round(float(b.iloc[-5:].mean()), 1), "roll_yield_pct": round(carry, 2), "r2": round(float(r2), 3),
             "rate_diff_pct": round(dr, 2), "gap_pct": round(carry - dr, 2)}
        res["fut"][c] = r
        L.append(f"| {c} | {r['rows']} | {r['first']} → {r['last']} | {r['basis_start_bp']} → {r['basis_end_bp']} | {r['roll_yield_pct']} | {r['r2']} | {r['rate_diff_pct']} | {r['gap_pct']} |")
    L += ["", "期貨 BID_ASK 日線同樣是回溯調整、而且是全日平均買／賣價，算出的價差有負值（CAD）——**期貨點差不能用這組數據估**，要用即時報價或 tick 數據。"]
    return L


def vol_checks(res: dict) -> list[str]:
    L = ["## 4. 隱含波動與歷史波動（P0）", "",
         "IB 的 `OPTION_IMPLIED_VOLATILITY`（期貨期權 30 天隱含波動）與 `HISTORICAL_VOLATILITY`（30 天歷史波動），年化小數。",
         "核對：(a) 壞值（0、> 100%）；(b) IB 歷史波動 vs 自己用 Dukascopy D1 算的 21 交易日收市對收市實現波動（同一時點、向後看）；"
         "(c) IB 隱含波動 vs 雲垂陣每日採集的 6E／6J 期權 ATM IV（`tradingview/data_external/ib_iv_log.csv`，同日）。"
         "**沒有計算隱含波動 − 之後的實現波動。**", "",
         "| 貨幣 | IV 根數 | IV 壞值（0） | IV 起 → 迄 | IV 中位 % | IV 範圍 % | 換月日 IV 跳動中位（點） | HV 根數 | IB HV vs 自算 21 日 RV：相關 | 中位差（點） |",
         "|---|---:|---:|---|---:|---|---:|---:|---:|---:|"]
    for c, (pair, inv) in FUT.items():
        iv = rd(IB / f"fut_{c}_D1_option_implied_volatility.csv.gz")["Close"]
        hv = rd(IB / f"fut_{c}_D1_historical_volatility.csv.gz")["Close"]
        bad = int(((iv <= 0) | (iv > 1)).sum())
        ivg = iv[(iv > 0) & (iv <= 1)] * 100
        hvg = hv[(hv > 0) & (hv <= 1)] * 100
        dk = pd.read_csv(DK / pair / f"{pair}_D1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
        dk = dk[dk.index.weekday < 5]
        rv = np.log(dk).diff().rolling(21).std() * math.sqrt(252) * 100
        j = pd.concat([hvg.rename("hv"), rv.rename("rv")], axis=1, sort=True).dropna()
        ltds = sorted({next_imm(t) for t in ivg.index})
        rolls = [ivg.index[ivg.index > l][0] for l in ltds if (ivg.index > l).any()]      # 每個最後交易日之後第一個交易日
        jump = ivg.diff().abs()
        roll_jump = float(jump.reindex(pd.DatetimeIndex(rolls)).median()) if rolls else float("nan")
        r = {"iv_rows": int(len(iv)), "iv_bad": bad, "iv_first": str(ivg.index[0])[:10], "iv_last": str(ivg.index[-1])[:10],
             "iv_median": round(float(ivg.median()), 2), "iv_min": round(float(ivg.min()), 2), "iv_max": round(float(ivg.max()), 2),
             "iv_roll_jump_median": round(roll_jump, 2), "iv_daily_jump_median": round(float(jump.median()), 2),
             "hv_rows": int(len(hv)), "hv_vs_rv_corr": round(float(j.hv.corr(j.rv)), 2) if len(j) > 20 else None,
             "hv_minus_rv_median": round(float((j.hv - j.rv).median()), 2) if len(j) > 20 else None}
        res["vol"][c] = r
        if c == "MXN":
            L.append(f"| MXN | {r['iv_rows']} | {bad} | — | — | — | — | {r['hv_rows']} | {r['hv_vs_rv_corr']} | **作廢**（合約錯，見第 3 節） |")
            continue
        L.append(f"| {c} | {r['iv_rows']} | {bad} | {r['iv_first']} → {r['iv_last']} | {r['iv_median']} | {r['iv_min']}–{r['iv_max']} | "
                 f"{r['iv_roll_jump_median']}（平日 {r['iv_daily_jump_median']}） | {r['hv_rows']} | {r['hv_vs_rv_corr']} | {r['hv_minus_rv_median']} |")
    # (c) 與每日採集的期權 ATM IV 對照
    log_rows = []
    try:
        import subprocess
        txt = subprocess.run(["git", "show", "origin/claude/dazzling-curie-f3xzb8:tradingview/data_external/ib_iv_log.csv"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        import io
        lg = pd.read_csv(io.StringIO(txt), parse_dates=["date"])
        for _, row in lg[lg.market.isin(["6E", "6J"])].iterrows():
            c = "EUR" if row.market == "6E" else "JPY"
            iv = rd(IB / f"fut_{c}_D1_option_implied_volatility.csv.gz")["Close"] * 100
            v = iv.get(row.date)
            log_rows.append({"date": str(row.date.date()), "market": row.market, "collector_mon_iv": row.mon_iv, "collector_mon_dte": int(row.mon_dte),
                             "ib_series_iv": round(float(v), 2) if v is not None and v > 0 else None})
    except Exception as exc:  # noqa: BLE001
        log_rows.append({"error": repr(exc)})
    res["vol_vs_collector"] = log_rows
    L += ["", "與每日採集（期權 ATM、月腿）同日對照：" + ("；".join(
        f"{r['date']} {r['market']} 採集 {r['collector_mon_iv']}%（{r['collector_mon_dte']} 天）vs IB 序列 {r['ib_series_iv'] if r['ib_series_iv'] is not None else '當日無值'}"
        for r in log_rows if "error" not in r) or "無重疊日")]
    return L


def main() -> None:
    if not IB.exists():
        sys.exit("沒有 data_forex_ibkr/：先 git checkout origin/claude/dazzling-curie-f3xzb8 -- data_forex_ibkr")
    res = {"spot": {}, "fut": {}, "vol": {}}
    cov = ["## 1. 覆蓋", "", "| 檔 | 根數 | 起 → 迄 |", "|---|---:|---|"]
    res["coverage"] = {}
    for f in sorted(IB.glob("*.csv.gz")):
        d = pd.read_csv(f, parse_dates=["Time"])
        name = f.name.replace(".csv.gz", "")
        res["coverage"][name] = {"rows": len(d), "first": str(d.Time.min())[:16], "last": str(d.Time.max())[:16]}
        cov.append(f"| {name} | {len(d):,} | {str(d.Time.min())[:10]} → {str(d.Time.max())[:10]} |")
    body = cov + [""] + spot_checks(res) + [""] + fut_checks(res) + [""] + vol_checks(res)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    OUT_TABLES.write_text("# IBKR 外匯數據驗收表（scripts/qc_ibkr_fx.py 自動產生）\n\n" + "\n".join(body) + "\n", encoding="utf-8")
    print("\n".join(body))


if __name__ == "__main__":
    main()
