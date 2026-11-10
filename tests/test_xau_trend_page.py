"""[11-10] 網頁趨勢簿段：持倉、#1114 區間、停條件（純渲染，唔掂 GCS）。"""
import os, sys, unittest
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import page  # noqa: E402

TL = {"on": True, "magic": 933, "rules": ["mobrk"], "names": {"mobrk": "月初三日區間突破（#1114）"}, "lots": 0.01, "pos": None,
      "levels": {"mobrk": {"month": "2026-11", "used": True, "hi": 3971.1, "lo": 3879.82}}, "orders": [], "pending": [],
      "account": {"positions": [], "received_utc": "2026-11-10 09:42:28"}, "last": {"note": "冇倉；今期已用，等下一期", "utc": "x", "price": 4086.6}, "book": []}


class TrendPage(unittest.TestCase):
    def test_render_levels_and_ok(self):
        h = page.trend_section(TL, "趨勢簿・933")
        self.assertIn("3879.82–3971.10", h); self.assertIn("本月已穿過", h); self.assertIn("未觸發停條件", h)

    def test_stop_streak(self):
        book = [{"r": -1.0, "pnl_hkd": -50, "opened_ts": 0, "closed_ts": 0} for _ in range(6)]
        h = page.trend_section({**TL, "book": book}, "x")
        self.assertIn("觸發停條件", h); self.assertIn("連蝕 6", h)
        st = page.trend_stats(book); self.assertEqual((st["n"], st["sum_r"], st["streak"]), (6, -6.0, 6))

    def test_none(self):
        self.assertEqual(page.trend_section(None, "x"), "")


if __name__ == "__main__":
    unittest.main()
