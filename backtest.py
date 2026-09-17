#!/usr/bin/env python3
# =============================================================================
# 智能諸葛亮 v12 — 離線回測（吃 MT5 匯出的 M1 CSV）
# -----------------------------------------------------------------------------
# 設計原則：**所有交易規則都直接 import main.py**，不在這裡重寫一份。
#   雷達判定、電閘狀態機、布林帶、RSI、倉位計算、加單間距、冷卻、結構過濾
#   全部呼叫 main.py 的函式，所以回測跟實盤用的是同一套邏輯。
#
# 這支腳本自己做的只有「券商那一端」：成交、止損止盈、移動止損、保本、
# 點差與權益變化——因為那些在實盤是 webhooktrade/MT5 做的，main.py 看不到。
#
# 用法：
#   python3 backtest.py XAUUSD_M1.csv
#   python3 backtest.py XAUUSD_M1.csv --sweep-k 0.6,0.8,1.0,1.2,1.5 --modes strict,aggressive
#   python3 backtest.py XAUUSD_M1.csv --mode all-off --trades trades.csv
#   python3 backtest.py m1_history.json --broker-offset 3
#
# MT5 匯出方式：工具 → 歷史數據中心 → 選 XAUUSD → M1 → 匯出，
# 或在圖表上「檔案 → 另存為」。欄位格式會自動辨識。
# =============================================================================
import argparse
import contextlib
import csv
import io
import json
import os
import sys
import types
from datetime import datetime, timezone


# =============================================================================
# 1. 讓 main.py 能在沒有 GCP 套件的環境下被 import
# =============================================================================
def install_stubs():
    """注入最小替身模組，這樣回測不需要安裝 google-cloud / flask / requests。"""
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module("functions_framework", http=lambda fn: fn)

    class _Response(dict):
        def __init__(self, payload):
            super().__init__(_json=payload)
            self.headers = {}

        def get_json(self, silent=False):
            return self["_json"]

    module("flask", jsonify=lambda *a, **k: _Response(a[0] if a else k),
           redirect=lambda url: ("redirect", url))

    class _Timeout(Exception):
        pass

    class _RequestException(Exception):
        pass

    module("requests", Timeout=_Timeout, RequestException=_RequestException,
           get=lambda *a, **k: (_ for _ in ()).throw(_RequestException("offline")),
           post=lambda *a, **k: (_ for _ in ()).throw(_RequestException("offline")))

    google = sys.modules.get("google") or module("google")
    google.__path__ = []
    cloud = module("google.cloud")
    cloud.__path__ = []
    google.cloud = cloud
    api_core = module("google.api_core")
    api_core.__path__ = []
    google.api_core = api_core

    class NotFound(Exception):
        pass

    class PreconditionFailed(Exception):
        pass

    exceptions = module("google.api_core.exceptions", NotFound=NotFound, PreconditionFailed=PreconditionFailed)
    api_core.exceptions = exceptions

    class _Client:
        def __init__(self, *a, **k):
            pass

        def bucket(self, name):
            raise RuntimeError("回測不應該碰到真的 GCS")

    storage = module("google.cloud.storage", Client=_Client)
    cloud.storage = storage

    class _GenAIClient:
        def __init__(self, *a, **k):
            self.models = None

    genai = module("google.genai", Client=_GenAIClient)
    genai.__path__ = []
    google.genai = genai
    module("google.genai.types",
           ThinkingConfig=lambda **k: None,
           GenerateContentConfig=lambda **k: None)


def install_memory_bucket(m):
    """把 main.py 的 GCS 換成純記憶體，回測不會寫到雲端。"""
    store = {}

    class Blob:
        def __init__(self, name, generation=None):
            self.name, self.generation = name, generation

        def download_as_bytes(self, if_generation_match=None):
            generation, text = store[self.name]
            if if_generation_match is not None and if_generation_match != generation:
                raise m.PreconditionFailed("generation mismatch")
            return text.encode("utf-8")

        def upload_from_string(self, text, if_generation_match=None, content_type=None):
            current = store.get(self.name, (0, None))[0]
            if if_generation_match is not None and if_generation_match != current:
                raise m.PreconditionFailed("generation mismatch")
            store[self.name] = (current + 1, text)

    class Bucket:
        def get_blob(self, name):
            return Blob(name, store[name][0]) if name in store else None

        def blob(self, name):
            return Blob(name)

    m._bucket = lambda: Bucket()
    return store


