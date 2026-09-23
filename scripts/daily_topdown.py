#!/usr/bin/env python3
"""每日由上而下股票分析：國家（指數 ETF）→ 個股 200 日線 → 新高 → 按板塊統計。

    python3 scripts/sector_rotation.py --index hsi     # 先更新三地板塊指數（group_index.csv，給板塊動能欄）
    python3 scripts/sector_rotation.py --index sp500
    python3 scripts/sector_rotation.py --index n225
    python3 scripts/daily_topdown.py                   # -> analysis/

**定位**：描述性篩選，**不是**預先登記、回測過的交易訊號。規則全部寫死在下面（RULES），
不按每天的結果調——要改規則先改這裡並寫進 commit 訊息。每天的新高名單記進
analysis/topdown_log.csv，累積幾個月就是真正的樣本外紀錄，可以事後誠實評估這套篩選有沒有用。

流程（寫死的規則，2026-09-23 使用者指定）：
1. **國家**：港股 2800.HK、美股 SPY、日股 EWJ（美元計；未有數據時退回 1321.T 日圓計）。
   動能分數 = 3/6/12 個月總報酬平均，只排名、**不篩選**（三地全部往下做）。
2. **個股 200 日線**：各地指數現任 point-in-time 成分股，最新收市（亞洲早上跑 = 昨天收市）
   在 200 日均線之上的留下。
3. **新高**：留下的股票，昨天收市價是否**嚴格高於**過去 3／6／9／12 個月（連昨天 63／126／189／252 個交易日）
   的**盤中最高價**（2026-09-23 使用者指定，跟報價頁「52 週高」同一把尺；原始價，不按股息還原）；
   至少創 3 個月新高的留下（12 個月新高必然也是 9／6／3 個月新高，分層計數）。
4. **按板塊統計**：留下的股票按 yfinance 行業分組，報每個板塊的檔數（各新高窗口分開數），
   附板塊 6 個月超額動能排名（sector_rotation.py 的 PIT 等權行業指數）作參考。
200 日線與報酬用含股息還原收市（AdjClose，約等於富途「前復權」）；新高用原始最高價（跟報價頁一致）。
"""
import argparse
import bisect
import csv
import io
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
from universe import Universe  # noqa: E402

OUT = ROOT / "analysis"
SECTOR_DIR = ROOT / "sector"

# 國家 -> 指數、主 ETF、參考列
COUNTRIES = {
    "hk": {"zh": "港股", "index": "hsi", "etf": "2800.HK", "usd": "2800.HK", "refs": ["^HSI"]},
    "us": {"zh": "美股", "index": "sp500", "etf": "SPY", "usd": "SPY", "refs": ["QQQ", "DIA", "RSP"]},
    "jp": {"zh": "日股", "index": "n225", "etf": "1321.T", "usd": "EWJ", "refs": ["^N225"]},
}
REF_ZH = {"^HSI": "恒生指數", "QQQ": "Nasdaq-100", "DIA": "道指", "RSP": "S&P 500 等權",
          "^N225": "日經225", "1321.T": "日經225 ETF（日圓）", "EWJ": "MSCI 日本（美元）",
          "2800.HK": "盈富基金", "SPY": "S&P 500"}

RULES = {"trend_ma": 200, "sector_lookback": 126, "min_members": 3,
         "high_windows": (("3月", 63), ("6月", 126), ("9月", 189), ("12月", 252)), "keep_min_window": "3月"}

SECTOR_ZH = {
    "Financial Services": "金融", "Real Estate": "地產", "Utilities": "公用",
    "Technology": "科技", "Communication Services": "通訊/互聯網",
    "Consumer Cyclical": "非必需消費", "Consumer Defensive": "必需消費",
    "Energy": "能源", "Basic Materials": "原材料", "Industrials": "工業",
    "Healthcare": "醫療",
}


# ---------- 個別序列指標 ----------

def closes_upto(ticker: str, as_of: date) -> list[tuple[date, float]]:
    try:
        s = md.load_series(ticker)
    except (FileNotFoundError, StopIteration):
        return []
    return [(d, v[1]) for d, v in sorted(s.items()) if d <= as_of and v[1] > 0]


def ret(c: list[float], n: int, skip: int = 0) -> float | None:
    if len(c) < n + 1:
        return None
    return c[-1 - skip] / c[-1 - n] - 1


def ohlc_upto(ticker: str, as_of: date) -> tuple[list[tuple[date, float]], list[tuple[float, float]]]:
    """([(date, 還原收市)], [(原始收市, 原始最高價)])，對齊；給個股用（新高要用原始最高價）。"""
    try:
        rows = [r for r in md.load_ohlcv(ticker) if r["Date"] <= as_of and r["AdjClose"] > 0]
    except (FileNotFoundError, StopIteration):
        return [], []
    return ([(r["Date"], r["AdjClose"]) for r in rows],
            [(r["Close"], max(r["High"] or r["Close"], r["Close"])) for r in rows])


