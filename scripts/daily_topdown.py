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
3. **新高**：留下的股票，最新收市是否為過去 3／6／9／12 個月（63／126／189／252 個交易日）
   收市最高；至少創 3 個月新高的留下（12 個月新高必然也是 9／6／3 個月新高，分層計數）。
4. **按板塊統計**：留下的股票按 yfinance 行業分組，報每個板塊的檔數（各新高窗口分開數），
   附板塊 6 個月超額動能排名（sector_rotation.py 的 PIT 等權行業指數）作參考。
價格一律用含股息還原收市（AdjClose，約等於富途「前復權」），除淨不會假跌破新高。
"""
import argparse
import bisect
import csv
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


def metrics(rows: list[tuple[date, float]]) -> dict | None:
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
    # 新高：最新收市 >= 過去 n 個交易日（含當天）收市最高；歷史不足 n 天 = None（不算新高也不算否）
    m["highs"] = {lab: (c[-1] >= max(c[-n:]) if len(c) >= n else None) for lab, n in RULES["high_windows"]}
    moms = [m[k] for k in ("r3", "r6", "r12")]
    m["score"] = sum(moms) / 3 if all(x is not None for x in moms) else None
    return m


def pct(x: float | None, digits: int = 1, sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def short_name(name: str) -> str:
    for suf in (" Limited", " Ltd.", " Ltd", " Co., Ltd.", " Company", " Corporation", " Corp.", " Inc.",
                ", Inc.", " Holdings", " Group", " plc", " N.V.", " Incorporated", " (The)"):
        name = name.replace(suf, "")
    return name.strip(" ,")[:28]


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
    args = ap.parse_args()
    report_day = args.as_of or date.today()
    # 用「昨天收市」：只取報告日之前的收市（早上跑本來就是這樣；白天手動跑也不會混進盤中價）
    as_of = report_day - timedelta(days=1)
    WIN = [lab for lab, _ in RULES["high_windows"]]
    SHOW = list(reversed(WIN))          # 顯示順序：12 → 9 → 6 → 3 個月（使用者指定）
    KEEP = RULES["keep_min_window"]

    # --- 第一層：國家（只排名，不篩選）---
    country = {}
    for c, cfg in COUNTRIES.items():
        usd_t = cfg["usd"] if md.has_data(cfg["usd"]) else cfg["etf"]
        refs = {t: metrics(closes_upto(t, as_of)) for t in cfg["refs"] + ([cfg["etf"]] if usd_t != cfg["etf"] else [])}
        country[c] = {"ticker": usd_t, "m": metrics(closes_upto(usd_t, as_of)), "refs": refs,
                      "usd_note": "" if usd_t == cfg["usd"] else f"（{cfg['usd']} 尚無數據，暫用 {cfg['etf']} 本幣計）"}
    ranked = sorted(COUNTRIES, key=lambda c: -(country[c]["m"]["score"]
                                                 if country[c]["m"] and country[c]["m"]["score"] is not None else -9))

    # --- 第二、三層：個股 200 日線 → 新高 ---
    stocks: dict[str, dict[str, dict]] = {}
    sec_of: dict[str, dict[str, str]] = {}
    names: dict[str, dict[str, str]] = {}
    for c, cfg in COUNTRIES.items():
        uni = Universe(cfg["index"])
        first, data = {}, {}
        for t in uni.members_at(as_of):
            rows = closes_upto(t, as_of)
            if rows:
                first[t], data[t] = rows[0][0], rows
        stocks[c] = {t: m for t in uni.eligible_at(as_of, first) if (m := metrics(data[t]))}
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
                   "highs": {lab: sum(1 for t in ab if st[t]["highs"][lab]) for lab in WIN},
                   "mom_rank": mom_rank.get(name), "ex6": mom.get(name, {}).get("ex6"), "n_rank": len(mom_rank)}
            table.append(row)
        table.sort(key=lambda r: (*(-r["highs"][lab] for lab in SHOW), -r["above"] / r["n"], r["name"]))
        sectors[c] = (sd, table)

    # --- 上次紀錄 ---
    log_path = OUT / "topdown_log.csv"
    log_rows = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8") as f:
            log_rows = list(csv.DictReader(f))
    prev = next((r for r in reversed(log_rows) if r["date"] < report_day.isoformat()), None)

    def longest(m: dict) -> str:
        return next((lab for lab in reversed(WIN) if m["highs"][lab]), "")

    # --- 報告 ---
    L = [f"# 每日由上而下股票分析（{report_day}，用 {as_of} 或之前的最新收市）\n",
         "> 國家 → 個股 200 日線 → 3／6／9／12 個月新高 → 按板塊統計。**描述性篩選**，不是回測過的交易訊號；"
         "規則寫死（見文末），每天名單記入 `analysis/topdown_log.csv` 做樣本外追蹤。\n"]

    L.append("## 一、國家（只排名、不篩選，三地全部往下做）\n")
    L.append("| 市場 | 指數 ETF | 收市日 | 1個月 | 3個月 | 6個月 | 12個月 | **動能分數** | 距200日線 | 距52週高 | "
             "成分股 >200日線 | 成分股 3月新高 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in ranked:
        x, m = country[c], country[c]["m"]
        if not m:
            L.append(f"| {COUNTRIES[c]['zh']} | {x['ticker']} | 無數據 |" + " |" * 9)
            continue
        L.append(f"| **{COUNTRIES[c]['zh']}** | {x['ticker']} | {m['last']} | {pct(m['r1'])} | {pct(m['r3'])} | "
                 f"{pct(m['r6'])} | {pct(m['r12'])} | **{pct(m['score'])}** | {pct(m['vs200'])} | {pct(m['dd52'])} | "
                 f"{len(x['above'])}/{x['n_members']}（{len(x['above']) / max(x['n_members'], 1):.0%}） | "
                 f"{len(x['kept'])} |")
    L.append("")
    L.append("參考：" + "；".join(
        f"{REF_ZH.get(t, t)} {t} 3個月 {pct(m['r3'])}、12個月 {pct(m['r12'])}"
        for c in ranked for t, m in country[c]["refs"].items() if m) + "。")
    notes = [country[c]["usd_note"] for c in COUNTRIES if country[c]["usd_note"]]
    L.append("動能分數 = 3/6/12 個月總報酬平均。港股以港元計（聯繫匯率≈美元）；日股用美元計的 EWJ，"
             "跟港美股同一把尺。" + "".join(notes) + "\n")

    L.append("## 二、個股篩選：200 日線 → 新高 → 各板塊檔數\n")
    L.append(f"「留下」= 最新收市在 200 日線上 **且** 創至少 {KEEP}新高。四個窗口依序顯示 **12 → 9 → 6 → 3 個月**；"
             "12 個月新高必然也是 9／6／3 個月新高，所以各欄是累計（12月 ≤ 9月 ≤ 6月 ≤ 3月）。"
             "板塊按 12 個月新高檔數排序，同數再比 9、6、3 個月。\n")
    for c in ranked:
        x, st = country[c], stocks[c]
        sd, table = sectors[c]
        hi_tot = {lab: sum(r["highs"][lab] for r in table) for lab in WIN}
        L.append(f"### {COUNTRIES[c]['zh']}（{Universe(COUNTRIES[c]['index']).cfg['name']}，收市 {x['last']}）\n")
        L.append(f"成分股 {x['n_members']} → 200 日線上 **{len(x['above'])}** → "
                 + "、".join(f"{lab}新高 **{hi_tot[lab]}**" for lab in SHOW) + "\n")
        L.append("| 板塊 | 成分股 | 200日線上 | " + " | ".join(f"**{lab}新高**" for lab in SHOW)
                 + " | 留下佔板塊 | 板塊動能排名（6月超額） |")
        L.append("|---|---|---|" + "---|" * len(SHOW) + "---|---|")
        for r in table:
            mr = f"{r['mom_rank']}/{r['n_rank']}（{pct(r['ex6'])}）" if r["mom_rank"] else ("薄" if r["n"] < RULES["min_members"] else "—")
            L.append(f"| {r['name']} | {r['n']} | {r['above']} | "
                     + " | ".join(f"**{r['highs'][lab]}**" if r["highs"][lab] else "0" for lab in SHOW)
                     + f" | {r['highs'][KEEP] / r['n']:.0%} | {mr} |")
        L.append(f"| **合計** | {x['n_members']} | {len(x['above'])} | "
                 + " | ".join(f"**{hi_tot[lab]}**" for lab in SHOW) + f" | {hi_tot[KEEP] / max(x['n_members'], 1):.0%} | |")
        if x["stale"]:
            L.append(f"\n⚠ {len(x['stale'])} 檔最新收市早於 {x['last']}（停牌或數據未更新），用其最後收市判斷："
                     + "、".join(f"{t}（{st[t]['last']}）" for t in x["stale"][:10]))
        L.append("")

    L.append("## 三、新高股票名單（12 → 9 → 6 → 3 個月）\n")
    L.append("每個窗口列出該窗口的**全部**新高股（12 個月新高的股票同時也會出現在 9、6、3 個月的名單）。\n")
    for c in ranked:
        st = stocks[c]
        L.append(f"### {COUNTRIES[c]['zh']}\n")
        order = [r["name"] for r in sectors[c][1]]
        for lab in SHOW:
            hits = [t for t in country[c]["above"] if st[t]["highs"][lab]]
            L.append(f"**{lab}新高：{len(hits)} 檔**\n")
            if not hits:
                L.append("（無）\n")
                continue
            L.append("| 板塊 | 代碼 | 名稱 | 距200日線 | 1個月 | 3個月 | 12個月 |")
            L.append("|---|---|---|---|---|---|---|")
            for t in sorted(hits, key=lambda t: (order.index(sector_zh(sec_of[c], t)), t)):
                m = st[t]
                L.append(f"| {sector_zh(sec_of[c], t)} | {t} | {names[c].get(t, '')} | "
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
                line += f"；新進 {'、'.join(added)}"
            if dropped:
                line += f"；移出 {'、'.join(dropped)}"
            L.append(line)
            if old:   # 上次名單從上次報告日至今（單次、未扣成本，只供追蹤）
                pd_ = date.fromisoformat(prev["date"])
                rs = [r for t in old if (r := ret_since(t, pd_, as_of)) is not None]
                b = ret_since(country[c]["ticker"], pd_, as_of)
                if rs:
                    L.append(f"  - 上次（{prev['date']}）名單 {len(rs)} 檔等權至今 {pct(sum(rs) / len(rs))}"
                             + (f"，同期 {country[c]['ticker']} {pct(b)}" if b is not None else ""))
    else:
        L.append("- 第一份新格式報告，沒有可比較的上次紀錄。")
    L.append("")

    L.append("## 五、規則與限制（寫死，不按結果調）\n")
    L.append("- 國家：動能分數 = 3/6/12 個月總報酬平均，只排名、不篩選")
    L.append("- 個股：各地指數現任 point-in-time 成分股（恒指／S&P 500／日經225），最新收市 > 200 日均線")
    L.append("- 新高：最新收市 ≥ 過去 63／126／189／252 個交易日的收市最高（含股息還原價）；上市不足該窗口的不計該窗口")
    L.append("- 板塊：yfinance 行業（**今天的**分類）；「板塊動能排名」= PIT 等權行業指數過去 6 個月相對全體等權的超額，"
             f"組員 < {RULES['min_members']} 檔不排")
    L.append("- 研究狀態（RESEARCH_HANDBOOK.md）：「200 日線 + 新高」這套篩選**沒有回測過**；行業動量只有港股 🔍（壓線），"
             "美股不確定、日股 ☠️；港股個股 12-1 動量單獨使用 ☠️。**名單是觀察起點，不是買入建議**")
    L.append("- 三地收市日可能不同（見各地標題）；美股收市在亞洲早上才有數據")

    OUT.mkdir(parents=True, exist_ok=True)
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
    def tk(c: str, t: str) -> str:     # 完整代號（2359.HK / 4502.T / AMD）+ 名稱
        n = names[c].get(t, "")
        return f"{t} {n}" if n else t

    uni_name = {c: Universe(COUNTRIES[c]["index"]).cfg["name"] for c in COUNTRIES}
    head = [f"📊 每日股票篩選 {report_day}",
            "",
            "篩選方法：",
            "① 三地指數成分股（恒生指數、S&P 500、日經225）",
            "② 昨天收市價在 200 天平均線之上",
            "③ 昨天收市價創 12／9／6／3 個月新高",
            "④ 按板塊（行業）統計檔數，並列出每一隻股票",
            "",
            "國家動能（3/6/12 個月報酬平均）：",
            *[f"・{COUNTRIES[c]['zh']}（{country[c]['ticker']}）{pct(country[c]['m']['score'])}" for c in ranked if country[c]["m"]],
            "",
            "各市場總覽："]
    for c in ranked:
        x, st = country[c], stocks[c]
        head.append(f"【{COUNTRIES[c]['zh']}】{x['n_members']} 檔 → 200天線上 {len(x['above'])} 檔 → "
                    + "、".join(f"{lab}新高 {sum(1 for t in x['above'] if st[t]['highs'][lab])}" for lab in SHOW))
    head += ["", "註：12 個月新高的股票必然也是 9、6、3 個月新高，所以會在每個窗口重複出現。",
             "描述性篩選，未經回測，不是買入建議。"]
    msgs = ["\n".join(head)]
    for c in ranked:
        x, st = country[c], stocks[c]
        lines = [f"【{COUNTRIES[c]['zh']}｜{uni_name[c]}】收市 {x['last']}",
                 f"成分股 {x['n_members']} 檔 → 200天線上 {len(x['above'])} 檔"]
        for lab in SHOW:
            hits = {t for t in x["above"] if st[t]["highs"][lab]}
            lines += ["", f"▍{lab}新高：{len(hits)} 檔"]
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
