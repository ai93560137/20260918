#!/usr/bin/env python3
"""第二收市數據源：港交所官方「每日報價表」（Daily Quotations，
https://www.hkex.com.hk/eng/stat/smstat/dayquot/d<YYMMDD>e.htm），全市場每檔的
官方英文簡稱與收市價。給 scripts/check_data_quality.py 跟 yfinance 交叉比對
收市價與**官方公司名**。

報價表每天收市後才發布、一份約 25MB，所以：
- 每次往回看 LOOKBACK_DAYS 天，沒存過的交易日才下載（17:00 HKT 那輪若報表未出，
  05:30 那輪會補上；第一次跑會順便補回近幾天的歷史）
- 只保留傳入 universe 清單裡的代碼，存 data/stocks_hkex/quotes_<交易日>.json（幾 KB）

    python3 scripts/fetch_hkex_equity.py scripts/pool_hsi_full.txt ...
    python3 scripts/fetch_hkex_equity.py --parse-file dayquot.htm scripts/pool_hsi_full.txt  # 本機測解析
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks_hkex"
URL = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{d:%y%m%d}e.htm"
HEADERS = {"User-Agent": "Mozilla/5.0 (data-quality cross-check)"}
LOOKBACK_DAYS = 10
HKT = timezone(timedelta(hours=8))

# 報價表 QUOTATIONS 區每檔兩行：
#     5 HSBC HOLDINGS    HKD  161.50   159.30   162.00            9,724,555
#                            159.30   159.20   159.00        1,558,694,930
# 第一行：代碼、簡稱(16字寬)、幣別、前收、賣盤、最高、成交股數
# 第二行：收市、買盤、最低、成交額
# 第一欄可能有標記符號（如 `*  700 TENCENT`，騰訊/盈富/友邦等大型股都有），要容許
ROW1 = re.compile(r"^([^\w\s])?\s{0,5}(\d{1,5}) (.{16}) ?([A-Z]{3})\s+(.*)$")


def read_universe(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_quotations(text: str) -> dict[str, dict]:
    """回傳 {"0005.HK": {"name", "close", "prev_close", "high", "low", "volume", "turnover"}}"""
    start = text.find('name = "quotations"')
    if start < 0:
        start = text.find('name="quotations"')
    if start < 0:
        raise ValueError("找不到 QUOTATIONS 區段（報表格式改了？）")
    end = text.find("<a name", start + 20)
    lines = html.unescape(text[start:end if end > 0 else None]).splitlines()
    out = {}
    for i, line in enumerate(lines[:-1]):
        m = ROW1.match(line)
        if not m:
            continue
        marker, code, name, _cur, rest = m.groups()
        t1 = rest.split()
        t2 = lines[i + 1].split()
        if len(t1) < 4 or len(t2) < 4 or not t2[0][0].isdigit() and t2[0] != "-":
            # 停牌等特殊行格式不同，只記名字
            out[f"{int(code):04d}.HK"] = {"name": name.strip(), "close": None, "note": " ".join(t1 + t2)[:80]}
            continue
        out[f"{int(code):04d}.HK"] = {
            "name": name.strip(),
            "marker": marker or "",
            "prev_close": num(t1[0]),
            "high": num(t1[2]),
            "volume": num(t1[3]),
            "close": num(t2[0]),
            "low": num(t2[2]),
            "turnover": num(t2[3]),
        }
    return out


def save_snapshot(trade_date: date, quotes: dict[str, dict], wanted: set[str], source: str) -> Path:
    keep = {t: q for t, q in quotes.items() if t in wanted}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"quotes_{trade_date.isoformat()}.json"
    out.write_text(json.dumps({"trade_date": trade_date.isoformat(), "source": source,
                               "n_market": len(quotes), "quotes": keep},
                              ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("universe", nargs="+", type=Path)
    ap.add_argument("--parse-file", type=Path, help="只解析本機報價表檔案（測試用，不下載不存檔）")
    args = ap.parse_args()

    wanted = {t for p in args.universe for t in read_universe(p) if t.endswith(".HK")}

    if args.parse_file:
        quotes = parse_quotations(args.parse_file.read_text(encoding="utf-8", errors="replace"))
        hit = {t: quotes[t] for t in sorted(wanted) if t in quotes}
        print(f"全市場 {len(quotes)} 檔，universe 命中 {len(hit)}/{len(wanted)}")
        for t in list(hit)[:8]:
            print(t, hit[t])
        print("universe 不在報表的:", sorted(wanted - set(quotes)))
        return

    s = requests.Session()
    s.headers.update(HEADERS)
    today = datetime.now(HKT).date()
    saved = 0
    for back in range(LOOKBACK_DAYS):
        d = today - timedelta(days=back)
        if d.weekday() >= 5 or (OUT_DIR / f"quotes_{d.isoformat()}.json").exists():
            continue
        url = URL.format(d=d)
        try:
            r = s.get(url, timeout=60)
        except Exception as exc:
            print(f"{d}: ERROR {exc}", file=sys.stderr)
            continue
        if r.status_code != 200:
            print(f"{d}: HTTP {r.status_code}（未發布或假期）")
            continue
        try:
            quotes = parse_quotations(r.content.decode("utf-8", errors="replace"))
        except ValueError as exc:
            print(f"{d}: 解析失敗 {exc}", file=sys.stderr)
            continue
        out = save_snapshot(d, quotes, wanted, url)
        saved += 1
        print(f"{d}: 全市場 {len(quotes)} 檔，存 universe {sum(t in quotes for t in wanted)}/{len(wanted)} -> {out}")
        time.sleep(1)
    print(f"新存 {saved} 份港交所報價表快照")


if __name__ == "__main__":
    main()
