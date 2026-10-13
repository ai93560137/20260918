"""scripts/ops_heartbeat.py 的單元測試：cron 比對、應跑次數、workflow 判讀、新鮮度判讀、訊息組成。

執行：python3 -m unittest tests/test_ops_heartbeat.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ops_heartbeat as hb  # noqa: E402

UTC = timezone.utc


def u(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


class CronTests(unittest.TestCase):
    def test_basic_fields(self):
        self.assertTrue(hb.cron_matches("30 23 * * *", u("2026-10-13 23:30")))
        self.assertFalse(hb.cron_matches("30 23 * * *", u("2026-10-13 23:31")))
        self.assertTrue(hb.cron_matches("*/15 * * * 1-5", u("2026-10-13 09:45")))   # 週二
        self.assertFalse(hb.cron_matches("*/15 * * * 1-5", u("2026-10-11 09:45")))  # 週日
        self.assertTrue(hb.cron_matches("4,19,34,49 * * * 1-5", u("2026-10-13 10:19")))
        self.assertTrue(hb.cron_matches("17 2 * * 6", u("2026-10-17 02:17")))       # 週六
        self.assertTrue(hb.cron_matches("0 3 * * 0", u("2026-10-18 03:00")))        # 週日 = 0
        self.assertTrue(hb.cron_matches("0 3 * * 7", u("2026-10-18 03:00")))        # 週日 = 7

    def test_expected_fires(self):
        start, end = u("2026-10-12 23:00"), u("2026-10-13 23:00")             # 週一 23:00 → 週二 23:00
        self.assertEqual(hb.expected_fires(["30 22 * * 1-5"], start, end), 1)
        self.assertEqual(hb.expected_fires(["35 6 * * 1-5", "55 7 * * 1-5"], start, end), 2)
        self.assertEqual(hb.expected_fires(["17 2 * * 6"], start, end), 0)       # 週六的不算
        self.assertEqual(hb.expected_fires(["*/15 * * * 1-5"], start, end), 4 * 24)


class WorkflowJudgeTests(unittest.TestCase):
    WFS = {"a.yml": {"name": "A", "crons": ["30 22 * * 1-5"]},
           "b.yml": {"name": "B", "crons": ["30 22 * * 1-5"]},
           "c.yml": {"name": "C", "crons": ["30 22 * * 1-5"]},
           "weekly.yml": {"name": "W", "crons": ["17 2 * * 6"]}}

    def test_judge(self):
        runs = [{"path": ".github/workflows/a.yml", "status": "completed", "conclusion": "success"},
                {"path": ".github/workflows/b.yml", "status": "completed", "conclusion": "failure", "html_url": "http://x"}]
        rows = hb.check_workflows(self.WFS, runs, u("2026-10-12 23:00"), u("2026-10-13 23:00"))
        d = {n: (l, m) for l, n, m in rows}
        self.assertEqual(d["a.yml"][0], "🟢")
        self.assertEqual(d["b.yml"][0], "🔴"); self.assertIn("失敗 1/1", d["b.yml"][1])
        self.assertEqual(d["c.yml"][0], "🔴"); self.assertIn("實際 0 次", d["c.yml"][1])
        self.assertNotIn("weekly.yml", d)   # 窗口內不該跑，不列

    def test_new_and_disabled_workflows(self):
        meta = {"c.yml": {"created_at": u("2026-10-13 09:00"), "state": "active"},   # 今天才加：22:30 之前不算
                "b.yml": {"created_at": u("2026-01-01 00:00"), "state": "disabled_manually"},
                "a.yml": {"created_at": u("2026-01-01 00:00"), "state": "disabled_inactivity"}}
        rows = hb.check_workflows(self.WFS, [], u("2026-10-12 23:00"), u("2026-10-13 20:00"), meta)
        d = {n: (l, m) for l, n, m in rows}
        self.assertNotIn("c.yml", d)
        self.assertEqual(d["b.yml"][0], "⚪"); self.assertIn("手動停用", d["b.yml"][1])
        self.assertEqual(d["a.yml"][0], "🔴"); self.assertIn("disabled_inactivity", d["a.yml"][1])


class FreshnessTests(unittest.TestCase):
    def test_judge_and_weekend_allowance(self):
        now = datetime(2026, 10, 14, 7, 30, tzinfo=hb.HKT)   # 週三
        items = [("新", "s", now - timedelta(hours=2), 6), ("舊", "s", now - timedelta(hours=10), 6),
                 ("缺", "s", None, 6), ("週更", "s", now - timedelta(days=6), 8 * 24)]
        rows = {n: l for l, n, _ in hb.judge_freshness(items, now)}
        self.assertEqual(rows, {"新": "🟢", "舊": "🔴", "缺": "🔴", "週更": "🟢"})
        monday = datetime(2026, 10, 19, 7, 30, tzinfo=hb.HKT)
        friday_close = datetime(2026, 10, 16, 0, 0, tzinfo=hb.HKT)
        rows = hb.judge_freshness([("日線", "s", friday_close, 40)], monday)
        self.assertEqual(rows[0][0], "🟢")   # 79.5 小時 < 40 + 48

    def test_dates(self):
        self.assertEqual(hb.last_csv_date("Date,Close\n2026-10-12,1\n2026-10-13,2\n").day, 13)
        us = hb.last_csv_date("Date,Close\n2026-10-12,1\n", "us")
        self.assertEqual((us.day, us.hour), (13, 5))          # 美股 10-12 收市 = 香港 10-13 05:00
        hk = hb.last_csv_date("Date,Close\n2026-10-13,1\n", "hk")
        self.assertEqual((hk.day, hk.hour, hk.minute), (13, 16, 30))
        self.assertEqual(hb.first_date("# 每日對帳表 2026-10-13\n").day, 13)
        self.assertEqual(hb.first_date("run 2026-10-13 17:36 x").hour, 17)


class ComposeTests(unittest.TestCase):
    def test_all_green_one_line(self):
        now = datetime(2026, 10, 14, 7, 30, tzinfo=hb.HKT)
        short, full = hb.compose(now, [("🟢", "a.yml", "1/1")], [("🟢", "x", "ok")], [])
        self.assertEqual(short.count("\n"), 0)
        self.assertIn("全部 2 項 🟢", short)

    def test_reds_only(self):
        now = datetime(2026, 10, 14, 7, 30, tzinfo=hb.HKT)
        short, _ = hb.compose(now, [("🟢", "a.yml", "1/1"), ("🔴", "b.yml", "失敗")], [("🔴", "x", "舊")], ["API 錯"])
        self.assertIn("🔴 2／3 項", short)
        self.assertIn("🔴 b.yml：失敗", short)
        self.assertNotIn("a.yml", short)
        self.assertIn("⚠ API 錯", short)


if __name__ == "__main__":
    unittest.main()
