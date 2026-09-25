#!/usr/bin/env python3
# =============================================================================
# 財報事件抓取：SEC 8-K Item 2.02（Results of Operations and Financial Condition）
# -----------------------------------------------------------------------------
# 給 research/news_trade/STRATEGY.md（財報公告後漂移）用。
#
# 流程：
#   1. S&P 500 point-in-time 名單（gifted-carson 的 universes/sp500/membership.csv，只有代號）
#      → 用 data/insider/ticker_cik/{季}.csv.gz（當時的代號 ↔ CIK）找出每段成分股區間的 CIK；
#      找不到的現任成分股用 SEC company_tickers.json 補。
#   2. 對每個 CIK 抓 https://data.sec.gov/submissions/CIK##########.json（含較舊的分頁），
#      留下 form 為 8-K／8-K/A 且 items 含 2.02 的申報。acceptanceDateTime 精確到秒，
#      回測用它判斷是盤前還是盤後公布。
#
# 輸出（data/news/）：
#   sp500_cik_map.csv            每段成分股區間對到的 CIK、來源、候選數（人工核對用）
#   earnings_8k.csv.gz           這些 CIK 的全部 2.02 申報（2005 年起，不限成分股期間）
#   sp500_earnings_events.csv.gz 只留申報當時是 S&P 500 成分股的事件，附價格資料夾用的代號
#   state.json                   每個 CIK 是否已抓完舊分頁、acceptance 時間的小時分布（時區核對）
#
# SEC 要求 User-Agent 帶聯絡方式：環境變數 SEC_USER_AGENT（workflow 從 repo secret 讀）。
# 用法：
#   python3 scripts/news_8k_fetch.py                     # 增量：每個 CIK 只抓最新一頁
#   python3 scripts/news_8k_fetch.py --full              # 連舊分頁全部重抓
#   python3 scripts/news_8k_fetch.py --equities-root _equities --limit 20   # 試跑前 20 家
# =============================================================================
import argparse
import csv
import glob
import gzip
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "news")
TICKER_CIK_DIR = os.path.join(ROOT, "data", "insider", "ticker_cik")
DEFAULT_EQ_ROOT = os.path.join(ROOT, "_equities")
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
START = date(2005, 1, 1)
MIN_INTERVAL = 0.13  # SEC 上限每秒 10 次，留餘裕
EVENT_FIELDS = ["cik", "company", "form", "accession", "filing_date", "acceptance", "items", "report_date"]


# -----------------------------------------------------------------------------
# 基本工具
# -----------------------------------------------------------------------------
class Blocked(Exception):
    """SEC 回 403：User-Agent 被擋，重試沒用。"""


class Sec:
    def __init__(self, ua):
        self.h = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
        self.last = 0.0
        self.calls = 0

    def get_json(self, url):
        for i in range(4):
            wait = MIN_INTERVAL - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                r = requests.get(url, headers=self.h, timeout=60)
            except requests.RequestException as e:
                print(f"  {url} 第 {i + 1} 次失敗：{e}", flush=True)
                time.sleep(3 * (i + 1))
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                raise Blocked(url)
            if r.status_code == 429 or r.status_code >= 500:
                print(f"  {url} → {r.status_code}，稍後重試", flush=True)
                time.sleep(10 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"{url} 重試 4 次仍失敗")


def cik10(cik):
    return f"{int(cik):010d}"


def norm_ticker(t):
    return (t or "").strip().upper().replace(".", "-").replace("/", "-")


