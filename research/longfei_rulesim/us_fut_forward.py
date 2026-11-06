"""[IDEAS #230] 龍飛陣 MNQ／MES 前向測試（規則版，B 方案，使用者 11-06「B 先做」）。

背景：台灣 OpenD 冇 CME 美期報價權限（10-16），AI 即時模擬做唔到；先用延遲數據做規則版前向測試，
規則同 R295 即日回測（rulesim.py）一模一樣，方便同 QQQ／SPY 對照。A 方案（開通富途 CME 報價、AI 即時模擬）使用者考慮緊。

數據：yfinance NQ=F／ES=F（GitHub Actions 跑；本機擋 Yahoo）。
  - 前向：1 分鐘（Yahoo 只畀最近 7 日），每日補未做嘅日子。
  - 補數（--backfill）：5 分鐘（最近 60 日），標明 bars="5m"，min_or_bars=6；同前向分開統計。
規則：rulesim.run_day（開市區間 09:30–10:00 美東、順日線突破、OR 另一邊止蝕最少 0.15%、1R 保本後跟 3 支 K 收緊、15:59 平倉）。
成本每邊：MNQ 0.5 點、MES 0.35 點（1 tick 滑價＋佣金約 US$0.5）。每點：MNQ US$2、MES US$5，×7.8 換 HKD，1 張。
輸出：GCS longfei/rulesim_fut/<MNQ|MES>/<日>.json、longfei/rulesim_fut/summary.json。只係紙上，唔落單。

用法：python3 research/longfei_rulesim/us_fut_forward.py [--backfill] [--dry-run]
"""
import argparse
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rulesim as rs  # noqa: E402

PRODUCTS = {"MNQ": ("NQ=F", 2.0, 0.5), "MES": ("ES=F", 5.0, 0.35)}
OUT = "longfei/rulesim_fut/"


def spec(pv, cost):
    s = dict(rs.SPEC["US"])
    s["cost"] = lambda px, c=cost: c
    s["hkd"] = lambda pts, px, v=pv: pts * v * 7.8
    return s


def intraday(tk, interval, period):
    import yfinance as yf
    df = yf.download(tk, period=period, interval=interval, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return {}
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    idx = df.index.tz_convert("America/New_York") if df.index.tz is not None else df.index
    days = {}
    for t, r in zip(idx, df.itertuples()):
        dt = t.to_pydatetime().replace(tzinfo=None)
        if time(9, 30) <= dt.time() <= time(15, 59):
            days.setdefault(dt.date().isoformat(), []).append((dt, float(r.Open), float(r.High), float(r.Low), float(r.Close)))
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="用 5 分鐘數據補最近 60 日")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    import yfinance as yf
    store = rs.Store(a.dry_run)
    today = date.today().isoformat()
    for prod, (tk, pv, cost) in PRODUCTS.items():
        d1 = yf.download(tk, period="1y", interval="1d", progress=False, auto_adjust=False)
        if hasattr(d1.columns, "levels"):
            d1.columns = [c[0] for c in d1.columns]
        closes = {d.strftime("%Y-%m-%d"): float(v) for d, v in d1["Close"].dropna().items()}
        mode = ("5m", "60d", 6) if a.backfill else ("1m", "7d", 10)
        days = intraday(tk, mode[0], mode[1])
        sp = spec(pv, cost)
        for day, bars in sorted(days.items()):
            if day >= today:                      # 當日未收市唔做
                continue
            out = f"{OUT}{prod}/{day}.json"
            old = store.get(out)
            if old and (old.get("bars") == "1m" or a.backfill):
                continue
            trend = rs.us_trend(closes, day)
            trade, why = rs.run_day(sorted(bars), trend, sp, min_or_bars=mode[2])
            store.put(out, {"date": day, "product": prod, "source": tk, "bars": mode[0], "trend": trend,
                            "trade": trade, "no_trade_reason": why, "rules": "R295 v1"})
            print(day, prod, mode[0], "趨勢", trend, trade and (trade["side"], trade["r"], trade["exit_reason"]) or why)
    rows = {"1m": [], "5m": []}
    for name in store.names(OUT):
        if name.endswith("summary.json"):
            continue
        doc = store.get(name)
        if doc and doc.get("trade"):
            rows[doc.get("bars", "1m")].append({"date": doc["date"], "product": doc["product"], **doc["trade"]})
    summ = {"updated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "rules": "R295 v1", "ideas": 230}
    for k, v in rows.items():
        v.sort(key=lambda x: (x["date"], x["product"]))
        summ[f"forward_{k}" if k == "1m" else "backfill_5m"] = {
            "all": rs.stats(v), "by_product": {p: rs.stats([x for x in v if x["product"] == p]) for p in PRODUCTS},
            "recent": v[-20:]}
    store.put(OUT + "summary.json", summ)
    print({k: summ[k]["all"] for k in summ if isinstance(summ[k], dict) and "all" in summ[k]})


if __name__ == "__main__":
    main()