def metrics(rows: list[tuple[date, float]], hl: list[tuple[float, float]] | None = None) -> dict | None:
    if len(rows) < 64:
        return None
    c = [x for _, x in rows]
    m = {"last": rows[-1][0], "r1": ret(c, 21), "r3": ret(c, 63), "r6": ret(c, 126), "r12": ret(c, 252),
         "r12_1": ret(c, 252, skip=21)}
    m["ma50"] = sum(c[-50:]) / 50 if len(c) >= 50 else None
    m["ma200"] = sum(c[-200:]) / 200 if len(c) >= 200 else None
    m["vs200"] = c[-1] / m["ma200"] - 1 if m["ma200"] else None
    m["golden"] = m["ma50"] > m["ma200"] if m["ma50"] and m["ma200"] else None
    m["dd52"] = c[-1] / max(c[-252:]) - 1
    lr = [math.log(b / a) for a, b in zip(c[-64:], c[-63:])]
    mu = sum(lr) / len(lr)
    m["vol"] = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1) * 252)
    # 新高（2026-09-23 使用者指定，跟報價頁「52 週高」同一把尺）：昨天**收市價**嚴格高於之前 n−1 個交易日
    # （連昨天共 n 天 ≈ N 個月）的**盤中最高價**。用原始價（只按拆股還原、不按股息），跟富途/Yahoo 報價頁一致；
    # 歷史不足 n 天 = None（不算）
    if hl:
        rc, hi = [x for x, _ in hl], [y for _, y in hl]
        m["highs"] = {lab: (rc[-1] > max(hi[-n:-1]) if len(hl) >= n else None) for lab, n in RULES["high_windows"]}
        m["prior_high"] = {lab: max(hi[-n:-1]) if len(hl) >= n else None for lab, n in RULES["high_windows"]}
    else:
        m["highs"] = {lab: None for lab, _ in RULES["high_windows"]}
    moms = [m[k] for k in ("r3", "r6", "r12")]
    m["score"] = sum(moms) / 3 if all(x is not None for x in moms) else None
    return m


def disp(t: str) -> str:
    """顯示用代號：港股 2359.HK、美股 AMD、日股 4502.JP（內部/Yahoo 代號是 .T，只改顯示）。"""
    return t[:-2] + ".JP" if t.endswith(".T") else t


WEEKDAY_ZH = "一二三四五六日"


def keycap(n: int) -> str:
    """連續天數用數字 emoji：1️⃣…9️⃣、🔟；11 以上逐位拼（1️⃣1️⃣）。"""
    if n == 10:
        return "🔟"
    return "".join(f"{ch}\ufe0f\u20e3" for ch in str(n))


def fmt_d(d: date | None) -> str:
    """2026-09-18 週五——三地假期不同，日期一律帶星期。"""
    return f"{d} 週{WEEKDAY_ZH[d.weekday()]}" if d else "—"


_CAL: dict[str, dict[date, tuple[str, str]]] = {}


def holidays(market: str) -> dict[date, tuple[str, str]]:
    """三地官方休市日曆（universes/calendars/<market>.csv，scripts/build_market_calendars.py 產生）：
    {日期: (中文名, holiday 假期 / adhoc 臨時休市)}。"""
    if market not in _CAL:
        p = ROOT / "universes" / "calendars" / f"{market}.csv"
        _CAL[market] = {}
        if p.exists():
            with open(p, newline="", encoding="utf-8") as f:
                _CAL[market] = {date.fromisoformat(r["date"]): (r["name_zh"], r["kind"]) for r in csv.DictReader(f)}
    return _CAL[market]


def day_status(market: str, d: date, later_data: bool = False) -> str:
    """某市場某個平日為何沒有收市：休市（假期名）／臨時休市／有開市但數據未到（或缺失）。"""
    h = holidays(market).get(d)
    if h:
        return f"休市（{h[0]}）" if h[1] == "holiday" else f"臨時休市（{h[0]}）"
    if later_data:
        return "有開市但沒有數據（可能是颱風／黑雨等臨時休市，或數據缺失）"
    return "有開市，數據未到（下次更新會補上）"


def gap_note(last: date | None, as_of: date, market: str) -> str:
    """last 之後到 as_of 之間沒有收市的平日，逐日標明是休市還是數據未到。"""
    if not last:
        return ""
    miss, d = [], last + timedelta(days=1)
    while d <= as_of:
        if d.weekday() < 5:
            miss.append(f"{d.month}/{d.day} {day_status(market, d)}")
        d += timedelta(days=1)
    return f"（{'；'.join(miss)}）" if miss else ""


