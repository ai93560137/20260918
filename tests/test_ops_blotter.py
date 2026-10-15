"""ops_blotter.py：歸陣、意圖價配對、滑價、去重（FUND_SOP 二之三 E）。虛構數字。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ops_blotter as bl  # noqa: E402

MAIN = '''
FUTU_TEAM_MANUAL = "使用者人手"
FUTU_TEAM_RULES = (
    (r"^HK\\.MHI\\d{4}$", "雲垂陣", "MHI 期貨 Δ 對沖", 1),
    (r"^HK\\.HSI\\d{4}$", FUTU_TEAM_MANUAL, "大恒指期貨（人手）", None),
)
'''
INTENTS = """date,team,code,side,qty,intent_price,note
2026-10-15,雲垂陣,HK.MHI2610,賣,1,24100,16:00 Δ 對沖
"""


def deal(t, code, side, qty, px, oid="1"):
    return {"time_hkt": t, "code": code, "product": "", "side": side, "qty": qty, "price": px, "order_id": oid}


class BlotterTest(unittest.TestCase):
    def setUp(self):
        self.rules = bl.team_rules(MAIN)

    def test_team_rules_from_source(self):
        self.assertEqual(bl.team_of("HK.MHI2610", self.rules), "雲垂陣")
        self.assertEqual(bl.team_of("HK.HSI2611", self.rules), "使用者人手")
        self.assertEqual(bl.team_of("US.QQQ", self.rules), bl.UNMATCHED)

    def test_real_main_py_parses(self):
        from pathlib import Path
        rules = bl.team_rules((Path(bl.ROOT) / "main.py").read_text(encoding="utf-8"))
        self.assertTrue(rules)

    def test_intent_match_and_slippage_sign(self):
        intents = bl.load_intents(INTENTS)
        rows = bl.build_rows([deal("2026-10-15 16:05:00", "HK.MHI2610", "賣", 1.0, 24090.0)], [], self.rules, intents)
        self.assertEqual(rows[0]["intent_price"], "24100")
        self.assertEqual(rows[0]["slip_pts"], "10")          # 賣低咗 10 點＝差過意圖
        self.assertEqual(bl.slip("買", 24110, 24100), 10)

    def test_intent_used_once_and_dedupe(self):
        intents = bl.load_intents(INTENTS)
        d1 = deal("2026-10-15 16:05:00", "HK.MHI2610", "賣", 1.0, 24090.0, "a")
        first = bl.build_rows([d1], [], self.rules, intents)
        again = bl.build_rows([d1, deal("2026-10-15 16:20:00", "HK.MHI2610", "賣", 1.0, 24080.0, "b")],
                              first, self.rules, bl.load_intents(INTENTS))
        self.assertEqual(len(again), 1)                      # d1 唔重複
        self.assertEqual(again[0]["intent_price"], "")       # 意圖手數已用完

    def test_next_day_night_session_matches_but_not_two_days(self):
        rows = bl.build_rows([deal("2026-10-16 01:00:00", "HK.MHI2610", "賣", 1.0, 24100.0),
                              deal("2026-10-17 10:00:00", "HK.MHI2610", "賣", 1.0, 24100.0, "z")],
                             [], self.rules, bl.load_intents(INTENTS.replace(",1,", ",2,")))
        self.assertEqual([r["intent_price"] for r in rows], ["24100", ""])

    def test_summary(self):
        rows = [{"team": "雲垂陣", "slip_pts": "10"}, {"team": "雲垂陣", "slip_pts": "-2"}, {"team": "使用者人手", "slip_pts": ""}]
        s = bl.summarize(rows, "2026-10")["teams"]
        self.assertEqual(s["雲垂陣"], {"fills": 2, "with_intent": 2, "avg_slip_pts": 4.0})
        self.assertIsNone(s["使用者人手"]["avg_slip_pts"])


if __name__ == "__main__":
    unittest.main()
