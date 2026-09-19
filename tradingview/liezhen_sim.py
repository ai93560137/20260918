#!/usr/bin/env python3
"""
智能諸葛亮 · 列陣 — 分批進場模擬器

把資金切成 N 等份，比較四種投入方式：

  一次全投    開局就全部投入（基準線）
  定期定額    每隔固定時間投一份
  逢跌加碼    每跌 X% 投一份，創新高後重置格子
  逢跌+期限   逢跌加碼，但超過期限仍未投完就全部投入

未投入的資金收現金利息——**這是整件事的關鍵**。
等待不是免費的，那筆錢的機會成本會一直累積。

    pip install yfinance pandas numpy
    python3 liezhen_sim.py --symbol SPY --principal 1000000 --n 10 --dip-step 5

誠實聲明：
  1. 只買不賣。投入的錢不會再拿出來。
  2. 逢跌加碼的格子在創新高後重置，等於每一輪下跌都能重新加碼——
     這對該策略是寬容的假設。
  3. 不含手續費（分批會產生 N 筆交易，一次全投只有 1 筆）。
"""
import argparse
import numpy as np
import pandas as pd

W = 10_000.0


def load_one(symbol, start, end):
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise SystemExit(f"抓不到 {symbol} 的資料")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close", "Adj Close"]].dropna()


def build_returns(df, div_tax):
    """總報酬 = 價格報酬 + 稅後股息報酬。"""
    r_total = df["Adj Close"].pct_change()
    r_price = df["Close"].pct_change()
    r_div = (r_total - r_price).clip(lower=0.0)
    return (r_price + r_div * (1.0 - div_tax)).dropna()


def run(r, i0, i1, a, mode):
    """逐根模擬。回傳期末餘額、最大回撤、平均投入比例、投完所花的年數。"""
    idx = r.index
    tranche = a.principal / a.n
    cash, equity, used = a.principal, 0.0, 0
    rate_d = a.cash_rate / 100.0 / a.bars_per_year
    px, peak, lvl_used = 1.0, 1.0, 0
    pk_val, dd, sum_inv, n_bar = a.principal, 0.0, 0.0, 0
    full_at = None
    months = 0

    for i in range(i0, i1):
        new_month = i == i0 or idx[i].to_period("M") != idx[i - 1].to_period("M")
        if new_month and i > i0:
            months += 1

        # ── 今天投幾份 ──
        add = 0
        if i == i0:
            add = a.n if mode == "lump" else 1          # 分批也是先投一份，不是全部空手等
        elif mode in ("dca",) and new_month and months % a.dca_months == 0:
            add = 1
        elif mode in ("dip", "dipf"):
            drop = 1.0 - px / peak
            lvl = int(drop / (a.dip_step / 100.0))
            if lvl > lvl_used:
                add = lvl - lvl_used
                lvl_used = lvl
            if mode == "dipf" and a.force_years > 0 and \
               (i - i0) >= a.force_years * a.bars_per_year:
                add = a.n                                # 期限到了，剩下的一次投完
        add = min(add, a.n - used)
        if add > 0:
            equity += add * tranche
            cash -= add * tranche
            used += add
            if used >= a.n and full_at is None:
                full_at = (i - i0) / a.bars_per_year

        # ── 這一根的損益 ──
        ri = r.iloc[i]
        equity *= 1.0 + ri
        cash *= 1.0 + rate_d
        px *= 1.0 + ri
        if px > peak:                                    # 創新高 → 格子重置
            peak = px
            lvl_used = 0

        tot = equity + cash
        pk_val = max(pk_val, tot)
        dd = max(dd, (pk_val - tot) / pk_val if pk_val > 0 else 0.0)
        sum_inv += equity / tot if tot > 0 else 0.0
        n_bar += 1

    return {"end": equity + cash, "dd": dd,
            "inv": sum_inv / max(1, n_bar),
            "full": full_at if full_at is not None else np.nan}


MODES = [("lump", "一次全投"), ("dca", "定期定額"), ("dip", "逢跌加碼"), ("dipf", "逢跌+期限")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--start", default="1993-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--principal", type=float, default=1_000_000)
    p.add_argument("--n", type=int, default=10, help="切成幾等份")
    p.add_argument("--dca-months", type=int, default=1, help="定期定額：每幾個月投一份")
    p.add_argument("--dip-step", type=float, default=5.0, help="逢跌加碼：每跌百分之幾投一份")
    p.add_argument("--force-years", type=float, default=2.0, help="逢跌+期限：幾年後強制投完")
    p.add_argument("--horizon", type=int, default=10, help="每組模擬幾年")
    p.add_argument("--cash-rate", type=float, default=3.0, help="未投入資金的年利率 %%")
    p.add_argument("--div-tax", type=float, default=0.30)
    p.add_argument("--bars-per-year", type=int, default=252)
    a = p.parse_args()

    r = build_returns(load_one(a.symbol, a.start, a.end), a.div_tax)
    idx, n = r.index, len(r)
    cagr = float(np.prod(1.0 + r.values)) ** (a.bars_per_year / n) - 1
    flag = "" if -0.20 < cagr < 0.30 else "   ⚠ 異常，別信下面任何數字"

    print(f"\n{a.symbol}  {idx[0].date()} → {idx[-1].date()}  ({n/a.bars_per_year:.1f} 年)")
    print(f"本金 {a.principal/W:,.0f}萬 切成 {a.n} 份（每份 {a.principal/a.n/W:,.0f}萬）   "
          f"定期定額每 {a.dca_months} 個月   逢跌每 {a.dip_step:g}%   "
          f"強制投完 {a.force_years:g} 年   現金利率 {a.cash_rate}%")
    print(f"年化報酬（檢查）買入持有 {cagr:.2%}{flag}")
    print("=" * 76)

    print(f"\n【全期 {n/a.bars_per_year:.1f} 年】")
    print(f"{'':14}{'期末餘額':>13}{'最大回撤':>10}{'平均投入':>10}{'投完所需':>10}")
    for m, name in MODES:
        s = run(r, 0, n, a, m)
        full = "—" if np.isnan(s["full"]) else f"{s['full']:.1f}年"
        print(f"{name:14}{s['end']/W:>12,.0f}萬{s['dd']:>10.1%}{s['inv']:>10.0%}{full:>10}")

    starts = [i for i in range(n) if i == 0 or idx[i].year != idx[i - 1].year]
    print(f"\n逐年起始（每組 {a.horizon} 年，期末餘額）")
    print("-" * 76)
    print(f"{'起始年':>6}" + "".join(f"{nm:>13}" for _, nm in MODES) + "   贏過一次全投")
    win = {m: 0 for m, _ in MODES}
    tot = 0
    for i0 in starts:
        y0 = idx[i0].year
        end = [i for i in starts if idx[i].year == y0 + a.horizon]
        if not end:
            continue
        i1 = end[0]
        res = {m: run(r, i0, i1, a, m) for m, _ in MODES}
        base = res["lump"]["end"]
        tot += 1
        for m, _ in MODES:
            if res[m]["end"] > base:
                win[m] += 1
        mark = " ".join("✔" if res[m]["end"] > base else "·" for m, _ in MODES[1:])
        print(f"{y0:>6}" + "".join(f"{res[m]['end']/W:>12,.0f}萬" for m, _ in MODES) + f"   {mark}")
    if tot:
        print("-" * 76)
        print(f"{'勝率':>6}" + "".join(f"{f'{win[m]/tot:.0%}':>13}" for m, _ in MODES) +
              f"   （{tot} 組，對照一次全投）")


if __name__ == "__main__":
    main()
