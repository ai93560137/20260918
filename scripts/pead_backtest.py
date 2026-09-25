#!/usr/bin/env python3
"""財報公告後漂移（PEAD）回測：照 research/news_trade/STRATEGY.md 預先登記的規格跑一次。

事件：data/news/sp500_earnings_events.csv.gz（SEC 8-K Item 2.02，申報當時的 S&P 500 成分股）
價格：gifted-carson 分支的 data/equities/us（含息還原）與 universes/（成分股、改名）

規則（主規格）
- t0：session = pre → 申報當天（遇假日順延）；regular / post → 下一個交易日
- 同一公司（CIK）30 天內多份 2.02 只算第一份
- 訊號：AR = 個股 [t0−1 收 → t0+1 收] − 等權 S&P 500 同期 ≥ +5%，且 t0 成交量 ≥ 過去 50 日平均 × 2
- t0+2 開盤進場，持有 60 個交易日後開盤出場；單邊成本 10 bps
- 組合：持有中部位每日開盤重設為等權；同時最多 30 檔，當天新訊號依 AR 由大到小補位

判決 A1–A7 與診斷見 STRATEGY.md §4；報告寫到 data/news/backtest/README.md。
"""
import argparse
import csv
import gzip
import math
import os
import random
import sys
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pelosi_backtest as bt  # noqa: E402  共用：價格讀取、績效、圖
import insider_backtest as ib  # noqa: E402  共用：成分股、改名、等權基準、t 值

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "data", "news", "sp500_earnings_events.csv.gz")
OUT_DIR = os.path.join(ROOT, "data", "news", "backtest")
DEFAULT_EQ_ROOT = os.path.join(ROOT, "_equities")

# 預先登記的參數（不要看結果後改）
START = date(2006, 1, 1)
DEDUPE_DAYS = 30
AR_MIN = 0.05
VOL_MULT = 2.0
VOL_LOOKBACK = 50
VOL_MIN_OBS = 40
HOLD = 60
MAX_POS = 30
COST = 0.001
GRID_AR = [0.03, 0.05, 0.08]
GRID_HOLD = [20, 40, 60]
N_RANDOM = 200
SEED = 20260925
RECENT_FROM = date(2016, 1, 1)
WINDOWS = [(2, 7, "t0+2 → t0+7"), (7, 22, "t0+7 → t0+22"), (22, 62, "t0+22 → t0+62")]


# -----------------------------------------------------------------------------
# 數據
# -----------------------------------------------------------------------------
def load_events(path=EVENTS):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_volume(eq_dir, t, start):
    """{日期: 成交量}；成交量缺或為 0 的日子不收。"""
    folder = os.path.join(eq_dir, t)
    out = {}
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("prices_") and name.endswith(".csv")):
            continue
        try:
            if int(name[7:11]) < start.year:
                continue
        except ValueError:
            continue
        for r in bt._read_csv_rows(os.path.join(folder, name)):
            try:
                v = float(r.get("Volume") or 0)
                if v > 0:
                    out[date.fromisoformat(r["Date"])] = v
            except ValueError:
                continue
    return out


def event_t0(cal, acc_et, session):
    """回傳 t0 在交易日曆的索引。"""
    d = date.fromisoformat(acc_et[:10])
    return bisect_left(cal, d) if session == "pre" else bisect_right(cal, d)


def dedupe(events):
    """同一 CIK 30 天內只留第一份（以已保留的那份起算）。"""
    last, out = {}, []
    for e in sorted(events, key=lambda e: e["acceptance"]):
        d = date.fromisoformat(e["acceptance_et"][:10])
        k = e["cik"]
        if k in last and (d - last[k]).days <= DEDUPE_DAYS:
            continue
        last[k] = d
        out.append(e)
    return out


