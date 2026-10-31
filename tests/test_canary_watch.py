"""canary/watch_list.py 的單元測試:四條留神規則的亮滅、綜合等級、缺值、輸出檔(同燈色日覆蓋)。

執行:python3 -m unittest tests/test_canary_watch.py -v(全程假資料,不連網)
"""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "canary"))

import watch_list as wl  # noqa: E402

DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23",
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def rows(short_by_day=None, p95="122.70"):
    short_by_day = short_by_day or {}
    return [{"date": d, "axis_short": short_by_day.get(d, "綠"), "axis_disaster": "綠", "vvix_p95": p95} for d in DAYS]


def alert(day, to="紅", axis="短期軸", kind="盤中預警"):
    return {"kind": kind, "day": day, "axis": axis, "to": to}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.bird("vix", "2026-10-30", 23.93, 19.42)
        self.bird("vvix", "2026-10-30", 124.06, 106.43)

    def bird(self, name, day, high, close):
        with open(os.path.join(self.data, f"{name}_daily.csv"), "w", newline="") as fh:
            fh.write("Date,Open,High,Low,Close\n")
            fh.write(f"2026-10-29,1,1,1,1\n{day},{close},{high},{close},{close}\n")

    def test_all_four_lit(self):
        st = wl.compute(rows(), [alert("2026-10-23"), alert("2026-10-26", kind="盤中預警(手動)"), alert("2026-10-30")],
                        [{"light_date": "2026-10-23", "ratio": "1.4824"}], self.data)
        self.assertEqual(st["lit"], 4)
        self.assertEqual(st["level"], "加強留神")
        self.assertIn("3 日(10-23(五)、10-26(一)、10-30(五))", st["rules"][0]["value"])
        self.assertIn("23.93 − 收市 19.42 = 4.51", st["rules"][1]["value"])

    def test_l1_counts_close_red_and_ignores_outside_window_and_other_axes(self):
        r = rows({"2026-10-21": "紅"})
        alerts = [alert("2026-10-16"), alert("2026-10-27", to="走平"), alert("2026-10-28", axis="災難軸", to="深紅"),
                  alert("2026-10-29"), alert("2026-10-21")]
        st = wl.compute(r, alerts, [], self.data)
        l1 = st["rules"][0]
        self.assertFalse(l1["lit"])              # 只有 10-21、10-29 兩日
        self.assertIn("2 日", l1["value"])

    def test_thresholds_off(self):
        self.bird("vix", "2026-10-30", 21.0, 19.0)      # 差 2.0 < 3.0
        self.bird("vvix", "2026-10-30", 120.0, 110.0)   # 120 < p95 122.70
        st = wl.compute(rows(), [], [{"light_date": "2026-10-23", "ratio": "1.29"}], self.data)
        self.assertEqual(st["lit"], 0)
        self.assertEqual(st["level"], "平常")

    def test_one_lit_is_normal_two_is_heightened(self):
        self.bird("vvix", "2026-10-30", 120.0, 110.0)
        st = wl.compute(rows(), [], [], self.data)       # 只得 L2
        self.assertEqual((st["lit"], st["level"]), (1, "平常"))
        st = wl.compute(rows(), [], [{"light_date": "2026-10-23", "ratio": "1.30"}], self.data)
        self.assertEqual((st["lit"], st["level"]), (2, "加強留神"))

    def test_missing_data_is_not_lit(self):
        st = wl.compute(rows(p95=""), [], [], os.path.join(self.tmp, "nowhere"))
        self.assertEqual(st["lit"], 0)
        self.assertEqual(st["rules"][1]["value"], "缺值")
        self.assertEqual(st["rules"][3]["value"], "未有後驗")

    def test_outputs_overwrite_same_light_date(self):
        st = wl.compute(rows(), [], [], self.data)
        j, lg = os.path.join(self.tmp, "w.json"), os.path.join(self.tmp, "w.csv")
        wl.write_outputs(st, "2026-10-31T01:41Z", j, lg)
        wl.write_outputs(st, "2026-10-31T02:00Z", j, lg)
        with open(lg, newline="") as fh:
            got = list(csv.DictReader(fh))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["generated_at_utc"], "2026-10-31T02:00Z")
        pub = json.load(open(j))
        self.assertNotIn("_log", pub)
        self.assertEqual(pub["light_date"], "2026-10-30")

    def test_tg_lines(self):
        st = wl.compute(rows(), [], [], self.data)
        lines = wl.tg_lines(st)
        self.assertTrue(lines[0].startswith("👀 留神清單(觀察名單,無警報權)|"))
        self.assertEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main()