def load_main(quiet=True):
    install_stubs()
    os.environ.setdefault("AI_REVIEW_ENABLED", "0")        # 回測無法重播 LLM
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer if quiet else sys.stdout):
        import main as m
    return m


# =============================================================================
# 2. 讀 CSV / JSON
# =============================================================================
def parse_timestamp(date_text, time_text):
    text = f"{date_text.strip()} {time_text.strip()}".strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y%m%d %H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    raise ValueError(f"無法解析時間：{text!r}")


def load_bars(path, broker_offset_hours=0.0):
    """回傳依時間排序的 [{time, open, high, low, close}]；time 已轉成真實 UTC。"""
    raw = open(path, encoding="utf-8-sig", errors="replace").read().strip()
    bars = []

    if raw.startswith("["):                                  # v12 的 m1_history JSON
        for row in json.loads(raw):
            bars.append({k: float(row[k]) for k in ("open", "high", "low", "close")} |
                        {"time": int(row["time"])})
    else:
        sample = raw[:4000]
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
        rows = [r for r in reader if r and any(c.strip() for c in r)]
        header, start = None, 0
        first = [c.strip().lower().strip("<>") for c in rows[0]]
        if any(c in ("open", "date", "time", "datetime") for c in first):
            header, start = first, 1

        def column(names, default=None):
            if header:
                for name in names:
                    if name in header:
                        return header.index(name)
            return default

        i_date = column(["date", "datetime"], 0)
        i_time = column(["time"], 1)
        # 沒有 header 時，MT5 的預設欄序是 date,time,open,high,low,close,...
        i_open = column(["open"], 2)
        i_high = column(["high"], 3)
        i_low = column(["low"], 4)
        i_close = column(["close"], 5)
        same_cell = (i_date == i_time) or (header and "datetime" in header)

        for row in rows[start:]:
            try:
                if same_cell:
                    stamp = parse_timestamp(row[i_date], "")
                else:
                    stamp = parse_timestamp(row[i_date], row[i_time])
                bars.append({"time": int(stamp),
                             "open": float(row[i_open]), "high": float(row[i_high]),
                             "low": float(row[i_low]), "close": float(row[i_close])})
            except (ValueError, IndexError):
                continue

    if not bars:
        raise SystemExit(f"❌ {path} 裡找不到可用的 K 線資料")

    offset = int(broker_offset_hours * 3600)
    for bar in bars:
        bar["time"] -= offset
    bars.sort(key=lambda b: b["time"])
    deduped = [bars[0]]
    for bar in bars[1:]:
        if bar["time"] != deduped[-1]["time"]:
            deduped.append(bar)
    return deduped


# =============================================================================
# 3. 券商端模擬（實盤由 webhooktrade / MT5 負責，main.py 看不到）
# =============================================================================
def extract_labels(text):
    """從 main.py 的決策訊息取出 [方括號] 裡的關卡名稱，例如 [首單過濾]。"""
    labels = []
    for line in text.splitlines():
        start, end = line.find("["), line.find("]")
        if 0 <= start < end:
            labels.append(line[start + 1:end])
    return labels


class Position:
    __slots__ = ("direction", "lots", "entry", "sl", "tp", "best", "opened_at", "be_done")

    def __init__(self, direction, lots, entry, sl_distance, tp_distance):
        self.direction, self.lots, self.entry = direction, lots, entry
        self.sl = entry - sl_distance if direction == "UP" else entry + sl_distance
        self.tp = entry + tp_distance if direction == "UP" else entry - tp_distance
        self.best = entry
        self.opened_at = None
        self.be_done = False

    def profit_at(self, price):
        move = price - self.entry if self.direction == "UP" else self.entry - price
        return move * self.lots * 100.0          # XAUUSD：1 手 = 100 盎司


