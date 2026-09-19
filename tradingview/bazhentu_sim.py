#!/usr/bin/env python3
"""
八陣圖校準器 — 把 zhugeliang_bazhentu_v1.pine 的狀態判定原樣搬到 Python，
在 XAUUSD / ES / NQ / HSI 上實測，回答三個問題：

  1. 何時橫行？      → 各狀態佔多少根，橫行區間的實際壽命
  2. 何時轉勢？      → 突破確認後的真假比例、順逆比（MFE/MAE）
  3. 有動能才入場值不值得？ → 分狀態的前瞻報酬期望值，對照「隨機進場」控制組

八陣圖的預設門檻是照美股指數調的。黃金是 24 小時、沒有有效成交量、
波動結構不同，直接沿用會失準。本檔的 --sweep 會掃出該商品自己的門檻。

用法（在你自己的機器上跑，需要 yfinance）：
    pip install yfinance pandas numpy
    python3 bazhentu_sim.py --symbol GC=F  --years 12
    python3 bazhentu_sim.py --symbol GC=F  --years 12 --sweep
    python3 bazhentu_sim.py --symbol ES=F --years 12
    python3 bazhentu_sim.py --symbol GC=F --csv mygold.csv     # 自備資料

自備 CSV 需要欄位：Date, Open, High, Low, Close（Volume 可有可無）。
XAUUSD 用富途／MT4 匯出的日線最準；GC=F 只是近似（期貨有轉倉缺口）。
"""
import argparse, sys
import numpy as np
import pandas as pd

# ── 八陣圖的日線預設（原樣抄自 .pine 第 165–172 行）────────────────────────
PRESET_D = dict(lenTrend=40, r2Min=0.45, slopeMin=0.030, lenRange=12,
                rangeMaxATR=3.2, rangeMinBars=6, boxMaxAge=20,
                bufATR=0.35, confirmBars=2, atrLen=14, failBars=10)


# ── Pine 內建函數的等價實作 ────────────────────────────────────────────────
def rma(s, n):                      # Wilder 平滑，ta.atr 用的就是這個
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def atr(df, n):
    pc = df.Close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()],
                   axis=1).max(axis=1)
    return rma(tr, n)


def linreg_slope_r2(close, n):
    """ta.linreg(close,n,0) - ta.linreg(close,n,1) 等於 OLS 斜率；r2 = corr(close,bar_index)^2"""
    x = np.arange(n, dtype=float)
    xm = x.mean()
    sxx = ((x - xm) ** 2).sum()
    v = close.values
    slope = np.full(len(v), np.nan)
    r2 = np.full(len(v), np.nan)
    for i in range(n - 1, len(v)):
        y = v[i - n + 1:i + 1]
        ym = y.mean()
        sxy = ((x - xm) * (y - ym)).sum()
        syy = ((y - ym) ** 2).sum()
        b = sxy / sxx
        slope[i] = b
        r2[i] = 0.0 if syy <= 0 else (sxy * sxy) / (sxx * syy)
    return pd.Series(slope, index=close.index), pd.Series(r2, index=close.index)


# ── 狀態機：1 上升軌道 / -1 下降軌道 / 0 橫行 / 2 過渡 ──────────────────────
def states(df, p):
    a = atr(df, p['atrLen'])
    slope, r2 = linreg_slope_r2(df.Close, p['lenTrend'])
    sN = slope / a.replace(0, np.nan)
    hi = df.High.rolling(p['lenRange']).max()
    lo = df.Low.rolling(p['lenRange']).min()
    wATR = (hi - lo) / a.replace(0, np.nan)

    up = (r2 >= p['r2Min']) & (sN >= p['slopeMin'])
    dn = (r2 >= p['r2Min']) & (sN <= -p['slopeMin'])
    rng = (~up) & (~dn) & (wATR <= p['rangeMaxATR'])
    st = np.where(up, 1, np.where(dn, -1, np.where(rng, 0, 2)))
    return pd.DataFrame(dict(st=st, sN=sN, r2=r2, wATR=wATR, hi=hi, lo=lo, atr=a),
                        index=df.index)


