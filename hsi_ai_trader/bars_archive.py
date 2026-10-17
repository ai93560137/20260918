"""[R218] 收市後將龍飛陣各產品嘅 1 分鐘 OHLC 存入私人 GCS（longfei/bars/<產品>/<日>.json），將來覆盤、回測用。

由 zhuge-longfei-bars.timer 每星期二至六 08:10 HKT 跑一次（美股盤後 08:00 收、恒指夜盤 03:00 收）。
- 向富途攞最近 6 日嘅 1 分鐘 K 線（美股包盤前盤後），按交易所當地日期分檔，先寫部機 ~/zhuge/bars/。
- 內容同上次上載唔同先經 Cloud Run（action=longfei_bars）上載：未齊嘅日子下次會補返，重複上載會覆蓋。
- 唔落單、唔解鎖交易；VM 冇 GCS 寫入權，同 push.py 一樣經 webhook。權杖唔寫入 log。
用法：python bars_archive.py [--days 6] [--products HSI,SPY] [--dry-run]
"""
import argparse
import hashlib
import inspect
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from markets import SPECS, spec_for

log = logging.getLogger("bars")
HKT = timezone(timedelta(hours=8))
FIELDS = ["t", "o", "h", "l", "c", "v"]
REQ_GAP_SEC = 0.6          # 富途歷史 K 線限速：每 30 秒 60 次


def products_from_env():
    """HSI ＋ settings.env 嘅模擬同真倉產品（同 longfei_units.sh 一致）。"""
    out = ["HSI"]
    for key in ("LONGFEI_EXTRA_PRODUCTS", "LONGFEI_REAL_PRODUCTS"):
        for p in os.getenv(key, "").upper().replace(" ", "").split(","):
            if p and p in SPECS and p not in out:
                out.append(p)
    return out


def quote_code(product):
    sp = spec_for(product)
    return f"US.{product}" if sp.kind == "stock" else f"{sp.market}.{product}main"   # 期貨用主連，唔使理轉倉


def to_days(rows):
    """[(time_key, o, h, l, c, v)] → {日期: [[HH:MM, o, h, l, c, v], ...]}，按時間排、同一分鐘去重。"""
    days = {}
    for tk, o, h, l, c, v in rows:
        tk = str(tk)
        days.setdefault(tk[:10], {})[tk[11:16]] = [tk[11:16], o, h, l, c, v]
    return {d: [m[k] for k in sorted(m)] for d, m in days.items()}


def fetch_1m(quote, code, start, end, extended):
    from futu import AuType, KLType, RET_OK
    params = inspect.signature(quote.request_history_kline).parameters
    kw = {"extended_time": True} if extended and "extended_time" in params else {}
    rows, key = [], None
    while True:
        ret, df, key = quote.request_history_kline(code, start=start, end=end, ktype=KLType.K_1M,
                                                   autype=AuType.NONE, max_count=1000, page_req_key=key, **kw)
        if ret != RET_OK:
            raise RuntimeError(f"request_history_kline {code}: {df}")
        rows += [(r["time_key"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                  float(r["volume"])) for _, r in df.iterrows()]
        time.sleep(REQ_GAP_SEC)
        if key is None:
            return rows


def upload(url, token, product, day, bars):
    body = json.dumps({"action": "longfei_bars", "token": token, "product": product, "date": day,
                       "fields": FIELDS, "bars": bars}, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        log.warning("上載 %s %s 失敗：%s", product, day, e.__class__.__name__)   # 唔印網址／權杖
        return False


def run(quote, products, days, out_dir: Path, url, token, dry_run=False, today=None):
    today = today or datetime.now(HKT).date()
    start, end = (today - timedelta(days=days)).isoformat(), today.isoformat()
    sent_file = out_dir / "uploaded.json"
    try:
        sent = json.loads(sent_file.read_text())
    except (FileNotFoundError, ValueError):
        sent = {}
    summary = {}
    for p in products:
        try:
            rows = fetch_1m(quote, quote_code(p), start, end, extended=spec_for(p).kind == "stock")
        except Exception as e:  # noqa: BLE001
            log.warning("%s 攞 1 分鐘 K 線失敗：%s", p, e)
            summary[p] = "error"
            continue
        n_up = 0
        for day, bars in sorted(to_days(rows).items()):
            text = json.dumps(bars, separators=(",", ":"))
            f = out_dir / p / f"{day}.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
            digest = hashlib.sha256(text.encode()).hexdigest()[:16]
            if sent.get(f"{p}/{day}") == digest or dry_run or not (url and token):
                continue
            if upload(url, token, p, day, bars):
                sent[f"{p}/{day}"] = digest
                n_up += 1
        summary[p] = f"{len(rows)} 條，上載 {n_up} 日"
        sent_file.write_text(json.dumps(sent, sort_keys=True))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--products", default="")
    ap.add_argument("--dry-run", action="store_true", help="只寫部機，唔上載")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    products = [p for p in a.products.upper().split(",") if p in SPECS] if a.products else products_from_env()
    out_dir = Path(os.getenv("BARS_DIR", str(Path.home() / "zhuge" / "bars"))).expanduser()
    from futu import OpenQuoteContext
    quote = OpenQuoteContext(host=os.getenv("OPEND_HOST", "127.0.0.1"), port=int(os.getenv("OPEND_PORT", "11111")))
    try:
        summary = run(quote, products, a.days, out_dir, os.getenv("ZHUGE_GCP_URL", "").strip(),
                      os.getenv("WEBHOOK_SECRET_TOKEN", "").strip(), a.dry_run)
    finally:
        quote.close()
    for p, s in summary.items():
        log.info("%s：%s", p, s)
    sys.exit(1 if summary and all(s == "error" for s in summary.values()) else 0)


if __name__ == "__main__":
    main()
