#!/usr/bin/env python3
"""回購公告抓取（第一批：美、港、台），供 research/buyback/STRATEGY.md 回測用。

  python3 scripts/buyback_fetch.py --market us [--start 2006-01] [--budget-min 300]
  python3 scripts/buyback_fetch.py --market hk
  python3 scripts/buyback_fetch.py --market tw

美國（SEC）
  1. EDGAR 全文搜尋（efts.sec.gov）逐月找 8-K 內文或附件含回購授權用語的文件
  2. 下載文件全文，逐句判讀「新增或加碼授權」並抓出金額或股數（判讀結果附原句，供人工稽核）
  3. 判為新授權的申報，再抓 index-headers 取得 ACCEPTANCE-DATETIME（美東時間）
  逐月存 data/buyback/us/months/{YYYY-MM}.csv.gz，已完成的月份不重抓（最近兩個月每次重抓）；
  有時間預算，沒抓完下次接著抓。SEC 要求 User-Agent 帶聯絡方式：從環境變數 SEC_USER_AGENT 讀。

香港（披露易）
  港股每年股東大會都會給回購一般授權，「授權」本身沒有訊號意義，所以抓「實際買回」的申報：
  2009 年起為「翌日披露報表 → Share Buyback」，之前為「Share Buyback Reports」。只用標題資料，不下載 PDF。
  輸出 data/buyback/hk/reports.csv.gz（每筆申報一列：股票代號、發佈時間、檔案連結）。

台灣（公開資訊觀測站）
  「買回自己公司股份彙總統計表」（t35sc09），上市（sii）與上櫃（otc）各一次請求即為完整歷史：
  董事會決議日、目的、預定買回股數、價格區間、預定期間、執行結果。
  輸出 data/buyback/tw/resolutions.csv.gz。執行結果欄位要到期間結束後才知道，回測不可當訊號用。
"""
import argparse
import csv
import gzip
import html
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "buyback")
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}


# -----------------------------------------------------------------------------
# 共用
# -----------------------------------------------------------------------------
class Blocked(Exception):
    """來源拒絕存取（403 等），立即停止，不要一直重試。"""


def get(session, url, method="GET", data=None, retries=4, pause=0.0):
    for i in range(retries):
        try:
            r = session.request(method, url, data=data, timeout=60)
            if r.status_code == 403:
                raise Blocked(f"403 {url}")
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"{r.status_code}")
            r.raise_for_status()
            if pause:
                time.sleep(pause)
            return r
        except requests.RequestException as e:
            if i == retries - 1:
                print(f"  失敗 {url}：{e}")
                return None
            time.sleep(2 ** (i + 1))


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    if path.endswith(".gz"):
        with gzip.GzipFile(path, "wb", mtime=0) as f:  # mtime=0：內容沒變就不產生 git 差異
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)


