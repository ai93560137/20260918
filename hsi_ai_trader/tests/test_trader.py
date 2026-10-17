"""用假券商 + 假 AI 測試風控。執行：python -m pytest tests -q"""
import json
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

    partial = None   # 設數字＝下一張單只成交咁多

    def market_order(self, code, side, qty, slippage, timeout=15):
        if not self.fill:
            return None, 0
        if self.partial is not None:
            qty, self.partial = min(qty, self.partial), None
        px = self.price + side  # 1 點滑點
        self.orders.append((code, side, qty, px))
        q0 = self.pos.get(code, 0)
        if q0 == 0:
            self.cost[code] = px
        else:
            closed = min(abs(q0), qty)
            self.cash += (px - self.cost[code]) * closed * (1 if q0 > 0 else -1) * 10
        self.pos[code] = q0 + side * qty
        return px, qty


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
                  stop_file=tmp_path / "STOP", pause_file=tmp_path / "PAUSE",
                  heartbeat_file=tmp_path / "heartbeat",
                  product="MHI", point_value=10, fee_per_side_hkd=0)   # 測試用細期數字，邏輯同大期一樣
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
    cfg = replace(Config(), max_stop_points=150)
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
    b.cash -= 50000                # 戶口其他陣蝕錢：唔應該計入龍飛陣日蝕
    advance(t, seconds=5)
    tr.tick()
    assert not tr.state.get("halted") and b.pos["HK.MHI2610"] == -1
    tr.state["today_trades"].append({"pnl_hkd": -9500})   # 模擬之前自己已蝕 9,500
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
    tr.cfg = cfg = replace(cfg, flatten_before_night_close=True)
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


def test_foreign_position_untouched_and_blocks_entries(env):
    """同戶口嘅人手／其他陣倉：唔接手、唔設止蝕、唔平、唔減；即月有外來倉就停開新倉。"""
    cfg, t, b, ai, tr = env
    b.pos["HK.MHI2610"], b.cost["HK.MHI2610"] = -1, 25100      # 外來即月倉
    b.pos["HK.MHI2611"], b.cost["HK.MHI2611"] = 1, 25100       # 外來下月倉
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.9, "reason": "x"}
    tr.tick()
    assert tr.state.get("pos") is None and tr.state["foreign_qty"] == -1
    assert b.orders == [] and ai.ctx["risk"]["new_entries_allowed"] is False
    b.price = 30000                                            # 外來倉大蝕都唔郁
    advance(t, minutes=5)
    tr.tick()
    assert b.orders == [] and not tr.state.get("halted")
    tr._flatten_all("測試")
    assert b.orders == []


