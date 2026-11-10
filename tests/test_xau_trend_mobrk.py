"""[IDEAS #1114] 趨勢簿 mobrk（月初三日區間突破）純函數：區間、第 4 日起先穿、一個月一次、SL 另一端、月尾平、plan。"""
import os
import sys
import unittest

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
os.environ.update(XAU_TREND_LIVE="1", XAU_TREND_RULES="mobrk", XAU_TREND_MAGIC="933")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import trend_live as T  # noqa: E402

NOV1 = 20758          # 2026-11-01（星期日）


def wdays(start, n):
    import datetime as dt
    out, d = [], start
    while len(out) < n:
        if dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).weekday() < 5:
            out.append(d)
        d += 1
    return out


def bars(ds, px=4000.0, rng=10.0):
    return [(d, {"o": px, "h": px + rng, "l": px - rng, "c": px, "t0": 0, "t1": 0}) for d in ds]


class Mobrk(unittest.TestCase):
    def setUp(self):
        self.ds = wdays(NOV1, 6)                         # 11-02、03、04（頭 3 日）、05、06、09
        self.days = bars(self.ds[:3], rng=10.0) + bars(self.ds[3:], rng=5.0)
        self.today = self.ds[-1]

    def test_levels_need_day4(self):
        self.assertIsNone(T.mobrk_levels(self.days[:3], self.ds[2]))
        self.assertEqual(T.mobrk_levels(self.days, self.today)[:2], (4010.0, 3990.0))

    def test_break_up_long_sl_low(self):
        self.days[-1][1]["h"] = 4012
        s = T.mobrk_signal(self.days, self.today, {})
        self.assertEqual((s["side"], s["sl"], s["period"]), (1, 3990.0, T.mkey(self.today)))

    def test_break_down_short_sl_high(self):
        self.days[-1][1]["l"] = 3985
        s = T.mobrk_signal(self.days, self.today, {})
        self.assertEqual((s["side"], s["sl"]), (-1, 4010.0))

    def test_earlier_break_marks_used(self):
        self.days[3][1]["h"] = 4015
        self.assertTrue(T.mobrk_signal(self.days, self.today, {}).get("used_only"))

    def test_used_once_per_month(self):
        self.days[-1][1]["h"] = 4012
        self.assertIsNone(T.mobrk_signal(self.days, self.today, {"mobrk": T.mkey(self.today)}))

    def test_no_break_inside(self):
        self.assertIsNone(T.mobrk_signal(self.days, self.today, {}))

    def test_month_last_weekday(self):
        import datetime as dt
        d = T.month_last_weekday(T.mkey(NOV1))
        self.assertEqual(dt.date(1970, 1, 1) + dt.timedelta(days=d), dt.date(2026, 11, 30))   # 11-30 係星期一
        d = T.month_last_weekday(T.mkey(NOV1 + 40))                                          # 2026-12
        self.assertEqual(dt.date(1970, 1, 1) + dt.timedelta(days=d), dt.date(2026, 12, 31))

    def test_exit_due_month_end(self):
        pos = {"rule": "mobrk", "period": T.mkey(self.today)}
        last = T.month_last_weekday(T.mkey(self.today))
        days = bars([last])
        self.assertIsNone(T.exit_due(pos, days, last * 86400 + 20 * 3600))
        self.assertEqual(T.exit_due(pos, days, last * 86400 + 21 * 3600), "月尾收市平")
        self.assertEqual(T.exit_due(pos, bars([last + 3]), (last + 3) * 86400), "月尾已過，平")

    def test_plan_opens(self):
        self.days[-1][1]["h"] = 4012
        st = {"d1": {str(d): r for d, r in self.days}, "used": {}, "orders": []}
        T.last_bar_age = lambda d1, now: 0
        act, why = T.plan(st, self.days, None, 4011.0, self.today * 86400 + 10 * 3600, None, False)
        self.assertEqual(act[0], "open"); self.assertEqual(act[1]["rule"], "mobrk"); self.assertIn("#1114", why)

    def test_plan_small_risk_skips(self):
        self.days[-1][1]["h"] = 4012
        st = {"d1": {}, "used": {}, "orders": []}
        T.last_bar_age = lambda d1, now: 0
        act, _ = T.plan(st, self.days, None, 3990.3, self.today * 86400 + 10 * 3600, None, False)
        self.assertEqual(act[0], "used")


if __name__ == "__main__":
    unittest.main()
