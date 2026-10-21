"""[R248] longfei_capacity：購買力唔夠就減細／做唔到；同一刻先平後開。"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import longfei_capacity as lc  # noqa: E402

HKT = timezone(timedelta(hours=8))


def T(p, h0, h1, r, n=100000):
    d = datetime(2026, 10, 19, tzinfo=HKT)
    return {"p": p, "t_open": d + timedelta(hours=h0), "t_close": d + timedelta(hours=h1), "r": r, "notional": n}


def test_capacity_caps_and_skips():
    trades = [T("SPY", 1, 5, 0.01), T("QQQ", 2, 6, 0.01), T("DIA", 3, 7, 0.01)]
    r = lc.simulate(trades, 100000, 2.0, lambda eq, av, k: 0.8 * eq)       # 每單 8 萬，購買力 20 萬
    assert r["taken"] == 3 and r["capped"] == 1 and r["skipped"] == 0       # 第 3 單得返 4 萬
    r = lc.simulate(trades, 100000, 2.0, lambda eq, av, k: 1.0 * eq)
    assert r["taken"] == 2 and r["skipped"] == 1
    assert abs(r["equity"] - (100000 + 2 * 1000)) < 1e-6


def test_close_before_open_same_time():
    trades = [T("SPY", 1, 2, 0.0), T("QQQ", 2, 3, 0.0)]
    r = lc.simulate(trades, 100000, 1.0, lambda eq, av, k: eq)
    assert r["taken"] == 2 and r["skipped"] == 0


def test_load_trades_uses_net_and_notional():
    docs = {"SPY": {"trades": [{"type": "CLOSE", "entry": 500.0, "qty": 10, "pnl_hkd_net": 390.0, "pnl_hkd_gross": 400,
                                "opened_at": "2026-10-19T22:00:00+08:00", "ts": "2026-10-19T22:30:00+08:00"},
                               {"type": "OPEN", "entry": 1}]}}
    t = lc.load_trades(docs)
    assert len(t) == 1 and abs(t[0]["notional"] - 39000) < 1e-6 and abs(t[0]["r"] - 0.01) < 1e-9
