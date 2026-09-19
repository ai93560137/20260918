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


def load_one(symbol, start, end):
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise SystemExit(f"抓不到 {symbol} 的資料")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close", "Adj Close"]].dropna()


def blend(rets, wts, code):
    """多標的定期再平衡的組合報酬。

    再平衡之間讓權重自然漂移，期初才拉回目標——這才是真實做法。
    每天強制拉回會產生虛假的再平衡紅利。
    """
    idx = rets.index
    cur = np.array(wts, dtype=float)
    out = np.zeros(len(idx))
    for i in range(len(idx)):
        if i == 0 or idx[i].to_period(code) != idx[i - 1].to_period(code):
            cur = np.array(wts, dtype=float)
        row = rets.iloc[i].values
        rp = float((cur * row).sum())
        out[i] = rp
        g = 1.0 + rp
        cur = cur * (1.0 + row) / g if g > 0 else cur
    return pd.Series(out, index=idx)


def build_returns(df, div_tax):
    """總報酬 = 價格報酬 + 稅後股息報酬。

    Adj Close 的報酬 = 股息全額再投資（未扣稅）；Close 的報酬 = 純價格報酬。
    兩者之差就是當根的股息報酬率，乘 (1 - 稅率) 還原成稅後。
    """
    r_total = df["Adj Close"].pct_change()
    r_price = df["Close"].pct_change()
    r_div = (r_total - r_price).clip(lower=0.0)
    return (r_price + r_div * (1.0 - div_tax)).dropna()


def realized_vol(r, a):
    """年化實際波動率（%），用『到前一根為止』的資料。"""
    return r.rolling(a.vol_len).std() * np.sqrt(a.bars_per_year) * 100.0


def bandify(raw, a):
    """把目標權重序列套上上下限與再平衡門檻，回傳實際權重與換手。

    權重一律用『前一根收盤』定下、當根才生效——不偷看未來。
    """
    w = np.full(len(raw), 1.0)
    turn = np.zeros(len(raw))
    cur = 1.0
    for i in range(len(raw)):
        w[i] = cur
        v = raw.iloc[i]
        if np.isfinite(v):
            new = min(a.max_w, max(a.min_w, v))
            if abs(new - cur) > a.band:
                turn[i] = abs(new - cur)   # 換手成本在收盤後扣
                cur = new
    return pd.Series(w, index=raw.index), pd.Series(turn, index=raw.index)


def weights(r, a):
    """調兵：w ∝ 目標波動 ÷ 實際波動（= 假設夏普不變的凱利）。"""
    vol = realized_vol(r, a)
    return bandify(a.target_vol / vol.where(vol > 0), a)


def kelly_weights(r, a):
    """凱利：w = 下注比例 × μ ÷ σ²。

    與調兵的差別在分母是 σ² 而不是 σ。兩者相等的條件是 μ ∝ σ（夏普不變），
    那是一個假設，不是事實——所以值得並排跑，看資料站在哪一邊。
    """
    vol = realized_vol(r, a) / 100.0
    raw = a.kelly_frac * (a.kelly_mu / 100.0) / (vol.where(vol > 0) ** 2)
    return bandify(raw, a)


PERIOD = {"monthly": ("M", 1), "quarterly": ("Q", 3), "annual": ("Y", 12)}


def is_start(idx, i, i0, code):
    """這一根是不是提領期間的第一根。"""
    return i == i0 or idx[i].to_period(code) != idx[i - 1].to_period(code)