def pct(x: float | None, digits: int = 1, sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def short_name(name: str) -> str:
    for suf in (" Limited", " Ltd.", " Ltd", " Co., Ltd.", " Company", " Corporation", " Corp.", " Inc.",
                ", Inc.", " Holdings", " Group", " plc", " N.V.", " Incorporated", " (The)"):
        name = name.replace(suf, "")
    return name.strip(" ,")[:40]


def load_names(market: str) -> dict[str, str]:
    out = {}
    p = md.V2_DIR / market / "_names.json"
    if p.exists():
        out = {t: r.get("name", "") for t, r in json.loads(p.read_text(encoding="utf-8")).items()}
    if market == "jp":   # 日股用 JPX 官方日文名（漢字比英文好認）
        p = md.V2_DIR / "jp" / "_jpx_listed.json"
        if p.exists():
            for t, r in json.loads(p.read_text(encoding="utf-8")).get("listed", {}).items():
                if r.get("name"):
                    out[t] = r["name"].replace("　", " ")
    out = {t: short_name(n) for t, n in out.items()}
    if market == "hk":   # 港股用港交所官方中文簡稱（scripts/fetch_hkex_names.py），沒有才用英文名
        p = md.V2_DIR / "hk" / "_hkex_listed.json"
        if p.exists():
            for t, r in json.loads(p.read_text(encoding="utf-8")).get("listed", {}).items():
                if r.get("name_zh"):
                    out[t] = r["name_zh"]
    return out


# ---------- 板塊指數（sector_rotation.py 的輸出）----------

def load_group_index(index: str) -> tuple[list[date], dict[str, list[float | None]]]:
    p = SECTOR_DIR / index / "group_index.csv"
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.reader(f)
        head = next(rd)
        rows = list(rd)
    dates = [date.fromisoformat(r[0]) for r in rows]
    cols = {h: [float(r[i]) if r[i] else None for r in rows] for i, h in enumerate(head) if i}
    return dates, cols


def sector_table(index: str, as_of: date) -> tuple[date, list[dict]]:
    dates, cols = load_group_index(index)
    e = bisect.bisect_right(dates, as_of) - 1
    L = RULES["sector_lookback"]

    def r(k: str, n: int, end: int) -> float | None:
        s = end - n
        if s < 0 or cols[k][end] is None or cols[k][s] is None:
            return None
        return cols[k][end] / cols[k][s] - 1

    def ex(k: str, n: int, end: int) -> float | None:
        a, b = r(k, n, end), r("全體等權", n, end)
        return a - b if a is not None and b is not None else None

    out = []
    for k in cols:
        if not k.startswith("行業:"):
            continue
        lv = [x for x in cols[k][max(0, e - 199):e + 1] if x is not None]
        out.append({"key": k, "name": k.split(":", 1)[1], "ex1": ex(k, 21, e), "ex3": ex(k, 63, e),
                    "ex6": ex(k, L, e), "ex12": ex(k, 252, e), "ex6_prev": ex(k, L, e - 21),
                    "trend": cols[k][e] > sum(lv) / len(lv) if len(lv) == 200 and cols[k][e] else None})
    return dates[e], out


def rank_by(rows: list[dict], key: str) -> dict[str, int]:
    v = sorted((r[key], r["name"]) for r in rows if r[key] is not None and r.get("eligible", True))
    return {n: i + 1 for i, (_, n) in enumerate(reversed(v))}


# ---------- 每日新高名單（analysis/newhighs/，給其他分支/程式用）----------

LIST_ORDER = ["hk", "jp", "us"]          # 名單檔裡的市場順序：港股、日股、美股
LIST_FIELDS = ["date", "market", "market_zh", "window_months", "sector", "ticker", "name",
               "close", "prior_high", "pct_above_ma200", "yahoo_ticker"]


def write_newhigh_lists(end: date, n_days: int) -> list[date]:
    """重算 end（含）之前最近 n_days 個交易日的新高名單，每天一檔：
    analysis/newhighs/<收市日>.csv（機器讀）+ .md（人讀），並更新 summary.csv。
    規則同報告：point-in-time 成分股、當天收市在 200 日線上、收市價嚴格高於之前 N 個月盤中最高價。
    某市場當天休市（有當天價格的成分股不到一半）就不列該市場。只在內容有變時才寫檔。"""
    out_dir = OUT / "newhighs"
    out_dir.mkdir(parents=True, exist_ok=True)
    wins = [(lab, int(lab.rstrip("月"))) for lab, _ in reversed(RULES["high_windows"])]   # 12 → 3
    start = end - timedelta(days=max(40, n_days * 3))
    mk = {}
    for c in LIST_ORDER:
        uni = Universe(COUNTRIES[c]["index"])
        cache, first = {}, {}
        for t in uni.all_tickers(since=start):
            rows, hl = ohlc_upto(t, end)
            if rows:
                cache[t], first[t] = (rows, hl, [d for d, _ in rows]), rows[0][0]
        trading = set()
        cnt: dict[date, int] = {}
        for rows, _, ds in cache.values():
            for d in ds[bisect.bisect_left(ds, start):]:
                cnt[d] = cnt.get(d, 0) + 1
        for d, n in cnt.items():
            if d not in holidays(c) and n >= 0.5 * max(len(uni.eligible_at(d, first)), 1):
                trading.add(d)
        mk[c] = {"uni": uni, "cache": cache, "first": first, "trading": trading,
                 "sec": uni.sectors()[0], "names": load_names(uni.cfg["market"])}
    days = sorted(set().union(*(m["trading"] for m in mk.values())))[-n_days:]

    summ_path = out_dir / "summary.csv"
    summary = []
    if summ_path.exists():
        with open(summ_path, newline="", encoding="utf-8") as f:
            summary = [r for r in csv.DictReader(f) if date.fromisoformat(r["date"]) not in days]
    for D in days:
        recs, md_lines = [], [f"# 新高名單 {fmt_d(D)} 收市\n",
                              "當天收市在 200 日線上、且收市價**高於**之前 12／9／6／3 個月盤中最高價的指數成分股"
                              "（12 個月新高必然也列在 9／6／3 個月）。由 scripts/daily_topdown.py 產生；描述性篩選，非買入建議。\n"]
        for c in LIST_ORDER:
            m_ = mk[c]
            if D not in m_["trading"]:
                later = any(d > D for d in m_["trading"])
                md_lines.append(f"## {COUNTRIES[c]['zh']}\n\n{fmt_d(D)}：{day_status(c, D, later)}\n")
                continue
            ms = {}
            for t in m_["uni"].eligible_at(D, m_["first"]):
                rows, hl, ds = m_["cache"][t]
                i = bisect.bisect_right(ds, D)
                if i == 0 or ds[i - 1] != D:          # 當天停牌/沒數據
                    continue
                m = metrics(rows[max(0, i - 300):i], hl[max(0, i - 300):i])
                if m:
                    ms[t] = (m, hl[i - 1][0])
            above = {t for t, (m, _) in ms.items() if m["vs200"] is not None and m["vs200"] > 0}
            counts = {}
            md_lines.append(f"## {COUNTRIES[c]['zh']}（{m_['uni'].cfg['name']}：{len(ms)} 檔有收市價，200 日線上 {len(above)} 檔）\n")
            for lab, months in wins:
                hits = [t for t in above if ms[t][0]["highs"][lab]]
                counts[months] = len(hits)
                by_sec: dict[str, list[str]] = {}
                for t in hits:
                    by_sec.setdefault(sector_zh(m_["sec"], t), []).append(t)
                md_lines.append(f"### {months} 個月新高：{len(hits)} 檔\n")
                if not hits:
                    md_lines.append("（無）")
                for sec in sorted(by_sec, key=lambda k: (-len(by_sec[k]), k)):
                    md_lines.append(f"- **{sec}** {len(by_sec[sec])} 檔：" + "、".join(
                        f"{disp(t)} {m_['names'].get(t, '')}".strip() for t in sorted(by_sec[sec])))
                    for t in sorted(by_sec[sec]):
                        m, close = ms[t]
                        recs.append({"date": D.isoformat(), "market": c, "market_zh": COUNTRIES[c]["zh"],
                                     "window_months": months, "sector": sec, "ticker": disp(t),
                                     "name": m_["names"].get(t, ""), "close": f"{close:g}",
                                     "prior_high": f"{m['prior_high'][lab]:g}",
                                     "pct_above_ma200": f"{m['vs200'] * 100:.1f}", "yahoo_ticker": t})
                md_lines.append("")
            summary.append({"date": D.isoformat(), "market": c, "n_members": len(ms), "n_above_ma200": len(above),
                            **{f"n_{mo}m": counts[mo] for _, mo in wins}})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=LIST_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(recs)
        for path, text in ((out_dir / f"{D}.csv", buf.getvalue()), (out_dir / f"{D}.md", "\n".join(md_lines) + "\n")):
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
    summary.sort(key=lambda r: (r["date"], LIST_ORDER.index(r["market"])))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["date", "market", "n_members", "n_above_ma200", "n_12m", "n_9m", "n_6m", "n_3m"],
                       lineterminator="\n")
    w.writeheader()
    w.writerows(summary)
    summ_path.write_text(buf.getvalue(), encoding="utf-8")
    return days


