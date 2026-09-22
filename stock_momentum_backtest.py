#!/usr/bin/env python3
"""港股月頻選股回測引擎——`--signal momentum`（動量輪動，判死，見 MOMENTUM_HK_BACKTEST.md）、
`--signal lowvol`（低波動，🔍，見 LOWVOL_HK_BACKTEST.md），只做多 vs 買入持有基準。

屬於 RESEARCH_HANDBOOK.md 第三節「適合股票的策略形態」候選之一：
低頻（月頻）、只做多、按組合分散。

**這是機制原型，不是可判決的結論**：手選8檔和「現有」HSI成分股76檔
兩輪都測過，結果都離譜到不可信（見 MOMENTUM_HK_BACKTEST.md）——不管
股票池是手選還是官方現有名單，只要不是 point-in-time 歷史成分股就
不能信（手冊第三節第4條）。`--cap-top-n` 是退而求其次的近似：每期
只在候選池裡「當時市值前N大」的子集選動量，至少修正「不管當時大小、
只要現在有名就能被選」的問題，但候選池本身仍限於我們已經有數據的
76 檔倖存者，測不到當時存在、後來下市/破產的公司，偏差沒有完全消除，
只是比整池排名收斂一些。

方法：
- 訊號：每月最後一個交易日，用 AdjClose 算 (lookback-skip) 個月動量，
  即 P[-skip] / P[-skip-lookback] - 1（12-1 動量，避開近一個月短期反轉）。
- 過濾：動量 <= 0 的候選不買（絕對動量濾網）；一半以上落選則空手待現金。
- 執行：訊號隔天開盤成交（次日開盤，不是訊號日收盤——見手冊第三節第1條）。
  用 AdjOpen = Open * AdjClose/Close 還原股息，讓開盤價之間的報酬含股息。
- 成本：只對「換手」的名字收費（新買/賣出各收一次 --cost-bps），
  留倉不換的名字不收費——比每期全額收費更接近實際下單行為。
- 權益曲線只在月頻（執行日）打點，不是逐日——與策略本身的月頻本質一致，
  但意味著月中最大回撤會被低估，見下方輸出的警語。

用法：
    python3 stock_momentum_backtest.py
    python3 stock_momentum_backtest.py --lookback 6 --top-k 2
    python3 stock_momentum_backtest.py --sweep
"""
import argparse
import bisect
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import marketdata

DATA_DIR = Path(__file__).resolve().parent / "data" / "stocks"


def load_series(ticker: str) -> dict[date, tuple[float, float, float]]:
    """回傳 {date: (adj_open, adj_close, raw_close)}。raw_close 給市值排名用
    （市值 = 當時實際股價 x 當時實際股數，不能用還原股息/拆股的 AdjClose）。
    讀檔交給多市場數據層 marketdata.py（港股舊格式 data/stocks/*.csv.gz、
    美股/日股新格式 data/equities/ 都支援）。"""
    return marketdata.load_series(ticker)


def load_shares(ticker: str) -> list[tuple[date, int]] | None:
    """回傳按日期排序的 [(date, shares_outstanding), ...]，抓不到就 None。
    見 scripts/fetch_stock_data.py 的 fetch_shares_outstanding。"""
    return marketdata.load_shares(ticker)


def shares_asof(shares: list[tuple[date, int]], as_of: date) -> int | None:
    """當時流通股數：找 <= as_of 的最近一筆（forward-fill）；再早都沒有就 None
    （表示這檔股票在 as_of 當時還沒有可靠的股數資料，不該被排進市值排名）。"""
    dates = [d for d, _ in shares]
    i = bisect.bisect_right(dates, as_of) - 1
    if i < 0:
        return None
    return shares[i][1]


def read_pool(universe_path: Path, exclude: set[str]) -> list[str]:
    tickers = []
    for line in universe_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        if line in exclude:
            continue
        tickers.append(line)
    return tickers


def month_end_dates(calendar: list[date]) -> list[date]:
    out = []
    for i in range(len(calendar) - 1):
        if calendar[i].month != calendar[i + 1].month:
            out.append(calendar[i])
    return out


