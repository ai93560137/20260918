"""[IDEAS #2031] 一次性回補恒指期貨（主連）1 分鐘 K 線（含夜市）入私人 GCS longfei/bars/<產品>/<日>.json，俾 MHI 日內／夜市研究用。

背景：MHI 日線研究 26 批（yfinance ^HSI 現貨、冇夜市）冇一個合格（IDEAS #2003–#2030）；1 分鐘存檔（bars_archive.py）2025-10 先開始。
使用者 11-09 揀「1」：用部機數據源攞較長嘅恒指期貨歷史再研究。

做法（同 bars_archive.py 一樣經 Cloud Run action=longfei_bars 上載，VM 冇 GCS 寫入權）：
- 逐個月攞（每個月約 2 萬條，記憶體細；10-18 OOM 事故之後唔好一次過攞幾年）。
- 每日寫部機 ~/zhuge/bars/<產品>/<日>.json，內容同上次上載唔同先上載（共用 uploaded.json，同 bars_archive 唔會重複）。
- 唔落單、唔解鎖交易、唔印權杖。

用法（喺 VM 用 venv 跑；先探測、再小範圍試、最後全部）：
  ~/zhuge-venv/bin/python bars_backfill.py --probe                       # 每年 1 月同 7 月各攞一日，睇最早有幾耐（唔上載）
  ~/zhuge-venv/bin/python bars_backfill.py --from 2025-01-01 --dry-run   # 只寫部機，唔上載
  ~/zhuge-venv/bin/python bars_backfill.py --from 2019-01-01             # 正式回補（約 15–25 分鐘）
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import bars_archive as ba

log = logging.getLogger("backfill")


def month_ranges(start: date, end: date):
    """[start, end] 切成逐月 (月初或 start, 月尾或 end)。"""
    out, cur = [], start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        out.append((cur, min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


def probe_days(first_year: int, today: date):
    """每年 1 月 10 日同 7 月 10 日前後（攞一個星期，避開假期）。"""
    out = []
    for y in range(first_year, today.year + 1):
        for m in (1, 7):
            d = date(y, m, 10)
            if d < today:
                out.append((d, d + timedelta(days=6)))
    return out


def save_and_upload(product, rows, out_dir: Path, url, token, sent, dry_run):
    n_days = n_up = 0
    for day, bars in sorted(ba.to_days(rows).items()):
        text = json.dumps(bars, separators=(",", ":"))
        f = out_dir / product / f"{day}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        n_days += 1
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        if sent.get(f"{product}/{day}") == digest or dry_run or not (url and token):
            continue
        if ba.upload(url, token, product, day, bars):
            sent[f"{product}/{day}"] = digest
            n_up += 1
    return n_days, n_up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="HSI")
    ap.add_argument("--from", dest="start", default="2019-01-01")
    ap.add_argument("--to", dest="end", default="")
    ap.add_argument("--probe", action="store_true", help="每年抽兩個星期睇有冇數據，唔寫唔上載")
    ap.add_argument("--probe-from", type=int, default=2010)
    ap.add_argument("--dry-run", action="store_true", help="只寫部機，唔上載")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    product = a.product.upper()
    if product not in ba.SPECS:
        sys.exit(f"唔識 {product}")
    today = datetime.now(ba.HKT).date()
    code = ba.quote_code(product)
    from futu import OpenQuoteContext
    quote = OpenQuoteContext(host=os.getenv("OPEND_HOST", "127.0.0.1"), port=int(os.getenv("OPEND_PORT", "11111")))
    try:
        if a.probe:
            for s, e in probe_days(a.probe_from, today):
                try:
                    rows = ba.fetch_1m(quote, code, s.isoformat(), e.isoformat(), extended=False)
                    days = ba.to_days(rows)
                    per = [len(v) for v in days.values()]
                    log.info("%s %s→%s：%d 日、每日 %s 條", code, s, e, len(days), per)
                except Exception as ex:  # noqa: BLE001
                    log.info("%s %s→%s：攞唔到（%s）", code, s, e, str(ex)[:120])
            return
        out_dir = Path(os.getenv("BARS_DIR", str(Path.home() / "zhuge" / "bars"))).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        sent_file = out_dir / "uploaded.json"
        try:
            sent = json.loads(sent_file.read_text())
        except (FileNotFoundError, ValueError):
            sent = {}
        url, token = os.getenv("ZHUGE_GCP_URL", "").strip(), os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
        if not a.dry_run and not (url and token):
            sys.exit("冇 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN：先 . ~/zhuge/env，或者加 --dry-run")
        end = date.fromisoformat(a.end) if a.end else today
        tot_d = tot_u = 0
        for s, e in month_ranges(date.fromisoformat(a.start), end):
            try:
                rows = ba.fetch_1m(quote, code, s.isoformat(), e.isoformat(), extended=False)
            except Exception as ex:  # noqa: BLE001
                log.warning("%s %s 攞唔到：%s", code, s.strftime("%Y-%m"), str(ex)[:120])
                continue
            nd, nu = save_and_upload(product, rows, out_dir, url, token, sent, a.dry_run)
            sent_file.write_text(json.dumps(sent, sort_keys=True))
            tot_d += nd
            tot_u += nu
            log.info("%s %s：%d 條、%d 日、上載 %d 日", code, s.strftime("%Y-%m"), len(rows), nd, nu)
        log.info("完成：%d 日、上載 %d 日", tot_d, tot_u)
    finally:
        quote.close()


if __name__ == "__main__":
    main()
