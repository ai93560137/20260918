"""用假券商 + 假 AI 測試風控。執行：python -m pytest tests -q"""
import sys
from dataclasses import replace
from datetime import datetime, date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config  # noqa: E402
from rules import HKT, session_status, pick_front_month, trading_day_key, validate_decision  # noqa: E402
from trader import Trader  # noqa: E402


class FakeBroker:
    def __init__(self):
        self.price = 25000.0
        self.pos = {}          # code -> qty
        self.cost = {}
        self.cash = 200000.0
        self.orders = []
        self.clock = None
        self.fill = True

    def equity(self):
        unreal = sum((self.price - self.cost[c]) * q * 10 for c, q in self.pos.items())
        return self.cash + unreal

    def positions(self, product):
        return {c: (q, self.cost[c]) for c, q in self.pos.items() if q}

    def list_contracts(self, product):
        return [("HK.MHI2610", date(2026, 10, 29)), ("HK.MHI2611", date(2026, 11, 27)),
                ("HK.HSI2610", date(2026, 10, 29))]

    def snapshot(self, code):
        return {"last": self.price, "bid": self.price - 1, "ask": self.price + 1,
                "update_time": self.clock(), "volume": 1}

    def klines(self, code, ktype, days_back, max_count):
        return [{"t": "x", "o": self.price, "h": self.price + 20, "l": self.price - 20,
                 "c": self.price, "v": 100}] * 20

    def market_order(self, code, side, qty, slippage, timeout=15):
        if not self.fill:
            return None
        px = self.price + side  # 1 點滑點
        self.orders.append((code, side, qty, px))
        q0 = self.pos.get(code, 0)
        if q0 == 0:
            self.cost[code] = px
        else:
            closed = min(abs(q0), qty)
            self.cash += (px - self.cost[code]) * closed * (1 if q0 > 0 else -1) * 10
        self.pos[code] = q0 + side * qty
        return px


class FakeBrain:
    def __init__(self):
        self.next = {"action": "HOLD", "confidence": 0.5, "reason": "等"}
        self.calls = 0

    def decide(self, ctx):
        self.calls += 1
        self.ctx = ctx
        d, self.next = self.next, {"action": "HOLD", "confidence": 0.5, "reason": "等"}
        return d


@pytest.fixture
def env(tmp_path):
    cfg = replace(Config(), log_dir=tmp_path / "logs", state_file=tmp_path / "state.json",
                  stop_file=tmp_path / "STOP", pause_file=tmp_path / "PAUSE")
    t = {"now": datetime(2026, 10, 16, 10, 0, 5, tzinfo=HKT)}  # 週五日市
    b, ai = FakeBroker(), FakeBrain()
    b.clock = lambda: t["now"]
    tr = Trader(cfg, b, ai, lambda: t["now"])
    return cfg, t, b, ai, tr


def advance(t, minutes=0, seconds=0):
    t["now"] = t["now"] + timedelta(minutes=minutes, seconds=seconds)


def test_sessions():
    f = lambda h, m, d=16: session_status(datetime(2026, 10, d, h, m, tzinfo=HKT))[0]
    assert f(9, 20) == "DAY_AM" and f(12, 30) is None and f(14, 0) == "DAY_PM"
    assert f(17, 0) is None and f(20, 0) == "NIGHT" and f(2, 30, 17) == "NIGHT"  # 週六凌晨
    assert f(4, 0, 17) is None and f(10, 0, 18) is None and f(1, 0, 19) is None  # 週日、週一凌晨
    _, left = session_status(datetime(2026, 10, 17, 2, 50, tzinfo=HKT))
    assert abs(left - 10) < 0.01


def test_front_month_rolls_on_last_trading_day():
    cs = [("HK.MHI2610", date(2026, 10, 29)), ("HK.MHI2611", date(2026, 11, 27))]
    assert pick_front_month(cs, "MHI", date(2026, 10, 28)) == "HK.MHI2610"
    assert pick_front_month(cs, "MHI", date(2026, 10, 29)) == "HK.MHI2611"


def test_day_key_rolls_at_17():
    assert trading_day_key(datetime(2026, 10, 16, 16, 59, tzinfo=HKT)) == "2026-10-16"
    assert trading_day_key(datetime(2026, 10, 16, 17, 15, tzinfo=HKT)) == "2026-10-17"