def next_trading_day(calendar: list[date], after: date) -> date | None:
    for d in calendar:
        if d > after:
            return d
    return None


def load_pointintime(directory: Path) -> list[tuple[date, set[str]]]:
    """讀 scripts/pointintime/hsi_<year>.txt，回傳按日期排序的
    [(快照日, 成分股集合)]。快照是 Wikipedia 年中版本，快照日取 6/30。"""
    out = []
    for p in sorted(directory.glob("hsi_*.txt")):
        year = p.stem.split("_")[-1]
        if not year.isdigit():
            continue
        members = {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")}
        out.append((date(int(year), 6, 30), members))
    return out


def trailing_vol(daily_rows: list[tuple[date, float]], daily_dates: list[date], as_of: date,
                 vol_days: int) -> float | None:
    """as_of（含）之前 vol_days 根 AdjClose 日對數報酬的標準差；根數不足 80% 回 None。
    回測引擎與前向模擬盤（scripts/paper_trade.py）共用，保證兩邊選股邏輯一致。"""
    idx = bisect.bisect_right(daily_dates, as_of)
    closes = [c for _, c in daily_rows[max(0, idx - vol_days - 1):idx] if c > 0]
    if len(closes) < int(vol_days * 0.8):
        return None
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))


def derive_dividends(series: dict[date, tuple[float, float, float]],
                     thresh: float = 0.001) -> list[tuple[date, float]]:
    """從 AdjClose/Close 比值在除淨日的跳幅反推每股股息：
    股息 = 除淨前一日收市 x (1 - 前一日比值 / 除淨日比值)；跳幅 < thresh 視為四捨五入噪音。
    驗證見 DIVYIELD_HK_BACKTEST.md（匯豐 2020 停派、中電季息、騰訊年息等都對得上）。"""
    ds = sorted(series)
    out = []
    for a_, b_ in zip(ds, ds[1:]):
        (_, ac_a, c_a), (_, ac_b, c_b) = series[a_], series[b_]
        if c_a <= 0 or c_b <= 0 or ac_a <= 0:
            continue
        fa, fb = ac_a / c_a, ac_b / c_b
        if fb / fa - 1 > thresh:
            out.append((b_, c_a * (1 - fa / fb)))
    return out


def sector_neutral_pick(scored: list[tuple[float, str]], sector_of: dict[str, str], k: int) -> set[str]:
    """K 個名額按各行業「有訊號的候選檔數」比例分配（最大餘數法），行業內取分數最高者。
    讓組合的行業組成跟宇宙一致，分辨「因子本身」與「押某個行業」。"""
    groups: dict[str, list[tuple[float, str]]] = {}
    for sc, t in scored:  # scored 已由高到低排好
        groups.setdefault(sector_of.get(t, ""), []).append((sc, t))
    n = sum(len(g) for g in groups.values())
    if n == 0:
        return set()
    raw = {sec: k * len(g) / n for sec, g in groups.items()}
    quota = {sec: int(q) for sec, q in raw.items()}
    for sec in sorted(raw, key=lambda x: raw[x] - quota[x], reverse=True)[:k - sum(quota.values())]:
        quota[sec] += 1
    return {t for sec, g in groups.items() for _, t in g[:quota[sec]]}


