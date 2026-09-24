#!/usr/bin/env python3
"""今天的真實個股期權平值 IV（OPTIONS_EQUITY_BACKTEST.md 第四部分）→ data/options_equity/live/。

    python3 scripts/fetch_stock_option_iv.py --market us     # 在 GitHub Actions 上跑（本環境擋 Yahoo / 港交所）
    python3 scripts/fetch_stock_option_iv.py --market hk

- us：現任 S&P 500 成分股（universe.Universe("sp500") 今天的名單），yfinance 期權鏈；取 20–45 日內最近的到期系列；
  保存平值附近（K/S 0.85–1.15）每個行使價的 call／put 買賣價，IV 由分析程式用中間價自己反推（不用 Yahoo 的 IV 欄）。
  下次業績日（yfinance calendar，拿得到才填）
- hk：港交所股票期權每日市場報告 dqe<YYMMDD>.htm 原文（gzip）；解析在分析端做。抓不到照報，不用別的來源代替
"""
import argparse
import csv
import gzip
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "options_equity" / "live"
UA = {"User-Agent": "Mozilla/5.0 (research; github-actions)"}


def us() -> int:
    import yfinance as yf
    from universe import Universe
    today = datetime.now(timezone.utc).date()
    tickers = sorted(Universe("sp500").members_at(today))
    rows, meta, fail = [], [], 0
    for i, t in enumerate(tickers):
        yt = t.replace(".", "-")
        try:
            tk = yf.Ticker(yt)
            exps = tk.options
            cand = [e for e in exps if 20 <= (date.fromisoformat(e) - today).days <= 45]
            if not cand:
                cand = [e for e in exps if (date.fromisoformat(e) - today).days >= 14][:1]
            if not cand:
                fail += 1
                continue
            e = cand[0]
            ch = tk.option_chain(e)
            spot = float(tk.fast_info["last_price"])
            earn = ""
            try:
                cal = tk.calendar
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if ed:
                    earn = str(ed[0])
            except Exception:  # noqa: BLE001
                pass
            meta.append([t, today, e, spot, earn])
            for cp, df in (("c", ch.calls), ("p", ch.puts)):
                for _, r in df.iterrows():
                    K = float(r["strike"])
                    if 0.85 <= K / spot <= 1.15:
                        rows.append([t, e, cp, K, float(r.get("bid") or 0), float(r.get("ask") or 0),
                                     int(r.get("openInterest") or 0) if r.get("openInterest") == r.get("openInterest") else 0])
        except Exception as ex:  # noqa: BLE001
            fail += 1
            print(f"{t}: {ex!r}")
        if i % 50 == 0:
            print(f"{i}/{len(tickers)}")
        time.sleep(0.2)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"us_meta_{today}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "asof", "expiry", "spot", "next_earnings"])
        w.writerows(meta)
    with open(OUT / f"us_chain_{today}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "expiry", "cp", "strike", "bid", "ask", "oi"])
        w.writerows(rows)
    print(f"us：{len(meta)}／{len(tickers)} 檔有期權鏈，失敗 {fail}，{len(rows)} 行")
    return 0 if meta else 1


def hk() -> int:
    import requests
    OUT.mkdir(parents=True, exist_ok=True)
    got = 0
    d = datetime.now(timezone(timedelta(hours=8))).date()
    for back in range(0, 6):
        x = d - timedelta(days=back)
        for url in (f"https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/dqe{x:%y%m%d}.htm",):
            try:
                r = requests.get(url, headers=UA, timeout=60)
                print(url, r.status_code, len(r.content))
                if r.status_code == 200 and len(r.content) > 10000:
                    (OUT / f"hk_dqe_{x}.htm.gz").write_bytes(gzip.compress(r.content))
                    got += 1
            except Exception as e:  # noqa: BLE001
                print(url, repr(e))
        if got >= 2:
            break
    print(f"hk：保存 {got} 份報告")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"], required=True)
    a = ap.parse_args()
    sys.exit(us() if a.market == "us" else hk())
