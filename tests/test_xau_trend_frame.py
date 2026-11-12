"""[11-12] 長線框架四條（tdrsi #1273／tdsurge #1285／tdx50 #1290／tdflip #1300）真倉規則：純計算測試（唔掂 GCS）。
同研究版逐日對拍喺 research/strategy_search/parity_frame.py（PARITY_FRAME.md）。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import trend_d1rules as D1R  # noqa: E402


def mk(closes, spread=2.0):
    return [(20000 + i, {"o": c, "h": c + spread, "l": c - spread, "c": c}) for i, c in enumerate(closes)]


def up(n=250):
    return [1000 + i * 1.0 for i in range(n)]


def flip(c):
    return [3000 - x for x in c]


class Frame(unittest.TestCase):
    def test_registered(self):
        for r in D1R.FRAME:
            self.assertIn(r, D1R.RULES); self.assertEqual(D1R.MAX_BARS[r], 250); self.assertIn("#", D1R.NAMES[r])

    def test_tdflip_recross_sma20_both_sides(self):
        c = up(); c += [c[-1] - 6, c[-1] - 12, c[-1] - 18, c[-1] - 24]; c += [c[-1] + 30]
        self.assertIsNone(D1R.signal("tdflip", mk(c[:-1])))
        sig = D1R.signal("tdflip", mk(c)); self.assertEqual(sig["side"], 1)
        self.assertAlmostEqual(sig["risk"], 3 * D1R.atr(mk(c))[-1])
        self.assertEqual(D1R.signal("tdflip", mk(flip(c)))["side"], -1)          # 鏡像做空
        self.assertEqual(D1R.signal("tdflip", mk(c + [c[-1] - 20, c[-1] + 5]))["side"], 1)   # 事件版：再穿再出

    def test_tdflip_exit_only_sma200(self):
        c = up(); days = mk(c + [c[-1] - 40])                                  # 穿 20 日低但仲喺 SMA200 上
        self.assertIsNone(D1R.exit_hit("tdflip", 1, days))
        self.assertIsNotNone(D1R.exit_hit("tdrsi", 1, days))                   # 20 日出場
        self.assertIsNotNone(D1R.exit_hit("tdx50", 1, days))                   # 10 日出場
        self.assertIn("SMA200", D1R.exit_hit("tdflip", 1, mk(c + [c[-1] - 200])))
        self.assertIn("SMA200", D1R.exit_hit("tdflip", -1, mk(flip(c) + [flip(c)[-1] + 200])))

    def test_exit_window_10_vs_20(self):
        c = up(); c += [c[-1] - 30] * 12; days = mk(c + [c[-1] - 1])           # 穿 10 日低；20 日窗仲包住之前高位後嘅低位
        self.assertIsNotNone(D1R.exit_hit("tdsurge", 1, days))
        c2 = up(); c2 += [c2[-1] - 30, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 5, c2[-1] - 10]
        self.assertIsNotNone(D1R.exit_hit("tdsurge", 1, mk(c2)))               # 穿之前 10 日低（−30 嗰日已出窗）
        self.assertIsNone(D1R.exit_hit("tdrsi", 1, mk(c2)))                    # 20 日窗仲包住 −30

    def test_tdsurge_needs_big_day(self):
        c = up(); a = D1R.atr(mk(c))[-1]
        self.assertIsNone(D1R.signal("tdsurge", mk(c + [c[-1] + 1.4 * a])))
        self.assertEqual(D1R.signal("tdsurge", mk(c + [c[-1] + 1.6 * a]))["side"], 1)
        self.assertIsNone(D1R.signal("tdsurge", mk(c + [c[-1] - 1.6 * a])))    # SMA200 上面唔做空
        f = flip(c); self.assertEqual(D1R.signal("tdsurge", mk(f + [f[-1] - 1.6 * a]))["side"], -1)

    def test_tdx50_cross(self):
        c = up(); c += [c[-1] - 40, c[-1] - 45]                                # 跌穿 SMA50（仲喺 SMA200 上）
        self.assertIsNone(D1R.signal("tdx50", mk(c)))
        self.assertEqual(D1R.signal("tdx50", mk(c + [c[-1] + 60]))["side"], 1)

    def test_tdrsi_cross_40(self):
        c = up(); c += [c[-1] - 8 * k for k in range(1, 9)]                     # 連跌：RSI 落 40 以下
        r = D1R.rsi(c); self.assertLess(r[-1], 40)
        self.assertIsNone(D1R.signal("tdrsi", mk(c)))
        c2 = c + [c[-1] + 60]; r2 = D1R.rsi(c2); self.assertGreater(r2[-1], 40)
        self.assertEqual(D1R.signal("tdrsi", mk(c2))["side"], 1)
        self.assertIsNone(D1R.signal("tdrsi", mk(c2 + [c2[-1] + 5])))           # 已經喺 40 上：唔再出

    def test_short_history_no_signal(self):
        for r in D1R.FRAME:
            self.assertIsNone(D1R.signal(r, mk(up(150))))

    def test_plan_open_and_exit(self):
        c = up(); c += [c[-1] - 40, c[-1] - 45, c[-1] + 15]; days = mk(c)
        po = D1R.plan_open("tdx50", days, c[-1])
        self.assertEqual(po["rule"], "tdx50"); self.assertLess(po["sl"], c[-1])
        pos = {"rule": "tdx50", "side": 1, "period": days[-1][0]}
        self.assertIsNone(D1R.plan_exit(pos, mk(c + [c[-1] + 1])))
        self.assertIsNotNone(D1R.plan_exit(pos, mk(c + [c[-1] - 300])))


if __name__ == "__main__":
    unittest.main()