def run_backtest(pool: list[str], benchmark: str, lookback: int, skip: int,
                  top_k: int, cost_bps: float, start: date | None,
                  abs_filter: bool, cap_top_n: int | None = None,
                  pointintime: list[tuple[date, set[str]]] | None = None,
                  signal: str = "momentum", vol_days: int = 252,
                  sectors: dict[str, dict[str, str]] | None = None,
                  sector_neutral: bool = False, sector_only: str | None = None,
                  div_months: int = 12) -> dict:
    all_tickers = pool + [benchmark]
    series = {t: load_series(t) for t in all_tickers}
    if signal == "lowvol":
        # 低波動要逐日收市價算波動率，先建好排序後的日期/AdjClose 陣列
        daily = {t: sorted((d, v[1]) for d, v in series[t].items()) for t in pool}
        daily_dates = {t: [d for d, _ in rows] for t, rows in daily.items()}
    if signal == "divyield":
        divs = {t: derive_dividends(series[t]) for t in pool}
        div_window = timedelta(days=round(div_months * 30.4375))
    shares = {t: load_shares(t) for t in pool} if cap_top_n else {}
    first_date = {t: min(s) for t, s in series.items() if s}
    excluded_no_cap_data = 0
    member_slots = 0     # point-in-time：各期成分股總數
    holes = 0            # point-in-time：成分股但沒有可用價格（已下市/代碼重用）
    delist_marks = 0     # 持倉期間價格中斷，用最後可得價結算的次數
    first_entry: date | None = None

    # 共用行事曆：用基準的交易日集合（HK 交易所同一行事曆）
    calendar = sorted(series[benchmark].keys())
    if start:
        calendar = [d for d in calendar if d >= start]
    m_ends = month_end_dates(calendar)

    # 每個月底 -> 執行日（下一個交易日）
    exec_dates = []
    for me in m_ends:
        nd = next_trading_day(calendar, me)
        if nd is not None:
            exec_dates.append((me, nd))

    if len(exec_dates) < lookback + skip + 2:
        raise SystemExit("樣本太短，不夠算動量，check --start / 數據期間")

    equity = 1.0
    equity_curve: list[tuple[date, float]] = []
    period_returns: list[tuple[date, float]] = []  # (exec_date, net period return)
    bench_period_returns: list[float] = []         # 同一期基準（AdjOpen 對 AdjOpen）
    baskets: list[tuple[date, list[str]]] = []      # 每期實際持倉（給持倉/行業集中度檢查）
    current_basket: set[str] = set()
    total_cost_paid = 0.0
    cash_periods = 0

    for i in range(lookback + skip, len(exec_dates) - 1):
        signal_me, entry_exec = exec_dates[i]
        _, exit_exec = exec_dates[i + 1]

        # --- point-in-time 成分股（當時的名單，含後來被剔除/下市的公司）---
        if pointintime:
            snap = None
            for snap_date, members in pointintime:
                if snap_date <= signal_me:
                    snap = (snap_date, members)
            if snap is None:
                continue  # 第一個快照之前不知道成分股是誰，不交易
            snap_date, members = snap
            # 防代碼重用：價格必須在快照日之前就存在，否則那份價格屬於
            # 後來拿到這個代碼的別家公司（例：0013 和黃 -> 和黃醫藥）
            base = {t for t in members if t in first_date and first_date[t] <= snap_date}
            member_slots += len(members)
            holes += len(members) - len(base)
        else:
            base = set(pool)

        # --- point-in-time 市值前 N 大過濾（近似 point-in-time 成分股表，
        #     見 RESEARCH_HANDBOOK.md 第三節第4條：不能只用「現在還在」的名單）---
        if cap_top_n:
            caps = []
            for t in base:
                sh = shares.get(t)
                if sh is None or signal_me not in series[t]:
                    continue
                n_shares = shares_asof(sh, signal_me)
                if n_shares is None:
                    continue
                raw_close = series[t][signal_me][2]
                caps.append((raw_close * n_shares, t))
            excluded_no_cap_data += len(base) - len(caps)
            caps.sort(reverse=True)
            eligible = {t for _, t in caps[:cap_top_n]}
        else:
            eligible = base

        # --- 行業（point-in-time：用同一年快照的恒指分類指數）---
        sector_of: dict[str, str] = {}
        if sectors is not None and pointintime:
            y = str(snap_date.year)
            sector_of = {t: sectors.get(t, {}).get(y, "") for t in eligible}
            if sector_only:
                eligible = {t for t in eligible if sector_of[t] == sector_only}

        # --- 算訊號，選籃子（分數越高越優先）---
        scored = []
        for t in eligible:
            s = series[t]
            if signal == "divyield":
                # 滾動 div_months 個月股息（年化）÷ 訊號日收市；價格歷史須涵蓋完整窗口、沒派息不選
                if first_date[t] > signal_me - div_window or signal_me not in s:
                    continue
                ttm = sum(x for d, x in divs[t] if signal_me - div_window < d <= signal_me)
                close = s[signal_me][2]
                if ttm > 0 and close > 0:
                    scored.append((ttm / (div_months / 12) / close, t))
                continue
            if signal == "lowvol":
                vol = trailing_vol(daily[t], daily_dates[t], signal_me, vol_days)
                if vol is not None:
                    scored.append((-vol, t))
                continue
            me_skip = exec_dates[i - skip][0]
            me_lb = exec_dates[i - skip - lookback][0]
            if me_skip not in s or me_lb not in s:
                continue
            p_skip = s[me_skip][1]
            p_lb = s[me_lb][1]
            if p_lb <= 0:
                continue
            mom = p_skip / p_lb - 1.0
            if abs_filter and mom <= 0:
                continue
            scored.append((mom, t))
        scored.sort(reverse=True)
        if sector_neutral and sector_of:
            new_basket = sector_neutral_pick(scored, sector_of, top_k)
        else:
            new_basket = {t for _, t in scored[:top_k]}
        if entry_exec not in series[benchmark] or exit_exec not in series[benchmark]:
            continue

        if not new_basket:
            cash_periods += 1

        # --- 換手成本：只對變動的名字收費 ---
        dropped = current_basket - new_basket
        added = new_basket - current_basket
        n_changed = len(dropped) + len(added)
        weight = 1.0 / top_k if top_k else 0.0
        cost_frac = n_changed * weight * (cost_bps / 10000.0)

        # --- 持有期報酬（AdjOpen 對 AdjOpen，含股息）---
        if new_basket:
            rets = []
            for t in new_basket:
                s = series[t]
                if entry_exec not in s:
                    continue  # 買不進（停牌），不算入這期
                p0 = s[entry_exec][0]
                if exit_exec in s:
                    p1 = s[exit_exec][0]
                else:
                    # 持倉期間下市/停牌：用最後可得收市價結算，不能讓它從平均裡
                    # 靜默消失（那等於把崩盤下市的持股當作沒買過——倖存者偏差）
                    last = [d for d in s if entry_exec <= d < exit_exec]
                    if not last:
                        continue
                    p1 = s[max(last)][1]
                    delist_marks += 1
                if p0 > 0:
                    rets.append(p1 / p0 - 1.0)
            gross_ret = sum(rets) / len(rets) if rets else 0.0
        else:
            gross_ret = 0.0

        if first_entry is None:
            first_entry = entry_exec
            equity_curve.append((entry_exec, 1.0))
        net_ret = gross_ret - cost_frac
        equity *= (1.0 + net_ret)
        total_cost_paid += cost_frac
        equity_curve.append((exit_exec, equity))
        period_returns.append((exit_exec, net_ret))
        b = series[benchmark]
        bench_period_returns.append(b[exit_exec][0] / b[entry_exec][0] - 1.0)
        baskets.append((entry_exec, sorted(new_basket)))
        current_basket = new_basket

    if first_entry is None:
        raise SystemExit("沒有任何可交易的期間（check --start / point-in-time 快照範圍）")

    # --- 基準買入持有（跟策略同一段：第一個實際交易期 -> 最後）---
    bench = series[benchmark]
    b_start = first_entry
    b_end = exec_dates[-1][1]
    bench_ret = bench[b_end][0] / bench[b_start][0] - 1.0 if b_start in bench and b_end in bench else float("nan")

    return {
        "equity_curve": equity_curve,
        "period_returns": period_returns,
        "final_equity": equity,
        "total_cost_paid": total_cost_paid,
        "cash_periods": cash_periods,
        "n_periods": len(period_returns),
        "bench_total_return": bench_ret,
        "bench_start": b_start,
        "bench_end": b_end,
        "avg_excluded_no_cap_data": excluded_no_cap_data / len(period_returns) if period_returns and cap_top_n else 0.0,
        "avg_members": member_slots / len(period_returns) if period_returns and pointintime else 0.0,
        "avg_holes": holes / len(period_returns) if period_returns and pointintime else 0.0,
        "delist_marks": delist_marks,
        "bench_period_returns": bench_period_returns,
        "baskets": baskets,
    }