def read_csv(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields, gz=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if gz:
        with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as g, \
                io.TextIOWrapper(g, encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def quarter_range(qkey):
    y, q = int(qkey[:4]), int(qkey[-1])
    m0 = 3 * (q - 1) + 1
    end = date(y + 1, 1, 1) if q == 4 else date(y, m0 + 3, 1)
    return date(y, m0, 1), end


# -----------------------------------------------------------------------------
# 1. 成分股區間 → CIK
# -----------------------------------------------------------------------------
def load_renames(eq_root):
    path = os.path.join(eq_root, "universes", "us", "renames.csv")
    if not os.path.exists(path):
        return {}
    return {norm_ticker(r["old"]): norm_ticker(r["new"]) for r in read_csv(path)
            if r.get("old") and not r["old"].startswith("#")}


def load_membership(eq_root):
    rows = []
    for r in read_csv(os.path.join(eq_root, "universes", "sp500", "membership.csv")):
        start = date.fromisoformat(r["start"])
        end = date.fromisoformat(r["end"]) if r.get("end") else None
        if end is not None and end < START:
            continue
        rows.append({"ticker": norm_ticker(r["ticker"]), "start": start, "end": end})
    return rows


def load_ticker_cik():
    """{代號: {cik: [(季起, 季迄, 申報數, 公司名)]}}；代號統一成價格資料夾格式（BRK.B → BRK-B）。"""
    out = defaultdict(lambda: defaultdict(list))
    files = sorted(glob.glob(os.path.join(TICKER_CIK_DIR, "*.csv.gz")))
    for path in files:
        q0, q1 = quarter_range(os.path.basename(path)[:6])
        for r in read_csv(path):
            out[norm_ticker(r["ticker"])][r["cik"].lstrip("0")].append((q0, q1, int(r["n_filings"]), r["issuer_name"]))
    return out, len(files)


def map_intervals(members, tc, renames, current):
    """每段成分股區間選一個 CIK：區間內用該代號申報最多次的公司。
    代號同時試原樣、改名後、去掉連字號（BRK-B → BRKB 之類的申報寫法）。"""
    back = defaultdict(set)
    for old, new in renames.items():
        back[new].add(old)
    out = []
    for m in members:
        t = m["ticker"]
        variants = {t, renames.get(t, t), t.replace("-", "")} | back.get(t, set())
        end = m["end"] or date.max
        score, names = Counter(), {}
        for v in variants:
            for cik, spans in tc.get(v, {}).items():
                for q0, q1, n, name in spans:
                    if q0 < end and q1 > max(m["start"], START):
                        score[cik] += n
                        names[cik] = name
        src = "form345"
        if not score and m["end"] is None and t in current:
            score[current[t][0]] = 1
            names[current[t][0]] = current[t][1]
            src = "company_tickers"
        if score:
            cik, _ = score.most_common(1)[0]
            out.append({**m, "cik": cik, "company": names[cik], "source": src,
                        "n_candidates": len(score), "alternatives": ";".join(c for c in score if c != cik)})
        else:
            out.append({**m, "cik": "", "company": "", "source": "missing", "n_candidates": 0, "alternatives": ""})
    return out


# -----------------------------------------------------------------------------
# 2. 抓 8-K 2.02
# -----------------------------------------------------------------------------
def parse_block(block, cik, company):
    """submissions 的欄位式區塊 → 2.02 事件列。"""
    forms = block.get("form") or []
    out = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        items = (block.get("items") or [""] * len(forms))[i] or ""
        if "2.02" not in [x.strip() for x in items.split(",")]:
            continue
        fd = block["filingDate"][i]
        if fd < START.isoformat():
            continue
        out.append({"cik": cik, "company": company, "form": form, "accession": block["accessionNumber"][i],
                    "filing_date": fd, "acceptance": (block.get("acceptanceDateTime") or [""] * len(forms))[i],
                    "items": items, "report_date": (block.get("reportDate") or [""] * len(forms))[i]})
    return out


def fetch_cik(sec, cik, full):
    """回傳 (事件列, 是否已抓完舊分頁)。舊分頁全部早於 START 時就不抓。"""
    data = sec.get_json(SUBMISSIONS.format(name=f"CIK{cik10(cik)}.json"))
    if data is None:
        return [], True
    company = data.get("name", "")
    filings = data.get("filings") or {}
    events = parse_block(filings.get("recent") or {}, cik, company)
    if full:
        for f in filings.get("files") or []:
            if (f.get("filingTo") or "9999") < START.isoformat():
                continue
            page = sec.get_json(SUBMISSIONS.format(name=f["name"]))
            if page:
                events += parse_block(page, cik, company)
    return events, full


def acceptance_hour(s):
    """'2024-05-02T16:30:22.000Z' → 16。SEC 的時間實際上是美東時間，但字串帶 Z；以分布核對。"""
    try:
        return int(s[11:13])
    except (ValueError, IndexError):
        return None


# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="SEC 8-K Item 2.02 財報事件抓取")
    ap.add_argument("--equities-root", default=os.environ.get("EQUITIES_ROOT", DEFAULT_EQ_ROOT))
    ap.add_argument("--full", action="store_true", help="連舊分頁全部重抓")
    ap.add_argument("--limit", type=int, help="只抓前 N 個 CIK（試跑）")
    args = ap.parse_args()

    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        sys.exit("請設定環境變數 SEC_USER_AGENT（名稱 + email）")
    sec = Sec(ua)

    tc, n_q = load_ticker_cik()
    if not tc:
        sys.exit(f"找不到 {TICKER_CIK_DIR}：先跑 scripts/insider_fetch.py --refresh-all 產生代號 ↔ CIK 對照")
    renames = load_renames(args.equities_root)
    members = load_membership(args.equities_root)
    print(f"成分股區間 {len(members)} 段；代號 ↔ CIK 對照 {n_q} 季、{len(tc)} 個代號", flush=True)

    try:
        ct = sec.get_json(COMPANY_TICKERS) or {}
    except Blocked:
        print(f"SEC 回 403——User-Agent 被擋（目前：{ua!r}）", flush=True)
        return 2
    current = {norm_ticker(v["ticker"]): (str(v["cik_str"]), v.get("title", "")) for v in ct.values()}

    mapping = map_intervals(members, tc, renames, current)
    src = Counter(m["source"] for m in mapping)
    print(f"區間對到 CIK：{dict(src)}；多候選 {sum(1 for m in mapping if m['n_candidates'] > 1)} 段", flush=True)
    write_csv(os.path.join(OUT_DIR, "sp500_cik_map.csv"),
              [{**m, "start": m["start"], "end": m["end"] or ""} for m in mapping],
              ["ticker", "start", "end", "cik", "company", "source", "n_candidates", "alternatives"])

    state_path = os.path.join(OUT_DIR, "state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"ciks": {}}
    ev_path = os.path.join(OUT_DIR, "earnings_8k.csv.gz")
    events = {r["accession"] + "|" + r["cik"]: r for r in (read_csv(ev_path) if os.path.exists(ev_path) else [])}

    ciks = sorted({m["cik"] for m in mapping if m["cik"]}, key=int)
    if args.limit:
        ciks = ciks[: args.limit]
    for n, cik in enumerate(ciks, 1):
        need_full = args.full or not state["ciks"].get(cik, {}).get("history_done")
        try:
            rows, done = fetch_cik(sec, cik, need_full)
        except Blocked:
            print(f"SEC 回 403——User-Agent 被擋（目前：{ua!r}）；已完成的 CIK 已存檔", flush=True)
            break
        for r in rows:
            events[r["accession"] + "|" + r["cik"]] = r
        st = state["ciks"].setdefault(cik, {})
        st["history_done"] = st.get("history_done", False) or done
        st["fetched"] = date.today().isoformat()
        if n % 100 == 0 or n == len(ciks):
            print(f"  [{n}/{len(ciks)}] 事件累計 {len(events)}（請求 {sec.calls} 次）", flush=True)

    all_events = sorted(events.values(), key=lambda r: (r["filing_date"], r["cik"]))
    write_csv(ev_path, all_events, EVENT_FIELDS, gz=True)

    # 只留申報當時是成分股的事件，附價格資料夾用的代號（改名後）
    by_cik = defaultdict(list)
    for m in mapping:
        if m["cik"]:
            by_cik[m["cik"]].append(m)
    joined = []
    for r in all_events:
        d = date.fromisoformat(r["filing_date"])
        for m in by_cik.get(r["cik"], []):
            if m["start"] <= d and (m["end"] is None or d < m["end"]):
                joined.append({**r, "ticker": m["ticker"], "price_ticker": renames.get(m["ticker"], m["ticker"]),
                               "member_start": m["start"]})
                break
    write_csv(os.path.join(OUT_DIR, "sp500_earnings_events.csv.gz"), joined,
              EVENT_FIELDS + ["ticker", "price_ticker", "member_start"], gz=True)

    hours = Counter(h for h in (acceptance_hour(r["acceptance"]) for r in all_events) if h is not None)
    state["acceptance_hour_hist"] = {str(h): hours[h] for h in sorted(hours)}
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["summary"] = {"intervals": len(mapping), "mapping_sources": dict(src), "ciks": len(ciks),
                        "events_all": len(all_events), "events_sp500": len(joined), "requests": sec.calls}
    with open(state_path, "w") as f:
        json.dump(state, f, indent=1)
    print(f"2.02 事件 {len(all_events)} 筆，其中申報時是成分股 {len(joined)} 筆", flush=True)
    print(f"acceptance 小時分布（核對時區：美東盤後約 16–17 時、盤前約 6–9 時）：{state['acceptance_hour_hist']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