class Broker:
    """固定止損止盈 + 可選的移動止損與保本。單根同時觸及時預設算止損。"""

    def __init__(self, spread=0.30, trailing=False, breakeven=False, optimistic=False,
                 ts_activation=2.0, ts_distance=4.0, be_trigger=3.0):
        self.spread, self.trailing, self.breakeven = spread, trailing, breakeven
        self.optimistic = optimistic
        self.ts_activation, self.ts_distance, self.be_trigger = ts_activation, ts_distance, be_trigger
        self.positions, self.closed = [], []

    def open(self, direction, lots, price, sl_distance, tp_distance, when):
        fill = price + self.spread / 2 if direction == "UP" else price - self.spread / 2
        position = Position(direction, lots, fill, sl_distance, tp_distance)
        position.opened_at = when
        self.positions.append(position)
        return position

    def gross(self):
        return round(sum(p.lots for p in self.positions), 2)

    def direction(self):
        return self.positions[0].direction if self.positions else None

    def floating(self, price):
        return sum(p.profit_at(price) for p in self.positions)

    def step(self, bar):
        """走完一根 M1：更新移動止損／保本，然後檢查出場。回傳本根已實現損益 (USD)。"""
        realised, survivors = 0.0, []
        for position in self.positions:
            up = position.direction == "UP"
            position.best = max(position.best, bar["high"]) if up else min(position.best, bar["low"])

            if self.breakeven and not position.be_done:
                reached = (position.best - position.entry) if up else (position.entry - position.best)
                if reached >= self.be_trigger:
                    position.sl = max(position.sl, position.entry) if up else min(position.sl, position.entry)
                    position.be_done = True
            if self.trailing:
                reached = (position.best - position.entry) if up else (position.entry - position.best)
                if reached >= self.ts_activation:
                    trail = position.best - self.ts_distance if up else position.best + self.ts_distance
                    position.sl = max(position.sl, trail) if up else min(position.sl, trail)

            hit_sl = bar["low"] <= position.sl if up else bar["high"] >= position.sl
            hit_tp = bar["high"] >= position.tp if up else bar["low"] <= position.tp
            exit_price, reason = None, None
            if hit_sl and hit_tp:
                exit_price, reason = ((position.tp, "止盈") if self.optimistic else (position.sl, "止損"))
            elif hit_sl:
                exit_price, reason = position.sl, ("保本／移動止損" if position.be_done or self.trailing else "止損")
            elif hit_tp:
                exit_price, reason = position.tp, "止盈"

            if exit_price is None:
                survivors.append(position)
                continue
            profit = position.profit_at(exit_price)
            realised += profit
            self.closed.append({
                "direction": position.direction, "lots": position.lots,
                "entry": round(position.entry, 2), "exit": round(exit_price, 2),
                "reason": reason, "profit_usd": round(profit, 2),
                "opened_at": position.opened_at, "closed_at": bar["time"],
                "minutes": int((bar["time"] - position.opened_at) / 60),
            })
        self.positions = survivors
        return realised