# -----------------------------------------------------------------------------
# 事件 → 反應（AR、量比）
# -----------------------------------------------------------------------------
def reactions(events, cal, prices, volumes, ew, first_price):
    """每個事件算 AR 與量比；價格不足或代號重用的事件記原因後略過。"""
    out, skip = [], {}

    def drop(why):
        skip[why] = skip.get(why, 0) + 1

    ci = {d: i for i, d in enumerate(cal)}
    for e in events:
        t = e["price_ticker"]
        i0 = event_t0(cal, e["acceptance_et"], e["session"])
        if i0 < 1 or i0 + 2 >= len(cal) or cal[i0] < START:
            drop("期間外")
            continue
        p = prices.get(t)
        if p is None:
            drop("缺價格")
            continue
        ms = date.fromisoformat(e["member_start"])
        if first_price[t] > ms + timedelta(days=ib.GRACE_DAYS):
            drop("代號重用")
            continue
        a, b, c = (p.idx.get(cal[i0 + k]) for k in (-1, 0, 1))
        if None in (a, b, c):
            drop("t0 前後缺價")
            continue
        ret = p.close[c] / p.close[a] - 1
        ew_ret = ew.close[i0 + 1] / ew.close[i0 - 1] - 1
        vol = volumes.get(t, {})
        v0 = vol.get(cal[i0])
        hist = [vol[cal[j]] for j in range(max(0, i0 - VOL_LOOKBACK), i0) if cal[j] in vol]
        if not v0 or len(hist) < VOL_MIN_OBS:
            drop("成交量不足")
            continue
        out.append({"ticker": t, "cik": e["cik"], "company": e["company"], "accession": e["accession"],
                    "session": e["session"], "acc_et": e["acceptance_et"], "i0": i0, "t0": cal[i0],
                    "ar": ret - ew_ret, "vol_ratio": v0 / (sum(hist) / len(hist))})
    assert all(cal[x["i0"]] in ci for x in out)
    return out, skip


# -----------------------------------------------------------------------------
# 交易
# -----------------------------------------------------------------------------
def make_trade(p, cal, i_entry, hold, ew):
    """cal[i_entry] 開盤進、cal[i_entry+hold] 開盤出；下市則以最後收盤出。含成本。"""
    if i_entry >= len(cal):
        return None
    j0 = p.idx.get(cal[i_entry])
    if j0 is None:
        return None
    i_exit = i_entry + hold
    if i_exit < len(cal) and cal[i_exit] in p.idx:
        px1, exit_day, how = p.open[p.idx[cal[i_exit]]], cal[i_exit], "open"
    elif i_exit < len(cal) or p.days[-1] < cal[-1]:
        # 出場日沒有價格（下市、停牌）：用出場日前最後一個收盤
        k = bisect_right(p.days, cal[min(i_exit, len(cal) - 1)]) - 1
        if k < j0:
            return None
        px1, exit_day, how = p.close[k], p.days[k], "close"
    else:
        return None  # 還在持有中（資料尾端），不算已完成交易
    gross = px1 / p.open[j0]
    ret = gross * (1 - COST) ** 2 - 1
    ew_ret = bt.bench_return(ew, cal[i_entry], exit_day, how == "open")
    return {"entry_i": i_entry, "entry_day": cal[i_entry], "exit_day": exit_day, "exit_how": how,
            "ret": ret, "gross": gross - 1, "ew": ew_ret}


def build_trades(signals, prices, cal, hold, ew):
    out = []
    for s in signals:
        tr = make_trade(prices[s["ticker"]], cal, s["i0"] + 2, hold, ew)
        if tr:
            tr.update(s)
            out.append(tr)
    return out


def select_positions(trades):
    """模擬 30 檔上限：同一天進場的依 AR 由大到小補位。回傳實際持有的交易。"""
    by_day = {}
    for x in trades:
        by_day.setdefault(x["entry_day"], []).append(x)
    held, taken = [], []
    for d in sorted(by_day):
        held = [x for x in held if x["exit_day"] > d]
        room = MAX_POS - len(held)
        for x in sorted(by_day[d], key=lambda x: -x["ar"])[:max(room, 0)]:
            held.append(x)
            taken.append(x)
    return taken


