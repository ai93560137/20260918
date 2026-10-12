"""scripts/screener_scorecard.py 與 scripts/strategy_divergence.py 的單元測試（標準庫）。

執行：python3 -m unittest tests/test_screener_scorecard.py -v
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import screener_scorecard as sc  # noqa: E402
import strategy_divergence as sd  # noqa: E402


def _series(start: date, opens: list[float], closes: list[float]) -> sc.Series:
    ds = [start + timedelta(days=i) for i in range(len(opens))]
    return sc.Series(ds, opens, closes)


class ForwardReturnTests(unittest.TestCase):
    def test_entry_next_open_exit_hth_close(self):
        d0 = date(2026, 1, 1)
        stock = _series(d0, [10, 10, 11, 12, 13, 14], [10, 10, 11, 12, 13, 14])
        bench = _series(d0, [100, 100, 100, 100, 100, 100], [100, 100, 100, 100, 100, 100])
        # 訊號日 d0+1（開 10）→ 進場 d0+2 開 11 → h=2 出場 d0+4 收 13
        r, ex, done = sc.forward(stock, bench, d0 + timedelta(days=1), 2)
        self.assertTrue(done)
        self.assertAlmostEqual(r, 13 / 11 - 1)
        self.assertAlmostEqual(ex, 13 / 11 - 1)  # 基準平盤

    def test_pending_when_not_enough_days(self):
        d0 = date(2026, 1, 1)
        stock = _series(d0, [10, 11, 12], [10, 11, 12])
        r, ex, done = sc.forward(stock, None, d0, 5)
        self.assertFalse(done)
        self.assertIsNone(r)

    def test_excess_subtracts_benchmark(self):
        d0 = date(2026, 1, 1)
        stock = _series(d0, [10, 10, 10, 10], [10, 10, 10, 11])   # 進 d0+1 開 10 → h=2 出 d0+3 收 11：+10%
        bench = _series(d0, [100, 100, 100, 100], [100, 100, 100, 105])  # +5%
        r, ex, done = sc.forward(stock, bench, d0, 2)
        self.assertAlmostEqual(r, 0.10)
        self.assertAlmostEqual(ex, 0.05)

    def test_signal_after_last_date(self):
        d0 = date(2026, 1, 1)
        stock = _series(d0, [10, 10], [10, 10])
        self.assertEqual(sc.forward(stock, None, d0 + timedelta(days=5), 1), (None, None, False))


class StatsTests(unittest.TestCase):
    def test_summarize(self):
        st = sc.summarize([0.1, -0.1, 0.2, 0.3])
        self.assertEqual(st["n"], 4)
        self.assertAlmostEqual(st["hit"], 0.75)
        self.assertAlmostEqual(st["mean"], 0.125)
        self.assertEqual(sc.summarize([])["n"], 0)

    def test_verdict_rules(self):
        ctrl = {"n": 1000, "hit": 0.45, "mean": 0.0}
        self.assertEqual(sc.verdict({"n": 30, "hit": 0.9, "t": 5}, ctrl), "⏳")        # 樣本未滿
        self.assertEqual(sc.verdict({"n": 100, "hit": 0.60, "t": 3.0}, ctrl), "🔍")     # 三關全過
        self.assertEqual(sc.verdict({"n": 100, "hit": 0.40, "t": 1.0}, ctrl), "☠️")     # 不高於對照
        self.assertEqual(sc.verdict({"n": 100, "hit": 0.48, "t": 1.0}, ctrl), "⏳")     # 高一點但未達門檻

    def test_universe_point_in_time(self):
        members = [("A", date(2020, 1, 1), None), ("B", date(2020, 1, 1), date(2026, 6, 1)), ("C", date(2026, 9, 1), None)]
        self.assertEqual(sc.universe_on(members, date(2026, 7, 1)), ["A"])
        self.assertEqual(sc.universe_on(members, date(2026, 9, 2)), ["A", "C"])
        self.assertEqual(sc.universe_on(members, date(2026, 5, 1)), ["A", "B"])


class PricesLoaderTests(unittest.TestCase):
    def test_loads_split_year_files_and_bench_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "data" / "equities" / "us" / "XYZ"
            d.mkdir(parents=True)
            for yr, rows in ((2025, [("2025-12-31", 9, 9)]), (2026, [("2026-01-02", 10, 11), ("2026-01-05", 11, 12)])):
                with open(d / f"prices_{yr}.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
                    for dt, o, c in rows:
                        w.writerow([dt, o, o, o, c, 1])
            spy = root / "data" / "equities" / "us" / "SPY"
            spy.mkdir()
            with open(spy / "prices_2026.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
                w.writerow(["2026-01-02", 100, 100, 100, 100, 1])
            p = sc.Prices(root)
            s = p.get("us", "XYZ")
            self.assertEqual([x.isoformat() for x in s.dates], ["2025-12-31", "2026-01-02", "2026-01-05"])
            self.assertIsNone(p.get("us", "_GSPC"))
            self.assertIsNotNone(p.bench("us"))  # 指數缺 → 退回 SPY
            self.assertIsNone(p.get("us", "NOPE"))


class DivergenceTests(unittest.TestCase):
    def test_light_thresholds(self):
        self.assertEqual(sd.light(None, None, 3, True)[0], "⚪")
        self.assertEqual(sd.light(0.5, 0.1, 10, False)[0], "⚪")
        self.assertEqual(sd.light(0.5, 0.1, 10, True)[0], "🟢")
        self.assertEqual(sd.light(-1.5, 0.1, 10, True)[0], "🟡")
        self.assertEqual(sd.light(0.0, 0.8, 10, True)[0], "🟡")
        self.assertEqual(sd.light(-2.5, 0.1, 10, True)[0], "🔴")
        self.assertEqual(sd.light(0.0, 1.0, 10, True)[0], "🔴")

    def test_zscore_and_drawdown(self):
        self.assertAlmostEqual(sd.zscore([10, 10, 10, 10], 0, 20), 10 / (20 / 2))
        self.assertIsNone(sd.zscore([], 0, 20))
        amt, pct = sd.max_drawdown([100, 120, 90, 130, 110])
        self.assertEqual(amt, 30)
        self.assertAlmostEqual(pct, 0.25)

    def test_read_snake_trades_from_realized_cum(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "forward_test.csv"
            p.write_text("date,instrument,pos,entry,mark,open_pnl,realized_cum,fees_cum,equity,quote_asof\n"
                         "2026-09-24,HSI2610,-1,24613,24690,-3850,-22750,165,1473235,x\n"
                         "2026-09-25,HSI2610,-1,24613,24524,4450,-22750,165,1481535,x\n"
                         "2026-10-12,HSI2610,1,24295,24249,-2300,-6850,275,1490575,x\n")
            s = sd.read_snake(Path(td))
            self.assertEqual(s["trades"], [15900.0])
            self.assertEqual(s["days"], 3)
            self.assertEqual(s["pos"], "1")

    def test_read_strangle_table(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "PAPER_TRADING.md"
            p.write_text("# x\n\n## 方向一真實交易紀錄：每週\n\n| 週 | a | b | c | d | e | f | g | h | i | j | 淨利（點） | 淨利（HK$） |\n"
                         "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                         "| 1 | . | . | . | . | . | . | 82 | . | . | . | **+74** | 3,700 |\n"
                         "| 2 | . | . | . | . | . | . | 90 | . | . | . | — | — |\n\n## 下一段\n")
            st = sd.read_strangle(p)
            self.assertEqual(st["weeks_opened"], 2)
            self.assertEqual(st["settled"], [74.0])


if __name__ == "__main__":
    unittest.main()
