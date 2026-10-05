"""dukascopy-node 匯出的 CSV（timestamp 毫秒、open/high/low/close/volume）→ data/dukascopy/<name>.csv.gz（UTC 時間字串）。
用法：python3 scripts/dukascopy_to_csv.py 來源.csv 目的.csv.gz
"""
import csv, gzip, sys
from datetime import datetime, timezone

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src, encoding="utf-8")))
n = 0
with gzip.open(dst, "wt", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh); w.writerow(["time_utc", "open", "high", "low", "close", "volume"])
    for r in rows:
        try:
            ts = int(float(r["timestamp"])) / 1000
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, ValueError):
            continue
        if h < l or h <= 0:
            continue
        w.writerow([datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, r.get("volume", "")])
        n += 1
print(f"{dst}: {n} 列（原始 {len(rows)}）" + (f"，{rows[0]['timestamp']} → {rows[-1]['timestamp']}" if rows else ""))
