#!/usr/bin/env python3
# =============================================================================
# 智能諸葛亮0829（ZGL）— ZLEMA 彩帶動能策略離線回測
# -----------------------------------------------------------------------------
# 把 TradingView 指標「智能諸葛亮0829」的訊號邏輯逐行移植成策略：
#   • 動能：hl2 的九條 ZLEMA 彩帶（6, 27, …, 174），WMA5(L1−L9) >= 0 為多方動能
#   • 首單：動能方向 + 同向 K 色（綠=close>open / 紅=close<open）
#   • 加單：同向 K 色、距上次進場 >= add_interval 根、次數 < max_adds
#   • 翻轉：動能一轉向，觸發旗標與加單計數即刻歸零（同指標 Section 3）
#   • 盤整過濾：stdev(close,20) 於 100 根內的百分位 < sideways_level 時
#     訂單改 log_only（狀態機照走、單不送）——同指標 build_json 的行為
#
# 出場模型（--exit）：
#   faithful  完全模擬目前實盤：訂單帶 execution_mode=close_opposite，
#             舊倉要等「翻轉後第一張反向單成交」才被平掉。
#             （指標裡 global_trend_up/down 從未賦值，FLIP 平倉是死代碼，
#              所以實盤現在就是這個行為。）
#   flipclose 補上 FLIP：動能翻轉當根收盤後，下一根開盤先全平再等反向首單。
#
# 成交假設：訊號於 K 線收盤確立（對應 alert.freq_once_per_bar_close），
# 下一根開盤成交；買進付點差（ask = open + spread），資料視為 bid 價。
# 每張單固定 0.01 手 XAUUSD = 1 oz → 價格每動 1 美元，單張損益 1 美元。
#
# 用法：
#   python3 zgl_backtest.py XAUUSD_M1.csv --broker-offset 3
#   python3 zgl_backtest.py XAUUSD_M1.csv --broker-offset 3 --sweep
#   python3 zgl_backtest.py XAUUSD_M1.csv --exit flipclose --max-adds 20 --trades out.csv
#   python3 zgl_backtest.py --selftest        # 引擎數學與狀態機自檢
#   python3 zgl_backtest.py --synthetic 80000 # 合成資料煙霧測試（僅驗證引擎，非結論）
# =============================================================================
import argparse
import csv
import math
import random
import sys
from collections import deque

try:
    from backtest import load_bars          # 重用 v12 回測的 MT5 CSV/JSON 載入器
except Exception:                            # pragma: no cover - 獨立使用時
    load_bars = None


# =============================================================================
# 1. Pine 內建函式的逐一對應（ta.ema / ta.wma / ta.stdev / ta.highest / ta.lowest）
# =============================================================================
class EMA:
    """ta.ema：alpha=2/(len+1)，首根以來源值起算（與 Pine 相同，靠暖機收斂）。"""

    def __init__(self, length):
        self.alpha = 2.0 / (length + 1.0)
        self.value = None

    def update(self, x):
        self.value = x if self.value is None else self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class ZLEMA:
    """指標裡的 zlema()：ema1 + (ema1 - ema2)。"""

    def __init__(self, length):
        self.e1, self.e2 = EMA(length), EMA(length)

    def update(self, x):
        a = self.e1.update(x)
        b = self.e2.update(a)
        return 2.0 * a - b


class WMA:
    """ta.wma：線性加權，最新一根權重最大；不足 length 根回傳 None。"""

    def __init__(self, length):
        self.length = length
        self.buf = deque(maxlen=length)
        self.denom = length * (length + 1) / 2.0

    def update(self, x):
        self.buf.append(x)
        if len(self.buf) < self.length:
            return None
        return sum((i + 1) * v for i, v in enumerate(self.buf)) / self.denom


class RollingStdev:
    """ta.stdev(close, n)：母體標準差（除以 n，與 Pine 相同）。"""

    def __init__(self, length):
        self.length = length
        self.buf = deque(maxlen=length)

    def update(self, x):
        self.buf.append(x)
        if len(self.buf) < self.length:
            return None
        mean = sum(self.buf) / self.length
        return math.sqrt(sum((v - mean) ** 2 for v in self.buf) / self.length)


