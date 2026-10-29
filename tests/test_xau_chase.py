"""[R351] MILESTONES M1 硬規則（使用者 10-30 批）：急跌 ≥6 後 15 分鐘內、決策價離低位 ≥3 嘅反抽沽一律擋；急升後回落買對稱。
K 線係 GCS xau/bars/ 嘅真實 M1（只留高低位）：L12／L18 要擋、L17／L19 唔擋。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, rules   # noqa: E402

CASES = {   # 決策價、開倉前 15 根 M1（含決策嗰根）嘅 (高, 低)
    "L12": (4054.88, [(4060.34, 4058.12), (4059.22, 4054.98), (4056.63, 4054.75), (4056.05, 4054.26), (4057.25, 4054.98), (4057.2, 4053.18), (4053.48, 4051.03), (4054.6, 4052.67), (4055.03, 4053.62), (4055.3, 4053.9), (4055.4, 4053.34), (4054.79, 4053.17), (4056.98, 4054.62), (4057.6, 4055.66), (4056.54, 4054.74)]),
    "L17": (4029.21, [(4026.37, 4022.86), (4029.41, 4025.93), (4030.49, 4029.06), (4031.12, 4030.04), (4033.71, 4030.55), (4034.39, 4032.49), (4034.54, 4031.8), (4034.29, 4032.51), (4034.59, 4033.41), (4034.03, 4032.47), (4034.71, 4032.58), (4035.18, 4034.0), (4034.04, 4032.1), (4033.18, 4031.06), (4031.33, 4029.05)]),
    "L18": (4014.77, [(4021.55, 4020.41), (4021.17, 4019.71), (4021.55, 4019.87), (4020.79, 4019.96), (4020.27, 4019.26), (4019.97, 4018.78), (4019.52, 4017.67), (4018.05, 4014.86), (4017.29, 4014.78), (4015.69, 4013.42), (4013.75, 4010.45), (4012.93, 4010.14), (4015.66, 4012.19), (4017.05, 4015.33), (4015.96, 4014.77)]),
    "L19": (4008.33, [(4013.73, 4012.82), (4014.54, 4013.01), (4013.68, 4011.59), (4012.14, 4010.14), (4013.54, 4010.25), (4014.15, 4012.37), (4012.84, 4010.17), (4010.74, 4009.03), (4009.9, 4007.98), (4009.28, 4008.3), (4010.26, 4008.23), (4010.3, 4009.14), (4009.13, 4007.91), (4008.67, 4007.91), (4008.49, 4007.84)]),
}
T0 = 1793200000


def bars(hl, t0=T0):
    return [{"time": t0 + i * 60, "open": (h + l) / 2, "high": h, "low": l, "close": (h + l) / 2} for i, (h, l) in enumerate(hl)]


def mirror(hl, pivot=8000.0):
    return [(pivot - l, pivot - h) for h, l in hl]


class ChaseBlock(unittest.TestCase):
    def test_defaults(self):
        self.assertTrue(config.CHASE_BLOCK)
        self.assertEqual((config.CHASE_WINDOW_MIN, config.CHASE_MOVE_USD, config.CHASE_BACK_USD), (15, 6.0, 3.0))

    def test_l12_l18_blocked(self):
        for name in ("L12", "L18"):
            price, hl = CASES[name]
            why = rules.chase_block(bars(hl), -1, price)
            self.assertIsNotNone(why, name)
            self.assertIn("唔准反抽沽", why)

    def test_l17_l19_not_blocked(self):
        for name in ("L17", "L19"):        # L17：低位喺高位之前；L19：決策價貼低位（0.49）
            price, hl = CASES[name]
            self.assertIsNone(rules.chase_block(bars(hl), -1, price), name)

    def test_buy_side_not_affected_by_drop(self):
        price, hl = CASES["L18"]
        self.assertIsNone(rules.chase_block(bars(hl), 1, price))

    def test_symmetric_buy(self):
        for name, blocked in (("L12", True), ("L18", True), ("L17", False), ("L19", False)):
            price, hl = CASES[name]
            why = rules.chase_block(bars(mirror(hl)), 1, 8000.0 - price)
            self.assertEqual(why is not None, blocked, name)
            if blocked:
                self.assertIn("唔准回落買", why)

    def test_window_only_last_15_minutes(self):
        price, hl = CASES["L18"]
        old = bars(hl, T0 - 3600)            # 一個鐘前嘅急跌：唔計
        flat = bars([(price + 0.5, price - 0.5)] * 15, T0)
        self.assertIsNone(rules.chase_block(old + flat, -1, price))

    def test_same_bar_high_low_not_counted(self):
        self.assertIsNone(rules.chase_block(bars([(4020.0, 4010.0)]), -1, 4015.0))

    def test_switch_off(self):
        price, hl = CASES["L18"]
        cfg = type("C", (), {k: getattr(config, k) for k in dir(config) if k.isupper()})
        cfg.CHASE_BLOCK = False
        self.assertIsNone(rules.chase_block(bars(hl), -1, price, cfg=cfg))

    def test_thresholds(self):
        hl = [(4020.0, 4019.0), (4016.0, 4014.0), (4017.0, 4015.0)]
        self.assertIsNone(rules.chase_block(bars(hl), -1, 4016.99))   # 反抽 2.99 < 3
        self.assertIsNotNone(rules.chase_block(bars(hl), -1, 4017.0))  # 反抽 3.00
        self.assertIsNone(rules.chase_block(bars([(4019.99, 4019.0), (4016.0, 4014.0)]), -1, 4017.5))   # 跌 5.99 < 6


if __name__ == "__main__":
    unittest.main()
