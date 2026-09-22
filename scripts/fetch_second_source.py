#!/usr/bin/env python3
"""美股/日股第二收市數據源（給 scripts/check_equities_quality.py 跟 yfinance 交叉比對
收市價與**公司名**）。港股的第二來源是 scripts/fetch_hkex_equity.py（港交所報價表）。

- us：Nasdaq.com screener API——一次請求拿到全美 ~7000 檔的最後成交價、公司名、
  行業、市值。收市後（排程 22:30 UTC = 美東 18:30）跑，最後成交價就是當日收市價
  （2026-09-22 探勘：AAPL screener $339.75 = 報價頁 "Closed at 4:00 PM ET" $339.75）。
  screener 沒有日期欄，交易日取 yfinance 剛抓的 SPY 最後一根日期；那一天不是
  今天（美東）就代表今天休市，不存（否則會把前一日收市錯標成今天）。

- jp：Yahoo!ファイナンス個股頁（Yahoo Japan，跟 yfinance 背後的美國 Yahoo 是不同公司、
  不同數據商）。取頁面內「前日終値」——自帶交易日期（updateDateMeta），比對不怕錯日；
  公司名取頁面標題（日文，如「トヨタ自動車(株)」）。只抓現任日經225成分股（~225 頁、每頁
  ~450KB，間隔 0.5 秒）。
  另抓 JPX「東証上場銘柄一覧」（每月更新）：官方日文名、33業種、TOPIX 規模區分，存
  _jpx_listed.json（只有 JPX 更新日期變了才重寫）。

只保留抓取清單裡的代碼，存 data/equities/<market>/_second/quotes_<交易日>.json
（每檔可帶自己的 date：停牌股的前日終値日期會比較舊）。

    python3 scripts/fetch_second_source.py --market us
    python3 scripts/fetch_second_source.py --market jp
"""
import argparse
import io
import json
import re
import sys
import time
from collections import Counter
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


YJ_PREV = re.compile(r'"previousPrice":\{"name":"[^"]*","value":"([\d,.]+)","updateDate":"[^"]*",'
                     r'"updateDateMeta":"(\d{4}-\d{2}-\d{2})"')
YJ_TITLE = re.compile(r"<title>(.*?)【(\w{4})】")
JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"


def fetch_jp(codes: list[str]) -> dict:
    s = requests.Session()
    s.headers.update({k: v for k, v in UA.items() if k in ("User-Agent",)} | {"Accept-Language": "ja"})
    out = {}
    for t in codes:
        try:
            r = s.get(f"https://finance.yahoo.co.jp/quote/{t}", timeout=30)
        except Exception as exc:
            print(f"WARN {t}: {exc}", file=sys.stderr)
            continue
        if r.status_code != 200:
            print(f"WARN {t}: HTTP {r.status_code}", file=sys.stderr)
            continue
        text = r.text
        m = YJ_PREV.search(text.replace('\\"', '"'))
        tm = YJ_TITLE.search(text)
        if not m:
            print(f"WARN {t}: 找不到前日終値（頁面格式改了？）", file=sys.stderr)
            continue
        out[t] = {"close": money(m.group(1)), "date": m.group(2), "name": tm.group(1) if tm else ""}
        time.sleep(0.5)
    return out


def update_jpx_listed(base, wanted: set[str]) -> None:
    """JPX 上場銘柄一覧 -> _jpx_listed.json（官方名/33業種/規模），JPX 日期沒變就不動。"""
    import pandas as pd
    r = requests.get(JPX_URL, headers={"User-Agent": UA["User-Agent"]}, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl", dtype=str)
    asof = str(df["日付"].iloc[0])
    path = base / "_jpx_listed.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("asof") == asof:
        print(f"JPX 上場銘柄一覧 {asof} 已存過")
        return
    rows = {}
    for _, x in df.iterrows():
        t = f"{x['コード']}.T"
        if t in wanted:
            rows[t] = {"name": x["銘柄名"], "market": x["市場・商品区分"], "sector33": x["33業種区分"],
                       "sector17": x["17業種区分"], "size": x["規模区分"]}
    path.write_text(json.dumps({"asof": asof, "source": JPX_URL, "listed": rows}, ensure_ascii=False,
                               indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"JPX 上場銘柄一覧 {asof}：全市場 {len(df)} 檔，存 {len(rows)}/{len(wanted)}")


def save(market: str, trade_date: str, source: str, n_market: int, quotes: dict) -> None:
    out = md.V2_DIR / market / "_second" / f"quotes_{trade_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"trade_date": trade_date, "source": source, "n_market": n_market, "quotes": quotes},
                              ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{trade_date}: 來源 {n_market} 檔，存 {len(quotes)} -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=["us", "jp"], required=True)
    args = ap.parse_args()

    wanted = read_list(ROOT / "universes" / args.market / "fetch_list.txt")
    base = md.V2_DIR / args.market
    if args.market == "jp":
        from universe import Universe
        today = datetime.now(timezone.utc).date()
        codes = sorted(Universe("n225").members_at(today))
        try:
            update_jpx_listed(base, wanted)
        except Exception as exc:
            print(f"WARN JPX 上場銘柄一覧抓取失敗：{exc}", file=sys.stderr)
        quotes = fetch_jp(codes)
        if not quotes:
            sys.exit("Yahoo!ファイナンス一檔都沒抓到")
        # 檔名用最多檔共同的交易日（停牌股的前日終値日期較舊，各自帶 date）
        trade_date = Counter(q["date"] for q in quotes.values()).most_common(1)[0][0]
        save("jp", trade_date, "finance.yahoo.co.jp（前日終値）", len(codes), quotes)
        return

    et_today = (datetime.now(timezone.utc) - timedelta(hours=4)).date()   # 美東（夏令；冬令差一小時不影響日期）
    try:
        last_bar = md.load_raw("SPY")[-1][0]
    except (FileNotFoundError, IndexError):
        sys.exit("沒有 SPY 的 v2 數據，無法判斷交易日")
    if last_bar != et_today:
        print(f"SPY 最後一根 {last_bar} ≠ 美東今天 {et_today}：今天休市或 yfinance 還沒更新，不存快照")
        return
    quotes, n_market = fetch_us(wanted)
    save("us", last_bar.isoformat(), "api.nasdaq.com/api/screener/stocks", n_market, quotes)


if __name__ == "__main__":
    main()
