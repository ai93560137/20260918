"""scripts/ib_es_nq_5m.py 的純函數：前月合約、紐約收市時間、交易時段、封包（不需要 ib_insync）。"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ib_es_nq_5m as m  # noqa: E402

UTC = timezone.utc


def bar(open_utc, o=7700.0, h=7705.0, l=7695.0, c=7702.0, v=1234):
    return SimpleNamespace(date=open_utc, open=o, high=h, low=l, close=c, volume=v)


class FrontMonth(unittest.TestCase):
    def test_october_uses_december(self):
        self.assertEqual(m.front_month(date(2026, 10, 18)), (2026, 12))
        self.assertEqual(m.local_symbol("ES", 2026, 12), "ESZ6")

    def test_rolls_eight_days_before_third_friday(self):
        self.assertEqual(m.third_friday(2026, 12), date(2026, 12, 18))
        self.assertEqual(m.front_month(date(2026, 12, 9)), (2026, 12))
        self.assertEqual(m.front_month(date(2026, 12, 10)), (2027, 3))
        self.assertEqual(m.local_symbol("NQ", 2027, 3), "NQH7")

    def test_after_expiry_month(self):
        self.assertEqual(m.front_month(date(2027, 3, 31)), (2027, 6))


class TimeKeys(unittest.TestCase):
    def test_close_time_in_new_york_summer_and_winter(self):
        # 夏令：UTC 19:50 開 = 紐約 15:50 開 → 收市 15:55
        self.assertEqual(m.ny_close_key(datetime(2026, 10, 16, 19, 50, tzinfo=UTC)), "2026-10-16 15:55:00")
        # 冬令：UTC 20:50 開 = 紐約 15:50 開
        self.assertEqual(m.ny_close_key(datetime(2026, 12, 4, 20, 50, tzinfo=UTC)), "2026-12-04 15:55:00")

    def test_session_hours(self):
        self.assertTrue(m.in_session("2026-10-16 17:00:00"))       # 星期五最後一根
        self.assertFalse(m.in_session("2026-10-16 17:05:00"))      # 休市
        self.assertFalse(m.in_session("2026-10-16 18:05:00"))      # 星期五晚 → 星期六交易日
        self.assertTrue(m.in_session("2026-10-18 18:05:00"))       # 星期日晚開市 → 星期一交易日
        self.assertTrue(m.in_session("2026-10-14 03:00:00"))


class Packet(unittest.TestCase):
    def test_drops_last_bar_sorts_dedupes_and_filters(self):
        t0 = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)
        bars = [bar(t0 + timedelta(minutes=5 * i), c=7700 + i) for i in range(4)]
        bars.append(bar(t0, c=1.0))                                  # 同一根重覆
        bars.append(bar(datetime(2026, 10, 16, 21, 5, tzinfo=UTC)))  # 17:10 紐約，休市
        data = m.bars_to_packet_data(list(reversed(bars)))
        keys = [d["time_key"] for d in data]
        self.assertEqual(keys, ["2026-10-16 15:45:00", "2026-10-16 15:50:00", "2026-10-16 15:55:00", "2026-10-16 16:00:00"])
        self.assertEqual(sorted(data[0]), ["close", "high", "low", "open", "time_key", "volume"])

    def test_naive_dates_are_utc_and_count_limit(self):
        t0 = datetime(2026, 10, 14, 13, 0)
        bars = [bar(t0 + timedelta(minutes=5 * i), v=-1) for i in range(200)]
        data = m.bars_to_packet_data(bars, count=120)
        self.assertEqual(len(data), 120)
        self.assertEqual(data[-1]["volume"], 1.0)              # 0／-1 → 1，main.py 先唔會略過
        self.assertEqual(data[0]["time_key"][:10], "2026-10-14")

    def test_last_bar_kept_when_market_closed(self):
        t0 = datetime(2026, 10, 16, 20, 45, tzinfo=UTC)                 # 紐約 16:45 開 → 16:50 … 17:00 收
        bars = [bar(t0 + timedelta(minutes=5 * i)) for i in range(3)]
        live = m.bars_to_packet_data(bars, now_utc=datetime(2026, 10, 16, 21, 12, tzinfo=UTC))
        self.assertEqual(live[-1]["time_key"], "2026-10-16 16:55:00")    # 啱啱收：最後一根當未完成
        closed = m.bars_to_packet_data(bars, now_utc=datetime(2026, 10, 18, 21, 0, tzinfo=UTC))
        self.assertEqual(closed[-1]["time_key"], "2026-10-16 17:00:00")  # 週末：17:00 嗰根照推

    def test_backfill_sessions_and_chunks(self):
        t0 = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)                  # 紐約 10-12 18:00 起（10-13 交易日）
        bars = [bar(t0 + timedelta(minutes=5 * i)) for i in range(12 * 24 * 5)]
        data = m.bars_to_packet_data(bars, count=10 ** 6, now_utc=datetime(2026, 10, 18, 21, 0, tzinfo=UTC))
        days = sorted({m.session_of(b["time_key"]) for b in data})
        self.assertEqual(days, ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])
        two = m.last_sessions(data, 2)
        self.assertEqual(sorted({m.session_of(b["time_key"]) for b in two}), ["2026-10-15", "2026-10-16"])
        parts = m.chunks(data)
        self.assertTrue(all(len(p) <= 400 for p in parts))
        self.assertEqual(sum(len(p) for p in parts), len(data))
        self.assertEqual(parts[-1][-1], data[-1])                         # 最後一包係最新
        self.assertEqual(m.ib_end(datetime(2026, 10, 9, 22, 0, tzinfo=UTC)), "20261009-22:00:00")

    def test_packet_shape(self):
        p = m.packet("tok", "US.ES_FRONT", "ib_delayed:ESZ6", [{"time_key": "x"}])
        self.assertEqual(p["action"], "futu_data")
        self.assertEqual(p["kline_type"], "K_5M")
        self.assertEqual(p["symbol"], "US.ES_FRONT")
        self.assertLessEqual(len(p["source"]), 32)                  # main.handle_futu_data 截 32 字


if __name__ == "__main__":
    unittest.main()
