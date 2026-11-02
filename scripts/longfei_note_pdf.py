"""使用者分析文章原文＋圖 → PDF，放 GCS 畀網頁睇（使用者 11-02「我每一次嘅文章同埋圖片將佢變成一個PDF放在網上，
等我每一次睇返原文都會睇到」）。

輸出：GCS ops/longfei/analyst/user_notes/<YYYY-MM-DD_HHMM>.pdf ＋ index.json（[{file, posted_hkt, title, images}]，新到舊）。
網頁：main.py ?view=user_notes（清單）、?view=user_note&f=<檔名>（PDF）。

用法：
  補返舊文章（由龍飛陣工作階段紀錄抽原文同圖）：
    python3 scripts/longfei_note_pdf.py backfill --jsonl <工作階段.jsonl> [--since 2026-10-23] [--dry-run]
  加一篇新文章：
    python3 scripts/longfei_note_pdf.py add --text 原文.txt --posted "2026-11-02 19:45" 圖1.png [圖2.png ...]
PDF 用 Chromium 無頭模式由 HTML 印（Noto CJK 字型）。原文一字不改。
"""
import argparse
import base64
import html
import json
import mimetypes
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUCKET = "zhuge-risk-manager-bucket"
PREFIX = "ops/longfei/analyst/user_notes/"
HKT = timezone(timedelta(hours=8))
SKIP_PREFIX = ("這篇是不是之前已經上傳",)        # 使用者重覆貼嘅文章


def build_html(title, posted, text, images):
    paras = "".join(f"<p>{html.escape(p)}</p>" if p.strip() else "<br>" for p in text.split("\n"))
    imgs = "".join(f"<img src='data:{mt};base64,{b64}'>" for mt, b64 in images)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 14mm 12mm; }}
body {{ font-family: 'Noto Sans CJK TC','Noto Sans CJK SC','Noto Serif CJK TC',sans-serif; font-size: 12.5pt; line-height: 1.6; color: #111; }}
h1 {{ font-size: 16pt; margin: 0 0 4px; }} .meta {{ color: #666; font-size: 10pt; margin-bottom: 10px; }}
p {{ margin: 0 0 4px; white-space: pre-wrap; }} img {{ width: 100%; margin: 10px 0; page-break-inside: avoid; }}
</style></head><body><h1>{html.escape(title)}</h1><div class="meta">使用者原文　貼出時間：{html.escape(posted)} HKT</div>
{paras}{imgs}</body></html>"""


def to_pdf(html_text, out):
    """Chromium 無頭模式印 PDF（環境預裝 /opt/pw-browsers/chromium；冇就用 PATH 入面嘅 chromium）。"""
    import shutil
    import subprocess
    exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else (
        shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome"))
    src = Path(out).with_suffix(".html")
    src.write_text(html_text, encoding="utf-8")
    subprocess.run([exe, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out}", src.as_uri()], check=True, capture_output=True, timeout=180)
    src.unlink()


def title_of(text):
    for line in text.split("\n"):
        if line.strip():
            return line.strip()[:80]
    return "（無標題）"


def upload(notes, dry):
    """notes: [(posted_dt, text, [(mime, b64)])] → 上傳 PDF 同更新 index.json。"""
    work = Path("/tmp/longfei_note_pdf")
    work.mkdir(exist_ok=True)
    bucket = None
    index = []
    if not dry:
        from google.cloud import storage
        bucket = storage.Client().bucket(BUCKET)
        b = bucket.blob(PREFIX + "index.json")
        if b.exists():
            index = json.loads(b.download_as_bytes())
    have = {it["file"] for it in index}
    for dt, text, imgs in notes:
        name = dt.strftime("%Y-%m-%d_%H%M") + ".pdf"
        title = title_of(text)
        posted = dt.strftime("%Y-%m-%d %H:%M")
        out = work / name
        to_pdf(build_html(title, posted, text, imgs), out)
        print(f"{name}  {out.stat().st_size // 1024} KB  {len(imgs)} 張圖  {title}")
        if dry:
            continue
        bucket.blob(PREFIX + name).upload_from_filename(str(out), content_type="application/pdf")
        if name not in have:
            index.append({"file": name, "posted_hkt": posted, "title": title, "images": len(imgs)})
            have.add(name)
    if not dry:
        index.sort(key=lambda it: it["posted_hkt"], reverse=True)
        bucket.blob(PREFIX + "index.json").upload_from_string(json.dumps(index, ensure_ascii=False),
                                                               content_type="application/json")
        print(f"index.json：{len(index)} 篇")


def cmd_backfill(a):
    notes = []
    for line in open(a.jsonl, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "user":
            continue
        c = (d.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        imgs = [(b["source"].get("media_type", "image/png"), b["source"]["data"]) for b in c
                if b.get("type") == "image" and (b.get("source") or {}).get("type") == "base64"]
        text = "\n".join(b.get("text", "") for b in c if b.get("type") == "text").strip()
        text = re.sub(r"\n*The \d+ attached images?.*$|\n*The attached image is also saved at.*$", "", text, flags=re.S).strip()
        if not imgs or len(text) < 30 or text.startswith(SKIP_PREFIX):
            continue
        dt = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone(HKT)
        if dt.strftime("%Y-%m-%d") < a.since:
            continue
        notes.append((dt, text, imgs))
    print(f"搵到 {len(notes)} 篇")
    upload(notes, a.dry_run)


def cmd_add(a):
    text = Path(a.text).read_text(encoding="utf-8").strip()
    imgs = []
    for p in a.images:
        mt = mimetypes.guess_type(p)[0] or "image/png"
        imgs.append((mt, base64.b64encode(Path(p).read_bytes()).decode("ascii")))
    dt = datetime.strptime(a.posted, "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
    upload([(dt, text, imgs)], a.dry_run)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--jsonl", required=True)
    b.add_argument("--since", default="2026-10-23")
    b.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("add")
    d.add_argument("--text", required=True)
    d.add_argument("--posted", required=True)
    d.add_argument("images", nargs="*")
    d.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    {"backfill": cmd_backfill, "add": cmd_add}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
