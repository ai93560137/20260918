"""[11-09] 心跳之間開完又平（冇見過倉位）都要入成交簿；933 補記 11-09 漏記單；策略停線計到。"""
import os
import sys
import unittest

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
os.environ.update(XAU_BOOK="signal", SIG_STUDENT_HWM_START="2026-11-09", SIG_STUDENT_LIVE="1", SIG_STUDENT_LIVE_RULES="spike2")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import live_book as LB  # noqa: E402
import student_live as SL  # noqa: E402

T = 1794188519


class Unseen(unittest.TestCase):
    def test_records_unseen_with_meta(self):
        st = {"book_ref": -1145.82}
        meta = {"side": -1, "lots": 0.01, "entry": 4117.54, "stop": 4121.92, "decision_price": 4117.54, "ch": "rule:spike2"}
        out = LB.track(st, None, None, -1164.32, now=T, unseen=lambda: meta)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["unseen"]); self.assertEqual(out[0]["pnl_hkd"], -18.5)
        self.assertLess(out[0]["r"], 0); self.assertEqual(st["book_ref"], -1164.32)
        self.assertEqual(LB.track(st, None, None, -1164.32, now=T + 60), [])          # 冇再變就唔記

    def test_small_change_ignored_and_no_meta_still_records(self):
        st = {"book_ref": 100.0}
        self.assertEqual(LB.track(st, None, None, 100.5, now=T), [])
        out = LB.track(st, None, None, 90.0, now=T)
        self.assertEqual(out[0]["pnl_hkd"], -10.5); self.assertIsNone(out[0]["r"])

    def test_normal_close_unchanged(self):
        st = {"book_ref": 0.0}
        pos = {"ticket": 1, "side": 1, "lots": 0.01, "entry": 4000.0, "stop": 3996.0}
        LB.track(st, None, pos, 0.0, now=T)
        out = LB.track(st, pos, None, 31.0, now=T + 60)
        self.assertEqual(len(out), 1); self.assertNotIn("unseen", out[0])


class Backfill(unittest.TestCase):
    def state(self):
        return {"book": [{"closed_ts": 1793000000, "r": 1.0, "id": "old"}],
                "orders": [{"id": "s4431fed", "acked": True, "ok": True, "ticket": 5, "ts": 1792990000, "side": "BUY", "lots": 0.05, "price": 3897.63, "sl": 3889.56},
                           {"id": "sa9cb13a", "acked": True, "ok": True, "ticket": 9, "ts": 1794188490, "side": "SELL", "lots": 0.01, "price": 4117.54,
                            "sl": 4121.92, "tp": 4113.92, "student": "rule:spike2"}]}

    def test_backfill_once_and_counts_in_stop(self):
        st = self.state()
        rec = SL.backfill_1109(st)
        self.assertEqual(rec["pnl_hkd"], -18.5); self.assertLess(rec["r"], 0)
        self.assertIsNone(SL.backfill_1109(st))
        why, stat = SL.strategy_stop(st)
        self.assertEqual(stat["n"], 1); self.assertLess(stat["cum_r"], 0)
        self.assertIsNone(SL._unseen_meta(st))                                   # 已補記，唔會再用；舊單（平倉之前）都唔會用

    def test_unseen_meta_picks_new_order_only(self):
        st = self.state(); st["backfill_1109"] = True
        meta = SL._unseen_meta(st)
        self.assertEqual(meta["id"], "sa9cb13a"); self.assertEqual(meta["side"], -1)
        self.assertIsNone(SL._unseen_meta(st))


if __name__ == "__main__":
    unittest.main()
