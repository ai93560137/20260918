"""[R289] 龍飛陣每日分析欄：用 yfinance 攞 NQ／ES 期貨同 SPX 現貨嘅日線同 1 小時線，寫 GCS ops/longfei/analyst/data/<代號>.json。

使用者 10-23：「根據我的思路，每天在網頁上加一個我的分析欄，我看看你能否學到我」。
雲端工作階段連唔到 Yahoo，所以由 GitHub Actions（longfei_analyst_data.yml，WIF）攞數據，分析由每日工作階段讀 GCS 寫。

輸出：{"symbol", "fetched_utc", "d1": [[日期, 開, 高, 低, 收], …], "h1": [[美東時間, 開, 高, 低, 收], …]}
用法：python3 scripts/longfei_analyst_data.py [--out-dir 本機資料夾]（冇 --out-dir 就寫 GCS）
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

SYMBOLS = {"NQ": "NQ=F", "ES": "ES=F", "SPX": "^GSPC",   # [R290] SPX 現貨：使用者 4 小時圖用現貨（只得正常時段）
           "VIX": "^VIX",                                   # [R304] 使用者 10-27 VIX 日線筆記（缺口、200 SMA、下降壓力線）
           "RSP": "RSP"}                                    # 使用者 10-29：等權標普 ETF，睇板塊輪動／市場廣度（對比 NQ）
BUCKET = "zhuge-risk-manager-bucket"
PREFIX = "ops/longfei/analyst/data/"
ET = ZoneInfo("America/New_York")
REBUILD_DAYS = 10


def trade_date(ts: str) -> str:
    """CME 期貨交易日：美東 18:00 之後嘅 K 線屬下一個平日（星期五／日晚 → 星期一）。"""
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
    d = t.date()
    if t.hour >= 18:
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d.isoformat()


def futures_d1(d1, h1, now_et):
    """[R349] 分析欄 10-28 發現：yfinance 期貨日線最後一支係未完成嘅夜盤（10-27 嗰支幅度得 10 點，
    真正 10-27 全日反而冇咗）。最近 REBUILD_DAYS 個交易日改用 1 小時線按 CME 交易日重砌，
    未收市（美東 17:00 前）嘅交易日唔放入日線。"""
    days = {}
    for ts, o, h, lo, c in h1:
        k = trade_date(ts)
        x = days.get(k)
        days[k] = [k, o, h, lo, c] if x is None else [k, x[1], max(x[2], h), min(x[3], lo), c]
    keys = sorted(days)[-REBUILD_DAYS:]
    if keys and now_et < datetime.combine(date.fromisoformat(keys[-1]), datetime.min.time(), ET).replace(hour=17):
        keys = keys[:-1]
    if not keys:
        return d1
    return [r for r in d1 if r[0] < keys[0]] + [days[k] for k in keys]


def rows(df, fmt):
    out = []
    for t, r in df.iterrows():
        o, h, lo, c = (float(r[k].iloc[0] if hasattr(r[k], "iloc") else r[k]) for k in ("Open", "High", "Low", "Close"))
        if c == c:                                            # 跳過 NaN
            out.append([t.strftime(fmt), round(o, 2), round(h, 2), round(lo, 2), round(c, 2)])
    return out


PREPOST = {"RSP"}   # 使用者嘅 TradingView RSP 4 小時圖包盤前盤後（每日 4 支 4 小時 K），均線先對得上


def fetch(ticker):
    d1 = yf.download(ticker, period="3y", interval="1d", progress=False, auto_adjust=False)
    h1 = yf.download(ticker, period="300d", interval="1h", progress=False, auto_adjust=False,
                     prepost=ticker in PREPOST)
    if h1.index.tz is not None:
        h1.index = h1.index.tz_convert("America/New_York")
    doc = {"symbol": ticker, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "d1": rows(d1, "%Y-%m-%d"), "h1": rows(h1, "%Y-%m-%d %H:%M")}
    if ticker in PREPOST:                   # 對照用：派息調整後日線（TradingView 預設調整股息）
        adj = yf.download(ticker, period="3y", interval="1d", progress=False, auto_adjust=True)
        doc["d1_adj"] = rows(adj, "%Y-%m-%d")
        doc["h1_note"] = "1 小時線包盤前盤後（prepost）"
    if ticker.endswith("=F"):
        doc["d1"] = futures_d1(doc["d1"], doc["h1"], datetime.now(ET))
        doc["d1_note"] = "R349：最近交易日由 1 小時線按 CME 交易日重砌，只含已收市日"
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="")
    a = ap.parse_args()
    bucket = None
    if not a.out_dir:
        from google.cloud import storage
        bucket = storage.Client().bucket(BUCKET)
    for name, ticker in SYMBOLS.items():
        doc = fetch(ticker)
        if name in ("VIX", "RSP") and (len(doc["d1"]) < 250 or len(doc["h1"]) < 200):   # VIX／RSP 只係輔助，唔夠就跳過唔好令成個 workflow 失敗
            print(f"{name} 數據唔夠，跳過：日線 {len(doc['d1'])}、1 小時 {len(doc['h1'])}")
            continue
        if len(doc["d1"]) < 250 or len(doc["h1"]) < 500:
            raise SystemExit(f"{ticker} 數據唔夠：日線 {len(doc['d1'])}、1 小時 {len(doc['h1'])}")
        text = json.dumps(doc, separators=(",", ":"))
        if a.out_dir:
            os.makedirs(a.out_dir, exist_ok=True)
            open(os.path.join(a.out_dir, f"{name}.json"), "w").write(text)
        else:
            bucket.blob(f"{PREFIX}{name}.json").upload_from_string(text, content_type="application/json")
        print(f"{name}: 日線 {len(doc['d1'])} 支（至 {doc['d1'][-1][0]}）、1 小時 {len(doc['h1'])} 支（至 {doc['h1'][-1][0]}）")


if __name__ == "__main__":
    main()
