"""[R355] #145 提早判（使用者 10-30）：P2 止損後 15 分鐘同方向冷靜期；P3 open 指令帶 px／dev，EA v0.41 不利偏離 > 1.5 唔開。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, rules, executor   # noqa: E402

T = 1_800_000_000.0


class Cooldown(unittest.TestCase):
    def test_default(self):
        self.assertEqual(config.SL_COOLDOWN_MIN, 15)

    def test_same_side_loss_blocked(self):
        why = rules.sl_cooldown({"side": -1, "closed_ts": T, "pnl": -120.0}, -1, T + 5 * 60)
        self.assertIn("冷靜期", why)

    def test_opposite_side_ok(self):
        self.assertIsNone(rules.sl_cooldown({"side": -1, "closed_ts": T, "pnl": -120.0}, 1, T + 60))

    def test_win_ok(self):
        self.assertIsNone(rules.sl_cooldown({"side": -1, "closed_ts": T, "pnl": 80.0}, -1, T + 60))

    def test_expired_ok(self):
        self.assertIsNone(rules.sl_cooldown({"side": 1, "closed_ts": T, "pnl": -50.0}, 1, T + 15 * 60 + 1))

    def test_none_and_off(self):
        self.assertIsNone(rules.sl_cooldown(None, 1, T))
        self.assertIsNone(rules.sl_cooldown({"side": 1, "closed_ts": None, "pnl": -1}, 1, T))
        off = type("C", (), {"SL_COOLDOWN_MIN": 0})
        self.assertIsNone(rules.sl_cooldown({"side": 1, "closed_ts": T, "pnl": -50.0}, 1, T + 60, cfg=off))


class SlipGuard(unittest.TestCase):
    def test_default_dev(self):
        self.assertAlmostEqual(config.MAX_ENTRY_SLIP, 1.5 * config.PIP)

    def test_open_text_has_px_dev_before_id(self):
        st = {"lots_level": 0}
        txt = executor.enqueue(st, "OPEN_SHORT", 3995.0, 3980.0, T, "abcdef123456", lots=0.05, note="AI決策", px=3989.28, dev=1.5)
        self.assertIn("|px=3989.28|dev=1.50|id=abcdef12", txt)

    def test_no_px_unchanged(self):
        txt = executor.enqueue({}, "OPEN_LONG", 3980.0, None, T, "abcdef123456", lots=0.05)
        self.assertNotIn("px=", txt)
        self.assertTrue(txt.endswith("|id=abcdef12"))

    def test_ea_v041_checks(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau", "mt5", "TianfuExecutor.mq5"), encoding="utf-8").read()
        self.assertIn('Field(parts, n, "dev")', src)
        self.assertIn("price moved", src)


if __name__ == "__main__":
    unittest.main()
