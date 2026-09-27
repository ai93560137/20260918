#!/usr/bin/env python3
"""外部來源每日彙整 → data/external/（預設分支 claude/gcp-trading-v12-rewrite-bz75t2）

由 .github/workflows/external_data_daily.yml 每天跑一次，把三個外部來源收進同一個地方：

  來源   原始位置                                             彙整到
  MT5    GCS archive/mt5_m1/<商品>/<券商日期>.json            data/external/mt5/<商品>/M1/<年>/<日期>.csv.gz
  Futu   GCS archive/futu_k_5m/<代號>/<美東日期>.json          data/external/futu/<代號>/K_5M/<年>/<日期>.csv.gz
         GCS archive/futu_options/<代號>/<美東日期>.json       data/external/futu/<代號>/options/<年>/<日期>.csv.gz
  IBKR   雲垂分支 claude/dazzling-curie-f3xzb8 的             data/external/ibkr/iv_term_structure/ib_iv_log.csv
         tradingview/data_external/ib_iv_log.csv、             data/external/ibkr/stock_closes/*.csv
         data_stock_ibkr/*.csv

MT5 / Futu 經 Cloud Run 的 ?view=archive&format=json&date=YYYY-MM-DD 讀取（main.py R95）。
Cloud Run 網址放 GitHub Secret ZHUGE_GCP_URL，不寫進 repo（這個 repo 是公開的）。
沒設就跳過 GCP 兩個來源，IBKR 照常同步，STATUS.md 會寫明原因。

每次重拉最近 EXTERNAL_DAYS 天（預設 10 天，涵蓋週末、漏跑與日線抽樣的回溯），與既有檔案按主鍵合併，
所以重跑不會重複、也不會把舊資料洗掉。gzip 固定 mtime=0，內容沒變就不產生 diff。

只存行情，不存帳戶淨值、持倉、權杖。
用法：
  ZHUGE_GCP_URL=https://… python3 scripts/external_data_sync.py
  python3 scripts/external_data_sync.py --days 10          # 補抓較長區間
"""
import argparse
import csv
import gzip
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("EXTERNAL_DIR") or ROOT / "data" / "external")   # 測試時可改到暫存區
IBKR_BRANCH = os.environ.get("IBKR_BRANCH", "claude/dazzling-curie-f3xzb8")
IBKR_REF = os.environ.get("IBKR_REF", f"origin/{IBKR_BRANCH}")
HTTP_TIMEOUT_SEC = 90
SAFE = re.compile(r"[^A-Za-z0-9._-]")

MT5_FIELDS = ["time_server", "time_utc", "open", "high", "low", "close", "time"]
KLINE_FIELDS = ["time_key", "open", "high", "low", "close", "volume"]
KDAY_FIELDS = ["code", "time_key", "open", "high", "low", "close", "volume"]
OPTION_FIELDS = ["asof_utc", "spot", "code", "option_type", "expiry", "strike", "iv", "delta",
                 "gamma", "vega", "theta", "last", "bid", "ask", "volume", "open_interest", "asof_ts"]


