"""港交所「證券市場每日行情報告」裡的界內證（inline warrants）：逐日下載、抽出 @L 的行，給 research/warrants_cbbc 做歷史驗證。

界內證簡稱格式：<發行商>-<相關資產>@L<到期年月><序號>（港交所命名規則），股份代號保留 47000–48999。
每日行情報告（英文）：https://www.hkex.com.hk/eng/stat/smstat/dayquot/d<yymmdd>e.htm（<pre> 純文字）。
雲端工作階段連不到 hkex.com.hk，所以由 GitHub Actions（.github/workflows/hkex_inline.yml）跑，結果 commit 回分支。

  python3 scripts/hkex_inline_fetch.py probe 2026-10-09      # 存當日報告樣本 ＋ 幾個候選的界內證清單頁，印 @L 行數
  python3 scripts/hkex_inline_fetch.py quotes 2025-10-01 2026-10-10   # 逐日下載，抽 @L 行 → data/hkex_inline/quotes_raw_<年>.csv.gz
  python3 scripts/hkex_inline_fetch.py terms                 # 試抓界內證條款清單（候選網址，存樣本給人看）
  python3 scripts/hkex_inline_fetch.py urls <網址1,網址2,...>   # 任意網址（hkex.com.hk）存到 sample/，CSV 印前幾行、HTML 印連結
  python3 scripts/hkex_inline_fetch.py survey 2019-07-01 2026-10-10 --step 14   # 每隔 N 天抽一天的行情報告，數 @L 行 → survey.csv（找界內證存在的年代）
  python3 scripts/hkex_inline_fetch.py wayback                # 從 web.archive.org 抓歷年 iwFullList.csv 快照（含上下限價、到期、收市價）→ iw_fulllist_history.csv.gz
  python3 scripts/hkex_inline_fetch.py wayback-dayquot [--from 2019 --to 2026]   # archive.org 存過的每日行情檔，逐個下載抽 @L 行 → quotes_raw_<年>.csv.gz
      （結果：archive.org 把大頁面截在 1 MB，24 MB 的行情檔只剩開頭，界內證那段（47xxx）看不到；這條路不通）
  python3 scripts/hkex_inline_fetch.py yahoo [--codes 47553,47891]   # Yahoo Finance 圖表 API 拉 <code>.HK 的歷史日線（退市窩輪常仍保留）→ yahoo_daily.csv.gz
      不給 --codes 就用 data/hkex_inline/terms.csv 裡全部代號

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
            body = resp.read()
            if body[:2] == b"\x1f\x8b":                                  # archive.org 的 id_ 原始內容有時是 gzip
                import gzip as _gz
                try:
                    body = _gz.decompress(body)
                except OSError:
                    pass
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception as exc:
        return -1, str(exc).encode()


def to_text(raw):
    txt = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    txt = re.sub(r"<[^>]+>", "", txt)
    return txt.replace("&nbsp;", " ").replace("&amp;", "&")


def inline_lines(txt):
    """回傳 (code, name, raw_line)。報告裡每隻證券佔兩行：
    第一行 CODE NAME CUR PRV.CLO ASK HIGH SHARES，第二行 CLOSING BID LOW TURNOVER（2026-10-09 樣本），
    所以 raw_line 把兩行用 ' || ' 接起來，欄位解析留給本機。"""
    out = []
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        m = INLINE_RE.match(line)
        if m:
            nxt = lines[i + 1].rstrip() if i + 1 < len(lines) and not INLINE_RE.match(lines[i + 1]) else ""
            out.append((m.group(1), m.group(2), line.rstrip() + " || " + nxt.strip()))
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
        if "hkex.com.hk" not in url and "web.archive.org" not in url:
            print(f"skip（只抓 hkex.com.hk／web.archive.org）：{url}")
            continue
        st, raw = get(url)
        print(f"url[{i}]: HTTP {st} {len(raw)} bytes  {url}")
        if st != 200 or not raw:
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1])[:90]
        ext = ".csv" if url.lower().endswith(".csv") else (".xls" if ".xls" in url.lower() else (".txt" if "cdx/search" in url else ".html"))
        (OUT / "sample" / f"url_{name}{ext}").write_bytes(raw[:2_000_000])
        if ext == ".txt":
            txt = raw.decode("utf-8", "replace")
            lines = txt.splitlines()
            print(f"   {len(lines)} 行")
            for l in lines[:80]:
                print("   | " + l[:220])
        elif ext == ".csv":
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


def survey(start, end, step):
    """抽樣：每 step 天取一個交易日（遇週末往後挪），記錄 @L 總行數與 HSI 行數，並把 @L 行存起來。"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "survey.csv"
    seen = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen[r["date"]] = r
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    d = d0
    lines_out = []
    while d <= d1:
        probe_day = d
        while probe_day.weekday() >= 5:
            probe_day += timedelta(days=1)
        key = probe_day.isoformat()
        if key not in seen:
            st, raw = get(DAYQUOT.format(yymmdd=yymmdd(probe_day)))
            if st == 200 and len(raw) > 1000:
                inl = inline_lines(to_text(raw))
                hsi = [x for x in inl if "HSI" in x[1].upper()]
                seen[key] = {"date": key, "status": "ok", "n_inline": len(inl), "n_hsi": len(hsi), "bytes": len(raw)}
                lines_out.extend((key, c, n, l) for c, n, l in inl)
                print(f"{key}: @L {len(inl)} 行，HSI {len(hsi)}")
            else:
                seen[key] = {"date": key, "status": f"http{st}", "n_inline": "", "n_hsi": "", "bytes": len(raw)}
                print(f"{key}: HTTP {st}")
            time.sleep(0.7)
        d += timedelta(days=step)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "status", "n_inline", "n_hsi", "bytes"])
        w.writeheader()
        for k in sorted(seen):
            w.writerow(seen[k])
    if lines_out:
        lp = OUT / "survey_lines.csv.gz"
        existing = []
        if lp.exists():
            with gzip.open(lp, "rt", encoding="utf-8", newline="") as f:
                existing = list(csv.reader(f))[1:]
        have = {(r[0], r[1]) for r in existing}
        merged = existing + [list(r) for r in lines_out if (r[0], r[1]) not in have]
        merged.sort(key=lambda r: (r[0], r[1]))
        with gzip.open(lp, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "code", "name", "raw_line"])
            w.writerows(merged)
        print(f"寫入 {lp.name}：{len(merged)} 行")


