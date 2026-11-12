"""長歷史日線存 GCS（天覆陣 11-12 要求；使用者 11-12「叫龍飛陣將 HSI/NQ/ES 數據俾天覆陣」）。

用 yfinance 攞最早有數嗰日起嘅日線，寫 GCS longfei/daily/<檔名>.json：
  {"ticker","source","fetched_utc","fields":["date","o","h","l","c","v"],"rows":[["YYYY-MM-DD",開,高,低,收,量],…],"note"}
只收已收市日（最後一支如果係今日美東未收市／期貨未完成嘅夜盤，就唔要）。只係數據，唔落單。
跑法：Actions「龍飛陣 策略搜尋」script=daily_archive。
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

TICKERS = {"NQ=F": "NQ_F", "ES=F": "ES_F", "^HSI": "HSI", "^NDX": "NDX", "^GSPC": "GSPC", "HSI=F": "HSI_F"}
NOTE = {"NQ=F": "Yahoo 連續合約，自動轉月、冇價差調整；日線收市係結算前後最後價",
        "ES=F": "Yahoo 連續合約，自動轉月、冇價差調整；日線收市係結算前後最後價",
        "HSI=F": "Yahoo 恒指期貨連續合約（如有）；歷史可能唔完整",
        "^HSI": "恒生指數現貨", "^NDX": "納斯達克 100 現貨", "^GSPC": "標普 500 現貨"}


def rows(tk):
    df = yf.download(tk, start="1990-01-01", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    tz = ZoneInfo("Asia/Hong_Kong" if "HSI" in tk else "America/New_York")
    now = datetime.now(tz)
    done_hour = 17                                   # 港股 16:10 收、美股 16:00 收、CME 17:00 收：17:00 後先當今日已收市
    out = []
    for d, r in zip(df.index, df.itertuples()):
        day = d.strftime("%Y-%m-%d")
        if day > now.strftime("%Y-%m-%d") or (day == now.strftime("%Y-%m-%d") and now.hour < done_hour):
            continue
        v = getattr(r, "Volume", 0)
        out.append([day, round(float(r.Open), 2), round(float(r.High), 2), round(float(r.Low), 2), round(float(r.Close), 2),
                    int(v) if v == v else 0])
    return out


def main():
    from google.cloud import storage
    b = storage.Client().bucket("zhuge-risk-manager-bucket")
    index = {}
    for tk, name in TICKERS.items():
        try:
            rs = rows(tk)
        except Exception as e:  # noqa: BLE001
            print(tk, "失敗", e)
            continue
        if len(rs) < 200:
            print(tk, "數據唔夠，跳過", len(rs))
            continue
        doc = {"ticker": tk, "source": "Yahoo Finance（yfinance）", "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "fields": ["date", "o", "h", "l", "c", "v"], "rows": rs, "note": NOTE.get(tk, "")}
        b.blob(f"longfei/daily/{name}.json").upload_from_string(json.dumps(doc, separators=(",", ":"), ensure_ascii=False),
                                                              content_type="application/json")
        index[name] = {"ticker": tk, "days": len(rs), "from": rs[0][0], "to": rs[-1][0]}
        print(name, tk, len(rs), rs[0][0], "→", rs[-1][0])
    b.blob("longfei/daily/index.json").upload_from_string(json.dumps(index, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
