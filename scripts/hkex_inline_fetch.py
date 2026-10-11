"""港交所「證券市場每日行情報告」裡的界內證（inline warrants）：逐日下載、抽出 @L 的行，給 research/warrants_cbbc 做歷史驗證。

界內證簡稱格式：<發行商>-<相關資產>@L<到期年月><序號>（港交所命名規則），股份代號保留 47000–48999。
每日行情報告（英文）：https://www.hkex.com.hk/eng/stat/smstat/dayquot/d<yymmdd>e.htm（<pre> 純文字）。
雲端工作階段連不到 hkex.com.hk，所以由 GitHub Actions（.github/workflows/hkex_inline.yml）跑，結果 commit 回分支。

  python3 scripts/hkex_inline_fetch.py probe 2026-10-09      # 存當日報告樣本 ＋ 幾個候選的界內證清單頁，印 @L 行數
  python3 scripts/hkex_inline_fetch.py quotes 2025-10-01 2026-10-10   # 逐日下載，抽 @L 行 → data/hkex_inline/quotes_raw_<年>.csv.gz
  python3 scripts/hkex_inline_fetch.py terms                 # 試抓界內證條款清單（候選網址，存樣本給人看）
  python3 scripts/hkex_inline_fetch.py urls <網址1,網址2,...>   # 任意網址（hkex.com.hk）存到 sample/，CSV 印前幾行、HTML 印連結

quotes 只存原始行（date, code, name, raw_line），欄位解析交給 research/warrants_cbbc/inline_history.py 在本機做，
這樣格式猜錯也不用重抓。
"""
import argparse
import csv
import gzip
import io
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DAYQUOT = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{yymmdd}e.htm"
OUT = Path(__file__).resolve().parents[1] / "data" / "hkex_inline"
UA = {"User-Agent": "Mozilla/5.0 (research; github actions)"}
INLINE_RE = re.compile(r"^\s*(\d{5})\s+(\S*@L\S*)\s+(.*)$")
TERMS_CANDIDATES = [
    "https://www.hkex.com.hk/Products/Securities/Inline-Warrants?sc_lang=en",
    "https://www.hkex.com.hk/eng/dwrc/search/listsearch.asp",
    "https://www.hkex.com.hk/eng/iwrc/search/listsearch.asp",
    "https://www.hkex.com.hk/Products/Securities/Structured-Products/Trading-Information-and-Historical-Data?sc_lang=en",
    "https://www.hkex.com.hk/Products/Securities/Inline-Warrants/Trading-Information?sc_lang=en",
    "https://www.hkex.com.hk/eng/dwrc/dwsummary.asp?id=47000",
]


def yymmdd(d):
    return d.strftime("%y%m%d")


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception as exc:
        return -1, str(exc).encode()


def to_text(raw):
    txt = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    txt = re.sub(r"<[^>]+>", "", txt)
    return txt.replace("&nbsp;", " ").replace("&amp;", "&")


def inline_lines(txt):
    """回傳 (code, name, raw_line)。報告裡一隻證券可能跨兩行（名稱太長時），這裡只取以 5 位代號開頭且名稱含 @L 的行。"""
    out = []
    for line in txt.splitlines():
        m = INLINE_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2), line.rstrip()))
    return out


def probe(day):
    d = date.fromisoformat(day)
    (OUT / "sample").mkdir(parents=True, exist_ok=True)
    url = DAYQUOT.format(yymmdd=yymmdd(d))
    st, raw = get(url)
    print(f"dayquot: HTTP {st} {len(raw)} bytes  {url}")
    if st == 200 and len(raw) > 1000:
        txt = to_text(raw)
        (OUT / "sample" / f"d{yymmdd(d)}e.txt").write_text(txt, encoding="utf-8")
        lines = txt.splitlines()
        print(f"   共 {len(lines)} 行")
        heads = [i for i, l in enumerate(lines) if "QUOTATIONS" in l.upper() or "CLOSING" in l.upper()][:6]
        for i in heads:
            print("\n".join("   | " + l[:160] for l in lines[max(0, i - 2):i + 6]))
            print("   ...")
        inl = inline_lines(txt)
        print(f"   含 @L 的行：{len(inl)}")
        for code, name, line in inl[:40]:
            print("   | " + line[:160])
        hsi = [x for x in inl if "HSI" in x[1].upper()]
        print(f"   其中名稱含 HSI：{len(hsi)}")
    time.sleep(0.5)
    terms()


