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


def _div_for(sym, first_open):
    lo_ok, hi_ok = (200, 20000) if sym == "XAUUSD" else (2, 200)
    for cand in (1000.0, 100000.0, 100.0):
        if lo_ok <= first_open / cand <= hi_ok:
            return cand
    return 1000.0


def _duka_days_to_h1(sym, y, m):
    """[IDEAS #194] 當月：逐日下載 /YYYY/MM(0 起)/DD/BID_candles_min_1.bi5（24 bytes／根：秒、開、收、低、高、量），合成 H1 [[utc, o, h, l, c], …]。
    只用已完結嘅鐘（唔要而家呢個鐘）；拎唔到嘅日子（假期、週末、未出）略過。"""
    import lzma, struct, time
    import urllib.request
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    hours = {}
    d = dt.date(y, m, 1)
    while d.month == m and d <= dt.date.today():
        url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{y:04d}/{m - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5"
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        except Exception as exc:  # noqa: BLE001
            print(f"{d} 日檔拎唔到：{exc}"); raw = None
        if raw:
            data = lzma.decompress(raw)
            recs = [struct.unpack(">5if", data[i * 24:(i + 1) * 24]) for i in range(len(data) // 24)]
            recs = [r for r in recs if r[1] > 0]
            if recs:
                div = _div_for(sym, recs[0][1])
                t0 = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
                for s_, o, c, lo, hi, v in recs:
                    if v <= 0 and o == c == lo == hi:
                        continue                                # 冇成交嘅平線分鐘
                    ts = t0 + s_; hk = ts - ts % 3600
                    if hk + 3600 > now:
                        continue
                    b = hours.get(hk)
                    if b is None:
                        hours[hk] = [hk, o / div, hi / div, lo / div, c / div]
                    else:
                        b[2] = max(b[2], hi / div); b[3] = min(b[3], lo / div); b[4] = c / div
        d += dt.timedelta(days=1)
        time.sleep(0.2)
    return [hours[k] for k in sorted(hours)]


def duka_h1(a):
    """[IDEAS #164] Dukascopy XAUUSD H1 BID：每月一個檔 /YYYY/MM(0 起)/BID_candles_hour_1.bi5（24 bytes／根：秒、開、收、低、高、量）。
    寫 GCS xau/sig/duka_h1/<YYYY-MM>.json＝[[utc, o, h, l, c], …]。"""
    import lzma, struct, time
    import urllib.request
    from google.cloud import storage
    bucket = None if a.dry_run else storage.Client().bucket(BUCKET)
    y, m = int(a.start[:4]), int(a.start[5:7]); y1, m1 = int(a.end[:4]), int(a.end[5:7])
    tot = 0
    while (y, m) <= (y1, m1):
        url = f"https://datafeed.dukascopy.com/datafeed/{a.sym}/{y:04d}/{m - 1:02d}/BID_candles_hour_1.bi5"
        raw = None
        for k in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = urllib.request.urlopen(req, timeout=60).read()
                break
            except Exception as exc:  # noqa: BLE001
                print(f"{y}-{m:02d} 第 {k + 1} 次失敗：{exc}")
                time.sleep(2 ** (k + 1))
        rows = []
        if not raw and (y, m) == (dt.date.today().year, dt.date.today().month):
            rows = _duka_days_to_h1(a.sym, y, m)                # [IDEAS #194] 當月未有月檔 → 用每日 M1 檔合成 H1
        if raw:
            data = lzma.decompress(raw)
            t0 = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp())
            recs = [struct.unpack(">5if", data[i * 24:(i + 1) * 24]) for i in range(len(data) // 24)]
            div = 1000.0
            for cand in (1000.0, 100000.0, 100.0):
                lo_ok, hi_ok = (200, 20000) if a.sym == "XAUUSD" else (2, 200)      # [IDEAS #168] XAGUSD 等
                if recs and lo_ok <= recs[0][1] / cand <= hi_ok:
                    div = cand
                    break
            rows = [[t0 + s, o / div, hi / div, lo / div, c / div] for s, o, c, lo, hi, v in recs if o > 0]
        print(f"duka_h1 {y}-{m:02d}：{len(rows)} 根" + (f"，{rows[0][4]:.2f} → {rows[-1][4]:.2f}" if rows else ""))
        tot += len(rows)
        if bucket and rows:
            bucket.blob(f"{PREFIX.replace('alt/', '')}duka_h1{'' if a.sym == 'XAUUSD' else '_' + a.sym.lower()}/{y:04d}-{m:02d}.json").upload_from_string(json.dumps(rows), content_type="application/json")
        m += 1
        if m == 13:
            y, m = y + 1, 1
        time.sleep(0.3)
    print(f"完成：duka_h1 共 {tot} 根")


def duka(a):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gb_rulesim"))
    import gb_rulesim as gb
    bars, st = gb.fetch_duka(a.start, a.end, cache=None if a.dry_run else gb.Gcs())
    print(f"duka：{st['bars']} 根；日數 {st['days']}、新下載 {st['ok']}、快取 {st['cached']}、空 {st['empty']}、失敗 {st['failed']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=("paxg", "gcf", "duka", "duka_h1"), required=True)
    ap.add_argument("--start", default="2026-07-24")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sym", default="XAUUSD", help="duka_h1 品種（XAUUSD 寫 duka_h1/；其他寫 duka_h1_<品種小寫>/）")
    a = ap.parse_args()
    if a.src == "duka":
        return duka(a)
    if a.src == "duka_h1":
        return duka_h1(a)
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
