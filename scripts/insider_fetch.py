#!/usr/bin/env python3
# =============================================================================
# 內部人公開市場買入（SEC Form 4）資料抓取
# -----------------------------------------------------------------------------
# 數據源：SEC「Insider Transactions Data Sets」——每季一個 zip，從 Form 3/4/5 的 XML
#   原樣攤平成 TSV（2006Q1 起）：
#   https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{年}q{季}_form345.zip
#   用到三張表（以 ACCESSION_NUMBER 串起來）：
#     SUBMISSION      FILING_DATE、DOCUMENT_TYPE（4 / 4/A）、ISSUERCIK、ISSUERNAME、ISSUERTRADINGSYMBOL
#     REPORTINGOWNER  RPTOWNERCIK、RPTOWNERNAME、RPTOWNER_RELATIONSHIP（Director/Officer/TenPercentOwner…）、
#                     RPTOWNER_TITLE
#     NONDERIV_TRANS  TRANS_DATE、TRANS_CODE（P = 公開市場買入）、TRANS_SHARES、TRANS_PRICEPERSHARE、
#                     TRANS_ACQUIRED_DISP_CD、SHRS_OWND_FOLWNG_TRANS、DIRECT_INDIRECT_OWNERSHIP
# 只保留 TRANS_CODE = P 且為取得（A）的非衍生性交易，每年一個檔：
#   data/insider/purchases/{年}.csv.gz
# 已處理過的季度記在 data/insider/state.json，之後只重抓最近兩季（SEC 會補登延遲申報）。
#
# SEC 要求 User-Agent 帶聯絡方式（否則回 403），用環境變數 SEC_USER_AGENT 設定，
# 例如 "YourName research you@example.com"（workflow 從 repo secret 讀）。
#
# 用法：
#   python3 scripts/insider_fetch.py                 # 補齊缺的季度 + 重抓最近兩季
#   python3 scripts/insider_fetch.py --from 2015q1   # 只從某季開始
#   python3 scripts/insider_fetch.py --refresh-all   # 全部重抓
# =============================================================================
import argparse
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timezone

import requests

BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
# 檔名大小寫沒有把握（2025Q1_form345.zip / 2025q1_form345.zip），S3 對不存在的路徑也回 403，
# 所以先從 SEC 的資料集頁面抓真正的連結；抓不到才兩種大小寫都試。
URL_VARIANTS = [BASE + "{y}q{q}_form345.zip", BASE + "{y}Q{q}_form345.zip"]
LIST_PAGES = ["https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets",
              "https://www.sec.gov/dera/data/form-345"]
LINK_RE = re.compile(r'href="([^"]*?(\d{4})[qQ]([1-4])_form345\.zip)"')
FIRST_QUARTER = (2006, 1)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "insider")
PURCHASE_DIR = os.path.join(OUT_DIR, "purchases")
STATE_FILE = os.path.join(OUT_DIR, "state.json")
SAMPLE_DIR = os.path.join(OUT_DIR, "_sample")  # 最新一季每張表前幾行，欄位變動時方便對照

FIELDS = ["quarter", "accession", "filing_date", "trans_date", "doc_type", "ticker", "issuer_cik", "issuer_name",
          "owner_cik", "owner_name", "relationship", "title", "shares", "price", "value",
          "shares_after", "direct"]
REQUIRED = {
    "SUBMISSION": ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
                   "ISSUERTRADINGSYMBOL"],
    "REPORTINGOWNER": ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP"],
    "NONDERIV_TRANS": ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                       "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"],
}


def user_agent():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        sys.exit("請設定環境變數 SEC_USER_AGENT（例如 \"YourName research you@example.com\"），"
                 "SEC 會擋掉沒有聯絡方式的請求")
    return ua


def parse_date(s):
    """SEC 資料集日期是 31-DEC-2020；也接受 2020-12-31、12/31/2020。失敗回 None。"""
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_float(s):
    try:
        return float((s or "").replace(",", ""))
    except ValueError:
        return None


def quarters(start, end):
    y, q = start
    while (y, q) <= end:
        yield y, q
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)


def last_published_quarter(today=None):
    """最後一季 = 本季。資料集在季末後才上線，本季多半 404（不算失敗），上線後由重抓最近兩季補上。"""
    today = today or datetime.now(timezone.utc).date()
    q = (today.month - 1) // 3 + 1
    return (today.year, q)