# =============================================================================
# 2. 訊號引擎：指標 Section 2/3/4 的逐 bar 移植
# =============================================================================
class ZGLSignals:
    def __init__(self, step=21, bos_smooth=5, add_interval=1, max_adds=200,
                 pyramid=True, sideways_level=0.0):
        self.zlemas = [ZLEMA(6 + step * k) for k in range(9)]
        self.wma = WMA(bos_smooth)
        self.add_interval = add_interval
        self.max_adds = max_adds
        self.pyramid = pyramid
        self.sideways_level = sideways_level
        self.stdev20 = RollingStdev(20)
        self.stdev_hist = deque(maxlen=100)

        self.is_up = None
        self.long_triggered = False
        self.short_triggered = False
        self.long_count = 0
        self.short_count = 0
        self.last_long_bar = 0
        self.last_short_bar = 0

    def update(self, bar_index, o, h, l, c):
        """收盤時呼叫。回傳 dict：動能方向、翻轉、首單/加單訊號、盤整旗標。"""
        hl2 = (h + l) / 2.0
        levels = [z.update(hl2) for z in self.zlemas]
        signal = self.wma.update(levels[0] - levels[8])
        if signal is None:
            return None
        is_up = signal >= 0.0
        flipped = self.is_up is not None and is_up != self.is_up
        self.is_up = is_up

        # 盤整過濾（Section 4 的 db_vol）：資料不足時 Pine 會是 na → 視為非盤整
        sd = self.stdev20.update(c)
        sideways = False
        if sd is not None:
            self.stdev_hist.append(sd)
            if len(self.stdev_hist) == 100 and self.sideways_level > 0:
                hi, lo = max(self.stdev_hist), min(self.stdev_hist)
                denom = (hi - lo) if hi != lo else 1.0
                sideways = (sd - lo) / denom * 100.0 < self.sideways_level

        green, red = c > o, c < o
        buy_first = is_up and green and not self.long_triggered
        sell_first = (not is_up) and red and not self.short_triggered
        buy_add = (self.pyramid and self.long_triggered and self.long_count < self.max_adds
                   and bar_index - self.last_long_bar >= self.add_interval and green and is_up)
        sell_add = (self.pyramid and self.short_triggered and self.short_count < self.max_adds
                    and bar_index - self.last_short_bar >= self.add_interval and red and not is_up)

        # Section 3 的狀態重設：動能一轉向，另一邊全部歸零
        if is_up:
            self.short_triggered, self.short_count, self.last_short_bar = False, 0, 0
            if buy_add:
                self.long_count += 1
            if buy_first:
                self.long_triggered = True
            if buy_first or buy_add:
                self.last_long_bar = bar_index
        else:
            self.long_triggered, self.long_count, self.last_long_bar = False, 0, 0
            if sell_add:
                self.short_count += 1
            if sell_first:
                self.short_triggered = True
            if sell_first or sell_add:
                self.last_short_bar = bar_index

        return {"is_up": is_up, "flipped": flipped, "sideways": sideways,
                "buy_first": buy_first, "buy_add": buy_add,
                "sell_first": sell_first, "sell_add": sell_add}


