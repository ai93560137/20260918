"""gcp_ib/ib_collector.py 的 pick_expiries 回歸測試（不連 IB，只測到期日挑選）。"""
import os, sys, unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gcp_ib"))
import ib_collector as ibc  # noqa: E402

# N225 在 IB 看起來只有月權（2026-09-25／09-29／10-06 的日誌到期日都是這幾個）
N225 = ["20261008", "20261112", "20261210"]
# ESTX50 有週權
ESTX = ["20261014", "20261021", "20261030", "20261120"]


class PickExpiries(unittest.TestCase):
    def test_n225_close_to_monthly_still_works(self):
        self.assertEqual(ibc.pick_expiries(N225, today=date(2026, 10, 6)), ("20261008", "20261112"))

    def test_n225_gap_between_monthlies_used_to_return_none(self):
        # 2026-10-13：10/8 已過期，下一個是 11/12（30 天）。舊版短腿 None → 整列被丟掉。
        self.assertEqual(ibc.pick_expiries(N225, today=date(2026, 10, 13)), ("20261112", "20261210"))

    def test_weekly_underlying_unchanged(self):
        self.assertEqual(ibc.pick_expiries(ESTX, today=date(2026, 10, 13)), ("20261014", "20261030"))

    def test_weekly_without_long_window_unchanged(self):
        self.assertEqual(ibc.pick_expiries(["20261014", "20261230"], today=date(2026, 10, 13)),
                         ("20261014", "20261230"))

    def test_only_one_future_expiry_gives_no_pair(self):
        wk, mon = ibc.pick_expiries(["20261112"], today=date(2026, 10, 13))
        self.assertIsNone(wk)

    def test_expired_ones_are_ignored(self):
        self.assertEqual(ibc.pick_expiries(["20261008", "20261112", "20261210"], today=date(2026, 10, 9)),
                         ("20261112", "20261210"))


if __name__ == "__main__":
    unittest.main()
