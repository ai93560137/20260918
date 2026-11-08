"""[IDEAS #2031] hsi_ai_trader/bars_backfill.py 純函數測試（唔連富途）。"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hsi_ai_trader"))
import bars_backfill as bb  # noqa: E402


class T(unittest.TestCase):
    def test_month_ranges(self):
        r = bb.month_ranges(date(2024, 1, 15), date(2024, 3, 10))
        self.assertEqual(r, [(date(2024, 1, 15), date(2024, 1, 31)), (date(2024, 2, 1), date(2024, 2, 29)),
                             (date(2024, 3, 1), date(2024, 3, 10))])

    def test_month_ranges_dec(self):
        r = bb.month_ranges(date(2023, 12, 1), date(2024, 1, 5))
        self.assertEqual(r[0], (date(2023, 12, 1), date(2023, 12, 31)))
        self.assertEqual(r[1], (date(2024, 1, 1), date(2024, 1, 5)))

    def test_probe_days(self):
        p = bb.probe_days(2024, date(2024, 8, 1))
        self.assertEqual(p, [(date(2024, 1, 10), date(2024, 1, 16)), (date(2024, 7, 10), date(2024, 7, 16))])

    def test_save_dry_run(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            rows = [("2024-01-02 09:15:00", 1, 2, 0.5, 1.5, 10), ("2024-01-02 17:15:00", 1, 2, 0.5, 1.5, 10),
                    ("2024-01-03 09:15:00", 1, 2, 0.5, 1.5, 10)]
            sent = {}
            nd, nu = bb.save_and_upload("HSI", rows, Path(d), "", "", sent, True)
            self.assertEqual((nd, nu), (2, 0))
            self.assertTrue((Path(d) / "HSI" / "2024-01-02.json").exists())


if __name__ == "__main__":
    unittest.main()