def read_csv(path):
    if not os.path.exists(path):
        return []
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_state(market):
    p = os.path.join(OUT, market, "state.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(market, state):
    p = os.path.join(OUT, market, "state.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def html_to_text(s):
    """HTML 的換行只是排版，區塊標籤才是段落；純文字（舊式 .txt 申報）每行固定寬度換行，空行才是段落。
    回傳以空行分段的文字，段落內沒有換行。"""
    is_html = bool(re.search(r"(?i)<(html|p|div|td|br)\b", s[:20000]))
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    if is_html:
        s = re.sub(r"[\r\n]+", " ", s)
        s = re.sub(r"(?i)<br\s*/?>|</?(p|div|tr|li|h\d|table)\b[^>]*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ").replace("\r", "")
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", s)]
    return "\n\n".join(p for p in paras if p)


# -----------------------------------------------------------------------------
# 美國：判讀
# -----------------------------------------------------------------------------
BUY = r"(?:re-?purchas\w*|buy-?\s?backs?|buy\s+back)"
AUTH = r"(?:authori[sz]\w*|approv\w*)"
_ANY = r"(?:[^.]|\.(?=\d))"  # 句中任意字元（小數點不算句尾）
NEW_RE = re.compile(r"\b(?:new|additional|incremental|increas\w*|expan\w*|augment\w*|replac\w*|another|"
                    r"upsiz\w*|supplement\w*|extension|extend\w*|raise[sd]?|boost\w*)\b", re.I)
# 董事會（剛剛）授權：「board/directors ... authorized/approved ... repurchase」
GRANT_RE = re.compile(rf"\b(?:board|directors|company|we)\b{_ANY}{{0,80}}?\b(?:has\s+|have\s+|recently\s+|today\s+)?"
                      rf"(?:authori[sz]ed|approved)\b{_ANY}{{0,200}}?{BUY}", re.I)
# 公告標題型：「XYZ Announces $500 Million Share Repurchase Authorization」「New $40 mil ... authorization」
HEAD_RE = re.compile(rf"\b(?:announc\w*|declar\w*|new)\b{_ANY}{{0,80}}?(?:\$|million|billion){_ANY}{{0,60}}?"
                     rf"{BUY}{_ANY}{{0,30}}?(?:program|plan|authori[sz]ation)", re.I)
# 描述既有計畫的進度、剩餘額度，或過去某個時點的授權
OLD_RE = re.compile(
    r"\b(?:previously|prior|existing|remaining|remained|remains|available\s+under|under\s+(?:the|its|our|this|that)\s+"
    r"(?:current|existing|\$)|had\s+repurchased|has\s+repurchased|have\s+repurchased|was\s+approximately|"
    r"as\s+of\s+(?:the\s+end|\w+\s+\d)|since\s+(?:the\s+)?inception|to\s+date|during\s+the\s+(?:first|second|third|"
    r"fourth)\s+quarter|in\s+(?:january|february|march|april|may|june|july|august|september|october|november|"
    r"december)\b|repurchased\s+(?:approximately\s+|a\s+total\s+of\s+)?[\d,.]+\s*(?:million\s+)?shares)", re.I)
TODAY_RE = re.compile(r"\b(?:today|announced|announces|has\s+authori[sz]ed|has\s+approved|have\s+authori[sz]ed|"
                      r"have\s+approved)\b", re.I)
MONEY_RE = re.compile(r"(?:US)?\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|bn|mm|mil|m|b)?\b", re.I)
SHARES_RE = re.compile(r"(?<![$\d.,])(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?\s+(?:of\s+(?:its|the\s+company'?s|our)\s+)?"
                       r"(?:outstanding\s+)?(?:shares|common\s+shares|common\s+stock|shares\s+of\s+(?:its\s+|the\s+"
                       r"company'?s\s+|our\s+)?common\s+stock)\b", re.I)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(?:its|the\s+company'?s|our)?\s*(?:then\s+)?"
                    r"(?:outstanding|issued)", re.I)


def _num(v, unit):
    x = float(v.replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("billion", "bn", "b"):
        x *= 1e9
    elif unit in ("million", "mm", "mil", "m"):
        x *= 1e6
    return x


def sentences(text):
    for para in text.split("\n\n"):
        for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(\"“])", para):
            s = s.strip()
            if 20 <= len(s) <= 1500:
                yield s


def classify_sentence(s, file_year=None):
    if file_year and not TODAY_RE.search(s):
        years = [int(y) for y in re.findall(r"\b((?:19|20)\d\d)\b", s)]
        if years and max(years) < file_year:
            return "old", 1  # 描述往年的授權
    grant = bool(GRANT_RE.search(s))
    head = bool(HEAD_RE.search(s))
    new = bool(NEW_RE.search(s))
    old = bool(OLD_RE.search(s))
    today = bool(TODAY_RE.search(s))
    if (grant or head) and (not old or (new and today)):
        return "new", 3 + today
    if new and not old and re.search(AUTH, s, re.I):
        return "new", 2
    return "old", 1 if (grant or new) else 0


def classify(text, file_year=None):
    """回傳 dict：kind = new（新增或加碼）/ old（只提既有計畫）/ none；附金額、股數、比例、原句，
    以及所有候選句（存下來以便之後改判讀規則時不必重新下載）。"""
    best, cands = None, []
    for s in sentences(text):
        if not re.search(BUY, s, re.I) or not re.search(AUTH, s, re.I):
            continue
        cands.append(s[:600])
        kind, score = classify_sentence(s, file_year)
        m, sh, pc = MONEY_RE.search(s), SHARES_RE.search(s), PCT_RE.search(s)
        cand = {"kind": kind, "score": score + (0.5 if (m or sh or pc) else 0),
                "amount_usd": _num(*m.groups()) if m else "",
                "shares": _num(*sh.groups()) if sh else "",
                "pct": float(pc.group(1)) if pc else "",
                "sentence": s[:600]}
        if best is None or cand["score"] > best["score"]:
            best = cand
    out = best or {"kind": "none", "score": -1, "amount_usd": "", "shares": "", "pct": "", "sentence": ""}
    out["candidates"] = " ⏎ ".join(cands[:6])
    return out


# -----------------------------------------------------------------------------
# 美國：抓取
# -----------------------------------------------------------------------------
EFTS = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
US_QUERIES = ['"repurchase program" authorized', '"repurchase plan" authorized',
              '"repurchase authorization"', '"buyback program" authorized']
US_FIELDS = ["adsh", "cik", "ticker", "company", "form", "items", "file_date", "acceptance_et", "session",
             "doc", "kind", "amount_usd", "shares", "pct", "sentence", "candidates", "queries"]
US_VERSION = 2  # 判讀或欄位改版時加一，舊版月份會重抓


def efts_month(s, ym):
    """回傳 {adsh: {src, docs:set, queries:set}}。"""
    y, m = map(int, ym.split("-"))
    d0 = date(y, m, 1)
    d1 = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    out = {}
    for q in US_QUERIES:
        frm = 0
        while True:
            params = {"q": q, "forms": "8-K", "dateRange": "custom", "startdt": d0.isoformat(),
                      "enddt": d1.isoformat(), "from": str(frm)}
            r = get(s, EFTS + "?" + "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items()),
                    pause=0.12)
            if r is None:
                break
            js = r.json()
            hits = js.get("hits", {}).get("hits", [])
            for h in hits:
                src = h.get("_source", {})
                if "8-K" not in (src.get("root_forms") or [src.get("form")]):
                    continue
                adsh, _, fname = h["_id"].partition(":")
                e = out.setdefault(adsh, {"src": src, "docs": set(), "queries": set()})
                e["docs"].add(fname)
                e["queries"].add(q)
            total = js.get("hits", {}).get("total", {}).get("value", 0)
            frm += len(hits)
            if not hits or frm >= total or frm >= 9900:
                if total > 9900:
                    print(f"  警告 {ym} {q}：{total} 筆超過搜尋上限")
                break
    return out


def ticker_of(src):
    for name in src.get("display_names") or []:
        m = re.search(r"\(([A-Z0-9.\-]+)(?:,\s*[A-Z0-9.\-]+)*\)\s*\(CIK", name)
        if m:
            return m.group(1)
    return ""


class Acceptance:
    """adsh → acceptanceDateTime（UTC），用 data.sec.gov/submissions 逐 CIK 查，含舊分頁；同一次執行內快取。"""

    def __init__(self, session):
        self.s, self.cache, self.pages_done = session, {}, set()

    def _absorb(self, block):
        for a, t in zip(block.get("accessionNumber", []), block.get("acceptanceDateTime", [])):
            self.cache[a] = t

    def get(self, cik, adsh, file_date):
        if adsh in self.cache:
            return self.cache[adsh]
        c10 = f"{int(cik):010d}"
        if c10 not in self.pages_done:
            self.pages_done.add(c10)
            r = get(self.s, SUBMISSIONS.format(name=f"CIK{c10}.json"), pause=0.12)
            if r is not None:
                js = r.json()
                self._absorb((js.get("filings") or {}).get("recent") or {})
                for f in (js.get("filings") or {}).get("files") or []:
                    self.pages_done.add(f["name"] + "?")  # 舊分頁先記下名稱，需要時才抓
                    self.cache.setdefault(("page", c10), []).append(f)
        if adsh in self.cache:
            return self.cache[adsh]
        for f in self.cache.get(("page", c10), []):
            if f.get("filingFrom", "") <= file_date <= f.get("filingTo", "9999") and f["name"] not in self.pages_done:
                self.pages_done.add(f["name"])
                r = get(self.s, SUBMISSIONS.format(name=f["name"]), pause=0.12)
                if r is not None:
                    self._absorb(r.json())
                if adsh in self.cache:
                    break
        return self.cache.get(adsh, "")


def fetch_us(args):
    from news_8k_fetch import to_eastern  # 同一套 UTC → 美東與時段判斷
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        print("需要環境變數 SEC_USER_AGENT（含聯絡 email）")
        return 1
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    acc = Acceptance(s)
    state = load_state("us")
    if state.get("version") != US_VERSION:
        print(f"判讀版本 {state.get('version')} → {US_VERSION}：全部月份重抓")
        state = {"version": US_VERSION}
    done = set(state.get("done_months", []))
    today = date.today()
    months, y, m = [], *map(int, args.start.split("-"))
    while (y, m) <= (today.year, today.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    recent = set(months[-2:])
    todo = [ym for ym in months if ym not in done or ym in recent]
    deadline = time.time() + args.budget_min * 60
    print(f"美國：{len(months)} 個月，待抓 {len(todo)}")
    for ym in todo:
        if time.time() > deadline:
            print("時間預算用完，下次接著抓")
            break
        found = efts_month(s, ym)
        rows = []
        for adsh, e in sorted(found.items()):
            src = e["src"]
            cik = (src.get("ciks") or [""])[0]
            best, best_doc, cands = {"kind": "none", "score": -1}, "", []
            for fname in sorted(e["docs"]):
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{fname}"
                r = get(s, url, pause=0.12)
                if r is None:
                    continue
                c = classify(html_to_text(r.text), int(src.get("file_date", "0000")[:4]) or None)
                if c["candidates"]:
                    cands.append(c["candidates"])
                if c["score"] > best["score"]:
                    best, best_doc = c, fname
            row = {"adsh": adsh, "cik": cik, "ticker": ticker_of(src),
                   "company": re.sub(r"\s*\(.*$", "", (src.get("display_names") or [""])[0]),
                   "form": src.get("form", ""), "items": ",".join(src.get("items") or []),
                   "file_date": src.get("file_date", ""), "doc": best_doc,
                   "queries": "|".join(sorted(e["queries"])), "candidates": " ⏎ ".join(cands)[:3000]}
            row.update({k: best.get(k, "") for k in ("kind", "amount_usd", "shares", "pct", "sentence")})
            if row["kind"] == "new":
                row["acceptance_et"], row["session"] = to_eastern(acc.get(cik, adsh, row["file_date"]))
            rows.append(row)
        write_csv(os.path.join(OUT, "us", "months", f"{ym}.csv.gz"), US_FIELDS, rows)
        n_new = sum(1 for r in rows if r["kind"] == "new")
        n_acc = sum(1 for r in rows if r["kind"] == "new" and r.get("acceptance_et"))
        print(f"  {ym}：申報 {len(rows)}，判為新授權 {n_new}（有申報時間 {n_acc}）")
        done.add(ym)
        state["done_months"] = sorted(done)
        state.setdefault("months", {})[ym] = {"filings": len(rows), "new": n_new, "with_time": n_acc,
                                              "fetched": today.isoformat()}
        save_state("us", state)
    # 合併成事件檔（只留新授權）
    ev = []
    for ym in sorted(done):
        ev += [r for r in read_csv(os.path.join(OUT, "us", "months", f"{ym}.csv.gz")) if r["kind"] == "new"]
    write_csv(os.path.join(OUT, "us", "events.csv.gz"), US_FIELDS, ev)
    state["summary"] = {"months_done": len(done), "months_total": len(months), "new_events": len(ev)}
    save_state("us", state)
    print(f"美國：完成 {len(done)}/{len(months)} 個月，新授權事件 {len(ev)}")
    return 0


# -----------------------------------------------------------------------------
# 香港
# -----------------------------------------------------------------------------
HK_URL = ("https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime"
          "&category=0&market=SEHK&stockId=-1&documentType=-1&fromDate={f}&toDate={t}&title="
          "&searchType=1&t1code={t1}&t2Gcode=-2&t2code={t2}&rowRange={n}&lang=E")
HK_FIELDS = ["news_id", "stock_code", "stock_name", "date_time", "title", "category", "file_link"]
HK_NEW_CATEGORY_FROM = date(2009, 1, 1)  # 之前是「Share Buyback Reports」（t1 51000）


def hk_range(s, d0, d1, t1, t2, rows_per=3000):
    """一次請求整段日期；網站的「載入更多」就是加大 rowRange，所以先用大的 rowRange，
    仍有下一頁才把日期對半拆。回傳 (列表, 是否仍被截斷)。"""
    url = HK_URL.format(f=d0.strftime("%Y%m%d"), t=d1.strftime("%Y%m%d"), t1=t1, t2=t2, n=rows_per)
    r = get(s, url, pause=0.3)
    if r is None:
        return [], True
    js = r.json()
    rows = json.loads(js.get("result") or "[]")
    if not js.get("hasNextRow"):
        return rows, False
    if d0 < d1:
        mid = d0 + (d1 - d0) // 2
        a, ta = hk_range(s, d0, mid, t1, t2, rows_per)
        b, tb = hk_range(s, mid + timedelta(days=1), d1, t1, t2, rows_per)
        return a + b, ta or tb
    return rows, True


def _hk_row(x):
    return {"news_id": x["NEWS_ID"],
            "stock_code": re.sub(r"<br\s*/?>", "|", x.get("STOCK_CODE", "")).strip("|"),
            "stock_name": html.unescape(re.sub(r"<br\s*/?>", "|", x.get("STOCK_NAME", ""))).strip("|"),
            "date_time": x.get("DATE_TIME", ""),
            "title": html.unescape(x.get("TITLE", "")),
            "category": html.unescape(re.sub(r"<br\s*/?>", "", x.get("LONG_TEXT", ""))),
            "file_link": x.get("FILE_LINK", "")}


def _hk_key(r):
    d, _, t = r["date_time"].partition(" ")
    dd, mm, yy = d.split("/")
    return f"{yy}-{mm}-{dd} {t}", r["news_id"]


def fetch_hk(args):
    s = requests.Session()
    s.headers.update(BROWSER)
    state = load_state("hk")
    path = os.path.join(OUT, "hk", "reports.csv.gz")
    have = {r["news_id"]: r for r in read_csv(path)}
    done = set(state.get("done_months", []))
    truncated = set(state.get("truncated_months", []))
    today = date.today()
    deadline = time.time() + args.budget_min * 60

    def save():
        out = sorted(have.values(), key=_hk_key)
        write_csv(path, HK_FIELDS, out)
        state["done_months"] = sorted(done)
        state["truncated_months"] = sorted(truncated)
        state["summary"] = {"reports": len(out), "stocks": len({r["stock_code"] for r in out}),
                            "first": _hk_key(out[0])[0] if out else "", "last": _hk_key(out[-1])[0] if out else ""}
        save_state("hk", state)

    y, m = map(int, args.start_hk.split("-"))
    while (y, m) <= (today.year, today.month):
        if time.time() > deadline:
            print("時間預算用完，下次接著抓")
            break
        ym = f"{y:04d}-{m:02d}"
        d0 = date(y, m, 1)
        d1 = min(date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1), today)
        if ym not in done or (today - d1).days < 45:
            t1, t2 = ("50000", "50100") if d0 >= HK_NEW_CATEGORY_FROM else ("51000", "-2")
            rows, trunc = hk_range(s, d0, d1, t1, t2)
            for x in rows:
                have[x["NEWS_ID"]] = _hk_row(x)
            (truncated.add if trunc else truncated.discard)(ym)
            print(f"  {ym}：{len(rows)} 筆{'（有截斷）' if trunc else ''}")
            done.add(ym)
            save()
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    save()
    print(f"香港：回購申報 {state['summary']['reports']} 筆，{state['summary']['stocks']} 檔；"
          f"完成 {len(done)} 個月")
    return 0


# -----------------------------------------------------------------------------
# 台灣
# -----------------------------------------------------------------------------
TW_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09"
TW_COLS = ["co_id", "name", "resolution_date", "purpose", "legal_cap_twd", "planned_shares", "price_low",
           "price_high", "period_start", "period_end", "completed", "threshold_info", "bought_shares",
           "cancelled_shares", "bought_pct_of_planned", "bought_amount_twd", "avg_price",
           "bought_pct_of_issued", "incomplete_reason"]
TW_FIELDS = ["market"] + TW_COLS


def roc_date(s):
    m = re.match(r"\s*(\d{2,3})/(\d{1,2})/(\d{1,2})", s or "")
    if not m:
        return ""
    return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()


def parse_tw(text, market):
    rows = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", text):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
        if len(cells) < 20 or not cells[0].isdigit():
            continue  # 表頭、累計列
        r = dict(zip(TW_COLS, cells[1:20]))
        for k in ("resolution_date", "period_start", "period_end"):
            r[k] = roc_date(r[k])
        for k in ("legal_cap_twd", "planned_shares", "bought_shares", "cancelled_shares", "bought_amount_twd"):
            r[k] = r[k].replace(",", "")
        r["market"] = market
        rows.append(r)
    return rows


def fetch_tw(args):
    s = requests.Session()
    s.headers.update(BROWSER)
    out = []
    for market in ("sii", "otc"):
        data = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": market,
                "year": "", "month": "", "b_date": "", "e_date": "", "co_id": ""}
        r = get(s, TW_URL, method="POST", data=data)
        if r is None:
            print(f"台灣 {market}：抓取失敗")
            return 1
        r.encoding = "utf-8"
        rows = parse_tw(r.text, market)
        print(f"台灣 {market}：{len(rows)} 筆決議（回應 {len(r.content):,} 位元組）")
        if not rows:
            os.makedirs(os.path.join(OUT, "tw"), exist_ok=True)
            with open(os.path.join(OUT, "tw", f"debug_{market}.html"), "w", encoding="utf-8") as f:
                f.write(r.text[:500_000])
        out += rows
        time.sleep(3)
    out.sort(key=lambda r: (r["resolution_date"], r["co_id"]))
    write_csv(os.path.join(OUT, "tw", "resolutions.csv.gz"), TW_FIELDS, out)
    years = {}
    for r in out:
        years[r["resolution_date"][:4]] = years.get(r["resolution_date"][:4], 0) + 1
    save_state("tw", {"summary": {"resolutions": len(out), "companies": len({r["co_id"] for r in out}),
                                  "by_year": years, "fetched": date.today().isoformat()}})
    return 0 if out else 1


def main():
    ap = argparse.ArgumentParser(description="回購公告抓取（美、港、台）")
    ap.add_argument("--market", required=True, choices=["us", "hk", "tw"])
    ap.add_argument("--start", default="2006-01", help="美國起始月")
    ap.add_argument("--start-hk", default="2000-01", help="香港起始月")
    ap.add_argument("--budget-min", type=float, default=300, help="抓取時間預算（分鐘，美、港）")
    args = ap.parse_args()
    try:
        return {"us": fetch_us, "hk": fetch_hk, "tw": fetch_tw}[args.market](args)
    except Blocked as e:
        print(f"被來源拒絕：{e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
