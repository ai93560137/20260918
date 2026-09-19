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

# ── 八陣圖的各週期預設（原樣抄自 .pine 第 165–172 行）──────────────────────
PRESETS = {
 'D':  dict(lenTrend=40, r2Min=0.45, slopeMin=0.030, lenRange=12, rangeMaxATR=3.2,
            rangeMinBars=6, boxMaxAge=20, bufATR=0.35, confirmBars=2),
 'H4': dict(lenTrend=45, r2Min=0.52, slopeMin=0.028, lenRange=14, rangeMaxATR=2.8,
            rangeMinBars=7, boxMaxAge=20, bufATR=0.28, confirmBars=1),
 'H1': dict(lenTrend=50, r2Min=0.55, slopeMin=0.025, lenRange=16, rangeMaxATR=3.0,
            rangeMinBars=8, boxMaxAge=25, bufATR=0.25, confirmBars=1),
 'M15':dict(lenTrend=60, r2Min=0.48, slopeMin=0.025, lenRange=20, rangeMaxATR=3.8,
            rangeMinBars=8, boxMaxAge=30, bufATR=0.25, confirmBars=1),
 'M5': dict(lenTrend=60, r2Min=0.58, slopeMin=0.030, lenRange=20, rangeMaxATR=3.8,
            rangeMinBars=8, boxMaxAge=40, bufATR=0.30, confirmBars=1),
}
for _k in PRESETS:
    PRESETS[_k].update(atrLen=14, failBars=10)
PRESET_D = PRESETS['D']
RESAMPLE = {'M5': '5min', 'M15': '15min', 'H1': '1h', 'H4': '4h', 'D': '1D'}


# ── Pine 內建函數的等價實作 ────────────────────────────────────────────────
def rma(s, n):                      # Wilder 平滑，ta.atr 用的就是這個
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def atr(df, n):
    pc = df.Close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()],
                   axis=1).max(axis=1)
    return rma(tr, n)


def linreg_slope_r2(close, n):
    """ta.linreg(close,n,0) - ta.linreg(close,n,1) 等於 OLS 斜率；r2 = corr(close,bar_index)^2
    向量化版本 —— M1 資料動輒 25 萬根，純 Python 迴圈跑不動。"""
    from numpy.lib.stride_tricks import sliding_window_view
    x = np.arange(n, dtype=float)
    xm = x.mean()
    sxx = ((x - xm) ** 2).sum()
    w = x - xm
    v = close.values.astype(float)
    slope = np.full(len(v), np.nan)
    r2 = np.full(len(v), np.nan)
    if len(v) >= n:
        W = sliding_window_view(v, n)
        sxy = (W * w).sum(1)
        syy = ((W - W.mean(1)[:, None]) ** 2).sum(1)
        slope[n - 1:] = sxy / sxx
        with np.errstate(divide='ignore', invalid='ignore'):
            r2[n - 1:] = np.where(syy > 0, (sxy * sxy) / (sxx * syy), 0.0)
    return pd.Series(slope, index=close.index), pd.Series(r2, index=close.index)


def resample(df, tf):
    """M1 原始資料 → 目標週期。週末的空 bar 會被丟掉。"""
    if tf == 'M1':
        return df
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    if 'Volume' in df.columns:
        agg['Volume'] = 'sum'
    return df.resample(RESAMPLE[tf]).agg(agg).dropna(subset=['Close'])


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


def trades(df, s, p, stopATR=None, tpATR=None, maxBars=10):
    """突破確認後進場，逐根用 High/Low 檢查停損停利（停損優先），到期用時間出場。
    stopATR=None 表示不設價格停損 —— 此時 maxBars 就是停損：最多抱這麼多根。"""
    st, hi, lo, a = s.st.values, s.hi.values, s.lo.values, s.atr.values
    C, H, L = df.Close.values, df.High.values, df.Low.values
    n = len(df)
    boxTop = boxBot = np.nan
    live, lastR, run, pdir, pc = False, -1, 0, 0, 0
    out = []
    for i in range(1, n):
        run = run + 1 if st[i] == 0 else 0
        if st[i] == 0 and run >= p['rangeMinBars']:
            boxTop, boxBot, live, lastR = hi[i - 1], lo[i - 1], True, i
        elif live and i - lastR > p['boxMaxAge']:
            live = False
        if not live or np.isnan(a[i]):
            pdir, pc = 0, 0
            continue
        raw = 1 if C[i] > boxTop + p['bufATR'] * a[i] else (-1 if C[i] < boxBot - p['bufATR'] * a[i] else 0)
        if raw != 0 and raw == pdir:
            pc += 1
        elif raw != 0:
            pdir, pc = raw, 1
        else:
            pdir, pc = 0, 0
        if pdir != 0 and pc == p['confirmBars']:
            px, av, dr, ex = C[i], a[i], pdir, None
            sp = px - dr * stopATR * av if stopATR else None
            tp = px + dr * tpATR * av if tpATR else None
            for j in range(i + 1, min(i + 1 + maxBars, n)):
                if sp is not None and ((dr > 0 and L[j] <= sp) or (dr < 0 and H[j] >= sp)):
                    ex = (sp, j, 'stop'); break
                if tp is not None and ((dr > 0 and H[j] >= tp) or (dr < 0 and L[j] <= tp)):
                    ex = (tp, j, 'tp'); break
            if ex is None:
                j = min(i + maxBars, n - 1)
                ex = (C[j], j, 'time')
            out.append(dict(t=df.index[i], dir=dr, ret=(ex[0] / px - 1) * dr * 100,
                            how=ex[2], bars=ex[1] - i))
            live, pdir, pc = False, 0, 0
    return pd.DataFrame(out)