def terms():
    (OUT / "sample").mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(TERMS_CANDIDATES):
        st, raw = get(url)
        print(f"terms[{i}]: HTTP {st} {len(raw)} bytes  {url}")
        if st == 200 and raw:
            name = re.sub(r"[^A-Za-z0-9]+", "_", url.split("hkex.com.hk/")[-1])[:80]
            (OUT / "sample" / f"terms_{i}_{name}.html").write_bytes(raw[:400_000])
            txt = raw.decode("utf-8", "replace")
            links = sorted(set(re.findall(r"""href=["']([^"']*(?:csv|xls|xlsx|FullList|full_list|download)[^"']*)["']""", txt, re.I)))[:30]
            for l in links:
                print("   link: " + l[:200])
        time.sleep(0.8)


def fetch_urls(urls):
    """任意網址存樣本（限 hkex.com.hk）。CSV 印前 8 行與行數；HTML 印含 csv/xls/htm/asp 的連結。"""
    (OUT / "sample").mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(u.strip() for u in urls.split(",") if u.strip()):
        if "hkex.com.hk" not in url:
            print(f"skip（只抓 hkex.com.hk）：{url}")
            continue
        st, raw = get(url)
        print(f"url[{i}]: HTTP {st} {len(raw)} bytes  {url}")
        if st != 200 or not raw:
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", url.split("hkex.com.hk/")[-1])[:90]
        ext = ".csv" if url.lower().endswith(".csv") else (".xls" if ".xls" in url.lower() else ".html")
        (OUT / "sample" / f"url_{name}{ext}").write_bytes(raw[:2_000_000])
        if ext == ".csv":
            txt = raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
            lines = txt.splitlines()
            print(f"   CSV {len(lines)} 行")
            for l in lines[:8]:
                print("   | " + l[:220])
        elif ext == ".html":
            txt = raw.decode("utf-8", "replace")
            links = sorted(set(re.findall(r"""href=["']([^"']*\.(?:csv|xls|xlsx|zip|htm|asp)[^"']*)["']""", txt, re.I)))
            for l in links[:60]:
                print("   link: " + l[:200])
            body = re.sub(r"<script.*?</script>", "", txt, flags=re.S)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body)
            print("   text: " + body[:600])
        time.sleep(0.8)


def quotes(start, end):
    OUT.mkdir(parents=True, exist_ok=True)
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    index_path = OUT / "quotes_index.csv"
    done = {}
    if index_path.exists():
        with open(index_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done[r["date"]] = r["status"]
    rows_by_year = {}
    d = d0
    while d <= d1:
        key = d.isoformat()
        if d.weekday() >= 5 or done.get(key) in ("ok", "none"):
            d += timedelta(days=1)
            continue
        st, raw = get(DAYQUOT.format(yymmdd=yymmdd(d)))
        if st == 200 and len(raw) > 1000:
            inl = inline_lines(to_text(raw))
            rows_by_year.setdefault(d.year, []).extend((key, c, n, l) for c, n, l in inl)
            done[key] = "ok"
            print(f"{key}: {len(inl)} 行 @L")
        elif st in (404, 403) or (st == 200 and len(raw) <= 1000):
            done[key] = "none"
            print(f"{key}: 沒有報告（HTTP {st}，假期？）")
        else:
            done[key] = f"error:{st}"
            print(f"{key}: 失敗 HTTP {st}")
        time.sleep(0.7)
        d += timedelta(days=1)
    for year, rows in rows_by_year.items():
        path = OUT / f"quotes_raw_{year}.csv.gz"
        existing = []
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                existing = list(csv.reader(f))[1:]
        seen = {(r[0], r[1]) for r in existing}
        merged = existing + [list(r) for r in rows if (r[0], r[1]) not in seen]
        merged.sort(key=lambda r: (r[0], r[1]))
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "code", "name", "raw_line"])
            w.writerows(merged)
        print(f"寫入 {path.name}：{len(merged)} 行")
    with open(index_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "status"])
        for k in sorted(done):
            w.writerow([k, done[k]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe"); p.add_argument("day")
    q = sub.add_parser("quotes"); q.add_argument("start"); q.add_argument("end")
    sub.add_parser("terms")
    u = sub.add_parser("urls"); u.add_argument("urls")
    a = ap.parse_args()
    if a.cmd == "probe":
        probe(a.day)
    elif a.cmd == "quotes":
        quotes(a.start, a.end)
    elif a.cmd == "urls":
        fetch_urls(a.urls)
    else:
        terms()


if __name__ == "__main__":
    main()
