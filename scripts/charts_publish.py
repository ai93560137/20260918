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


def hsi_fib(tmp, bucket):
    """龍飛陣斐波那契：下載最近 200 日 1 分鐘恒指即月 K 線，跑 hsi_fib.py。"""
    src = os.path.join(tmp, "k")
    os.makedirs(src, exist_ok=True)
    blobs = sorted(bucket.list_blobs(prefix="archive/futu_k_1m/HK.HSI_FRONT/"), key=lambda b: b.name)[-200:]
    for b in blobs:
        try:      # 唔帶 generation：今日嘅檔每分鐘重寫，用舊 generation 會 404
            bucket.blob(b.name).download_to_filename(os.path.join(src, os.path.basename(b.name)))
        except Exception as exc:
            print(f"略過 {b.name}：{exc}", file=sys.stderr)
    png = os.path.join(tmp, "hsi_fib_4h.png")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "research/longfei_lessons/hsi_fib.py"), src, png],
                         check=True, capture_output=True, text=True)
    return png, json.loads(out.stdout.strip().splitlines()[-1])


CHARTS = [
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