def breakouts(df, s, p):
    """橫行箱鎖存 → 突破 → 站穩確認 → 事後判真假，並量 MFE/MAE（ATR 單位）"""
    st = s.st.values; hi = s.hi.values; lo = s.lo.values; a = s.atr.values
    C, H, L = df.Close.values, df.High.values, df.Low.values
    n = len(df)

    boxTop = boxBot = np.nan
    boxLive = False
    lastRangeBar = -1
    runRange = 0
    pendDir, pendCnt = 0, 0
    out = []
    boxLives = []

    for i in range(1, n):
        runRange = runRange + 1 if st[i] == 0 else 0
        if st[i] == 0 and runRange >= p['rangeMinBars']:
            if not boxLive:
                boxLives.append(i)
            boxTop, boxBot = hi[i - 1], lo[i - 1]   # 用前一根，突破當根不自己撐大箱子
            boxLive, lastRangeBar = True, i
        elif boxLive and i - lastRangeBar > p['boxMaxAge']:
            boxLive = False

        if not boxLive or np.isnan(a[i]):
            pendDir, pendCnt = 0, 0
            continue

        upL = boxTop + p['bufATR'] * a[i]
        dnL = boxBot - p['bufATR'] * a[i]
        raw = 1 if C[i] > upL else (-1 if C[i] < dnL else 0)

        if raw != 0 and raw == pendDir:
            pendCnt += 1
        elif raw != 0:
            pendDir, pendCnt = raw, 1
        else:
            pendDir, pendCnt = 0, 0

        if pendDir != 0 and pendCnt == p['confirmBars']:
            j = min(i + p['failBars'], n - 1)
            seg = slice(i + 1, j + 1)
            if i + 1 > j:
                pendDir, pendCnt = 0, 0
                continue
            px, av, d = C[i], a[i], pendDir
            mfe = (H[seg].max() - px) / av if d > 0 else (px - L[seg].min()) / av
            mae = (px - L[seg].min()) / av if d > 0 else (H[seg].max() - px) / av
            back = ((C[seg] < boxTop).any() if d > 0 else (C[seg] > boxBot).any())
            out.append(dict(i=i, dir=d, px=px, mfe=mfe, mae=mae, fake=bool(back),
                            fwd=(C[j] / px - 1) * d * 100))
            boxLive = False
            pendDir, pendCnt = 0, 0

    return pd.DataFrame(out), boxLives


def report(name, df, p, fwd_h=10, seed=0):
    s = states(df, p)
    bk, boxLives = breakouts(df, s, p)
    n = len(df)
    print(f"\n{'='*66}\n{name}   {df.index[0].date()} → {df.index[-1].date()}   {n} 根日線\n{'='*66}")

    # 1. 何時橫行
    vc = pd.Series(s.st).value_counts(normalize=True) * 100
    lab = {1: "上升軌道", -1: "下降軌道", 0: "橫行", 2: "過渡"}
    print("【狀態分佈】")
    for k in [1, -1, 0, 2]:
        print(f"  {lab[k]:<6} {vc.get(k, 0):>5.1f}%")
    # 軌道壽命
    runs, cur, prev = [], 0, None
    for v in s.st:
        if v == prev:
            cur += 1
        else:
            if prev in (1, -1) and cur:
                runs.append(cur)
            cur, prev = 1, v
    if runs:
        print(f"  軌道平均壽命 {np.mean(runs):.1f} 根   中位數 {np.median(runs):.0f}   最長 {max(runs)}")

    # 2. 何時轉勢
    if len(bk) == 0:
        print("\n【突破】樣本為 0 —— 這組門檻在此商品上發不出訊號。")
        return s, bk
    fake = bk.fake.mean() * 100
    ratio = bk.mfe.mean() / bk.mae.mean() if bk.mae.mean() > 0 else np.nan
    print(f"\n【突破確認後 {p['failBars']} 根】{len(bk)} 次（多 {(bk.dir>0).sum()} / 空 {(bk.dir<0).sum()}）")
    print(f"  順向 MFE {bk.mfe.mean():.2f} ATR   逆向 MAE {bk.mae.mean():.2f} ATR   順逆比 {ratio:.2f}")
    print(f"  假突破率 {fake:.1f}%   平均前瞻報酬 {bk.fwd.mean():+.2f}%   勝率 {(bk.fwd>0).mean()*100:.1f}%")

    # 3. 有動能才入場值不值得 —— 分狀態前瞻報酬 + 隨機控制組
    ret = (df.Close.shift(-fwd_h) / df.Close - 1) * 100
    print(f"\n【分狀態的前瞻 {fwd_h} 根報酬（方向 = 狀態方向）】")
    for k in [1, -1, 0, 2]:
        m = (s.st == k) & ret.notna()
        if m.sum() < 20:
            continue
        d = 1 if k == 1 else (-1 if k == -1 else 1)
        v = ret[m] * d
        print(f"  {lab[k]:<6} n={m.sum():>5}  平均 {v.mean():+.3f}%  勝率 {(v>0).mean()*100:>5.1f}%  標準差 {v.std():.2f}%")

    rng = np.random.default_rng(seed)
    idx = rng.choice(np.where(ret.notna())[0], size=min(len(bk) * 200, ret.notna().sum()), replace=True)
    sgn = rng.choice([1, -1], size=len(idx))
    rnd = ret.values[idx] * sgn
    print(f"  {'隨機控制組':<6} n={len(idx):>5}  平均 {rnd.mean():+.3f}%  勝率 {(rnd>0).mean()*100:>5.1f}%  標準差 {rnd.std():.2f}%")
    t = bk.fwd.mean() / (bk.fwd.std() / np.sqrt(len(bk))) if bk.fwd.std() > 0 else np.nan
    print(f"\n  突破訊號 vs 0 的 t 值 = {t:.2f}   {'→ 有統計意義' if abs(t) > 2 else '→ 跟雜訊分不開'}")
    return s, bk