def sim(r, w, turn, a, i0, i1, principal):
    """逐根模擬真實餘額。

    固定提領模式下，結果必須與 10.1 的線性公式一致——這是內建的自我檢查。
    比例提領模式下線性不成立（提領金額取決於餘額），只能這樣逐根跑。
    """
    idx = r.index
    code, mult = PERIOD[a.freq]
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

        if is_start(idx, i, i0, code):
            amt = wd_fixed * mult if a.mode == "fixed" else bal * a.pct / 100.0 * mult / 12.0
            if a.mode == "pct" and a.floor > 0:
                amt = max(amt, a.floor * mult)
            take = min(amt + a.trade_fee, max(0.0, bal))   # 手續費也要賣股票來付
            amt = max(0.0, take - a.trade_fee)
            bal -= take
            incomes.append(amt / mult)                     # 一律換算成「每月等值」才能比較
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
    code, mult = PERIOD[a.freq]
    rate_cash = a.cash_rate / 100.0 / a.bars_per_year
    rate_brw = (a.cash_rate + a.borrow_spread) / 100.0 / a.bars_per_year
    g, h, wd = 1.0, 0.0, a.monthly
    for i in range(i0, i1):
        if i > i0 and idx[i].year != idx[i - 1].year:
            wd *= 1.0 + a.infl / 100.0
        wi = w.iloc[i]
        excess = wi - 1.0
        g *= 1.0 + wi * r.iloc[i] - excess * (rate_brw if excess > 0 else rate_cash)
        if is_start(idx, i, i0, code):
            h += (wd * mult + a.trade_fee) / g
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
    p.add_argument("--symbol", default="SPY",
                   help="單一標的，或以逗號分隔的多標的（例如 SPY,EWJ,EFA）。"
                        "多標的會取日期交集——結果會被歷史最短的那一支截斷。")
    p.add_argument("--weights", default="",
                   help="多標的的權重，逗號分隔（例如 0.4,0.2,0.4）。省略 = 等權。自動正規化。")
    p.add_argument("--blend-rebal", choices=["monthly", "quarterly", "annual"], default="annual",
                   help="多標的之間的再平衡頻率。預設年度——再平衡之間讓權重自然漂移。")
    p.add_argument("--start", default="1993-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--principal", type=float, default=15_000_000)
    p.add_argument("--monthly", type=float, default=50_000, help="fixed 模式的每月提領")
    p.add_argument("--mode", choices=["fixed", "pct", "both"], default="fixed")
    p.add_argument("--freq", choices=["monthly", "quarterly", "annual"], default="monthly",
                   help="提領頻率。--monthly 永遠是『每月等值金額』，季提=×3、年提=×12，"
                        "所以三種頻率的年提領總額相同，可以直接比較。")
    p.add_argument("--trade-fee", type=float, default=0.0,
                   help="每一筆提領的固定交易成本（元）。小額本金的關鍵變數："
                        "月提一年 12 筆、年提一年 1 筆。")
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
    p.add_argument("--kelly-mu", type=float, default=0.0,
                   help="加一組凱利對照：假設的年化超額算術報酬 %%（SPY 約 6.7）。0 = 不跑。"
                        "凱利 w = 下注比例 × μ/σ²，調兵 w = 目標σ/σ——差在分母的次方。")
    p.add_argument("--kelly-frac", type=float, default=0.5,
                   help="下注滿凱利的幾倍。預設 0.5（半凱利）。滿凱利的『跌到剩一半』機率是 50%%，"
                        "半凱利只有 12.5%%，而成長率仍有滿凱利的 75%%。")
    p.add_argument("--trend", type=int, default=0,
                   help="加一組趨勢濾網對照（例如 200 = 200 日均線）：價格在均線之上滿倉、"
                        "之下空手（資金收現金利息）。訊號用前一根收盤決定，不偷看未來。"
                        "調兵量的是『波動』，趨勢濾網量的是『方向』——日本式陰跌正好是"
                        "波動不高但方向向下，這一組是專門用來檢驗那個缺口的。")
    p.add_argument("--static-w", type=float, default=0.0,
                   help="對照組：固定曝險倍數（例如 0.6）。設 -1 = 自動用調兵的平均曝險。"
                        "這是檢驗『調兵的好處是不是只因為股票買得少』的關鍵對照組。")
    a = p.parse_args()

    syms = [x.strip() for x in a.symbol.split(",") if x.strip()]
    if a.weights:
        wts = [float(x) for x in a.weights.split(",")]
        if len(wts) != len(syms):
            raise SystemExit(f"標的 {len(syms)} 個，權重 {len(wts)} 個，對不上")
    else:
        wts = [1.0 / len(syms)] * len(syms)
    tot_w = sum(wts)
    wts = [x / tot_w for x in wts]

    if len(syms) == 1:
        r = build_returns(load_one(syms[0], a.start, a.end), a.div_tax)
    else:
        cols = {}
        for sym in syms:
            cols[sym] = build_returns(load_one(sym, a.start, a.end), a.div_tax)
        rets = pd.DataFrame(cols).dropna()          # 交集日期：被最短的那一支截斷
        if rets.empty:
            raise SystemExit("各標的的日期沒有交集")
        r = blend(rets, wts, PERIOD[a.blend_rebal][0])
    w, turn = weights(r, a)
    idx = r.index
    n = len(r)

    g_bh = np.prod(1.0 + r.values)
    cagr = g_bh ** (a.bars_per_year / n) - 1
    flag = "" if -0.20 < cagr < 0.30 else "   ⚠ 異常，別信下面任何數字"

    head = a.symbol if len(syms) == 1 else \
        " + ".join(f"{sy} {wt:.0%}" for sy, wt in zip(syms, wts)) + f"（{a.blend_rebal} 再平衡）"
    print(f"\n{head}  {idx[0].date()} → {idx[-1].date()}  ({n/a.bars_per_year:.1f} 年)")
    freq_zh = {"monthly": "月提", "quarterly": "季提", "annual": "年提"}[a.freq]
    print(f"本金 {money(a.principal)}   通膨 {a.infl}%   股息稅 {a.div_tax:.0%}"
          f"   調兵目標波動 {a.target_vol}%")
    print(f"提領頻率 {freq_zh}（每筆 {money(a.monthly*PERIOD[a.freq][1])}）"
          f"   每筆手續費 {a.trade_fee:,.0f}   現金利率 {a.cash_rate}%   換手成本 {a.cost_bps}bp")
    print(f"年化報酬（檢查）買入持有 {cagr:.2%}{flag}")
    print("=" * 78)

    ones = pd.Series(1.0, index=idx)
    zeros = pd.Series(0.0, index=idx)
    strat = [("調兵", w, turn), ("買入持有", ones, zeros)]
    if a.static_w != 0.0:
        sw = w.mean() if a.static_w < 0 else a.static_w
        strat.append((f"固定曝險 {sw:.2f}x", pd.Series(sw, index=idx), zeros))
    if a.kelly_mu > 0:
        kw, kt = kelly_weights(r, a)
        strat.append((f"凱利 {a.kelly_frac:g}× (μ={a.kelly_mu:g}%)", kw, kt))
    if a.trend > 0:
        px = (1.0 + r).cumprod()                       # 合成價格指數（混合組合也適用）
        sig = (px > px.rolling(a.trend).mean()).shift(1).fillna(False)
        tw = sig.astype(float)
        strat.append((f"趨勢濾網 {a.trend}日", tw, tw.diff().abs().fillna(0.0)))

    modes = ["fixed", "pct"] if a.mode == "both" else [a.mode]
    for m in modes:
        a.mode = m
        label = (f"固定提領 {money(a.monthly)}/月等值" if m == "fixed"
                 else f"比例提領 {a.pct}%/年")
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
