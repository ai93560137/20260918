#!/usr/bin/env python3
"""三級共振（main.py GoldIndicatorSession.compute_verdict + next_trend_state）的離線量測。

把 GCP 電閘的判定邏輯原樣搬到 Python，在 XAUUSD M1 全歷史上跑一次，
看「開閘 → 關閘」這段持倉值多少錢。扣成本、分半樣本、對照隨機進場。

用法: python3 sanjigongzhen_sim.py
"""
import math
import numpy as np
import pandas as pd

NOISE_K      = 1.0        # main.py:157
WIN_BIG      = 60         # M15 視窗（分鐘）
WIN_MID      = 24         # M5  視窗
WIN_SML      = 4          # M1  視窗
SPREAD_USD   = 0.40       # 券商實際點差，來回成本（每盎司）
USD_HKD      = 7.8
OZ           = 1.0


def load(path='/tmp/cache/m1.pkl'):
    df = pd.read_pickle(path)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    return df


def verdict_series(df, noise_k=NOISE_K):
    """向量化 compute_verdict。回傳 regime 碼與方向。

    regime: 0=RANGE/NODATA, 1=SETUP, 2=TREND, 3=PAUSE
    dir   : +1 / -1 / 0
    """
    c = df['Close'].to_numpy(np.float64)
    t = df.index.to_numpy('datetime64[s]').astype(np.int64)
    n = len(c)

    d = np.empty(n); d[0] = np.nan; d[1:] = np.diff(c)
    contig1 = np.empty(n, bool); contig1[0] = False
    contig1[1:] = (t[1:] - t[:-1]) == 60

    # 最近 60 根的 σ（只算相鄰 1 分鐘的差，與 main.py 的 diffs 條件一致）
    dv = np.where(contig1, d, 0.0)
    cnt = contig1.astype(np.float64)
    def roll(a, w):
        cs = np.concatenate(([0.0], np.cumsum(a)))
        out = np.full(len(a), np.nan)
        out[w-1:] = cs[w:] - cs[:-w]
        return out
    s1 = roll(dv, WIN_BIG); s2 = roll(dv*dv, WIN_BIG); k = roll(cnt, WIN_BIG)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = s1 / k
        var  = (s2 - k*mean*mean) / (k - 1.0)
    sigma = np.sqrt(np.maximum(var, 0.0))
    ok = (k >= 30) & (sigma > 0)

    signs = {}
    for name, w in (('big', WIN_BIG), ('mid', WIN_MID), ('sml', WIN_SML)):
        move = np.full(n, np.nan); move[w:] = c[w:] - c[:-w]
        span = np.full(n, np.nan); span[w:] = (t[w:] - t[:-w]) / 60.0
        # 視窗必須是連續的 w 分鐘，否則 main.py 會回 NODATA
        good = span == w
        thr = noise_k * sigma * np.sqrt(np.where(good, span, np.nan))
        s = np.zeros(n, np.int8)
        s = np.where(move > thr, 1, np.where(move < -thr, -1, 0)).astype(np.int8)
        s[~(good & ok)] = 0
        signs[name] = s
        ok = ok & good

    big, mid, sml = signs['big'], signs['mid'], signs['sml']
    reso = (big != 0) & (mid == big) & ok
    regime = np.zeros(n, np.int8)
    regime[reso & (sml == big)]  = 2   # TREND
    regime[reso & (sml == -big)] = 1   # SETUP
    regime[reso & (sml == 0)]    = 3   # PAUSE
    direction = np.where(reso, big, 0).astype(np.int8)
    direction[~ok] = 0
    regime[~ok] = 0
    return regime, direction


def run_gate(regime, direction, skip_setup=False):
    """逐根跑 next_trend_state + gate_status，回傳每根的 (armed_dir)。0 = 鎖閘。"""
    n = len(regime)
    out = np.zeros(n, np.int8)
    st_reg, st_dir, st_armed = 0, 0, False
    for i in range(n):
        vr, vd = regime[i], direction[i]
        if vr == 0:
            st_reg, st_dir, st_armed = 0, 0, False
        elif vr == 3:                                   # PAUSE
            if st_reg == 2 and st_dir == vd:
                pass
            elif st_reg == 1 and st_dir == vd:
                st_armed = False
            else:
                st_reg, st_dir, st_armed = 0, 0, False
        elif vr == 1:                                   # SETUP
            if st_reg == 2 and st_dir == vd and st_armed:
                st_reg, st_dir, st_armed = 2, st_dir, True
            else:
                st_reg, st_dir, st_armed = 1, vd, False
        else:                                           # TREND
            if st_reg == 1 and st_dir == vd:
                st_reg, st_dir, st_armed = 2, vd, True
            elif st_reg == 2 and st_dir == vd:
                if skip_setup and not st_armed:
                    st_armed = True
            elif skip_setup:
                st_reg, st_dir, st_armed = 2, vd, True
            else:
                st_reg, st_dir, st_armed = 2, vd, False
        out[i] = st_dir if (st_armed and st_reg == 2 and st_dir != 0) else 0
    return out


