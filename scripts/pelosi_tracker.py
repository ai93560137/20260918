#!/usr/bin/env python3
# =============================================================================
# 佩洛西（Nancy Pelosi）股票交易追蹤
# -----------------------------------------------------------------------------
# 數據源：美國眾議院書記官處（House Clerk）官方財務披露
#   索引  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{年}FD.zip
#         （內含 {年}FD.xml，每份申報一筆：姓名、FilingType、FilingDate、DocID）
#   PTR   https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{年}/{DocID}.pdf
#         （Periodic Transaction Report，FilingType = P）
# 流程：抓索引 → 篩 Last=Pelosi 且 FilingType=P → 對未見過的 DocID 下載 PDF、
#       解析每筆交易 → 寫入 data/pelosi/ → 有新申報時產生 Telegram 訊息。
# 注意：STOCK Act 容許交易後 45 天內申報，所以這是「延遲」資訊，不是即時訊號。
#       金額只有區間（如 $1,000,001 - $5,000,000），沒有確切股數/價格。
#
# 用法：
#   python3 scripts/pelosi_tracker.py                 # 抓今年（1 月時連去年）
#   python3 scripts/pelosi_tracker.py --years 2024 2025 2026   # 回補
#   python3 scripts/pelosi_tracker.py --no-prices     # 不抓 Yahoo 現價
# 首次執行（沒有 state）自動回補 2014 年起的申報，只建檔、不發通知。
# =============================================================================
import argparse
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

BASE = "https://disclosures-clerk.house.gov/public_disc"
INDEX_URL = BASE + "/financial-pdfs/{year}FD.zip"
PTR_URL = BASE + "/ptr-pdfs/{year}/{doc_id}.pdf"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
UA = {"User-Agent": "Mozilla/5.0 (pelosi-tracker; +github actions)"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "pelosi")
STATE_FILE = os.path.join(OUT_DIR, "state.json")
TX_FILE = os.path.join(OUT_DIR, "transactions.json")
REPORT_FILE = os.path.join(OUT_DIR, "README.md")
RAW_DIR = os.path.join(OUT_DIR, "raw")  # 每份 PTR 抽出的純文字，可離線重新解析
BACKFILL_FROM = 2014  # 更早的申報多為紙本掃描，解析不了

TX_TYPES = {"P": "買入", "S": "賣出", "S (partial)": "部分賣出", "E": "交換"}
OWNERS = {"SP": "配偶", "JT": "聯名", "DC": "受養子女", "Self": "本人"}

