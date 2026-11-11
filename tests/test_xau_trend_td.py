"""[11-11] #1268（td：200 日線方向＋回調重拾 20 日線）真倉規則：純計算測試（唔掂 GCS）；同研究版 topdown_1268 狀態機對拍。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import trend_d1rules as D1R  # noqa: E402


def mk(closes, spread=2.0):
    return [(20000 + i, {"o": c, "h": c + spread, "l": c - spread, "c": c}) for i, c in enumerate(closes)]


def series():
    """250 日慢升（收市一直喺 SMA200 上）→ 跌 4 日穿 SMA20 → 升返上 SMA20。"""
    c = [1000 + i * 1.0 for i in range(250)]
    c += [c[-1] - 6, c[-1] - 12, c[-1] - 18, c[-1] - 24]
    c += [c[-1] + 30]
    return c


class Td(unittest.TestCase):
    def test_signal_on_recross(self):
        c = series(); days = mk(c)
        self.assertIsNone(D1R.signal("td", days[:-1]))                 # 回調緊：未有訊號
        sig = D1R.signal("td", days)
        self.assertEqual(sig["side"], 1); self.assertAlmostEqual(sig["risk"], 3 * D1R.atr(days)[-1])
        po = D1R.plan_open("td", days, c[-1])
        self.assertEqual(po["rule"], "td"); self.assertEqual(po["period"], days[-1][0]); self.assertLess(po["sl"], c[-1])

    def test_no_repeat_while_state_holds(self):
        c = series() + [series()[-1] + 2, series()[-1] + 4]
        self.assertIsNone(D1R.signal("td", mk(c)))                     # 狀態維持：唔再出訊號

    def test_exit_on_20d_low_or_sma200(self):
        c = series(); days = mk(c + [c[-1] + 1])
        pos = {"rule": "td", "side": 1, "period": mk(c)[-1][0]}
        self.assertIsNone(D1R.plan_exit(pos, days))
        low = min(c[-20:]) - 5
        self.assertIn("20 日", D1R.plan_exit(pos, mk(c + [low])))

    def test_needs_history(self):
        self.assertIsNone(D1R.signal("td", mk(series()[:150])))

    def test_short_mirror(self):
        c = [3000 - i * 1.0 for i in range(250)]
        c += [c[-1] + 6, c[-1] + 12, c[-1] + 18, c[-1] + 24]; c += [c[-1] - 30]
        self.assertEqual(D1R.signal("td", mk(c))["side"], -1)

    def test_max_bars(self):
        self.assertEqual(D1R.MAX_BARS["td"], 250); self.assertIn("td", D1R.RULES)


if __name__ == "__main__":
    unittest.main()