def sweep(name, df, base):
    print(f"\n{'='*66}\n{name} 門檻掃描 — 找這個商品自己的預設\n{'='*66}")
    print(f"{'r2':>5}{'slope':>7}{'rangeATR':>10}{'突破數':>8}{'假突破':>8}{'順逆比':>8}{'前瞻%':>8}{'t':>7}")
    best = None
    for r2m in [0.35, 0.45, 0.55, 0.65]:
        for sl in [0.020, 0.030, 0.040, 0.050]:
            for rm in [2.6, 3.2, 3.8]:
                p = dict(base, r2Min=r2m, slopeMin=sl, rangeMaxATR=rm)
                s = states(df, p)
                bk, _ = breakouts(df, s, p)
                if len(bk) < 25:
                    continue
                t = bk.fwd.mean() / (bk.fwd.std() / np.sqrt(len(bk)))
                ratio = bk.mfe.mean() / bk.mae.mean()
                print(f"{r2m:>5.2f}{sl:>7.3f}{rm:>10.1f}{len(bk):>8}{bk.fake.mean()*100:>7.1f}%"
                      f"{ratio:>8.2f}{bk.fwd.mean():>+8.2f}{t:>7.2f}")
                if best is None or t > best[0]:
                    best = (t, r2m, sl, rm, len(bk))
    if best:
        print(f"\n  最高 t：r2={best[1]} slope={best[2]} rangeATR={best[3]}  (t={best[0]:.2f}, n={best[4]})")
        print("  ⚠ 這是在同一份資料上挑出來的最佳值，本身就是過度配適。")
        print("    要信它，先把資料切一半：前半段挑門檻，後半段驗證。差太多就是假的。")


def load(a):
    if a.csv:
        df = pd.read_csv(a.csv, parse_dates=['Date']).set_index('Date').sort_index()
    else:
        import yfinance as yf
        df = yf.download(a.symbol, period=f"{a.years}y", interval="1d",
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    df = df[['Open', 'High', 'Low', 'Close']].dropna().astype(float)
    if len(df) < 200:
        sys.exit("資料太少，拿不到結論。")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GC=F", help="GC=F 黃金 / ES=F / NQ=F / ^HSI")
    ap.add_argument("--csv", default=None, help="自備日線 CSV（Date,Open,High,Low,Close）")
    ap.add_argument("--years", type=int, default=12)
    ap.add_argument("--fwd", type=int, default=10, help="前瞻報酬的根數")
    ap.add_argument("--split", action="store_true", help="前後各半分開跑，看門檻撐不撐得住")
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()

    df = load(a)
    name = a.csv or a.symbol
    if a.split:
        h = len(df) // 2
        report(name + "（前半）", df.iloc[:h], PRESET_D, a.fwd)
        report(name + "（後半）", df.iloc[h:], PRESET_D, a.fwd)
    else:
        report(name, df, PRESET_D, a.fwd)
    if a.sweep:
        sweep(name, df, PRESET_D)
