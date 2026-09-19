#!/usr/bin/env python3
"""
糧草 — 提領模擬器（Python 獨立實作）

用途：與 TradingView 的 zhugeliang_liangcao_v1.pine 互相驗證。
兩套程式碼、兩個資料來源，數字對得上才能信。

    pip install yfinance pandas numpy
    python3 liangcao_sim.py --symbol SPY --principal 15000000 --monthly 50000

資料：Yahoo Finance 的 Adj Close（已還原股息與拆股）= 總報酬。
注意：Adj Close 是「股息全額再投資、不扣稅」。要比照 Pine 的 30% 預扣稅，
      用 --div-tax 0.30，程式會從 Close 與 Adj Close 的差額反推股息再打折。
"""
import argparse
import numpy as np
import pandas as pd


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

    Adj Close 的報酬 = 股息全額再投資（未扣稅）。
    價格報酬 = Close 的報酬。兩者之差就是當根的股息報酬率，乘上 (1 - 稅率) 還原稅後。
    """
    r_total = df["Adj Close"].pct_change()
    r_price = df["Close"].pct_change()
    r_div = (r_total - r_price).clip(lower=0.0)          # 股息報酬（浮點誤差壓成 0）
    return (r_price + r_div * (1.0 - div_tax)).dropna()


def weights(r, target_vol, vol_len, max_w, min_w, band, bars_per_year):
    """調兵的曝險權重：用『前一根收盤』算出的波動率決定，當根才生效。"""
    vol = r.rolling(vol_len).std() * np.sqrt(bars_per_year) * 100.0
    w = np.full(len(r), np.nan)
    cur = 1.0
    turn = np.zeros(len(r))
    for i in range(len(r)):
        w[i] = cur                                        # 這一根用的是上一根收盤定下的權重
        v = vol.iloc[i]
        if np.isfinite(v) and v > 0:
            new = min(max_w, max(min_w, target_vol / v))
            if abs(new - cur) > band:
                turn[i] = abs(new - cur)                  # 換手成本在收盤後扣
                cur = new
    return pd.Series(w, index=r.index), pd.Series(turn, index=r.index), vol


def simulate(r, w, turn, a):
    """回傳兩條 $1 成長曲線 G 與兩條提領現值 H（金額單位）。

    固定提領下餘額對本金是線性的：
        餘額_t = G_t × (本金 − Σ_{u≤t} 提領_u / G_u)
    令 H_t = Σ 提領_u / G_u，破產 ⟺ 本金 < H_t，且 H 單調遞增 → 臨界點在期末。
    """
    idx = r.index
    month = pd.Series(idx.to_period("M"), index=idx)
    new_month = month != month.shift(1)
    new_year = pd.Series(idx.year, index=idx) != pd.Series(idx.year, index=idx).shift(1)

    gB = gV = 1.0
    hB = hV = 0.0
    wd = a.monthly
    rate_cash = a.cash_rate / 100.0 / a.bars_per_year
    rate_brw = (a.cash_rate + a.borrow_spread) / 100.0 / a.bars_per_year

    GB, GV, HB, HV, YR = [], [], [], [], []
    snap = []                                             # 年度邊界快照（G、H 在這一年開始時的值）
    for i, t in enumerate(idx):
        if new_year.iloc[i]:
            if snap:
                wd *= 1.0 + a.infl / 100.0
            snap.append((t.year, gB, hB, gV, hV))

        ri = r.iloc[i]
        wi = w.iloc[i]
        excess = wi - 1.0
        r_port = wi * ri - excess * (rate_brw if excess > 0 else rate_cash)

        gB *= 1.0 + ri
        gV *= 1.0 + r_port

        if new_month.iloc[i] and wd > 0:                  # 扣款在報酬之後
            hB += wd / gB
            hV += wd / gV

        if turn.iloc[i] > 0:
            gV *= 1.0 - turn.iloc[i] * a.cost_bps / 10000.0

        GB.append(gB); GV.append(gV); HB.append(hB); HV.append(hV); YR.append(t.year)

    out = pd.DataFrame({"gB": GB, "gV": GV, "hB": HB, "hV": HV}, index=idx)
    return out, pd.DataFrame(snap, columns=["year", "gB", "hB", "gV", "hV"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--start", default="1993-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--principal", type=float, default=15_000_000)
    p.add_argument("--monthly", type=float, default=50_000)
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
    a = p.parse_args()

    df = load(a.symbol, a.start, a.end)
    r = build_returns(df, a.div_tax)
    w, turn, vol = weights(r, a.target_vol, a.vol_len, a.max_w, a.min_w, a.band, a.bars_per_year)
    path, snap = simulate(r, w, turn, a)

    n = len(r)
    yrs = n / a.bars_per_year
    gBe, gVe = path["gB"].iloc[-1], path["gV"].iloc[-1]
    hBe, hVe = path["hB"].iloc[-1], path["hV"].iloc[-1]

    # 金絲雀：年化報酬落在 5–12% 才合理。三位數 = 資料層壞了。
    cagrB = gBe ** (a.bars_per_year / n) - 1
    cagrV = gVe ** (a.bars_per_year / n) - 1
    flag = "" if -0.20 < cagrB < 0.30 else "   ⚠ 異常，別信下面任何數字"

    balB = path["gB"] * (a.principal - path["hB"])
    balV = path["gV"] * (a.principal - path["hV"])

    W = 10_000.0
    print(f"\n{a.symbol}  {r.index[0].date()} → {r.index[-1].date()}  ({yrs:.1f} 年)")
    print(f"本金 {a.principal/W:,.0f}萬   每月提領 {a.monthly/W:,.1f}萬"
          f"   通膨 {a.infl}%   股息稅 {a.div_tax:.0%}")
    print("=" * 74)
    print(f"{'':22}{'調兵':>16}{'買入持有':>16}")
    print(f"{'年化報酬（檢查）':22}{cagrV:>15.2%}{cagrB:>16.2%}{flag}")
    print(f"{'期末餘額':22}{max(0,balV.iloc[-1])/W:>15,.0f}萬{max(0,balB.iloc[-1])/W:>15,.0f}萬")
    print(f"{'最低餘額':22}{max(0,balV.min())/W:>15,.0f}萬{max(0,balB.min())/W:>15,.0f}萬")
    print(f"{'撐完全程所需本金':22}{hVe/W:>15,.0f}萬{hBe/W:>15,.0f}萬")
    print(f"{'可持續月提領':22}{a.principal*a.monthly/hVe/W:>15,.2f}萬"
          f"{a.principal*a.monthly/hBe/W:>15,.2f}萬")
    ddV = (1 - balV / balV.cummax()).max()
    ddB = (1 - balB / balB.cummax()).max()
    print(f"{'餘額最大回撤':22}{ddV:>15.1%}{ddB:>16.1%}")
    print(f"{'平均曝險':22}{w.mean():>15.2f}x{1.0:>15.2f}x")

    print("\n逐年起始（年期 " + (f"{a.horizon} 年" if a.horizon else "到資料結束") + "）")
    print("-" * 74)
    print(f"{'起始年':>6}{'年期':>6}{'調·所需本金':>14}{'持·所需本金':>14}"
          f"{'調·期末':>14}{'持·期末':>14}  結果")
    okV = okB = tot = 0
    for _, row in snap.iterrows():
        if a.horizon:
            tgt = snap[snap.year == row.year + a.horizon]
            if tgt.empty:
                continue
            e = tgt.iloc[0]
            span = a.horizon
        else:
            e = pd.Series({"gB": gBe, "hB": hBe, "gV": gVe, "hV": hVe})
            span = snap.year.iloc[-1] - row.year
        nB = row.gB * (e.hB - row.hB)
        nV = row.gV * (e.hV - row.hV)
        eB = e.gB * (a.principal / row.gB - (e.hB - row.hB))
        eV = e.gV * (a.principal / row.gV - (e.hV - row.hV))
        tot += 1
        okB += eB > 0
        okV += eV > 0
        print(f"{int(row.year):>6}{span:>5}年{nV/W:>13,.0f}萬{nB/W:>13,.0f}萬"
              f"{max(0,eV)/W:>13,.0f}萬{max(0,eB)/W:>13,.0f}萬"
              f"  {'調✔' if eV>0 else '調✘'} {'持✔' if eB>0 else '持✘'}")
    if tot:
        print("-" * 74)
        print(f"存活率（{tot} 組）   調兵 {okV/tot:.0%}   買入持有 {okB/tot:.0%}")


if __name__ == "__main__":
    main()