def trade_report(name, df, p, stopATR, tpATR, maxBars, aum, exposure):
    s = states(df, p)
    tr = trades(df, s, p, stopATR, tpATR, maxBars)
    if len(tr) < 10:
        print(f"\n{name}: 交易數 {len(tr)}，不足以下結論。")
        return
    t = tr.ret.mean() / (tr.ret.std() / np.sqrt(len(tr)))
    print(f"\n{'='*66}\n{name} 進出場模擬  停損={stopATR or '無（改用時間出場）'} "
          f"停利={tpATR or '無'} 最長持有={maxBars} 根\n{'='*66}")
    print(f"  {len(tr)} 筆  平均 {tr.ret.mean():+.3f}%  勝率 {(tr.ret>0).mean()*100:.1f}%  t={t:+.2f}")
    print(f"  單筆最壞 {tr.ret.min():+.3f}%  最好 {tr.ret.max():+.3f}%  平均持有 {tr.bars.mean():.1f} 根")
    print(f"  出場方式：" + "  ".join(f"{k} {v}" for k, v in tr.how.value_counts().items()))
    eq = (1 + tr.ret / 100).cumprod()
    mdd = (eq / eq.cummax() - 1).min() * 100
    print(f"  訊號序列最大回撤（名義）{mdd:.2f}%  → 曝險 {exposure}x 時對 NAV 約 {mdd*exposure:.2f}%")
    tr = tr.assign(m=pd.to_datetime(tr.t).dt.to_period('M'))
    mo = tr.groupby('m').ret.agg(['count', 'sum'])
    print(f"\n  逐月（名義 %）：")
    for k, v in mo.iterrows():
        print(f"    {k}  {int(v['count']):>3} 筆  {v['sum']:+7.3f}%")
    print(f"  {(mo['sum']>0).sum()} 個月正 / {(mo['sum']<=0).sum()} 個月負   "
          f"月均 {mo['sum'].mean():+.3f}%  標準差 {mo['sum'].std():.3f}%")
    notional = aum * exposure
    mm = mo['sum'] / 100 * notional
    print(f"\n  AUM {aum:,.0f} × 曝險 {exposure}x = 名義 {notional:,.0f}")
    print(f"  月均 {mm.mean():+,.0f}   標準差 {mm.std():,.0f}   最壞月 {mm.min():+,.0f}")


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
        raw = pd.read_csv(a.csv)
        tcol = 'Date' if 'Date' in raw.columns else 'Time'
        raw[tcol] = pd.to_datetime(raw[tcol], format='mixed', dayfirst=False)
        df = raw.set_index(tcol).sort_index()
        df.index.name = 'Date'
    else:
        import yfinance as yf
        df = yf.download(a.symbol, period=f"{a.years}y", interval="1d",
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    keep = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    df = df[keep].dropna(subset=['Close']).astype(float)
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
    ap.add_argument("--tf", default="D", choices=list(RESAMPLE) + ["M1"],
                    help="把資料重取樣到這個週期，並自動套用八陣圖該週期的預設門檻")
    ap.add_argument("--trades", action="store_true", help="跑進出場模擬並換算成錢")
    ap.add_argument("--stop", type=float, default=None, help="停損 ATR 倍數；不給 = 只用時間出場")
    ap.add_argument("--tp", type=float, default=None, help="停利 ATR 倍數")
    ap.add_argument("--hold", type=int, default=10, help="最長持有根數（時間出場）")
    ap.add_argument("--aum", type=float, default=24_000_000.0)
    ap.add_argument("--exposure", type=float, default=0.3)
    a = ap.parse_args()

    df = resample(load(a), a.tf)
    PRESET = PRESETS.get(a.tf, PRESET_D)
    name = f"{a.csv or a.symbol}  [{a.tf}]"
    if a.split:
        h = len(df) // 2
        report(name + "（前半）", df.iloc[:h], PRESET, a.fwd)
        report(name + "（後半）", df.iloc[h:], PRESET, a.fwd)
        if a.trades:
            trade_report(name + "（前半）", df.iloc[:h], PRESET, a.stop, a.tp, a.hold, a.aum, a.exposure)
            trade_report(name + "（後半）", df.iloc[h:], PRESET, a.stop, a.tp, a.hold, a.aum, a.exposure)
    else:
        report(name, df, PRESET, a.fwd)
        if a.trades:
            trade_report(name, df, PRESET, a.stop, a.tp, a.hold, a.aum, a.exposure)
    if a.sweep:
        sweep(name, df, PRESET)