def simulate(taken, prices, cal):
    """每日：隔夜（前收→開）→ 開盤出場、進場、重設等權 → 盤中（開→收）。
    回傳 (淨值曲線, 年換手)。沒有持股的日子持現金（報酬 0）。重設等權的微調不計成本。"""
    by_entry = {}
    for x in taken:
        by_entry.setdefault(x["entry_day"], []).append(x)
    held = {}  # id → [lot, value, last_px]
    cash, curve, traded = 1.0, [], 0.0
    start = min(by_entry) if by_entry else None
    for d in cal:
        if start is None or d < start:
            continue
        # 隔夜與開盤出場
        for k, (lot, val, last) in list(held.items()):
            p = prices[lot["ticker"]]
            i = p.idx.get(d)
            if i is None:
                continue
            val *= p.open[i] / last
            if lot["exit_how"] == "open" and d >= lot["exit_day"]:
                traded += val
                cash += val * (1 - COST)
                del held[k]
            else:
                held[k] = [lot, val, p.open[i]]
        # 進場並重設等權
        new = by_entry.get(d, [])
        n = len(held) + len(new)
        if n:
            total = cash + sum(v for _, v, _ in held.values())
            w = total / n
            new_ids = {id(lot) for lot in new}
            for lot in new:
                p = prices[lot["ticker"]]
                traded += w
                held[id(lot)] = [lot, w * (1 - COST), p.open[p.idx[d]]]
            for k, (lot, val, last) in held.items():
                if k not in new_ids:
                    held[k] = [lot, w, last]
            cash = 0.0
        # 盤中與以收盤出場（下市）
        for k, (lot, val, last) in list(held.items()):
            p = prices[lot["ticker"]]
            i = p.idx.get(d)
            if i is not None:
                val *= p.close[i] / last
                held[k] = [lot, val, p.close[i]]
            if lot["exit_how"] == "close" and d >= lot["exit_day"]:
                traded += val
                cash += val * (1 - COST)
                del held[k]
        nav = cash + sum(v for _, v, _ in held.values())
        curve.append((d, nav, bool(held)))
    years = (curve[-1][0] - curve[0][0]).days / 365.25 if len(curve) > 1 else 1
    # 年換手（單邊）：買賣總額 ÷ 2 ÷ 平均淨值 ÷ 年數
    avg_nav = sum(c[1] for c in curve) / len(curve) if curve else 1
    return curve, traded / 2 / avg_nav / years


# -----------------------------------------------------------------------------
# 統計
# -----------------------------------------------------------------------------
def monthly_returns(curve):
    last = {}
    for d, v, _ in curve:
        last[(d.year, d.month)] = v
    keys = sorted(last)
    return {k: last[k] / last[p] - 1 for p, k in zip(keys, keys[1:])}


def capm(port_m, spy_m):
    ks = sorted(set(port_m) & set(spy_m))
    y = [port_m[k] for k in ks]
    x = [spy_m[k] for k in ks]
    n = len(ks)
    if n < 12:
        return {}
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    alpha = my - beta * mx
    resid = [b - alpha - beta * a for a, b in zip(x, y)]
    s2 = sum(r * r for r in resid) / (n - 2)
    se_a = math.sqrt(s2 * (1 / n + mx * mx / sxx))
    return {"alpha_m": alpha, "alpha_y": (1 + alpha) ** 12 - 1, "beta": beta, "t": alpha / se_a, "n": n}


def random_benchmark(taken, mem_by_day, prices, cal, hold, ew, rng):
    """同一天、同檔數隨機抽成分股，持有同樣天數；回傳每次抽樣的平均報酬。"""
    by_day = {}
    for x in taken:
        by_day.setdefault(x["entry_i"], 0)
        by_day[x["entry_i"]] += 1
    means = []
    for _ in range(N_RANDOM):
        rs = []
        for i, k in by_day.items():
            pool = mem_by_day(i)
            for t in rng.sample(pool, min(k, len(pool))):
                tr = make_trade(prices[t], cal, i, hold, ew)
                if tr:
                    rs.append(tr["ret"])
        means.append(sum(rs) / len(rs) if rs else 0.0)
    return means


def window_excess(signals, prices, cal, ew):
    """事件後各區間的平均超額（開盤到開盤，不含成本）：看漂移集中在哪一段。"""
    out = []
    for a, b, label in WINDOWS:
        xs = []
        for s in signals:
            p = prices[s["ticker"]]
            ia, ib_ = s["i0"] + a, s["i0"] + b
            if ib_ >= len(cal):
                continue
            ja, jb = p.idx.get(cal[ia]), p.idx.get(cal[ib_])
            if ja is None or jb is None:
                continue
            xs.append(p.open[jb] / p.open[ja] - ew.open[ib_] / ew.open[ia])
        out.append((label, len(xs), sum(xs) / len(xs) if xs else None, ib.tstat(xs)))
    return out


def mdd(curve):
    peak, m = 0.0, 0.0
    for _, v, _ in curve:
        peak = max(peak, v)
        m = min(m, v / peak - 1)
    return m


