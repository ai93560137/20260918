#!/usr/bin/env python3
"""GCP 整條管線的回測 —— 三級共振（方向）＋ 進場引擎（結構／K 線／RSI／加單）。

§22/§23 只測了三級共振本身。真正決定下不下單的是它後面那層
PureGCPPyramidingSession，而那一層從來沒有人量過。這支腳本把 main.py 的
evaluate_and_trigger / _first_entry_structure / calculate_max_lots 原樣移植。

兩個版本：
  A  舊版：armed 由三級共振給（GATE_DRIVER=REGIME），多空皆做
  B  現版：armed 由風控五關給（GATE_DRIVER=RISK）＋ LONG_ONLY

用法: python3 gcp_pipeline_sim.py
"""
import math
import numpy as np
import pandas as pd
from sanjigongzhen_sim import load, verdict_series, run_gate

# ---- main.py 的常數（逐項對照） --------------------------------------------
CONTRACT_SIZE   = 100.0     # 1 手 = 100 oz
FX_HKD_USD      = 1 / 7.8
RISK_PCT        = 0.02
BROKER_LEVERAGE = 500.0
MAX_MARGIN_PCT  = 0.20
HARD_MAX_LOTS   = 1.00
ORDER_SIZE      = 0.01
SL_ATR_MULT     = 1.5
MIN_SL_DISTANCE = 6.0
TARGET_RRR      = 3.0
ADD_SPACING_ATR = 0.5
REENTRY_COOLDOWN_SEC = 300
ORDER_SETTLE_SEC     = 180
RSI_BUY_MAX     = 85.0
RSI_SELL_MIN    = 15.0
M15_CLOSE_POSITION_MIN = 0.7
BB_PERIOD, BB_STD = 20, 2.0
SPREAD_USD      = 0.40      # 來回，每盎司
EQUITY0_HKD     = 20000.0
# 風控電閘（B 版）
VOL_FLOOR_ATR_PCT = 0.10
DD_TOLERANCE_PCT  = 20.0
WORST_GAP_PCT     = 14.0
EXPOSURE_HARD_CAP = 2.0
DAILY_LOSS_LIMIT_PCT = 3.0
TRAINING_MAX_PER_DAY = 2


def wilder_rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = np.empty_like(c); ad = np.empty_like(c)
    au[:n] = np.nan; ad[:n] = np.nan
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = au / ad
    return np.where(ad == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))


