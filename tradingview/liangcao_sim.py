#!/usr/bin/env python3
"""
糧草 — 提領模擬器（Python 獨立實作）

與 TradingView 的 zhugeliang_liangcao_v1.pine 互相驗證。
兩套程式碼、兩個資料來源，數字對得上才能信。

    pip install yfinance pandas numpy
    python3 liangcao_sim.py --symbol SPY --principal 15000000 --monthly 50000

兩種提領模式：
  fixed  固定金額——每月提固定的錢。會破產，但收入穩定。
  pct    比例提領——每月提「當時餘額」的固定比例。永遠不會破產，
         但收入會跟著市場縮水。崩盤時自動少提，這正是它不破產的原因。

資料：Yahoo Finance 的 Adj Close（已還原股息與拆股）= 總報酬。
Adj Close 是「股息全額再投資、不扣稅」，--div-tax 0.30 會從 Close 與
Adj Close 的差額反推股息再打折，還原稅後總報酬。
"""
import argparse
import numpy as np
import pandas as pd

W = 10_000.0  # 顯示單位：萬


def load(symbol, start, end):
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise SystemExit(f"抓不到 {symbol} 的資料")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close", "Adj Close"]].dropna()


def build_returns(df, div_tax):
    """總報酬 = 價格報酬 + 稅後股息報酬。

    Adj Close 的報酬 = 股息全額再投資（未扣稅）；Close 的報酬 = 純價格報酬。
    兩者之差就是當根的股息報酬率，乘 (1 - 稅率) 還原成稅後。
    """
    r_total = df["Adj Close"].pct_change()
    r_price = df["Close"].pct_change()
    r_div = (r_total - r_price).clip(lower=0.0)
    return (r_price + r_div * (1.0 - div_tax)).dropna()


def weights(r, a):
    """調兵的曝險權重：用『前一根收盤』算出的波動率決定，當根才生效。"""
    vol = r.rolling(a.vol_len).std() * np.sqrt(a.bars_per_year) * 100.0
    w = np.full(len(r), 1.0)
    turn = np.zeros(len(r))
    cur = 1.0
    for i in range(len(r)):
        w[i] = cur                       # 這一根用的是上一根收盤定下的權重
        v = vol.iloc[i]
        if np.isfinite(v) and v > 0:
            new = min(a.max_w, max(a.min_w, a.target_vol / v))
            if abs(new - cur) > a.band:
                turn[i] = abs(new - cur)  # 換手成本在收盤後扣
                cur = new
    return pd.Series(w, index=r.index), pd.Series(turn, index=r.index)


def sim(r, w, turn, a, i0, i1, principal):
    """逐根模擬真實餘額。

    固定提領模式下，結果必須與 10.1 的線性公式一致——這是內建的自我檢查。
    比例提領模式下線性不成立（提領金額取決於餘額），只能這樣逐根跑。
    """
    idx = r.index
    bal = principal
    wd_fixed = a.monthly
    rate_cash = a.cash_rate / 100.0 / a.bars_per_year
    rate_brw = (a.cash_rate + a.borrow_spread) / 100.0 / a.bars_per_year

    bals, incomes, inc_year = [], [], []
    peak, dd, busted = bal, 0.0, None

    for i in range(i0, i1):
        if i > i0 and idx[i].year != idx[i - 1].year:
            wd_fixed *= 1.0 + a.infl / 100.0

        wi = w.iloc[i]
        excess = wi - 1.0
        r_port = wi * r.iloc[i] - excess * (rate_brw if excess > 0 else rate_cash)
        bal *= 1.0 + r_port

        if i == i0 or idx[i].to_period("M") != idx[i - 1].to_period("M"):
            amt = wd_fixed if a.mode == "fixed" else bal * a.pct / 100.0 / 12.0
            if a.mode == "pct" and a.floor > 0:
                amt = max(amt, a.floor)
            amt = max(0.0, min(amt, bal))          # 提不出比餘額多的錢
            bal -= amt
            incomes.append(amt)
            inc_year.append(idx[i].year)

        if turn.iloc[i] > 0:
            bal *= 1.0 - turn.iloc[i] * a.cost_bps / 10000.0

        peak = max(peak, bal)
        dd = max(dd, (peak - bal) / peak if peak > 0 else 0.0)
        if bal <= 0 and busted is None:
            busted = idx[i].year
        bals.append(bal)

    inc = np.array(incomes)
    return {
        "end": bal, "min": min(bals) if bals else np.nan, "dd": dd, "busted": busted,
        "inc": inc, "inc_year": inc_year, "total": inc.sum(),
        "n": i1 - i0, "avg_w": w.iloc[i0:i1].mean(),
    }