# -----------------------------------------------------------------------------
# 報告
# -----------------------------------------------------------------------------
def ok(b):
    return "✅" if b else "❌"


def fmt(v, d=2):
    return "—" if v is None else f"{v:.{d}f}"


def render(r):
    L = []
    A = r["checks"]
    passed = all(v[0] for v in A.values())
    verdict = ("🔍 **全過：有希望，進入前向紙上交易。**" if passed else
               "☠️ **A1 不過：策略不成立，依預先登記不調參數重跑。**" if not A["A1"][0] else
               "⚠️ **A1 過，但其他條件未全過：不進入實盤，記錄後結案。**")
    cov = r["coverage"]
    L += ["# PEAD 回測報告（財報公告後漂移，以市場反應衡量）", "",
          "規格照 `research/news_trade/STRATEGY.md` 預先登記的版本，只跑一次，沒有調參。",
          f"期間 {r['period'][0]} – {r['period'][1]}；產生腳本 `scripts/pead_backtest.py`。", "",
          "## 結論", "", verdict, "",
          "| # | 條件 | 門檻 | 結果 | 通過 |", "|---|---|---|---|---|"]
    names = {"A1": ("逐筆超額 t 值（按進場月份分組，vs 等權 S&P 500）", "≥ 2.0"),
             "A2": ("組合月報酬 CAPM alpha t 值（vs SPY）", "≥ 2.0"),
             "A3": (f"同日同檔數隨機抽樣（{N_RANDOM} 次）百分位", "≥ 95"),
             "A4": ("鄰域 AR {3,5,8}% × 持有 {20,40,60} 日：t(月) ≥ 1.5 的格數", "≥ 6 / 9"),
             "A5": ("2016 年後平均超額", "> 0"),
             "A6": ("最大回撤 ÷ SPY 同期最大回撤", "≤ 1.5"),
             "A7": ("年換手（單邊）", "≤ 800%")}
    for k, (name, th) in names.items():
        L.append(f"| {k} | {name} | {th} | {A[k][1]} | {ok(A[k][0])} |")
    m, mt = r["main"], r["main_taken"]
    L += ["", "## 主規格（AR ≥ +5%、量 ≥ 2 倍、持有 60 日）", "",
          "| 項目 | 全部訊號 | 實際持有（30 檔上限） |", "|---|---|---|",
          f"| 交易筆數 | {m['n']:,} | {mt['n']:,} |",
          f"| 平均報酬（含成本） | {bt.pct(m['mean_ret'], 2)} | {bt.pct(mt['mean_ret'], 2)} |",
          f"| 平均超額（vs 等權 S&P 500） | {bt.pct(m['mean_excess'], 2)} | {bt.pct(mt['mean_excess'], 2)} |",
          f"| 中位數超額 | {bt.pct(m['median_excess'], 2)} | {bt.pct(mt['median_excess'], 2)} |",
          f"| 超額勝率 | {m['hit'] * 100:.1f}% | {mt['hit'] * 100:.1f}% |",
          f"| t 值（逐筆） | {fmt(m['t'])} | {fmt(mt['t'])} |",
          f"| **t 值（按月分組）** | **{fmt(m['t_month'])}**（{m['months']} 個月） | {fmt(mt['t_month'])} |",
          "", "A1 以全部訊號計算（「逐筆」）；實際持有那欄供參考，只有同日訊號超過 30 檔時才會不同。", "",
          "### 組合績效", "",
          "| | 年化 | 最大回撤 | 波動 | Sharpe | 持股時間 |", "|---|---|---|---|---|---|"]
    for name, s in r["port_stats"].items():
        L.append(f"| {name} | {bt.pct(s.get('cagr'))} | {bt.pct(s.get('mdd'))} | {bt.pct(s.get('vol'))} | "
                 f"{fmt(s.get('sharpe'))} | {s.get('invested', 1) * 100:.0f}% |")
    c = r["capm"]
    L += ["", f"CAPM（月報酬 vs SPY，{c.get('n', 0)} 個月，未扣無風險利率）：alpha 年化 {bt.pct(c.get('alpha_y'))}，"
          f"beta {fmt(c.get('beta'))}，alpha t = {fmt(c.get('t'))}。"
          f"平均同時持股 {r['avg_pos']:.1f} 檔；年換手 {r['turnover'] * 100:.0f}%。", "",
          "![淨值](equity.svg)", "",
          "### 隨機抽樣對照（A3）", "",
          f"實際持有交易的平均報酬 {bt.pct(r['rand']['strategy'], 2)}；隨機抽樣 {N_RANDOM} 次的平均 "
          f"{bt.pct(r['rand']['mean'], 2)}（第 5／50／95 百分位 {bt.pct(r['rand']['p5'], 2)}／"
          f"{bt.pct(r['rand']['p50'], 2)}／{bt.pct(r['rand']['p95'], 2)}），策略位於第 {r['rand']['pctile']:.0f} 百分位。", "",
          "## 鄰域（A4）：按月分組 t 值", "",
          "| AR 門檻 \\ 持有 | " + " | ".join(f"{h} 日" for h in GRID_HOLD) + " |",
          "|---|" + "---|" * len(GRID_HOLD)]
    for a in GRID_AR:
        cells = []
        for h in GRID_HOLD:
            e = r["grid"][(a, h)]
            cells.append(f"{fmt(e.get('t_month'))}（{bt.pct(e.get('mean_excess'), 2)}，{e.get('n', 0):,} 筆）")
        L.append(f"| ≥ {a * 100:.0f}% | " + " | ".join(cells) + " |")
    L += ["", "## 逐年（主規格，全部訊號）", "",
          "| 年 | 筆數 | 平均超額 | 勝率 |", "|---|---|---|---|"]
    for y, v in sorted(r["by_year"].items()):
        L.append(f"| {y} | {v['n']} | {bt.pct(v['sum'] / v['n'], 2)} | {v['win'] / v['n'] * 100:.0f}% |")
    L += ["", "## 診斷（不影響判決）", "", "**方向一致性**：壞消息組（AR ≤ −5%、量 ≥ 2 倍、持有 60 日）應該較差。", "",
          "| 組別 | 筆數 | 平均超額 | t（月） |", "|---|---|---|---|",
          f"| 好消息（主規格） | {m['n']:,} | {bt.pct(m['mean_excess'], 2)} | {fmt(m['t_month'])} |",
          f"| 壞消息 | {r['neg'].get('n', 0):,} | {bt.pct(r['neg'].get('mean_excess'), 2)} | {fmt(r['neg'].get('t_month'))} |",
          "", "**漂移集中在哪一段**（主規格訊號，開盤到開盤，不含成本）：", "",
          "| 區間 | 筆數 | 平均超額 | t（逐筆） |", "|---|---|---|---|"]
    for label, n, mu, t in r["windows"]:
        L.append(f"| {label} | {n:,} | {bt.pct(mu, 2)} | {fmt(t)} |")
    L += ["", "## 數據涵蓋", "",
          f"- 8-K 2.02 事件 {cov['events']:,} 筆 → 30 天去重後 {cov['dedup']:,} 筆 → 可計算反應 {cov['reacted']:,} 筆",
          "- 略過：" + "、".join(f"{k} {v:,}" for k, v in sorted(cov["skip"].items(), key=lambda kv: -kv[1])),
          f"- 通過 AR 門檻 {cov['ar_pass']:,} 筆，其中量比也通過 {cov['signals']:,} 筆；完成交易 {m['n']:,} 筆"
          f"（未滿 {HOLD} 日的持有中部位不計）",
          f"- 以最後收盤出場（出場日無價格，多為下市、併購）{r['delist']:,} 筆",
          f"- **倖存者偏差**：成分股 {cov['members']:,} 個代號中只有 {cov['members_priced']:,} 個有本地價格，"
          "缺的多是已下市、被併購的公司；樣本偏向存活下來的公司，通常會**高估**報酬。",
          "", "## 方法備註", "",
          "- 事件日由 8-K 申報時間決定；新聞稿通常更早，8-K 晚一天的情況由「t0 前一日收盤起算」涵蓋。",
          "- 等權 S&P 500 基準：每天當時的成分股收盤對收盤報酬平均（跳過代號重用的價格）。",
          "- 代號重用防護：價格資料第一天必須在成分股起日後 7 天內，否則視為別家公司的價格而略過。",
          "- 組合每天開盤重設等權（微調不計成本）；進出場各收 10 bps。沒有訊號時持現金，報酬 0。",
          "- A3 比較的是「實際持有交易的平均報酬」與「同日同檔數隨機成分股、同樣持有期」的平均報酬。"
          "隨機抽樣不控制 beta：訊號股多半是高波動股，多頭期間原始報酬較高，所以 A3 通過不代表有超額。",
          "- CAPM 用原始月報酬，沒有扣無風險利率；alpha 的 t 值不受這個影響太多（兩邊同時扣）。", ""]
    return "\n".join(L)


