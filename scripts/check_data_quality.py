#!/usr/bin/env python3
"""每日股票數據品質檢查，輸出 data/stocks/QC_REPORT.md。

由 .github/workflows/fetch_stock_data.yml 每次抓完數據後執行；本機也能跑
（不加 --fetch-names 就不需要網路，只檢查已存在的檔案）：
    python3 scripts/check_data_quality.py
    python3 scripts/check_data_quality.py --fetch-names   # 需要網路（Actions 上）

檢查項目（🔴 嚴重 = 會直接污染回測；🟡 注意 = 需要人看一眼）。逐根的價格
檢查只對「近30天」每天警告，更早的彙總進報告最後的「歷史已知」表：
- 🔴 近30天有價格 <= 0、High < Low（資料損壞）、單日漲跌 > 40%
- 🟡 近30天開/收市價落在高低價外（港股競價時段慣例，多半不是髒值）
- 🔴 名字不符：yfinance 現在的公司名 vs Wikipedia 記載的成分股名差很多
  ——港交所代碼下市後會重新分配給別家公司，同一代碼的價格歷史可能被
  靜默拼接成兩家公司，回測會完全錯
- 🔴 名字變了：yfinance 公司名跟上次檢查不同（改名或代碼被重用）
- 🔴 雙來源收市價不符：最近 20 份港交所官方快照 vs yfinance 收市價
  相差 > 1%
- 🟡 數據過期（最後一根距今 > 7 天，已下市的舊成分股是預期結果）
- 🟡 交易日斷層 > 14 天（停牌？）
- 🟡 同一代碼在 Wikipedia 不同年份記載的名字不一致（代碼重用或編輯錯誤）
- 🟡 沒有第二來源可交叉驗證

已人工確認沒問題的項目寫進 scripts/qc_acks.json（{"<TICKER>:<檢查>": "理由"}），
報告會移到「已確認」區，不再每天重複警告。
"""
import argparse
import csv
import gzip
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIMARY_DIR = ROOT / "data" / "stocks"
HKEX_DIR = ROOT / "data" / "stocks_hkex"
WIKI_NAMES = ROOT / "scripts" / "pointintime" / "hsi_names.json"
YF_NAMES = PRIMARY_DIR / "names_yf.json"
ACKS = ROOT / "scripts" / "qc_acks.json"
REPORT = PRIMARY_DIR / "QC_REPORT.md"

STALE_DAYS = 7
RECENT_DAYS = 30
BIG_MOVE = 0.40
GAP_DAYS = 14
XSRC_TOL = 0.01
XSRC_WINDOW = 20
NAME_SIM_MIN = 0.5

NAME_STOPWORDS = {
    "limited", "ltd", "co", "company", "corp", "corporation", "inc", "plc", "the",
    "holdings", "holding", "group", "grop", "a", "h", "class", "shares", "share",
    # 港交所簡稱的股份類別後綴：-W 同股不同權、-SW 第二上市+同股不同權、-R 人民幣櫃台
    "w", "sw", "r",
}


def load_ohlc(path: Path) -> list[tuple[date, float, float, float, float]]:
    rows = []
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((date.fromisoformat(r["Date"]), float(r["Open"]), float(r["High"]),
                             float(r["Low"]), float(r["Close"])))
            except (ValueError, TypeError, KeyError):
                continue
    return rows