WAYBACK_TARGETS = ("www.hkex.com.hk/eng/iwrc/search/iwFullList.csv", "www.hkex.com.hk/chi/iwrc/search/iwFullList.csv")


def wayback():
    """web.archive.org 的 CDX 索引列出 iwFullList.csv 的所有快照，逐個下載、解析成列（加 capture 日期）。"""
    import json
    OUT.mkdir(parents=True, exist_ok=True)
    rows, caps_seen = [], set()
    for target in WAYBACK_TARGETS:
        cdx = f"https://web.archive.org/cdx/search/cdx?url={target}&output=json&fl=timestamp,statuscode,length&filter=statuscode:200&collapse=timestamp:8"
        st, raw = get(cdx, timeout=120)
        print(f"CDX {target}: HTTP {st} {len(raw)} bytes")
        if st != 200 or not raw:
            continue
        try:
            caps = json.loads(raw.decode("utf-8", "replace"))[1:]
        except ValueError:
            print("   CDX 不是 JSON：" + raw[:200].decode("utf-8", "replace"))
            continue
        print(f"   {len(caps)} 個快照（每天最多一個）：{caps[0][0] if caps else ''} … {caps[-1][0] if caps else ''}")
        for ts, _st, _len in caps:
            if ts[:8] in caps_seen:
                continue
            url = f"https://web.archive.org/web/{ts}id_/https://{target}"
            st2, body = get(url, timeout=120)
            if st2 != 200 or not body:
                print(f"   {ts}: HTTP {st2}")
                time.sleep(1.0)
                continue
            txt = body.decode("utf-16", "replace") if body[:2] in (b"\xff\xfe", b"\xfe\xff") else body.decode("utf-8", "replace")
            lines = [l for l in txt.splitlines() if l.strip()]
            header_i = next((i for i, l in enumerate(lines) if "Code" in l and "Lower" in l), None)
            n = 0
            if header_i is not None:
                header = [h.strip() for h in lines[header_i].split("\t")]
                for l in lines[header_i + 1:]:
                    cells = [c.strip() for c in l.split("\t")]
                    if len(cells) < 8 or not cells[0].isdigit():
                        continue
                    rows.append({"capture": ts[:8], **dict(zip(header, cells))})
                    n += 1
            caps_seen.add(ts[:8])
            print(f"   {ts}: {len(body)} bytes，{n} 隻")
            time.sleep(1.0)
    if rows:
        keys = ["capture"] + sorted({k for r in rows for k in r if k != "capture"})
        with gzip.open(OUT / "iw_fulllist_history.csv.gz", "wt", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"寫入 iw_fulllist_history.csv.gz：{len(rows)} 列，{len(caps_seen)} 個快照日")


