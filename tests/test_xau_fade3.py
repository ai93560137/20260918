"""[IDEAS #1125] 933 組合三條急動規則（#1121 M5 急動、#1122 離開市 15、#1123 兩根急動）：features 純函數同回測定義一致。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
import features as F  # noqa: E402

T0 = 1_800_000_000 // 86400 * 86400          # 某日 00:00 UTC


def bars(rows, t0=T0):
    """rows：[(o, h, l, c)]，每分鐘一根，offset 0。"""
    return [{"time": t0 + 60 * i, "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(rows)]


def flat(n, px=4000.0):
    return [(px, px + 0.2, px - 0.2, px)] * n


def rules(m1, now):
    return {c["rule"]: c for c in F.rule_candidates(m1, 0, now)}


class Spike2(unittest.TestCase):
    def test_two_up_bodies_sum_5_sell(self):
        rows = flat(40) + [(4000, 4003, 4000, 4002.5), (4002.5, 4005.2, 4002.4, 4005.0)]
        m1 = bars(rows); now = m1[-1]["time"] + 60
        c = rules(m1, now).get("spike2")
        self.assertIsNotNone(c); self.assertEqual(c["side"], "SELL")

    def test_mixed_direction_no(self):
        rows = flat(40) + [(4000, 4006, 4000, 4006), (4006, 4006, 4005, 4005.5)]
        m1 = bars(rows); self.assertNotIn("spike2", rules(m1, m1[-1]["time"] + 60))

    def test_sum_below_5_no(self):
        rows = flat(40) + [(4000, 4002, 4000, 4002), (4002, 4004.9, 4002, 4004.9)]
        m1 = bars(rows); self.assertNotIn("spike2", rules(m1, m1[-1]["time"] + 60))


class M5Spike(unittest.TestCase):
    def test_range_6_on_last_minute_of_m5(self):
        rows = flat(40) + [(4000, 4001, 3999.9, 4001), (4001, 4004, 4001, 4004), (4004, 4006.5, 4003, 4006), (4006, 4006, 4004, 4005), (4005, 4005.5, 4004, 4005)]
        m1 = bars(rows)                     # 40 根 flat 之後由 t%300==0 開始，第 45 根（index 44）t%300==240
        self.assertEqual(m1[-1]["time"] % 300, 240)
        c = rules(m1, m1[-1]["time"] + 60).get("m5spike")
        self.assertIsNotNone(c); self.assertEqual(c["side"], "SELL")      # 收市高過開市 → 反向做空

    def test_not_last_minute_no(self):
        rows = flat(40) + [(4000, 4007, 3999, 4006), (4006, 4006, 4005, 4005.5)]
        m1 = bars(rows)
        self.assertNotIn("m5spike", rules(m1, m1[-1]["time"] + 60))


class DayOpen(unittest.TestCase):
    def test_fires_once_per_day(self):
        rows = flat(30) + [(4000, 4000, 3984, 3984.5)]
        m1 = bars(rows); now = m1[-1]["time"] + 60
        c, day = F.dopen_candidate(m1, 0, now, {})
        self.assertIsNotNone(c); self.assertEqual(c["side"], "BUY"); self.assertTrue(day["done"])
        c2, _ = F.dopen_candidate(m1 + bars([(3984.5, 3984.5, 3980, 3981)], m1[-1]["time"] + 60), 0, now + 60, day)
        self.assertIsNone(c2)

    def test_open_remembered_after_window_drops(self):
        m1 = bars(flat(30)); _, day = F.dopen_candidate(m1, 0, m1[-1]["time"] + 60, {})
        self.assertEqual(day["open"], 4000.0)
        later = bars([(4010, 4016, 4010, 4015.5)], T0 + 8 * 3600)          # 舊 K 線已經冇咗
        c, day2 = F.dopen_candidate(later, 0, later[-1]["time"] + 60, day)
        self.assertIsNotNone(c); self.assertEqual(c["side"], "SELL")

    def test_missed_open_skips_day(self):
        m1 = bars(flat(10) + [(4000, 4020, 4000, 4020)], T0 + 600)          # 第一根 00:10 → 今日唔做
        c, day = F.dopen_candidate(m1, 0, m1[-1]["time"] + 60, {})
        self.assertIsNone(c); self.assertTrue(day["done"])

    def test_first_bar_itself_not_compared(self):
        m1 = bars([(4000, 4020, 4000, 4018)])
        c, _ = F.dopen_candidate(m1, 0, m1[-1]["time"] + 60, {})
        self.assertIsNone(c)


if __name__ == "__main__":
    unittest.main()