# 一筆交易的核心：[資產類別] 交易類型 交易日 通知日 金額區間
# pypdf 抽出的日期常黏在一起（01/14/202501/14/2025$250,001 -），所以 \s* 都允許 0 個空白
# 兩種版面都要吃：
#   新版（約 2020 起）：SP Apple Inc. (AAPL) [ST] P 01/14/2025 01/14/2025 $250,001 - $500,000
#   舊版（2014–2020）：sP apple Inc. (aaPl) P 02/2/2018 02/2/2018 $100,001 - $250,000
#     小型大寫字型被抽成大小寫混雜（sP、(aaPl)、[oP]、交易類型 s），沒有 [資產類別]，日可能是單位數。
# pypdf 抽出的日期常黏在一起（01/14/202501/14/2025$250,001 -），所以 \s* 都允許 0 個空白
CORE_RE = re.compile(
    r"(?:\[(?P<atype>[A-Za-z]{2})\]\s*)?"
    r"(?<![A-Za-z])(?P<tx>[Ss]\s*\(\s*partial\s*\)|[PpSsEe])\s*"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*"
    r"(?P<notif>\d{1,2}/\d{1,2}/\d{4})\s*"
    r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+|Over \$[\d,]+|Spouse/DC Over \$[\d,]+|\$[\d,]+)"
)
# 持有人代號前可能黏著上一筆說明的句點（…9/21/18.sP apple Inc.）
OWNER_RE = re.compile(r"(?:^|[\s.])(SP|JT|DC)\s", re.I)
# pypdf 會把代號抽成大小寫混雜（TSlA、(aaPl)），所以不分大小寫、之後轉大寫
TICKER_RE = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9.\-]{0,6})\s*\)\s*$")
# 頁首/頁尾樣板文字，出現在交易列表中間時要剔除
BOILERPLATE_RE = re.compile(
    r"\* For the complete list of asset type abbreviations.*?(?=SP |JT |DC |$)"
    r"|Filing ID #\d+"
    r"|Clerk of the House of Representatives[^\n]*",
    re.S,
)
# 表頭（每頁重複）：交易從第一個表頭之後開始，之前的申報人資料（含 Washington, DC）不能當持有人代號
HEADER_RE = re.compile(
    r"ID Owner Asset Transaction\s*Type\s*Date\s*Notification\s*Date\s*Amount(?:\s*Cap\.\s*Gains\s*>\s*\$200\?)?",
    re.I,
)
# 跨頁被切開的一筆：「… Class A Common P 01/16/2026 01/16/2026 $50,001 - [表頭] Stock (TEM) [ST] $100,000」
STRADDLE_RE = re.compile(
    r"^\s*(?P<rest>[^()\[\]$]*?)\(\s*(?P<tk>[A-Za-z][A-Za-z0-9.\-]{0,6})\s*\)\s*"
    r"\[(?P<at>[A-Za-z]{2})\]\s*(?P<amt>\$[\d,]+)"
)
# 期權說明在去掉所有空白後比對（舊版會把字拆開：expiration d ate、personall y）
OPTION_RE = re.compile(
    r"(?P<verb>purchased|purchaseof|purchase|sold|saleof|exercised|exerciseof|received)"
    r"(?P<n>[\d,]+)(?P<kind>call|put)options?"
    r".*?strikepriceof\$(?P<strike>[\d,.]+?)\.?(?=[a-z]|$)"
    r".*?expirationdateof(?P<exp>\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2}))",
    re.S,
)
# 「50 call options purchased 12/17/21 … expired with no value.」：到期作廢，視同出場
EXPIRED_RE = re.compile(
    r"(?P<n>[\d,]+)(?P<kind>call|put)options?.*?strikepriceof\$(?P<strike>[\d,.]+?)\.?(?=[a-z]|$)"
    r".*?expirationdateof(?P<exp>\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2})).*?expired",
    re.S,
)
# 2014 年版只寫「Purchase of 50 Options」，沒有 call/put、行使價、到期日
BARE_OPTION_RE = re.compile(r"(?P<verb>purchased|purchaseof|purchase|sold|saleof)(?P<n>[\d,]+)options?")
VERBS = {"purchaseof": "purchased", "purchase": "purchased", "saleof": "sold", "exerciseof": "exercised"}


# -----------------------------------------------------------------------------
# 抓取
# -----------------------------------------------------------------------------
def http_get(url, timeout=60, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"GET {url} 失敗：{last}")


def parse_index(xml_bytes, last_name="Pelosi"):
    """回傳該議員所有 PTR 申報（FilingType=P）。"""
    root = ET.fromstring(xml_bytes)
    out = []
    for m in root.iter("Member"):
        g = lambda tag: (m.findtext(tag) or "").strip()
        if g("Last").lower() != last_name.lower() or g("FilingType") != "P":
            continue
        out.append({
            "doc_id": g("DocID"),
            "year": g("Year"),
            "filing_date": _iso(g("FilingDate")),
            "name": " ".join(x for x in (g("Prefix"), g("First"), g("Last"), g("Suffix")) if x),
            "district": g("StateDst"),
        })
    return out


def fetch_filings(year, last_name):
    blob = http_get(INDEX_URL.format(year=year), timeout=120)
    if blob is None:
        print(f"[{year}] 索引不存在（404）")
        return []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
        if not name:
            raise RuntimeError(f"{year}FD.zip 裡沒有 XML")
        return parse_index(z.read(name), last_name)