def wayback_dayquot(year_from, year_to):
    """CDX 列出 archive.org 存過的 d<yymmdd>e.htm，逐個下載（id_ 原始內容）抽 @L 行，寫進 quotes_raw_<年>.csv.gz 與 survey.csv。"""
    import json
    OUT.mkdir(parents=True, exist_ok=True)
    caps = []
    for host in ("www.hkex.com.hk", "hkex.com.hk"):
        cdx = (f"https://web.archive.org/cdx/search/cdx?url={host}/eng/stat/smstat/dayquot/d&matchType=prefix&output=txt"
               f"&fl=original%2Ctimestamp%2Cstatuscode&filter=statuscode:200&from={year_from}&to={year_to}&limit=2000")
        st, raw = get(cdx, timeout=180)
        print(f"CDX {host}: HTTP {st} {len(raw)} bytes")
        if st != 200:
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.search(r"/d(\d{6})e\.htm$", parts[0]):
                caps.append((parts[0], parts[1]))
    # 每個交易日只留一個快照
    by_day = {}
    for orig, ts in caps:
        yymmdd_ = re.search(r"/d(\d{6})e\.htm$", orig).group(1)
        by_day.setdefault(yymmdd_, (orig, ts))
    print(f"archive.org 有 {len(by_day)} 個不同交易日的行情檔")
    index_path = OUT / "survey.csv"
    seen = {}
    if index_path.exists():
        with open(index_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen[r["date"]] = r
    rows_by_year = {}
    for yymmdd_, (orig, ts) in sorted(by_day.items()):
        day = date(2000 + int(yymmdd_[:2]), int(yymmdd_[2:4]), int(yymmdd_[4:6])).isoformat()
        if seen.get(day, {}).get("status") == "ok":
            continue
        url = f"https://web.archive.org/web/{ts}id_/{orig}"
        st, raw = get(url, timeout=180)
        if st != 200 or len(raw) < 1000:
            print(f"{day}: HTTP {st} {len(raw)} bytes")
            seen[day] = {"date": day, "status": f"wb_http{st}", "n_inline": "", "n_hsi": "", "bytes": len(raw)}
            time.sleep(1.0)
            continue
        inl = inline_lines(to_text(raw))
        hsi = [x for x in inl if "HSI" in x[1].upper()]
        seen[day] = {"date": day, "status": "ok", "n_inline": len(inl), "n_hsi": len(hsi), "bytes": len(raw)}
        rows_by_year.setdefault(day[:4], []).extend((day, c, n, l) for c, n, l in inl)
        print(f"{day}: @L {len(inl)} 行，HSI {len(hsi)}（{len(raw)} bytes，快照 {ts}）")
        time.sleep(1.0)
    with open(index_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "status", "n_inline", "n_hsi", "bytes"])
        w.writeheader()
        for k in sorted(seen):
            w.writerow(seen[k])
    for year, rows in rows_by_year.items():
        path = OUT / f"quotes_raw_{year}.csv.gz"
        existing = []
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                existing = list(csv.reader(f))[1:]
        have = {(r[0], r[1]) for r in existing}
        merged = existing + [list(r) for r in rows if (r[0], r[1]) not in have]
        merged.sort(key=lambda r: (r[0], r[1]))
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "code", "name", "raw_line"])
            w.writerows(merged)
        print(f"寫入 {path.name}：{len(merged)} 行")