# =============================================================================
# 4. 回測主體
# =============================================================================
class Backtest:
    def __init__(self, m, bars, args):
        self.m, self.bars, self.args = m, bars, args
        self.store = install_memory_bucket(m)
        self.broker = Broker(spread=args.spread, trailing=args.trailing, breakeven=args.breakeven,
                             optimistic=args.optimistic,
                             ts_activation=(args.ts_activation if args.ts_activation is not None
                                            else m.to_float(m.TS_ACTIVATION_PRICE, 2.0)),
                             ts_distance=(args.ts_distance if args.ts_distance is not None
                                          else m.to_float(m.TS_DISTANCE_PRICE, 4.0)),
                             be_trigger=(args.be_trigger if args.be_trigger is not None
                                         else m.to_float(m.BREAKEVEN_DISTANCE_PRICE, 3.0)))
        self.equity = args.equity
        self.m15 = []
        self.stats = {"bars": 0, "skipped_closed": 0, "resets": 0, "open_bars": 0,
                      "judged": 0, "entries": 0, "verdicts": {}, "blocked": {},
                      "peak_lots": 0.0, "max_dd_pct": 0.0, "min_equity": None}
        self.peak_mtm = args.equity

    # ---- M15 聚合與 ATR（實盤由 EA 提供，這裡自己算） ----
    def push_m15(self, bar):
        key = bar["time"] // 900
        if self.m15 and self.m15[-1]["time"] == key * 900:
            last = self.m15[-1]
            last["high"] = max(last["high"], bar["high"])
            last["low"] = min(last["low"], bar["low"])
            last["close"] = bar["close"]
        else:
            self.m15.append({"time": key * 900, "open": bar["open"], "high": bar["high"],
                             "low": bar["low"], "close": bar["close"]})
        self.m15 = self.m15[-60:]

    def atr_m15(self, period=14):
        if len(self.m15) < 2:
            return None
        trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
               for p, c in zip(self.m15, self.m15[1:])][-period:]
        return round(sum(trs) / len(trs), 2) if trs else None

    def run(self, noise_k, bypass, target_rrr=None, sl_atr_mult=None):
        m = self.m
        m.NOISE_K = noise_k
        self.store.clear()
        m.write_gate_bypass(frozenset(bypass), "backtest")
        if target_rrr is not None or sl_atr_mult is not None:
            params = m.default_order_params()
            if target_rrr is not None:
                params["target_rrr"] = target_rrr
            if sl_atr_mult is not None:
                params["sl_atr_mult"] = sl_atr_mult
            m.write_order_params(params)
        clock = {"t": 0.0}
        m.now_ts = lambda: clock["t"]
        history, equity_curve = [], []

        for bar in self.bars:
            clock["t"] = float(bar["time"])
            self.stats["bars"] += 1

            # (1) 出場先結算（券商端）
            realised = self.broker.step(bar)
            if realised:
                self.equity += realised / m.FX_TO_USD.get(self.args.currency.upper(), 1.0)
                with contextlib.suppress(Exception):
                    m.update_pyramid_state(last_close_ts=bar["time"])

            # (1b) 逐根計算「權益＋浮動」的回撤（實盤的真實痛感）
            rate = m.FX_TO_USD.get(self.args.currency.upper(), 1.0)
            mtm = self.equity + self.broker.floating(bar["close"]) / rate
            self.peak_mtm = max(self.peak_mtm, mtm)
            if self.peak_mtm > 0:
                drawdown = (self.peak_mtm - mtm) / self.peak_mtm * 100.0
                self.stats["max_dd_pct"] = max(self.stats["max_dd_pct"], drawdown)
            self.stats["min_equity"] = mtm if self.stats["min_equity"] is None else min(self.stats["min_equity"], mtm)
            self.stats["peak_lots"] = max(self.stats["peak_lots"], self.broker.gross())

            # (2) 休市時段：實盤會整根略過
            if not self.args.ignore_hours and not m.GoldIndicatorSession.is_gold_market_open(bar["time"]):
                self.stats["skipped_closed"] += 1
                continue

            # (3) M1 歷史（含缺口重置，與 main.py 同一套規則）
            if history and bar["time"] - history[-1]["time"] > m.M1_GAP_RESET_SEC:
                history = []
                self.stats["resets"] += 1
            history.append({k: bar[k] for k in ("time", "open", "high", "low", "close")})
            history = history[-m.M1_HISTORY_MAX:]
            self.push_m15(bar)                      # EA 每根心跳都會送 m15_ohlc

            # (4) 雷達判定 → 電閘狀態機
            verdict = m.GoldIndicatorSession.compute_verdict(history)
            self.stats["verdicts"][verdict["regime"]] = self.stats["verdicts"].get(verdict["regime"], 0) + 1
            if verdict["regime"] not in (m.REGIME_NODATA,):
                self.stats["judged"] += 1
            state = m.read_gate_state()
            regime, direction, armed, _ = m.next_trend_state(state, verdict, "setup_trigger" in bypass)
            state.update(regime=regime, dir=direction, armed=armed, news_lock=False)
            m.gcs_write_text(m.GATE_STATE_FILE, json.dumps(state, ensure_ascii=False))
            if m.gate_status(state) != "OPEN":
                continue
            self.stats["open_bars"] += 1

            # (5) 進場判斷：完全交給 main.py 的引擎
            atr = self.atr_m15()
            levels = m.mtf_levels_session.compute_levels(self.m15)
            if atr is None or levels.get("status") != "ready":
                self.stats["blocked"]["結構未就緒"] = self.stats["blocked"].get("結構未就緒", 0) + 1
                continue
            gross = self.broker.gross()
            side_dir = self.broker.direction()
            payload = {
                "equity": self.equity, "currency": self.args.currency,
                "buy_lots": gross if side_dir == "UP" else 0.0,
                "sell_lots": gross if side_dir == "DOWN" else 0.0,
                "m15_ohlc": {**self.m15[-1], "atr_m15": atr},
            }
            rsi = m.wilder_rsi_last([b["close"] for b in history])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                candidate = m.pure_gcp_session.evaluate_and_trigger(
                    payload, state, levels, history[-1], rsi, now=bar["time"], bypass=frozenset(bypass))
            if not candidate:
                for label in extract_labels(buffer.getvalue()):      # 記下是哪一關擋的
                    self.stats["blocked"][label] = self.stats["blocked"].get(label, 0) + 1
                continue

            # (6) 成交（實盤是 webhooktrade）
            params = m.read_order_params()[0]
            sl = candidate["sl_distance"]
            self.broker.open(candidate["direction"], params["size"], bar["close"],
                             sl, round(sl * params["target_rrr"], 2), bar["time"])
            self.stats["entries"] += 1
            with contextlib.suppress(Exception):
                m.update_pyramid_state(last_entry_price=bar["close"], last_entry_dir=candidate["direction"],
                                       last_order_ts=bar["time"], exposure_at_order=gross)
            equity_curve.append((bar["time"], round(self.equity, 2)))

        # 收盤時仍持倉 → 以最後收盤價估值
        last_price = self.bars[-1]["close"]
        floating = self.broker.floating(last_price)
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%M")
        still_open = [f"{p.direction} {p.lots:.2f} 手 @ {p.entry:.2f}（{fmt(p.opened_at)} UTC 進場，"
                      f"止損 {p.sl:.2f} / 止盈 {p.tp:.2f}，現價 {last_price:.2f}）"
                      for p in self.broker.positions]
        return {"closed": self.broker.closed, "floating_usd": round(floating, 2),
                "open_positions": len(self.broker.positions), "equity": round(self.equity, 2),
                "curve": equity_curve, "still_open": still_open, **self.stats}