def trades_from_gate(df, gate):
    """開閘 → 下一根開盤進場；關閘或轉向 → 下一根開盤出場。"""
    o = df['Open'].to_numpy(np.float64)
    idx = df.index
    rows, pos, entry_i = [], 0, -1
    n = len(gate)
    for i in range(n - 1):
        g = gate[i]
        if pos != 0 and g != pos:
            rows.append((idx[entry_i], idx[i+1], pos, o[entry_i], o[i+1]))
            pos = 0
        if pos == 0 and g != 0:
            pos, entry_i = g, i + 1
    if pos != 0:
        rows.append((idx[entry_i], idx[-1], pos, o[entry_i], df['Close'].iloc[-1]))
    tr = pd.DataFrame(rows, columns=['in', 'out', 'dir', 'px_in', 'px_out'])
    tr['gross_usd'] = (tr.px_out - tr.px_in) * tr['dir'] * OZ
    tr['net_usd']   = tr.gross_usd - SPREAD_USD * OZ
    tr['net_hkd']   = tr.net_usd * USD_HKD
    tr['bars']      = ((tr['out'] - tr['in']).dt.total_seconds() / 60).astype(int)
    return tr


def report(tr, label, years):
    net = tr.net_hkd
    n = len(net)
    if n == 0:
        print(f"{label}: 沒有交易"); return
    t = net.mean() / (net.std(ddof=1) / math.sqrt(n)) if n > 1 else float('nan')
    wins = net[net > 0]; losses = net[net <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
    eq = net.cumsum(); dd = (eq - eq.cummax()).min()
    print(f"\n── {label} ──")
    print(f"  交易數        {n:,}   （每年約 {n/years:,.0f} 筆）")
    print(f"  毛利          HK${tr.gross_usd.sum()*USD_HKD:>12,.0f}")
    print(f"  成本          HK${SPREAD_USD*OZ*USD_HKD*n:>12,.0f}   （佔毛利 "
          f"{SPREAD_USD*OZ*USD_HKD*n/abs(tr.gross_usd.sum()*USD_HKD)*100 if tr.gross_usd.sum() else float('nan'):.1f}%）")
    print(f"  淨利          HK${net.sum():>12,.0f}")
    print(f"  每筆淨利      HK${net.mean():>12,.2f}   t = {t:+.2f}")
    print(f"  勝率          {len(wins)/n*100:.2f}%   PF {pf:.3f}")
    print(f"  平均持倉      {tr.bars.mean():.1f} 分鐘（中位數 {tr.bars.median():.0f}）")
    print(f"  最大回撤      HK${dd:>12,.0f}")
    print(f"  年化（本金 HK$20,000）  {net.sum()/20000/years*100:+.2f}%")
    return net


if __name__ == '__main__':
    df = load()
    years = (df.index[-1] - df.index[0]).total_seconds() / (365.25*86400)
    print(f"資料 {len(df):,} 根 M1，{df.index[0]} → {df.index[-1]}（{years:.2f} 年）")

    regime, direction = verdict_series(df)
    cnt = pd.Series(regime).value_counts().sort_index()
    names = {0: 'RANGE/NODATA', 1: 'SETUP', 2: 'TREND', 3: 'PAUSE'}
    print("\n判定分佈（每根 M1）:")
    for kk, vv in cnt.items():
        print(f"  {names[kk]:<14} {vv:>10,}  {vv/len(df)*100:5.2f}%")

    allnet = {}
    for skip in (False, True):
        gate = run_gate(regime, direction, skip_setup=skip)
        tr = trades_from_gate(df, gate)
        lab = f"三級共振電閘（skip_setup={skip}）"
        allnet[skip] = tr
        report(tr, lab, years)
        # 分半
        mid = tr['in'].iloc[len(tr)//2]
        a, b = tr[tr['in'] < mid], tr[tr['in'] >= mid]
        print(f"  分半：前半 {len(a)} 筆 HK${a.net_hkd.sum():+,.0f} / 後半 {len(b)} 筆 HK${b.net_hkd.sum():+,.0f}")
        print(f"  毛利 t = {(tr.gross_usd.mean()/(tr.gross_usd.std(ddof=1)/math.sqrt(len(tr)))):+.2f}"
              f"（未扣成本；扣了才是能不能做）")
        tr.to_pickle(f'/tmp/cache/sjgz_trades_skip{int(skip)}.pkl')
