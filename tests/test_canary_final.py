"""金絲雀讀雲垂定稿標記(INCIDENTS 2026-10-22):last_row=partial 嘅列要剔除。"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "canary"))
import build_canary_table as bct  # noqa: E402

CSV = "Date,Open,High,Low,Close\n2026-11-04,1,1,1,16.61\n2026-11-05,1,1,1,17.08\n"


class DropUnfinalized(unittest.TestCase):
    def run_with(self, status_by_file):
        with tempfile.TemporaryDirectory() as d:
            for b in bct.BIRDS + bct.LAB_FILES:
                with open(os.path.join(d, f"{b}_daily.csv"), "w") as fh:
                    fh.write(CSV)

            def fake_run(cmd, **kw):
                name = cmd[-1].rsplit("/", 1)[-1]
                if name in status_by_file:
                    return types.SimpleNamespace(returncode=0, stdout=json.dumps(status_by_file[name]))
                return types.SimpleNamespace(returncode=128, stdout="")

            with mock.patch.object(bct, "DATA_DIR", d), mock.patch.object(bct.subprocess, "run", fake_run):
                dropped = bct.drop_unfinalized("origin/x")
            vix = open(os.path.join(d, "vix_daily.csv")).read()
            move = open(os.path.join(d, "move_daily.csv")).read()
            saved = sorted(f for f in os.listdir(d) if f.endswith(".json"))
        return dropped, vix, move, saved

    def test_partial_dropped_final_kept(self):
        us = {"vix_daily.csv": {"last_date": "2026-11-05", "last_row": "partial", "row_fetched_utc": "2026-11-05 08:40"},
              "move_daily.csv": {"last_date": "2026-11-05", "last_row": "final"}}
        dropped, vix, move, saved = self.run_with({"us_daily_status.json": us})
        self.assertEqual(dropped, ["vix@2026-11-05"])
        self.assertNotIn("2026-11-05", vix)
        self.assertIn("2026-11-04", vix)
        self.assertIn("2026-11-05", move)
        self.assertEqual(saved, ["us_daily_status.json"])   # 留底

    def test_no_status_file_keeps_everything(self):
        dropped, vix, _, saved = self.run_with({})
        self.assertEqual(dropped, [])
        self.assertIn("2026-11-05", vix)
        self.assertEqual(saved, [])

    def test_partial_date_not_in_file_noop(self):
        us = {"vix_daily.csv": {"last_date": "2026-11-06", "last_row": "partial"}}
        dropped, vix, _, _ = self.run_with({"us_daily_status.json": us})
        self.assertEqual(dropped, [])
        self.assertIn("2026-11-05", vix)

    def test_asia_status_merged(self):
        asia = {"axvi_daily.csv": {"last_date": "2026-11-05", "last_row": "partial"}}
        dropped, _, _, saved = self.run_with({"asia_daily_status.json": asia})
        self.assertEqual(dropped, ["axvi@2026-11-05"])
        self.assertEqual(saved, ["asia_daily_status.json"])


if __name__ == "__main__":
    unittest.main()