def read_tsv(z, name):
    """讀 zip 內的表（檔名大小寫/路徑不一定），回傳 (header, rows iterator)。"""
    member = next((n for n in z.namelist() if os.path.basename(n).upper() == f"{name}.TSV"), None)
    if member is None:
        raise RuntimeError(f"zip 裡沒有 {name}.tsv（內容：{z.namelist()}）")
    fh = io.TextIOWrapper(z.open(member), encoding="utf-8", errors="replace", newline="")
    reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = [h.strip().upper() for h in next(reader)]
    missing = [c for c in REQUIRED[name] if c not in header]
    if missing:
        raise RuntimeError(f"{name}.tsv 缺欄位 {missing}；實際欄位：{header}")
    return header, reader


def extract_purchases(zip_bytes, sample_dir=None):
    """一季 zip → 公開市場買入明細（每位申報人一列；聯名申報會展開成多列）。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        if sample_dir:
            os.makedirs(sample_dir, exist_ok=True)
            for name in REQUIRED:
                member = next((n for n in z.namelist() if os.path.basename(n).upper() == f"{name}.TSV"), None)
                if member:
                    with z.open(member) as src, open(os.path.join(sample_dir, f"{name}.tsv"), "wb") as dst:
                        dst.write(b"".join(src.readline() for _ in range(4)))

        header, rows = read_tsv(z, "NONDERIV_TRANS")
        ix = {h: i for i, h in enumerate(header)}
        trans = []
        for r in rows:
            if len(r) < len(header):
                continue
            if r[ix["TRANS_CODE"]].strip().upper() != "P":
                continue
            if r[ix["TRANS_ACQUIRED_DISP_CD"]].strip().upper() not in ("A", ""):
                continue
            shares = to_float(r[ix["TRANS_SHARES"]])
            price = to_float(r[ix["TRANS_PRICEPERSHARE"]])
            td = parse_date(r[ix["TRANS_DATE"]])
            if not shares or shares <= 0 or td is None:
                continue
            get = lambda col: r[ix[col]].strip() if col in ix else ""
            trans.append({
                "accession": r[ix["ACCESSION_NUMBER"]].strip(),
                "trans_date": td.isoformat(),
                "shares": shares,
                "price": price,
                "value": round(shares * price, 2) if price else None,
                "shares_after": to_float(get("SHRS_OWND_FOLWNG_TRANS")),
                "direct": get("DIRECT_INDIRECT_OWNERSHIP"),
            })
        need = {t["accession"] for t in trans}

        header, rows = read_tsv(z, "SUBMISSION")
        ix = {h: i for i, h in enumerate(header)}
        subs = {}
        for r in rows:
            if len(r) < len(header):
                continue
            acc = r[ix["ACCESSION_NUMBER"]].strip()
            if acc not in need:
                continue
            fd = parse_date(r[ix["FILING_DATE"]])
            subs[acc] = {
                "filing_date": fd.isoformat() if fd else "",
                "doc_type": r[ix["DOCUMENT_TYPE"]].strip(),
                "ticker": r[ix["ISSUERTRADINGSYMBOL"]].strip().upper(),
                "issuer_cik": r[ix["ISSUERCIK"]].strip(),
                "issuer_name": r[ix["ISSUERNAME"]].strip(),
            }

        header, rows = read_tsv(z, "REPORTINGOWNER")
        ix = {h: i for i, h in enumerate(header)}
        owners = {}
        for r in rows:
            if len(r) < len(header):
                continue
            acc = r[ix["ACCESSION_NUMBER"]].strip()
            if acc not in need:
                continue
            owners.setdefault(acc, []).append({
                "owner_cik": r[ix["RPTOWNERCIK"]].strip(),
                "owner_name": r[ix["RPTOWNERNAME"]].strip(),
                "relationship": r[ix["RPTOWNER_RELATIONSHIP"]].strip(),
                "title": r[ix["RPTOWNER_TITLE"]].strip() if "RPTOWNER_TITLE" in ix else "",
            })

    out = []
    for t in trans:
        s = subs.get(t["accession"])
        if not s or not s["filing_date"]:
            continue
        for o in owners.get(t["accession"], [{"owner_cik": "", "owner_name": "", "relationship": "",
                                              "title": ""}]):
            out.append({**t, **s, **o})
    return out


def discover_links(ua):
    """從 SEC 資料集頁面抓每季 zip 的真正連結。回傳 ({(年, 季): url}, {頁面: HTTP 狀態})。"""
    links, status = {}, {}
    for page in LIST_PAGES:
        try:
            r = requests.get(page, headers=ua, timeout=60)
        except requests.RequestException as e:
            status[page] = str(e)
            continue
        status[page] = r.status_code
        if r.status_code != 200:
            continue
        for href, y, q in LINK_RE.findall(r.text):
            url = href if href.startswith("http") else "https://www.sec.gov" + (href if href.startswith("/") else "/" + href)
            links.setdefault((int(y), int(q)), url)
        if links:
            break
    return links, status


def download(urls, ua, label):
    """依序試每個網址。404/403 當作「這個網址不存在」換下一個；其他錯誤重試。全失敗回 None。"""
    for url in urls:
        for i in range(4):
            try:
                r = requests.get(url, headers=ua, timeout=300)
                if r.status_code in (403, 404):
                    print(f"  {label}：{url} → {r.status_code}", flush=True)
                    break
                r.raise_for_status()
                return r.content
            except requests.RequestException as e:
                print(f"  {label} 第 {i + 1} 次失敗：{e}", flush=True)
                time.sleep(5 * (i + 1))
    return None


def write_year(year, rows):
    os.makedirs(PURCHASE_DIR, exist_ok=True)
    rows.sort(key=lambda r: (r["filing_date"], r["ticker"], r["owner_cik"], r["trans_date"]))
    path = os.path.join(PURCHASE_DIR, f"{year}.csv.gz")
    # mtime=0：內容沒變時 gzip 位元組也一樣，git 才不會每次都有 diff
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, \
            io.TextIOWrapper(gz, encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_year(year):
    path = os.path.join(PURCHASE_DIR, f"{year}.csv.gz")
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser(description="SEC Form 4 內部人買入資料抓取")
    ap.add_argument("--from", dest="start", default=f"{FIRST_QUARTER[0]}q{FIRST_QUARTER[1]}")
    ap.add_argument("--refresh-all", action="store_true")
    ap.add_argument("--refresh-recent", type=int, default=2, help="重抓最近幾季（預設 2）")
    args = ap.parse_args()

    start = (int(args.start[:4]), int(args.start[-1]))
    end = last_published_quarter()
    all_q = list(quarters(start, end))
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {"done": {}}
    recent = set(all_q[-args.refresh_recent:]) if args.refresh_recent else set()
    todo = [yq for yq in all_q
            if args.refresh_all or f"{yq[0]}q{yq[1]}" not in state["done"] or yq in recent]
    print(f"季度 {len(all_q)} 個，這次要抓 {len(todo)} 個")

    ua = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    by_year = {}
    failed = []
    def save(y):
        # 同一筆（accession + 申報人 + 日期 + 股數 + 價格）只留一次
        seen, uniq = set(), []
        for r in by_year[y]:
            k = (r["accession"], r["owner_cik"], r["trans_date"], str(r["shares"]), str(r["price"]))
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        by_year[y] = uniq
        write_year(y, uniq)
        state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=1)

    links, page_status = discover_links(ua)
    print(f"資料集頁面：{page_status}；找到 {len(links)} 個季度連結"
          + (f"（例：{next(iter(links.values()))}）" if links else ""), flush=True)
    if links == {} and page_status and all(c == 403 for c in page_status.values()):
        print(f"SEC 資料集頁面也回 403——是 User-Agent 被擋，不是網址錯。請把 SEC_USER_AGENT"
              f"（目前：{ua['User-Agent']!r}）設成「名稱 + 真實 email」", flush=True)
        return 2

    for n, (y, q) in enumerate(todo, 1):
        urls = [links[(y, q)]] if (y, q) in links else [u.format(y=y, q=q) for u in URL_VARIANTS]
        blob = download(urls, ua, f"{y}q{q}")
        if blob is None:
            print(f"  {y}q{q}：尚未上線或下載失敗", flush=True)
            if (y, q) != end:
                failed.append(f"{y}q{q}")
            continue
        qkey = f"{y}q{q}"
        rows = extract_purchases(blob, SAMPLE_DIR)  # 每季覆寫，留下最後成功那季的表頭樣本
        for r in rows:
            r["quarter"] = qkey
        # 同一年其他季度保留舊資料，只換掉這一季（資料集的季度 = SEC 收件季度，不一定等於申報日年份）
        if y not in by_year:
            by_year[y] = read_year(y)
        by_year[y] = [r for r in by_year[y] if r.get("quarter") != qkey] + rows
        state["done"][qkey] = {"rows": len(rows), "fetched": date.today().isoformat()}
        save(y)  # 每季存檔：中途被中斷，已完成的季度不會白抓
        print(f"  [{n}/{len(todo)}] {qkey}：買入 {len(rows)} 筆（{len(blob) / 1e6:.1f} MB）", flush=True)
        time.sleep(0.5)  # SEC 限每秒 10 次，這裡遠低於

    if failed:
        print(f"下載失敗的季度：{failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
