"""篩選器前瞻報酬評分卡（screener scorecard）——把「找機會」本身當成 harness 來打分。

讀 VCP 分支（claude/gifted-carson-v2tvhw）每日產生的篩選名單：
  analysis/newhighs/<收市日>.csv   200 日線上 + 12/9/6/3 個月新高（daily_topdown.py）
  analysis/vcp/<收市日>.csv        VCP 收縮型態（setup / breakout）
以同一分支 data/equities/<市場>/<代碼>/prices_<年>.csv 的日線算每一檔被選出之後的前瞻報酬，
扣掉同市場基準（指數：美股 ^GSPC、港股 ^HSI、日股 ^N225；指數檔缺才退回 SPY／2800.HK／1321.T）得到超額報酬，再跟「同日全部成分股」的
隨機對照比較。只用標準庫。

## 預先登記（2026-10-13，寫在看到任何結果之前）

* **進場**：名單在收市日翌日早上發出，所以進場價 = 收市日之後第一個交易日的**開市價**。
* **出場**：進場日起第 h 個交易日的**收市價**，h ∈ {5, 10, 20}；主判定用 **h = 10**。
* **超額報酬** = 個股報酬 − 同期基準報酬（同一段日期、同樣開市進收市出）。
* **命中** = 超額報酬 > 0。篩選器分數 = 命中率（對應 harness_learning 的 Eq.3：平均分）。
* **隨機對照** = 同一個收市日、同一市場的全部指數成分股（point-in-time 名單）用同一條公式算出的命中率與
  平均超額報酬。這是「亂選」的基準線。
* **判決（每個市場、每個篩選器分開）**，h = 10 且已評分的名單 ≥ 60 檔才判：
    - 🔍 命中率比對照高 ≥ 5 個百分點、兩比例 z ≥ 2、平均超額報酬 t ≥ 2 → 值得進回測
    - ☠️ 命中率不高於對照（差 ≤ 0）→ 棄用
    - ⏳ 其他 → 繼續累積
  未滿 60 檔一律 ⏳，只列數字。
* **不得**在看到結果後改動進出場定義、h、門檻或對照組；要改就另開一個新篩選器名稱重新累積。

## 用法

    python3 scripts/screener_scorecard.py --src <VCP 分支抽出的目錄> --out research/screener_scorecard

<src> 要有 analysis/newhighs、analysis/vcp、data/equities/<市場>/<代碼>/prices_*.csv、
universes/sp500/membership.csv、universes/n225/membership.csv、scripts/universe_hsi_live.txt。
GitHub Actions（.github/workflows/screener_scorecard.yml）每週用 `git archive` 從該分支抽這些檔。

輸出：
  <out>/newhighs_picks.csv、<out>/vcp_picks.csv   每檔一列，含特徵與各 h 的報酬／超額報酬（未到期留空）
  <out>/SCORECARD.md                              摘要表、對照、判決
  <out>/<screener>_report.txt                     harness_learning 風格的執行報告（失敗案例＋特徵），給 proposer 讀
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HORIZONS = (5, 10, 20)
MAIN_H = 10
MIN_N = 60
# 基準先用指數（跟成分股一樣是不含股息的價格指數）；ETF 只做備援——1321.T 的歷史有拆股未調整的痕跡
BENCH = {"us": ("_GSPC", "SPY"), "hk": ("_HSI", "2800.HK"), "jp": ("_N225", "1321.T")}
MARKET_ZH = {"us": "美股", "hk": "港股", "jp": "日股"}


# ---------------------------------------------------------------- 價格
@dataclass
class Series:
    dates: list[date]
    open: list[float]
    close: list[float]

    def idx_after(self, d: date) -> int | None:
        """第一個 > d 的交易日索引（進場日）。"""
        i = bisect.bisect_right(self.dates, d)
        return i if i < len(self.dates) else None

    def idx_on_or_before(self, d: date) -> int | None:
        i = bisect.bisect_right(self.dates, d) - 1
        return i if i >= 0 else None


class Prices:
    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[tuple[str, str], Series | None] = {}

    def bench(self, market: str) -> Series | None:
        for t in BENCH[market]:
            s = self.get(market, t)
            if s is not None:
                return s
        return None

    def get(self, market: str, yahoo_ticker: str) -> Series | None:
        key = (market, yahoo_ticker)
        if key in self.cache:
            return self.cache[key]
        d = self.root / "data" / "equities" / market / yahoo_ticker.replace("^", "_")
        rows: dict[date, tuple[float, float]] = {}
        for p in sorted(d.glob("prices_*.csv")) if d.is_dir() else []:
            with open(p, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        o, c = float(r["Open"]), float(r["Close"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if o > 0 and c > 0:
                        rows[date.fromisoformat(r["Date"])] = (o, c)
        if not rows:
            self.cache[key] = None
            return None
        ds = sorted(rows)
        s = Series(ds, [rows[x][0] for x in ds], [rows[x][1] for x in ds])
        self.cache[key] = s
        return s


def forward(stock: Series, bench: Series | None, signal_day: date, h: int) -> tuple[float, float | None, bool] | None:
    """回傳 (個股報酬, 超額報酬 或 None, 是否已到期)。進場 = 翌日開市；出場 = 進場日起第 h 個交易日收市。
    還沒走到 h 天 → (None, None, False)。"""
    e = stock.idx_after(signal_day)
    if e is None:
        return None, None, False
    x = e + h
    if x >= len(stock.dates):
        return None, None, False
    r = stock.close[x] / stock.open[e] - 1.0
    if bench is None:
        return r, None, True
    be = bench.idx_on_or_before(stock.dates[e])
    bx = bench.idx_on_or_before(stock.dates[x])
    if be is None or bx is None or bench.dates[be] < signal_day:
        return r, None, True
    br = bench.close[bx] / bench.open[be] - 1.0
    return r, r - br, True


# ---------------------------------------------------------------- 成分股（對照組）
def load_membership(path: Path) -> list[tuple[str, date, date | None]]:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            start = date.fromisoformat(r["start"]) if r.get("start") else date(1900, 1, 1)
            end = date.fromisoformat(r["end"]) if r.get("end") else None
            out.append((r["ticker"], start, end))
    return out


def universe_on(members: list[tuple[str, date, date | None]], d: date) -> list[str]:
    return [t for t, s, e in members if s <= d and (e is None or e > d)]


def load_universes(src: Path) -> dict[str, "callable"]:
    us = load_membership(src / "universes" / "sp500" / "membership.csv")
    jp = load_membership(src / "universes" / "n225" / "membership.csv")
    hk_path = src / "scripts" / "universe_hsi_live.txt"
    hk = [ln.strip() for ln in hk_path.read_text(encoding="utf-8").splitlines()
          if ln.strip() and not ln.startswith("#")] if hk_path.exists() else []
    return {
        "us": lambda d: universe_on(us, d),
        "jp": lambda d: universe_on(jp, d),
        "hk": lambda d: hk,  # 只有現行名單，近一兩個月的對照足夠
    }


# ---------------------------------------------------------------- 名單
@dataclass
class Pick:
    screener: str
    signal_day: date
    market: str
    ticker: str
    yahoo: str
    name: str
    features: dict = field(default_factory=dict)
    ret: dict = field(default_factory=dict)      # h -> 個股報酬
    excess: dict = field(default_factory=dict)   # h -> 超額
    scored: dict = field(default_factory=dict)   # h -> bool（到期了沒）
    note: str = ""


def load_newhighs(src: Path) -> list[Pick]:
    picks = []
    for p in sorted((src / "analysis" / "newhighs").glob("20*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                # 同一檔同一天在 12/9/6/3 每個窗口各一列；只取「最長窗口」那列，一檔一天一列
                if r["window_months"] != r["longest_months"]:
                    continue
                picks.append(Pick(
                    "newhighs", date.fromisoformat(r["date"]), r["market"], r["ticker"], r["yahoo_ticker"], r["name"],
                    {"window": int(r["longest_months"]), "sector": r["sector"],
                     "pct_above_ma200": float(r["pct_above_ma200"]), "streak": int(r["streak_longest"] or 1)},
                ))
    return picks


def load_vcp(src: Path) -> list[Pick]:
    picks = []
    for p in sorted((src / "analysis" / "vcp").glob("20*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                picks.append(Pick(
                    "vcp", date.fromisoformat(r["date"]), r["market"], r["ticker"], r["yahoo_ticker"], r["name"],
                    {"status": r["status"], "n_contractions": r["n_contractions"], "depths_pct": r["depths_pct"],
                     "pct_vs_pivot": r["pct_vs_pivot"], "stop_pct": r["stop_pct"]},
                ))
    return picks


# ---------------------------------------------------------------- 計分
def score_picks(picks: list[Pick], prices: Prices) -> None:
    for pk in picks:
        s = prices.get(pk.market, pk.yahoo)
        b = prices.bench(pk.market)
        if s is None:
            pk.note = "no price data"
            continue
        for h in HORIZONS:
            r, ex, done = forward(s, b, pk.signal_day, h)
            pk.scored[h] = done
            if done:
                pk.ret[h] = r
                pk.excess[h] = ex


def control_stats(signal_days_by_market: dict[str, set[date]], universes, prices: Prices, h: int) -> dict[str, dict]:
    """同日全部成分股的命中率與平均超額（pooled）。"""
    out = {}
    for m, days in signal_days_by_market.items():
        b = prices.bench(m)
        ex_all: list[float] = []
        for d in sorted(days):
            for t in universes[m](d):
                s = prices.get(m, t)
                if s is None:
                    continue
                _, ex, done = forward(s, b, d, h)
                if done and ex is not None:
                    ex_all.append(ex)
        out[m] = summarize(ex_all)
    return out


def summarize(xs: list[float]) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0, "hit": None, "mean": None, "median": None, "t": None}
    hit = sum(1 for x in xs if x > 0) / n
    mean = statistics.fmean(xs)
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 and n > 1 else None
    return {"n": n, "hit": hit, "mean": mean, "median": statistics.median(xs), "t": t}


def two_prop_z(k: int, n: int, p0: float | None) -> float | None:
    if n == 0 or p0 is None or p0 <= 0 or p0 >= 1:
        return None
    return (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def verdict(pick_stats: dict, ctrl: dict) -> str:
    n = pick_stats["n"]
    if n < MIN_N or ctrl["n"] == 0:
        return "⏳"
    diff = pick_stats["hit"] - ctrl["hit"]
    z = two_prop_z(round(pick_stats["hit"] * n), n, ctrl["hit"])
    t = pick_stats["t"]
    if diff >= 0.05 and (z or 0) >= 2 and (t or 0) >= 2:
        return "🔍"
    if diff <= 0:
        return "☠️"
    return "⏳"


# ---------------------------------------------------------------- 輸出
def pct(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def num(x: float | None, d: int = 2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def write_picks_csv(picks: list[Pick], path: Path) -> None:
    feat_keys = sorted({k for p in picks for k in p.features})
    cols = ["screener", "signal_day", "market", "ticker", "yahoo_ticker", "name", *feat_keys]
    for h in HORIZONS:
        cols += [f"ret_{h}", f"excess_{h}"]
    cols.append("note")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in sorted(picks, key=lambda p: (p.signal_day, p.market, p.ticker)):
            row = [p.screener, p.signal_day.isoformat(), p.market, p.ticker, p.yahoo, p.name]
            row += [p.features.get(k, "") for k in feat_keys]
            for h in HORIZONS:
                row += [f"{p.ret[h]:.5f}" if h in p.ret else "",
                        f"{p.excess[h]:.5f}" if p.excess.get(h) is not None else ""]
            row.append(p.note)
            w.writerow(row)


def group(picks: list[Pick], key) -> dict:
    g = defaultdict(list)
    for p in picks:
        g[key(p)].append(p)
    return dict(g)


def excess_list(picks: list[Pick], h: int) -> list[float]:
    return [p.excess[h] for p in picks if p.excess.get(h) is not None]


def feature_str(p: Pick) -> str:
    return ", ".join(f"{k}={v}" for k, v in p.features.items())


def build_report(screener: str, picks: list[Pick], ctrl: dict[str, dict], h: int = MAIN_H, max_failures: int = 8) -> str:
    """harness_learning 風格：Score 一行 + 失敗案例（最差超額）+ 特徵。給 proposer 讀。"""
    done = [p for p in picks if p.excess.get(h) is not None]
    pend = [p for p in picks if p.excess.get(h) is None and not p.note]
    st = summarize(excess_list(picks, h))
    lines = [f"Screener: {screener}   horizon: {h} trading days   entry: next open, exit: close",
             f"Score (hit rate, excess>0): {num(st['hit'], 3)} on {st['n']} scored picks "
             f"({len(pend)} pending, {sum(1 for p in picks if p.note)} no data); mean excess {pct(st['mean'])}, "
             f"median {pct(st['median'])}, t {num(st['t'])}"]
    for m in sorted(ctrl):
        c = ctrl[m]
        lines.append(f"Control {MARKET_ZH[m]} (all constituents, same days): hit {num(c['hit'], 3)} "
                     f"mean excess {pct(c['mean'])} n={c['n']}")
    worst = sorted(done, key=lambda p: p.excess[h])[:max_failures]
    for i, p in enumerate(worst, 1):
        lines += ["", f"--- FAILED {i} ---",
                  f"Pick: {p.signal_day} {MARKET_ZH[p.market]} {p.ticker} {p.name}",
                  f"Features: {feature_str(p)}",
                  f"Return {h}d: {pct(p.ret.get(h))}  Excess: {pct(p.excess.get(h))}"]
    best = sorted(done, key=lambda p: -p.excess[h])[:3]
    for i, p in enumerate(best, 1):
        lines += ["", f"--- BEST {i} ---",
                  f"Pick: {p.signal_day} {MARKET_ZH[p.market]} {p.ticker} {p.name}",
                  f"Features: {feature_str(p)}",
                  f"Return {h}d: {pct(p.ret.get(h))}  Excess: {pct(p.excess.get(h))}"]
    return "\n".join(lines) + "\n"


def write_scorecard(out: Path, all_picks: dict[str, list[Pick]], ctrls: dict[str, dict[int, dict[str, dict]]],
                    as_of: date, src_note: str) -> None:
    L = [f"# 篩選器前瞻報酬評分卡（更新 {as_of}）", "",
         "> 把「找機會」當成 harness 打分：每檔被選出的股票，翌日開市買入、第 h 個交易日收市賣出，",
         "> 扣同市場價格指數（美股 ^GSPC、港股 ^HSI、日股 ^N225）得超額報酬；對照組 = 同日全部成分股。",
         f"> 規則、門檻與判決條件**預先登記**在 `scripts/screener_scorecard.py` 檔頭，不按結果調整。主判定 h = {MAIN_H}，≥ {MIN_N} 檔才判。",
         f"> 來源：{src_note}。價格為拆股還原、未含股息的收市價，5–20 日內股息影響可忽略。", "",
         "判決：🔍 值得進回測　☠️ 棄用　⏳ 繼續累積（樣本未滿或未達門檻）", ""]
    for scr, picks in all_picks.items():
        L += [f"## {scr}", ""]
        nodata = [p for p in picks if p.note]
        L.append(f"名單合計 {len(picks)} 檔（{min(p.signal_day for p in picks) if picks else '—'} → "
                 f"{max(p.signal_day for p in picks) if picks else '—'}），無價格數據 {len(nodata)} 檔。")
        L += ["", "### 命中率對照（h = 進場後交易日數）", "",
              "| 市場 | h | 已評分 | 待到期 | 命中率 | 對照命中率 | 差（pp） | z | 平均超額 | 對照平均超額 | 中位超額 | t | 判決 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        by_m = group(picks, lambda p: p.market)
        for m in ("us", "hk", "jp"):
            ps = by_m.get(m, [])
            for h in HORIZONS:
                st = summarize(excess_list(ps, h))
                pend = sum(1 for p in ps if p.excess.get(h) is None and not p.note)
                c = ctrls[scr][h].get(m, {"n": 0, "hit": None, "mean": None})
                diff = (st["hit"] - c["hit"]) * 100 if st["hit"] is not None and c["hit"] is not None else None
                z = two_prop_z(round((st["hit"] or 0) * st["n"]), st["n"], c["hit"]) if st["n"] else None
                v = verdict(st, c) if h == MAIN_H else ""
                L.append(f"| {MARKET_ZH[m]} | {h} | {st['n']} | {pend} | {num(st['hit'], 3)} | {num(c['hit'], 3)} | "
                         f"{'—' if diff is None else f'{diff:+.1f}'} | {num(z)} | {pct(st['mean'])} | {pct(c['mean'])} | "
                         f"{pct(st['median'])} | {num(st['t'])} | {v} |")
        # 全部市場合計（只看 h=MAIN_H）
        st = summarize(excess_list(picks, MAIN_H))
        L += ["", f"三地合計 h={MAIN_H}：已評分 {st['n']}，命中率 {num(st['hit'], 3)}，平均超額 {pct(st['mean'])}，t {num(st['t'])}。", ""]
        # 按特徵切
        if scr == "newhighs":
            L += ["### 按新高窗口（h = 10）", "", "| 窗口 | 已評分 | 命中率 | 平均超額 | 中位超額 |", "|---|---:|---:|---:|---:|"]
            for w in (12, 9, 6, 3):
                st = summarize(excess_list([p for p in picks if p.features.get("window") == w], MAIN_H))
                L.append(f"| {w} 個月 | {st['n']} | {num(st['hit'], 3)} | {pct(st['mean'])} | {pct(st['median'])} |")
            L += ["", "### 首次出現 vs 連續（h = 10；streak = 連續第幾天最長窗口不變）", "",
                  "| 組 | 已評分 | 命中率 | 平均超額 |", "|---|---:|---:|---:|"]
            for label, cond in (("首次（streak = 1）", lambda p: p.features.get("streak") == 1),
                                ("連續（streak ≥ 2）", lambda p: p.features.get("streak", 1) >= 2)):
                st = summarize(excess_list([p for p in picks if cond(p)], MAIN_H))
                L.append(f"| {label} | {st['n']} | {num(st['hit'], 3)} | {pct(st['mean'])} |")
            L += ["", "### 按板塊（h = 10，已評分 ≥ 5 檔才列）", "", "| 板塊 | 已評分 | 命中率 | 平均超額 |", "|---|---:|---:|---:|"]
            for sec, ps in sorted(group(picks, lambda p: p.features.get("sector", "")).items(),
                                  key=lambda kv: -len(kv[1])):
                st = summarize(excess_list(ps, MAIN_H))
                if st["n"] >= 5:
                    L.append(f"| {sec} | {st['n']} | {num(st['hit'], 3)} | {pct(st['mean'])} |")
        if scr == "vcp":
            L += ["### 按狀態（h = 10）", "", "| 狀態 | 已評分 | 命中率 | 平均超額 |", "|---|---:|---:|---:|"]
            for stt, ps in sorted(group(picks, lambda p: p.features.get("status", "")).items()):
                st = summarize(excess_list(ps, MAIN_H))
                L.append(f"| {stt} | {st['n']} | {num(st['hit'], 3)} | {pct(st['mean'])} |")
        L += ["", f"執行報告（失敗案例＋特徵，給 proposer 讀）：`research/screener_scorecard/{scr}_report.txt`；"
                  f"逐檔明細：`research/screener_scorecard/{scr}_picks.csv`。", ""]
    L += ["## 怎麼讀", "",
          "- 對照組是「同一天亂選一檔成分股」的期望值。篩選器要有用，命中率與平均超額都要穩定高於對照，不是高於零。",
          "- 同一檔股票連續多天上榜會被算多次（每天一個獨立的進場決定）；「首次出現」那一欄是去掉重複的版本。",
          "- 樣本之間高度相關（同一週的名單一起漲跌），t 值會偏大；所以判決門檻定在 ≥ 60 檔而且要連過三關。",
          "- 這張卡只回答「名單有沒有資訊」，沒有倉位、止損、成本；值得進回測的才去做完整回測。", ""]
    (out / "SCORECARD.md").write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="VCP 分支抽出的目錄（含 analysis/、data/equities/、universes/）")
    ap.add_argument("--out", default=Path("research/screener_scorecard"), type=Path)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--src-note", default="VCP 分支 claude/gifted-carson-v2tvhw 的 analysis/ 與 data/equities/")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    prices = Prices(a.src)
    universes = load_universes(a.src)
    all_picks = {"newhighs": load_newhighs(a.src), "vcp": load_vcp(a.src)}
    ctrls: dict[str, dict[int, dict[str, dict]]] = {}
    for scr, picks in all_picks.items():
        score_picks(picks, prices)
        days = defaultdict(set)
        for p in picks:
            days[p.market].add(p.signal_day)
        ctrls[scr] = {h: control_stats(days, universes, prices, h) for h in HORIZONS}
        write_picks_csv(picks, a.out / f"{scr}_picks.csv")
        (a.out / f"{scr}_report.txt").write_text(build_report(scr, picks, ctrls[scr][MAIN_H]), encoding="utf-8")
        st = summarize(excess_list(picks, MAIN_H))
        print(f"[{scr}] picks={len(picks)} scored(h={MAIN_H})={st['n']} hit={num(st['hit'], 3)} mean_excess={pct(st['mean'])}")
    write_scorecard(a.out, all_picks, ctrls, a.as_of, a.src_note)
    print(f"wrote {a.out / 'SCORECARD.md'}")


if __name__ == "__main__":
    main()
