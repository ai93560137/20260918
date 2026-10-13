"""scripts/strategy_divergence.py 地載陣讀取器：規格解析、歸檔去重、按月加權、完整月、回撤。

執行：python3 -m unittest tests/test_strategy_divergence_dizai.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import strategy_divergence as sd  # noqa: E402

COMBO = {"type": "dizai_paper_combo",
         "components": {"que": "dizai/que/HK.HSI_FRONT.json", "steady60": "dizai/forward/HK.HSI_FRONT.json#steady60"}}


def t(ts, pnl, **k):
    return {"exit_tk": ts, "pnl": pnl, **k}


class SpecTests(unittest.TestCase):
    def test_specs(self):
        self.assertEqual(sd.dizai_specs({"type": "dizai_paper_state", "gcs": "dizai/heng/HK.HSI_FRONT.json"}),
                         {"heng": ("dizai/heng/HK.HSI_FRONT.json", None)})
        self.assertEqual(sd.dizai_specs({"type": "dizai_paper_state", "gcs": "dizai/forward/HK.HSI_FRONT.json", "variant": "bold_nq"}),
                         {"bold_nq": ("dizai/forward/HK.HSI_FRONT.json", "bold_nq")})
        self.assertEqual(sd.dizai_specs(COMBO)["steady60"], ("dizai/forward/HK.HSI_FRONT.json", "steady60"))


class ArchiveTests(unittest.TestCase):
    def test_merge_dedupes_and_keeps_old(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            (raw / "dizai__que__HK.HSI_FRONT.json").write_text(json.dumps(
                {"start": "2026-10-10", "trades": [t("2026-10-12 10:00", 50), t("2026-10-13 11:00", -20)]}))
            (raw / "dizai__forward__HK.HSI_FRONT.json").write_text(json.dumps(
                {"start": "2026-10-10", "variants": {"steady60": {"trades": [t("2026-10-12 15:00", 30)]}}}))
            arc = {"que": {"start": "2026-10-10", "trades": [t("2026-10-11 09:30", 5), t("2026-10-12 10:00", 50)]}}
            arc = sd.merge_dizai(arc, raw, sd.dizai_specs(COMBO))
            self.assertEqual([x["pnl"] for x in arc["que"]["trades"]], [5, 50, -20])   # 舊嘅保留、重覆唔加、按時間排
            self.assertEqual(len(arc["steady60"]["trades"]), 1)
            self.assertIs(sd.merge_dizai(arc, None, {}), arc)


class MonthlyTests(unittest.TestCase):
    def test_weights_full_months_and_drawdown(self):
        arc = {"que": {"start": "2026-10-10", "trades": [t("2026-10-20 10:00", 100), t("2026-11-03 10:00", -40),
                                                          t("2027-01-05 10:00", 10)]},
               "steady60": {"start": "2026-10-10", "trades": [t("2026-11-10 10:00", 30), t("2026-12-01 10:00", -50)]}}
        m = sd.dizai_monthly(arc, {"que": 1, "steady60": 2}, date(2027, 2, 15))
        self.assertEqual(m["months"], ["2026-11", "2026-12", "2027-01"])   # 10 月唔完整唔計；2 月未完
        self.assertEqual(m["monthly"], [-40 + 60, -100, 10])
        self.assertEqual((m["n_trades"], m["losses"]), (5, 2))
        self.assertEqual(m["cum"], 100 - 40 + 60 - 100 + 10)
        self.assertEqual(m["dd"], 120 - 20)                                  # 高位 120（10/20 +100、11/10 +60 後）→ 12/01 跌到 20
        self.assertIn("error", sd.dizai_monthly({}, {"que": 1}, date(2027, 1, 1)))

    def test_start_on_first_day_counts(self):
        m = sd.dizai_monthly({"heng": {"start": "2026-11-01", "trades": []}}, {"heng": 1}, date(2027, 1, 2))
        self.assertEqual((m["months"], m["monthly"]), (["2026-11", "2026-12"], [0.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
