"""[11-12] 趨勢簿複利手數（XAU_TREND_COMPOUND）：純計算測試（唔掂 GCS）。"""
import os
import sys
import unittest

os.environ.update(WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import config       # noqa: E402
import trend_live   # noqa: E402


class Compound(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(config, k) for k in ("TREND_LOTS", "TREND_MAX_LOTS", "TREND_COMPOUND", "TREND_COMPOUND_UNIT_HKD", "TREND_COMPOUND_MAX_LOTS")}
        config.TREND_LOTS, config.TREND_MAX_LOTS = 0.01, 0.01
        config.TREND_COMPOUND, config.TREND_COMPOUND_UNIT_HKD, config.TREND_COMPOUND_MAX_LOTS = True, 20000.0, 0.05

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(config, k, v)

    def test_default_off(self):
        config.TREND_COMPOUND = False
        self.assertEqual(trend_live.lots({"equity": 999999.0}), 0.01)
        self.assertEqual(trend_live.lots(), 0.01)

    def test_unit_zero_is_off(self):
        config.TREND_COMPOUND_UNIT_HKD = 0.0
        self.assertEqual(trend_live.lots({"equity": 999999.0}), 0.01)

    def test_steps(self):
        for eq, want in ((5000, 0.01), (19999, 0.01), (20000, 0.01), (39999, 0.01), (40000, 0.02), (59999.9, 0.02), (60000, 0.03), (100000, 0.05)):
            self.assertEqual(trend_live.lots({"equity": float(eq)}), want, eq)

    def test_cap(self):
        self.assertEqual(trend_live.lots({"equity": 10_000_000.0}), 0.05)
        config.TREND_COMPOUND_MAX_LOTS = 0.02
        self.assertEqual(trend_live.lots({"equity": 10_000_000.0}), 0.02)

    def test_shrinks_when_equity_falls(self):
        self.assertEqual(trend_live.lots({"equity": 61000.0}), 0.03)
        self.assertEqual(trend_live.lots({"equity": 41000.0}), 0.02)
        self.assertEqual(trend_live.lots({"equity": 15000.0}), 0.01)

    def test_bad_equity_falls_back(self):
        for eq in (None, 0, -5.0, float("nan"), float("inf"), "30000", True):
            self.assertEqual(trend_live.lots({"equity": eq}), 0.01, repr(eq))
        self.assertEqual(trend_live.lots({}), 0.01)
        self.assertEqual(trend_live.lots(None), 0.01)

    def test_never_below_fixed(self):
        config.TREND_LOTS, config.TREND_MAX_LOTS = 0.02, 0.02
        self.assertEqual(trend_live.lots({"equity": 1000.0}), 0.02)


if __name__ == "__main__":
    unittest.main()
