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

    def test_inside_only_after_key(self):
        lv = {"keys": [7498.5, 7665], "lookback": 3}
        base = [["x", 7580, 7600, 7570, 7590], ["y", 7590, 7598, 7566, 7580], ["z", 7580, 7597, 7550, 7560]]
        # 11/10：前一根創新低 7493 測試 7498.5、冇收穿，inside bar 收喺上面 → 提（空方冇力）
        r = w.check(base + [["a", 7551, 7566, 7493, 7523], ["b", 7523, 7559, 7521, 7555]], lv)
        self.assertEqual([x[0] for x in r], ["inside_key"])
        self.assertIn("空方冇力", r[0][2])
        # 前一根創新高 7671.5 測試 7665，inside bar 收返 7665 下面 → 提（多方冇力）
        up = [["x", 7590, 7607, 7584, 7603], ["y", 7603, 7625, 7593, 7608], ["z", 7608, 7630, 7600, 7625]]
        r = w.check(up + [["a", 7625, 7671.5, 7597, 7667], ["b", 7666, 7668, 7637, 7643]], lv)
        self.assertIn("多方冇力", r[0][2])
        # inside bar 收企 7665 上面（攻破咗）→ 唔提
        self.assertEqual(w.check(up + [["a", 7625, 7671.5, 7597, 7667], ["b", 7667, 7670, 7660, 7668]], lv), [])
        # 前一根冇創新高新低（只係掂到關鍵位）→ 唔提
        flat = [["x", 7640, 7680, 7630, 7650], ["y", 7650, 7675, 7640, 7655], ["z", 7655, 7672, 7645, 7660]]
        self.assertEqual(w.check(flat + [["a", 7660, 7668, 7648, 7655], ["b", 7655, 7662, 7650, 7652]], lv), [])

    def test_near_key(self):
        keys = [7498.5, 7565, 7665]
        self.assertIn("測試 7,498.50，收返上面（守得住）", w.near_key(["a", 7551, 7566, 7493, 7523], keys))      # 11/10：低 7493 插穿 7498.5 收返上面
        self.assertIn("測試 7,665.00，收返下面（攻唔破）", w.near_key(["a", 7609, 7671.5, 7597, 7660], keys))    # 高 7671.5 過 7665 收返下面
        self.assertIn("唔喺關鍵位", w.near_key(["a", 7616.75, 7628.5, 7600.5, 7619.75], keys))

    def test_closed_bars(self):
        bars = [["2026-11-11 10:00", 1, 2, 0, 1], ["2026-11-11 14:00", 1, 2, 0, 1], ["2026-11-11 18:00", 1, 2, 0, 1]]
        now = datetime(2026, 11, 11, 17, 5, tzinfo=ET)
        self.assertEqual([b[0] for b in w.closed_bars(bars, now)], ["2026-11-11 10:00", "2026-11-11 14:00"])   # 14:00 嗰根 17:00 收
        now = datetime(2026, 11, 11, 16, 59, tzinfo=ET)
        self.assertEqual([b[0] for b in w.closed_bars(bars, now)], ["2026-11-11 10:00"])


if __name__ == "__main__":
    unittest.main()