# =============================================================================
# 3. 券商端：0.01 手單位倉、close_opposite、點差、權益曲線
# =============================================================================
class Broker:
    def __init__(self, spread=0.30, unit_usd_per_usd=1.0, equity=10000.0):
        self.spread = spread
        self.unit = unit_usd_per_usd          # 0.01 手 XAUUSD = 1 oz → 1.0
        self.longs, self.shorts = [], []      # 每個元素 = 一張單的進場價
        self.realized = 0.0
        self.equity0 = equity
        self.trades = []                      # (dir, entry, exit, pnl, when)
        self.peak = equity
        self.max_dd = 0.0
        self.max_units = 0
        self.bars_in_market = 0

    # --- 成交（價格傳入 bid；買方付點差） ---
    def open_long(self, bid, when):
        self.longs.append((bid + self.spread, when))

    def open_short(self, bid, when):
        self.shorts.append((bid, when))

    def close_longs(self, bid, when):
        for entry, t0 in self.longs:
            pnl = (bid - entry) * self.unit
            self.realized += pnl
            self.trades.append(("long", entry, bid, pnl, t0, when))
        self.longs = []

    def close_shorts(self, bid, when):
        ask = bid + self.spread
        for entry, t0 in self.shorts:
            pnl = (entry - ask) * self.unit
            self.realized += pnl
            self.trades.append(("short", entry, ask, pnl, t0, when))
        self.shorts = []

    def mark(self, close_bid):
        floating = sum((close_bid - e) * self.unit for e, _ in self.longs)
        floating += sum((e - (close_bid + self.spread)) * self.unit for e, _ in self.shorts)
        equity = self.equity0 + self.realized + floating
        self.peak = max(self.peak, equity)
        if self.peak > 0:
            self.max_dd = max(self.max_dd, (self.peak - equity) / self.peak * 100.0)
        units = len(self.longs) + len(self.shorts)
        self.max_units = max(self.max_units, units)
        if units:
            self.bars_in_market += 1
        return equity


# =============================================================================
# 4. 回測主迴圈：收盤出訊號 → 下一根開盤成交
# =============================================================================
def run(bars, *, exit_mode="faithful", trade_mode="both", spread=0.30,
        step=21, bos_smooth=5, add_interval=1, max_adds=200, pyramid=True,
        sideways_level=0.0, equity=10000.0, warmup=1000, collect_trades=False):
    sig_engine = ZGLSignals(step=step, bos_smooth=bos_smooth, add_interval=add_interval,
                            max_adds=max_adds, pyramid=pyramid, sideways_level=sideways_level)
    broker = Broker(spread=spread, equity=equity)
    pending = None                            # 上一根收盤產生、等本根開盤成交的訊號

    for i, bar in enumerate(bars):
        o = bar["open"]
        if pending is not None and i >= warmup:
            s = pending
            allow_long = trade_mode in ("both", "long")
            allow_short = trade_mode in ("both", "short")
            when = bar["time"]

            if exit_mode == "flipclose" and s["flipped"]:
                broker.close_longs(o, when)
                broker.close_shorts(o, when)

            if not s["sideways"]:             # 盤整 → log_only，單不送（狀態機已在訊號端照走）
                if (s["buy_first"] or s["buy_add"]) and allow_long:
                    broker.close_shorts(o, when)          # execution_mode=close_opposite
                    broker.open_long(o, when)
                if (s["sell_first"] or s["sell_add"]) and allow_short:
                    broker.close_longs(o, when)
                    broker.open_short(o, when)

        pending = sig_engine.update(i, o, bar["high"], bar["low"], bar["close"])
        broker.mark(bar["close"])

    # 期末強制平倉，讓統計對稱
    last = bars[-1]
    broker.close_longs(last["close"], last["time"])
    broker.close_shorts(last["close"], last["time"])
    broker.mark(last["close"])

    wins = [t for t in broker.trades if t[3] > 0]
    losses = [t for t in broker.trades if t[3] <= 0]
    gross_win = sum(t[3] for t in wins)
    gross_loss = -sum(t[3] for t in losses)
    result = {
        "trades": len(broker.trades),
        "win_rate": 100.0 * len(wins) / len(broker.trades) if broker.trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "net_usd": broker.realized,
        "return_pct": broker.realized / equity * 100.0,
        "max_dd_pct": broker.max_dd,
        "max_units": broker.max_units,
        "exposure_pct": 100.0 * broker.bars_in_market / max(1, len(bars)),
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": gross_loss / len(losses) if losses else 0.0,
    }
    if collect_trades:
        result["trade_rows"] = broker.trades
    return result


