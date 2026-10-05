"""ES 標普 500 期貨日線 → 風揚陣 ES 頁（?view=es_range）。[R127]

GitHub Actions（.github/workflows/es_daily_push.yml）每個交易日 CME 收市後跑：用 yfinance 抓 ES=F 連續合約日線（CME 全段高低收），
以 Futu 腳本同款的 K_SESSION 封包推到 Cloud Run（action=futu_data、symbol=US.ES_FRONT），伺服器合併進 futu/daily/US.ES_FRONT.json。
- 進行中的交易日（紐約時間 17:00 收市前）那一列不推。
- 推完後叫 ?view=es_range&report=preopen 記下一個交易日的開市前預測（伺服器只在紐約 18:00–19:00 記錄，其他時間只預覽）。
需要環境變數：ZHUGE_GCP_URL（Cloud Run 網址）、ZHUGE_WEBHOOK_TOKEN（WEBHOOK_SECRET_TOKEN）。
用法：python3 scripts/es_daily_push.py [--days 30] [--symbol ES=F] [--dry-run]
"""
import argparse, json, os, sys, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ALIAS = "US.ES_FRONT"
CHUNK = 400


def session_today(now=None):
    t = (now or datetime.now(timezone.utc)).astimezone(NY)
    return (t + timedelta(hours=6)).strftime("%Y-%m-%d")


def fetch_bars(symbol, days):
    import yfinance as yf
    df = yf.Ticker(symbol).history(period="max" if days >= 5000 else f"{days}d", interval="1d", auto_adjust=False, actions=False)
    if df is None or not len(df):
        sys.exit(f"{symbol}: yfinance 沒有數據")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
    now = datetime.now(timezone.utc).astimezone(NY)
    cur = session_today(now)
    bars = []
    for ts, r in df.iterrows():
        d = ts.strftime("%Y-%m-%d")
        if r["High"] <= 0 or r["High"] < r["Low"]:
            continue
        if d >= cur and now.strftime("%H:%M") < "17:00":          # 進行中的交易日不推（17:00 收市後才推）
            continue
        if d > cur:
            continue
        bars.append({"time_key": f"{d} 00:00:00", "open": round(float(r["Open"]), 2), "high": round(float(r["High"]), 2),
                     "low": round(float(r["Low"]), 2), "close": round(float(r["Close"]), 2), "volume": float(r["Volume"] or 1)})
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30); ap.add_argument("--symbol", default="ES=F"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    base = os.environ.get("ZHUGE_GCP_URL", "").strip().rstrip("/")
    token = os.environ.get("ZHUGE_WEBHOOK_TOKEN", "").strip()
    bars = fetch_bars(a.symbol, a.days)
    print(f"{a.symbol}: {len(bars)} 個交易日 {bars[0]['time_key'][:10]} → {bars[-1]['time_key'][:10]}（目前交易日 {session_today()}）")
    if a.dry_run:
        print(json.dumps(bars[-3:], ensure_ascii=False)); return
    if not base or not token:
        sys.exit("GitHub Secret ZHUGE_GCP_URL 或 ZHUGE_WEBHOOK_TOKEN 沒設")
    import requests
    for i in range(0, len(bars), CHUNK):
        packet = {"action": "futu_data", "token": token, "source": f"yfinance:{a.symbol}", "symbol": ALIAS, "kline_type": "K_SESSION",
                  "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "script_version": "gh-es-1", "data": bars[i:i + CHUNK]}
        for attempt in range(3):
            r = requests.post(base + "/", json=packet, timeout=60)
            if r.status_code == 200:
                break
            print(f"  推送 {i}–{i + CHUNK} 回應 HTTP {r.status_code}：{r.text[:200]}"); time.sleep(5)
        else:
            sys.exit("推送失敗")
        print(f"  已推 {min(i + CHUNK, len(bars))}／{len(bars)}")
    r = requests.get(base + "/", params={"view": "es_range", "report": "preopen", "format": "json"}, timeout=60)
    print(f"開市前預測：HTTP {r.status_code} {r.text[:300]}")


if __name__ == "__main__":
    main()
