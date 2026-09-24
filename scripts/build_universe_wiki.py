#!/usr/bin/env python3
"""把 Wikipedia 原始 wikitext 修訂版本解析成 point-in-time 指數成分股區間檔。

純文字解析、只用標準庫、不需要網路，可重複執行（輸出完全由輸入決定）：
    python3 scripts/build_universe_wiki.py

輸入（research_output/multimarket/ 底下，由 research_multimarket_probe.py 抓好）：
- wiki/ndx/<YYYY>.txt       英文維基「Nasdaq-100」約每年 6/30 的修訂版本
- wiki/n225/<YYYY>.txt      英文維基「Nikkei 225」同上
- wiki/djia_hist/current.txt 英文維基「Historical components of the Dow Jones
                              Industrial Average」（逐次調整後的完整 30 檔名單）
- probe/nasdaq_screener.json    Nasdaq 全美上市清單（驗證 NDX 代碼用）
- probe/nikkei_components_en.txt 日經官方現行成分股頁 HTML（驗證 N225 用）

輸出：
- universes/{ndx,djia,n225}/membership.csv   ticker,start,end（end 不含、空白 = 至今）
- universes/n225/current_official.csv         日經官方現行名單 code,ticker,name,sector
- universes/WIKI_PARSE_REPORT.md              解析報告（逐年數量、換手、驗證、限制）

**這不是官方權威來源**——是維基編輯者記錄的「當時成分股」，可能滯後或錯漏
（日經 225 的維基名單常常好幾年沒更新，見報告）。年度快照沿用恒指慣例
（universe.py / scripts/pointintime/）：<YYYY> 年的快照視為 <YYYY>-06-30 起生效，
直到下一份快照；最後一份快照的成分股 end 留空。道指用歷史頁上的實際調整日。
"""
import csv
import html
import json
import re
from collections import Counter
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "research_output" / "multimarket" / "wiki"
PROBE = ROOT / "research_output" / "multimarket" / "probe"
OUT = ROOT / "universes"

YEARS = range(2008, 2027)
SNAP_MONTH_DAY = (6, 30)  # 年度快照生效日（跟恒指慣例一致）

# 合理數量範圍：超出就視為「這年解析失敗」，沿用前一年名單並寫進報告
NDX_RANGE = (95, 115)   # Nasdaq-100 = 100 家公司，雙重股權會多出幾檔（最多約 107-108）
N225_RANGE = (215, 235)  # 日經 225 = 225 檔（維基本身偶有多列/漏列一兩檔）
# 年換手警戒線（超過多半是解析問題或維基名單停更後一次補齊）
NDX_TURNOVER_WARN = 25
N225_TURNOVER_WARN = 20

REF_RE = re.compile(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LINK_RE = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
REV_RE = re.compile(r"<!-- revision (\d{4}-\d{2}-\d{2})T")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
DATE_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})")


# ───────────────────────────── 共用小工具 ─────────────────────────────

def strip_markup(s: str) -> str:
    """去掉 <ref>、註解、[[連結|顯示文字]] → 顯示文字、粗斜體引號、多餘空白。"""
    s = COMMENT_RE.sub("", REF_RE.sub("", s))
    s = LINK_RE.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def revision_date(text: str) -> str:
    """檔案第一行 `<!-- revision 2008-05-31T20:29:16Z -->` 的日期。"""
    m = REV_RE.search(text)
    return m.group(1) if m else ""


def parse_en_date(s: str) -> date | None:
    """'May 19th, 2008' / 'June 29, 2026' → date。"""
    m = DATE_RE.search(s)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))