def norm_name(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    return " ".join(t for t in tokens if t not in NAME_STOPWORDS)


def name_similarity(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb)
    # 縮寫（CKH vs CK Hutchison）讓 token 比對吃虧，取兩種相似度的較大者
    return max(jaccard, SequenceMatcher(None, na, nb).ratio())


def fetch_yf_names(tickers: list[str], budget_s: float = 360) -> dict[str, str]:
    """有時間上限：抓名字很慢時寧可少抓幾檔，也要讓日報照常寫出來。"""
    import yfinance as yf
    out = {}
    started = time.monotonic()
    for t in tickers:
        if time.monotonic() - started > budget_s:
            print(f"WARN 抓公司名超過 {budget_s}s，只抓了 {len(out)} 檔", file=sys.stderr)
            break
        try:
            info = yf.Ticker(t).get_info()
            name = info.get("longName") or info.get("shortName") or ""
        except Exception as exc:
            print(f"WARN {t}: 抓不到公司名（{exc}）", file=sys.stderr)
            name = ""
        if name:
            out[t] = name
        time.sleep(0.3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch-names", action="store_true", help="從 yfinance 抓今天的公司名（需要網路）")
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="測試用，覆寫今天日期")
    args = ap.parse_args()

    today = args.today or datetime.now(timezone.utc).date()
    acks: dict[str, str] = json.loads(ACKS.read_text(encoding="utf-8")) if ACKS.exists() else {}
    wiki_names: dict[str, dict[str, str]] = (
        json.loads(WIKI_NAMES.read_text(encoding="utf-8")) if WIKI_NAMES.exists() else {})
    yf_names: dict[str, dict] = json.loads(YF_NAMES.read_text(encoding="utf-8")) if YF_NAMES.exists() else {}

    primary_files = sorted(p for p in PRIMARY_DIR.glob("*.csv.gz") if ".shares." not in p.name)
    tickers = [p.name[:-len(".csv.gz")].replace("_", "^", 1) if p.name.startswith("_")
               else p.name[:-len(".csv.gz")] for p in primary_files]

    # 港交所每日快照（fetch_hkex_equity.py），取最近 XSRC_WINDOW 份
    hkex_snaps: list[tuple[date, dict]] = []
    if HKEX_DIR.exists():
        for p in sorted(HKEX_DIR.glob("quotes_*.json"))[-XSRC_WINDOW:]:
            try:
                snap = json.loads(p.read_text(encoding="utf-8"))
                hkex_snaps.append((date.fromisoformat(snap.get("trade_date") or snap["trade_date_guess"]), snap["quotes"]))
            except (ValueError, KeyError):
                continue

    issues: list[tuple[str, str, str, str]] = []  # (severity, ticker, check, detail)
    history: dict[str, dict[str, tuple[int, date]]] = {}  # {ticker: {check: (count, last_date)}}，只統計不每天警告

    def flag(sev: str, t: str, check: str, detail: str) -> None:
        issues.append((sev, t, check, detail))

    for t, path in zip(tickers, primary_files):
        rows = load_ohlc(path)
        if not rows:
            flag("🔴", t, "empty", "檔案沒有可解析的資料列")
            continue
        dates = [r[0] for r in rows]
        if len(set(dates)) != len(dates) or dates != sorted(dates):
            flag("🔴", t, "dates", "日期重複或未排序")

        # 逐根檢查：近 RECENT_DAYS 天內的問題每天報（新數據出錯），更早的只進
        # 「歷史已知」彙總表——每天重複列同一批十年前的髒值只會淹沒真問題
        nonpos = [r[0] for r in rows if min(r[1:]) <= 0]
        # High < Low：真的壞掉的資料列
        hl_bad = [r[0] for r in rows if min(r[1:]) > 0 and r[2] < r[3]]
        # 開/收市價落在 High-Low 外：港股開市前競價/收市競價的成交價常不計入
        # 數據商的持續交易時段高低價，多半是慣例差異而非髒值（見 data/stocks/README.md）
        auction = [r[0] for r in rows if min(r[1:]) > 0 and r[2] >= r[3] and
                   (r[2] < max(r[1], r[4]) * (1 - 1e-6) or r[3] > min(r[1], r[4]) * (1 + 1e-6))]
        moves = [(rows[i][0], rows[i][4] / rows[i - 1][4] - 1) for i in range(1, len(rows))
                 if rows[i - 1][4] > 0 and rows[i][4] > 0 and abs(rows[i][4] / rows[i - 1][4] - 1) > BIG_MOVE]

        def is_recent(d: date) -> bool:
            return (today - d).days <= RECENT_DAYS

        for check, sev, bad, desc in (
            ("nonpositive", "🔴", nonpos, "價格 <= 0"),
            ("ohlc_high_lt_low", "🔴", hl_bad, "High < Low（資料損壞）"),
            ("ohlc_auction", "🟡", auction, "開/收市價落在高低價外（多半是競價時段慣例）"),
        ):
            recent = [d for d in bad if is_recent(d)]
            if recent:
                flag(sev, t, check, f"近{RECENT_DAYS}天 {len(recent)} 根{desc}：{', '.join(map(str, recent[-3:]))}")
            if len(bad) > len(recent):
                history.setdefault(t, {})[check] = (len(bad) - len(recent), max(d for d in bad if not is_recent(d)))
        recent_moves = [m for m in moves if is_recent(m[0])]
        for d, m in recent_moves:
            flag("🔴", t, "bigmove", f"{d} 單日 {m:+.0%}（> {BIG_MOVE:.0%}，需對第二來源確認是真實波動還是拆股/髒值）")
        if len(moves) > len(recent_moves):
            old = [m for m in moves if not is_recent(m[0])]
            history.setdefault(t, {})["bigmove"] = (len(old), old[-1][0])

        age = (today - dates[-1]).days
        if age > STALE_DAYS:
            flag("🟡", t, "stale", f"最後一根 {dates[-1]}（{age} 天前）")

        gaps = [(dates[i - 1], dates[i]) for i in range(1, len(dates)) if (dates[i] - dates[i - 1]).days > GAP_DAYS]
        if gaps:
            g0, g1 = gaps[-1]
            flag("🟡", t, "gap", f"{len(gaps)} 段 > {GAP_DAYS} 天斷層，最近 {g0} -> {g1}")

        # --- 第二來源（港交所官方收市價）交叉比對：只有港股有 ---
        if t.endswith(".HK") and age <= STALE_DAYS:
            sec = {d: q[t]["close"] for d, q in hkex_snaps if t in q and q[t].get("close")}
            yf_close = {r[0]: r[4] for r in rows}
            common = [(d, yf_close[d], c) for d, c in sec.items() if d in yf_close and yf_close[d] > 0 and c > 0]
            if not sec:
                flag("🟡", t, "no_second_source", "港交所快照沒有這檔，無法交叉驗證收市價")
            elif common:
                worst_d, yv, hv = max(common, key=lambda x: abs(x[1] / x[2] - 1))
                if abs(yv / hv - 1) > XSRC_TOL:
                    flag("🔴", t, "xsource", f"最近 {len(common)} 個共同交易日最大差 {yv / hv - 1:+.2%}"
                                            f"（{worst_d}，yfinance={yv:.4g} 港交所={hv:.4g}）")

        # --- Wikipedia 不同年份名字是否一致 ---
        wn = wiki_names.get(t, {})
        if len(wn) > 1:
            yrs = sorted(wn)
            base = wn[yrs[-1]]
            odd = [(y, wn[y]) for y in yrs if name_similarity(wn[y], base) < NAME_SIM_MIN]
            if odd:
                flag("🟡", t, "wiki_name_varies", f"最新記載「{base}」，但 " +
                     "、".join(f"{y}年「{n}」" for y, n in odd))

    # --- point-in-time 成分股覆蓋率：每個「某年是成分股」的代碼，那年有沒有價格？---
    # 快照是年中（6/30 前後）的 Wikipedia 版本，用 6/30 當作「那年是成分股」的檢查日
    first_date = {}
    for t, p in zip(tickers, primary_files):
        rows = load_ohlc(p)
        if rows:
            first_date[t] = rows[0][0]
    for t, yrs in sorted(wiki_names.items()):
        member_years = sorted(yrs)
        if t not in first_date:
            flag("🟡", t, "constituent_no_data",
                 f"{member_years[0]}-{member_years[-1]}年是成分股（{yrs[member_years[-1]]}），但主來源完全沒有價格"
                 "（多半已下市/私有化——回測測不到它，倖存者偏差殘留）")
            continue
        uncovered = [y for y in member_years if first_date[t] > date(int(y), 6, 30)]
        if uncovered:
            # 價格從成分股期間之後才開始 = 這個代碼後來換了公司，現有價格屬於新公司
            flag("🔴", t, "code_reuse_suspected",
                 f"{uncovered[0]}-{uncovered[-1]}年是成分股（{yrs[uncovered[-1]]}），但價格 {first_date[t]} 才開始"
                 "——代碼被重新分配給別家公司，現有價格不是當年那家，回測不能拿來代表它")

    # --- yfinance 公司名：跟 Wikipedia 比、跟上次比 ---
    if args.fetch_names:
        hk_tickers = [t for t in tickers if t.endswith(".HK")]
        fetched = fetch_yf_names(hk_tickers)
        for t, name in fetched.items():
            rec = yf_names.setdefault(t, {"name": name, "history": [{"date": today.isoformat(), "name": name}]})
            if rec["name"] != name:
                flag("🔴", t, "yf_name_changed", f"上次「{rec['name']}」→ 今天「{name}」（改名或代碼被重用）")
                rec["history"].append({"date": today.isoformat(), "name": name})
                rec["name"] = name
        YF_NAMES.write_text(json.dumps(yf_names, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")

    # --- 港交所官方公司名：跟前一份快照比（代碼重用/改名），跟 Wikipedia 比 ---
    if hkex_snaps:
        latest_d, latest_q = hkex_snaps[-1]
        prev = hkex_snaps[-2] if len(hkex_snaps) > 1 else None
        for t, q in sorted(latest_q.items()):
            name = q.get("name", "")
            if prev and t in prev[1] and prev[1][t].get("name") and name and prev[1][t]["name"] != name:
                flag("🔴", t, "hkex_name_changed", f"港交所名稱 {prev[0]}「{prev[1][t]['name']}」→ "
                                                   f"{latest_d}「{name}」（改名或代碼被重用）")
            wn = wiki_names.get(t)
            if wn and name:
                y = max(wn)
                sim = name_similarity(name, wn[y])
                if sim < NAME_SIM_MIN:
                    # 港交所用英文簡稱（如 CKH HOLDINGS），縮寫會讓相似度偏低，先列 🟡 人工確認
                    flag("🟡", t, "hkex_vs_wiki_name", f"港交所「{name}」vs Wikipedia {y}年「{wn[y]}」"
                                                       f"（相似度 {sim:.2f}）")

    for t, rec in yf_names.items():
        wn = wiki_names.get(t)
        if not wn:
            continue
        latest_year = max(wn)
        sim = name_similarity(rec["name"], wn[latest_year])
        if sim < NAME_SIM_MIN:
            flag("🔴", t, "name_mismatch", f"yfinance「{rec['name']}」vs Wikipedia {latest_year}年「{wn[latest_year]}」"
                                           f"（相似度 {sim:.2f}）")

    # --- 報告 ---
    open_issues = [i for i in issues if f"{i[1]}:{i[2]}" not in acks]
    acked = [i for i in issues if f"{i[1]}:{i[2]}" in acks]
    crit = [i for i in open_issues if i[0] == "🔴"]
    warn = [i for i in open_issues if i[0] == "🟡"]

    lines = [
        f"# 數據品質日報（{today}）",
        "",
        f"由 `scripts/check_data_quality.py` 產生。主來源 yfinance（`data/stocks/`）"
        f"{len(tickers)} 檔，第二來源港交所官方快照（`data/stocks_hkex/`）"
        f"{len(hkex_snaps)} 份（最新 {hkex_snaps[-1][0] if hkex_snaps else '無'}），"
        f"公司名紀錄 {len(yf_names)} 檔。",
        "",
        f"**🔴 嚴重 {len(crit)} 項 ｜ 🟡 注意 {len(warn)} 項 ｜ ✅ 已確認 {len(acked)} 項**",
        "",
        "確認沒問題的項目加進 `scripts/qc_acks.json`（key 格式 `<TICKER>:<檢查>`）。",
        "",
    ]
    for title, group in (("🔴 嚴重（會污染回測，先處理）", crit), ("🟡 注意", warn)):
        lines += [f"## {title}", ""]
        if not group:
            lines += ["（無）", ""]
            continue
        lines += ["| 代碼 | 檢查 | 說明 |", "|---|---|---|"]
        lines += [f"| {t} | {c} | {d} |" for _, t, c, d in sorted(group, key=lambda x: (x[2], x[1]))]
        lines.append("")
    if acked:
        lines += ["## ✅ 已確認（不再警告）", "", "| 代碼 | 檢查 | 確認理由 |", "|---|---|---|"]
        lines += [f"| {t} | {c} | {acks[f'{t}:{c}']} |" for _, t, c, _ in sorted(acked, key=lambda x: (x[2], x[1]))]
        lines.append("")
    if history:
        checks = ["nonpositive", "ohlc_high_lt_low", "ohlc_auction", "bigmove"]
        lines += [f"## 歷史已知（{RECENT_DAYS} 天前的逐根問題，只統計不警告）", "",
                  "格式：根數（最近一次日期）。回測前如果用到這些日期要留意；"
                  "`nonpositive` / `ohlc_high_lt_low` 是真的髒值，回測引擎要能處理。", "",
                  "| 代碼 | " + " | ".join(checks) + " |", "|---|" + "---|" * len(checks)]
        for t in sorted(history):
            cells = [f"{history[t][c][0]}（{history[t][c][1]}）" if c in history[t] else "" for c in checks]
            lines.append(f"| {t} | " + " | ".join(cells) + " |")
        lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"QC: 🔴 {len(crit)} 嚴重 / 🟡 {len(warn)} 注意 / ✅ {len(acked)} 已確認 -> {REPORT}")


if __name__ == "__main__":
    main()