def pdf_text(pdf_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


# -----------------------------------------------------------------------------
# 解析 PTR
# -----------------------------------------------------------------------------
def _iso(mdy):
    """'1/14/2025' / '01/14/2025' → '2025-01-14'；失敗回原字串。"""
    try:
        return datetime.strptime(mdy.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return mdy.strip()


def _clean_desc(text):
    text = BOILERPLATE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 常見欄位：F S: New（申報狀態）、S O:（子帳戶）、D:（說明）、C:（備註）
    # 舊版是 F IlINg s TaTus : New D EsCRIPTIoN : …（大小寫亂、字被拆開），標籤前也可能沒空白
    m = re.search(r"(?<![A-Za-z])D\s*(?:(?i:ESCRIPTION)\s*)?:\s*(.+?)"
                  r"(?=\s*(?:C\s*(?:(?i:OMMENTS)\s*)?:|F\s*(?:(?i:ILING)\s*)?S\s*(?:(?i:TATUS)\s*)?:"
                  r"|S\s*(?:(?i:UBHOLDING)\s*)?O\s*(?:(?i:F)\s*)?:|I P O|(?i:i\s*nitial\s+p\s*ublic)"
                  r"|\* For)|$)",
                  text)
    return m.group(1).strip() if m else ""


def parse_option(desc):
    compact = re.sub(r"\s+", "", desc or "").lower()
    m = OPTION_RE.search(compact)
    verb = m.group("verb") if m else None
    if not m:
        m = EXPIRED_RE.search(compact)
        verb = "expired" if m else None
    if not m:
        b = BARE_OPTION_RE.search(compact)
        if not b:
            return None
        return {"action": VERBS.get(b.group("verb"), b.group("verb")),
                "contracts": int(b.group("n").replace(",", "")),
                "kind": None, "strike": None, "expiry": None}
    exp = m.group("exp")
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            exp = datetime.strptime(exp, fmt).date().isoformat()
            break
        except ValueError:
            pass
    return {
        "action": VERBS.get(verb, verb),
        "contracts": int(m.group("n").replace(",", "")),
        "kind": m.group("kind"),
        "strike": float(m.group("strike").replace(",", "")),
        "expiry": exp,
    }


def parse_amount(amount):
    nums = [int(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)", amount)]
    if not nums:
        return None, None
    if amount.lower().startswith(("over", "spouse")):
        return nums[0], None
    return nums[0], nums[-1]


def _fix_straddle(row, tail):
    """跨頁切開的一筆：代號、資產類別、金額上限跑到下一頁開頭，補回 row，回傳剩下的說明文字。"""
    if row["ticker"]:
        return tail
    m = STRADDLE_RE.match(tail)
    if not m:
        return tail
    row["asset"] = f"{row['asset']} {m.group('rest').strip(' -')}".strip()
    row["ticker"] = m.group("tk").upper()
    row["asset_type"] = row["asset_type"] or m.group("at").upper()
    if "-" not in row["amount"]:  # 金額只抓到下限
        row["amount"] = f"{row['amount'].strip()} - {m.group('amt')}"
        row["amount_min"], row["amount_max"] = parse_amount(row["amount"])
    return tail[m.end():]


def parse_ptr(text):
    """PTR 純文字 → 交易清單。解析不到回 []（多半是手寫掃描版）。"""
    # 小型大寫標籤會被抽成「D\0\0\0…:」，先去掉 NUL
    flat = re.sub(r"\s+", " ", BOILERPLATE_RE.sub(" ", text.replace("\x00", "")))
    h = HEADER_RE.search(flat)
    flat = HEADER_RE.sub(" ", flat[h.end():] if h else flat)
    matches = list(CORE_RE.finditer(flat))
    rows = []
    prev_end = 0
    for i, m in enumerate(matches):
        seg = flat[prev_end:m.start()]
        # seg = 「上一筆的說明」+「持有人 資產名稱 (代號)」
        owners = list(OWNER_RE.finditer(seg))
        if owners:
            o = owners[-1]
            owner, asset, desc_prev = o.group(1).upper(), seg[o.end():], seg[:o.start()]
        else:
            # 2014–2015 年版沒有持有人代號：seg 整段同時是上一筆說明和這一筆資產名稱，分不乾淨。
            # 代號仍在 seg 結尾；上一筆說明會帶著這筆名稱當字尾（只影響顯示，期權/代號照樣解析）
            owner, asset, desc_prev = "SP", seg, seg
            if rows:
                asset = re.split(r"[.:]\s*(?=[^.:]*$)|\d/\d{2}(?=[A-Z])", asset)[-1]
        if rows:
            rows[-1]["description"] = _clean_desc(_fix_straddle(rows[-1], desc_prev))
        asset = asset.strip()
        tm = TICKER_RE.search(asset)
        ticker = tm.group(1).upper() if tm else ""
        name = asset[:tm.start()].strip() if tm else asset
        tx = "S (partial)" if "partial" in m.group("tx").lower() else m.group("tx").upper()
        lo, hi = parse_amount(m.group("amount"))
        rows.append({
            "owner": owner,
            "asset": name,
            "ticker": ticker,
            "asset_type": (m.group("atype") or "").upper(),
            "type": tx,
            "date": _iso(m.group("date")),
            "notified": _iso(m.group("notif")),
            "amount": re.sub(r"\s+", " ", m.group("amount")),
            "amount_min": lo,
            "amount_max": hi,
            "description": "",
        })
        prev_end = m.end()
    if rows:
        rows[-1]["description"] = _clean_desc(_fix_straddle(rows[-1], flat[prev_end:]))
    for r in rows:
        opt = parse_option(r["description"])
        if not r["asset_type"]:  # 舊版沒有資產類別：說明提到期權就當 OP，其餘當股票
            r["asset_type"] = "OP" if opt else "ST"
        r["option"] = opt if r["asset_type"] == "OP" else None
    return rows


# -----------------------------------------------------------------------------
# 現價（best effort，Yahoo 失敗就略過）
# -----------------------------------------------------------------------------
def yahoo_closes(ticker, start):
    t = {"SQ": "XYZ", "FB": "META"}.get(ticker, ticker).replace(".", "-")  # 改名代號
    p1 = int(datetime.combine(start - timedelta(days=7), datetime.min.time(), timezone.utc).timestamp())
    url = YAHOO_URL.format(ticker=t) + f"?period1={p1}&period2={int(time.time())}&interval=1d"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    days = [datetime.fromtimestamp(ts, timezone.utc).date() for ts in res["timestamp"]]
    return [(d, c) for d, c in zip(days, closes) if c is not None]


def attach_prices(rows):
    """每個代號抓一次，補上交易日收盤與最新收盤、漲跌幅。"""
    by_ticker = {}
    for r in rows:
        if r["ticker"] and r["asset_type"] in ("ST", "OP", "EF"):
            by_ticker.setdefault(r["ticker"], []).append(r)
    for tk, rs in by_ticker.items():
        start = min(date.fromisoformat(r["date"]) for r in rs if len(r["date"]) == 10)
        try:
            series = yahoo_closes(tk, start)
        except Exception as e:  # noqa: BLE001 — 現價只是附加資訊
            print(f"  現價 {tk} 失敗：{e}")
            continue
        if not series:
            continue
        last_d, last_c = series[-1]
        for r in rs:
            d = date.fromisoformat(r["date"])
            on = next((c for dd, c in series if dd >= d), None)
            r["price_at_tx"] = round(on, 2) if on else None
            r["price_now"] = round(last_c, 2)
            r["price_now_date"] = last_d.isoformat()
            r["change_pct"] = round((last_c / on - 1) * 100, 2) if on else None
        time.sleep(0.3)


# -----------------------------------------------------------------------------
# 輸出
# -----------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def fmt_option(opt):
    """「50 張 Call 行使價 $150 到期 2026-01-16」；舊版申報缺的欄位就省略，作廢的標明。"""
    parts = [f"{opt['contracts']} 張"]
    if opt.get("kind"):
        parts.append(opt["kind"].title())
    else:
        parts.append("期權")
    if opt.get("strike") is not None:
        parts.append(f"行使價 ${opt['strike']:g}")
    if opt.get("expiry"):
        parts.append(f"到期 {opt['expiry']}")
    if opt.get("action") == "expired":
        parts.append("（到期作廢）")
    return " ".join(parts)


def fmt_tx_line(r):
    tx = TX_TYPES.get(r["type"], r["type"])
    head = f"{'🟢' if r['type'] == 'P' else '🔴' if r['type'].startswith('S') else '⚪'} {tx} "
    head += f"{r['ticker'] or r['asset']}"
    if r["ticker"]:
        head += f"（{r['asset'][:40]}）"
    lines = [head, f"   交易日 {r['date']}｜{r['amount']}｜{OWNERS.get(r['owner'], r['owner'])}"]
    opt = r.get("option")
    if opt:
        lines.append(f"   期權：{fmt_option(opt)}")
    elif r["description"]:
        lines.append(f"   說明：{r['description'][:160]}")
    if r.get("change_pct") is not None:
        lines.append(f"   正股 ${r['price_at_tx']} → ${r['price_now']}（{r['change_pct']:+.1f}%）")
    return "\n".join(lines)


def build_tg(filings):
    parts = []
    for f in filings:
        head = [
            "🏛 佩洛西新交易申報（PTR）",
            f"申報日 {f['filing_date']}｜DocID {f['doc_id']}",
            f["url"],
        ]
        if not f["transactions"]:
            head.append("⚠️ PDF 無法自動解析（可能是掃描版），請直接開連結看。")
        body = [fmt_tx_line(r) for r in f["transactions"]]
        parts.append("\n".join(head) + ("\n\n" + "\n\n".join(body) if body else ""))
    parts.append("※ 國會議員可在交易後 45 天內申報，非即時訊號；金額僅為區間。")
    return "\n\n━━━━━━━━\n\n".join(parts)


def split_tg(text, limit=3900):
    """Telegram 單則上限 4096 字，按段落切。"""
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        add = para if not cur else "\n\n" + para
        if len(cur) + len(add) > limit and cur:
            chunks.append(cur)
            cur = para[:limit]
        else:
            cur += add
    if cur:
        chunks.append(cur)
    return chunks


def build_report(filings):
    txs = [dict(r, filing_date=f["filing_date"], doc_id=f["doc_id"], url=f["url"])
           for f in filings for r in f["transactions"]]
    txs.sort(key=lambda r: (r["date"], r["filing_date"]), reverse=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# 佩洛西（Nancy Pelosi）股票交易追蹤",
        "",
        f"更新時間：{now}　｜　申報 {len(filings)} 份　｜　交易 {len(txs)} 筆",
        "",
        "數據源：[House Clerk 財務披露](https://disclosures-clerk.house.gov/FinancialDisclosure)"
        "（Periodic Transaction Report）。交易多由配偶 Paul Pelosi 帳戶進行；"
        "申報可延遲至交易後 45 天，金額只有區間。漲跌幅為正股自交易日收盤至最新收盤（Yahoo，僅供參考）。",
        "",
    ]
    # 代號彙總：買入/賣出次數與最近一筆
    agg = {}
    for r in txs:
        k = r["ticker"] or r["asset"][:30]
        a = agg.setdefault(k, {"buy": 0, "sell": 0, "last": r["date"], "chg": r.get("change_pct")})
        if r["type"] == "P":
            a["buy"] += 1
        elif r["type"].startswith("S"):
            a["sell"] += 1
    out += ["## 代號彙總", "", "| 代號 | 買入 | 賣出 | 最近交易 | 自最近交易漲跌 |", "|---|---:|---:|---|---:|"]
    for k, a in sorted(agg.items(), key=lambda kv: kv[1]["last"], reverse=True):
        chg = f"{a['chg']:+.1f}%" if a["chg"] is not None else "—"
        out.append(f"| {k} | {a['buy']} | {a['sell']} | {a['last']} | {chg} |")
    out += ["", "## 全部交易（新 → 舊）", "",
            "| 交易日 | 申報日 | 代號 | 資產 | 類型 | 金額 | 細節 | 漲跌 |",
            "|---|---|---|---|---|---|---|---:|"]
    for r in txs:
        opt = r.get("option")
        detail = (fmt_option(opt)
                  if opt else (r["description"][:60] or ""))
        chg = f"{r['change_pct']:+.1f}%" if r.get("change_pct") is not None else "—"
        asset = r["asset"].replace("|", "/")[:45]
        out.append(f"| {r['date']} | [{r['filing_date']}]({r['url']}) | {r['ticker'] or '—'} | {asset} "
                   f"| {TX_TYPES.get(r['type'], r['type'])} | {r['amount']} | {detail.replace('|', '/')} | {chg} |")
    unparsed = [f for f in filings if not f["transactions"]]
    if unparsed:
        out += ["", "## 無法自動解析的申報", ""]
        out += [f"- {f['filing_date']} [{f['doc_id']}]({f['url']})" for f in unparsed]
    return "\n".join(out) + "\n"


def filing_text(f):
    """PTR 純文字：優先讀 raw 快取，沒有才下載 PDF 抽字並存檔。PDF 尚未上線回 None。"""
    path = os.path.join(RAW_DIR, f"{f['doc_id']}.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    pdf = http_get(f["url"])
    if pdf is None:
        return None
    try:
        text = pdf_text(pdf)
    except Exception as e:  # noqa: BLE001 — 壞檔當成空文字，不擋其他申報
        print(f"  {f['doc_id']} PDF 讀取失敗：{e}")
        text = ""
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    time.sleep(0.5)
    return text


def safe_parse(f, text):
    try:
        rows = parse_ptr(text)
    except Exception as e:  # noqa: BLE001 — 單份解析失敗不擋其他
        print(f"  {f['doc_id']} 解析失敗：{e}")
        rows = []
    note = "（無文字，多半是掃描版）" if not text.strip() else ""
    print(f"  {f['doc_id']}（{f['filing_date']}）交易 {len(rows)} 筆{note}")
    return rows


def gh_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="佩洛西股票交易追蹤（House Clerk PTR）")
    ap.add_argument("--years", type=int, nargs="*", help="要抓的申報年份（預設今年，1 月連去年）")
    ap.add_argument("--member", default="Pelosi", help="議員姓氏（預設 Pelosi）")
    ap.add_argument("--no-prices", action="store_true", help="不抓 Yahoo 現價")
    ap.add_argument("--notify-backfill", action="store_true", help="首次建檔也產生通知")
    ap.add_argument("--reparse", action="store_true", help="重新解析所有已知申報（改了解析規則後用）")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    os.makedirs(OUT_DIR, exist_ok=True)

    state = load_json(STATE_FILE, None)
    first_run = state is None
    if args.years:
        years = args.years
    elif first_run:  # 首次建檔直接回補歷史，回測才有樣本（不通知）
        years = list(range(BACKFILL_FROM, today.year + 1))
    else:
        years = [today.year - 1, today.year] if today.month == 1 else [today.year]
    state = state or {"seen": []}
    seen = set(state["seen"])
    filings = load_json(TX_FILE, [])
    known = {f["doc_id"] for f in filings}

    new = []
    for y in years:
        idx = fetch_filings(y, args.member)
        print(f"[{y}] {args.member} PTR 申報 {len(idx)} 份")
        for f in sorted(idx, key=lambda x: x["filing_date"]):
            if f["doc_id"] in seen or f["doc_id"] in known:
                continue
            f["url"] = PTR_URL.format(year=f["year"] or y, doc_id=f["doc_id"])
            text = filing_text(f)
            if text is None:
                print(f"  {f['doc_id']} PDF 尚未上線，下次再試")
                continue
            f["transactions"] = safe_parse(f, text)
            new.append(f)
            seen.add(f["doc_id"])

    if args.reparse:  # 解析規則改了之後，用 raw 文字重跑全部舊申報（raw 沒有才重新下載）
        for f in filings:
            text = filing_text(f)
            if text is not None:
                f["transactions"] = safe_parse(f, text)

    if not args.no_prices:
        attach_prices([r for f in filings + new for r in f["transactions"]])

    filings = sorted(filings + new, key=lambda f: f["filing_date"], reverse=True)
    save_json(TX_FILE, filings)
    state.update(seen=sorted(seen), updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    save_json(STATE_FILE, state)
    with open(REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(build_report(filings))

    notify = new and (not first_run or args.notify_backfill)
    for old in [p for p in os.listdir(OUT_DIR) if p.startswith("tg_msg")]:
        os.remove(os.path.join(OUT_DIR, old))
    if notify:
        for i, chunk in enumerate(split_tg(build_tg(new)), 1):
            with open(os.path.join(OUT_DIR, f"tg_msg_{i:02d}.txt"), "w", encoding="utf-8") as fh:
                fh.write(chunk)
    print(f"新申報 {len(new)} 份；{'產生通知' if notify else '不通知'}"
          f"{'（首次建檔）' if first_run else ''}")
    gh_output("new", len(new))
    gh_output("notify", "1" if notify else "0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