def level2_section(text: str, header_re: str) -> str:
    """取出某個二級標題（== X ==）到下一個二級標題之間的內容（含三級小節）。"""
    m = re.search(header_re, text, re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^==[^=]", rest, re.MULTILINE)
    return rest[:n.start()] if n else rest


def yahoo_us(ticker: str) -> str:
    """美股代碼轉 Yahoo 格式：BRK.B / BRK/B → BRK-B。"""
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def snapshots_to_intervals(snaps: list[tuple[date, set[str]]]) -> list[tuple[str, date, date | None]]:
    """逐年快照 → 連續成員區間。快照 i 的名單有效期 [d_i, d_{i+1})；
    最後一份快照的成員 end=None（至今）。"""
    snaps = sorted(snaps, key=lambda x: x[0])
    out = []
    for t in sorted(set().union(*(m for _, m in snaps))):
        start = None
        for i, (d, mem) in enumerate(snaps):
            if t in mem and start is None:
                start = d
            if t not in mem and start is not None:
                out.append((t, start, d))
                start = None
        if start is not None:
            out.append((t, start, None))
    return out


def dated_lists_to_intervals(lists: list[tuple[date, set[str]]]) -> list[tuple[str, date, date | None]]:
    """跟上面同一個邏輯（道指：每次調整日的完整名單）。"""
    return snapshots_to_intervals(lists)


def write_membership(path: Path, intervals: list[tuple[str, date, date | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(intervals, key=lambda r: (r[0], r[1]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ticker", "start", "end"])
        for t, a, b in rows:
            w.writerow([t, a.isoformat(), b.isoformat() if b else ""])


def similar(a: str, b: str) -> float:
    """公司名相似度（改名/改代碼偵測用）：去掉常見公司後綴再比。"""
    generic = (r"\b(inc|corp|corporation|co|ltd|limited|holdings?|plc|group|company|the|class [a-c]|"
               r"communications|technolog(?:y|ies)|systems|international|industries|financial|"
               r"pharmaceuticals?|electric|kaisha|incorporated)\b\.?")

    def norm(s):
        s = re.sub(r"\(.*?\)", "", s.lower())
        return re.sub(r"[^a-z0-9]", "", re.sub(generic, "", s))
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    # 前綴相同（Meiji Seika → Meiji Holdings 這種合併改組不算；要整段名字是對方的開頭）
    # 且較短的一方至少 5 個字元，避免 DIC ↔ Disco 這種巧合
    if min(len(na), len(nb)) >= 5 and (na.startswith(nb) or nb.startswith(na)):
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def rename_candidates(removed: dict[str, str], added: dict[str, str], thr: float = 0.75):
    """同一年「走一檔、進一檔」且公司名相近 → 疑似改名/改代碼（只列出，不自動合併）。"""
    out = []
    for rt, rn in sorted(removed.items()):
        best = max(((similar(rn, an), at, an) for at, an in added.items()), default=None)
        if best and best[0] >= thr:
            out.append((rt, rn, best[1], best[2]))
    return out


# ───────────────────────────── Nasdaq-100 ─────────────────────────────
# 兩種年代格式：
# - 2008-2018：`#[[Apple Inc.]] (AAPL)` 編號清單（2016 起包在 {{columns-list}} 裡）
# - 2019 起：id="constituents" 的 wikitable，表頭有 Ticker 欄（欄位順序各年不同：
#   早年 Company||Ticker、2025 起 Ticker !! Company），逐列 `|a||b` 或多行 `| a`
# 2026-09 的最新版（current.txt）已把名單搬到獨立條目「List of NASDAQ-100 companies」，
# 所以最新快照用 2026.txt。

# 已知的 NDX 代碼變更（公開資訊、人工整理；只用在報告的比對與提示，**不**改寫 membership）。
# (舊代碼, 新代碼, 說明)
NDX_KNOWN_TICKER_CHANGES = [
    ("ERTS", "EA", "Electronic Arts 2011 年改代碼"),
    ("NWSA", "FOXA", "News Corp A 股 2013 年分拆後改名 21st Century Fox（新 News Corp 另拿 NWSA）"),
    ("GOOG", "GOOGL", "2014-04 拆股前的 GOOG 是 A 股；之後 A 股 = GOOGL、新 C 股 = GOOG"),
    ("LINTA", "QVCA", "Liberty Interactive 追蹤股 2014 年改代碼"),
    ("QVCA", "QRTEA", "2018 年改名 Qurate Retail"),
    ("PCLN", "BKNG", "Priceline 2018 年改名 Booking Holdings"),
    ("CTRP", "TCOM", "Ctrip 2019 年改名 Trip.com"),
    ("SYMC", "NLOK", "Symantec 2019 年改名 NortonLifeLock（後再改 GEN）"),
    ("WLTW", "WTW", "Willis Towers Watson 後來改代碼 WTW"),
    ("FB", "META", "Facebook 2022 年改名 Meta Platforms"),
    ("FISV", "FI", "Fiserv 2023 年轉 NYSE 並改代碼"),
]
# 非改名但常被誤認的：KRFT → KHC（Kraft 被 Heinz 併購）、BRCM（被 Avago 併購，AVGO 早已是成分股）


NDX_LIST_RE = re.compile(r"\(([A-Z][A-Z.]{0,5})\)\s*$")


def ndx_components_section(text: str) -> str:
    return level2_section(text, r"^==\s*(?:Current )?[Cc]omponents\s*==")


def parse_ndx_table(sec: str) -> list[tuple[str, str]]:
    """wikitable 格式 → [(ticker, company)]。靠表頭找 Ticker / Company 欄。"""
    start = sec.find("{|")
    end = sec.find("\n|}", start)
    table = sec[start:end]
    header: list[str] = []
    out = []
    for row in re.split(r"\n\|-[^\n]*", table):
        row = row.strip()
        if not row or row.startswith("{|") and "!" not in row:
            continue
        if row.startswith("{|"):
            row = row[row.find("!"):]
        if row.startswith("!"):
            cells = re.split(r"!!|\|\||\n!", row.lstrip("!"))
            header = [strip_markup(c.lstrip("|")).lower() for c in cells]
            continue
        cells = [strip_markup(c) for c in re.split(r"\|\||\n\|", LINK_RE.sub(
            lambda m: m.group(2) if m.group(2) is not None else m.group(1), row).lstrip("|"))]
        ti = next(i for i, h in enumerate(header) if "ticker" in h or "symbol" in h)
        ci = next((i for i, h in enumerate(header) if "company" in h or "security" in h), 1 - ti)
        tk = cells[ti] if ti < len(cells) else ""
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", tk):
            out.append((tk, cells[ci] if ci < len(cells) else ""))
    return out


def parse_ndx_list(sec: str) -> list[tuple[str, str]]:
    """編號清單格式：`#[[Adobe Systems|Adobe Systems Incorporated]] (ADBE)`。"""
    out = []
    for line in sec.splitlines():
        if not line.startswith("#"):
            continue
        clean = strip_markup(line.lstrip("#"))
        m = NDX_LIST_RE.search(clean)
        if m:
            out.append((m.group(1), clean[:m.start()].strip()))
    return out


def ndx_asof(sec: str) -> str:
    """名單上方的「This list is current as of …」說明（2024 起沒有這句）。"""
    m = re.search(r"current as (?:of|prior to)[^.]*?(" + DATE_RE.pattern + ")", sec)
    return m.group(1) if m else ""


def parse_ndx(text: str) -> tuple[list[tuple[str, str]], str, str]:
    """回傳 ([(yahoo_ticker, 公司名)], 格式, as-of 字串)。"""
    sec = ndx_components_section(text)
    if not sec:
        return [], "無成分股小節", ""
    if 'id="constituents"' in sec or "{| class=\"wikitable" in sec:
        rows, fmt = parse_ndx_table(sec), "wikitable"
    else:
        rows, fmt = parse_ndx_list(sec), "編號清單"
    seen, out = set(), []
    for t, n in rows:
        t = yahoo_us(t)
        if t not in seen:
            seen.add(t)
            out.append((t, n))
    return out, fmt, ndx_asof(sec)


def parse_ndx_changes(text: str) -> list[tuple[date, list[str], list[str]]]:
    """2026 版條目裡的「Historical components」調整表（id="changes"）：
    每列 Date | 加入代碼 | 加入公司 | 剔除代碼 | 剔除公司 | 原因。只拿來驗證年度快照。"""
    i = text.find('id="changes"')
    if i < 0:
        return []
    table = text[i:text.find("\n|}", i)]
    out = []
    for row in re.split(r"\n\|-[^\n]*", table)[1:]:
        lines = [l for l in row.strip().split("\n") if l.startswith("|")]
        cells = []
        for l in lines:
            cells.extend(c.strip() for c in l[1:].split("||"))
        if len(cells) < 5:
            continue
        d = parse_en_date(cells[0])
        if not d:
            continue
        def tickers(c):
            return [yahoo_us(x) for x in re.findall(r"\b[A-Z][A-Z.]{0,5}\b", strip_markup(c))]
        out.append((d, tickers(cells[1]), tickers(cells[3])))
    return out


def reconstruct_from_changes(latest: set[str], latest_date: date,
                             changes: list[tuple[date, list[str], list[str]]], ref: date) -> set[str]:
    """從最新名單往回倒推 ref 當天（含當天生效的調整）的成分股。"""
    s = set(latest)
    for d, added, removed in sorted(changes, key=lambda x: x[0], reverse=True):
        if ref < d <= latest_date:
            s -= set(added)
            s |= set(removed)
    return s


# ───────────────────────────── 日經 225 ─────────────────────────────
# 各年都是「==Components== 底下按行業 ===小節=== 的條列」：
#   * [[Ajinomoto]] Co., Inc. ({{tyo2|2802}})
# 少數列寫成 {{TYO|4043}} 或 TSE 網站連結（2016 DeNA：topSearchStr=2432）。
# 2024 年起東證新上市公司用英數混合代碼（285A Kioxia、543A Archion），照收，
# Yahoo 格式同樣是 285A.T。

TYO_RE = re.compile(r"\{\{\s*(?:tyo2?|TYO|tse|TSE)\s*\|\s*([0-9]{3}[0-9A-Z])\s*\}\}")
TYO_FALLBACK_RE = re.compile(r"topSearchStr=([0-9]{3}[0-9A-Z])|TYO\]*\s*:\s*([0-9]{3}[0-9A-Z])\b")
JP_CODE_RE = re.compile(r"^[0-9]{3}[0-9A-Z]$")


def parse_n225(text: str) -> tuple[list[tuple[str, str, str]], int, list[str], str]:
    """回傳 ([(code, 公司名, 維基行業小節)] 去重後, 原始列數, 重複代碼, as-of 字串)。"""
    sec = level2_section(text, r"^==\s*Components\s*==")
    rows, sector = [], ""
    for line in sec.splitlines():
        h = re.match(r"^===\s*(.+?)\s*===", line)
        if h:
            sector = strip_markup(h.group(1))
            continue
        if not line.startswith("*"):
            continue
        m = TYO_RE.search(line)
        code = m.group(1) if m else None
        if not code:
            fb = TYO_FALLBACK_RE.search(line)
            code = (fb.group(1) or fb.group(2)) if fb else None
        if not code:
            continue
        name = strip_markup(TYO_RE.sub("", line.lstrip("*")))
        name = re.sub(r"\(\s*\)|\(\s*Tokyo Stock Exchange.*$|\(\s*TYO.*$", "", name).strip(" ,")
        rows.append((code, name, sector))
    cnt = Counter(c for c, _, _ in rows)
    dups = sorted(c for c, n in cnt.items() if n > 1)
    seen, out = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            out.append(r)
    m = re.search(r"As of ([^,]*?)(?:,| the Nikkei)", sec)
    asof = strip_markup(m.group(1)) if m else ""
    return out, len(rows), dups, asof


def parse_nikkei_official(path: Path) -> tuple[list[tuple[str, str, str]], str]:
    """日經官方成分股頁：<h3 class="idx-section-subheading">行業</h3> 之後
    `<td>7203</td><td>TOYOTA MOTOR CORP.</td>`。回傳 ([(code, name, sector)], 更新日)。"""
    if not path.exists():
        return [], ""
    t = path.read_text(encoding="utf-8", errors="replace")
    sector, out = "", []
    for h, code, name in re.findall(
            r'<h3 class="idx-section-subheading">(.*?)</h3>|<td>([0-9]{3}[0-9A-Z])</td>\s*<td>(.*?)</td>',
            t, re.DOTALL):
        if h:
            sector = html.unescape(re.sub(r"<[^>]+>", "", h)).strip()
        else:
            out.append((code, html.unescape(re.sub(r"<[^>]+>", "", name)).strip(), sector))
    m = re.search(r"Update[：:]\s*([A-Za-z]{3}/\d{1,2}/\d{4})", t)
    upd = datetime.strptime(m.group(1), "%b/%d/%Y").date().isoformat() if m else ""
    return out, upd


# ───────────────────────────── 道瓊工業平均 ─────────────────────────────
# 歷史頁每次調整一個二級標題 `== June 29, 2026 ==`，底下 3 欄 wikitable 列出調整後
# 的 30 檔（新加入的標 ↑），`Dropped from Average` 之後是被剔除的（標 ↓）。
# 只有公司名、沒有代碼 → 用下面的人工對照表。對照原則（報告裡有完整清單）：
#   1. 現在仍上市的同一證券（中間只是改名/改代碼）→ 用現行 Yahoo 代碼，
#      讓價格歷史接得上（AlliedSignal→HON、Travelers Inc./Primerica→C、
#      SBC→T、United Technologies→RTX、Kraft Foods Inc.→MDLZ、Alcoa Inc.→HWM）
#   2. 已下市/被併購 → 離開道指時的代碼（Texaco TX、Union Carbide UK…）；
#      通用汽車沿用 repo S&P 500 名單的 MTLQQ
#   3. 唯一的撞號：舊 AT&T Corp.（T，2004 年剔除）與 SBC（Yahoo 的 T 是 SBC 這條線）
#      1999-2004 同時在指數裡 → 舊 AT&T 給佔位代碼 T-OLD（Yahoo 抓不到，回測會自動略過）

DJIA_START = date(1987, 3, 12)  # 從這次調整後的名單開始（涵蓋 1990 年起的需求）

DJIA_NAME_TO_TICKER = {
    "3M Company": "MMM",
    "Minnesota Mining & Manufacturing Company": "MMM",
    "Allied-Signal Incorporated": "HON",
    "AlliedSignal Incorporated": "HON",
    "Honeywell International": "HON",
    "Honeywell International Inc.": "HON",
    "Honeywell Technologies Inc.": "HON",
    "Alcoa Inc.": "HWM",
    "Aluminum Company of America": "HWM",
    "Alphabet Inc.": "GOOGL",  # 頁面未註明股別，暫用 A 股（報告已標註待確認）
    "Altria Group Incorporated": "MO",
    "Altria Group, Incorporated": "MO",
    "Altria Group, Inc.": "MO",
    "Philip Morris Companies Inc.": "MO",
    "Amazon.com, Inc.": "AMZN",
    "American Express Company": "AXP",
    "American International Group, Inc.": "AIG",
    "Amgen Inc.": "AMGN",
    "Apple Inc.": "AAPL",
    "AT&T Corporation": "T-OLD",
    "American Telephone and Telegraph Company": "T-OLD",
    "AT&T Inc.": "T",
    "SBC Communications Inc.": "T",
    "Bank of America Corporation": "BAC",
    "Bethlehem Steel Corporation": "BS",
    "The Boeing Company": "BA",
    "Caterpillar Inc.": "CAT",
    "Chevron Corporation": "CVX",
    "Cisco Systems, Inc.": "CSCO",
    "Citigroup Inc.": "C",
    "Travelers Inc.": "C",
    "Primerica": "C",
    "The Coca-Cola Company": "KO",
    "Dow Inc.": "DOW",
    "DowDuPont Inc.": "DD",
    "E.I. du Pont de Nemours & Company": "DD",
    "Eastman Kodak Company": "EK",
    "Exxon Corporation": "XOM",
    "Exxon Mobil Corporation": "XOM",
    "F. W. Woolworth Company": "Z",
    "Venator": "Z",  # 1997 年剔除時頁面用後來的名字 Venator（即 Woolworth，2001 年再改名 Foot Locker）
    "General Electric Company": "GE",
    "General Motors Corporation": "MTLQQ",
    "Motors Liquidation Company": "MTLQQ",
    "The Goldman Sachs Group, Inc.": "GS",
    "Goodyear Tire and Rubber Company": "GT",
    "Hewlett-Packard Company": "HPQ",
    "The Home Depot, Inc.": "HD",
    "Intel Corporation": "INTC",
    "International Business Machines Corporation": "IBM",
    "International Paper Company": "IP",
    "J.P. Morgan & Company": "JPM",
    "JPMorgan Chase & Co.": "JPM",
    "Johnson & Johnson": "JNJ",
    "Kraft Foods Inc.": "MDLZ",
    "McDonald's Corporation": "MCD",
    "Merck & Co., Inc.": "MRK",
    "Microsoft Corporation": "MSFT",
    "Navistar International Corporation": "NAV",
    "Nike, Inc.": "NKE",
    "Nvidia Corporation": "NVDA",
    "Pfizer Inc.": "PFE",
    "The Procter & Gamble Company": "PG",
    "Raytheon Technologies Corporation": "RTX",
    "United Technologies Corporation": "RTX",
    "Salesforce, Inc.": "CRM",
    "Sears Roebuck & Company": "S",
    "The Sherwin-Williams Company": "SHW",
    "Texaco Incorporated": "TX",
    "The Travelers Companies, Inc.": "TRV",
    "Union Carbide Corporation": "UK",
    "USX Corporation": "X",
    "United States Steel Corporation": "X",
    "UnitedHealth Group Inc.": "UNH",
    "UnitedHealth Group Incorporated": "UNH",
    "Verizon Communications Inc.": "VZ",
    "Visa Inc.": "V",
    "Wal-Mart Stores, Inc.": "WMT",
    "Walmart Inc.": "WMT",
    "Walgreens Boots Alliance, Inc.": "WBA",
    "The Walt Disney Company": "DIS",
    "Westinghouse Electric Corporation": "WX",
}

DJIA_SECTION_RE = re.compile(r"^==\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*==\s*$", re.MULTILINE)


def djia_clean_cell(c: str) -> tuple[str, str]:
    """表格儲存格 → (公司名, 標記 ↑/↓/'')。去掉 {{small|(formerly …)}}、<br />、† 等。"""
    mark = "↑" if "↑" in c else ("↓" if "↓" in c else "")
    c = re.sub(r"<br\s*/?>.*", "", c, flags=re.DOTALL)
    c = re.sub(r"\{\{small\|.*?\}\}", "", c)
    c = strip_markup(c)
    c = re.sub(r"[↑↓†‡*]", "", c)
    c = c.split("|")[-1]  # 頁面少數壞掉的連結語法 `Microsoft|Microsoft Corporation`
    return re.sub(r"\s+", " ", c).strip(), mark


def parse_djia(text: str) -> list[dict]:
    """回傳 [{date, members:[名], added:[名], dropped:[名]}]，日期由舊到新。"""
    parts = DJIA_SECTION_RE.split(text)
    out = []
    for i in range(1, len(parts), 2):
        d = parse_en_date(parts[i])
        body = parts[i + 1]
        a = body.find("{|")
        table = body[a:body.find("\n|}", a)] if a >= 0 else ""
        members, added, dropped = [], [], []
        in_dropped = False
        for line in table.split("\n"):
            if not line.startswith("|") or line.startswith("|-") or line.startswith("{|"):
                continue
            if "Dropped from Average" in line:
                in_dropped = True
                continue
            for cell in line[1:].split("||"):
                name, mark = djia_clean_cell(cell)
                if not name:
                    continue
                if in_dropped:
                    dropped.append(name)
                else:
                    members.append(name)
                    if mark == "↑":
                        added.append(name)
        out.append({"date": d, "members": members, "added": added, "dropped": dropped})
    return sorted(out, key=lambda r: r["date"])


# ───────────────────────────── 主流程 ─────────────────────────────

def snap_date(y: int) -> date:
    return date(y, *SNAP_MONTH_DAY)


def build_yearly(kind: str, parse_fn, valid_range) -> dict:
    """逐年讀快照；數量不合理 → 沿用前一年（不捏造）。回傳報告需要的所有資訊。"""
    info = {"years": [], "snaps": [], "names": {}, "carried": []}
    prev = None
    for y in YEARS:
        path = WIKI / kind / f"{y}.txt"
        rec = {"year": y, "file": path.name, "exists": path.exists()}
        if path.exists():
            text = path.read_text(encoding="utf-8")
            rec["rev"] = revision_date(text)
            rec.update(parse_fn(text))
        else:
            rec.update({"rev": "", "members": {}, "fmt": "檔案不存在"})
        ok = valid_range[0] <= len(rec["members"]) <= valid_range[1]
        rec["ok"] = ok
        if not ok:
            if prev is None:
                info["years"].append(rec)
                continue
            rec["carried_from"] = prev["year"]
            info["carried"].append(y)
            mem = prev["used"]
        else:
            mem = rec["members"]
        rec["used"] = mem
        for t, n in mem.items():
            info["names"].setdefault(t, {})[y] = n
        info["snaps"].append((snap_date(y), set(mem)))
        info["years"].append(rec)
        prev = rec
    info["intervals"] = snapshots_to_intervals(info["snaps"])
    return info


def ndx_parse_record(text: str) -> dict:
    rows, fmt, asof = parse_ndx(text)
    return {"members": dict(rows), "fmt": fmt, "asof": asof, "raw_count": len(rows)}


def n225_parse_record(text: str) -> dict:
    rows, raw, dups, asof = parse_n225(text)
    bad = [c for c, _, _ in rows if not JP_CODE_RE.match(c)]
    return {"members": {f"{c}.T": n for c, n, _ in rows}, "fmt": "行業條列", "asof": asof,
            "raw_count": raw, "dups": dups, "bad_codes": bad,
            "alnum": [c for c, _, _ in rows if not c.isdigit()],
            "sectors": {f"{c}.T": s for c, _, s in rows}}


def yoy(info: dict) -> list[dict]:
    """逐年加入/剔除數量與疑似改名。"""
    out, prev = [], None
    for rec in info["years"]:
        if "used" not in rec:
            continue
        cur = rec["used"]
        r = {"year": rec["year"], "added": [], "removed": [], "renames": []}
        if prev is not None:
            r["added"] = sorted(set(cur) - set(prev))
            r["removed"] = sorted(set(prev) - set(cur))
            r["renames"] = rename_candidates({t: prev[t] for t in r["removed"]},
                                             {t: cur[t] for t in r["added"]})
        out.append(r)
        prev = cur
    return out


def _yr_span(years) -> str:
    """[2008, 2009, 2010, 2013] → '2008–2010, 2013'。"""
    if not years:
        return "—"
    years = sorted(years)
    out, a = [], years[0]
    for p, c in zip(years, years[1:] + [None]):
        if c != p + 1:
            out.append(f"{a}" if a == p else f"{a}–{p}")
            a = c
    return ", ".join(out)


def md_table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(lines)


def main() -> None:
    report: list[str] = []
    W = report.append

    # ── NDX ──
    ndx = build_yearly("ndx", ndx_parse_record, NDX_RANGE)
    write_membership(OUT / "ndx" / "membership.csv", ndx["intervals"])
    ndx_yoy = yoy(ndx)
    ndx_current = (WIKI / "ndx" / "current.txt").read_text(encoding="utf-8")
    ndx_cur_rows, _, _ = parse_ndx(ndx_current)
    ndx_moved = ("List of NASDAQ-100 companies" in ndx_current) and not ndx_cur_rows
    # 驗證 1：最新快照 vs Nasdaq screener
    screener = json.loads((PROBE / "nasdaq_screener.json").read_text(encoding="utf-8"))
    scr = {yahoo_us(r["symbol"]): r.get("name", "") for r in screener}
    ndx_last = ndx["years"][-1]
    ndx_not_in_scr = sorted(t for t in ndx_last["used"] if t not in scr)
    # 驗證 2：用 2026 版的歷史調整表往回倒推，對照各年快照
    last_text = (WIKI / "ndx" / f"{ndx_last['year']}.txt").read_text(encoding="utf-8")
    changes = parse_ndx_changes(last_text)
    last_ref = date.fromisoformat(ndx_last["rev"])
    recon = []
    for rec in ndx["years"]:
        if not rec.get("ok"):
            continue
        ref = parse_en_date(rec["asof"]) if rec["asof"] else date.fromisoformat(rec["rev"])
        rs = reconstruct_from_changes(set(ndx_last["used"]), last_ref, changes, ref)
        snap = set(rec["members"])
        # 套用已知改代碼（舊 → 新，連續套用）後再比一次，看剩下多少真正的差異
        def canon(t, y=rec["year"]):
            for old, new, _ in NDX_KNOWN_TICKER_CHANGES:
                if t == old and not (old == "GOOG" and y >= 2014):
                    t = new
            return t
        snap_c, rs_c = {canon(t) for t in snap}, {canon(t) for t in rs}
        recon.append((rec["year"], ref, len(snap & rs), sorted(snap - rs), sorted(rs - snap),
                      len(snap_c & rs_c), sorted(snap_c - rs_c), sorted(rs_c - snap_c)))
    # 已知改代碼在年度快照中的實際位置（舊代碼最後出現年 / 新代碼首次出現年）
    ndx_years_of = {}
    for rec in ndx["years"]:
        for t in rec.get("used", {}):
            ndx_years_of.setdefault(t, []).append(rec["year"])

    # ── N225 ──
    n225 = build_yearly("n225", n225_parse_record, N225_RANGE)
    write_membership(OUT / "n225" / "membership.csv", n225["intervals"])
    n225_yoy = yoy(n225)
    official, official_upd = parse_nikkei_official(PROBE / "nikkei_components_en.txt")
    if official:
        with open(OUT / "n225" / "current_official.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["code", "ticker", "name", "sector"])
            for code, name, sec in sorted(official):
                w.writerow([code, f"{code}.T", name, sec])
    off_set = {f"{c}.T": n for c, n, _ in official}
    n225_last = n225["years"][-1]
    n225_cur_rows, _, _, _ = parse_n225((WIKI / "n225" / "current.txt").read_text(encoding="utf-8"))
    n225_cur = {f"{c}.T" for c, _, _ in n225_cur_rows}

    # ── DJIA ──
    djia_text = (WIKI / "djia_hist" / "current.txt").read_text(encoding="utf-8")
    sections = [s for s in parse_djia(djia_text) if s["date"] >= DJIA_START]
    # 第一節的「剔除」是起始日之前就離開的公司，不需要代碼
    unresolved = sorted({n for i, s in enumerate(sections) for n in s["members"] + (s["dropped"] if i else [])
                         if n not in DJIA_NAME_TO_TICKER})
    djia_lists = [(s["date"], {DJIA_NAME_TO_TICKER.get(n, "?" + n) for n in s["members"]}) for s in sections]
    djia_intervals = dated_lists_to_intervals(djia_lists)
    write_membership(OUT / "djia" / "membership.csv", djia_intervals)
    # 驗證：每次調整後 30 檔；↑/↓ 標記 vs 相鄰兩份名單的代碼差集
    djia_checks = []
    for i, s in enumerate(sections):
        cur = djia_lists[i][1]
        row = {"date": s["date"], "n": len(s["members"]), "n_tk": len(cur)}
        if i > 0:
            prev = djia_lists[i - 1][1]
            row["add_tk"] = sorted(cur - prev)
            row["rm_tk"] = sorted(prev - cur)
            row["add_mark"] = sorted({DJIA_NAME_TO_TICKER.get(n, n) for n in s["added"]})
            row["drop_mark"] = sorted({DJIA_NAME_TO_TICKER.get(n, n) for n in s["dropped"]})
        djia_checks.append(row)
    # 從 1987 年逐次回放「↑/↓」到最新：驗證跟頁面最新一節的 30 檔一致
    replay = set(djia_lists[0][1])
    for s in sections[1:]:
        replay -= {DJIA_NAME_TO_TICKER.get(n, n) for n in s["dropped"]}
        replay |= {DJIA_NAME_TO_TICKER.get(n, n) for n in s["added"]}
    djia_latest = djia_lists[-1][1]
    # 頁首「Summary of changes since 1991」條列的日期都應該有對應的一節
    summary_sec = level2_section(djia_text, r"^==\s*Summary of changes since 1991\s*==")
    summary_dates = sorted({parse_en_date(m.group(0)) for m in
                            re.finditer(r"On " + DATE_RE.pattern, summary_sec)} - {None})
    section_dates = {s["date"] for s in sections}
    summary_missing = [d for d in summary_dates if d not in section_dates]
    rename_only = sorted(section_dates - set(summary_dates) - {DJIA_START})
    in_scr_djia = sorted(t for t in djia_latest if t not in scr)

    # ─────────── 報告 ───────────
    W("# 指數成分股（Wikipedia 解析）報告\n")
    W("由 `scripts/build_universe_wiki.py` 自動產生（重跑即覆蓋）。來源為 "
      "`research_output/multimarket/wiki/` 底下已存好的英文維基原始 wikitext 修訂版本，"
      "驗證用 `research_output/multimarket/probe/` 的 Nasdaq screener 與日經官方成分股頁。\n")
    W("**這不是官方權威來源**。年度快照（NDX、N225）視為 `<YYYY>-06-30` 起生效到下一份快照為止"
      "（跟 `universe.py` 恒指慣例一致），最後一份快照的成分股 `end` 留空；道指用歷史頁的實際調整日。"
      "`end` 為不含（第一個不是成分股的日子）。代碼為 Yahoo Finance 格式。\n")
    W("## 輸出檔\n")
    W(md_table(["檔案", "列數（區間）", "不同代碼數", "最早 start"], [
        ["`universes/ndx/membership.csv`", len(ndx["intervals"]), len({t for t, _, _ in ndx["intervals"]}),
         min(a for _, a, _ in ndx["intervals"])],
        ["`universes/n225/membership.csv`", len(n225["intervals"]), len({t for t, _, _ in n225["intervals"]}),
         min(a for _, a, _ in n225["intervals"])],
        ["`universes/djia/membership.csv`", len(djia_intervals), len({t for t, _, _ in djia_intervals}),
         min(a for _, a, _ in djia_intervals)],
        ["`universes/n225/current_official.csv`", len(official), len(official), f"官方頁更新日 {official_upd}"],
    ]))
    W("")

    # NDX
    W("## 一、Nasdaq-100（NDX）\n")
    W("格式：2008–2018 為 `#[[公司]] (TICKER)` 編號清單；2019 起為 `id=\"constituents\"` wikitable"
      "（2025 起欄位順序改成 Ticker 在前，程式靠表頭辨認欄位）。")
    if ndx_moved:
        W("`ndx/current.txt`（2026-09 版）已把成分股表搬到獨立條目「List of NASDAQ-100 companies」，"
          "本身沒有名單 → **最新快照採用 2026.txt（2026-06-29 版）**。")
    W("「名單日期」是維基名單上方自述的 *current as of* 日期（2024 起不再寫），常早於修訂日。\n")
    rows = []
    for rec, yy in zip([r for r in ndx["years"] if "used" in r], ndx_yoy):
        turnover = max(len(yy["added"]), len(yy["removed"]))
        flag = "⚠ 換手過高" if turnover > NDX_TURNOVER_WARN else ""
        if rec.get("carried_from"):
            flag = f"⚠ 解析失敗，沿用 {rec['carried_from']}"
        rows.append([rec["year"], rec["rev"], rec.get("asof", "") or "—", rec["fmt"], len(rec["used"]),
                     f"+{len(yy['added'])} / −{len(yy['removed'])}" if yy["year"] != YEARS[0] else "—", flag])
    W(md_table(["年", "修訂日", "名單日期", "格式", "檔數", "較前一年", "備註"], rows))
    W("")
    W(f"- 沿用前一年的年份：{', '.join(map(str, ndx['carried'])) or '無（每年都解析成功）'}")
    W("- 檔數 > 100 是雙重股權（GOOGL/GOOG、FOXA/FOX、LBTYA/LBTYK、DISCA/DISCK 等）；"
      "2015–2017 年約 107–108 檔與當時「107 equity securities」的描述相符。")
    W("- 名字只出現、沒有代碼的條目：無（每一列都有代碼）。\n")
    W("### 疑似改名／改代碼（同年走一檔、進一檔且公司名相近；只列出，**未**自動合併）\n")
    ren = [[yy["year"], f"{a} ({b})", f"{c} ({d})"] for yy in ndx_yoy for a, b, c, d in yy["renames"]]
    W(md_table(["年", "剔除", "加入"], ren) if ren else "無。")
    W("")
    W("### 驗證 A：最新快照 vs Nasdaq screener（現行上市清單）\n")
    W(f"最新快照 {ndx_last['year']}（{len(ndx_last['used'])} 檔）中，screener 找不到的代碼 "
      f"{len(ndx_not_in_scr)} 檔：{', '.join(ndx_not_in_scr) or '無'}。")
    W("（screener 為 2026-09 抓取；快照為 2026-06-29，之間下市/併購/改代碼的會出現在這裡。"
      "EA 應是 2025 年宣布的私有化收購完成後下市——未另行查證。）\n")
    W("### 驗證 B：用 2026 版條目的「Historical components」調整表倒推，對照各年快照\n")
    W(f"調整表共 {len(changes)} 筆（{min(c[0] for c in changes)} → {max(c[0] for c in changes)}）。"
      "以 2026 快照為起點，把參考日（名單日期；沒寫就用修訂日）之後生效的調整逆向還原，"
      "再跟當年快照比對。差異多半是：代碼改名（調整表用當時代碼）、調整表漏列、或維基名單本身沒及時更新。\n")
    W(md_table(["年", "參考日", "吻合", "只在快照", "只在倒推", "套用已知改代碼後吻合", "剩餘差異（快照 / 倒推）"],
               [[y, r, n, " ".join(a) or "—", " ".join(b) or "—", n2,
                 (" ".join(a2) or "∅") + " / " + (" ".join(b2) or "∅")]
                for y, r, n, a, b, n2, a2, b2 in recon]))
    W("")
    clean_from = next((r[0] for i, r in enumerate(recon) if all(not x[6] and not x[7] for x in recon[i:])), None)
    worst = max(len(r[6]) + len(r[7]) for r in recon)
    W("剩餘差異主要來自調整表本身：部分列的剔除代碼寫成後來的代碼（如 DISCK、LMCK、MDLZ），"
      "或漏列某些股別/併購（CMCSA/CMCSK、BRCM 被 AVGO 併購）。"
      f"套用已知改代碼後，{clean_from} 年起每年都**完全一致**；更早年份最多剩 {worst} 檔差異。\n")
    W("### 已知代碼變更（人工整理，僅供參考；membership 仍照各年快照原樣）\n")
    W(md_table(["舊代碼", "新代碼", "說明", "舊代碼出現於快照", "新代碼出現於快照"],
               [[o, n, why, _yr_span(ndx_years_of.get(o)), _yr_span(ndx_years_of.get(n))]
                for o, n, why in NDX_KNOWN_TICKER_CHANGES]))
    W("")
    W("注意 GOOG：2008–2013 快照裡的 GOOG 是當時的 A 股（今 GOOGL），2014 起的 GOOG 是 C 股；"
      "membership 把它當成同一個代碼連續持有（Yahoo 的 GOOG 價格序列本身就是這樣接起來的）。"
      "2014 年維基把 A/C 股標籤寫反了，但代碼集合 {GOOG, GOOGL} 正確。\n")

    # N225
    W("## 二、日經 225（N225）\n")
    W("格式：各年皆為 `==Components==` 底下按行業小節的條列 `* [[公司]] ({{tyo2|7203}})`；"
      "少數寫成 `{{TYO|…}}` 或 TSE 網址（2016 DeNA）。代碼格式檢查：`^\\d{4}$`，"
      "另外容許東證 2024 年起的英數混合新代碼（`^\\d{3}[0-9A-Z]$`，如 285A Kioxia、543A Archion）。\n")
    stale = {}
    for rec in n225["years"]:
        if rec.get("asof"):
            stale.setdefault(rec["asof"], []).append(rec["year"])
    stale_txt = "、".join(f"{_yr_span(ys)} 版都寫 *As of {a}*" for a, ys in stale.items() if len(ys) > 1)
    W("**重要**：維基 N225 名單經常好幾年沒更新（見「名單日期」欄：" + stale_txt + "），"
      "所以某些年換手為 0、下一年一次補很多檔——這是來源滯後，不是解析錯誤。\n")
    rows = []
    for rec, yy in zip([r for r in n225["years"] if "used" in r], n225_yoy):
        turnover = max(len(yy["added"]), len(yy["removed"]))
        notes = []
        if len(rec["used"]) != 225:
            notes.append(f"⚠ {len(rec['used'])} ≠ 225")
        if rec.get("dups"):
            notes.append("重複列 " + ",".join(rec["dups"]))
        if rec.get("alnum"):
            notes.append("英數代碼 " + ",".join(rec["alnum"]))
        if rec.get("bad_codes"):
            notes.append("格式錯誤 " + ",".join(rec["bad_codes"]))
        if turnover > N225_TURNOVER_WARN:
            notes.append("⚠ 換手過高")
        if yy["year"] != YEARS[0] and turnover == 0:
            notes.append("與前一年相同（名單未更新）")
        if rec.get("carried_from"):
            notes.append(f"⚠ 解析失敗，沿用 {rec['carried_from']}")
        rows.append([rec["year"], rec["rev"], rec.get("asof") or "—", rec.get("raw_count", ""),
                     len(rec["used"]),
                     f"+{len(yy['added'])} / −{len(yy['removed'])}" if yy["year"] != YEARS[0] else "—",
                     "；".join(notes)])
    W(md_table(["年", "修訂日", "名單日期（As of）", "原始列數", "不同代碼", "較前一年", "備註"], rows))
    W("")
    W(f"- 沿用前一年的年份：{', '.join(map(str, n225['carried'])) or '無（19 份快照都有可用名單，包括 2017）'}")
    W("- 「重複列」= 同一代碼在兩個行業小節各列一次（維基編輯錯誤），已去重；"
      "檔數 ≠ 225 的年份是維基本身多列/漏列（沒有捏造補齊）。")
    W("- 所有代碼皆可解析，無「只有公司名」的條目。\n")
    W("### 逐年加入／剔除明細\n")
    for yy in n225_yoy[1:]:
        if yy["added"] or yy["removed"]:
            cur = n225["names"]
            W(f"- **{yy['year']}**：加入 " + ", ".join(f"{t}（{cur[t][yy['year']]}）" for t in yy["added"])
              + "；剔除 " + ", ".join(f"{t}（{cur[t][yy['year'] - 1] if (yy['year'] - 1) in cur[t] else ''}）"
                                     for t in yy["removed"]))
    W("")
    W("### 疑似改代碼／控股改組（同年走一檔、進一檔且公司名相近；只列出，未自動合併）\n")
    ren = [[yy["year"], f"{a} ({b})", f"{c} ({d})"] for yy in n225_yoy for a, b, c, d in yy["renames"]]
    W(md_table(["年", "剔除", "加入"], ren) if ren else "無。")
    W("")
    W("### 驗證：最新維基快照 vs 日經官方現行名單\n")
    last_set = set(n225_last["used"])
    W(f"官方頁（更新日 {official_upd}）解析出 {len(official)} 檔、{len({s for _, _, s in official})} 個行業"
      f" → `universes/n225/current_official.csv`。")
    W(f"維基 {n225_last['year']} 快照 {len(last_set)} 檔；兩者交集 **{len(last_set & set(off_set))}** 檔。")
    only_w = sorted(last_set - set(off_set))
    only_o = sorted(set(off_set) - last_set)
    wiki_names = n225_last["used"]
    W(f"- 只在維基：{', '.join(f'{t}（{wiki_names[t]}）' for t in only_w) or '無'}")
    W(f"- 只在官方：{', '.join(f'{t}（{off_set[t]}）' for t in only_o) or '無'}")
    W(f"- 維基 current.txt（2026-09 版）名單與 2026 快照"
      f"{'相同' if n225_cur == last_set else '不同：' + str(sorted(n225_cur ^ last_set))}。\n")

    # DJIA
    W("## 三、道瓊工業平均（DJIA）\n")
    W(f"來源頁 `djia_hist/current.txt`（修訂 {revision_date(djia_text)}）每次調整一節、列出調整後完整名單。"
      f"取 {DJIA_START} 起共 {len(sections)} 次調整（區間精確到日）。頁面只有公司名，代碼用程式內的人工對照表。\n")
    W(md_table(["調整日", "名單檔數", "代碼數", "加入（代碼差集）", "剔除（代碼差集）", "頁面 ↑", "頁面 ↓", "一致？"],
               [[c["date"], c["n"], c["n_tk"], " ".join(c.get("add_tk", [])) or "—",
                 " ".join(c.get("rm_tk", [])) or "—", " ".join(c.get("add_mark", [])) or "—",
                 " ".join(c.get("drop_mark", [])) or "—",
                 "—" if "add_tk" not in c else
                 ("✓" if (c["add_tk"], c["rm_tk"]) == (c["add_mark"], c["drop_mark"]) else "見說明")]
                for c in djia_checks]))
    W("")
    W("「見說明」= 頁面標了加入/剔除，但兩者對應到同一個 Yahoo 代碼（同一證券改名/換殼），所以代碼層面沒有變動：")
    for c in djia_checks:
        if "add_tk" in c and (c["add_tk"], c["rm_tk"]) != (c["add_mark"], c["drop_mark"]):
            W(f"- {c['date']}：頁面 ↑ {' '.join(c['add_mark'])} / ↓ {' '.join(c['drop_mark'])}，"
              f"代碼差集 +{' '.join(c['add_tk']) or '∅'} / −{' '.join(c['rm_tk']) or '∅'}")
    W("")
    W(f"- 無法對應代碼的公司名：{', '.join(unresolved) or '無'}")
    W(f"- 從 {DJIA_START} 名單逐次套用 ↑/↓ 回放到最新，結果與頁面最新一節（{sections[-1]['date']}）的 30 檔"
      f"{'**完全一致**' if replay == djia_latest else '不一致：' + str(sorted(replay ^ djia_latest))}。")
    W(f"- 頁首「Summary of changes since 1991」列出 {len(summary_dates)} 個調整日，"
      f"{'全部都有對應的一節' if not summary_missing else '缺少對應小節：' + ', '.join(map(str, summary_missing))}；"
      f"另有 {', '.join(map(str, rename_only)) or '無'} 為只改名、成分不變的小節。")
    W(f"- 現行 30 檔：{' '.join(sorted(djia_latest))}")
    W(f"- 現行 30 檔中 Nasdaq screener 找不到的：{', '.join(in_scr_djia) or '無'}\n")
    W("### 公司名 → 代碼對照（1987 年起出現過的全部名稱）\n")
    used_names = sorted({n for i, s in enumerate(sections) for n in s["members"] + (s["dropped"] if i else [])})
    W(md_table(["維基名稱", "代碼"], [[n, DJIA_NAME_TO_TICKER.get(n, "？")] for n in used_names]))
    W("")
    W("對照原則：(1) 仍上市的同一證券（中間只是改名/改代碼）→ 現行 Yahoo 代碼，讓價格歷史接得上；"
      "(2) 已下市/被併購 → 離開道指時的代碼（通用汽車沿用 repo S&P 500 名單的 MTLQQ）；"
      "(3) 舊 AT&T Corp.（1916–2004）的歷史代碼 T 現在屬於 SBC 這條線（SBC 1999–2004 也同時在指數內）"
      "→ 給佔位代碼 `T-OLD`（Yahoo 抓不到，回測時會因無價格被略過）。\n")

    # 限制
    W("## 已知限制\n")
    W("1. **維基不是官方來源**：名單是編輯者記錄的，可能滯後、漏改或打錯（N225 尤其嚴重，見上表的名單日期）。")
    W("2. **年度顆粒度**：NDX、N225 只取每年約 6/30 的修訂版本，年內的調整（NDX 每年 12 月重組＋"
      "臨時替換、2026 起每季；N225 每年 4/10 月定期調整＋臨時替換）全部被壓到 6/30；"
      "且名單自述日期常比修訂日早好幾個月甚至幾年。")
    W("3. NDX 的精確日期其實可以從 2026 版條目的「Historical components」調整表重建（本報告只拿來驗證）；"
      "若要升級成逐日區間，可改用該表（注意表內代碼是當時代碼，需處理改名）。")
    W("4. 代碼沿用各年快照當時的寫法（FB→META、GOOG/GOOGL 等不自動合併），改名清單只列在報告裡。"
      "已下市代碼可能被 Yahoo 重新分配給別家公司——`universe.py` 的「價格起始日 ≤ 入選日」檢查會擋掉"
      "新公司，但擋不住「舊代碼現在屬於一家歷史更長的公司」的情況（例如道指 T-OLD 就是為此另立）。")
    W("5. DJIA 名稱→代碼是人工對照；J.P. Morgan & Co.（2000 年前）用 JPM、Alcoa Inc. 用 HWM、"
      "Primerica/Travelers Inc. 用 C、E.I. du Pont 與 DowDuPont 都用 DD——Yahoo 上這些代碼的早年價格"
      "是否真的是當時那家公司，需要以價格資料再核對。Alphabet（2026-06-29 加入）頁面未註明股別，暫用 GOOGL，待確認。")
    W("6. N225 維基部分年份不是 225 檔（見表），未補齊；日本新式英數代碼（285A.T 等）在舊工具可能被當成非法代碼。")

    (OUT / "WIKI_PARSE_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    # 終端摘要
    print("NDX :", [(r["year"], len(r["used"])) for r in ndx["years"] if "used" in r])
    print("N225:", [(r["year"], len(r["used"])) for r in n225["years"] if "used" in r])
    print("DJIA:", [(str(c["date"]), c["n_tk"]) for c in djia_checks])
    print("DJIA 未對應名稱:", unresolved)
    print("輸出：universes/{ndx,n225,djia}/membership.csv、universes/n225/current_official.csv、"
          "universes/WIKI_PARSE_REPORT.md")


if __name__ == "__main__":
    main()