def utc_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- files
def read_csv_gz(path):
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv_gz(path, rows, fields):
    """Deterministic gzip: same rows → same bytes, so git sees no change."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fields})
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    data = raw.getvalue()
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def fmt_cell(value):
    """Floats written the same way every run (avoid 1.0 vs 1 churn)."""
    if isinstance(value, float):
        return repr(round(value, 8))
    return value


def merge_rows(existing, new, key_fields):
    merged = {tuple(str(r.get(k, "")) for k in key_fields): r for r in existing}
    for row in new:
        row = {k: fmt_cell(v) for k, v in row.items()}
        merged[tuple(str(row.get(k, "")) for k in key_fields)] = row
    return [merged[k] for k in sorted(merged)]


# ---------------------------------------------------------------- GCP series → paths
def series_target(source, instrument, day):
    """(path, fields, key_fields, extra) for one archived series, or None for unknown sources.
    extra 是要補進每一列的欄位（日線抽樣要記代號）。"""
    inst = SAFE.sub("_", instrument)
    year = day[:4]
    if source == "futu_k_day":                                  # [R96] 日線抽樣：同一天所有代號合成一個檔
        return OUT / "futu" / "_K_DAY" / year / f"{day}.csv.gz", KDAY_FIELDS, ("code", "time_key"), \
            {"code": instrument}
    if source == "mt5_m1":
        return OUT / "mt5" / inst / "M1" / year / f"{day}.csv.gz", MT5_FIELDS, ("time",), {}
    if source.startswith("futu_k_"):
        ktype = source[len("futu_"):].upper()                  # futu_k_5m → K_5M
        return OUT / "futu" / inst / ktype / year / f"{day}.csv.gz", KLINE_FIELDS, ("time_key",), {}
    if source == "futu_options":
        return OUT / "futu" / inst / "options" / year / f"{day}.csv.gz", OPTION_FIELDS, ("asof_ts", "code"), {}
    return None


def pull_gcp(base_url, days, status):
    if not base_url:
        status["gcp"] = {"ok": False, "note": "GitHub Secret ZHUGE_GCP_URL 沒設，MT5／Futu 未同步"}
        return
    base_url = base_url.rstrip("/") + "/"
    changed, fetched, unknown, errors = 0, {}, set(), []
    for day in days:
        try:
            resp = requests.get(base_url, params={"view": "archive", "format": "json", "date": day},
                                timeout=HTTP_TIMEOUT_SEC)
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{day}: {type(exc).__name__}")
            continue
        if resp.status_code != 200 or body.get("status") != "ok":
            errors.append(f"{day}: HTTP {resp.status_code} {body.get('status') or body.get('message')}")
            continue
        for key, rows in (body.get("data") or {}).items():
            source, _, instrument = key.partition("/")
            target = series_target(source, instrument, day)
            if target is None:
                unknown.add(source)
                continue
            path, fields, key_fields, extra = target
            merged = merge_rows(read_csv_gz(path), [{**row, **extra} for row in rows], key_fields)
            if write_csv_gz(path, merged, fields):
                changed += 1
            fetched[key] = fetched.get(key, 0) + len(rows)
    status["gcp"] = {"ok": not errors, "days": days, "files_changed": changed, "rows_fetched": fetched,
                     "errors": errors, "unknown_sources": sorted(unknown)}


# ---------------------------------------------------------------- IBKR mirror
def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def mirror_ibkr(status):
    # (來源, 目的地, 選用)：選用的檔還不存在不算缺（雲垂開始產生後自動同步）
    copies = [("tradingview/data_external/ib_iv_log.csv", OUT / "ibkr" / "iv_term_structure" / "ib_iv_log.csv", False),
              ("tradingview/data_external/ib_daily_sample.csv",                     # SOP 附錄 B：每日抽樣
               OUT / "ibkr" / "daily_sample" / "ib_daily_sample.csv", True)]
    try:
        listing = git("ls-tree", "--name-only", IBKR_REF, "data_stock_ibkr/").decode().split()
        copies += [(name, OUT / "ibkr" / "stock_closes" / Path(name).name, False)
                   for name in listing if name.endswith((".csv", ".txt"))]
        head = git("log", "-1", "--format=%H %cI", IBKR_REF).decode().strip()
    except subprocess.CalledProcessError as exc:
        status["ibkr"] = {"ok": False, "note": f"讀不到 {IBKR_REF}：{exc.stderr.decode(errors='replace').strip()[:200]}"}
        return
    changed, missing, pending = 0, [], []
    for src, dst, optional in copies:
        try:
            data = git("show", f"{IBKR_REF}:{src}")
        except subprocess.CalledProcessError:
            (pending if optional else missing).append(src)
            continue
        if dst.exists() and dst.read_bytes() == data:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        changed += 1
    status["ibkr"] = {"ok": not missing, "source_branch": IBKR_BRANCH, "source_commit": head,
                      "files": len(copies) - len(missing) - len(pending), "files_changed": changed,
                      "missing": missing, "not_yet": pending}


# ---------------------------------------------------------------- status
def latest_files(pattern):
    """{series: (latest_date, rows)} for every series dir matching pattern."""
    out = {}
    for path in sorted(OUT.glob(pattern)):
        series = str(path.parent.parent.relative_to(OUT))
        date = path.name[:10]
        if series not in out or date > out[series][0]:
            out[series] = (date, None, path)
    return {s: (d, len(read_csv_gz(p))) for s, (d, _, p) in out.items()}


def write_status(status):
    status["run_utc"] = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    series = latest_files("*/*/*/*/*.csv.gz")
    series.update(latest_files("futu/_K_DAY/*/*.csv.gz"))
    status["series"] = {k: {"latest_date": d, "rows": n} for k, (d, n) in series.items()}
    (OUT / "STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
    lines = [f"# 外部來源彙整狀態（{status['run_utc']} UTC 自動產生）", "",
             "| 系列 | 最新日期 | 該日列數 |", "|---|---|---:|"]
    lines += [f"| `{k}` | {d} | {n} |" for k, (d, n) in sorted(series.items())] or ["| （尚無） | | |"]
    gcp, ibkr = status.get("gcp", {}), status.get("ibkr", {})
    lines += ["", "## 本次執行", "",
              f"- **MT5／Futu（GCP）**：{'✅' if gcp.get('ok') else '⚠️'} "
              + (gcp.get("note") or f"拉 {len(gcp.get('days', []))} 天，變更 {gcp.get('files_changed', 0)} 個檔")
              + ("；錯誤：" + "；".join(gcp["errors"]) if gcp.get("errors") else "")
              + ("；未對應的來源：" + "、".join(gcp["unknown_sources"]) if gcp.get("unknown_sources") else ""),
              f"- **IBKR（{IBKR_BRANCH}）**：{'✅' if ibkr.get('ok') else '⚠️'} "
              + (ibkr.get("note") or f"{ibkr.get('files', 0)} 個檔，變更 {ibkr.get('files_changed', 0)} 個"
                 + (f"，來源 commit {ibkr.get('source_commit', '')[:8]} {ibkr.get('source_commit', '')[41:51]}"
                    if ibkr.get("source_commit") else "")
                 + ("；缺：" + "、".join(ibkr["missing"]) if ibkr.get("missing") else "")
                 + ("；尚未開始：" + "、".join(ibkr["not_yet"]) if ibkr.get("not_yet") else "")),
              "", "週末與假日沒有新 K 線是正常的；平日最新日期落後兩天以上才需要查。", ""]
    (OUT / "STATUS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=int(os.environ.get("EXTERNAL_DAYS", "10")))
    parser.add_argument("--skip-ibkr", action="store_true")
    args = parser.parse_args()
    today = utc_now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(max(1, args.days) - 1, -1, -1)]
    status = {}
    pull_gcp(os.environ.get("ZHUGE_GCP_URL", "").strip(), days, status)
    if not args.skip_ibkr:
        mirror_ibkr(status)
    OUT.mkdir(parents=True, exist_ok=True)
    write_status(status)
    print((OUT / "STATUS.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