# =============================================================================
# 5. 引擎自檢與合成資料
# =============================================================================
def selftest():
    w = WMA(5)
    out = [w.update(x) for x in (1, 2, 3, 4, 5)]
    assert out[:4] == [None] * 4 and abs(out[4] - 55.0 / 15.0) < 1e-12, "WMA 錯誤"

    e = EMA(9)
    assert e.update(10.0) == 10.0, "EMA 首值應等於來源"
    assert abs(e.update(20.0) - (0.2 * 20 + 0.8 * 10)) < 1e-12, "EMA 遞迴錯誤"

    z = ZLEMA(9)
    v = None
    for _ in range(300):
        v = z.update(50.0)
    assert abs(v - 50.0) < 1e-9, "ZLEMA 常數輸入應收斂到常數"

    # 狀態機：動能恆為多（用大幅上漲 K 線保證）、間隔 2、上限 2
    s = ZGLSignals(step=1, bos_smooth=1, add_interval=2, max_adds=2)
    price, firsts, adds = 100.0, [], []
    for i in range(60):
        o, c = price, price + 1.0            # 全綠 K，持續上漲 → 動能恆多
        r = s.update(i, o, c + 0.5, o - 0.5, c)
        price = c
        if r and r["buy_first"]:
            firsts.append(i)
        if r and r["buy_add"]:
            adds.append(i)
    assert len(firsts) == 1, f"首單應只有一次，得到 {firsts}"
    assert len(adds) == 2, f"加單上限 2 應只加 2 次，得到 {adds}"
    assert adds[0] - firsts[0] >= 2 and adds[1] - adds[0] >= 2, f"加單間隔應 >=2：{firsts}+{adds}"

    # 翻轉重設：先漲後跌，空方首單要在動能翻空後的紅 K 出現
    s2 = ZGLSignals(step=1, bos_smooth=1)
    price, saw_flip, saw_sell = 100.0, False, False
    for i in range(200):
        delta = 1.0 if i < 100 else -1.0
        o, c = price, price + delta
        r = s2.update(i, o, max(o, c) + 0.5, min(o, c) - 0.5, c)
        price = c
        if r and r["flipped"]:
            saw_flip = True
        if r and r["sell_first"]:
            assert saw_flip, "空首單不該出現在翻空之前"
            saw_sell = True
    assert saw_flip and saw_sell, "應觀察到翻轉與空方首單"
    print("✅ selftest 全數通過（WMA / EMA / ZLEMA / 狀態機 / 翻轉重設）")


def synthetic_bars(n, seed=42):
    """趨勢段+盤整段交替的合成 M1 資料。只用來驗證引擎會不會動，不構成任何結論。"""
    rng = random.Random(seed)
    bars, price, t = [], 3600.0, 1_760_000_000
    mu = 0.0
    for i in range(n):
        if i % 2400 == 0:                    # 每 ~40 小時換一次 regime
            mu = rng.choice([0.03, -0.03, 0.0, 0.05, -0.05])
        ret = rng.gauss(mu, 0.9)
        o = price
        c = max(1.0, o + ret)
        hi = max(o, c) + abs(rng.gauss(0, 0.3))
        lo = min(o, c) - abs(rng.gauss(0, 0.3))
        bars.append({"time": t, "open": o, "high": hi, "low": lo, "close": c})
        price, t = c, t + 60
    return bars


# =============================================================================
# 6. 報表
# =============================================================================
def fmt_row(label, r):
    pf = f"{r['profit_factor']:.2f}" if math.isfinite(r["profit_factor"]) else "inf"
    return (f"{label:<44} {r['trades']:>6} {r['win_rate']:>5.1f}% {pf:>6} "
            f"{r['net_usd']:>+10.0f} {r['return_pct']:>+7.1f}% {r['max_dd_pct']:>6.1f}% "
            f"{r['max_units']:>5} {r['exposure_pct']:>5.1f}%")


