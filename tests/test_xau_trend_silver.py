"""[IDEAS #1442，使用者 11-12「#1442 白銀真倉」] 白銀趨勢簿：只做多、最低止蝕按產品、報價 3 位小數、種子按產品、唔收星期日 K 線。
純計算測試（唔掂 GCS）。同研究版對拍喺 research/strategy_search/parity_silver.py。"""
import importlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import trend_d1rules as D1R  # noqa: E402


def mk(closes, spread=0.2):
    return [(20000 + i, {"o": c, "h": c + spread, "l": c - spread, "c": c}) for i, c in enumerate(closes)]


def up(n=250):
    return [20 + i * 0.05 for i in range(n)]


class Silver(unittest.TestCase):
    def test_long_only_blocks_short(self):
        c = up(); c += [c[-1] + 3.0]                                # 單日大升 → 做多訊號
        days = mk(c); self.assertEqual(D1R.signal("tdsurge", days)["side"], 1)
        self.assertEqual(D1R.plan_open("tdsurge", days, c[-1], long_only=True, min_abs=0.0, digits=3)["side"], 1)
        f = [100 - x for x in c]; days = mk(f)                      # 鏡像 → 做空訊號
        self.assertEqual(D1R.signal("tdsurge", days)["side"], -1)
        self.assertIsNone(D1R.plan_open("tdsurge", days, f[-1], long_only=True, min_abs=0.0, digits=3))
        self.assertEqual(D1R.plan_open("tdsurge", days, f[-1])["side"], -1)   # 預設（黃金）照舊雙向

    def test_floor_and_digits(self):
        c = up(); c += [c[-1] + 3.0]; days = mk(c); a = D1R.atr(days)
        po = D1R.plan_open("tdsurge", days, c[-1], long_only=True, min_abs=0.0, digits=3)
        self.assertAlmostEqual(po["risk"], round(3 * a[-1], 3)); self.assertLess(po["risk"], 3.0)   # 冇被黃金嘅 3 美元下限拉闊
        self.assertEqual(po["sl"], round(c[-1] - 3 * a[-1], 3))
        self.assertEqual(D1R.plan_open("tdsurge", days, c[-1])["risk"], 3.0)                      # 預設（黃金）下限照舊 3
        self.assertEqual(D1R.floor(days, 0.0), 0.3 * a[-2]); self.assertEqual(D1R.floor(days), 3.0)

    def _cfg(self, sym):
        old = os.environ.get("XAU_SYMBOL"); os.environ["XAU_SYMBOL"] = sym
        try:
            import config
            return importlib.reload(config)
        finally:
            if old is None:
                os.environ.pop("XAU_SYMBOL", None)
            else:
                os.environ["XAU_SYMBOL"] = old

    def test_config_by_product(self):
        import config
        try:
            c = self._cfg("XAGUSD")
            self.assertEqual((c.PRODUCT_KIND, c.PREFIX, c.PRICE_DIGITS, c.TREND_MIN_SL_ABS, c.TREND_DROP_SUNDAY, c.TREND_LONG_ONLY), ("silver", "xag/", 3, 0.0, True, False))
            c = self._cfg("XAUUSD")
            self.assertEqual((c.PRODUCT_KIND, c.PREFIX, c.TREND_MIN_SL_ABS, c.TREND_DROP_SUNDAY, c.TREND_LONG_ONLY), ("gold", "xau/", 3.0, False, False))
        finally:
            importlib.reload(config)

    def test_seed_and_sunday(self):
        import config
        import trend_live as TL
        sun, mon = 1794096000 + 22 * 3600, 1794182400 + 3600          # 2026-11-08（日）22:00 UTC、11-09（一）01:00 UTC
        old = (config.SYMBOL, config.TREND_DROP_SUNDAY)
        try:
            config.SYMBOL, config.TREND_DROP_SUNDAY = "XAGUSD", True
            seed = TL.load_seed(); self.assertGreaterEqual(len(seed), 300)
            self.assertTrue(all(20 < r["c"] < 200 for r in seed.values()))                      # 白銀價，唔係黃金
            self.assertFalse(any((int(k) + 3) % 7 in (5, 6) for k in seed))                     # 冇星期六、日
            self.assertTrue(TL.closed_window(sun)); self.assertFalse(TL.closed_window(mon))
            config.SYMBOL = "EURUSD"; self.assertEqual(TL.load_seed(), {})                      # 冇種子嘅產品唔會攞錯
            config.SYMBOL, config.TREND_DROP_SUNDAY = "XAUUSD", False
            self.assertFalse(TL.closed_window(sun)); self.assertTrue(TL.closed_window(sun - 3 * 3600))   # 黃金照舊：星期日 21:00 UTC 後收
            self.assertTrue(all(r["c"] > 1000 for r in TL.load_seed().values()))
        finally:
            config.SYMBOL, config.TREND_DROP_SUNDAY = old


if __name__ == "__main__":
    unittest.main()
