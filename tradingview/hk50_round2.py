#!/usr/bin/env python3
"""HK50 第二輪研究（2026-09-20）— 交接文件 §5 三個建議方向的實測。

結果全部寫在 HSI_HANDOFF.md §8。三個方向的結論：
  1. 調兵（波動率目標）D1     → 動態部分負貢獻（輸給固定曝險對照組）
  2. 八陣圖軌道 H4/D1 順勢    → 無優勢；空下降軌道穩定虧損
  3. 盤中條件（前30分/跳空/量）→ 全部過不了成本
  附. 下降軌道做多（均值回歸）  → 每格為正，但利潤集中在頂端 5%，異常值檢查不過

用法：
    python3 hk50_round2.py voltarget    # 調兵 vs 固定曝險
    python3 hk50_round2.py trend       # 八陣圖狀態持倉回測（含切半）
    python3 hk50_round2.py intraday    # 盤中條件篩選
    python3 hk50_round2.py longdown    # 下降軌道做多 + 異常值檢查

資料放在 data/（不進版本庫）：HK50_D1_MAX.csv、HK50_H4_MAX.csv、HK50_M5_MAX.csv
"""
import sys
import numpy as np
import pandas as pd

from bazhentu_sim import PRESETS, states

DATA = 'data/'
COST_RT = 0.000475          # 點差 10 點來回 ≈ 0.0475%
COST_SIDE = COST_RT / 2


def load(fname):
    df = pd.read_csv(DATA + fname)
    df['Time'] = pd.to_datetime(df['Time'], format='%Y.%m.%d %H:%M:%S')
    return df.set_index('Time').sort_index()


def bars_per_year(idx):
    return len(idx) / ((idx[-1] - idx[0]).days / 365.25)


def t_of(x):
    return x.mean() / (x.std() / np.sqrt(len(x))) if len(x) > 5 and x.std() > 0 else np.nan


# ── 1. 調兵：波動率目標 vs 固定曝險對照組 ────────────────────────────────
def voltarget():
    df = load('HK50_D1_MAX.csv')
    r = df.Close.pct_change()
    start = df.index[61]                      # 共同暖機起點，lb20/lb60 才可比
    print(f"D1 調兵  共同評估窗口 {start.date()} → {df.index[-1].date()}")
    print(f"{'':26}{'年化':>8}{'波動':>8}{'夏普':>7}{'回撤':>8}{'年化/回撤':>9}")

    def metrics(ret, label):
        ann = (1 + ret).prod() ** (252 / len(ret)) - 1
        vol = ret.std() * np.sqrt(252)
        eq = (1 + ret).cumprod()
        mdd = (eq / eq.cummax() - 1).min()
        print(f"{label:<26}{ann*100:>+7.2f}%{vol*100:>7.2f}%{ann/vol:>7.2f}"
              f"{mdd*100:>+7.2f}%{ann/abs(mdd):>9.2f}")

    for tgt, lb in [(0.15, 20), (0.15, 60), (0.18, 60)]:
        rv = r.rolling(lb).std() * np.sqrt(252)
        w = (tgt / rv).clip(upper=1.0).shift(1)
        w_, r_ = w[df.index >= start], r[df.index >= start]
        cost = w_.diff().abs().fillna(w_.iloc[0]) * COST_SIDE
        strat = w_ * r_ - cost
        fixed = w_.mean() * r_
        d = strat - fixed
        metrics(fixed, f'固定曝險 {w_.mean():.2f}x')
        metrics(strat, f'調兵 目標{int(tgt*100)}%/回看{lb}')
        print(f"    動態−靜態 {d.mean()*1e4:+.2f} bp/日  t={t_of(d):+.2f}\n")
    metrics(r[df.index >= start], '買入持有')


# ── 2. 八陣圖狀態持倉回測 ────────────────────────────────────────────────
def state_backtest(df, tf, mode):
    st = states(df, PRESETS[tf]).st
    pos = pd.Series(0.0, index=df.index)
    if mode == 'follow':
        pos[st == 1], pos[st == -1] = 1, -1
    elif mode == 'long':
        pos[st == 1] = 1
    elif mode == 'short':
        pos[st == -1] = -1
    elif mode == 'longdown':
        pos[st == -1] = 1
    pos = pos.shift(1).fillna(0)              # 本根收盤判定，下一根生效
    r = df.Close.pct_change().fillna(0)
    strat = pos * r - pos.diff().abs().fillna(0) * COST_SIDE
    return strat, pos, r