HEADER = (f"{'設定':<44} {'筆數':>6} {'勝率':>6} {'獲利因子':>6} {'損益USD':>10} "
          f"{'報酬':>8} {'回撤':>7} {'最大倉':>5} {'持倉時間':>6}")


def main():
    ap = argparse.ArgumentParser(description="智能諸葛亮0829 ZLEMA 彩帶策略回測")
    ap.add_argument("data", nargs="?", help="MT5 匯出的 M1 CSV 或 m1_history JSON")
    ap.add_argument("--broker-offset", type=float, default=0.0, help="券商時區時差（小時）")
    ap.add_argument("--exit", choices=["faithful", "flipclose"], default="faithful")
    ap.add_argument("--trade-mode", choices=["both", "long", "short"], default="both")
    ap.add_argument("--spread", type=float, default=0.30)
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--bos-smooth", type=int, default=5)
    ap.add_argument("--add-interval", type=int, default=1)
    ap.add_argument("--max-adds", type=int, default=200)
    ap.add_argument("--no-pyramid", action="store_true")
    ap.add_argument("--sideways-level", type=float, default=0.0)
    ap.add_argument("--equity", type=float, default=10000.0)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--trades", help="把每筆成交寫到這個 CSV")
    ap.add_argument("--sweep", action="store_true", help="掃描出場模型 × 加單上限 × 間隔 × 盤整過濾")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--synthetic", type=int, default=0, help="產生 N 根合成 K 線做引擎煙霧測試")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    if args.synthetic:
        bars = synthetic_bars(args.synthetic)
        print(f"⚠️ 合成資料 {len(bars)} 根：只驗證引擎行為，數字不構成任何交易結論。")
    elif args.data:
        if load_bars is None:
            raise SystemExit("找不到 backtest.py 的 load_bars，請在 repo 根目錄執行")
        bars = load_bars(args.data, args.broker_offset)
        print(f"📊 載入 {len(bars)} 根 K 線")
    else:
        ap.error("請提供資料檔，或使用 --selftest / --synthetic")

    base = dict(spread=args.spread, step=args.step, bos_smooth=args.bos_smooth,
                equity=args.equity, warmup=args.warmup, trade_mode=args.trade_mode)

    if args.sweep:
        print(HEADER)
        for exit_mode in ("faithful", "flipclose"):
            for max_adds, interval in ((0, 1), (5, 1), (20, 1), (20, 3), (200, 1), (200, 3)):
                r = run(bars, exit_mode=exit_mode, max_adds=max(1, max_adds),
                        pyramid=max_adds > 0, add_interval=interval, sideways_level=0.0, **base)
                label = f"{exit_mode} adds={max_adds} interval={interval}"
                print(fmt_row(label, r))
        for lvl in (10.0, 20.0, 40.0):
            r = run(bars, exit_mode="flipclose", max_adds=20, add_interval=1,
                    sideways_level=lvl, **base)
            print(fmt_row(f"flipclose adds=20 盤整過濾={lvl:.0f}", r))
        return

    r = run(bars, exit_mode=args.exit, max_adds=args.max_adds, pyramid=not args.no_pyramid,
            add_interval=args.add_interval, sideways_level=args.sideways_level,
            collect_trades=bool(args.trades), **base)
    print(HEADER)
    print(fmt_row(f"{args.exit} adds={args.max_adds} interval={args.add_interval}", r))
    print(f"平均獲利 {r['avg_win']:.2f} / 平均虧損 {r['avg_loss']:.2f} USD（單張 0.01 手）")

    if args.trades and "trade_rows" in r:
        with open(args.trades, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["direction", "entry", "exit", "pnl_usd", "open_time", "close_time"])
            for row in r["trade_rows"]:
                w.writerow([row[0], f"{row[1]:.2f}", f"{row[2]:.2f}", f"{row[3]:.2f}", row[4], row[5]])
        print(f"📝 已輸出 {len(r['trade_rows'])} 筆交易到 {args.trades}")


if __name__ == "__main__":
    main()
