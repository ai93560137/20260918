#!/usr/bin/env python3
"""股票期權 + 正股研究（OPTIONS_EQUITY_BACKTEST.md）的外部數據 → data/options_equity/（純文字 CSV，進 git）。

    python3 scripts/fetch_options_equity_data.py        # 在 GitHub Actions 上跑（本環境擋 CBOE / Yahoo）

- CBOE 官方策略基準指數（對照組，真實 SPX 期權成交）：BXM（平值備兌）、BXY（2% 價外備兌）、
  PUT（平值現金擔保賣 put）、PPUT（5% 價外保護 put）、CLL（95–110 領口）
  來源 cdn.cboe.com 的 <SYM>_History.csv；拿不到就退回 yfinance ^<SYM>
- 無風險利率：^IRX（13 週美國國庫券，年化 %）
- 波動率指數：^VIX、^VHSI（^VHSI 在 yfinance 抓不到時保留現有 VHSI.csv——初版複製自雲垂分支 tradingview/data_external/vhsi_daily.csv）
- 2800.HK 全部股息（倉庫 data/equities/hk/2800.HK/actions.csv 只從 2013 起，2008–2012 缺）→ DIV_2800.csv（Date,Dividend）
輸出一律 Date,Close 兩欄，只在內容有變時重寫。
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "options_equity"
CBOE = ["BXM", "BXY", "PUT", "PPUT", "CLL"]
YF = {"IRX": "^IRX", "VIX": "^VIX", "VHSI": "^VHSI"}
UA = {"User-Agent": "Mozilla/5.0 (research; github-actions)"}


def write(name: str, s: pd.Series, src: str) -> None:
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    text = "Date,Close\n" + "".join(f"{d:%Y-%m-%d},{v:.6g}\n" for d, v in s.items())
    p = OUT / f"{name}.csv"
    if p.exists() and p.read_text(encoding="utf-8") == text:
        print(f"{name}: 無變動（{len(s)} 行）")
        return
    p.write_text(text, encoding="utf-8")
    print(f"{name}: {len(s)} 行 {s.index[0]:%Y-%m-%d} → {s.index[-1]:%Y-%m-%d}（{src}）")


def cboe(sym: str) -> pd.Series | None:
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        cols = {c.lower().strip(): c for c in df.columns}
        dcol = cols.get("date") or df.columns[0]
        vcol = cols.get(sym.lower()) or cols.get("close") or df.columns[-1]
        s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").values,
                      index=pd.to_datetime(df[dcol], errors="coerce"))
        return s[s.index.notna()]
    except Exception as e:  # noqa: BLE001
        print(f"{sym}: CBOE 失敗 {e!r}")
        return None


def yfin(tk: str) -> pd.Series | None:
    import yfinance as yf
    try:
        h = yf.Ticker(tk).history(period="max", auto_adjust=False)
    except Exception as e:  # noqa: BLE001
        print(f"{tk}: yfinance 失敗 {e!r}")
        return None
    if h is None or h.empty:
        print(f"{tk}: yfinance 沒有數據")
        return None
    h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
    return h["Close"]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for sym in CBOE:
        s, src = cboe(sym), "CBOE"
        if s is None or len(s) < 1000:
            s, src = yfin("^" + sym), "yfinance"
        if s is None or len(s) < 1000:
            print(f"::warning::{sym} 兩個來源都拿不到")
            bad += 1
            continue
        write(sym, s, src)
    for name, tk in YF.items():
        s = yfin(tk)
        if s is None:
            print(f"::warning::{tk} 拿不到")
            bad += 1
            continue
        write(name, s, "yfinance")
    try:
        import yfinance as yf
        dv = yf.Ticker("2800.HK").dividends
        dv.index = pd.to_datetime(dv.index).tz_localize(None).normalize()
        text = "Date,Dividend\n" + "".join(f"{d:%Y-%m-%d},{v:.6g}\n" for d, v in dv.sort_index().items())
        (OUT / "DIV_2800.csv").write_text(text, encoding="utf-8")
        print(f"DIV_2800: {len(dv)} 筆 {dv.index.min():%Y-%m-%d} → {dv.index.max():%Y-%m-%d}")
    except Exception as e:  # noqa: BLE001
        print(f"::warning::2800.HK 股息拿不到 {e!r}")
    return 1 if bad == len(CBOE) + len(YF) else 0


if __name__ == "__main__":
    sys.exit(main())
