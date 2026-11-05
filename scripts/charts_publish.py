"""[R258] 📐 分析圖：跑分析腳本出圖，上載 GCS charts/，更新 charts/index.json，舊服務 ?view=charts 顯示。

使用者 10-23（經龍飛陣）：「分析圖、報告都想放喺網頁上面，唔好只係傳檔案」。由總指揮負責。
而家只有一張：龍飛陣 恒指即月期貨 4 小時線斐波那契（research/longfei_lessons/hsi_fib.py）。
加新圖：喺 CHARTS 加一項（id、標題、陣、說明、點樣出圖），workflow charts_publish.yml 就會一齊跑。

用法：python3 scripts/charts_publish.py [--only hsi_fib_4h] [--dry-run]（--dry-run 只出圖唔上載）
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKET = os.environ.get("GCS_BUCKET", "zhuge-risk-manager-bucket")
HKT = timezone(timedelta(hours=8))
INDEX = "charts/index.json"


def hsi_fib(tmp, bucket, tf="4h", ndays=200):
    """龍飛陣斐波那契：下載最近 ndays 日 1 分鐘恒指即月 K 線，跑 hsi_fib.py（tf＝4h／1d）。"""
    src = os.path.join(tmp, "k")
    os.makedirs(src, exist_ok=True)
    blobs = sorted(bucket.list_blobs(prefix="archive/futu_k_1m/HK.HSI_FRONT/"), key=lambda b: b.name)[-ndays:]
    for b in blobs:
        try:      # 唔帶 generation：今日嘅檔每分鐘重寫，用舊 generation 會 404
            bucket.blob(b.name).download_to_filename(os.path.join(src, os.path.basename(b.name)))
        except Exception as exc:
            print(f"略過 {b.name}：{exc}", file=sys.stderr)
    png = os.path.join(tmp, f"hsi_fib_{tf}.png")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "research/longfei_lessons/hsi_fib.py"), src, png, tf],
                         check=True, capture_output=True, text=True)
    return png, json.loads(out.stdout.strip().splitlines()[-1])


_XAU_H1 = {}


def xau_h1_csv(tmp, bucket):
    """🌌 天覆陣：GCS xau/sig/duka_h1/<月>.json（2005 起，[t,o,h,l,c]）＋經紀 M1 xau/sig/bars/<日>.jsonl 補 Dukascopy 之後嘅鐘
    → H1 CSV（t_utc,o,h,l,c）。週末平線（h==l 且同上一根收市一樣）剔走。四張圖共用，只砌一次。"""
    if "csv" in _XAU_H1 and os.path.exists(_XAU_H1["csv"]):
        return _XAU_H1["csv"]
    rows = {}
    for b in sorted(bucket.list_blobs(prefix="xau/sig/duka_h1/"), key=lambda b: b.name):
        try:
            for r in json.loads(bucket.blob(b.name).download_as_text()):
                rows[int(r[0])] = [float(x) for x in r[1:5]]
        except Exception as exc:
            print(f"略過 {b.name}：{exc}", file=sys.stderr)
    last = max(rows) if rows else 0
    m1 = {}
    for b in sorted(bucket.list_blobs(prefix="xau/sig/bars/"), key=lambda b: b.name)[-40:]:
        try:
            txt = bucket.blob(b.name).download_as_text()
        except Exception as exc:
            print(f"略過 {b.name}：{exc}", file=sys.stderr)
            continue
        for ln in txt.splitlines():
            try:
                arr = json.loads(ln)
            except ValueError:
                continue
            for x in arr if isinstance(arr, list) else [arr]:
                if isinstance(x, dict) and x.get("utc"):
                    m1[int(x["utc"])] = (float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]))
    for t in sorted(m1):
        k = t // 3600 * 3600
        if k <= last:
            continue
        o, h, l, c = m1[t]
        r = rows.get(k)
        rows[k] = [o, h, l, c] if r is None else [r[0], max(r[1], h), min(r[2], l), c]
    path = os.path.join(tmp, "xau_h1.csv")
    prev = None
    with open(path, "w") as f:
        for t in sorted(rows):
            o, h, l, c = rows[t]
            if h == l and prev == c:
                continue
            prev = c
            f.write(f"{t},{o},{h},{l},{c}\n")
    _XAU_H1["csv"] = path
    return path


def xau_fib(tf):
    def make(tmp, bucket):
        src = xau_h1_csv(_XAU_H1.setdefault("dir", tempfile.mkdtemp()), bucket)
        png = os.path.join(tmp, f"xau_fib_{tf.lower()}.png")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "research/tianfu_charts/xau_fib.py"), src, png, tf],
                             check=True, capture_output=True, text=True)
        return png, json.loads(out.stdout.strip().splitlines()[-1])
    return make


XAU_DESC = ("程式自己揀波段（回望期內最高點同最低點；高點喺後＝升浪回撤、低點喺後＝跌浪反彈），劃 0.236–0.886 位同 50／100／200 均線；"
            "Dukascopy H1＋經紀 M1，MT5 伺服器時間（紐約 17:00 換日）。")

CHARTS = [
    # [天覆陣 11-05] 使用者「參考龍飛陣，用斐波那契回撤分析圖在月、週、日、H4」：XAUUSD 四個時間框（排頭，龍飛陣圖排尾出圖仍然最新）
    {"id": "xau_fib_m", "title": "XAUUSD 黃金 月線・斐波那契回撤", "team": "🌌 天覆陣",
     "desc": "回望 120 個月。" + XAU_DESC, "make": xau_fib("M")},
    {"id": "xau_fib_w", "title": "XAUUSD 黃金 週線・斐波那契回撤", "team": "🌌 天覆陣",
     "desc": "回望 104 週。" + XAU_DESC, "make": xau_fib("W")},
    {"id": "xau_fib_d", "title": "XAUUSD 黃金 日線・斐波那契回撤", "team": "🌌 天覆陣",
     "desc": "回望 180 日。" + XAU_DESC, "make": xau_fib("D")},
    {"id": "xau_fib_h4", "title": "XAUUSD 黃金 4 小時線・斐波那契回撤", "team": "🌌 天覆陣",
     "desc": "回望 180 根（約 30 個交易日）。" + XAU_DESC, "make": xau_fib("H4")},
    # [R364] 使用者 10-30「恒指加番日線，同斐波那契回撤」：同 4 小時線同一個波段；下載全部 1 分鐘存檔（約一年）先夠 SMA200
    {"id": "hsi_fib_1d", "title": "恒指即月期貨 日線・斐波那契回撤", "team": "🐉 龍飛陣",
     "desc": "同 4 小時線同一個波段（最近 90 日最高點同佢之前嘅最低點），劃 0.236–0.886 回撤位同 50／100／200 日均線；夜市歸下一個交易日。",
     "make": lambda tmp, bucket: hsi_fib(tmp, bucket, "1d", 400)},
    # 4 小時線排尾出圖：updated_hkt 較新，網頁（按更新時間新到舊）會排第一
    {"id": "hsi_fib_4h", "title": "恒指即月期貨 4 小時線・斐波那契回撤", "team": "🐉 龍飛陣",
     "desc": "程式自己揀波段（最近 90 日最高點同佢之前嘅最低點），劃 0.236–0.886 回撤位同 50／100／200 均線；日市＋夜市，香港時間。",
     "make": hsi_fib},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from google.cloud import storage
    bucket = storage.Client().bucket(BUCKET)
    blob = bucket.blob(INDEX)
    index = json.loads(blob.download_as_text()) if blob.exists() else {"items": []}
    items = {it["id"]: it for it in index.get("items", [])}
    for c in CHARTS:
        if args.only and c["id"] != args.only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            png, data = c["make"](tmp, bucket)
            print(c["id"], json.dumps(data, ensure_ascii=False))
            if args.dry_run:
                continue
            bucket.blob(f"charts/{c['id']}.png").upload_from_filename(png, content_type="image/png")
            bucket.blob(f"charts/{c['id']}.json").upload_from_string(json.dumps(data, ensure_ascii=False),
                                                                    content_type="application/json")
        items[c["id"]] = {k: c[k] for k in ("id", "title", "team", "desc")} | {
            "png": f"charts/{c['id']}.png", "json": f"charts/{c['id']}.json",
            "updated_hkt": datetime.now(HKT).strftime("%Y-%m-%d %H:%M")}
    if not args.dry_run:
        blob.upload_from_string(json.dumps({"items": list(items.values())}, ensure_ascii=False, indent=1),
                                content_type="application/json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
