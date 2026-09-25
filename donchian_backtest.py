#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前 N 日高低點突破策略回測（預設 N=2）。

規則（使用者定義）：
  - 任一 M1 K 線的最低價跌破「前 2 個完整交易日」的最低點 → 做空
  - 最高價升破「前 2 個完整交易日」的最高點 → 做多

實作要點：
  - 「日」以券商日曆日切分（資料時間戳保留券商時間，載入時 offset=0，
    與 MT5 D1 K 線切法一致）；前 N 日 = 最近 N 個「完整」交易日。
  - 觸發視為 stop order：突破當根以 max(open, 突破價) 成交（多）／
    min(open, 突破價) 成交（空）。資料視為 bid，買方付點差。
  - 每個交易日、每個方向最多進場一次（否則停損後價格仍在通道外會立刻重進）。
  - 同一根 K 同時觸發雙向時，取距開盤價較近的一側，另一側當日作廢。

出場模式（--mode）：
  sar      永遠在場：反向突破時平倉並反手（經典 Donchian）。
  channel  反向突破只平倉不反手（配合 --trade-mode long/short 做單邊）。
  atr      進場時掛停損/停利：SL = k_sl × 日ATR(14)，TP = k_tp × 日ATR(14)
           （k_tp=0 表示不設停利，僅靠反向突破/停損出場）。
           SL 與 TP 同根皆可觸發時，保守假設先打停損。
  eod      當日收盤前最後一根強制平倉（隔日重新等突破）。

