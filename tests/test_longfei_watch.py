"""research/longfei_analyst/mimic/watch.py 純函數測試（唔連 GCS）。"""
import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "longfei_analyst", "mimic"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research", "longfei_analyst"))
import watch as w  # noqa: E402

ET = ZoneInfo("America/New_York")


class T(unittest.TestCase):
    def test_below_cross_only(self):
        lv = {"below": [7565]}
        self.assertEqual([x[0] for x in w.check([["a", 7600, 7610, 7570, 7580], ["b", 7580, 7590, 7540, 7550]], lv)], ["below"])
        self.assertEqual(w.check([["a", 7560, 7562, 7540, 7550], ["b", 7550, 7570, 7530, 7540]], lv), [])      # 已經喺下面，唔重複
        self.assertEqual(w.check([["a", 7600, 7610, 7570, 7580], ["b", 7580, 7590, 7560, 7566]], lv), [])      # 插針唔算，睇收市

    def test_inside_down(self):
        self.assertEqual([x[0] for x in w.check([["a", 7600, 7620, 7560, 7610], ["b", 7605, 7615, 7580, 7590]], {})], ["inside"])
        self.assertEqual([x[0] for x in w.check([["a", 7600, 7620, 7560, 7610], ["b", 7590, 7615, 7580, 7605]], {})], ["inside_up"])   # 收紅（向上）都提
        self.assertEqual(w.check([["a", 7600, 7620, 7560, 7610], ["b", 7605, 7625, 7580, 7590]], {}), [])      # 高過前一根高，唔係 inside

    def test_near_key(self):
        keys = [7498.5, 7565, 7665]
        self.assertIn("測試 7,498.50，收返上面", w.near_key(["a", 7551, 7566, 7493, 7523], keys))      # 11/10：低 7493 插穿 7498.5 收返上面
        self.assertIn("測試 7,665.00，收返下面", w.near_key(["a", 7609, 7671.5, 7597, 7660], keys))    # 高 7671.5 過 7665 收返下面
        self.assertIn("唔喺關鍵位", w.near_key(["a", 7616.75, 7628.5, 7600.5, 7619.75], keys))

    def test_closed_bars(self):
        bars = [["2026-11-11 10:00", 1, 2, 0, 1], ["2026-11-11 14:00", 1, 2, 0, 1], ["2026-11-11 18:00", 1, 2, 0, 1]]
        now = datetime(2026, 11, 11, 17, 5, tzinfo=ET)
        self.assertEqual([b[0] for b in w.closed_bars(bars, now)], ["2026-11-11 10:00", "2026-11-11 14:00"])   # 14:00 嗰根 17:00 收
        now = datetime(2026, 11, 11, 16, 59, tzinfo=ET)
        self.assertEqual([b[0] for b in w.closed_bars(bars, now)], ["2026-11-11 10:00"])


if __name__ == "__main__":
    unittest.main()
