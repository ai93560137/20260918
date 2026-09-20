#!/usr/bin/env python3
"""HK50 第三輪研究（2026-09-20）— 四個新進出場候選 + 時段拆解。

結果寫在 HSI_HANDOFF.md §9。結論：
  四個候選（ORB、日/夜盤條件、星期幾、Donchian）全部陣亡。
  副產品是兩個結構事實：
    1. 全日漂移幾乎全在夜盤（17:15–03:00 HKT），日盤 ≈ 0——但夜盤漂移
       集中在頂端 5% 的夜，異常值檢查不過，且變現被成本殺死
    2. 傍晚空檔（16:30→17:15）系統性 −2.2 bp/日，五年逐年顯著（t 最強 −6.5），
       幅度低於單邊點差 → 不可直接交易，但值得當執行時機規則

用法：
    python3 hk50_round3.py sessions    # 時段拆解 + 傍晚空檔 + 夜盤穩健性
    python3 hk50_round3.py candidates  # ORB / 日夜盤條件 / 星期幾 / Donchian
"""
import sys
import numpy as np
import pandas as pd

DATA = 'data/'
COST = 0.000475


def t_of(x):
    return x.mean() / (x.std() / np.sqrt(len(x))) if len(x) > 5 and x.std() > 0 else np.nan


def daily_sessions():
    """M5 → 每日：日盤（開盤起 7h15m ≈ 09:15–16:30 HKT）與夜盤（其後到收）。"""
    m5 = pd.read_csv(DATA + 'HK50_M5_MAX.csv')
    m5['Time'] = pd.to_datetime(m5['Time'], format='%Y.%m.%d %H:%M:%S')
    m5 = m5.set_index('Time').sort_index()
    rows = []
    for d, day in m5.groupby(m5.index.date):
        if len(day) < 30:
            continue
        cut = day.index[0] + pd.Timedelta(hours=7, minutes=15)
        ds, ns = day[day.index < cut], day[day.index >= cut]
        if len(ds) < 10 or len(ns) < 5:
            continue
        rows.append(dict(date=pd.Timestamp(d), open=ds.Open.iloc[0],
                         orb_h=ds.High.iloc[:6].max(), orb_l=ds.Low.iloc[:6].min(),
                         ds_close=ds.Close.iloc[-1], n_open=ns.Open.iloc[0],
                         close=ns.Close.iloc[-1],
                         ds_bars=ds.iloc[6:][['Open', 'High', 'Low', 'Close']].values))
    df = pd.DataFrame(rows).set_index('date')
    df['r_day'] = df.ds_close / df.open - 1
    df['r_gap_eve'] = df.n_open / df.ds_close - 1
    df['r_night'] = df.close / df.n_open - 1
    df['gap_morning'] = df.open / df.close.shift(1) - 1
    return df


def sessions():
    df = daily_sessions()
    print(f"{len(df)} 天\n══ 全日報酬拆解（毛，年化 252 日）══")
    for name, r in [('早盤跳空 03:00→09:15', df.gap_morning), ('日盤 09:15→16:30', df.r_day),
                    ('傍晚空檔 16:30→17:15', df.r_gap_eve), ('夜盤 17:15→03:00', df.r_night)]:
        r = r.dropna()
        print(f"  {name:<22} 年化 {r.mean()*252*100:+7.2f}%  t={t_of(r):+.2f}")
    print("\n══ 傍晚空檔逐年 ══")
    for y, g in df.groupby(df.index.year):
        print(f"  {y}: 平均 {g.r_gap_eve.mean()*1e4:+.2f} bp  中位數 {g.r_gap_eve.median()*1e4:+.2f}"
              f"  負比例 {(g.r_gap_eve < 0).mean()*100:.0f}%  t={t_of(g.r_gap_eve):+.2f}")
    print("\n══ 夜盤漂移：異常值檢查與變現 ══")
    s = df.r_night.sort_values()
    k = int(len(s) * 0.05)
    print(f"  逐年皆正（5/5），但拿掉最賺 5% 的夜之後：{s.iloc[:-k].mean()*1e4:+.2f} bp/夜"
          f"（原 {df.r_night.mean()*1e4:+.2f}）→ 異常值檢查不過")
    v = df.r_night - COST
    print(f"  每晚做多（扣成本）: {v.mean()*252*100:+.2f}%/年  t={t_of(v):+.2f} → 死")


