"""白銀趨勢簿日線修復腳本：純函數測試（唔連網、唔掂 GCS）。"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("repair_trend_xag_seed", os.path.join(ROOT, "scripts", "repair_trend_xag_seed.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
D = 86400


def bar(day, o, h, l, c, h0=0, h1=23):
    return {"o": o, "h": h, "l": l, "c": c, "t0": day * D + h0 * 3600, "t1": day * D + h1 * 3600}


class Repair(unittest.TestCase):
    OK = ({"XAU_TREND_LIVE": "0"}, {"pos": None, "pending_cmds": []}, {"positions": [], "symbol": "XAGUSD"})

    def test_refusal(self):
        env, st, ac = self.OK
        self.assertIsNone(R.refusal(env, st, ac)); self.assertIsNone(R.refusal({}, st, ac))
        self.assertIn("XAU_TREND_LIVE", R.refusal({"XAU_TREND_LIVE": "1"}, st, ac))
        self.assertIn("pos", R.refusal(env, {"pos": {"rule": "tdsurge"}}, ac))
        self.assertIn("指令", R.refusal(env, {"pos": None, "pending_cmds": [{"id": "w1"}]}, ac))
        self.assertIn("持倉", R.refusal(env, st, {"positions": [{"ticket": 1}], "symbol": "XAGUSD"}))
        self.assertIn("XAGUSD", R.refusal(env, st, {"positions": [], "symbol": "XAUUSD"}))
        self.assertIn("XAGUSD", R.refusal(env, st, {}))

    def test_new_d1_fills_gap_and_merges_last_day(self):
        cur = {"100": bar(100, 50, 51, 49, 50.5, 0, 17),            # 舊種子：呢日只得 17 小時
               "103": bar(103, 49.8, 50.2, 49.7, 50.0, 7, 12)}      # 心跳砌：只得 5 小時；101、102 冇
        seed = {"99": bar(99, 48, 49, 47, 48.5), "100": bar(100, 50, 52, 49, 51.2), "101": bar(101, 51.2, 52, 50, 50.4),
                "102": bar(102, 50.4, 50.9, 49.5, 49.9), "103": bar(103, 49.9, 50.1, 49.6, 49.8, 0, 9)}
        new = R.new_d1(cur, seed)
        self.assertEqual(sorted(new, key=int), ["99", "100", "101", "102", "103"])
        self.assertEqual(new["100"], seed["100"]); self.assertEqual(new["101"], seed["101"])
        m = new["103"]                                              # 最後一日：種子 00–09 時＋心跳 07–12 時
        self.assertEqual((m["o"], m["h"], m["l"], m["c"], m["t0"], m["t1"]), (49.9, 50.2, 49.6, 50.0, 103 * D, 103 * D + 12 * 3600))
        self.assertEqual(R.gaps(new), []); self.assertEqual(R.gaps(cur), ["1970-04-13"]); self.assertEqual([k for k, _, _ in R.changes(cur, new)], ["99", "100", "101", "102", "103"])

    def test_keeps_days_after_seed_and_caps(self):
        seed = {str(k): bar(k, 1, 2, 0.5, 1.5) for k in range(10, 20)}
        cur = {"19": bar(19, 1, 2, 0.5, 1.5), "20": bar(20, 1.5, 3, 1, 2.5), "5": bar(5, 9, 9, 9, 9)}
        new = R.new_d1(cur, seed, keep=6)
        self.assertEqual(sorted(new, key=int), ["15", "16", "17", "18", "19", "20"]); self.assertEqual(new["20"], cur["20"])
        self.assertEqual(R.new_d1(cur, {}), cur); self.assertEqual(R.changes(new, new), [])
        self.assertEqual(R.gaps({"11": {}, "12": {}, "15": {}, "18": {}}), ["1970-01-14", "1970-01-15"])   # 日 13、14（三、四）缺；16、17 週末唔計

    def test_fmt_has_no_account_info(self):
        line = R.fmt("100", None, bar(100, 50, 51, 49, 50.5))
        self.assertIn("（冇）", line); self.assertIn("C 50.5", line)


if __name__ == "__main__":
    unittest.main()
