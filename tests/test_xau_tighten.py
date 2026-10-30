"""[R354] UPDATE_STOP 只准收緊：10-30 L26 AI「止損放闊至6美元」把 SELL 止損 3991.80 放到 3992.70 冇被擋。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, rules   # noqa: E402

SHORT = {"side": -1, "entry": 3986.64, "stop": 3991.80, "target": 3975.00, "lots": 0.05}
LONG = {"side": 1, "entry": 4000.00, "stop": 3994.00, "target": 4010.00, "lots": 0.05}


def upd(pos, stop, last, target=None):
    return rules.validate_decision({"action": "UPDATE_STOP", "stop_price": stop, "target_price": target, "confidence": 0.7},
                                   position=pos, last=last, can_open=True, trades_today=0)


class TightenOnly(unittest.TestCase):
    def test_default_on(self):
        self.assertTrue(config.STOP_TIGHTEN_ONLY)

    def test_l26_loosen_blocked(self):
        a, s, t, why = upd(SHORT, 3992.70, 3987.11)
        self.assertEqual((a, s), ("HOLD", None))
        self.assertIn("只准收緊", why)

    def test_short_tighten_ok(self):
        a, s, t, why = upd(SHORT, 3986.64, 3981.35)
        self.assertEqual((a, s, why), ("UPDATE_STOP", 3986.64, None))

    def test_long_loosen_blocked_and_tighten_ok(self):
        self.assertEqual(upd(LONG, 3992.00, 4001.0)[0], "HOLD")
        self.assertEqual(upd(LONG, 3996.00, 4005.0)[:2], ("UPDATE_STOP", 3996.00))

    def test_same_stop_noop(self):
        a, s, t, why = upd(LONG, 3994.00, 4003.0)
        self.assertEqual(a, "HOLD")
        self.assertIn("一樣", why)

    def test_no_current_stop_allowed(self):
        self.assertEqual(upd({**LONG, "stop": None}, 3990.0, 4003.0)[0], "UPDATE_STOP")

    def test_switch_off_allows_loosen(self):
        keep = config.STOP_TIGHTEN_ONLY
        try:
            config.STOP_TIGHTEN_ONLY = False
            self.assertEqual(upd(SHORT, 3992.70, 3987.11)[0], "UPDATE_STOP")
        finally:
            config.STOP_TIGHTEN_ONLY = keep


if __name__ == "__main__":
    unittest.main()
