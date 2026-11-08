"""[IDEAS #1125] 趨勢簿（927）純函數：日線合併、上季突破、補入、低波幅突破、到期平倉、plan。"""
import os
import sys
import unittest

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
os.environ.update(XAU_TREND_LIVE="1", XAU_TREND_ADOPT="qbrk")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import trend_live as T  # noqa: E402

D0 = 20454            # 2026-01-01（Q1）


def mk(n, start=D0, px=4000.0, rng=10.0):
    return [(start + i, {"o": px, "h": px + rng, "l": px - rng, "c": px, "t0": 0, "t1": 0}) for i in range(n)]


class D1Merge(unittest.TestCase):
    def test_merge_ohlc(self):
        t = D0 * 86400
        bars = [{"t": t + 60, "open": 1, "high": 3, "low": 0.5, "close": 2}, {"t": t, "open": 1.5, "high": 2, "low": 1, "close": 1.8},
                {"t": t + 120, "open": 2, "high": 2.5, "low": 1.9, "close": 2.2}]
        d = T.d1_merge({}, bars)[str(D0)]
        self.assertEqual((d["o"], d["h"], d["l"], d["c"]), (1.5, 3, 0.5, 2.2))
        self.assertEqual(T.d1_merge({str(D0): d}, bars[:1])[str(D0)], d)   # 重覆冇影響


class Quarter(unittest.TestCase):
    def setUp(self):
        self.days = mk(90) + mk(5, start=D0 + 90, px=4000.0, rng=5.0)     # Q1 4000±10；Q2 頭幾日 ±5
        self.today = self.days[-1][0]

    def test_levels(self):
        self.assertEqual(T.qbrk_levels(self.days, self.today), (4010.0, 3990.0, 4000.0))

    def test_break_down_short(self):
        self.days[-1][1]["l"] = 3985
        s = T.qbrk_signal(self.days, self.today, {})
        self.assertEqual((s["side"], s["sl"]), (-1, 4000.0))

    def test_earlier_break_used(self):
        self.days[-2][1]["h"] = 4011
        self.assertTrue(T.qbrk_signal(self.days, self.today, {}).get("used_only"))

    def test_adopt_alive_and_stopped(self):
        days = mk(90) + mk(5, start=D0 + 90, px=3985.0, rng=3.0)            # Q2 第一日已經穿上季低 3990、冇返上 4000
        a = T.qbrk_adopt(days, days[-1][0])
        self.assertEqual((a["side"], a["sl"], a["since"]), (-1, 4000.0, D0 + 90))
        days[-1][1]["h"] = 4001                                             # 掂咗上季中位 → 已止蝕
        self.assertIsNone(T.qbrk_adopt(days, days[-1][0]))

    def test_exit_quarter_end(self):
        pos = {"rule": "qbrk", "period": T.qkey(self.today)}
        last = T.quarter_last_weekday(pos["period"])
        days = self.days + [(last, self.days[-1][1])]
        self.assertIsNone(T.exit_due(pos, days, last * 86400 + 20 * 3600))
        self.assertTrue(T.exit_due(pos, days, last * 86400 + 21 * 3600))


class LowVol(unittest.TestCase):
    def test_signal_when_atr_low(self):
        days = mk(250, rng=20.0) + mk(20, start=D0 + 250, rng=5.0)        # 最近波幅收窄
        today = D0 + 270
        days.append((today, {"o": 4000, "h": 4006, "l": 3999, "c": 4006, "t0": 0, "t1": 0}))
        s = T.lvbrk_signal(days, today, {})
        self.assertEqual((s["side"], s["sl"]), (1, 4000.0))
        self.assertIsNone(T.lvbrk_signal(days, today, {"lvbrk": today}))

    def test_no_signal_when_atr_high(self):
        days = mk(250, rng=5.0) + mk(20, start=D0 + 250, rng=20.0)         # 最近波幅放大
        today = D0 + 270
        days.append((today, {"o": 4000, "h": 4031, "l": 3999, "c": 4030, "t0": 0, "t1": 0}))
        self.assertIsNone(T.lvbrk_signal(days, today, {}))

    def test_exit_10th_day(self):
        days = mk(12)
        pos = {"rule": "lvbrk", "period": D0}
        self.assertIsNone(T.exit_due(pos, days[:9], (D0 + 8) * 86400 + 22 * 3600))
        self.assertTrue(T.exit_due(pos, days[:10], (D0 + 9) * 86400 + 21 * 3600))
        self.assertTrue(T.exit_due(pos, days[:11], (D0 + 10) * 86400 + 60))


class Plan(unittest.TestCase):
    def test_adopt_opens_then_blocked_waits(self):
        days = mk(90) + mk(5, start=D0 + 90, px=3985.0, rng=3.0)
        now = days[-1][0] * 86400 + 3600
        act, _ = T.plan(T.empty_state(), days, None, 3990.0, now, None, False)
        self.assertEqual(act[0], "open"); self.assertTrue(act[1]["adopt"])
        act, why = T.plan(T.empty_state(), days, None, 3990.0, now, "control＝PAUSE", False)
        self.assertIsNone(act); self.assertIn("等緊", why)

    def test_has_position_waits(self):
        days = mk(95)
        st = {**T.empty_state(), "pos": {"rule": "qbrk", "period": T.qkey(days[-1][0])}}
        act, _ = T.plan(st, days, {"ticket": 1}, 4000.0, days[-1][0] * 86400, None, False)
        self.assertIsNone(act)

    def test_seed_loads(self):
        self.assertGreater(len(T.load_seed()), 300)


if __name__ == "__main__":
    unittest.main()
