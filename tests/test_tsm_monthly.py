"""[IDEAS #2018 真倉] hsi_ai_trader/tsm_monthly.py 純函數測試（唔連富途、唔上網）。"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hsi_ai_trader"))
import tsm_monthly as t  # noqa: E402

ET = ZoneInfo("America/New_York")


def daily_series(start, months, growth):
    out, d, px = [], start, 100.0
    while len({x[0][:7] for x in out}) <= months:
        if d.weekday() < 5:
            out.append((d.isoformat(), px))
            px *= 1 + growth
        d += timedelta(days=1)
    return out


class T(unittest.TestCase):
    def test_month_end_closes(self):
        rows = [("2026-09-29", 1), ("2026-09-30", 2), ("2026-10-01", 3), ("2026-10-30", 4)]
        self.assertEqual(t.month_end_closes(rows), [("2026-09", "2026-09-30", 2), ("2026-10", "2026-10-30", 4)])

    def test_signal_up_down(self):
        up = daily_series(date(2024, 1, 1), 15, 0.001)
        s = t.signal(up, datetime(2025, 4, 2, 19, tzinfo=ET))
        self.assertEqual(s["target"], 1)
        self.assertEqual(s["month"], "2025-03")
        dn = daily_series(date(2024, 1, 1), 15, -0.001)
        self.assertEqual(t.signal(dn, datetime(2025, 4, 2, 19, tzinfo=ET))["target"], 0)

    def test_signal_ignores_current_month(self):
        up = daily_series(date(2024, 1, 1), 15, 0.001)
        cur = up[-1][0][:7]
        s = t.signal(up, datetime.fromisoformat(up[-1][0] + "T19:00").replace(tzinfo=ET))
        self.assertLess(s["month"], cur)

    def test_signal_not_enough(self):
        self.assertIsNone(t.signal(daily_series(date(2025, 1, 1), 5, 0.001), datetime(2025, 7, 2, tzinfo=ET)))

    def test_plan_buy_new_month(self):
        acts, _ = t.plan({"qty": 0, "code": None, "month": "2026-09"}, {"month": "2026-10", "target": 1}, "US.MNQ2612", 0, False)
        self.assertEqual(acts, [("buy", "US.MNQ2612"), ("set_month", "2026-10")])

    def test_plan_sell_when_target0(self):
        acts, _ = t.plan({"qty": 1, "code": "US.MNQ2612", "month": "2026-10"}, {"month": "2026-11", "target": 0},
                         "US.MNQ2612", 1, False)
        self.assertEqual(acts, [("sell", "US.MNQ2612"), ("set_month", "2026-11")])

    def test_plan_hold_same_month(self):
        acts, notes = t.plan({"qty": 1, "code": "US.MNQ2612", "month": "2026-10"}, {"month": "2026-10", "target": 1},
                             "US.MNQ2612", 1, False)
        self.assertEqual((acts, notes), ([], []))

    def test_plan_roll(self):
        acts, notes = t.plan({"qty": 1, "code": "US.MNQ2612", "month": "2026-11"}, {"month": "2026-11", "target": 1},
                             "US.MNQ2603", 1, False)
        self.assertEqual(acts, [("sell", "US.MNQ2612"), ("buy", "US.MNQ2603")])

    def test_plan_stop_filled_no_reentry_same_month(self):
        acts, _ = t.plan({"qty": 1, "code": "US.MNQ2612", "month": "2026-11"}, {"month": "2026-11", "target": 1},
                         "US.MNQ2612", 0, True)
        self.assertEqual(acts, [("mark_flat", "後備止蝕成交")])

    def test_plan_mismatch_manual(self):
        acts, notes = t.plan({"qty": 1, "code": "US.MNQ2612", "month": "2026-11"}, {"month": "2026-12", "target": 0},
                             "US.MNQ2612", 0, False)
        self.assertEqual(acts, [])
        self.assertTrue(notes)

    def test_fresh_price(self):
        self.assertEqual(t.fresh_price(27000, 1000, 1000 + 600), 27000.0)
        self.assertIsNone(t.fresh_price(27000, 1000, 1000 + 3 * 3600))      # 週末舊價
        self.assertIsNone(t.fresh_price(None, 1000, 1000))

    def test_foreign_positions(self):
        st0 = {"qty": 0, "code": None}
        self.assertEqual(t.foreign_positions({"US.MNQ2612": (-2, 26820.0)}, st0), {"US.MNQ2612": -2})
        st1 = {"qty": 1, "code": "US.MNQ2612"}
        self.assertEqual(t.foreign_positions({"US.MNQ2612": (1, 27000.0)}, st1), {})
        self.assertEqual(t.foreign_positions({"US.MNQ2612": (-1, 27000.0)}, st1), {"US.MNQ2612": -2})
        self.assertEqual(t.foreign_positions({}, st1, stop_filled=True), {})
        self.assertEqual(t.foreign_positions({}, st0), {})

    def test_prices(self):
        self.assertEqual(t.limit_price(26000, 1, 0.25), 26065.0)
        self.assertEqual(t.limit_price(26000, -1, 0.25), 25935.0)
        self.assertEqual(t.stop_price(26000, 0.12, 0.25), 22880.0)


if __name__ == "__main__":
    unittest.main()
