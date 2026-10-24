"""[R289] 龍飛陣每日分析欄：用 yfinance 攞 NQ／ES 期貨同 SPX 現貨嘅日線同 1 小時線，寫 GCS ops/longfei/analyst/data/<代號>.json。

使用者 10-23：「根據我的思路，每天在網頁上加一個我的分析欄，我看看你能否學到我」。
雲端工作階段連唔到 Yahoo，所以由 GitHub Actions（longfei_analyst_data.yml，WIF）攞數據，分析由每日工作階段讀 GCS 寫。

輸出：{"symbol", "fetched_utc", "d1": [[日期, 開, 高, 低, 收], …], "h1": [[美東時間, 開, 高, 低, 收], …]}
用法：python3 scripts/longfei_analyst_data.py [--out-dir 本機資料夾]（冇 --out-dir 就寫 GCS）
"""
import argparse
import json
import os
from datetime import datetime, timezone

import yfinance as yf

SYMBOLS = {"NQ": "NQ=F", "ES": "ES=F", "SPX": "^GSPC"}   # [R290] SPX 現貨：使用者 4 小時圖用現貨（只得正常時段）
BUCKET = "zhuge-risk-manager-bucket"
PREFIX = "ops/longfei/analyst/data/"


def rows(df, fmt):
    out = []
    for t, r in df.iterrows():
        o, h, lo, c = (float(r[k].iloc[0] if hasattr(r[k], "iloc") else r[k]) for k in ("Open", "High", "Low", "Close"))
        if c == c:                                            # 跳過 NaN
            out.append([t.strftime(fmt), round(o, 2), round(h, 2), round(lo, 2), round(c, 2)])
    return out


def fetch(ticker):
    d1 = yf.download(ticker, period="3y", interval="1d", progress=False, auto_adjust=False)
    h1 = yf.download(ticker, period="300d", interval="1h", progress=False, auto_adjust=False)
    if h1.index.tz is not None:
        h1.index = h1.index.tz_convert("America/New_York")
    return {"symbol": ticker, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "d1": rows(d1, "%Y-%m-%d"), "h1": rows(h1, "%Y-%m-%d %H:%M")}


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