def trend():
    for name, fname, tf in [('H4', 'HK50_H4_MAX.csv', 'H4'), ('D1', 'HK50_D1_MAX.csv', 'D')]:
        df = load(fname)
        for half, part in [('全期', df), ('前半', df.iloc[:len(df)//2]), ('後半', df.iloc[len(df)//2:])]:
            print(f"\n── {name} {half} ──")
            print(f"{'模式':<8}{'年化':>9}{'bp/根':>8}{'t(根)':>8}{'t(月)':>8}{'在場%':>7}")
            for mode in ['follow', 'long', 'short']:
                strat, pos, r = state_backtest(part, tf, mode)
                ann = (1 + strat).prod() ** (bars_per_year(part.index) / len(strat)) - 1
                mo = strat.groupby(strat.index.to_period('M')).sum()
                print(f"{mode:<8}{ann*100:>+8.2f}%{strat.mean()*1e4:>+8.2f}"
                      f"{t_of(strat):>+8.2f}{t_of(mo):>+8.2f}{(pos != 0).mean()*100:>6.1f}%")


# ── 3. 盤中條件篩選 ──────────────────────────────────────────────────────
def intraday():
    m5 = load('HK50_M5_MAX.csv')
    rows = []
    for d, day in m5.groupby(m5.index.date):
        if len(day) < 30:
            continue
        rows.append(dict(date=pd.Timestamp(d), open=day.Open.iloc[0], c30=day.Close.iloc[5],
                         close=day.Close.iloc[-1], vol30=day.Volume.iloc[:6].sum()))
    df = pd.DataFrame(rows).set_index('date')
    df['gap'] = df.open / df.close.shift(1) - 1
    df['r30'] = df.c30 / df.open - 1
    df['r_rest'] = df.close / df.c30 - 1
    df['r_intra'] = df.close / df.open - 1
    df['vol30_z'] = (df.vol30 - df.vol30.rolling(60).mean()) / df.vol30.rolling(60).std()
    df = df.dropna(subset=['gap'])
    print(f"{len(df)} 個交易日\n")
    print("開盤前 30 分鐘 → 其餘盤中：corr = %+.4f（成本 0.0475%% 需要 corr 約 0.05 以上才打平）"
          % np.corrcoef(df.r30, df.r_rest)[0, 1])
    print("\n連續跳空門檻 → 順向做盤中（開進收出，淨值）")
    for th in [0.002, 0.003, 0.004, 0.006, 0.008]:
        m = df.gap.abs() > th
        v = df.r_intra[m] * np.sign(df.gap[m]) - COST_RT
        print(f"  |gap|>{th*100:.1f}%  n={m.sum():>4}  淨 {v.mean()*100:+.4f}%  t={t_of(v):+.2f}")
    print("\n開盤 30 分量能異常（z>1）→ 做多盤中（淨值）")
    m = (df.vol30_z > 1)
    v = df.r_intra[m] - COST_RT
    print(f"  n={m.sum()}  淨 {v.mean()*100:+.4f}%  t={t_of(v):+.2f}")


# ── 附. 下降軌道做多 + 異常值檢查 ────────────────────────────────────────
def longdown():
    for name, fname, tf in [('H4', 'HK50_H4_MAX.csv', 'H4'), ('D1', 'HK50_D1_MAX.csv', 'D')]:
        df = load(fname)
        print(f"\n── 下降軌道做多 {name} ──")
        for half, part in [('全期', df), ('前半', df.iloc[:len(df)//2]), ('後半', df.iloc[len(df)//2:])]:
            strat, pos, r = state_backtest(part, tf, 'longdown')
            ann = (1 + strat).prod() ** (bars_per_year(part.index) / len(strat)) - 1
            mo = strat.groupby(strat.index.to_period('M')).sum()
            act = strat[pos != 0].sort_values()
            trimmed = act.iloc[:-max(1, int(len(act) * 0.05))]   # 拿掉最賺的 5% 持倉根
            print(f"  {half:<4} 年化 {ann*100:+6.2f}%  t(月){t_of(mo):+.2f}  "
                  f"去頂5%後 {trimmed.mean()*1e4:+.1f} bp/根")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'voltarget'
    dict(voltarget=voltarget, trend=trend, intraday=intraday, longdown=longdown)[cmd]()
