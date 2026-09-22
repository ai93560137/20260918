#!/usr/bin/env python3
"""美股/日股第二收市數據源（給 scripts/check_equities_quality.py 跟 yfinance 交叉比對
收市價與**公司名**）。港股的第二來源是 scripts/fetch_hkex_equity.py（港交所報價表）。

- us：Nasdaq.com screener API——一次請求拿到全美 ~7000 檔的最後成交價、公司名、
  行業、市值。收市後（排程 22:30 UTC = 美東 18:30）跑，最後成交價就是當日收市價
  （2026-09-22 探勘：AAPL screener $339.75 = 報價頁 "Closed at 4:00 PM ET" $339.75）。
  screener 沒有日期欄，交易日取 yfinance 剛抓的 SPY 最後一根日期；那一天不是
  今天（美東）就代表今天休市，不存（否則會把前一日收市錯標成今天）。

只保留抓取清單裡的代碼，存 data/equities/<market>/_second/quotes_<交易日>.json。

    python3 scripts/fetch_second_source.py --market us
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
      "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def read_list(p: Path) -> set[str]:
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}


def money(s: str) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def fetch_us(wanted: set[str]) -> tuple[dict, int]:
    r = requests.get("https://api.nasdaq.com/api/screener/stocks", headers=UA,
                     params={"tableonly": "true", "download": "true"}, timeout=60)
    r.raise_for_status()
    rows = r.json()["data"]["rows"]
    out = {}
    for x in rows:
        t = x["symbol"].strip().replace("/", "-")   # BRK/B -> BRK-B（Yahoo 格式）
        if t not in wanted:
            continue
        out[t] = {"name": x.get("name", "").strip(), "close": money(x.get("lastsale", "")),
                  "sector": x.get("sector", ""), "industry": x.get("industry", ""),
                  "market_cap": money(x.get("marketCap", "") or "")}
    return out, len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=["us"], required=True)
    args = ap.parse_args()

    wanted = read_list(ROOT / "universes" / args.market / "fetch_list.txt")
    et_today = (datetime.now(timezone.utc) - timedelta(hours=4)).date()   # 美東（夏令；冬令差一小時不影響日期）
    try:
        last_bar = md.load_raw("SPY")[-1][0]
    except (FileNotFoundError, IndexError):
        sys.exit("沒有 SPY 的 v2 數據，無法判斷交易日")
    if last_bar != et_today:
        print(f"SPY 最後一根 {last_bar} ≠ 美東今天 {et_today}：今天休市或 yfinance 還沒更新，不存快照")
        return
    quotes, n_market = fetch_us(wanted)
    out = md.V2_DIR / args.market / "_second" / f"quotes_{last_bar.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"trade_date": last_bar.isoformat(), "source": "api.nasdaq.com/api/screener/stocks",
                               "n_market": n_market, "quotes": quotes},
                              ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{last_bar}: 全市場 {n_market} 檔，存抓取清單內 {len(quotes)}/{len(wanted)} -> {out}")


if __name__ == "__main__":
    main()