def yahoo(codes_arg):
    """Yahoo Finance：https://query1.finance.yahoo.com/v8/finance/chart/<code>.HK?range=max&interval=1d → 日線（含退市後仍保留的歷史）。"""
    import json
    OUT.mkdir(parents=True, exist_ok=True)
    if codes_arg:
        codes = [c.strip().zfill(5) for c in codes_arg.split(",") if c.strip()]
    else:
        tp = OUT / "terms.csv"
        if not tp.exists():
            sys.exit("沒有 --codes 也沒有 terms.csv")
        with open(tp, newline="", encoding="utf-8") as f:
            codes = sorted({r["code"].zfill(5) for r in csv.DictReader(f)})
    path = OUT / "yahoo_daily.csv.gz"
    existing = []
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            existing = list(csv.reader(f))[1:]
    done = {r[1] for r in existing}
    rows = list(existing)
    ok = fail = 0
    for code in codes:
        if code in done:
            continue
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.HK?range=max&interval=1d&events=div%2Csplit"
        st, raw = get(url, timeout=60)
        n = 0
        if st == 200 and raw:
            try:
                res = json.loads(raw.decode("utf-8", "replace"))["chart"]["result"]
                if res:
                    r0 = res[0]
                    ts = r0.get("timestamp") or []
                    q = r0["indicators"]["quote"][0]
                    for i, t in enumerate(ts):
                        d = date.fromtimestamp(t + 8 * 3600).isoformat()
                        c = q["close"][i]
                        if c is None:
                            continue
                        rows.append([d, code, q["open"][i], q["high"][i], q["low"][i], c, q["volume"][i]])
                        n += 1
            except (KeyError, ValueError, TypeError) as exc:
                print(f"{code}: 解析失敗 {exc}")
        if n:
            ok += 1
            print(f"{code}: {n} 根日線 {rows[-n][0]} → {rows[-1][0]}")
        else:
            fail += 1
            print(f"{code}: HTTP {st}，0 根（{raw[:120].decode('utf-8', 'replace') if raw else ''}）")
        time.sleep(1.5)
    rows.sort(key=lambda r: (r[1], r[0]))
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    print(f"Yahoo：成功 {ok}、失敗 {fail}；寫入 {path.name} 共 {len(rows)} 列")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe"); p.add_argument("day")
    q = sub.add_parser("quotes"); q.add_argument("start"); q.add_argument("end")
    sub.add_parser("terms")
    u = sub.add_parser("urls"); u.add_argument("urls")
    sv = sub.add_parser("survey"); sv.add_argument("start"); sv.add_argument("end"); sv.add_argument("--step", type=int, default=14)
    sub.add_parser("wayback")
    wd = sub.add_parser("wayback-dayquot"); wd.add_argument("--from", dest="yfrom", default="2019"); wd.add_argument("--to", dest="yto", default="2026")
    ya = sub.add_parser("yahoo"); ya.add_argument("--codes", default="")
    a = ap.parse_args()
    if a.cmd == "probe":
        probe(a.day)
    elif a.cmd == "quotes":
        quotes(a.start, a.end)
    elif a.cmd == "urls":
        fetch_urls(a.urls)
    elif a.cmd == "survey":
        survey(a.start, a.end, a.step)
    elif a.cmd == "wayback":
        wayback()
    elif a.cmd == "wayback-dayquot":
        wayback_dayquot(a.yfrom, a.yto)
    elif a.cmd == "yahoo":
        yahoo(a.codes)
    else:
        terms()


if __name__ == "__main__":
    main()