def m15_frames(df):
    """完成的 M15 K 線 → BB(20,2) 與 ATR(14)；再把它們對齊回每根 M1。"""
    g = df.resample('15min')
    m15 = pd.DataFrame({'Open': g.Open.first(), 'High': g.High.max(),
                        'Low': g.Low.min(), 'Close': g.Close.last()}).dropna()
    c = m15.Close
    sma = c.rolling(BB_PERIOD).mean()
    sd = c.rolling(BB_PERIOD).apply(lambda x: np.sqrt(((x - x.mean()) ** 2).mean()), raw=True)
    tr = pd.concat([m15.High - m15.Low, (m15.High - c.shift()).abs(),
                    (m15.Low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    lv = pd.DataFrame({'mid': sma, 'r1': sma + BB_STD * sd, 's1': sma - BB_STD * sd,
                       'atr': atr}).shift(1)          # 只用【已完成】的 M15，不偷看
    # 對齊回 M1：每根 M1 取它所屬 M15 區間的「上一根完成 M15」的值
    idx = df.index.floor('15min')
    out = lv.reindex(idx)
    out.index = df.index
    return out


def forming_m15(df):
    """該根 M1 當下，正在形成的 M15 K 線的 high/low/close → 收盤位置。"""
    key = df.index.floor('15min')
    hi = df.High.groupby(key).cummax().to_numpy()
    lo = df.Low.groupby(key).cummin().to_numpy()
    cl = df.Close.to_numpy()
    rng = hi - lo
    return np.where(rng > 0, (cl - lo) / rng, np.nan)


def max_lots(equity_hkd, price, sl):
    eq_usd = equity_hkd * FX_HKD_USD
    if eq_usd <= 0 or price <= 0 or sl <= 0:
        return 0.0
    risk = eq_usd * RISK_PCT / (sl * CONTRACT_SIZE)
    marg = eq_usd * MAX_MARGIN_PCT / (price * CONTRACT_SIZE / BROKER_LEVERAGE)
    return math.floor(min(risk, marg, HARD_MAX_LOTS) * 100 + 1e-9) / 100.0


def simulate(df, mode):
    """mode='A' 舊版（三級共振 armed，多空）；'B' 現版（風控 armed ＋ 只做多）"""
    O, H, L, C = (df[k].to_numpy(float) for k in ('Open', 'High', 'Low', 'Close'))
    t = df.index.to_numpy('datetime64[s]').astype(np.int64)
    n = len(df)
    regime, vdir = verdict_series(df)
    armed_regime = run_gate(regime, vdir, False)          # A 版的 armed
    rsi = wilder_rsi(C)
    lv = m15_frames(df)
    mid, r1, s1, atr15 = (lv[k].to_numpy(float) for k in ('mid', 'r1', 's1', 'atr'))
    pos15 = forming_m15(df)
    day = df.index.tz_localize('UTC').tz_convert('America/New_York').strftime('%Y-%m-%d').to_numpy()

    equity = EQUITY0_HKD
    peak = EQUITY0_HKD
    lots = 0.0            # 目前持倉（手），正=多 負=空
    legs = []             # [(entry_px, lot, sl_px, tp_px)]
    anchor = None; anchor_dir = 0
    last_close_ts = -1e9; last_order_ts = -1e9; expo_at_order = -1.0
    cur_day = None; day_pnl = 0.0; day_trades = 0
    trades = []; rejects = {}

    def rej(k):
        rejects[k] = rejects.get(k, 0) + 1

    for i in range(n):
        if day[i] != cur_day:
            cur_day, day_pnl, day_trades = day[i], 0.0, 0

        # ---- 先處理出場（用這根 M1 的高低點，停損優先） ----
        if legs:
            closed = []
            for k, (px, lot, slp, tpp, ein) in enumerate(legs):
                d = 1 if lot > 0 else -1
                hit = None
                if d > 0:
                    if L[i] <= slp: hit = slp
                    elif H[i] >= tpp: hit = tpp
                else:
                    if H[i] >= slp: hit = slp
                    elif L[i] <= tpp: hit = tpp
                if hit is not None:
                    gross = (hit - px) * d * abs(lot) * CONTRACT_SIZE
                    net = (gross - SPREAD_USD * abs(lot) * CONTRACT_SIZE) * 7.8
                    equity += net; day_pnl += net
                    trades.append(dict(t=df.index[i], t_in=df.index[ein], i_in=ein,
                                       dir='多' if d > 0 else '空',
                                       px_in=px, px_out=hit, lot=abs(lot), R=abs(px - slp),
                                       how='tp' if hit == tpp else 'sl', hkd=net))
                    closed.append(k)
            if closed:
                legs = [l for k, l in enumerate(legs) if k not in closed]
                lots = sum(l[1] for l in legs)
                last_close_ts = t[i]
                if not legs:
                    anchor, anchor_dir = None, 0
        peak = max(peak, equity)

        # ---- armed / dir ----
        d_now = vdir[i]                                    # 三級共振給的方向（兩版都一樣）
        if mode == 'A':
            armed = armed_regime[i] != 0
            d_now = armed_regime[i]
        else:   # B 與 C 共用同一套風控五關
            # 風控五關
            price = C[i]; a = atr15[i]
            if np.isnan(a) or price <= 0:
                armed = False
            else:
                ok_vol = (a / price * 100) >= VOL_FLOOR_ATR_PCT
                dd = max(0.0, (peak - equity) / peak * 100) if peak > 0 else 0.0
                cap = min(EXPOSURE_HARD_CAP, max(0.0, (DD_TOLERANCE_PCT - dd) / WORST_GAP_PCT))
                exp_now = abs(lots) * CONTRACT_SIZE * price / (equity * FX_HKD_USD) if equity > 0 else 9e9
                ok_exp = exp_now <= cap
                ok_day = day_pnl > -equity * DAILY_LOSS_LIMIT_PCT / 100
                ok_pace = day_trades < TRAINING_MAX_PER_DAY
                armed = ok_vol and ok_exp and ok_day and ok_pace
                if not ok_vol: rej('風控:波動')
                elif not ok_exp: rej('風控:曝險')
                elif not ok_day: rej('風控:單日虧損')
                elif not ok_pace: rej('風控:訓練節奏')
        if mode == 'C':
            d_now = 1                                   # 完全不看三級共振：永遠做多
        if not armed or d_now == 0:
            if armed and d_now == 0: rej('三級共振:RANGE')
            continue
        side = 1 if d_now > 0 else -1
        if mode == 'B' and side < 0:
            rej('只做多'); continue

        # ---- 資料就緒 ----
        if np.isnan(mid[i]) or np.isnan(atr15[i]) or atr15[i] <= 0:
            rej('結構未就緒'); continue
        sl_dist = max(MIN_SL_DISTANCE, round(atr15[i] * SL_ATR_MULT, 2))
        ml = max_lots(equity, C[i], sl_dist)
        gross_lots = round(abs(lots), 2)
        if t[i] - last_order_ts < ORDER_SETTLE_SEC and abs(gross_lots - expo_at_order) < 0.005:
            rej('等待成交回報'); continue
        if not np.isnan(rsi[i]) and ((side > 0 and rsi[i] >= RSI_BUY_MAX) or
                                     (side < 0 and rsi[i] <= RSI_SELL_MIN)):
            rej('RSI 極值'); continue
        candle_ok = (C[i] > O[i]) if side > 0 else (C[i] < O[i])

        if gross_lots == 0:
            if t[i] - last_close_ts < REENTRY_COOLDOWN_SEC: rej('平倉冷卻'); continue
            if not candle_ok: rej('首單:K 線不同向'); continue
            if side > 0 and C[i] <= r1[i]: rej('首單:未突破上軌'); continue
            if side < 0 and C[i] >= s1[i]: rej('首單:未跌破下軌'); continue
            if np.isnan(pos15[i]): rej('首單:M15 資料不足'); continue
            if side > 0 and pos15[i] < M15_CLOSE_POSITION_MIN: rej('首單:收盤位置不夠高'); continue
            if side < 0 and pos15[i] > 1 - M15_CLOSE_POSITION_MIN: rej('首單:收盤位置不夠低'); continue
            if ml + 1e-9 < ORDER_SIZE: rej('首單:風險上限不足'); continue
            kind = 'FIRST'
        else:
            if (1 if lots > 0 else -1) != side: rej('加單:方向衝突'); continue
            if gross_lots + ORDER_SIZE > ml + 1e-9: rej('加單:超過風險上限'); continue
            if not candle_ok: rej('加單:K 線不同向'); continue
            if (side > 0 and C[i] < mid[i]) or (side < 0 and C[i] > mid[i]):
                rej('加單:結構破壞'); continue
            if anchor is None or anchor_dir != side:
                anchor, anchor_dir = C[i], side
                rej('加單:重設基準'); continue
            spacing = round(atr15[i] * ADD_SPACING_ATR, 2)
            target = anchor + spacing if side > 0 else anchor - spacing
            if (side > 0 and C[i] < target) or (side < 0 and C[i] > target):
                rej('加單:未達加碼距離'); continue
            kind = 'ADD'

        px = C[i]
        legs.append((px, ORDER_SIZE * side, px - side * sl_dist, px + side * sl_dist * TARGET_RRR, i))
        lots = sum(l[1] for l in legs)
        anchor, anchor_dir = px, side
        last_order_ts = t[i]; expo_at_order = round(abs(lots), 2)
        day_trades += 1

    return pd.DataFrame(trades), rejects, equity


def report(tr, equity, years, label, rejects):
    print(f"\n{'='*64}\n{label}\n{'='*64}")
    if tr.empty:
        print("  一筆都沒有成交。")
    else:
        h = tr.hkd
        t = h.mean() / (h.std(ddof=1) / math.sqrt(len(h)))
        eq = h.cumsum(); dd = (eq - eq.cummax()).min()
        sv = np.sort(h.values)[::-1]; k = int(len(h) * 0.05)
        print(f"  成交       {len(h):>6} 筆（每年 {len(h)/years:,.0f}）"
              f"  停損 {(tr.how=='sl').sum()} / 停利 {(tr.how=='tp').sum()}")
        print(f"  勝率       {(h>0).mean()*100:>6.2f}%   PF "
              f"{h[h>0].sum()/abs(h[h<=0].sum()):.3f}" if (h<=0).any() else "")
        print(f"  總損益     HK${h.sum():>+10,.0f}   每筆 HK${h.mean():>+8.2f}   t = {t:+.2f}")
        print(f"  年化       {h.sum()/EQUITY0_HKD/years*100:>+6.2f}%   最大回撤 HK${dd:,.0f}"
              f" ({dd/EQUITY0_HKD*100:.1f}%)")
        print(f"  期末權益   HK${equity:,.0f}（起始 {EQUITY0_HKD:,.0f}）")
        print(f"  去掉最賺 5%（{k} 筆）→ HK${sv[k:].sum():+,.0f}")
        y = tr.copy(); y['yr'] = y.t.dt.year
        print("  逐年 " + "  ".join(f"{a}:{b.hkd.sum():+,.0f}" for a, b in y.groupby('yr')))
    top = sorted(rejects.items(), key=lambda x: -x[1])[:8]
    print("  最常見的攔截原因：" + "  ".join(f"{k}×{v:,}" for k, v in top))


if __name__ == '__main__':
    df = load()
    years = (df.index[-1] - df.index[0]).days / 365.25
    print(f"XAUUSD M1 {len(df):,} 根　{df.index[0]} → {df.index[-1]}　({years:.2f} 年)")
    for mode, label in (('A', 'A｜舊版 GCP：三級共振開閘 ＋ 多空皆做（從未回測過的那個）'),
                        ('B', 'B｜現版 GCP：風控五關開閘 ＋ 三級共振給方向 ＋ 只做多'),
                        ('C', 'C｜拿掉三級共振：風控五關開閘 ＋ 永遠做多 ＋ 同一個進場引擎')):
        tr, rej, eq = simulate(df, mode)
        report(tr, eq, years, label, rej)
        tr.to_pickle(f'/tmp/cache/gcp_pipeline_{mode}.pkl')
