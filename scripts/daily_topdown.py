#!/usr/bin/env python3
"""每日由上而下股票分析：國家（指數 ETF）→ 板塊動能排列 → 個股。

    python3 scripts/sector_rotation.py --index hsi     # 先更新三地板塊指數（group_index.csv）
    python3 scripts/sector_rotation.py --index sp500
    python3 scripts/sector_rotation.py --index n225
    python3 scripts/daily_topdown.py                   # -> analysis/

**定位**：描述性篩選，**不是**預先登記、回測過的交易訊號。規則全部寫死在下面（RULES），
不按每天的結果調——要改規則先改這裡並寫進 commit 訊息。每天的焦點/板塊/個股清單記進
analysis/topdown_log.csv，累積幾個月就是真正的樣本外紀錄，可以事後誠實評估這套篩選有沒有用。

三層（寫死的規則）：
1. **國家**：港股 2800.HK、美股 SPY、日股 EWJ（美元計；未有數據時退回 1321.T 日圓計）。
   動能分數 = 3/6/12 個月總報酬的平均；趨勢 = 收市在 200 日均線之上。
   焦點國家 = 趨勢向上的國家中動能分數最高者（全部向下 → 仍取最高、標「全面弱勢」）；
   第二名同樣趨勢向上且分數差 ≤ 3 個百分點 → 列為次焦點，一起向下找。
2. **板塊**：scripts/sector_rotation.py 的 point-in-time 成分股等權行業指數（yfinance 11 行業），
   按**過去 6 個月相對全體等權的超額**排名（= SECTOR_ROTATION.md 第一部分預先登記的 L=6 規格），
   取前 3（N=3）；組員 < 3 檔的「薄」組不排。
3. **個股**：焦點國家前 3 板塊的現任成分股，組內按三個動能的平均百分位排
   （12-1 個月報酬、6 個月報酬、3 個月報酬），每板塊列前 5；另標趨勢/過熱/急跌。
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

RULES = {"trend_ma": 200, "close_call_pp": 3.0, "sector_lookback": 126, "top_sectors": 3,
         "stocks_per_sector": 5, "min_members": 3, "hot_above_ma200": 0.40, "drop_1m": -0.10}

# 已判決的研究結論（RESEARCH_HANDBOOK.md / SECTOR_ROTATION.md），報告裡提醒這套篩選的證據強度
VERDICTS = {
    "hk": "行業動量 🔍（壓線過關，alpha 集中 2022 年後）；個股 12-1 動量單獨使用 ☠️；高股息 🔍、低波動 🔍",
    "us": "行業動量 不確定（alpha t 2.29 但隨機對照差一名、2013 後 t 0.22）",
    "jp": "行業動量 ☠️（alpha t 0.36）——日股的板塊排序沒有回測支持，只當描述",
}

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
    moms = [m[k] for k in ("r3", "r6", "r12")]
    m["score"] = sum(moms) / 3 if all(x is not None for x in moms) else None
    return m


def div_yield(ticker: str, as_of: date) -> float | None:
    divs, _ = md.load_actions(ticker)
    raw = md.load_raw(ticker)
    raw = [r for r in raw if r[0] <= as_of]
    if not raw:
        return None
    ttm = sum(a for d, a in divs if as_of - timedelta(days=365) < d <= as_of)
    return ttm / raw[-1][4] if raw[-1][4] > 0 else None


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
    return {t: short_name(n) for t, n in out.items()}


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

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="報告日（預設今天；各市場取當日或之前最新收市）")
    args = ap.parse_args()
    as_of = args.as_of or date.today()

    # --- 第一層：國家 ---
    country = {}
    for c, cfg in COUNTRIES.items():
        usd_t = cfg["usd"] if md.has_data(cfg["usd"]) else cfg["etf"]
        m = metrics(closes_upto(usd_t, as_of))
        m_local = metrics(closes_upto(cfg["etf"], as_of))
        refs = {t: metrics(closes_upto(t, as_of)) for t in cfg["refs"] + ([cfg["etf"]] if usd_t != cfg["etf"] else [])}
        country[c] = {"ticker": usd_t, "m": m, "local": m_local, "refs": refs,
                      "usd_note": "" if usd_t == cfg["usd"] else f"（{cfg['usd']} 尚無數據，暫用 {cfg['etf']} 本幣計）"}

    # 成分股：現任 PIT 名單的指標（廣度 + 第三層要用）
    stocks: dict[str, dict[str, dict]] = {}
    sec_of: dict[str, dict[str, str]] = {}
    names: dict[str, dict[str, str]] = {}
    for c, cfg in COUNTRIES.items():
        uni = Universe(cfg["index"])
        mem = uni.members_at(as_of)
        first = {}
        data = {}
        for t in mem:
            rows = closes_upto(t, as_of)
            if rows:
                first[t] = rows[0][0]
                data[t] = rows
        elig = uni.eligible_at(as_of, first)
        stocks[c] = {t: m for t in elig if (m := metrics(data[t]))}
        sec_of[c] = uni.sectors()[0]
        names[c] = load_names(uni.cfg["market"])
        above = [s["vs200"] > 0 for s in stocks[c].values() if s["vs200"] is not None]
        country[c]["breadth"] = sum(above) / len(above) if above else None
        country[c]["n_members"] = len(stocks[c])

    ranked = sorted(COUNTRIES, key=lambda c: -(country[c]["m"]["score"] if country[c]["m"] and country[c]["m"]["score"] is not None else -9))
    up = [c for c in ranked if country[c]["m"] and (country[c]["m"]["vs200"] or -1) > 0]
    weak_all = not up
    focus = (up or ranked)[0]
    second = None
    if len(up) >= 2 and up[0] == focus:
        gap = (country[focus]["m"]["score"] - country[up[1]]["m"]["score"]) * 100
        if gap <= RULES["close_call_pp"]:
            second = up[1]
    drill = [focus] + ([second] if second else [])

    # --- 第二層：板塊 ---
    sectors = {}
    for c, cfg in COUNTRIES.items():
        try:
            sd, rows = sector_table(cfg["index"], as_of)
        except FileNotFoundError:
            sectors[c] = (None, [])
            continue
        cnt: dict[str, int] = {}
        for t in stocks[c]:
            z = SECTOR_ZH.get(sec_of[c].get(t, ""), sec_of[c].get(t) or "未分類")
            cnt[z] = cnt.get(z, 0) + 1
        for r in rows:
            r["n"] = cnt.get(r["name"], 0)
            r["eligible"] = r["n"] >= RULES["min_members"]
        rk, rk_prev = rank_by(rows, "ex6"), rank_by(rows, "ex6_prev")
        for r in rows:
            r["rank"], r["rank_prev"] = rk.get(r["name"]), rk_prev.get(r["name"])
        rows.sort(key=lambda r: r["rank"] or 99)
        sectors[c] = (sd, rows)

    # --- 第三層：個股 ---
    picks: dict[str, list[tuple[str, list[dict]]]] = {}
    for c in drill:
        out = []
        for r in [r for r in sectors[c][1] if r["rank"]][:RULES["top_sectors"]]:
            mem = [t for t in stocks[c] if SECTOR_ZH.get(sec_of[c].get(t, ""), "") == r["name"]]
            full = [t for t in mem if all(stocks[c][t][k] is not None for k in ("r3", "r6", "r12_1"))]
            pr: dict[str, float] = {t: 0.0 for t in full}
            for k in ("r12_1", "r6", "r3"):
                order = sorted(full, key=lambda t: stocks[c][t][k])
                for i, t in enumerate(order):
                    pr[t] += (i + 0.5) / len(order) / 3
            best = sorted(full, key=lambda t: -pr[t])[:RULES["stocks_per_sector"]]
            rows = []
            for t in best:
                s = dict(stocks[c][t], ticker=t, pr=pr[t], name=names[c].get(t, ""),
                         dy=div_yield(t, as_of))
                s["n_sector"] = len(mem)
                flags = []
                if s["vs200"] is not None and s["vs200"] > 0 and s["golden"]:
                    flags.append("趨勢✓")
                elif s["vs200"] is not None and s["vs200"] < 0:
                    flags.append("⚠在200日線下")
                if s["vs200"] is not None and s["vs200"] > RULES["hot_above_ma200"]:
                    flags.append("⚠過熱")
                if s["r1"] is not None and s["r1"] < RULES["drop_1m"]:
                    flags.append("⚠近月急跌")
                s["flags"] = " ".join(flags)
                rows.append(s)
            out.append((r["name"], rows))
        picks[c] = out

    # --- 上次清單至今表現（樣本外追蹤）---
    log_path = OUT / "topdown_log.csv"
    log_rows = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8") as f:
            log_rows = list(csv.DictReader(f))
    prev = next((r for r in reversed(log_rows) if r["date"] < as_of.isoformat()), None)

    # --- 報告 ---
    L = [f"# 每日由上而下股票分析（{as_of}）\n",
         "> 國家 → 板塊 → 個股的**描述性篩選**，不是回測過的交易訊號。規則寫死（見文末），每天清單記入 "
         "`analysis/topdown_log.csv` 做樣本外追蹤。\n"]
    L.append("## 一、國家：先看哪一個市場\n")
    L.append("| 市場 | 指數 ETF | 收市日 | 1個月 | 3個月 | 6個月 | 12個月 | **動能分數** | 距200日線 | 50日>200日 | 距52週高 | 年化波動 | 成分股廣度 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in ranked:
        x, m = country[c], country[c]["m"]
        if not m:
            L.append(f"| {COUNTRIES[c]['zh']} | {x['ticker']} | 無數據 |" + " |" * 10)
            continue
        star = " 🎯" if c == focus else (" ◎" if c == second else "")
        L.append(f"| **{COUNTRIES[c]['zh']}{star}** | {x['ticker']} | {m['last']} | {pct(m['r1'])} | {pct(m['r3'])} | "
                 f"{pct(m['r6'])} | {pct(m['r12'])} | **{pct(m['score'])}** | {pct(m['vs200'])} | "
                 f"{'是' if m['golden'] else '否'} | {pct(m['dd52'])} | {pct(m['vol'], 0, False)} | "
                 f"{pct(x['breadth'], 0, False)}（{x['n_members']} 檔 >200日線） |")
    L.append("")
    L.append("參考：" + "；".join(
        f"{REF_ZH.get(t, t)} {t} 3個月 {pct(m['r3'])}、12個月 {pct(m['r12'])}"
        for c in ranked for t, m in country[c]["refs"].items() if m) + "。")
    notes = [country[c]["usd_note"] for c in COUNTRIES if country[c]["usd_note"]]
    L.append("港股以港元計（聯繫匯率≈美元）；日股用美元計的 EWJ，才跟港美股同一把尺（日圓升跌會影響港人實際回報）。"
             + "".join(notes) + "\n")
    fm = country[focus]["m"]
    if weak_all:
        concl = (f"**三地 ETF 全部在 200 日線下（全面弱勢）**。動能最高的是 {COUNTRIES[focus]['zh']}"
                 f"（{pct(fm['score'])}），仍照規則向下找，但這種環境宜輕倉、以觀察為主。")
    else:
        concl = (f"**焦點：{COUNTRIES[focus]['zh']}**——趨勢向上的市場中動能分數最高（{pct(fm['score'])}，"
                 f"高於 200 日線 {pct(fm['vs200'])}，成分股 {pct(country[focus]['breadth'], 0, False)} 在 200 日線上）。")
        if second:
            concl += (f" **次焦點：{COUNTRIES[second]['zh']}**（{pct(country[second]['m']['score'])}，"
                      f"與焦點差 ≤ {RULES['close_call_pp']:.0f} 個百分點，一併向下找）。")
        down = [COUNTRIES[c]["zh"] for c in ranked if c not in up]
        if down:
            concl += f" {'、'.join(down)}在 200 日線下，暫不深入。"
    L.append(concl + "\n")

    L.append("## 二、板塊動能排列\n")
    L.append(f"排名依據：過去 6 個月相對「全體成分股等權」的超額（預先登記的行業動量規格），前 {RULES['top_sectors']} 名向下找個股。"
             "箭頭 = 對比一個月前的排名。\n")
    for c in ranked:
        sd, rows = sectors[c]
        tag = "🎯 焦點" if c == focus else ("◎ 次焦點" if c == second else "參考")
        L.append(f"### {COUNTRIES[c]['zh']}（{Universe(COUNTRIES[c]['index']).cfg['name']}，{tag}，板塊數據至 {sd}）\n")
        L.append(f"研究狀態：{VERDICTS[c]}\n")
        if not rows:
            L.append("（沒有板塊指數；先跑 scripts/sector_rotation.py）\n")
            continue
        if c in drill:
            L.append("| 排名 | 板塊 | 檔數 | 1個月超額 | 3個月超額 | **6個月超額** | 12個月超額 | 板塊指數趨勢 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for r in rows:
                if r["rank"] and r["rank_prev"]:
                    arrow = "↑" if r["rank"] < r["rank_prev"] else ("↓" if r["rank"] > r["rank_prev"] else "→")
                    rk = f"{r['rank']}（{r['rank_prev']}{arrow}）"
                else:
                    rk = "薄" if not r["eligible"] else "—"
                top = " ⬇" if r["rank"] and r["rank"] <= RULES["top_sectors"] else ""
                tr = "—" if r["trend"] is None else ("200日線上" if r["trend"] else "200日線下")
                L.append(f"| {rk} | **{r['name']}**{top} | {r['n']} | {pct(r['ex1'])} | {pct(r['ex3'])} | "
                         f"**{pct(r['ex6'])}** | {pct(r['ex12'])} | {tr} |")
            L.append("")
        else:
            ok = [r for r in rows if r["rank"]]
            L.append("強：" + "、".join(f"{r['name']} {pct(r['ex6'])}" for r in ok[:3])
                     + "；弱：" + "、".join(f"{r['name']} {pct(r['ex6'])}" for r in ok[-3:]) + "\n")

    L.append("## 三、個股：前 3 板塊裡動能最強的成分股\n")
    L.append("組內排序 = 12-1 個月、6 個月、3 個月報酬的平均百分位（100 = 板塊內最強）。"
             f"趨勢✓ = 收市在 200 日線上且 50 日線 > 200 日線；過熱 = 高於 200 日線 {RULES['hot_above_ma200']:.0%} 以上；"
             f"近月急跌 = 1 個月跌逾 {-RULES['drop_1m']:.0%}。\n")
    for c in drill:
        L.append(f"### {COUNTRIES[c]['zh']}\n")
        for sec, rows in picks[c]:
            n_sec = rows[0]["n_sector"] if rows else 0
            L.append(f"**{sec}**（板塊內 {n_sec} 檔）\n")
            L.append("| 代碼 | 名稱 | 百分位 | 1個月 | 3個月 | 6個月 | 12-1個月 | 距200日線 | 距52週高 | 年化波動 | 股息率 | 提示 |")
            L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for s in rows:
                L.append(f"| {s['ticker']} | {s['name']} | {s['pr'] * 100:.0f} | {pct(s['r1'])} | {pct(s['r3'])} | "
                         f"{pct(s['r6'])} | {pct(s['r12_1'])} | {pct(s['vs200'])} | {pct(s['dd52'])} | "
                         f"{pct(s['vol'], 0, False)} | {pct(s['dy'], 1, False)} | {s['flags']} |")
            L.append("")

    # 與上次比較 + 上次清單至今表現
    today_picks = [t for c in drill for _, rows in picks[c] for t in [s["ticker"] for s in rows]]
    L.append("## 四、與上次報告比較\n")
    if prev:
        pf, pp = prev["focus"], [t for t in prev["picks"].split() if t]
        if pf != focus:
            L.append(f"- **焦點轉換**：{COUNTRIES.get(pf, {'zh': pf})['zh']} → {COUNTRIES[focus]['zh']}")
        else:
            L.append(f"- 焦點不變（{COUNTRIES[focus]['zh']}）")
        for c in COUNTRIES:
            old = [x for x in prev.get(f"{c}_top", "").split("|") if x]
            new = [r["name"] for r in sectors[c][1] if r["rank"]][:RULES["top_sectors"]]
            if old and old != new:
                L.append(f"- {COUNTRIES[c]['zh']}前 3 板塊：{'、'.join(old)} → {'、'.join(new)}")
        added = [t for t in today_picks if t not in pp]
        dropped = [t for t in pp if t not in today_picks]
        if added or dropped:
            L.append(f"- 個股清單新進：{'、'.join(added) or '無'}；移出：{'、'.join(dropped) or '無'}")
        # 上次清單從上次報告日收市至今
        pd_ = date.fromisoformat(prev["date"])
        rets, bench = [], {}
        for t in pp:
            rows = closes_upto(t, as_of)
            ds = [d for d, _ in rows]
            i = bisect.bisect_right(ds, pd_) - 1
            if i >= 0 and rows[-1][0] > rows[i][0]:
                rets.append(rows[-1][1] / rows[i][1] - 1)
        if rets:
            etf = country[pf]["ticker"] if pf in country else None
            b = None
            if etf:
                rows = closes_upto(etf, as_of)
                ds = [d for d, _ in rows]
                i = bisect.bisect_right(ds, pd_) - 1
                b = rows[-1][1] / rows[i][1] - 1 if i >= 0 else None
            L.append(f"- 上次（{prev['date']}）清單 {len(rets)} 檔等權至今 {pct(sum(rets) / len(rets))}"
                     + (f"，同期 {etf} {pct(b)}" if b is not None else "") + "（單次、未扣成本，只供追蹤）")
    else:
        L.append("- 第一份報告，沒有可比較的上次紀錄。")
    L.append("")

    L.append("## 五、規則與限制（寫死，不按結果調）\n")
    L.append(f"- 國家：動能分數 = 3/6/12 個月總報酬平均；焦點 = 收市在 200 日線上的市場中分數最高者；"
             f"次焦點 = 第二名也在 200 日線上且分數差 ≤ {RULES['close_call_pp']:.0f} 個百分點")
    L.append(f"- 板塊：point-in-time 成分股等權行業指數，6 個月超額排名取前 {RULES['top_sectors']}；組員 < {RULES['min_members']} 檔不排")
    L.append(f"- 個股：前 {RULES['top_sectors']} 板塊內 12-1/6/3 個月報酬平均百分位，每板塊前 {RULES['stocks_per_sector']} 名")
    L.append("- 行業分類是 yfinance **今天的**分類；成分股是指數現任名單（不含已剔除的弱勢股）")
    L.append("- 研究結論（RESEARCH_HANDBOOK.md）：只有港股行業動量過了預先登記門檻（🔍，壓線）；美股不確定、日股 ☠️；"
             "港股個股動量單獨使用 ☠️。**這份清單是研究/觀察起點，不是買入建議**")
    L.append("- 美股收市在亞洲早上才有數據；三地收市日可能不同（見第一節「收市日」）")

    OUT.mkdir(parents=True, exist_ok=True)
    text = "\n".join(L) + "\n"
    (OUT / "DAILY_TOPDOWN.md").write_text(text, encoding="utf-8")
    (OUT / "archive").mkdir(exist_ok=True)
    (OUT / "archive" / f"{as_of}.md").write_text(text, encoding="utf-8")

    # 樣本外紀錄
    rec = {"date": as_of.isoformat(), "focus": focus, "second": second or "", "weak_all": int(weak_all),
           **{f"{c}_score": f"{country[c]['m']['score']:.4f}" if country[c]["m"] and country[c]["m"]["score"] is not None else ""
              for c in COUNTRIES},
           **{f"{c}_top": "|".join([r["name"] for r in sectors[c][1] if r["rank"]][:RULES["top_sectors"]])
              for c in COUNTRIES},
           "picks": " ".join(today_picks)}
    log_rows = [r for r in log_rows if r["date"] != rec["date"]] + [rec]
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec))
        w.writeheader()
        for r in sorted(log_rows, key=lambda r: r["date"]):
            w.writerow({k: r.get(k, "") for k in rec})

    # Telegram 摘要
    tg = [f"📊 每日由上而下分析 {as_of}",
          "國家動能（3/6/12月平均）：" + "、".join(
              f"{COUNTRIES[c]['zh']} {pct(country[c]['m']['score'])}{'' if (country[c]['m']['vs200'] or -1) > 0 else '（200日線下）'}"
              for c in ranked if country[c]["m"]),
          ("⚠ 全面弱勢，" if weak_all else "") + f"🎯 焦點：{COUNTRIES[focus]['zh']}"
          + (f"　◎ 次焦點：{COUNTRIES[second]['zh']}" if second else "")]
    for c in drill:
        ok = [r for r in sectors[c][1] if r["rank"]]
        tg.append(f"{COUNTRIES[c]['zh']}板塊（6月超額）強：" + "、".join(f"{r['name']} {pct(r['ex6'])}" for r in ok[:3])
                  + "；弱：" + "、".join(f"{r['name']} {pct(r['ex6'])}" for r in ok[-2:]))
        for sec, rows in picks[c]:
            tg.append(f"・{sec}：" + "、".join(
                f"{s['ticker'].replace('.HK', '').replace('.T', '')} {s['name'][:10]}{'⚠' if '⚠' in s['flags'] else ''}"
                for s in rows[:3]))
    tg.append("描述性篩選，非買入建議；全文 analysis/DAILY_TOPDOWN.md")
    (OUT / "tg_topdown.txt").write_text("\n".join(tg) + "\n", encoding="utf-8")
    print("\n".join(tg))


if __name__ == "__main__":
    main()
