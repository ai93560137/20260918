"""scripts/event_calendar.py 的單元測試：各來源轉事件、結算日、期權到期、規則、事件週。

執行：python3 -m unittest tests/test_event_calendar.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import event_calendar as ec  # noqa: E402

RULES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "calendar", "rules.json")))
HK_HOL = "date,name_zh,name,kind\n2026-10-01,國慶日,,holiday\n2026-10-19,重陽節補假,,holiday\n"
US_HOL = "date,name_zh,name,kind\n2026-11-26,感恩節,,holiday\n"
FOMC = ("date,scheduled,statement_time_et,statement_time_rule,press_conference,heading,source_url,note\n"
        "2026-10-28,1,,14:00,0,2026 October 27-28,,future\n2026-10-20,0,,,0,call,,unscheduled\n")
FF = {"events": [{"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High"},
                 {"title": "Speech", "country": "EUR", "date": "2026-10-14T09:00:00-04:00", "impact": "Medium"},
                 {"title": "Retail", "country": "USD", "date": "2026-10-15T08:30:00-04:00", "impact": "Medium"}]}
POS = ("| 陣 | 戶口 | 持倉 | 開倉 | 規則 | 完結 | 狀態 | 紀錄 |\n|---|---|---|---|---|---|---|---|\n"
       "| 🌬️ 風揚 | 富途 | 沽 HSI 週期權 10/16（各 1 張） | x | x | 2026-10-16 現金結算 | 持倉中 | x |\n"
       "| ✋ 人手 | 富途 | MHI 即日 | 不定 | x | 即日 | 不定 | x |\n")


class SourceTests(unittest.TestCase):
    def test_ff_filter_and_hkt(self):
        evs = ec.from_forexfactory([FF], RULES)
        names = [(e["event"], e["date"], e["time_hkt"]) for e in evs]
        self.assertIn(("CPI m/m", "2026-10-14", "20:30"), names)
        self.assertIn(("Retail", "2026-10-15", "20:30"), names)      # USD Medium 保留
        self.assertNotIn("Speech", [n for n, _, _ in names])          # EUR Medium 不留

    def test_fomc_scheduled_only_and_timezone(self):
        evs = ec.from_fomc(FOMC)
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["date"], evs[0]["time_hkt"]), ("2026-10-29", "02:00"))   # 14:00 EDT = 翌日 02:00 HKT

    def test_hk_settlement_uses_trading_days(self):
        trading = {date(2026, 10, d) for d in (26, 27, 28, 29, 30)} | {date(2026, 10, 2)}
        evs = ec.from_hk_settlement([(2026, 10)], ec.holidays(HK_HOL), trading)
        self.assertEqual(evs[0]["date"], "2026-10-29")
        evs = ec.from_hk_settlement([(2026, 12)], ec.holidays("date,name_zh\n2026-12-25,聖誕,\n2026-12-31,除夕,\n"), None)
        self.assertEqual(evs[0]["date"], "2026-12-29")                # 12-31 假、12-30 最後、12-29 倒數第二

    def test_us_options(self):
        evs = ec.from_us_options([(2026, 10), (2026, 12)], ec.holidays(US_HOL))
        d = {(e["date"], "EOM" in e["event"]) for e in evs}
        self.assertIn(("2026-10-16", False), d)
        self.assertIn(("2026-10-30", True), d)
        self.assertTrue(any("季度" in e["event"] for e in evs if e["date"] == "2026-12-18"))

    def test_positions(self):
        evs = ec.from_positions(POS)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["date"], "2026-10-16")
        self.assertIn("沽 HSI 週期權 10/16", evs[0]["event"])


class BuildTests(unittest.TestCase):
    def test_build_rules_and_event_weeks(self):
        now = datetime(2026, 10, 13, 7, 0, tzinfo=ec.HKT)
        src = {"ff_this": FF, "ff_next": None, "fomc": FOMC, "hk_hol": HK_HOL, "us_hol": US_HOL, "jp_hol": "",
               "hk_trading": None, "positions": POS}
        evs, flagged = ec.build(now, src, RULES)
        by = {(e["date"], e["category"]): e for e in evs}
        self.assertEqual(by[("2026-10-14", "數據")]["affects"], "雲垂 MES、人手 EW、金絲雀")
        self.assertEqual(by[("2026-10-19", "HK 假期")]["event_week"], "Y")
        # 風揚陣 2026-10-13 收緊：只算 FOMC／Federal Funds 與港股平日假期；CPI 單獨不算事件週
        self.assertNotIn((2026, 42), flagged)    # 只有 CPI
        self.assertIn((2026, 43), flagged)       # 重陽補假週
        self.assertIn((2026, 44), flagged)       # FOMC 週
        md = ec.week_md(evs, flagged, now)
        self.assertIn("本週 10-12～10-18：非事件週", md)
        self.assertIn("下週 10-19～10-25：⚠ 事件週", md)

    def test_event_week_ignores_other_countries_data(self):
        evs = [ec.ev(datetime(2026, 10, 15).date(), "14:00", "GBP", "數據", "GDP m/m", "High", "ForexFactory"),
               ec.ev(datetime(2026, 10, 15).date(), "20:30", "USD", "數據", "CPI y/y", "High", "ForexFactory")]
        self.assertEqual(ec.apply_rules(evs, RULES), {})
        fomc = [ec.ev(datetime(2026, 10, 29).date(), "02:00", "USD", "數據", "Federal Funds Rate", "High", "ForexFactory")]
        self.assertIn((2026, 44), ec.apply_rules(fomc, RULES))
        csv_text = ec.to_csv(evs)
        self.assertTrue(csv_text.startswith("date,time_hkt,market,category,event,impact,affects,event_week,source"))


if __name__ == "__main__":
    unittest.main()
