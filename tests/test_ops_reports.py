"""scripts/ops_reports.py 的單元測試：損益段、IDEAS 差異、評分卡、偏離燈、分段；不碰 GCS／Telegram。

執行：python3 -m unittest tests/test_ops_reports.py -v
"""
from __future__ import annotations

import csv
import io
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ops_reports as rp  # noqa: E402

PNL = ("date,equity_total,mt5_realized_today,ladder,unreal_雲垂陣,real_雲垂陣,unreal_風揚陣_方向一,real_風揚陣_方向一\n"
       "2026-10-09,1000000,0,A,0,0,0,0\n"
       "2026-10-12,1010000,0,A,500,100,0,0\n"
       "2026-10-13,990000,12.5,B,-200,300,1000,0\n"
       "2026-10-14,1020000,0,A,800,0,2000,500\n")
ROWS = list(csv.DictReader(io.StringIO(PNL)))
IDEAS_OLD = "| # | 想法 | 陣 | 狀態 |\n|---|---|---|---|\n| 1 | 方向一 | 風揚 | 📒 紙上 |\n| 2 | 蛇 | 蛇蟠 | 💡 已登記 |\n"
IDEAS_NEW = IDEAS_OLD.replace("📒 紙上", "💼 實倉（10-12 起）") + "| 3 | 新想法 | 地載 | 🔬 回測 |\n"
SCORE = ("## newhighs\n| 市場 | h | 已評分 | 待評 | 命中 | 對照 | a | b | c | d | e | f | 判決 |\n"
         "| 美股 | 10 | 67 | 3 | 0.373 | 0.313 | x | x | x | x | x | x | 🔍 |\n"
         "| 美股 | 5 | 67 | 3 | 0.4 | 0.3 | x | x | x | x | x | x | ⏳ |\n"
         "## vcp\n| 港股 | 10 | 0 | 0 | — | — | x | x | x | x | x | x | ⏳ |\n")
DIV = "| 策略 | 燈 | 說明 |\n|---|---|---|\n| 蛇蟠 HSI | ⚪ | 樣本未夠 |\n| 雲垂 MES | 🟡 | z=-1.6 |\n"


class PnlTests(unittest.TestCase):
    def test_week_uses_prior_close_as_base(self):
        out, st = rp.pnl_section(ROWS, date(2026, 10, 12), date(2026, 10, 18), "T")
        text = "\n".join(out)
        self.assertEqual((st["base"], st["last"], st["chg"]), (1000000.0, 1020000.0, 20000.0))
        self.assertIn("HK$1,000,000 → HK$1,020,000（+20,000，+2.00%）", text)
        self.assertNotIn("期初取期間第一日", text)
        self.assertAlmostEqual(st["mdd"], 20000 / 1010000)
        self.assertIn("最差一日 -20,000", text)
        self.assertIn("雲垂陣 已實現 +400／期末未實現 +800", text)
        self.assertIn("風揚陣・方向一 已實現 +500／期末未實現 +2,000", text)
        self.assertIn("MT5 黃金已實現合計 +12.50", text)
        self.assertIn("Ⓐ 2 日、Ⓑ 1 日", text)

    def test_first_period_and_empty(self):
        out, st = rp.pnl_section(ROWS, date(2026, 10, 1), date(2026, 10, 9), "T")
        self.assertIn("期初取期間第一日", "\n".join(out))
        out, st = rp.pnl_section(ROWS, date(2026, 11, 1), date(2026, 11, 30), "T", ladder_line=False)
        self.assertIn("沒有資料", "\n".join(out))
        self.assertEqual(st["n"], 0)
        out, _ = rp.pnl_section(ROWS, date(2026, 10, 12), date(2026, 10, 18), "T", ladder_line=False)
        self.assertNotIn("風控階梯", "\n".join(out))


    def test_public_hides_equity_level(self):
        out, _ = rp.pnl_section(ROWS, date(2026, 10, 12), date(2026, 10, 18), "T", public=True)
        text = "\n".join(out)
        self.assertIn("合計權益報酬 +2.00%", text)
        self.assertIn("最差一日 -1.98%", text)
        self.assertNotIn("HK$", text)
        self.assertNotIn("1,020,000", text)
        self.assertNotIn("20,000", text)
        self.assertIn("雲垂陣 已實現 +400", text)          # 按陣盈虧照列（策略總表本已公開）


class PublicIndexTests(unittest.TestCase):
    def test_merge_replaces_same_key_and_keeps_12(self):
        now = rp.datetime(2026, 10, 18, 9, 0, tzinfo=rp.HKT)
        idx = None
        for i in range(14):
            idx = rp.merge_public(idx, "weekly", f"2026-{i // 4 + 7:02d}-{i % 4 * 7 + 1:02d}", f"w{i}", now)
        idx = rp.merge_public(idx, "weekly", "2026-10-18", "old", now)
        idx = rp.merge_public(idx, "weekly", "2026-10-18", "new", now)
        self.assertEqual(len(idx["weekly"]), 12)
        self.assertEqual((idx["weekly"][0]["key"], idx["weekly"][0]["text"]), ("2026-10-18", "new"))
        self.assertEqual(sum(r["key"] == "2026-10-18" for r in idx["weekly"]), 1)
        idx = rp.merge_public(idx, "monthly", "2026-10", "m", now)
        self.assertEqual(len(idx["weekly"]), 12)
        self.assertEqual(idx["monthly"][0]["key"], "2026-10")


class GovernanceTests(unittest.TestCase):
    def test_ideas_diff(self):
        d = rp.ideas_diff(IDEAS_OLD, IDEAS_NEW)
        self.assertIn("↻ #1 方向一：📒 紙上 → 💼 實倉", d)
        self.assertIn("＋ #3 新想法（🔬 回測）", d)
        self.assertEqual(len(d), 2)
        self.assertEqual(rp.ideas_diff(None, IDEAS_NEW), ["IDEAS.md 期初未存在，本期新建，共 3 列"])
        self.assertEqual(rp.ideas_diff(IDEAS_NEW, IDEAS_NEW), [])

    def test_scorecard_only_h10(self):
        v = rp.scorecard_verdicts(SCORE)
        self.assertEqual(set(v), {("newhighs", "美股"), ("vcp", "港股")})
        self.assertTrue(v[("newhighs", "美股")].startswith("🔍（已評分 67，命中 0.373 對照 0.313）"))

    def test_divergence_lights(self):
        self.assertEqual(rp.divergence_lights(DIV), {"蛇蟠 HSI": "⚪", "雲垂 MES": "🟡"})


class ChunkTests(unittest.TestCase):
    def test_chunks_respect_limit_and_keep_text(self):
        text = "\n\n".join(["甲" * 50, "乙" * 120, "丙" * 30])
        parts = rp.chunks(text, limit=100)
        self.assertTrue(all(len(p) <= 100 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))
        self.assertEqual(rp.chunks("短"), ["短"])


if __name__ == "__main__":
    unittest.main()