損益單位＝報價單位 × 1（XAUUSD：0.01 手＝1 oz，1 點＝1 USD；
指數 CFD 按各商品每點價值換算）。未模擬滑價、隔夜利息。
"""

import argparse
import csv
import math
from datetime import datetime, timezone

from zgl_backtest import load_any


def day_key(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def run(bars, lookback=2, mode="sar", trade_mode="both", spread=0.30,
        atr_len=14, k_sl=2.0, k_tp=0.0, ema_len=20, equity=10000.0,
        collect_trades=False):
    """單一設定回測。回傳統計 dict。"""
    days = []            # 已完成交易日 [{high, low, close}]
    cur_day = None       # 進行中的日 aggregates
    cur_key = None
    atr = None           # Wilder ATR（以完整日計）
    ema = None           # 日收盤 EMA（mode="ema" 的出場線，每日更新一次）
    ema_n = 0

    pos = 0              # +1 多 / -1 空 / 0 空手
    entry_price = None
    entry_time = None
    sl = tp = None
    traded_today = {1: False, -1: False}

    pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    wins = losses = 0
    win_sum = loss_sum = 0.0
    bars_in_pos = 0
    trade_rows = []

    def finish_day():
        nonlocal atr, ema, ema_n
        if cur_day is None:
            return
        days.append(dict(cur_day))
        if len(days) >= 2:
            prev_close = days[-2]["close"]
            tr = max(cur_day["high"] - cur_day["low"],
                     abs(cur_day["high"] - prev_close),
                     abs(cur_day["low"] - prev_close))
            atr = tr if atr is None else (atr * (atr_len - 1) + tr) / atr_len
        c = cur_day["close"]
        ema = c if ema is None else ema + 2.0 / (ema_len + 1) * (c - ema)
        ema_n += 1

    def close_pos(price, ts, reason):
        nonlocal pos, pnl, peak, max_dd, wins, losses, win_sum, loss_sum
        nonlocal entry_price, entry_time, sl, tp
        exit_price = price + spread if pos < 0 else price   # 空單回補付點差（買回要付 ask = 價 + 點差）
        gain = (exit_price - entry_price) * pos
        pnl += gain
        peak = max(peak, pnl)
        max_dd = max(max_dd, peak - pnl)
        if gain >= 0:
            wins += 1
            win_sum += gain
        else:
            losses += 1
            loss_sum -= gain
        if collect_trades:
            trade_rows.append(["LONG" if pos > 0 else "SHORT",
                               f"{entry_price:.6f}", f"{exit_price:.6f}", f"{gain:.6f}",   # 6 位小數：5 位報價的外匯 .2f 會把損益四捨五入到 100 pips
                               datetime.fromtimestamp(entry_time, tz=timezone.utc).isoformat(),
                               datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), reason])
        pos, entry_price, entry_time, sl, tp = 0, None, None, None, None

    def open_pos(direction, price, ts):
        nonlocal pos, entry_price, entry_time, sl, tp
        pos = direction
        entry_price = price + spread if direction > 0 else price   # 買方付點差
        entry_time = ts
        traded_today[direction] = True
        if mode == "atr" and atr:
            sl = entry_price - direction * k_sl * atr
            tp = entry_price + direction * k_tp * atr if k_tp > 0 else None
        else:
            sl = tp = None

    for i, bar in enumerate(bars):
        key = day_key(bar["time"])
        if key != cur_key:
            finish_day()
            cur_key = key
            cur_day = {"high": bar["high"], "low": bar["low"], "close": bar["close"]}
            traded_today = {1: False, -1: False}
        else:
            cur_day["high"] = max(cur_day["high"], bar["high"])
            cur_day["low"] = min(cur_day["low"], bar["low"])
            cur_day["close"] = bar["close"]

        if len(days) < lookback or (mode == "atr" and atr is None) \
                or (mode == "ema" and ema_n < ema_len):
            continue

        hi_level = max(d["high"] for d in days[-lookback:])
        lo_level = min(d["low"] for d in days[-lookback:])

        if pos != 0:
            bars_in_pos += 1
            # 1) ATR 停損/停利（保守：同根先停損）
            if pos > 0 and sl is not None and bar["low"] <= sl:
                close_pos(min(bar["open"], sl), bar["time"], "SL")
            elif pos < 0 and sl is not None and bar["high"] >= sl:
                close_pos(max(bar["open"], sl), bar["time"], "SL")
            elif pos > 0 and tp is not None and bar["high"] >= tp:
                close_pos(max(bar["open"], tp), bar["time"], "TP")
            elif pos < 0 and tp is not None and bar["low"] <= tp:
                close_pos(min(bar["open"], tp), bar["time"], "TP")
            # EMA 出場：價格回穿日收盤 EMA（停損單語意，掛在 EMA 價位）
            elif mode == "ema" and pos > 0 and bar["low"] <= ema:
                close_pos(min(bar["open"], ema), bar["time"], "EMA")
            elif mode == "ema" and pos < 0 and bar["high"] >= ema:
                close_pos(max(bar["open"], ema), bar["time"], "EMA")

        # 2) 突破訊號
        long_sig = bar["high"] >= hi_level and not traded_today[1]
        short_sig = bar["low"] <= lo_level and not traded_today[-1]
        if long_sig and short_sig:                     # 同根雙向：取距開盤較近者
            if abs(hi_level - bar["open"]) <= abs(bar["open"] - lo_level):
                short_sig = False
            else:
                long_sig = False
            traded_today[1] = traded_today[-1] = True  # 另一側當日作廢

        if trade_mode == "long":
            short_entry_allowed = False
        else:
            short_entry_allowed = True
        if trade_mode == "short":
            long_entry_allowed = False
        else:
            long_entry_allowed = True

        if pos > 0 and short_sig:                      # 反向突破
            close_pos(min(bar["open"], lo_level), bar["time"], "REV")
            if mode in ("sar", "atr", "ema") and short_entry_allowed:
                open_pos(-1, min(bar["open"], lo_level), bar["time"])
        elif pos < 0 and long_sig:
            close_pos(max(bar["open"], hi_level), bar["time"], "REV")
            if mode in ("sar", "atr", "ema") and long_entry_allowed:
                open_pos(1, max(bar["open"], hi_level), bar["time"])
        elif pos == 0:
            if long_sig and long_entry_allowed:
                open_pos(1, max(bar["open"], hi_level), bar["time"])
            elif short_sig and short_entry_allowed:
                open_pos(-1, min(bar["open"], lo_level), bar["time"])

        # 3) 日終平倉
        if mode == "eod" and pos != 0:
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            if nxt is None or day_key(nxt["time"]) != cur_key:
                close_pos(bar["close"], bar["time"], "EOD")

    if pos != 0:                                       # 期末強制平倉
        close_pos(bars[-1]["close"], bars[-1]["time"], "END")

    trades = wins + losses
    return {
        "trades": trades,
        "win_rate": wins / trades if trades else 0.0,
        "pf": (win_sum / loss_sum) if loss_sum > 0 else math.inf,
        "pnl": pnl,
        "ret": pnl / equity,
        "max_dd": max_dd / equity,
        "avg_win": win_sum / wins if wins else 0.0,
        "avg_loss": loss_sum / losses if losses else 0.0,
        "in_pos": bars_in_pos / len(bars) if bars else 0.0,
        "trade_rows": trade_rows,
    }


HEADER = (f"{'設定':<44} {'筆數':>6} {'勝率':>7} {'獲利因子':>6} "
          f"{'損益(點)':>10} {'報酬':>8} {'回撤':>8} {'持倉時間':>7}")


def fmt_row(label, r):
    pf = f"{r['pf']:.2f}" if math.isfinite(r["pf"]) else "inf"
    return (f"{label:<44} {r['trades']:>7} {r['win_rate']*100:>5.1f}% {pf:>6} "
            f"{r['pnl']:>+10.0f} {r['ret']*100:>+7.1f}% {r['max_dd']*100:>7.1f}% "
            f"{r['in_pos']*100:>6.1f}%")


def selftest():
    # 手工資料：3 天 × 每天 3 根。D1: H=110 L=100，D2: H=112 L=102。
    # 前 2 日通道 = [100, 112]。第 3 天第 2 根升破 112 → 應做多一次。
    def mk(ts, o, h, l, c):
        return {"time": ts, "open": o, "high": h, "low": l, "close": c}
    day = 86400
    bars = [mk(0, 105, 110, 100, 108), mk(60, 108, 109, 107, 108), mk(120, 108, 109, 107, 108),
            mk(day, 108, 112, 102, 110), mk(day + 60, 110, 111, 109, 110), mk(day + 120, 110, 111, 109, 110),
            mk(2 * day, 110, 111, 109, 110), mk(2 * day + 60, 110, 113, 109, 113),
            mk(2 * day + 120, 113, 114, 112, 114)]
    r = run(bars, lookback=2, mode="sar", spread=0.0)
    assert r["trades"] == 1, r
    # 進場 112、期末 114 平 → +2
    assert abs(r["pnl"] - 2.0) < 1e-9, r
    # 第 3 天先跌破 100 → 做空；同日再升破 112 → 反手做多（SAR）
    bars2 = bars[:6] + [mk(2 * day, 105, 106, 99, 100), mk(2 * day + 60, 100, 113, 99, 113),
                        mk(2 * day + 120, 113, 114, 112, 112)]
    r2 = run(bars2, lookback=2, mode="sar", spread=0.0)
    assert r2["trades"] == 2, r2          # 空單被反手平掉 + 期末平多單
    # 空 99→112 虧 13（進場 min(open=105? 不，第7根 open=105, 突破99）
    # 空單成交 min(105, 100)=100，多單反手 max(100,112)=112：空 -12、多 +0
    assert abs(r2["pnl"] - (-12.0 + (112 - 112))) < 1e-9, r2
    # 每日每方向只進一次：同日再破高不加碼
    bars3 = bars + [mk(2 * day + 180, 114, 120, 113, 119)]
    r3 = run(bars3, lookback=2, mode="sar", spread=0.0)
    assert r3["trades"] == 1, r3
    print("✅ selftest 全數通過（通道計算 / 單日單次 / SAR 反手）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", help="M1 CSV / .csv.gz（MT5 匯出格式）")
    ap.add_argument("--lookback", type=int, default=2, help="通道回看天數（預設 2）")
    ap.add_argument("--mode", choices=["sar", "channel", "atr", "eod", "ema"], default="sar")
    ap.add_argument("--ema-len", type=int, default=20, help="ema 模式：日收盤 EMA 週期")
    ap.add_argument("--trade-mode", choices=["both", "long", "short"], default="both")
    ap.add_argument("--spread", type=float, default=0.30)
    ap.add_argument("--atr-len", type=int, default=14)
    ap.add_argument("--k-sl", type=float, default=2.0)
    ap.add_argument("--k-tp", type=float, default=0.0)
    ap.add_argument("--equity", type=float, default=10000.0)
    ap.add_argument("--trades", help="把每筆成交寫到這個 CSV")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if not args.data:
        raise SystemExit("請指定資料檔（或 --selftest）")

    bars = load_any(args.data, 0.0)       # 保留券商時間，日界＝券商午夜（同 MT5 D1）
    print(f"📊 載入 {len(bars)} 根 K 線 "
          f"({day_key(bars[0]['time'])} → {day_key(bars[-1]['time'])})")
    base = dict(spread=args.spread, equity=args.equity, atr_len=args.atr_len)

    if args.sweep:
        print(HEADER)
        for lb in (1, 2, 3, 5):
            r = run(bars, lookback=lb, mode="sar", trade_mode="both", **base)
            print(fmt_row(f"sar N={lb}", r))
        for tm in ("long", "short"):
            r = run(bars, lookback=2, mode="channel", trade_mode=tm, **base)
            print(fmt_row(f"channel N=2 {tm}-only", r))
        for k_sl, k_tp in ((1.5, 0.0), (2.0, 0.0), (2.0, 4.0), (3.0, 6.0)):
            r = run(bars, lookback=2, mode="atr", trade_mode="both",
                    k_sl=k_sl, k_tp=k_tp, **base)
            print(fmt_row(f"atr N=2 SL={k_sl} TP={k_tp or '無'}", r))
        r = run(bars, lookback=2, mode="eod", trade_mode="both", **base)
        print(fmt_row("eod N=2（日內，收盤平倉）", r))
        return

    r = run(bars, lookback=args.lookback, mode=args.mode, trade_mode=args.trade_mode,
            k_sl=args.k_sl, k_tp=args.k_tp, ema_len=args.ema_len,
            collect_trades=bool(args.trades), **base)
    print(HEADER)
    print(fmt_row(f"{args.mode} N={args.lookback} {args.trade_mode}", r))
    print(f"平均獲利 {r['avg_win']:.2f} / 平均虧損 {r['avg_loss']:.2f}（報價單位）")
    if args.trades:
        with open(args.trades, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["direction", "entry", "exit", "pnl", "open_time", "close_time", "reason"])
            w.writerows(r["trade_rows"])
        print(f"📝 交易明細已寫入 {args.trades}")


if __name__ == "__main__":
    main()