def max_drawdown(curve: list[tuple[date, float]]) -> tuple[float, int]:
    peak = curve[0][1]
    peak_i = 0
    mdd = 0.0
    mdd_len = 0
    for i, (_, v) in enumerate(curve):
        if v > peak:
            peak = v
            peak_i = i
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd
            mdd_len = i - peak_i
    return mdd, mdd_len


def t_stat(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return float("nan")
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return float("nan")
    return mean / (sd / math.sqrt(n))


def risk_stats(res: dict) -> dict:
    """相對基準的評估：主指標是「每月超額報酬（策略 - 2800）」的 t 值——
    策略只看自己報酬的 t 值會把大盤 beta 也算成 edge。夏普未扣無風險利率。"""
    rets = [r for _, r in res["period_returns"]]
    bench = res["bench_period_returns"]
    excess = [r - b for r, b in zip(rets, bench)]

    def sharpe(xs: list[float]) -> float:
        if len(xs) < 2:
            return float("nan")
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
        return m / sd * math.sqrt(12) if sd else float("nan")

    curve, eq = [], 1.0
    for d, b in zip((d for d, _ in res["period_returns"]), bench):
        eq *= 1.0 + b
        curve.append((d, eq))
    bench_mdd = max_drawdown([(None, 1.0)] + curve)[0] if curve else float("nan")
    n = len(rets)
    beta = alpha = alpha_t = float("nan")
    if n > 2:
        mb, mr = sum(bench) / n, sum(rets) / n
        sbb = sum((x - mb) ** 2 for x in bench)
        if sbb > 0:
            beta = sum((x - mb) * (y - mr) for x, y in zip(bench, rets)) / sbb
            alpha = mr - beta * mb
            resid = [y - alpha - beta * x for x, y in zip(bench, rets)]
            se = math.sqrt(sum(e * e for e in resid) / (n - 2)) * math.sqrt(1 / n + mb * mb / sbb)
            alpha_t = alpha / se if se else float("nan")
    return {
        "beta": beta,
        "alpha_ann": alpha * 12,
        "alpha_t": alpha_t,
        "t_excess": t_stat(excess),
        "excess_ann": sum(excess) / len(excess) * 12 if excess else float("nan"),
        "sharpe": sharpe(rets),
        "bench_sharpe": sharpe(bench),
        "bench_mdd": bench_mdd,
        "hit_rate": sum(1 for x in excess if x > 0) / len(excess) if excess else float("nan"),
    }


def by_year(period_returns: list[tuple[date, float]]) -> dict[int, float]:
    acc: dict[int, float] = {}
    for d, r in period_returns:
        acc[d.year] = acc.get(d.year, 1.0) * (1.0 + r)
    return {y: v - 1.0 for y, v in acc.items()}


def report(res: dict, label: str) -> None:
    n = res["n_periods"]
    years = n / 12.0 if n else float("nan")
    total_ret = res["final_equity"] - 1.0
    cagr = res["final_equity"] ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    mdd, mdd_months = max_drawdown(res["equity_curve"])
    rets = [r for _, r in res["period_returns"]]
    t = t_stat(rets)
    years_map = by_year(res["period_returns"])

    print(f"\n=== {label} ===")
    print(f"期間: {res['bench_start']} -> {res['bench_end']}（{n} 個月，~{years:.1f} 年）")
    print(f"策略總報酬: {total_ret:+.1%}  CAGR: {cagr:+.1%}")
    print(f"基準({res['bench_start']}->{res['bench_end']}) 買入持有總報酬: {res['bench_total_return']:+.1%}")
    print(f"最大回撤（月頻打點，會低估月中回撤）: {mdd:.1%}，回補耗時 {mdd_months} 個月")
    print(f"月報酬 t 值: {t:.2f}（t>=2 已驗證 / 1.5~2 有希望未證實 / <1.5 不看，見手冊鐵律第7條）")
    rs = risk_stats(res)
    print(f"**相對基準** 每月超額報酬 t 值: {rs['t_excess']:.2f}，年化超額 {rs['excess_ann']:+.1%}，"
          f"勝過基準月份 {rs['hit_rate']:.0%}")
    print(f"CAPM: beta {rs['beta']:.2f}，年化 alpha {rs['alpha_ann']:+.1%}，alpha t {rs['alpha_t']:.2f}")
    print(f"夏普（未扣無風險）: 策略 {rs['sharpe']:.2f} vs 基準 {rs['bench_sharpe']:.2f}；"
          f"基準同期月頻最大回撤 {rs['bench_mdd']:.1%}")
    print(f"空手（無合格標的）月數: {res['cash_periods']}/{n}")
    if res.get("avg_excluded_no_cap_data"):
        print(f"平均每期因缺流通股數資料被排除的候選數: {res['avg_excluded_no_cap_data']:.1f}")
    if res.get("avg_members"):
        print(f"point-in-time：平均每期成分股 {res['avg_members']:.1f} 檔，其中沒有可用價格 "
              f"{res['avg_holes']:.1f} 檔（已下市/私有化/代碼重用——殘留的倖存者偏差）")
    if res.get("delist_marks"):
        print(f"持倉期間價格中斷、以最後可得價結算: {res['delist_marks']} 次")
    print(f"累計成本拖累: {res['total_cost_paid']:.1%}（已算進總報酬）")
    print("按年拆解:")
    for y in sorted(years_map):
        print(f"  {y}: {years_map[y]:+.1%}")
    if total_ret <= res["bench_total_return"]:
        print("!! 輸給買入持有——按手冊鐵律第6條，這版本目前是垃圾，不要往下做。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", type=Path, default=Path(__file__).parent / "scripts" / "universe_hk.txt")
    ap.add_argument("--benchmark", default="2800.HK")
    ap.add_argument("--lookback", type=int, default=12, help="動量回看月數（不含 skip）")
    ap.add_argument("--skip", type=int, default=1, help="排除最近幾個月（避開短期反轉）")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--cost-bps", type=float, default=15.0, help="單邊成本 bps，預設 15bps~=港股印花稅+費用來回一半")
    ap.add_argument("--start", type=lambda s: date.fromisoformat(s), default=None)
    ap.add_argument("--no-abs-filter", action="store_true", help="關掉絕對動量濾網，動量<=0也硬選")
    ap.add_argument("--cap-top-n", type=int, default=None,
                     help="每期只在「當時市值前N大」候選裡選動量，近似 point-in-time 成分股表；"
                          "需要 data/stocks/<TICKER>.shares.csv.gz（流通股數歷史）")
    ap.add_argument("--pointintime-dir", type=Path, default=None,
                     help="用逐年 point-in-time 成分股快照（scripts/pointintime/hsi_<year>.txt）決定每期"
                          "可選名單，取代 --universe 的固定股票池")
    ap.add_argument("--signal", choices=["momentum", "lowvol", "divyield"], default="momentum",
                     help="momentum=12-1 動量取最強 top_k；lowvol=過去 vol_days 日報酬波動率取最低 top_k")
    ap.add_argument("--vol-days", type=int, default=252, help="低波動訊號的回看交易日數")
    ap.add_argument("--div-months", type=int, default=12, help="高股息訊號的滾動股息月數（年化）")
    ap.add_argument("--sector-neutral", action="store_true",
                     help="名額按 point-in-time 行業檔數比例分配、行業內選股（需 --pointintime-dir）")
    ap.add_argument("--sector-only", default=None,
                     help="只在某行業內選（診斷用，如 Utilities；配 --top-k 99 = 該行業全部等權）")
    ap.add_argument("--sweep", action="store_true", help="掃 lookback x top-k 鄰域，檢查手冊鐵律第4條的參數平原")
    args = ap.parse_args()

    pointintime = load_pointintime(args.pointintime_dir) if args.pointintime_dir else None
    sectors = None
    if args.sector_neutral or args.sector_only:
        if not args.pointintime_dir:
            raise SystemExit("--sector-neutral / --sector-only 需要 --pointintime-dir（行業要用當年的分類）")
        sectors = json.loads((args.pointintime_dir / "hsi_sectors.json").read_text(encoding="utf-8"))
    if pointintime:
        members = set().union(*(m for _, m in pointintime))
        pool = sorted(t for t in members if t != args.benchmark and
                      marketdata.has_data(t))
        missing = sorted(members - set(pool) - {args.benchmark})
        print(f"point-in-time 快照 {len(pointintime)} 期（{pointintime[0][0]} ~ {pointintime[-1][0]}），"
              f"歷年成分股聯集 {len(members)} 檔，有價格 {len(pool)} 檔，完全沒價格: {missing}")
    else:
        pool = read_pool(args.universe, exclude={args.benchmark})
        print(f"股票池（{len(pool)} 檔，非權威成分股表）: {pool}")

    if args.sweep:
        # 預先登記的鄰域（手冊鐵律第4、9條）：動量 lookback(月) x top_k；低波動 vol_days x 持股數
        if args.signal == "momentum":
            grid = [(lb, k, args.vol_days) for lb in (6, 9, 12) for k in (2, 3, 4)]
        elif args.signal == "divyield":
            grid = [(args.lookback, k, w) for w in (12, 24) for k in (5, 10, 15)]
        else:
            grid = [(args.lookback, k, vd) for vd in (126, 252)
                    for k in ((10, 15, 20) if args.sector_neutral else (5, 10, 15))]
        for lb, k, vd in grid:
            try:
                res = run_backtest(pool, args.benchmark, lb, args.skip, k,
                                    args.cost_bps, args.start, not args.no_abs_filter,
                                    args.cap_top_n, pointintime, args.signal,
                                    vd if args.signal == "lowvol" else args.vol_days,
                                    sectors, args.sector_neutral, args.sector_only,
                                    vd if args.signal == "divyield" else args.div_months)
            except SystemExit as e:
                print(f"lookback={lb} top_k={k} vol_days={vd}: {e}")
                continue
            total_ret = res["final_equity"] - 1.0
            rs = risk_stats(res)
            mdd = max_drawdown(res["equity_curve"])[0]
            head = {"momentum": f"lookback={lb:2d} top_k={k}", "lowvol": f"vol_days={vd:3d} top_k={k:2d}",
                    "divyield": f"div_months={vd:2d} top_k={k:2d}"}[args.signal]
            print(f"{head}: 總報酬 {total_ret:+7.1%}  基準 {res['bench_total_return']:+7.1%}  "
                  f"alpha t={rs['alpha_t']:5.2f}  beta {rs['beta']:.2f}  超額t={rs['t_excess']:5.2f}  "
                  f"夏普 {rs['sharpe']:.2f}/{rs['bench_sharpe']:.2f}  MDD {mdd:.0%}/{rs['bench_mdd']:.0%}")
        return

    res = run_backtest(pool, args.benchmark, args.lookback, args.skip, args.top_k,
                        args.cost_bps, args.start, not args.no_abs_filter, args.cap_top_n, pointintime,
                        args.signal, args.vol_days, sectors, args.sector_neutral, args.sector_only,
                        args.div_months)
    label = (f"signal={args.signal} " + {"momentum": f"lookback={args.lookback} skip={args.skip}",
                                          "lowvol": f"vol_days={args.vol_days}",
                                          "divyield": f"div_months={args.div_months}"}[args.signal]
             + f" top_k={args.top_k} cost={args.cost_bps}bps")
    if args.cap_top_n:
        label += f" cap_top_n={args.cap_top_n}"
    if pointintime:
        label += " point-in-time"
    if args.sector_neutral:
        label += " 行業中性"
    if args.sector_only:
        label += f" 只持{args.sector_only}"
    report(res, label)


if __name__ == "__main__":
    main()
