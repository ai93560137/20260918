#!/usr/bin/env python3
"""
智能諸葛亮 · 借東風 — 波克夏拆解與複製測試

諸葛亮造不出風，他借風。
我們造不出保險浮存金，所以問一個可以驗證的問題：

    **波克夏的超額報酬，能不能用「公開買得到的因子 + 槓桿」解釋掉？**

這正是 AQR《Buffett's Alpha》（Frazzini, Kabiller, Pedersen 2018）的方法，
而且完全可以重現：

  1. 用 ETF 組出「品質 + 低波動 + 價值」的因子組合
  2. 加上槓桿（AQR 估計波克夏約 1.6x）
  3. 把 BRK 的報酬對這些因子做回歸
  4. 看截距（alpha）還剩多少、t 值有沒有過 2

  alpha 消失 → 可複製，他的優勢是因子暴險 + 便宜槓桿
  alpha 還在 → 不可複製，有因子解釋不了的東西

    pip install yfinance pandas numpy
    python3 jiedongfeng_sim.py

⚠️ 三個誠實的限制，看結果前先讀：
  1. **因子 ETF 是事後挑的**。QUAL/USMV/VTV 是今天回頭看選出來的代表，
     1965 年的人沒有這些工具，也不知道該挑哪些。
  2. **歷史很短**。QUAL 2013 才成立，交集只有十餘年——
     而波克夏的故事有 60 年。十年的 alpha 不顯著，不代表六十年的也不顯著。
  3. **複製組合贏過 BRK 不是好消息**，是過度配適的警訊。
"""
import argparse
import numpy as np
import pandas as pd

TD = 252


def load_rets(symbols, start, end, div_tax):
    """各標的的稅後總報酬（用 Adj Close 與 Close 的差額反推股息）。"""
    import yfinance as yf
    out = {}
    for s in symbols:
        df = yf.download(s, start=start, end=end, auto_adjust=False, progress=False)
        if df.empty:
            raise SystemExit(f"抓不到 {s}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Close", "Adj Close"]].dropna()
        rt, rp = df["Adj Close"].pct_change(), df["Close"].pct_change()
        out[s] = (rp + (rt - rp).clip(lower=0.0) * (1.0 - div_tax)).dropna()
    return pd.DataFrame(out).dropna()


def blend(rets, code="Y"):
    """等權、定期再平衡；期間內讓權重自然漂移。"""
    idx, k = rets.index, rets.shape[1]
    cur = np.full(k, 1.0 / k)
    out = np.zeros(len(idx))
    for i in range(len(idx)):
        if i == 0 or idx[i].to_period(code) != idx[i - 1].to_period(code):
            cur = np.full(k, 1.0 / k)
        row = rets.iloc[i].values
        rp = float((cur * row).sum())
        out[i] = rp
        if 1.0 + rp > 0:
            cur = cur * (1.0 + row) / (1.0 + rp)
    return pd.Series(out, index=idx)


def lever(r, L, cost):
    """槓桿 L、借款年息 cost%。連續再平衡——這對槓桿是寬容的假設。"""
    c = cost / 100.0 / TD
    return L * r - (L - 1.0) * c


def stats(r, rf):
    g = float(np.prod(1.0 + r.values))
    n = len(r)
    cagr = g ** (TD / n) - 1
    vol = r.std() * np.sqrt(TD)
    sharpe = (r.mean() - rf / TD) / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan
    eq = (1.0 + r).cumprod()
    dd = (1 - eq / eq.cummax()).max()
    return cagr, vol, sharpe, dd


