#!/usr/bin/env python3
"""港股動量輪動策略回測（原型）——月頻只做多動量輪動 vs 買入持有基準。

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
import csv
import gzip
import math
import sys
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data" / "stocks"


def load_series(ticker: str) -> dict[date, tuple[float, float, float]]:
    """回傳 {date: (adj_open, adj_close, raw_close)}。raw_close 給市值排名用
    （市值 = 當時實際股價 x 當時實際股數，不能用還原股息/拆股的 AdjClose）。"""
    path = DATA_DIR / (ticker.replace("^", "_") + ".csv.gz")
    out = {}
    with gzip.open(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row["Date"])
            o, c, ac = float(row["Open"]), float(row["Close"]), float(row["AdjClose"])
            # yfinance 港股數據偶有 Open=0 的髒值（見 data/stocks/README.md 已知限制），
            # 退回用 AdjClose 當天的收盤價估開盤（假設無隔夜跳空，聊勝於除以零崩潰）
            adj_open = o * (ac / c) if c and o else ac
            out[d] = (adj_open, ac, c)
    return out


def load_shares(ticker: str) -> list[tuple[date, int]] | None:
    """回傳按日期排序的 [(date, shares_outstanding), ...]，抓不到就 None。
    見 scripts/fetch_stock_data.py 的 fetch_shares_outstanding。"""
    path = DATA_DIR / (ticker.replace("^", "_") + ".shares.csv.gz")
    if not path.exists():
        return None
    out = []
    with gzip.open(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            out.append((date.fromisoformat(row["Date"]), int(row["Shares"])))
    out.sort()
    return out or None


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


def run_backtest(pool: list[str], benchmark: str, lookback: int, skip: int,
                  top_k: int, cost_bps: float, start: date | None,
                  abs_filter: bool, cap_top_n: int | None = None) -> dict:
    all_tickers = pool + [benchmark]
    series = {t: load_series(t) for t in all_tickers}
    shares = {t: load_shares(t) for t in pool} if cap_top_n else {}
    excluded_no_cap_data = 0

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
    equity_curve: list[tuple[date, float]] = [(exec_dates[0][1], 1.0)]
    period_returns: list[tuple[date, float]] = []  # (exec_date, net period return)
    current_basket: set[str] = set()
    total_cost_paid = 0.0
    cash_periods = 0

    for i in range(lookback + skip, len(exec_dates) - 1):
        signal_me, entry_exec = exec_dates[i]
        _, exit_exec = exec_dates[i + 1]

        # --- point-in-time 市值前 N 大過濾（近似 point-in-time 成分股表，
        #     見 RESEARCH_HANDBOOK.md 第三節第4條：不能只用「現在還在」的名單）---
        if cap_top_n:
            caps = []
            for t in pool:
                sh = shares.get(t)
                if sh is None or signal_me not in series[t]:
                    continue
                n_shares = shares_asof(sh, signal_me)
                if n_shares is None:
                    continue
                raw_close = series[t][signal_me][2]
                caps.append((raw_close * n_shares, t))
            excluded_no_cap_data += len(pool) - len(caps)
            caps.sort(reverse=True)
            eligible = {t for _, t in caps[:cap_top_n]}
        else:
            eligible = set(pool)

        # --- 算動量，選籃子 ---
        scored = []
        for t in eligible:
            s = series[t]
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
                if entry_exec not in s or exit_exec not in s:
                    continue
                p0 = s[entry_exec][0]
                p1 = s[exit_exec][0]
                if p0 > 0:
                    rets.append(p1 / p0 - 1.0)
            gross_ret = sum(rets) / len(rets) if rets else 0.0
        else:
            gross_ret = 0.0

        net_ret = gross_ret - cost_frac
        equity *= (1.0 + net_ret)
        total_cost_paid += cost_frac
        equity_curve.append((exit_exec, equity))
        period_returns.append((exit_exec, net_ret))
        current_basket = new_basket

    # --- 基準買入持有（同一段執行日窗口）---
    bench = series[benchmark]
    b_start = exec_dates[lookback + skip][1]
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
    print(f"空手（無合格標的）月數: {res['cash_periods']}/{n}")
    if res.get("avg_excluded_no_cap_data"):
        print(f"平均每期因缺流通股數資料被排除的候選數: {res['avg_excluded_no_cap_data']:.1f}")
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
    ap.add_argument("--sweep", action="store_true", help="掃 lookback x top-k 鄰域，檢查手冊鐵律第4條的參數平原")
    args = ap.parse_args()

    pool = read_pool(args.universe, exclude={args.benchmark})
    print(f"股票池（{len(pool)} 檔，非權威成分股表）: {pool}")

    if args.sweep:
        for lb in (6, 9, 12):
            for k in (2, 3, 4):
                try:
                    res = run_backtest(pool, args.benchmark, lb, args.skip, k,
                                        args.cost_bps, args.start, not args.no_abs_filter,
                                        args.cap_top_n)
                except SystemExit as e:
                    print(f"lookback={lb} top_k={k}: {e}")
                    continue
                total_ret = res["final_equity"] - 1.0
                rets = [r for _, r in res["period_returns"]]
                t = t_stat(rets)
                print(f"lookback={lb:2d} top_k={k}: 總報酬 {total_ret:+7.1%}  "
                      f"基準 {res['bench_total_return']:+7.1%}  t={t:5.2f}  "
                      f"空手 {res['cash_periods']}/{res['n_periods']}")
        return

    res = run_backtest(pool, args.benchmark, args.lookback, args.skip, args.top_k,
                        args.cost_bps, args.start, not args.no_abs_filter, args.cap_top_n)
    label = f"lookback={args.lookback} skip={args.skip} top_k={args.top_k} cost={args.cost_bps}bps"
    if args.cap_top_n:
        label += f" cap_top_n={args.cap_top_n}"
    report(res, label)


if __name__ == "__main__":
    main()