# -----------------------------------------------------------------------------
# 主程式
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="PEAD 回測（STRATEGY.md 預先登記規格）")
    ap.add_argument("--equities-root", default=os.environ.get("EQUITIES_ROOT", DEFAULT_EQ_ROOT))
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    eq_dir = os.path.join(args.equities_root, "data", "equities", "us")
    if not os.path.isdir(eq_dir):
        print(f"找不到本地美股資料：{eq_dir}")
        return 1
    load_from = START - timedelta(days=120)

    renames = ib.load_renames(args.equities_root)
    mem = ib.load_membership(args.equities_root, renames)
    events = load_events()
    tickers = set(mem) | {e["price_ticker"] for e in events} | {"SPY"}
    print(f"事件 {len(events):,} 筆；載入價格 {len(tickers)} 檔…")
    prices = bt.load_all_prices(tickers, load_from, None, eq_dir, {}, yahoo=False)
    first_price = {t: ib.first_local_date(eq_dir, t) or p.days[0] for t, p in prices.items()}
    spy = prices["SPY"]
    cal = [d for d in spy.days if d >= load_from]
    ew = ib.ew_index(mem, prices, cal, first_price)
    print(f"價格 {len(prices)} 檔；交易日 {len(cal)}")

    ded = dedupe(events)
    need = {e["price_ticker"] for e in ded if e["price_ticker"] in prices}
    volumes = {t: load_volume(eq_dir, t, load_from) for t in need}
    reacted, skip = reactions(ded, cal, prices, volumes, ew, first_price)
    print(f"去重 {len(ded):,}；可計算反應 {len(reacted):,}；略過 {skip}")

    def signals(ar_min, sign=1):
        return [x for x in reacted if sign * x["ar"] >= ar_min and x["vol_ratio"] >= VOL_MULT]

    def excess(trades):
        return ib.excess_stats(trades)

    main_sig = signals(AR_MIN)
    trades = build_trades(main_sig, prices, cal, HOLD, ew)
    taken = select_positions(trades)
    m, mt = excess(trades), excess(taken)
    print(f"訊號 {len(main_sig):,}；完成交易 {len(trades):,}；實際持有 {len(taken):,}；"
          f"平均超額 {bt.pct(m['mean_excess'], 2)} t(月)={fmt(m['t_month'])}")

    curve, turnover = simulate(taken, prices, cal)
    c0 = curve[0][0]
    cal_p = [d for d in cal if d >= c0]
    spy_curve = bt.bench_curve(spy, cal_p)
    ew_curve = [(d, v, True) for d, v in zip(ew.days, ew.close) if d >= c0]
    port_stats = {"PEAD 組合": bt.stats(curve), "SPY 買入持有": bt.stats(spy_curve),
                  "等權 S&P 500（point-in-time）": bt.stats(ew_curve)}
    cp = capm(monthly_returns(curve), monthly_returns(spy_curve))
    avg_pos = 0.0
    if taken:
        span = sum(1 for d in cal_p for x in taken if x["entry_day"] <= d < x["exit_day"])
        avg_pos = span / len(cal_p)

    # A3：隨機抽樣
    members = [(t, s, e) for t, iv in mem.items() for s, e in iv if t in prices]
    cache = {}

    def mem_by_day(i):
        if i not in cache:
            d = cal[i]
            cache[i] = sorted(t for t, s, e in members
                              if s <= d and (e is None or d < e) and d in prices[t].idx
                              and first_price[t] <= s + timedelta(days=ib.GRACE_DAYS))
        return cache[i]

    rng = random.Random(SEED)
    rmeans = sorted(random_benchmark(taken, mem_by_day, prices, cal, HOLD, ew, rng))
    strat_mean = mt["mean_ret"]
    pctile = 100 * sum(1 for v in rmeans if v < strat_mean) / len(rmeans)
    rand = {"strategy": strat_mean, "mean": sum(rmeans) / len(rmeans), "p5": rmeans[int(0.05 * N_RANDOM)],
            "p50": rmeans[N_RANDOM // 2], "p95": rmeans[int(0.95 * N_RANDOM) - 1], "pctile": pctile}
    print(f"隨機抽樣：策略第 {pctile:.0f} 百分位")

    # A4：鄰域
    grid = {}
    for a in GRID_AR:
        sg = signals(a)
        for h in GRID_HOLD:
            grid[(a, h)] = excess(build_trades(sg, prices, cal, h, ew)) or {}
            print(f"  AR≥{a:.0%} 持有 {h}：t(月)={fmt(grid[(a, h)].get('t_month'))}")
    n_grid = sum(1 for v in grid.values() if (v.get("t_month") or 0) >= 1.5)

    recent = [x["ret"] - x["ew"] for x in trades if x["ew"] is not None and x["entry_day"] >= RECENT_FROM]
    recent_mu = sum(recent) / len(recent) if recent else None
    mdd_ratio = mdd(curve) / mdd(spy_curve) if mdd(spy_curve) else None

    checks = {
        "A1": ((m.get("t_month") or 0) >= 2.0, fmt(m.get("t_month"))),
        "A2": ((cp.get("t") or 0) >= 2.0, fmt(cp.get("t"))),
        "A3": (pctile >= 95, f"{pctile:.0f}"),
        "A4": (n_grid >= 6, f"{n_grid} / 9"),
        "A5": (recent_mu is not None and recent_mu > 0, f"{bt.pct(recent_mu, 2)}（{len(recent):,} 筆）"),
        "A6": (mdd_ratio is not None and mdd_ratio <= 1.5,
               f"{fmt(mdd_ratio)}（{bt.pct(mdd(curve))} vs {bt.pct(mdd(spy_curve))}）"),
        "A7": (turnover <= 8.0, f"{turnover * 100:.0f}%"),
    }

    neg = excess(build_trades(signals(AR_MIN, -1), prices, cal, HOLD, ew)) or {}
    by_year = {}
    for x in trades:
        if x["ew"] is None:
            continue
        v = by_year.setdefault(x["entry_day"].year, {"n": 0, "sum": 0.0, "win": 0})
        v["n"] += 1
        v["sum"] += x["ret"] - x["ew"]
        v["win"] += (x["ret"] - x["ew"]) > 1e-9

    res = {"checks": checks, "main": m, "main_taken": mt, "port_stats": port_stats, "capm": cp,
           "avg_pos": avg_pos, "turnover": turnover, "rand": rand, "grid": grid, "by_year": by_year,
           "neg": neg, "windows": window_excess(main_sig, prices, cal, ew),
           "delist": sum(1 for x in trades if x["exit_how"] == "close"),
           "period": (curve[0][0], curve[-1][0]),
           "coverage": {"members": len(mem), "members_priced": sum(1 for t in mem if t in prices),
                        "events": len(events), "dedup": len(ded), "reacted": len(reacted), "skip": skip,
                        "ar_pass": sum(1 for x in reacted if x["ar"] >= AR_MIN), "signals": len(main_sig)}}

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(render(res))
    with open(os.path.join(args.out, "trades.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "company", "accession", "acceptance_et", "session", "t0", "ar", "vol_ratio",
                    "entry_day", "exit_day", "exit_how", "ret", "ew", "excess", "held"])
        held = {id(x) for x in taken}
        for x in sorted(trades, key=lambda x: (x["entry_day"], -x["ar"])):
            w.writerow([x["ticker"], x["company"], x["accession"], x["acc_et"], x["session"], x["t0"],
                        f"{x['ar']:.4f}", f"{x['vol_ratio']:.2f}", x["entry_day"], x["exit_day"], x["exit_how"],
                        f"{x['ret']:.4f}", "" if x["ew"] is None else f"{x['ew']:.4f}",
                        "" if x["ew"] is None else f"{x['ret'] - x['ew']:.4f}", int(id(x) in held)])
    bt.svg_chart([("PEAD", "--s1", [(d, v) for d, v, _ in curve]),
                  ("等權 S&P 500", "--s3", [(d, v / ew_curve[0][1]) for d, v, _ in ew_curve]),
                  ("SPY", "--s2", [(d, v) for d, v, _ in spy_curve])],
                 os.path.join(args.out, "equity.svg"), "PEAD 組合 vs 基準（對數軸）")
    for k, (passed, val) in checks.items():
        print(f"{k} {ok(passed)} {val}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