def test_roll_closes_only_own_position(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    b.pos["HK.MHI2611"], b.cost["HK.MHI2611"] = -2, 25000      # 外來下月倉
    t["now"] = datetime(2026, 10, 29, 9, 30, 5, tzinfo=HKT)   # 最後交易日 → 轉月
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0 and b.pos["HK.MHI2611"] == -2
    assert tr.state["contract"] == "HK.MHI2611" and tr.state["pos"] is None


def test_stop_file(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    b.pos["HK.MHI2611"], b.cost["HK.MHI2611"] = 3, 25000      # 外來倉：STOP 都唔掂
    cfg.stop_file.write_text("x")
    advance(t, seconds=5)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 0 and b.pos["HK.MHI2611"] == 3 and tr.state["halted"]


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


def test_heartbeat_written_every_tick(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    hb = json.loads(cfg.heartbeat_file.read_text(encoding="utf-8"))
    assert hb["utc"].endswith("+00:00") and hb["errors"] == 0 and hb["halted"] is False
    assert hb["trd_env"] == cfg.trd_env


def test_cancelled_limits_default_off(env):
    """使用者 2026-10-16 取消：每張止蝕距離、每日次數、夜市收市前平倉。日蝕上限照保留。"""
    cfg, t, b, ai, tr = env
    a, stop, _, why = validate_decision({"action": "OPEN_SHORT", "stop_price": 25600}, position=0,
                                        entry=None, last=25000, cfg=cfg, remaining_loss=10000,
                                        can_open=True, trades_today=99)
    assert a == "OPEN_SHORT" and stop == 25600 and why is None
    a, *_ = validate_decision({"action": "OPEN_SHORT", "stop_price": 26100}, position=0,
                              entry=None, last=25000, cfg=cfg, remaining_loss=10000,
                              can_open=True, trades_today=0)
    assert a == "HOLD"                          # 1,100 點 × HK$10 > 日蝕剩餘額度
    t["now"] = datetime(2026, 10, 17, 2, 30, 5, tzinfo=HKT)
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    t["now"] = datetime(2026, 10, 17, 2, 51, 0, tzinfo=HKT)
    tr.tick()
    assert b.pos["HK.MHI2610"] == 1             # 唔再 02:50 強制平倉


def test_lessons_loaded_into_system(tmp_path):
    from brain import load_lessons, build_system, SYSTEM
    assert load_lessons(tmp_path / "none.md") == ("", None)
    f = tmp_path / "L.md"
    f.write_text("唔好追高\n", encoding="utf-8")
    text, ver = load_lessons(f)
    assert text == "唔好追高" and len(ver) == 8
    assert build_system(text).endswith("唔好追高") and "{product_line}" not in build_system("")
    assert "Micro E-mini S&P" in build_system("", replace(Config(), product="MES"))
    assert "Hang Seng Index Futures (HKFE) (HSI" in build_system("", Config())


def test_brain_request_shape_and_usage():
    """Sonnet 5.5 拒絕強制 tool_choice；system 要有 1h 快取；usage 要記快取命中。"""
    from types import SimpleNamespace as NS
    from brain import ClaudeBrain
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            return NS(stop_reason="tool_use",
                      usage=NS(input_tokens=900, output_tokens=50, cache_read_input_tokens=800,
                               cache_creation_input_tokens=0),
                      content=[NS(type="tool_use", name="decide",
                                  input={"action": "HOLD", "stop_price": None, "target_price": None,
                                         "confidence": 0.5, "reason": "等"})])

    b = ClaudeBrain.__new__(ClaudeBrain)
    b.cfg, b.client = Config(), NS(messages=FakeMessages())
    d = b.decide({"b": 1, "a": 2})
    assert sent["tool_choice"]["type"] == "auto"
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert sent["tools"][0]["strict"] is True
    assert '{"a":2,"b":1}' in sent["messages"][0]["content"]
    assert d["action"] == "HOLD" and d["_usage"]["cache_read"] == 800


def test_push_packet_has_no_equity_and_reads_logs(env, monkeypatch):
    import push
    cfg, t, b, ai, tr = env
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24900, "confidence": 0.7, "reason": "突破"}
    advance(t, minutes=5)
    tr.tick()
    pkt = push.build_packet(cfg, tr.state, "tok")
    assert pkt["action"] == "longfei_push" and "status" not in pkt
    assert pkt["state"]["pos"]["side"] == 1 and "equity" not in json.dumps(pkt["state"])
    assert [x["type"] for x in pkt["trades"]] == ["OPEN"] and pkt["decisions"][-1]["final"] == "OPEN_LONG"
    monkeypatch.delenv("ZHUGE_GCP_URL", raising=False)
    assert push.push(cfg, tr.state) is False          # 冇設定就唔推


def test_us_session_and_day_key():
    from markets import ET, session_status as ss, trading_day_key as tdk, quarterly_contracts
    f = lambda y, mo, d, h, mi: ss(datetime(y, mo, d, h, mi, tzinfo=ET), "US")[0]
    assert f(2026, 10, 19, 10, 0) == "GLOBEX"           # 週一 10:00 美東
    assert f(2026, 10, 19, 17, 30) is None              # 每日維護 17:00–18:00
    assert f(2026, 10, 19, 18, 30) == "GLOBEX"
    assert f(2026, 10, 17, 12, 0) is None               # 週六
    assert f(2026, 10, 18, 17, 0) is None and f(2026, 10, 18, 18, 5) == "GLOBEX"   # 週日 18:00 開
    assert f(2026, 10, 23, 17, 5) is None               # 週五收市
    _, left = ss(datetime(2026, 10, 19, 16, 50, tzinfo=ET), "US")
    assert abs(left - 10) < 0.01
    _, left = ss(datetime(2026, 10, 19, 18, 0, tzinfo=ET), "US")
    assert abs(left - 23 * 60) < 0.01
    assert tdk(datetime(2026, 10, 19, 17, 59, tzinfo=ET), "US") == "2026-10-19"
    assert tdk(datetime(2026, 10, 19, 18, 0, tzinfo=ET), "US") == "2026-10-20"
    qs = quarterly_contracts("MES", "US", date(2026, 10, 16))
    assert qs[0] == ("US.MES2612", date(2026, 12, 18)) and qs[1][0] == "US.MES2703"


def test_us_roll_eight_days_before_expiry_and_config():
    cs = [("US.MES2612", date(2026, 12, 18)), ("US.MES2703", date(2027, 3, 19)), ("HK.HSI2612", date(2026, 12, 30))]
    assert pick_front_month(cs, "MES", date(2026, 12, 9), roll_days=8) == "US.MES2612"
    assert pick_front_month(cs, "MES", date(2026, 12, 10), roll_days=8) == "US.MES2703"
    import importlib, os
    import config as cmod
    os.environ["PRODUCT"] = "MYM"
    try:
        c = importlib.reload(cmod).CFG
        assert (c.product, c.market, c.point_value, c.tick, c.roll_days) == ("MYM", "US", 3.9, 1, 8)
    finally:
        del os.environ["PRODUCT"]
        importlib.reload(cmod)


def test_etf_session_sizing_and_fee():
    from markets import ET, SPECS, session_status as ss, trading_day_key as tdk, order_qty, fee_hkd
    f = lambda h, mi, d=19: ss(datetime(2026, 10, d, h, mi, tzinfo=ET), "US", "stock")[0]
    assert f(3, 59) is None and f(4, 0) == "PRE" and f(9, 30) == "RTH" and f(16, 0) == "POST" and f(20, 0) is None
    assert f(10, 0, 17) is None                                   # 週六
    assert tdk(datetime(2026, 10, 19, 3, 59, tzinfo=ET), "US", "stock") == "2026-10-18"
    assert tdk(datetime(2026, 10, 19, 4, 0, tzinfo=ET), "US", "stock") == "2026-10-19"
    assert order_qty(SPECS["SPY"], 660.0, 1) == 151 and order_qty(SPECS["HSI"], 25000, 1) == 1   # US$100,000 ÷ 660
    assert fee_hkd(SPECS["SPY"], 15, 16) == 32 and fee_hkd(SPECS["HSI"], 1, 40) == 80


def test_etf_risk_scales_with_shares():
    cfg = replace(Config(), product="SPY", point_value=7.8, slippage_points=0.05)
    # 15 股，止蝕 10 美元：(10 + 0.1) × 7.8 × 15 ≈ HK$1,182
    a, stop, _, why = validate_decision({"action": "OPEN_SHORT", "stop_price": 670}, position=0, entry=None,
                                        last=660, cfg=cfg, remaining_loss=1000, can_open=True, trades_today=0, qty=15)
    assert a == "HOLD" and "止蝕風險" in why
    a, *_ = validate_decision({"action": "OPEN_SHORT", "stop_price": 670}, position=0, entry=None,
                              last=660, cfg=cfg, remaining_loss=10000, can_open=True, trades_today=0, qty=15)
    assert a == "OPEN_SHORT"


def test_etf_end_to_end_short(tmp_path):
    from markets import ET
    cfg = replace(Config(), log_dir=tmp_path / "logs", state_file=tmp_path / "s.json", stop_file=tmp_path / "STOP",
                  pause_file=tmp_path / "PAUSE", heartbeat_file=tmp_path / "hb", product="SPY", market="US",
                  kind="stock", point_value=7.8, fee_per_side_hkd=0, slippage_points=0.05, tick=0.01,
                  daily_loss_limit=100_000)
    t = {"now": datetime(2026, 10, 19, 10, 0, 5, tzinfo=ET).astimezone(HKT)}   # 週一 10:00 美東（正常時段）
    b, ai = FakeBroker(), FakeBrain()
    b.price, b.clock = 660.0, (lambda: t["now"])
    tr = Trader(cfg, b, ai, lambda: t["now"])
    tr.tick()
    assert tr.state["contract"] == "US.SPY"
    ai.next = {"action": "OPEN_SHORT", "stop_price": 670, "target_price": None, "confidence": 0.7, "reason": "x"}
    advance(t, minutes=5)
    tr.tick()
    assert b.pos["US.SPY"] == -151 and tr.state["pos"]["qty"] == 151
    b.price = 650.0
    ai.next = {"action": "CLOSE", "confidence": 0.7, "reason": "止賺"}
    advance(t, minutes=5)
    tr.tick()
    assert b.pos["US.SPY"] == 0
    close = [json.loads(l) for l in (cfg.log_dir / "trades.jsonl").read_text("utf-8").splitlines()
             if '"CLOSE"' in l][-1]
    # FakeBroker 每邊 1 點滑價：沽 659、買回 651，每股 +8 × 151 股 × 7.8
    assert close["points"] == 8.0 and close["pnl_hkd_gross"] == round(8 * 151 * 7.8)


def test_etf_stops_keep_cents():
    cfg = replace(Config(), product="SPY", point_value=7.8, slippage_points=0.05, tick=0.01)
    a, stop, tgt, _ = validate_decision({"action": "OPEN_SHORT", "stop_price": 770.47, "target_price": 768.33},
                                        position=0, entry=None, last=770.02, cfg=cfg, remaining_loss=10000,
                                        can_open=True, trades_today=0, qty=12)
    assert (a, stop, tgt) == ("OPEN_SHORT", 770.47, 768.33)
    a, stop, *_ = validate_decision({"action": "UPDATE_STOP", "stop_price": 769.555}, position=-12, entry=770.02,
                                    last=769.0, cfg=cfg, remaining_loss=10000, can_open=True, trades_today=0)
    assert a == "UPDATE_STOP" and stop in (769.55, 769.56)


def test_review_fields_on_close(env):
    cfg, t, b, ai, tr = env
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": 24950, "target_price": 25100, "confidence": 0.7, "reason": "突破",
               "_lessons": "abcd1234"}
    advance(t, minutes=5)
    tr.tick()
    for p in (25030, 24990, 24940):                 # 先浮賺 29，再跌穿止蝕（觸發嗰下都計入 MAE）
        b.price = p
        advance(t, seconds=5)
        tr.tick()
    close = [json.loads(l) for l in (cfg.log_dir / "trades.jsonl").read_text("utf-8").splitlines()
             if '"CLOSE"' in l][-1]
    assert close["mfe"] == 29 and close["mae"] == -61 and close["risk_pts"] == 50
    assert close["r_multiple"] == round(close["points"] / 50, 2) and close["lessons"] == "abcd1234"
    assert close["confidence"] == 0.7 and close["hold_min"] == 0.2 and close["open_reason"] == "突破"
    dec = [json.loads(l) for l in (cfg.log_dir / "decisions.jsonl").read_text("utf-8").splitlines()][-1]
    assert dec["lessons"] == "abcd1234" and dec["session"] == "DAY_AM"


def _open_long(t, ai, tr, stop=24950):
    tr.tick()
    ai.next = {"action": "OPEN_LONG", "stop_price": stop, "target_price": 25100, "confidence": 0.7, "reason": "突破"}
    advance(t, minutes=5)
    tr.tick()


def test_partial_open_records_filled_qty(env):
    cfg, t, b, ai, tr = env
    cfg = replace(cfg, max_qty=3)
    tr.cfg = cfg
    b.partial = 2
    _open_long(t, ai, tr)
    assert tr.state["pos"]["qty"] == 2 and b.pos["HK.MHI2610"] == 2
    ev = (cfg.log_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "PARTIAL_FILL" in ev


def test_partial_close_keeps_remainder(env):
    cfg, t, b, ai, tr = env
    tr.cfg = cfg = replace(cfg, max_qty=3)
    _open_long(t, ai, tr)
    assert tr.state["pos"]["qty"] == 3
    b.partial = 1
    b.price = 24940                       # 撞止蝕
    advance(t, seconds=5)
    tr.tick()
    assert tr.state["pos"]["qty"] == 2 and b.pos["HK.MHI2610"] == 2
    advance(t, seconds=5)
    tr.tick()                             # 下一輪平埋
    assert tr.state["pos"] is None and b.pos["HK.MHI2610"] == 0
    closes = [json.loads(x) for x in (cfg.log_dir / "trades.jsonl").read_text(encoding="utf-8").splitlines()
              if json.loads(x)["type"] == "CLOSE"]
    assert [c["qty"] for c in closes] == [1, 2] and "部分 1／3" in closes[0]["reason"]


def test_open_capped_or_skipped_by_buying_power(env):
    cfg, t, b, ai, tr = env
    tr.cfg = replace(cfg, max_qty=3, kind="stock")
    b.max_open_qty = lambda code, side, price: 0
    _open_long(t, ai, tr)
    assert tr.state.get("pos") is None and not b.orders
    assert "OPEN_SKIPPED" in (cfg.log_dir / "events.jsonl").read_text(encoding="utf-8")
    b.max_open_qty = lambda code, side, price: 1
    ai.next = {"action": "OPEN_LONG", "stop_price": 24950, "target_price": 25100, "confidence": 0.7, "reason": "再試"}
    advance(t, minutes=5)
    tr.tick()
    assert tr.state["pos"]["qty"] == 1


def test_real_skips_open_when_capacity_unknown(env):
    cfg, t, b, ai, tr = env
    tr.cfg = replace(cfg, trd_env="REAL", kind="stock")

    def boom(*a):
        raise RuntimeError("x")
    b.max_open_qty = boom
    _open_long(t, ai, tr)
    assert tr.state.get("pos") is None and not b.orders


def test_real_preflight_runs_every_interval(env):
    cfg, t, b, ai, tr = env
    calls = []
    b.real_preflight = lambda code, qty, price: calls.append(qty) or {"ok": True, "found": True}
    tr.tick()
    advance(t, minutes=10)
    tr.tick()
    assert len(calls) == 1 and tr.state["real_preflight"]["ok"] is True
    advance(t, minutes=25)
    tr.tick()
    assert len(calls) == 2
    b.real_preflight = lambda *a: (_ for _ in ()).throw(RuntimeError("冇權限"))
    advance(t, minutes=31)
    tr.tick()
    assert tr.state["real_preflight"]["ok"] is False and "冇權限" in tr.state["real_preflight"]["error"]


def test_real_needs_real_instance_and_listed_product(monkeypatch):
    import importlib
    import config as c
    for k in ("LONGFEI_INSTANCE", "LONGFEI_REAL_PRODUCTS", "TRD_ENV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PRODUCT", "SPY")
    monkeypatch.setenv("LONGFEI_REAL_PRODUCTS", "QQQ, spy,HSI")
    assert importlib.reload(c).Config().trd_env == "SIMULATE"          # 模擬程式永遠模擬
    monkeypatch.setenv("LONGFEI_INSTANCE", "REAL")
    assert importlib.reload(c).Config().trd_env == "REAL"
    monkeypatch.setenv("PRODUCT", "DIA")
    assert importlib.reload(c).Config().trd_env == "SIMULATE"          # 冇列明
    monkeypatch.setenv("PRODUCT", "HSI")
    assert importlib.reload(c).Config().trd_env == "REAL"
    monkeypatch.delenv("LONGFEI_INSTANCE")
    monkeypatch.setenv("TRD_ENV", "REAL")
    assert importlib.reload(c).Config().trd_env == "SIMULATE"          # HSI 模擬程式唔再跟 TRD_ENV
    for k in ("PRODUCT", "TRD_ENV", "LONGFEI_REAL_PRODUCTS"):
        monkeypatch.delenv(k)
    importlib.reload(c)


def test_futures_preflight_uses_power_vs_initial_margin():
    import types
    import pandas as pd
    if "futu" not in sys.modules:                 # 本機冇 futu-api：用假模組，常數就係名
        class _C:
            def __getattr__(self, n):
                return n
        fake = types.ModuleType("futu")
        for n in ("OpenQuoteContext", "OpenFutureTradeContext", "OpenSecTradeContext", "Market", "SecurityType",
                  "KLType", "AuType", "TrdEnv", "TrdSide", "TrdMarket", "OrderType", "ModifyOrderOp", "OrderStatus",
                  "SecurityFirm", "PositionSide"):
            setattr(fake, n, _C())
        fake.RET_OK = 0
        sys.modules["futu"] = fake
    from broker import FutuBroker, RET_OK

    class T:
        def get_acc_list(self):
            return RET_OK, pd.DataFrame([{"acc_id": 1, "trd_env": "REAL", "acc_type": "MARGIN", "trdmarket_auth": "['HK']"}])

        def accinfo_query(self, **k):
            return RET_OK, pd.DataFrame([{"total_assets": 500000, "power": 170000, "risk_status": "LEVEL1"}])

        def acctradinginfo_query(self, **k):
            return RET_OK, pd.DataFrame([{"max_cash_and_margin_buy": "N/A", "max_sell_short": "N/A",
                                          "long_required_im": 150000, "short_required_im": 150000}])
    b = FutuBroker.__new__(FutuBroker)
    from markets import spec_for
    from config import Config
    b.cfg, b.spec, b.trade = replace(Config(), real_acc_id=0), spec_for("HSI"), T()
    r = b.real_preflight("HK.HSI2610", 1, 25000)
    assert r["ok"] and r["can_long"] and r["can_short"] and r["im_pct_long"] == 88
    T.acctradinginfo_query = lambda self, **k: (RET_OK, pd.DataFrame([{"long_required_im": 200000, "short_required_im": 200000}]))
    r = b.real_preflight("HK.HSI2610", 1, 25000)
    assert not r["ok"] and not r["can_long"]


def test_real_futures_needs_cushion_after_margin(env):
    cfg, t, b, ai, tr = env
    tr.cfg = replace(cfg, trd_env="REAL")          # 10:05 日市：要求 = 37,500 + 10,000
    b.futures_room = lambda code, side, price: {"cushion": 150000, "im": 110000}
    _open_long(t, ai, tr)
    assert tr.state.get("pos") is None and not b.orders
    assert "期貨戶口緩衝唔夠" in (cfg.log_dir / "events.jsonl").read_text(encoding="utf-8")
    b.futures_room = lambda code, side, price: {"cushion": 170000, "im": 110000}
    ai.next = {"action": "OPEN_LONG", "stop_price": 24950, "target_price": 25100, "confidence": 0.7, "reason": "再試"}
    advance(t, minutes=5)
    tr.tick()
    assert tr.state["pos"]["qty"] == 1


def test_sim_futures_skips_cushion_check(env):
    cfg, t, b, ai, tr = env
    b.futures_room = lambda *a: {"cushion": 0, "im": 999999}
    _open_long(t, ai, tr)
    assert tr.state["pos"]["qty"] == 1


def test_daily_loss_limit_per_product(monkeypatch):
    import importlib
    import config as c
    for k in ("DAILY_LOSS_LIMIT", "DAILY_LOSS_LIMIT_SPY", "DAILY_LOSS_LIMIT_HSI"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PRODUCT", "SPY")
    monkeypatch.setenv("DAILY_LOSS_LIMIT", "10000")            # 舊嘅共用設定唔再管 ETF
    assert importlib.reload(c).Config().daily_loss_limit == 100_000
    monkeypatch.setenv("DAILY_LOSS_LIMIT_SPY", "50000")
    assert importlib.reload(c).Config().daily_loss_limit == 50_000
    monkeypatch.setenv("PRODUCT", "HSI")
    assert importlib.reload(c).Config().daily_loss_limit == 10_000
    monkeypatch.delenv("DAILY_LOSS_LIMIT")
    assert importlib.reload(c).Config().daily_loss_limit == 10_000
    for k in ("PRODUCT", "DAILY_LOSS_LIMIT_SPY"):
        monkeypatch.delenv(k)
    importlib.reload(c)


def test_account_snapshot_sim_and_real(env):
    cfg, t, b, ai, tr = env
    b.account_snapshot = lambda: {"currency": "HKD", "equity": 1_000_000.0, "power": 900_000.0}
    tr.snapshot_equity()
    assert tr.state["sim_account"]["power"] == 900_000.0
    from push import build_packet
    assert build_packet(cfg, tr.state, "t")["state"]["sim_account"]["equity"] == 1_000_000.0
    tr.state.pop("sim_account")
    tr.cfg = replace(cfg, trd_env="REAL")
    tr.snapshot_equity()
    assert "sim_account" not in tr.state and tr.state["real_account"]["equity"] == 1_000_000.0
    tr.state["sim_account"] = {"equity": 1}
    pk = build_packet(tr.cfg, tr.state, "t")["state"]
    assert pk["sim_account"] is None and pk["real_account"]["power"] == 900_000.0


def test_preflight_account_moves_to_real_account(env):
    cfg, t, b, ai, tr = env
    b.real_preflight = lambda code, qty, price: {"ok": True, "account": {"currency": "HKD", "equity": 5.0, "power": 2.0}}
    tr.tick()
    assert "account" not in tr.state["real_preflight"]
    assert tr.state["real_account"]["power"] == 2.0 and tr.state["real_account"]["source"] == "preflight"


def test_r215_new_etfs_like_spy():
    from markets import SPECS, order_qty, session_status as ss, ET
    for p in ("TLT", "IEF", "HYG", "GLD", "USO", "EEM", "EFA", "IWM"):
        s = SPECS[p]
        assert (s.kind, s.market, s.notional_usd, s.daily_loss_hkd, s.tick) == ("stock", "US", 100_000, 100_000, 0.01)
        assert ss(datetime(2026, 10, 19, 5, 0, tzinfo=ET), s.market, s.kind)[0] == "PRE"
    assert order_qty(SPECS["TLT"], 90.0, 1) == 1111 and "IAU" not in SPECS
