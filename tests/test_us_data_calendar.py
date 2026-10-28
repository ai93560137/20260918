"""R348 美國數據日曆：解析、合併、封鎖時段。"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import us_data_calendar as c  # noqa: E402

U = timezone.utc


class T(unittest.TestCase):
    def test_parse_ff_filters(self):
        items = [
            {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00", "impact": "High"},
            {"title": "CPI m/m", "country": "EUR", "date": "2026-11-06T05:00:00-05:00", "impact": "High"},
            {"title": "Crude Oil", "country": "USD", "date": "2026-11-04T10:30:00-05:00", "impact": "Medium"},
            {"title": "Bank Holiday", "country": "USD", "date": "2026-11-11T00:00:00-05:00", "impact": "High"},
            {"title": "bad", "country": "USD", "date": "x", "impact": "High"},
        ]
        got = c.parse_ff(items)
        self.assertEqual(got, [{"t": "2026-11-06T13:30:00Z", "title": "Non-Farm Employment Change", "src": "ff"}])

    def test_merge_dedup_and_prune(self):
        now = datetime(2026, 10, 28, 0, 0, tzinfo=U)
        ff = [{"t": "2026-10-28T18:00:00Z", "title": "FOMC", "src": "ff"},
              {"t": "2026-10-20T12:30:00Z", "title": "old", "src": "ff"}]
        manual = [{"t": "2026-10-28T18:00:00Z", "title": "fomc"}, {"t": "2026-10-29T12:30:00Z", "title": "GDP"}]
        got = c.merge(ff, manual, now)
        self.assertEqual([e["title"] for e in got], ["FOMC", "GDP"])

    def test_is_blocked_window(self):
        doc = {"block_hours": 4, "events": [{"t": "2026-10-28T18:00:00Z", "title": "FOMC"}]}
        self.assertIsNone(c.is_blocked(doc, datetime(2026, 10, 28, 13, 59, tzinfo=U)))
        self.assertEqual(c.is_blocked(doc, datetime(2026, 10, 28, 14, 0, tzinfo=U))["title"], "FOMC")
        self.assertIsNotNone(c.is_blocked(doc, datetime(2026, 10, 28, 17, 59, tzinfo=U)))
        self.assertIsNone(c.is_blocked(doc, datetime(2026, 10, 28, 18, 0, tzinfo=U)))
        self.assertIsNone(c.is_blocked(None, datetime(2026, 10, 28, 15, 0, tzinfo=U)))

    def test_manual_file_valid(self):
        import json
        d = json.loads(c.MANUAL_PATH.read_text(encoding="utf-8"))
        for e in d["events"]:
            datetime.fromisoformat(e["t"].replace("Z", "+00:00"))


if __name__ == "__main__":
    unittest.main()
