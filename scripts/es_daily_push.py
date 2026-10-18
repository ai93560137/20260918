"""ES 標普 500 期貨日線 → 風揚陣 ES 頁（?view=es_range）。[R127]

GitHub Actions（.github/workflows/es_daily_push.yml）每個交易日 CME 收市後跑：用 yfinance 抓 ES=F 連續合約日線（CME 全段高低收），
以 Futu 腳本同款的 K_SESSION 封包推到 Cloud Run（action=futu_data、symbol=US.ES_FRONT），伺服器合併進 futu/daily/US.ES_FRONT.json。
- 進行中的交易日（紐約時間 17:00 收市前）那一列不推。
- 推完後叫 ?view=es_range&report=preopen 記下一個交易日的開市前預測（伺服器只在紐約 18:00–19:00 記錄，其他時間只預覽）。
需要環境變數：ZHUGE_GCP_URL（Cloud Run 網址）、ZHUGE_WEBHOOK_TOKEN（WEBHOOK_SECRET_TOKEN）。
用法：python3 scripts/es_daily_push.py [--days 30] [--symbols ES=F:US.ES_FRONT:es_range,NQ=F:US.NQ_FRONT:nq_range] [--dry-run]
[R230] 2026-10-18 恢復排程並加 NQ：MT5 差價合約數據 10-16 同 CME 對唔上（ES 低 7,740 對真實 7,676），日線改返用 yfinance；
mt5_push.py mt5-4 起唔再推 K_SESSION，兩個來源唔會互相覆蓋。
"""
import argparse, json, os, sys, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DEFAULT_SYMBOLS = "ES=F:US.ES_FRONT:es_range,NQ=F:US.NQ_FRONT:nq_range"   # yfinance 代號:Cloud Run 別名:頁面 view
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


def parse_symbols(text):
    out = []
    for part in (text or "").split(","):
        bits = [b.strip() for b in part.split(":")]
        if len(bits) == 3 and all(bits):
            out.append(tuple(bits))
    return out


def push(base, token, yf_symbol, alias, view, bars):
    import requests
    for i in range(0, len(bars), CHUNK):
        packet = {"action": "futu_data", "token": token, "source": f"yfinance:{yf_symbol}", "symbol": alias, "kline_type": "K_SESSION",
                  "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "script_version": "gh-es-2", "data": bars[i:i + CHUNK]}
        for attempt in range(3):
            r = requests.post(base + "/", json=packet, timeout=60)
            if r.status_code == 200:
                break
            print(f"  推送 {i}–{i + CHUNK} 回應 HTTP {r.status_code}：{r.text[:200]}"); time.sleep(5)
        else:
            sys.exit(f"{alias} 推送失敗")
        print(f"  {alias} 已推 {min(i + CHUNK, len(bars))}／{len(bars)}")
    r = requests.get(base + "/", params={"view": view, "report": "preopen", "format": "json"}, timeout=60)
    print(f"  {alias} 開市前預測：HTTP {r.status_code} {r.text[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30); ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    symbols = parse_symbols(a.symbols)
    if not symbols:
        sys.exit(f"--symbols 格式要係 yfinance代號:別名:view，逗號分隔：{a.symbols}")
    base = os.environ.get("ZHUGE_GCP_URL", "").strip().rstrip("/")
    token = os.environ.get("ZHUGE_WEBHOOK_TOKEN", "").strip()
    if not a.dry_run and (not base or not token):
        sys.exit("GitHub Secret ZHUGE_GCP_URL 或 ZHUGE_WEBHOOK_TOKEN 沒設")
    for yf_symbol, alias, view in symbols:
        bars = fetch_bars(yf_symbol, a.days)
        print(f"{yf_symbol} → {alias}: {len(bars)} 個交易日 {bars[0]['time_key'][:10]} → {bars[-1]['time_key'][:10]}（目前交易日 {session_today()}）")
        if a.dry_run:
            print(json.dumps(bars[-3:], ensure_ascii=False))
            continue
        push(base, token, yf_symbol, alias, view, bars)


if __name__ == "__main__":
    main()