# ---------- 主程式 ----------

def sector_zh(sec_map: dict[str, str], t: str) -> str:
    s = sec_map.get(t, "")
    return SECTOR_ZH.get(s, s or "未分類")


def ret_since(ticker: str, since: date, as_of: date) -> float | None:
    rows = closes_upto(ticker, as_of)
    ds = [d for d, _ in rows]
    i = bisect.bisect_right(ds, since) - 1
    if i < 0 or rows[-1][0] <= rows[i][0]:
        return None
    return rows[-1][1] / rows[i][1] - 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None,
                    help="報告日（預設今天，香港日期）；各市場取報告日之前的最新收市（= 昨天收市）")
    ap.add_argument("--list-days", type=int, default=5,
                    help="重算最近幾個交易日的新高名單（analysis/newhighs/；預設 5，補回補數據/遲到的收市）")
    args = ap.parse_args()
    report_day = args.as_of or date.today()
    # 用「昨天收市」：只取報告日之前的收市（早上跑本來就是這樣；白天手動跑也不會混進盤中價）
    as_of = report_day - timedelta(days=1)
    WIN = [lab for lab, _ in RULES["high_windows"]]
    SHOW = list(reversed(WIN))          # 顯示順序：12 → 9 → 6 → 3 個月（使用者指定）
    KEEP = RULES["keep_min_window"]

    def longest(m: dict) -> str:
        """創新高的最長窗口（顯示時每隻股票只列在這一格，不在較短窗口重複）。"""
        return next((lab for lab in SHOW if m["highs"][lab]), "")

    def streak(c: str, t: str) -> int:
        """連續第幾個交易日列在今天這個窗口（最長新高窗口相同、且在 200 日線上）；窗口改變就由 1 重新計。"""
        lab = longest(stocks[c][t])
        rows, hl = series_of[c][t]
        n = 0
        for i in range(len(rows) - 1, max(len(rows) - 120, 0), -1):
            m = metrics(rows[max(0, i - 300):i + 1], hl[max(0, i - 300):i + 1])
            if not m or m["vs200"] is None or m["vs200"] <= 0 or longest(m) != lab:
                break
            n += 1
        return n

    # --- 第一層：國家（只排名，不篩選）---
    country = {}
    for c, cfg in COUNTRIES.items():
        usd_t = cfg["usd"] if md.has_data(cfg["usd"]) else cfg["etf"]
        refs = {t: metrics(closes_upto(t, as_of)) for t in cfg["refs"] + ([cfg["etf"]] if usd_t != cfg["etf"] else [])}
        country[c] = {"ticker": usd_t, "m": metrics(closes_upto(usd_t, as_of)), "refs": refs,
                      "usd_note": "" if usd_t == cfg["usd"] else f"（{cfg['usd']} 尚無數據，暫用 {disp(cfg['etf'])} 本幣計）"}
    ranked = sorted(COUNTRIES, key=lambda c: -(country[c]["m"]["score"]
                                                 if country[c]["m"] and country[c]["m"]["score"] is not None else -9))

    # --- 第二、三層：個股 200 日線 → 新高 ---
    stocks: dict[str, dict[str, dict]] = {}
    series_of: dict[str, dict] = {}          # 每個市場每檔的 (還原收市, 原始收市/最高) 序列，算連續天數用
    sec_of: dict[str, dict[str, str]] = {}
    names: dict[str, dict[str, str]] = {}
    for c, cfg in COUNTRIES.items():
        uni = Universe(cfg["index"])
        first, data = {}, {}
        for t in uni.members_at(as_of):
            rows, hl = ohlc_upto(t, as_of)
            if rows:
                first[t], data[t] = rows[0][0], (rows, hl)
        stocks[c] = {t: m for t in uni.eligible_at(as_of, first) if (m := metrics(*data[t]))}
        series_of[c] = data
        sec_of[c] = uni.sectors()[0]
        names[c] = load_names(uni.cfg["market"])
        st = stocks[c]
        above = {t for t, m in st.items() if m["vs200"] is not None and m["vs200"] > 0}
        kept = {t for t in above if st[t]["highs"][KEEP]}
        # 該地「收市日」= 成分股最常見的最後日期（個別檔多一天/少一天不影響；早於它的列為落後）
        lasts = [m["last"] for m in st.values()]
        last = max(set(lasts), key=lambda d: (lasts.count(d), d)) if lasts else None
        country[c].update(n_members=len(st), n_ma=sum(m["vs200"] is not None for m in st.values()),
                          above=above, kept=kept, last=last,
                          stale=sorted(t for t, m in st.items() if last and m["last"] < last))

    # --- 板塊統計 + 板塊動能排名（參考）---
    sectors = {}
    for c, cfg in COUNTRIES.items():
        st = stocks[c]
        try:
            sd, srows = sector_table(cfg["index"], as_of)
        except FileNotFoundError:
            sd, srows = None, []
        size: dict[str, int] = {}
        for t in st:
            size[sector_zh(sec_of[c], t)] = size.get(sector_zh(sec_of[c], t), 0) + 1
        for r in srows:
            r["eligible"] = size.get(r["name"], 0) >= RULES["min_members"]
        mom_rank = rank_by(srows, "ex6")
        mom = {r["name"]: r for r in srows}
        table = []
        for name, n in size.items():
            mem = [t for t in st if sector_zh(sec_of[c], t) == name]
            ab = [t for t in mem if t in country[c]["above"]]
            row = {"name": name, "n": n, "above": len(ab),
                   "highs": {lab: sum(1 for t in ab if st[t]["highs"][lab]) for lab in WIN},   # 累計（記錄用）
                   "excl": {lab: sum(1 for t in ab if longest(st[t]) == lab) for lab in WIN},  # 只算最長窗口（顯示用）
                   "mom_rank": mom_rank.get(name), "ex6": mom.get(name, {}).get("ex6"), "n_rank": len(mom_rank)}
            table.append(row)
        table.sort(key=lambda r: (*(-r["excl"][lab] for lab in SHOW), -r["above"] / r["n"], r["name"]))
        sectors[c] = (sd, table)

    # --- 上次紀錄 ---
    log_path = OUT / "topdown_log.csv"
    log_rows = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8") as f:
            log_rows = list(csv.DictReader(f))
    prev = next((r for r in reversed(log_rows) if r["date"] < report_day.isoformat()), None)

    # --- 報告 ---
    L = [f"# 每日由上而下股票分析（{report_day}，用 {as_of} 或之前的最新收市）\n",
         "> 國家 → 個股 200 日線 → 3／6／9／12 個月新高 → 按板塊統計。**描述性篩選**，不是回測過的交易訊號；"
         "規則寫死（見文末），每天名單記入 `analysis/topdown_log.csv` 做樣本外追蹤。\n"]

    L.append("## 一、國家（只排名、不篩選，三地全部往下做）\n")
    L.append("| 市場 | 指數 ETF | 收市日 | 1個月 | 3個月 | 6個月 | 12個月 | **動能分數** | 距200日線 | 距52週高 | "
             "成分股 >200日線 | 新高合共（3個月以上） |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in ranked:
        x, m = country[c], country[c]["m"]
        if not m:
            L.append(f"| {COUNTRIES[c]['zh']} | {x['ticker']} | 無數據 |" + " |" * 9)
            continue
        L.append(f"| **{COUNTRIES[c]['zh']}** | {disp(x['ticker'])} | {fmt_d(m['last'])} | {pct(m['r1'])} | {pct(m['r3'])} | "
                 f"{pct(m['r6'])} | {pct(m['r12'])} | **{pct(m['score'])}** | {pct(m['vs200'])} | {pct(m['dd52'])} | "
                 f"{len(x['above'])}/{x['n_members']}（{len(x['above']) / max(x['n_members'], 1):.0%}） | "
                 f"{len(x['kept'])} |")
    L.append("")
    L.append("參考：" + "；".join(
        f"{REF_ZH.get(t, t)} {disp(t)} 3個月 {pct(m['r3'])}、12個月 {pct(m['r12'])}"
        for c in ranked for t, m in country[c]["refs"].items() if m) + "。")
    notes = [country[c]["usd_note"] for c in COUNTRIES if country[c]["usd_note"]]
    L.append("動能分數 = 3/6/12 個月總報酬平均。港股以港元計（聯繫匯率≈美元）；日股用美元計的 EWJ，"
             "跟港美股同一把尺。" + "".join(notes) + "\n")

    L.append("## 二、個股篩選：200 日線 → 新高 → 各板塊檔數\n")
    L.append(f"「留下」= 最新收市在 200 日線上 **且** 創至少 {KEEP}新高。四個窗口依序顯示 **12 → 9 → 6 → 3 個月**；"
             "**每隻股票只算在它創新高的最長窗口**（12 個月新高不再重複算進 9／6／3 個月），各欄相加 = 合共。"
             "板塊按 12 個月新高檔數排序，同數再比 9、6、3 個月。（累計版名單見 `analysis/newhighs/`。）\n")
    for c in ranked:
        x, st = country[c], stocks[c]
        sd, table = sectors[c]
        hi_tot = {lab: sum(r["excl"][lab] for r in table) for lab in WIN}
        L.append(f"### {COUNTRIES[c]['zh']}（{Universe(COUNTRIES[c]['index']).cfg['name']}，收市 {fmt_d(x['last'])}）"
                 f"{gap_note(x['last'], as_of, c)}\n")
        L.append(f"成分股 {x['n_members']} → 200 日線上 **{len(x['above'])}** → "
                 + "、".join(f"{lab}新高 **{hi_tot[lab]}**" for lab in SHOW) + f"（合共 **{len(x['kept'])}**）\n")
        L.append("| 板塊 | 成分股 | 200日線上 | " + " | ".join(f"**{lab}新高**" for lab in SHOW)
                 + " | 合共 | 留下佔板塊 | 板塊動能排名（6月超額） |")
        L.append("|---|---|---|" + "---|" * len(SHOW) + "---|---|---|")
        for r in table:
            mr = f"{r['mom_rank']}/{r['n_rank']}（{pct(r['ex6'])}）" if r["mom_rank"] else ("薄" if r["n"] < RULES["min_members"] else "—")
            L.append(f"| {r['name']} | {r['n']} | {r['above']} | "
                     + " | ".join(f"**{r['excl'][lab]}**" if r["excl"][lab] else "0" for lab in SHOW)
                     + f" | {r['highs'][KEEP]} | {r['highs'][KEEP] / r['n']:.0%} | {mr} |")
        L.append(f"| **合計** | {x['n_members']} | {len(x['above'])} | "
                 + " | ".join(f"**{hi_tot[lab]}**" for lab in SHOW)
                 + f" | **{len(x['kept'])}** | {len(x['kept']) / max(x['n_members'], 1):.0%} | |")
        if x["stale"]:
            L.append(f"\n⚠ {len(x['stale'])} 檔最新收市早於 {x['last']}（停牌或數據未更新），用其最後收市判斷："
                     + "、".join(f"{disp(t)}（{st[t]['last']}）" for t in x["stale"][:10]))
        L.append("")

    L.append("## 三、新高股票名單（12 → 9 → 6 → 3 個月）\n")
    L.append("每隻股票只列在它創新高的**最長**窗口：列在「12月」的也是 9／6／3 個月新高，不再重複列出。"
             "（每個窗口的完整累計名單見 `analysis/newhighs/<收市日>.md`。）\n")
    for c in ranked:
        st = stocks[c]
        L.append(f"### {COUNTRIES[c]['zh']}\n")
        order = [r["name"] for r in sectors[c][1]]
        for lab in SHOW:
            hits = [t for t in country[c]["above"] if longest(st[t]) == lab]
            L.append(f"**{lab}新高：{len(hits)} 檔**\n")
            if not hits:
                L.append("（無）\n")
                continue
            L.append("| 板塊 | 代碼 | 名稱 | 連續天數 | 距200日線 | 1個月 | 3個月 | 12個月 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for t in sorted(hits, key=lambda t: (order.index(sector_zh(sec_of[c], t)), t)):
                m = st[t]
                L.append(f"| {sector_zh(sec_of[c], t)} | {disp(t)} | {names[c].get(t, '')} | {keycap(streak(c, t))} | "
                         f"{pct(m['vs200'])} | {pct(m['r1'])} | {pct(m['r3'])} | {pct(m['r12'])} |")
            L.append("")

    L.append("## 四、與上次報告比較\n")
    if prev:
        for c in ranked:
            old = set(prev.get(f"{c}_kept", "").split())
            new = country[c]["kept"]
            added, dropped = sorted(new - old), sorted(old - new)
            line = f"- {COUNTRIES[c]['zh']}：留下 {prev.get(f'{c}_n_kept') or len(old)} → {len(new)} 檔"
            if added:
                line += f"；新進 {'、'.join(map(disp, added))}"
            if dropped:
                line += f"；移出 {'、'.join(map(disp, dropped))}"
            L.append(line)
            if old:   # 上次名單從上次報告日至今（單次、未扣成本，只供追蹤）
                pd_ = date.fromisoformat(prev["date"])
                rs = [r for t in old if (r := ret_since(t, pd_, as_of)) is not None]
                b = ret_since(country[c]["ticker"], pd_, as_of)
                if rs:
                    L.append(f"  - 上次（{prev['date']}）名單 {len(rs)} 檔等權至今 {pct(sum(rs) / len(rs))}"
                             + (f"，同期 {disp(country[c]['ticker'])} {pct(b)}" if b is not None else ""))
    else:
        L.append("- 第一份新格式報告，沒有可比較的上次紀錄。")
    L.append("")

    L.append("## 五、規則與限制（寫死，不按結果調）\n")
    L.append("- 國家：動能分數 = 3/6/12 個月總報酬平均，只排名、不篩選")
    L.append("- 個股：各地指數現任 point-in-time 成分股（恒指／S&P 500／日經225），最新收市 > 200 日均線")
    L.append("- 新高：昨天收市價**嚴格高於**之前 62／125／188／251 個交易日（連昨天約 3／6／9／12 個月）的盤中最高價；"
             "用原始價（按拆股還原、不按股息），跟報價頁 52 週高一致；上市不足該窗口的不計")
    L.append("- 板塊：yfinance 行業（**今天的**分類）；「板塊動能排名」= PIT 等權行業指數過去 6 個月相對全體等權的超額，"
             f"組員 < {RULES['min_members']} 檔不排")
    L.append("- 研究狀態（RESEARCH_HANDBOOK.md）：「200 日線 + 新高」這套篩選**沒有回測過**；行業動量只有港股 🔍（壓線），"
             "美股不確定、日股 ☠️；港股個股 12-1 動量單獨使用 ☠️。**名單是觀察起點，不是買入建議**")
    L.append("- 三地收市日可能不同（見各地標題）；美股收市在亞洲早上才有數據")

    OUT.mkdir(parents=True, exist_ok=True)
    listed_days = write_newhigh_lists(as_of, args.list_days)
    print(f"新高名單：{listed_days[0]} ~ {listed_days[-1]}（{len(listed_days)} 個交易日）-> {OUT / 'newhighs'}",
          file=sys.stderr)
    text = "\n".join(L) + "\n"
    (OUT / "DAILY_TOPDOWN.md").write_text(text, encoding="utf-8")
    (OUT / "archive").mkdir(exist_ok=True)
    (OUT / "archive" / f"{report_day}.md").write_text(text, encoding="utf-8")

    # 樣本外紀錄（每天一列）
    rec = {"date": report_day.isoformat()}
    for c in COUNTRIES:
        x = country[c]
        rec[f"{c}_last"] = x["last"].isoformat() if x["last"] else ""
        rec[f"{c}_score"] = f"{x['m']['score']:.4f}" if x["m"] and x["m"]["score"] is not None else ""
        rec[f"{c}_n"] = x["n_members"]
        rec[f"{c}_n_above"] = len(x["above"])
        rec[f"{c}_n_kept"] = len(x["kept"])
        rec[f"{c}_by_sector"] = "|".join(f"{r['name']}:{r['highs'][KEEP]}" for r in sectors[c][1] if r["highs"][KEEP])
        rec[f"{c}_kept"] = " ".join(sorted(x["kept"]))
    log_rows = [r for r in log_rows if r["date"] != rec["date"] and f"{ranked[0]}_kept" in r] + [rec]
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec))
        w.writeheader()
        for r in sorted(log_rows, key=lambda r: r["date"]):
            w.writerow({k: r.get(k, "") for k in rec})

    # Telegram（給投資人看）：第一則總覽，之後每個市場一則；每個窗口列出**全部**股票與名稱，不省略。
    # Telegram 單則上限 4096 字，超過就按行切成多則（標「續」）。
    def tk(c: str, t: str) -> str:     # 完整代號（2359.HK / 4502.JP / AMD）+ 名稱 + 連續天數；收市日跟該市場不同就標日期
        n = names[c].get(t, "")
        s_ = (f"{disp(t)} {n}" if n else disp(t)) + f" {keycap(streak(c, t))}"
        lt = stocks[c][t]["last"]
        return s_ + (f"（{lt.month}/{lt.day} 收市）" if lt != country[c]["last"] else "")

    uni_name = {c: Universe(COUNTRIES[c]["index"]).cfg["name"] for c in COUNTRIES}
    head = [f"📊 每日股票篩選｜報告日 {fmt_d(report_day)}（香港）",
            "各市場用自己最近一個交易日的收市價，三地假期不同，請看每個市場標示的收市日期。",
            "",
            "篩選方法：",
            "① 三地指數成分股（恒生指數、S&P 500、日經225）",
            "② 最近一個交易日的收市價在 200 天平均線之上",
            "③ 該收市價高於過去 12／9／6／3 個月的最高價（盤中最高，跟報價頁「52 週高」同一把尺）",
            "④ 按板塊（行業）統計檔數，並列出每一隻股票",
            "每隻股票只列在它創新高的最長窗口（列在 12 個月的，也是 9／6／3 個月新高，不再重複）",
            "數字 emoji（1️⃣2️⃣…🔟）= 連續第幾個交易日列在同一個窗口；窗口改變（例如 3 個月升到 6 個月）就由 1️⃣ 重新計",
            "",
            "國家動能（3/6/12 個月報酬平均）：",
            *[f"・{COUNTRIES[c]['zh']}（{disp(country[c]['ticker'])}，收市 {fmt_d(country[c]['m']['last'])}）"
              f"{pct(country[c]['m']['score'])}" for c in ranked if country[c]["m"]],
            "",
            "各市場總覽："]
    for c in ranked:
        x, st = country[c], stocks[c]
        head.append(f"【{COUNTRIES[c]['zh']}】收市 {fmt_d(x['last'])}{gap_note(x['last'], as_of, c)}")
        head.append(f"  {x['n_members']} 檔 → 200天線上 {len(x['above'])} 檔 → "
                    + "、".join(f"{lab}新高 {sum(1 for t in x['above'] if longest(st[t]) == lab)}" for lab in SHOW)
                    + f"（合共 {len(x['kept'])}）")
    head += ["", "描述性篩選，未經回測，不是買入建議。"]
    msgs = ["\n".join(head)]
    for c in ranked:
        x, st = country[c], stocks[c]
        lines = [f"【{COUNTRIES[c]['zh']}｜{uni_name[c]}】收市 {fmt_d(x['last'])}",
                 *([gap_note(x["last"], as_of, c)] if gap_note(x["last"], as_of, c) else []),
                 f"成分股 {x['n_members']} 檔 → 200天線上 {len(x['above'])} 檔"]
        for lab in SHOW:
            hits = {t for t in x["above"] if longest(st[t]) == lab}
            lines += ["", f"▍{lab}新高（{x['last'].month}/{x['last'].day} 收市）：{len(hits)} 檔"]
            if not hits:
                lines.append("（無）")
                continue
            for r in sectors[c][1]:
                sec_hits = sorted(t for t in hits if sector_zh(sec_of[c], t) == r["name"])
                if sec_hits:
                    lines.append(f"・{r['name']} {len(sec_hits)} 檔：" + "、".join(tk(c, t) for t in sec_hits))
        # 按行切成 ≤ 3800 字的多則
        chunk: list[str] = []
        for line in lines:
            if chunk and len("\n".join(chunk + [line])) > 3800:
                msgs.append("\n".join(chunk))
                chunk = [f"【{COUNTRIES[c]['zh']}】（續）"]
            chunk.append(line[:3700])
        msgs.append("\n".join(chunk))
    parts_dir = OUT / "tg_parts"
    parts_dir.mkdir(exist_ok=True)
    for old in parts_dir.glob("part_*.txt"):
        old.unlink()
    for i, m in enumerate(msgs, 1):
        (parts_dir / f"part_{i:02d}.txt").write_text(m + "\n", encoding="utf-8")
    (OUT / "tg_topdown.txt").write_text("\n\n".join(msgs) + "\n", encoding="utf-8")
    print("\n\n----\n".join(msgs))

if __name__ == "__main__":
    main()
