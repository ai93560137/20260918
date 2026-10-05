"""美國指數期貨連續合約日線（yfinance），給 research/us_futures 的波幅預測與蛇蟠陣用。

雲端工作階段連不到 Yahoo、富途帳戶沒有 CME 權限，所以由 GitHub Actions（us_futures_daily.yml）跑，結果 commit 回 data/us_futures/。
- 代號：ES=F（標普 500 E-mini）、NQ=F（納指 100 E-mini）、YM=F（道指 E-mini）；另抓指數 ^GSPC、^NDX、^DJI 作對照。
- Yahoo 的期貨日線是 CME 全段（Globex 近 23 小時）的高低收，用戶決定「一天 = 整段 23 小時」，所以直接用。
- 連續合約由 Yahoo 自己接（前月換下月不做價差調整），轉月日會有跳空，跟 HK.HSI_FRONT 的 K_SESSION 一樣。
- 輸出：data/us_futures/<代號>_daily.csv（Date,Open,High,Low,Close,Volume），每次整份重抓（max），並記 manifest.json（列數、起訖日、抓取時間）。
用法：python3 scripts/us_futures_daily.py [--symbols ES=F,NQ=F,YM=F,^GSPC,^NDX,^DJI]
"""
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "us_futures"
DEFAULT = "ES=F,NQ=F,YM=F,^GSPC,^NDX,^DJI"


def fname(sym):
    return sym.replace("=F", "").replace("^", "IDX_") + "_daily.csv"


def fetch(sym):
    import yfinance as yf
    for attempt in range(3):
        df = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False, actions=False)
        if df is not None and len(df):
            break
        time.sleep(5 * (attempt + 1))
    if df is None or not len(df):
        raise RuntimeError(f"{sym}: 沒有數據")
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
    df = df[(df["High"] > 0) & (df["Low"] > 0) & (df["High"] >= df["Low"])]
    df.index.name = "Date"
    return df


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols", default=DEFAULT); a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "series": {}}
    for sym in [s.strip() for s in a.symbols.split(",") if s.strip()]:
        df = fetch(sym)
        path = OUT / fname(sym)
        df.to_csv(path, float_format="%.4f", date_format="%Y-%m-%d")
        manifest["series"][sym] = {"file": path.name, "rows": int(len(df)), "first": str(df.index[0].date()), "last": str(df.index[-1].date())}
        print(f"{sym}: {len(df)} 列 {df.index[0].date()} → {df.index[-1].date()} → {path.name}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
