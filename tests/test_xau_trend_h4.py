"""[IDEAS #1421，使用者 11-13「#1421 轉真倉」] H4 規則 h4macd：純計算＋trend_live.plan 接駁（唔掂 GCS、唔收發心跳）。
同研究版逐根對拍喺 research/strategy_search/parity_h4macd.py（PARITY_H4MACD.md：329／329 一致）。"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import trend_h4rules as R  # noqa: E402

K0 = 123000 * 6            # 一個 UTC 日開頭嘅 H4 key（×14400 係 86400 嘅倍數）


def mk(closes, k0=K0, spread=2.0):
    return [(k0 + i, {"o": c, "h": c + spread, "l": c - spread, "c": c}) for i, c in enumerate(closes)]


def wave(n=240):
    return [4000 + 60 * math.sin(i / 9.0) for i in range(n)]


def crosses(bars, side):
    h = R.macd_hist([r["c"] for _, r in bars])
    return [i for i in range(R.MIN_BARS, len(bars)) if side * h[i] > 0 and side * h[i - 1] <= 0]


class Rule(unittest.TestCase):
    def test_merge_and_eligible(self):
        t = K0 * R.H4
        h4 = R.h4_merge({}, [{"t": t + 60, "open": 2, "high": 3, "low": 1, "close": 2.5}, {"t": t, "open": 1.9, "high": 2.1, "low": 1.8, "close": 2.0},
                             {"t": t + R.H4, "open": 2.5, "high": 2.6, "low": 2.4, "close": 2.55}])
        self.assertEqual(h4[str(K0)], {"o": 1.9, "h": 3, "l": 1, "c": 2.5, "t0": t, "t1": t + 60}); self.assertEqual(len(h4), 2)
        self.assertEqual(len(R.h4_merge({str(i): {"o": 1, "h": 1, "l": 1, "c": 1, "t0": 0, "t1": 0} for i in range(10)}, [], keep=4)), 4)
        self.assertEqual([R.eligible(K0 + j) for j in range(6)], [False, False, True, True, True, False])   # 00、04 唔做；08、12、16 做；20 唔做

    def test_signal_only_on_eligible_cross_in_state_direction(self):
        bars = mk(wave()); ups = crosses(bars, 1); dns = crosses(bars, -1)
        self.assertTrue(ups and dns)
        hit = miss = 0
        for i in ups:
            done = bars[:i + 1]; sig = R.signal("h4macd", done, 1, 30.0)
            if R.eligible(done[-1][0]):
                hit += 1; self.assertEqual(sig["side"], 1)
                a = R.atr(done)[-1]; self.assertAlmostEqual(sig["risk"], max(2 * a, 3.0, 9.0))
                self.assertIsNone(R.signal("h4macd", done, 0, 30.0)); self.assertIsNone(R.signal("h4macd", done, -1, 30.0))   # 日線冇方向／方向相反唔做
                self.assertIsNone(R.signal("h4macd", done, 1, None)); self.assertIsNone(R.signal("h4macd", done[:-1], 1, 30.0))
                po = R.plan_open("h4macd", done, 1, 30.0, 4010.0)
                self.assertEqual((po["side"], po["period"], po["sl"]), (1, done[-1][0] + 1, round(4010.0 - sig["risk"], 2)))
            else:
                miss += 1; self.assertIsNone(R.signal("h4macd", done, 1, 30.0))
        self.assertTrue(hit and miss)
        short = [i for i in dns if R.eligible(bars[i][0])]
        self.assertEqual(R.signal("h4macd", bars[:short[0] + 1], -1, 30.0)["side"], -1)                 # 鏡像做空
        self.assertEqual(R.signal("h4macd", bars[:short[0] + 1], -1, 300.0)["risk"], 90.0)             # 0.3×D1 ATR 下限
        self.assertIsNone(R.signal("h4macd", mk(wave(100)), 1, 30.0))                                  # K 線唔夠

    def test_exit_trail_and_day_flip(self):
        c = [4000 + i for i in range(60)]; bars = mk(c); e = bars[40][0]
        pos = {"rule": "h4macd", "side": 1, "period": e}; today = (e * R.H4) // 86400
        self.assertIsNone(R.plan_exit(pos, bars, 1, today))
        self.assertIsNone(R.plan_exit(pos, bars, 0, today))                                           # 入場同一日：狀態變咗都要等新一日
        self.assertIn("狀態", R.plan_exit(pos, bars, 0, today + 1)); self.assertIn("狀態", R.plan_exit(pos, bars, -1, today + 1))
        drop = mk(c + [c[-1] - 30]); self.assertIn("20 根", R.plan_exit(pos, drop, 1, today))           # 收市穿 20 根最低收市
        self.assertIsNone(R.plan_exit({**pos, "period": drop[-1][0] + 1}, drop, 1, today))             # 入場之前嘅穿位唔計
        self.assertIsNone(R.plan_exit({"rule": "td", "side": 1, "period": e}, drop, 0, today + 5))
        up = mk([4000 - i for i in range(60)] + [4000 - 59 + 30])                                     # 做空：收市穿 20 根最高收市
        self.assertIn("20 根", R.plan_exit({"rule": "h4macd", "side": -1, "period": up[40][0]}, up, -1, (up[40][0] * R.H4) // 86400))


class Live(unittest.TestCase):
    def setUp(self):
        import config
        import trend_live as T
        self.T, self.cfg = T, config
        self.old = (config.TREND_MAGIC, config.TREND_RULES, config.TREND_BOOKS, config.SYMBOL, T.H4R.day_ctx)
        config.TREND_MAGIC, config.TREND_RULES, config.TREND_BOOKS, config.SYMBOL = 944, ("h4macd",), (), "XAUUSD"
        T.H4R.day_ctx = lambda days: (1, 30.0)

    def tearDown(self):
        c = self.cfg
        c.TREND_MAGIC, c.TREND_RULES, c.TREND_BOOKS, c.SYMBOL, self.T.H4R.day_ctx = self.old

    def test_plan_open_window_and_exit(self):
        T = self.T; bars = mk(wave()); i = next(j for j in crosses(bars, 1) if R.eligible(bars[j][0]))
        done = bars[:i + 1]; key = done[-1][0] + 1; t0 = key * R.H4
        h4 = {str(k): {**r, "t0": k * R.H4, "t1": k * R.H4 + 239 * 60} for k, r in done}
        h4[str(key)] = {"o": 4010, "h": 4011, "l": 4009, "c": 4010, "t0": t0, "t1": t0 + 60}
        day = t0 // 86400; days = [(day - 1, {"o": 1, "h": 1, "l": 1, "c": 1, "t0": 0, "t1": 0}), (day, {"o": 1, "h": 1, "l": 1, "c": 1, "t0": t0, "t1": t0 + 60})]
        st = {**T.empty_state(), "h4": h4, "d1": {str(d): r for d, r in days}}
        act, why = T.plan(st, days, None, 4010.0, t0 + 90, None, [])
        self.assertEqual(act[0], "open"); self.assertEqual((act[1]["rule"], act[1]["side"], act[1]["period"]), ("h4macd", 1, key)); self.assertIn("#1421", why)
        self.assertIsNone(T.plan(st, days, None, 4010.0, t0 + 90, "EA dry_run", [])[0])                 # 被擋唔開
        self.assertIsNone(T.plan({**st, "used": {"h4macd": key}}, days, None, 4010.0, t0 + 90, None, [])[0])   # 呢根已用
        late = {**st, "d1": {**st["d1"], str(day): {**days[-1][1], "t1": t0 + 1000}}}
        self.assertIsNone(T.plan(late, days, None, 4010.0, t0 + 1000, None, [])[0])                     # 遲過 15 分鐘唔追
        pos = {"rule": "h4macd", "side": 1, "sl": 3950.0, "period": key, "ts": t0 + 90}
        live = [{"side": 1, "lots": 0.01, "entry": 4010.0, "stop": 3950.0}]
        self.assertIsNone(T.plan({**st, "pos": pos}, days, live[0], 4010.0, t0 + 300, None, [])[0])     # 有倉、冇出場條件
        T.H4R.day_ctx = lambda d: (0, 30.0)
        nxt = days + [(day + 1, {"o": 1, "h": 1, "l": 1, "c": 1, "t0": 0, "t1": 0})]
        act, why = T.plan({**st, "pos": pos}, nxt, live[0], 4010.0, (day + 1) * 86400 + 60, None, [])
        self.assertEqual(act[0], "close"); self.assertIn("狀態", why)

    def test_seed_only_for_gold(self):
        T = self.T; seed = T.load_h4_seed()
        self.assertGreaterEqual(len(seed), 300); self.assertTrue(all(r["c"] > 1000 for r in seed.values()))
        self.cfg.SYMBOL = "XAGUSD"; self.assertEqual(T.load_h4_seed(), {})
        self.assertTrue(T.has_h4()); self.assertIn("h4macd", T.NAMES)


if __name__ == "__main__":
    unittest.main()