def linear_need(r, w, turn, a, i0, i1):
    """固定提領的『所需本金』= 提領流在這條報酬路徑上的現值（見 README 10.1）。"""
    idx = r.index
    rate_cash = a.cash_rate / 100.0 / a.bars_per_year
    rate_brw = (a.cash_rate + a.borrow_spread) / 100.0 / a.bars_per_year
    g, h, wd = 1.0, 0.0, a.monthly
    for i in range(i0, i1):
        if i > i0 and idx[i].year != idx[i - 1].year:
            wd *= 1.0 + a.infl / 100.0
        wi = w.iloc[i]
        excess = wi - 1.0
        g *= 1.0 + wi * r.iloc[i] - excess * (rate_brw if excess > 0 else rate_cash)
        if i == i0 or idx[i].to_period("M") != idx[i - 1].to_period("M"):
            h += wd / g
        if turn.iloc[i] > 0:
            g *= 1.0 - turn.iloc[i] * a.cost_bps / 10000.0
    return h


def money(x):
    return f"{x/W:,.1f}萬" if abs(x) >= W else f"{x:,.0f}"


def report(tag, res, a):
    inc = res["inc"]
    print(f"{tag:22}", end="")
    print(f"{money(max(0, res['end'])):>14}", end="")
    if a.mode == "fixed":
        print(f"{'破產 '+str(res['busted']) if res['busted'] else '撐住':>12}", end="")
    else:
        print(f"{money(inc.min()):>12}", end="")
    print(f"{money(inc.mean()):>12}{res['dd']:>10.1%}{res['avg_w']:>9.2f}x")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--start", default="1993-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--principal", type=float, default=15_000_000)
    p.add_argument("--monthly", type=float, default=50_000, help="fixed 模式的每月提領")
    p.add_argument("--mode", choices=["fixed", "pct", "both"], default="fixed")
    p.add_argument("--pct", type=float, default=4.0, help="pct 模式：每年提當時餘額的百分之幾")
    p.add_argument("--floor", type=float, default=0.0, help="pct 模式：每月最低提領（會恢復破產風險）")
    p.add_argument("--infl", type=float, default=0.0, help="提領年增率 %%（0 = 不做通膨調整）")
    p.add_argument("--horizon", type=int, default=20, help="逐年表的年期（0 = 算到資料結束）")
    p.add_argument("--target-vol", type=float, default=15.0)
    p.add_argument("--vol-len", type=int, default=60)
    p.add_argument("--max-w", type=float, default=1.0)
    p.add_argument("--min-w", type=float, default=0.0)
    p.add_argument("--band", type=float, default=0.10)
    p.add_argument("--cost-bps", type=float, default=1.0)
    p.add_argument("--cash-rate", type=float, default=2.0)
    p.add_argument("--borrow-spread", type=float, default=1.0)
    p.add_argument("--div-tax", type=float, default=0.30)
    p.add_argument("--bars-per-year", type=int, default=252)
    p.add_argument("--static-w", type=float, default=0.0,
                   help="對照組：固定曝險倍數（例如 0.6）。設 -1 = 自動用調兵的平均曝險。"
                        "這是檢驗『調兵的好處是不是只因為股票買得少』的關鍵對照組。")
    a = p.parse_args()

    df = load(a.symbol, a.start, a.end)
    r = build_returns(df, a.div_tax)
    w, turn = weights(r, a)
    idx = r.index
    n = len(r)

    g_bh = np.prod(1.0 + r.values)
    cagr = g_bh ** (a.bars_per_year / n) - 1
    flag = "" if -0.20 < cagr < 0.30 else "   ⚠ 異常，別信下面任何數字"

    print(f"\n{a.symbol}  {idx[0].date()} → {idx[-1].date()}  ({n/a.bars_per_year:.1f} 年)")
    print(f"本金 {money(a.principal)}   通膨 {a.infl}%   股息稅 {a.div_tax:.0%}"
          f"   調兵目標波動 {a.target_vol}%")
    print(f"年化報酬（檢查）買入持有 {cagr:.2%}{flag}")
    print("=" * 78)

    ones = pd.Series(1.0, index=idx)
    zeros = pd.Series(0.0, index=idx)
    strat = [("調兵", w, turn), ("買入持有", ones, zeros)]
    if a.static_w != 0.0:
        sw = w.mean() if a.static_w < 0 else a.static_w
        strat.append((f"固定曝險 {sw:.2f}x", pd.Series(sw, index=idx), zeros))

    modes = ["fixed", "pct"] if a.mode == "both" else [a.mode]
    for m in modes:
        a.mode = m
        label = f"固定提領 {money(a.monthly)}/月" if m == "fixed" else f"比例提領 {a.pct}%/年"
        print(f"\n【{label}】")
        print(f"{'':22}{'期末餘額':>14}{'是否破產' if m=='fixed' else '最低月提領':>12}"
              f"{'平均月提領':>12}{'最大回撤':>10}{'平均曝險':>10}")
        for tag, ws, ts in strat:
            report(tag, sim(r, ws, ts, a, 0, n, a.principal), a)

    # ── 逐年起始 ──
    a.mode = modes[0]
    starts = [i for i in range(n) if i == 0 or idx[i].year != idx[i - 1].year]
    print(f"\n逐年起始（年期 {a.horizon} 年，模式 {a.mode}）")
    print("-" * 78)
    col = "所需本金" if a.mode == "fixed" else "最低月提"
    print(f"{'起始年':>6}" + "".join(f"{t+'·'+col:>15}" for t, _, _ in strat))
    ok = [0] * len(strat)
    tot = 0
    worst = [0.0] * len(strat)
    for i0 in starts:
        y0 = idx[i0].year
        end = [i for i in starts if idx[i].year == y0 + a.horizon] if a.horizon else [n]
        if not end:
            continue
        i1 = end[0]
        tot += 1
        cells = []
        for k, (t, ws, ts) in enumerate(strat):
            res = sim(r, ws, ts, a, i0, i1, a.principal)
            ok[k] += res["end"] > 0
            if a.mode == "fixed":
                v = linear_need(r, ws, ts, a, i0, i1)
                worst[k] = max(worst[k], v)
                cells.append(f"{money(v)}{'✔' if res['end']>0 else '✘'}")
            else:
                worst[k] = max(worst[k], -res["inc"].min())
                cells.append(money(res["inc"].min()))
        print(f"{y0:>6}" + "".join(f"{c:>15}" for c in cells))
    if tot:
        print("-" * 78)
        print(f"{'存活率':>6}" + "".join(f"{f'{ok[k]/tot:.0%}':>15}" for k in range(len(strat))))
        if a.mode == "fixed":
            print(f"{'最糟':>6}" + "".join(f"{money(worst[k]):>15}" for k in range(len(strat))))
            print(f"{'→月提上限':>6}" +
                  "".join(f"{money(a.monthly*a.principal/worst[k]):>15}" for k in range(len(strat))))


if __name__ == "__main__":
    main()
