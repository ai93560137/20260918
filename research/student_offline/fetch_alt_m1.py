"""另類黃金 M1 數據（使用者 10-31「rev15 離線用其他數據源再試」）：雲端工作階段連唔到外網，由 GitHub Actions 跑，寫入 GCS。
  paxg：Binance 公開歸檔 data.binance.vision 嘅 PAXGUSDT 1 分鐘（代幣化黃金，24／7；週末段之後分析時剔走）
  gcf ：yfinance GC=F 期貨 1 分鐘（只可以拎最近 7 日）
  duka：Dukascopy 現貨補數（用 gb_rulesim.fetch_duka，寫佢嘅快取 xau/sig/duka/<日>.json；10-31 為 0342／5117 交叉驗證補 10-29 之後）
輸出 GCS xau/sig/alt/<src>/<UTC 日>.json＝[[utc, open, high, low, close], …]。只有價格。
用法：python3 research/student_offline/fetch_alt_m1.py --src paxg --start 2026-07-24 --end 2026-10-31"""
import argparse
import csv
import datetime as dt
import io
import json
import urllib.request
import zipfile

BUCKET = "zhuge-risk-manager-bucket"
PREFIX = "xau/sig/alt/"


def days(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]


def paxg_day(d):
    url = f"https://data.binance.vision/data/spot/daily/klines/PAXGUSDT/1m/PAXGUSDT-1m-{d}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=60).read()
    except Exception as exc:  # noqa: BLE001
        print(f"{d} paxg 拎唔到：{exc}")
        return []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = []
    for r in csv.reader(io.StringIO(text)):
        t = int(r[0])
        t = t // 1_000_000 if t > 10**14 else t // 1000        # 2025 起現貨歸檔用微秒，之前毫秒
        rows.append([t, float(r[1]), float(r[2]), float(r[3]), float(r[4])])
    return rows


def gcf_all():
    import yfinance as yf
    df = yf.Ticker("GC=F").history(period="7d", interval="1m")
    out = {}
    for ts, row in df.iterrows():
        t = int(ts.timestamp())
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()
        out.setdefault(d, []).append([t, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])])
    return out


def duka(a):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gb_rulesim"))
    import gb_rulesim as gb
    bars, st = gb.fetch_duka(a.start, a.end, cache=None if a.dry_run else gb.Gcs())
    print(f"duka：{st['bars']} 根；日數 {st['days']}、新下載 {st['ok']}、快取 {st['cached']}、空 {st['empty']}、失敗 {st['failed']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=("paxg", "gcf", "duka"), required=True)
    ap.add_argument("--start", default="2026-07-24")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.src == "duka":
        return duka(a)
    from google.cloud import storage
    bucket = None if a.dry_run else storage.Client().bucket(BUCKET)
    got = {d: paxg_day(d) for d in days(a.start, a.end)} if a.src == "paxg" else gcf_all()
    n = 0
    for d, rows in sorted(got.items()):
        if not rows:
            continue
        rows.sort()
        n += len(rows)
        print(f"{a.src} {d}：{len(rows)} 根，{rows[0][4]:.2f} → {rows[-1][4]:.2f}")
        if bucket:
            bucket.blob(f"{PREFIX}{a.src}/{d}.json").upload_from_string(json.dumps(rows), content_type="application/json")
    print(f"完成：{a.src} 共 {n} 根")


if __name__ == "__main__":
    main()
