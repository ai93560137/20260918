"""[R368] 921 逆 H4 唔做多（XAU_H4_TREND_FILTER）：H4 EMA50 斜率計法、擋單規則、訊號書唔受影響、斜率計唔到唔擋。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, h4_trend   # noqa: E402

T0 = 1_790_000_000 // 14400 * 14400 + 7200      # 22:00 UTC 對齊嘅 H4 開盤


def m1_series(step, n_h4=70):
    out = []
    for i in range(n_h4 * 240):
        t = T0 + i * 60
        c = 4000 + step * i / 240
        out.append((t, c, c + 0.2, c - 0.2, c))
    return out


class R368(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(config.H4_TREND_FILTER, "off")
        self.assertIsNone(h4_trend.block_reason("OPEN_LONG", T0, slope_fn=lambda n: -1.0))

    def test_slope_sign(self):
        up = m1_series(+1.0); dn = m1_series(-1.0); now = up[-1][0] + 60
        s_up, k, n = h4_trend.slope_from_m1(up, now)
        s_dn, _, _ = h4_trend.slope_from_m1(dn, now)
        self.assertGreater(s_up, 0); self.assertLess(s_dn, 0); self.assertGreaterEqual(n, 51)
        self.assertEqual(k, h4_trend.current_h4_key(now))

    def test_not_enough(self):
        s, _, n = h4_trend.slope_from_m1(m1_series(1.0, n_h4=20), T0 + 20 * 14400)
        self.assertIsNone(s); self.assertLess(n, 51)

    def test_long_mode(self):
        f = lambda s: (lambda now: s)   # noqa: E731
        self.assertIn("逆 H4 唔做多", h4_trend.block_reason("OPEN_LONG", T0, mode="long", slope_fn=f(-0.5)))
        self.assertIsNone(h4_trend.block_reason("OPEN_LONG", T0, mode="long", slope_fn=f(0.5)))
        self.assertIsNone(h4_trend.block_reason("OPEN_SHORT", T0, mode="long", slope_fn=f(0.5)))   # long 模式唔擋做空
        self.assertIsNone(h4_trend.block_reason("UPDATE_STOP", T0, mode="long", slope_fn=f(-0.5)))
        self.assertIsNone(h4_trend.block_reason("OPEN_LONG", T0, mode="long", slope_fn=f(None)))   # 計唔到唔擋

    def test_both_mode(self):
        self.assertIn("逆 H4 唔做空", h4_trend.block_reason("OPEN_SHORT", T0, mode="both", slope_fn=lambda n: 0.5))
        self.assertIn("逆 H4 唔做多", h4_trend.block_reason("OPEN_LONG", T0, mode="both", slope_fn=lambda n: -0.5))

    def test_signal_book_exempt(self):
        old = config.SIGNAL_BOOK
        config.SIGNAL_BOOK = True
        try:
            self.assertIsNone(h4_trend.block_reason("OPEN_LONG", T0, mode="long", slope_fn=lambda n: -1.0))
        finally:
            config.SIGNAL_BOOK = old


if __name__ == "__main__":
    unittest.main()