def candidates():
    df = daily_sessions()
    print("══ 1. ORB 開盤區間突破（前 30 分高低點、首破進場、對側停損、日盤收盤出）══")

    def orb_run(sub):
        out = []
        for _, row in sub.iterrows():
            pos, entry = 0, None
            for o, hi, lo, c in row.ds_bars:
                if pos == 0:
                    if c > row.orb_h:
                        pos, entry = 1, c
                    elif c < row.orb_l:
                        pos, entry = -1, c
                else:
                    stop = row.orb_l if pos > 0 else row.orb_h
                    if (pos > 0 and lo <= stop) or (pos < 0 and hi >= stop):
                        out.append(pos * (stop / entry - 1) - COST)
                        pos = 2
                        break
            if pos in (1, -1):
                out.append(pos * (row.ds_close / entry - 1) - COST)
        return pd.Series(out)

    h = len(df) // 2
    for lbl, sub in [('全期', df), ('前半', df.iloc[:h]), ('後半', df.iloc[h:])]:
        v = orb_run(sub)
        print(f"  {lbl} n={len(v)}  淨 {v.mean()*100:+.4f}%/筆  t={t_of(v):+.2f}")

    print("\n══ 2. 日盤/夜盤互為條件（淨值）══")
    for label, mask, tgt, sgn in [
            ('昨夜盤跌 → 今日盤做多', df.r_night.shift(1) < 0, df.r_day, 1),
            ('今日盤漲 → 今夜盤做多', df.r_day > 0, df.r_night, 1),
            ('今日盤跌 → 今夜盤做空', df.r_day < 0, df.r_night, -1)]:
        m = mask.fillna(False)
        v = tgt[m] * sgn - COST
        print(f"  {label:<24} n={m.sum():>4} 淨 {v.mean()*100:+.4f}% t={t_of(v):+.2f}")

    print("\n══ 3. 星期幾（日盤報酬，毛）══")
    for dow, g in df.groupby(df.index.dayofweek):
        print(f"  週{'一二三四五'[dow]}: {g.r_day.mean()*100:+.4f}% (t={t_of(g.r_day):+.2f})")

    print("\n══ 4. Donchian 20 日進 / 10 日反向出（D1，扣成本）══")
    d1 = pd.read_csv(DATA + 'HK50_D1_MAX.csv')
    d1['Time'] = pd.to_datetime(d1['Time'], format='%Y.%m.%d %H:%M:%S')
    d1 = d1.set_index('Time').sort_index()

    def donchian(sub, both):
        hi20 = sub.Close.rolling(20).max().shift(1)
        lo20 = sub.Close.rolling(20).min().shift(1)
        hi10 = sub.Close.rolling(10).max().shift(1)
        lo10 = sub.Close.rolling(10).min().shift(1)
        pos, p = pd.Series(np.nan, index=sub.index), 0
        for i in range(len(sub)):
            c = sub.Close.iloc[i]
            if p == 0:
                if c >= hi20.iloc[i]:
                    p = 1
                elif both and c <= lo20.iloc[i]:
                    p = -1
            elif p == 1 and c <= lo10.iloc[i]:
                p = 0
            elif p == -1 and c >= hi10.iloc[i]:
                p = 0
            pos.iloc[i] = p
        pos = pos.shift(1).fillna(0)
        strat = pos * sub.Close.pct_change().fillna(0) - pos.diff().abs().fillna(0) * COST / 2
        mo = strat.groupby(strat.index.to_period('M')).sum()
        yrs = (sub.index[-1] - sub.index[0]).days / 365.25
        return (1 + strat).prod() ** (1 / yrs) - 1, t_of(mo)

    h = len(d1) // 2
    for lbl, sub in [('全期', d1), ('前半', d1.iloc[:h]), ('後半', d1.iloc[h:])]:
        for both, bl in [(True, '雙向'), (False, '只多')]:
            ann, tmo = donchian(sub, both)
            print(f"  {lbl} {bl}: 年化 {ann*100:+6.2f}%  t(月)={tmo:+.2f}")


if __name__ == '__main__':
    dict(sessions=sessions, candidates=candidates)[sys.argv[1] if len(sys.argv) > 1 else 'sessions']()
