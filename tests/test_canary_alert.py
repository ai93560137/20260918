"""canary/special_alert.py 的單元測試:盤中升級才發、同日不重發、報價不新鮮不判、收市確認／解除、同燈色日不重發。

執行:python3 -m unittest tests/test_canary_alert.py -v(全程假報價,不連網)
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "canary"))

import special_alert as sa  # noqa: E402

NOW = datetime(2026, 10, 23, 15, 30, tzinfo=timezone.utc)     # 紐約 10-23(五) 11:30


def row(d, s9, s3, short, dis, v9="18.00", vx="19.00", v3="20.00"):
    return {"date": d, "vix9d": v9, "vix": vx, "vix3m": v3, "slope_9d": str(s9), "slope_3m": str(s3),
            "axis_short": short, "axis_disaster": dis}


ROWS = [row("2026-10-21", -1.19, -2.04, "綠", "綠"), row("2026-10-22", -0.17, -1.09, "走平", "綠")]


def fetcher(v9, vx, v3, t=NOW - timedelta(minutes=5)):
    px = {"^VIX9D": v9, "^VIX": vx, "^VIX3M": v3}
    return lambda sym: (px[sym], t)


class IntradayTests(unittest.TestCase):
    def test_escalation_to_red_alerts_once(self):
        text, st, log, _ = sa.intraday(NOW, fetcher(20.09, 20.08, 20.93), ROWS, {})
        self.assertIn("短期軸盤中升級:走平 → 紅", text)
        self.assertIn("VIX9D 20.09 − VIX 20.08 = +0.01", text)
        self.assertIn("上一收市 10-22(四) -0.17(走平)", text)
        self.assertEqual(st["intraday_short"], 2)
        self.assertEqual(log[0]["kind"], "盤中預警")
        again, st2, log2, why = sa.intraday(NOW + timedelta(minutes=30), fetcher(20.5, 20.1, 20.9, NOW + timedelta(minutes=25)), ROWS, st)
        self.assertIsNone(again)
        self.assertEqual(log2, [])

    def test_same_level_as_close_does_not_alert(self):
        text, st, _, why = sa.intraday(NOW, fetcher(18.7, 19.0, 20.0), ROWS, {})   # −0.30 仍是走平
        self.assertIsNone(text)
        self.assertIn("未升級", why)
        self.assertEqual(st["intraday_short"], 1)

    def test_green_to_flat_alerts(self):
        rows = [row("2026-10-21", -2.0, -2.0, "綠", "綠"), row("2026-10-22", -1.19, -2.04, "綠", "綠")]
        text, st, _, _ = sa.intraday(NOW, fetcher(18.6, 18.95, 20.06), rows, {})
        self.assertIn("短期軸盤中升級:綠 → 走平", text)

    def test_disaster_escalation(self):
        text, st, log, _ = sa.intraday(NOW, fetcher(25.0, 24.0, 23.5), ROWS, {})
        self.assertIn("災難軸盤中升級:綠 → 深紅", text)
        self.assertEqual({l["axis"] for l in log}, {"短期軸", "災難軸"})

    def test_stale_quote_skipped(self):
        text, st, _, why = sa.intraday(NOW, fetcher(25, 20, 21, NOW - timedelta(hours=3)), ROWS, {})
        self.assertIsNone(text)
        self.assertIn("不新鮮", why)

    def test_fetch_failure_skipped(self):
        def bad(sym):
            raise OSError("403")
        text, _, _, why = sa.intraday(NOW, bad, ROWS, {})
        self.assertIsNone(text)
        self.assertIn("失敗", why)

    def test_weekend_skipped(self):
        sat = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
        text, _, _, why = sa.intraday(sat, fetcher(25, 20, 21, sat), ROWS, {})
        self.assertIsNone(text)
        self.assertIn("週末", why)

    def test_new_day_resets_but_keeps_close_done(self):
        st = {"us_date": "2026-10-22", "intraday_short": 2, "intraday_disaster": 0, "close_done": ["2026-10-21"]}
        text, st2, _, _ = sa.intraday(NOW, fetcher(18.7, 19.0, 20.0), ROWS, st)
        self.assertEqual(st2["us_date"], "2026-10-23")
        self.assertEqual(st2["intraday_short"], 1)
        self.assertEqual(st2["close_done"], ["2026-10-21"])


class CloseTests(unittest.TestCase):
    def test_confirm_upgrade(self):
        rows = ROWS + [row("2026-10-23", 0.01, -0.85, "紅", "綠", "20.09", "20.08", "20.93")]
        text, st, log, _ = sa.close(rows, {}, NOW)
        self.assertIn("收市確認:短期軸 走平 → 紅(10-22(四) → 10-23(五))", text)
        self.assertEqual(st["close_done"], ["2026-10-23"])
        again, _, _, why = sa.close(rows, st, NOW)
        self.assertIsNone(again)
        self.assertIn("已處理過", why)

    def test_release_when_close_below_intraday(self):
        rows = ROWS + [row("2026-10-23", -0.30, -0.9, "走平", "綠")]
        st = {"us_date": "2026-10-23", "intraday_short": 2, "intraday_disaster": 0}
        text, _, log, _ = sa.close(rows, st, NOW)
        self.assertIn("收市解除:短期軸 盤中曾到紅,收市為走平", text)
        self.assertEqual(log[0]["kind"], "收市解除")

    def test_confirm_and_release_together(self):
        rows = [row("2026-10-21", -2, -2, "綠", "綠"), row("2026-10-22", -0.3, -1, "走平", "綠")]
        st = {"us_date": "2026-10-22", "intraday_short": 2, "intraday_disaster": 0}
        text, _, log, _ = sa.close(rows, st, NOW)
        self.assertIn("收市確認:短期軸 綠 → 走平", text)
        self.assertIn("收市解除:短期軸 盤中曾到紅,收市為走平", text)

    def test_no_change_no_message(self):
        rows = ROWS + [row("2026-10-23", -0.3, -1.0, "走平", "綠")]
        text, st, log, _ = sa.close(rows, {}, NOW)
        self.assertIsNone(text)
        self.assertEqual(log, [])
        self.assertEqual(st["close_done"], ["2026-10-23"])

    def test_downgrade_without_intraday_is_silent(self):
        rows = ROWS + [row("2026-10-23", -1.0, -1.0, "綠", "綠")]
        text, _, _, _ = sa.close(rows, {}, NOW)
        self.assertIsNone(text)


if __name__ == "__main__":
    unittest.main()