# =============================================================================
# 5. 報表
# =============================================================================
def summarise(result, args):
    trades = result["closed"]
    wins = [t for t in trades if t["profit_usd"] > 0]
    losses = [t for t in trades if t["profit_usd"] < 0]
    won = sum(t["profit_usd"] for t in wins)
    lost = abs(sum(t["profit_usd"] for t in losses))
    gross_usd = sum(t["profit_usd"] for t in trades)
    return {
        "開閘": result["open_bars"],
        "交易": len(trades),
        "勝率": f"{len(wins) / len(trades) * 100:.0f}%" if trades else "—",
        "獲利因子": round(won / lost, 2) if lost else "—",
        "已實現USD": round(gross_usd, 2),
        "報酬%": round((result["equity"] - args.equity) / args.equity * 100, 1),
        "最大回撤%": round(result["max_dd_pct"], 1),
        "最大持倉": round(result["peak_lots"], 2),
        "最大單筆虧損": round(min([t["profit_usd"] for t in trades], default=0), 2),
        f"期末{args.currency}": round(result["equity"], 0),
    }


def print_table(rows, headers):
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def main():
    parser = argparse.ArgumentParser(description="智能諸葛亮 v12 離線回測（MT5 M1 CSV）")
    parser.add_argument("csv", help="MT5 匯出的 M1 CSV，或 v12 的 m1_history JSON")
    parser.add_argument("--broker-offset", type=float, default=0.0,
                        help="券商伺服器時間與 UTC 的時差（小時）。MT5 常見為 2 或 3")
    parser.add_argument("--mode", default="strict",
                        choices=["strict", "relaxed", "aggressive", "all-off"], help="關卡模式")
    parser.add_argument("--modes", help="一次比較多個模式，逗號分隔")
    parser.add_argument("--sweep-k", help="掃描 NOISE_K，例如 0.6,0.8,1.0,1.2,1.5")
    parser.add_argument("--noise-k", type=float, help="單次回測用的 NOISE_K（預設用 main.py 的值）")
    parser.add_argument("--equity", type=float, default=78000.0, help="起始權益")
    parser.add_argument("--currency", default="HKD", help="帳戶貨幣（USD / HKD）")
    parser.add_argument("--spread", type=float, default=0.30, help="點差（美元），進場時吃掉")
    parser.add_argument("--trailing", action="store_true", help="模擬移動止損（語義未確認，預設關）")
    parser.add_argument("--breakeven", action="store_true", help="模擬保本（語義未確認，預設關）")
    parser.add_argument("--optimistic", action="store_true", help="單根同時觸及止損止盈時算止盈")
    parser.add_argument("--ts-activation", type=float, help="覆寫移動止損啟動距離（美元獲利）")
    parser.add_argument("--ts-distance", type=float, help="覆寫移動止損跟隨距離（美元）")
    parser.add_argument("--be-trigger", type=float, help="覆寫保本啟動距離（美元獲利）")
    parser.add_argument("--ignore-hours", action="store_true", help="忽略黃金休市時段")
    parser.add_argument("--trades", help="把每筆交易寫成 CSV")
    parser.add_argument("--by-month", action="store_true", help="逐月拆解（檢查不同市況下是否穩定）")
    parser.add_argument("--target-rrr", type=float, help="覆寫止盈倍數（預設讀 main.py 的 TARGET_RRR）")
    parser.add_argument("--sl-atr-mult", type=float, help="覆寫止損的 ATR 倍數")
    parser.add_argument("--sweep-rrr", help="掃描止盈倍數，例如 1.0,1.5,2.0,3.0")
    args = parser.parse_args()

    m = load_main()
    bars = load_bars(args.csv, args.broker_offset)
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
    span_days = (bars[-1]["time"] - bars[0]["time"]) / 86400
    gaps = sum(1 for a, b in zip(bars, bars[1:]) if b["time"] - a["time"] > 60)
    print("=" * 78)
    print(f"資料：{args.csv}")
    print(f"  {len(bars)} 根 M1｜{fmt(bars[0]['time'])} → {fmt(bars[-1]['time'])} UTC（{span_days:.1f} 天）"
          f"｜缺口 {gaps} 處")
    if args.broker_offset:
        print(f"  已扣掉券商時差 {args.broker_offset:+.1f} 小時")
    if span_days < 5:
        print("  ⚠️ 資料不到 5 天，結果只能當作 sanity check，不足以調參數")
    trail_note = (f"移動止損 開（啟動 {args.ts_activation if args.ts_activation is not None else m.TS_ACTIVATION_PRICE}"
                  f" / 跟隨 {args.ts_distance if args.ts_distance is not None else m.TS_DISTANCE_PRICE}）"
                  if args.trailing else "移動止損 關")
    print(f"  設定：點差 {args.spread}、{trail_note}、"
          f"保本 {'開' if args.breakeven else '關'}、休市 {'忽略' if args.ignore_hours else '照實盤略過'}")
    print("=" * 78)

    modes = [x.strip() for x in args.modes.split(",")] if args.modes else [args.mode]
    ks = [float(x) for x in args.sweep_k.split(",")] if args.sweep_k else [args.noise_k or m.NOISE_K]
    mode_bypass = {"strict": [], "relaxed": sorted(m.GATE_MODES["relaxed"][1]),
                   "aggressive": sorted(m.GATE_MODES["aggressive"][1]), "all-off": m.GATE_SWITCH_KEYS}

    rrrs = [float(x) for x in args.sweep_rrr.split(",")] if args.sweep_rrr else [args.target_rrr]
    rows, all_trades = [], []
    for mode in modes:
        for k in ks:
            for rrr in rrrs:
                result = Backtest(m, bars, args).run(k, mode_bypass[mode], rrr, args.sl_atr_mult)
                summary = summarise(result, args)
                label = f"{mode}" + (f" TP={rrr:g}R" if rrr else "")
                rows.append([label, f"{k:.2f}"] + [summary[h] for h in summary])
                for trade in result["closed"]:
                    all_trades.append({"mode": label, "noise_k": k, **trade})
            if len(modes) * len(ks) * len(rrrs) == 1:
                print()
                for key, value in summary.items():
                    print(f"  {key:<16}{value}")
                print(f"  {'判定分布':<16}{result['verdicts']}")
                print(f"  {'休市略過':<16}{result['skipped_closed']} 根｜歷史重置 {result['resets']} 次")
                if result["blocked"]:
                    print(f"  {'開閘後被攔截':<16}")
                    for label, count in sorted(result["blocked"].items(), key=lambda kv: -kv[1]):
                        print(f"      {label:<14}{count} 次")
                for position in result["still_open"]:
                    print(f"  {'未平倉':<16}{position}")

    if len(rows) > 1:
        headers = ["模式", "K"] + list(summarise(result, args).keys())
        print()
        print_table(rows, headers)

    if args.by_month and all_trades:
        from collections import defaultdict
        buckets = defaultdict(list)
        for trade in all_trades:
            key = (trade["mode"], trade["noise_k"],
                   datetime.fromtimestamp(trade["closed_at"], timezone.utc).strftime("%Y-%m"))
            buckets[key].append(trade)
        print()
        print("逐月拆解（已實現損益，USD）")
        monthly = []
        for (mode, k, month), group in sorted(buckets.items()):
            wins = [t for t in group if t["profit_usd"] > 0]
            lost = abs(sum(t["profit_usd"] for t in group if t["profit_usd"] < 0))
            won = sum(t["profit_usd"] for t in wins)
            monthly.append([f"{mode} K={k}", month, len(group),
                            f"{len(wins) / len(group) * 100:.0f}%",
                            round(won / lost, 2) if lost else "—",
                            round(sum(t["profit_usd"] for t in group), 2)])
        print_table(monthly, ["設定", "月份", "交易", "勝率", "獲利因子", "損益USD"])
        print()
        by_config = defaultdict(list)
        for row in monthly:
            by_config[row[0]].append(row[5])
        print("各設定的月度穩定度")
        rows = [[config, len(values), sum(1 for v in values if v > 0),
                 round(sum(values), 2), round(min(values), 2), round(max(values), 2)]
                for config, values in sorted(by_config.items())]
        print_table(rows, ["設定", "月數", "獲利月數", "合計USD", "最差月", "最好月"])

    if args.trades and all_trades:
        with open(args.trades, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_trades[0].keys()))
            writer.writeheader()
            for trade in all_trades:
                writer.writerow({**trade,
                                 "opened_at": fmt(trade["opened_at"]), "closed_at": fmt(trade["closed_at"])})
        print(f"\n已寫出 {len(all_trades)} 筆交易 → {args.trades}")

    print("=" * 78)
    print("回測沒有涵蓋的部分（實盤仍會影響結果）：")
    print("  • 新聞風控：無法重播歷史日曆，回測一律當作沒有事件")
    print("  • AI 覆核：無法重播 LLM 回應，回測一律放行")
    print("  • 移動止損／保本的實際語義由 webhooktrade 決定，這裡是假設值")
    print("  • 滑價、隔夜利息、成交延遲、部分成交都沒有模擬")
    print("=" * 78)


if __name__ == "__main__":
    main()
