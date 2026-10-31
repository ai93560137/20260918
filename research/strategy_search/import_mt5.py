"""匯入使用者上載嘅券商 MT5 歷史（UltimaMarkets，ExportM1／匯出 *_MAX.csv）到 GCS，以後回測用。
- 原檔：GCS xau/data/mt5/<zip 名>（原封不動）
- M1 轉 UTC，逐 UTC 日：GCS xau/sig/mt5m1/<YYYY-MM-DD>.json＝[[utc, open, high, low, close, tick_volume], …]
伺服器時間＝UTC+2（冬）／UTC+3（美國夏令時期間）；10-31 用 Dukascopy 重疊日核實（收市中位差 0.15–0.24 美元）。
用法：python3 research/strategy_search/import_mt5.py <zip 路徑> [--dry-run]"""
import csv
import datetime as dt
import io
import json
import os
import sys
import zipfile
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
RAW_PREFIX = "xau/data/mt5/"
M1_PREFIX = "xau/sig/mt5m1/"


def server_to_utc(s):
    naive = dt.datetime.strptime(s, "%Y.%m.%d %H:%M:%S")
    guess = naive.replace(tzinfo=dt.timezone.utc) - dt.timedelta(hours=2)
    off = 3 if guess.astimezone(NY).dst() else 2
    return int((naive.replace(tzinfo=dt.timezone.utc) - dt.timedelta(hours=off)).timestamp())


def main():
    path = sys.argv[1]
    dry = "--dry-run" in sys.argv
    z = zipfile.ZipFile(path)
    name = next(n for n in z.namelist() if "_M1_" in n)
    days = {}
    with z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, "utf-8"))
        next(r)
        for row in r:
            t = server_to_utc(row[0])
            d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()
            days.setdefault(d, []).append([t, float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(float(row[5]))])
    print(f"{name}：{sum(len(v) for v in days.values())} 根，{len(days)} 個 UTC 日，{min(days)}→{max(days)}")
    if dry:
        return
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gb_rulesim"))
    import gb_rulesim as gb
    g = gb.Gcs()
    raw_name = RAW_PREFIX + "XAUUSD_MAX_" + max(days) + ".zip"
    g.b.blob(raw_name).upload_from_filename(path, content_type="application/zip")
    print("原檔 →", raw_name)
    from concurrent.futures import ThreadPoolExecutor
    def up(item):
        d, rows = item
        rows.sort()
        g.write(f"{M1_PREFIX}{d}.json", json.dumps(rows), "application/json")
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(up, sorted(days.items())))
    print(f"M1 → {M1_PREFIX}<日>.json × {len(days)}")


if __name__ == "__main__":
    main()