def ols(y, X):
    """回傳係數與 t 值。第一欄是截距（alpha）。"""
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    e = y - X1 @ b
    dof = max(1, len(y) - X1.shape[1])
    cov = (e @ e / dof) * np.linalg.inv(X1.T @ X1)
    return b, b / np.sqrt(np.diag(cov))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="BRK-B", help="要拆解的標的")
    p.add_argument("--market", default="SPY")
    p.add_argument("--sleeves", default="QUAL,USMV,VTV",
                   help="因子沙包：品質、低波動、價值。逗號分隔。")
    p.add_argument("--lev", type=float, default=1.6, help="複製組合的槓桿（AQR 估計波克夏約 1.6）")
    p.add_argument("--borrow", type=float, default=1.0, help="借款年息 %%")
    p.add_argument("--rf", type=float, default=2.0, help="無風險利率 %%（算夏普用）")
    p.add_argument("--start", default="1990-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--div-tax", type=float, default=0.0,
                   help="股息預扣稅。比較策略時設 0（兩邊同樣待遇）")
    p.add_argument("--horizon", type=int, default=5, help="逐年起始表的年期")
    a = p.parse_args()

    sleeves = [x.strip() for x in a.sleeves.split(",") if x.strip()]
    syms = [a.target, a.market] + sleeves
    R = load_rets(syms, a.start, a.end, a.div_tax)
    idx, n = R.index, len(R)
    rf = a.rf / 100.0

    fac = blend(R[sleeves])                      # 無槓桿因子組合
    rep = lever(fac, a.lev, a.borrow)            # 加槓桿後的複製組合
    series = {
        a.target:                 R[a.target],
        a.market:                 R[a.market],
        "因子組合 1.0x":           fac,
        f"複製組合 {a.lev:g}x":    rep,
    }

    print(f"\n借東風：{a.target} 拆解測試")
    print(f"因子沙包 {' + '.join(sleeves)}（等權、年度再平衡）"
          f"   槓桿 {a.lev:g}x @ {a.borrow:g}%   無風險 {a.rf:g}%")
    print(f"資料交集 {idx[0].date()} → {idx[-1].date()}  ({n/TD:.1f} 年)")
    if n / TD < 20:
        print(f"⚠️  只有 {n/TD:.1f} 年。波克夏的故事有 60 年——這個樣本回答不了長期問題。")
    print("=" * 78)

    print(f"\n{'':18}{'年化報酬':>10}{'年化波動':>10}{'夏普':>8}{'最大回撤':>10}")
    for k, v in series.items():
        c, vol, sh, dd = stats(v, rf)
        flag = "" if -0.20 < c < 0.40 else "  ⚠"
        print(f"{k:18}{c:>10.2%}{vol:>10.1%}{sh:>8.2f}{dd:>10.1%}{flag}")

    # ── 回歸：alpha 還剩多少 ──
    print(f"\n【回歸：{a.target} 的超額報酬能被解釋掉嗎】")
    y = (R[a.target] - rf / TD).values
    for name, cols in [("只用市場", [a.market]), ("市場 + 因子", [a.market] + sleeves)]:
        X = (R[cols] - rf / TD).values
        b, t = ols(y, X)
        alpha = b[0] * TD
        print(f"\n  {name}")
        print(f"     alpha = {alpha:>7.2%}/年   t = {t[0]:>5.2f}"
              f"   {'✅ 顯著（因子解釋不了）' if abs(t[0]) > 2 else '❌ 不顯著（可以被解釋掉）'}")
        print("     " + "   ".join(f"{c}:{b[i+1]:.2f}(t={t[i+1]:.1f})" for i, c in enumerate(cols)))

    # ── 槓桿成本敏感度 ──
    print(f"\n【槓桿成本的影響】（{a.lev:g}x）")
    print(f"{'借款年息':>10}{'年化報酬':>12}{'夏普':>9}{'最大回撤':>11}")
    for c in (-2.0, 0.0, 1.0, 3.0, 4.8):
        cg, _, sh, dd = stats(lever(fac, a.lev, c), rf)
        tag = "  ← 浮存金（承保獲利）" if c < 0 else ("  ← 一般孖展" if c > 4 else "")
        print(f"{c:>9.1f}%{cg:>12.2%}{sh:>9.2f}{dd:>11.1%}{tag}")

    # ── 逐年起始 ──
    starts = [i for i in range(n) if i == 0 or idx[i].year != idx[i - 1].year]
    print(f"\n【逐年起始，每組 {a.horizon} 年的年化報酬】")
    print(f"{'起始年':>6}" + "".join(f"{k:>16}" for k in series))
    win = 0
    tot = 0
    for i0 in starts:
        y0 = idx[i0].year
        e = [i for i in starts if idx[i].year == y0 + a.horizon]
        if not e:
            continue
        i1 = e[0]
        row = {k: stats(v.iloc[i0:i1], rf)[0] for k, v in series.items()}
        tot += 1
        if row[f"複製組合 {a.lev:g}x"] > row[a.target]:
            win += 1
        print(f"{y0:>6}" + "".join(f"{row[k]:>15.1%} " for k in series))
    if tot:
        print(f"\n複製組合贏過 {a.target} 的比例：{win}/{tot} = {win/tot:.0%}")
        print("（贏太多不是好消息——那代表因子沙包是事後挑的）")


if __name__ == "__main__":
    main()
