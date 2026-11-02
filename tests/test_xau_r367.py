"""[R367] IDEAS #212（使用者 11-02「而家直接更新用新方法」）：921 止蝕止賺距離 × XAU_SLTP_WIDEN；手數由按風險計自動 ÷k；
浮盈未到 1R 唔准 AI 收緊；訊號書（931）唔受影響。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, risk_size, rules   # noqa: E402


class Widen(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(config.SLTP_WIDEN, 1.0)
        self.assertEqual(rules.widen_k(), 1.0)

    def test_k_and_signal_book(self):
        C = type("C", (), {"SLTP_WIDEN": 1.5, "SIGNAL_BOOK": False})
        self.assertEqual(rules.widen_k(C), 1.5)
        S = type("S", (), {"SLTP_WIDEN": 1.5, "SIGNAL_BOOK": True})
        self.assertEqual(rules.widen_k(S), 1.0)
        L = type("L", (), {"SLTP_WIDEN": 0.5, "SIGNAL_BOOK": False})
        self.assertEqual(rules.widen_k(L), 1.0)

    def test_levels_long_short(self):
        self.assertEqual(rules.widen_levels(4000.0, 1, 3994.0, 4010.0, 1.5), (3991.0, 4015.0))
        self.assertEqual(rules.widen_levels(4000.0, -1, 4006.0, 3994.0, 1.5), (4009.0, 3991.0))
        self.assertEqual(rules.widen_levels(4000.0, -1, 4006.0, None, 1.5), (4009.0, None))
        self.assertEqual(rules.widen_levels(4000.0, 1, 3994.0, 4010.0, 1.0), (3994.0, 4010.0))

    def test_lots_divide_by_k(self):
        old = (config.RISK_SIZING, config.RISK_PCT)
        config.RISK_SIZING, config.RISK_PCT = True, 10
        try:
            base, _ = risk_size.size(30000, 4000.0, 4006.0, 0.05)
            wide, info = risk_size.size(30000, 4000.0, 4009.0, 0.05)
            self.assertLessEqual(wide, base)
            self.assertAlmostEqual(info["per_lot_hkd"] * 1.0, 1.5 * risk_size.per_lot_loss_hkd(4000.0, 4006.0), places=4)
        finally:
            config.RISK_SIZING, config.RISK_PCT = old

    def test_update_block(self):
        pos = {"side": -1, "entry": 4000.0, "stop": 4009.0}
        self.assertIn("放闊", rules.widen_update_block(pos, 3995.0, 4009.0, 1.5))     # 浮盈 5 < 1R 9
        self.assertIsNone(rules.widen_update_block(pos, 3990.0, 4009.0, 1.5))         # 浮盈 10 ≥ 9
        self.assertIsNone(rules.widen_update_block(pos, 3995.0, 4009.0, 1.0))         # 冇放闊
        self.assertIsNone(rules.widen_update_block(pos, 3995.0, None, 1.5))           # 冇初始止蝕紀錄


if __name__ == "__main__":
    unittest.main()