def test_open_without_stop_rejected():
    cfg = Config()
    a, *_ , why = validate_decision({"action": "OPEN_LONG"}, position=0, entry=None, last=25000,
                                    cfg=cfg, remaining_loss=10000, can_open=True, trades_today=0)
    assert a == "HOLD" and "止蝕" in why


def test_stop_clamped_to_max():
    cfg = Config()
    a, stop, _, why = validate_decision({"action": "OPEN_SHORT", "stop_price": 25600}, position=0,
                                        entry=None, last=25000, cfg=cfg, remaining_loss=10000,
                                        can_open=True, trades_today=0)
    assert a == "OPEN_SHORT" and stop == 25000 + cfg.max_stop_points


def test_open_then_stop_hit(env):
    cfg, t, b, ai, tr = env
    tr.tick()                                  # 10:00:05 決策（HOLD）
    ai.next = {"action": "OPEN_LONG", "stop_price": 24950, "target_price": 25100,
               "confidence": 0.7, "reason": "突破"}
    advance(t, minutes=5)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 1
    assert tr.state["pos"]["stop"] == 25001 - 50
    b.price = 24940
    advance(t, seconds=5)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0 and tr.state["pos"] is None
    closes = [l for l in (cfg.log_dir / "trades.jsonl").read_text("utf-8").splitlines() if "CLOSE" in l]
    assert len(closes) == 1 and "止蝕" in closes[0]


def test_daily_loss_limit_halts_and_blocks(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    ai.next = {"action": "OPEN_SHORT", "stop_price": 25150, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    assert b.pos["HK.MHI2610"] == -1
    b.cash -= 9500                 # 模擬之前已蝕 9,500
    tr.state["pos"]["stop"] = 99999  # 令止蝕唔觸發，專測日蝕上限
    b.price = 25060
    advance(t, seconds=5)
    tr.tick()
    assert tr.state["halted"] and b.pos["HK.MHI2610"] == 0
    calls = ai.calls
    advance(t, minutes=5)
    tr.tick()
    assert ai.calls == calls       # 停機後唔再問 AI


def test_flatten_before_night_close(env):
    cfg, t, b, ai, tr = env
    t["now"] = datetime(2026, 10, 17, 2, 30, 5, tzinfo=HKT)
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 1
    t["now"] = datetime(2026, 10, 17, 2, 51, 0, tzinfo=HKT)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0


def test_no_entry_near_close(env):
    cfg, t, b, ai, tr = env
    t["now"] = datetime(2026, 10, 16, 16, 25, 5, tzinfo=HKT)
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.9, "reason": "x"}
    tr.tick()
    assert not b.pos.get("HK.MHI2610") and ai.ctx["risk"]["new_entries_allowed"] is False


def test_adopt_unknown_position_and_roll(env):
    cfg, t, b, ai, tr = env
    b.pos["HK.MHI2610"], b.cost["HK.MHI2610"] = -1, 25100
    tr.tick()
    assert tr.state["pos"]["stop"] == 25100 + cfg.max_stop_points
    t["now"] = datetime(2026, 10, 29, 9, 30, 5, tzinfo=HKT)   # 最後交易日 → 轉月
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0 and tr.state["contract"] == "HK.MHI2611"


def test_stop_file(env):
    cfg, t, b, ai, tr = env
    b.pos["HK.MHI2610"], b.cost["HK.MHI2610"] = 1, 25000
    cfg.stop_file.write_text("x")
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0 and tr.state["halted"]


def test_order_failure_does_not_create_position(env):
    cfg, t, b, ai, tr = env
    b.fill = False
    ai.next = {"action": "OPEN_LONG", "stop_price": 24950, "confidence": 0.7, "reason": "x"}
    tr.tick()
    assert tr.state.get("pos") is None and tr.state.get("trades_today") == 0


def test_errors_halt(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    b.snapshot = lambda code: (_ for _ in ()).throw(RuntimeError("OpenD 斷線"))
    for _ in range(cfg.max_consecutive_errors):
        tr.tick()
    assert tr.state["halted"]
