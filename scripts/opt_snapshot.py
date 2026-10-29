#!/usr/bin/env python3
"""單一個股期權鏈＋日線快照（給「某股大跌，賣 put／賣 call 值唔值」這類即時查詢用；不是回測）。

    python3 scripts/opt_snapshot.py GOOG GOOGL     # 在 GitHub Actions 上跑（沙盒擋 Yahoo）

輸出 analysis/opt_snapshot/<日期>/：
  <T>_px.csv     近 400 個交易日 OHLCV（yfinance，auto_adjust=False）
  <T>_chain.csv  到期日 ≤ 75 日的全部系列（最多 5 個）：expiry,cp,strike,bid,ask,last,iv_yahoo,oi,volume
  meta.csv       ticker,asof_utc,spot,prev_close,next_earnings
由 .github/workflows/opt_snapshot.yml 觸發：往 analysis/opt_snapshot/request.txt 追加一行「代號 代號 …」並 push。
"""
import csv
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(tickers: list[str]) -> int:
    import yfinance as yf
    now = datetime.now(timezone.utc)
    today = now.date()
    out = ROOT / "analysis" / "opt_snapshot" / str(today)
    out.mkdir(parents=True, exist_ok=True)
    meta = []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            h = tk.history(period="2y", auto_adjust=False)
            with open(out / f"{t}_px.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "adjclose", "volume"])
                for d, r in h.tail(400).iterrows():
                    w.writerow([d.date(), r["Open"], r["High"], r["Low"], r["Close"], r.get("Adj Close", r["Close"]), int(r["Volume"])])
            fi = tk.fast_info
            spot, prev = float(fi["last_price"]), float(fi["previous_close"])
            earn = ""
            try:
                cal = tk.calendar
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if ed:
                    earn = str(ed[0])
            except Exception:  # noqa: BLE001
                pass
            meta.append([t, now.isoformat(timespec="seconds"), spot, prev, earn])
            exps = [e for e in tk.options if 0 < (date.fromisoformat(e) - today).days <= 75][:5]
            rows = []
            for e in exps:
                ch = tk.option_chain(e)
                for cp, df in (("c", ch.calls), ("p", ch.puts)):
                    for _, r in df.iterrows():
                        oi = r.get("openInterest")
                        vol = r.get("volume")
                        rows.append([e, cp, float(r["strike"]), float(r.get("bid") or 0), float(r.get("ask") or 0),
                                     float(r.get("lastPrice") or 0), float(r.get("impliedVolatility") or 0),
                                     int(oi) if oi == oi and oi is not None else 0,
                                     int(vol) if vol == vol and vol is not None else 0])
                time.sleep(0.3)
            with open(out / f"{t}_chain.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["expiry", "cp", "strike", "bid", "ask", "last", "iv_yahoo", "oi", "volume"])
                w.writerows(rows)
            print(f"{t}: spot {spot:.2f} prev {prev:.2f} ({spot / prev - 1:+.2%}) 到期 {exps} 共 {len(rows)} 行 業績 {earn}")
        except Exception as ex:  # noqa: BLE001
            print(f"{t}: 失敗 {ex!r}")
    with open(out / "meta.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "asof_utc", "spot", "prev_close", "next_earnings"])
        w.writerows(meta)
    return 0 if meta else 1


if __name__ == "__main__":
    sys.exit(main([a.upper() for a in sys.argv[1:]] or ["GOOG"]))
