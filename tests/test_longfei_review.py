"""[R204] 龍飛陣覆盤（scripts/longfei_review.py）。唔連 GCS，全部用假資料。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import longfei_review as lr  # noqa: E402


def _trade(i, pnl, side=-1, session="RTH", reason="止蝕 718", mfe=None, mae=None, risk=2.0):
    ts = f"2026-10-16T15:{i:02d}:00+00:00"
    close = {"type": "CLOSE", "ts": ts, "opened_at": ts, "side": side, "points": pnl / 100,
             "pnl_hkd_gross": pnl, "reason": reason, "open_session": session}
    if mfe is not None:
        close.update(mfe=mfe, mae=mae, risk_pts=risk, r_multiple=(pnl / 100) / risk)
    return close


class ReviewTest(unittest.TestCase):
    def test_open_reason_filled_from_open_record(self):
        data = {"QQQ": {"status": {}, "decisions": [], "trades": [
            {"type": "OPEN", "ts": "2026-10-16T15:00:00+00:00", "reason": "順勢追空", "confidence": 0.7},
            {"type": "CLOSE", "ts": "2026-10-16T15:30:00+00:00", "opened_at": "2026-10-16T15:00:00+00:00",
             "side": -1, "points": 2.0, "pnl_hkd_gross": 203, "reason": "止蝕 718"}]}}
        rows = lr.closes(data)
        self.assertEqual(rows[0]["open_reason"], "順勢追空")
        self.assertEqual(rows[0]["confidence"], 0.7)
        self.assertEqual(lr.exit_kind(rows[0]["reason"], rows[0]["points"]), "移動止蝕（鎖利）")
        self.assertEqual(lr.exit_kind("止蝕 718", -1.0), "止蝕")

    def test_merge_decisions_dedupes_by_ts(self):
        a = [{"ts": "1", "final": "HOLD"}, {"ts": "2", "final": "HOLD"}]
        b = [{"ts": "2", "final": "HOLD"}, {"ts": "3", "final": "OPEN_SHORT"}]
        self.assertEqual([x["ts"] for x in lr._merge_decs(a, b)], ["1", "2", "3"])

    def test_fmt_zero_has_no_sign(self):
        self.assertEqual(lr.fmt(-0.0), "0")
        self.assertEqual(lr.fmt(390), "+390")

    def test_candidates_need_min_sample(self):
        rows = [{**_trade(i, -100, session="PRE"), "product": "SPY"} for i in range(lr.MIN_N - 1)]
        self.assertIn("暫時冇", lr.candidates(rows, {})[0])

    def test_losing_session_and_gave_back_candidates(self):
        rows = [{**_trade(i, -100, session="PRE", mfe=2.5, mae=-2.0), "product": "SPY"}
                for i in range(lr.MIN_N + 2)]
        text = "\n".join(lr.candidates(rows, {}))
        self.assertIn("時段「PRE」持續蝕錢", text)
        self.assertIn("賺錢變蝕錢", text)

    def test_report_renders(self):
        data = {"SPY": {"status": {"pos": None, "day_pnl": 0.0}, "decisions": [{"ts": "1", "final": "HOLD"}],
                        "trades": [_trade(1, 187, reason="止賺 768")]}}
        text = lr.report(data)
        self.assertIn("已平倉 **1** 筆", text)
        self.assertIn("SPY：1 次決策", text)
        self.assertIn("最大回撤 0", text)


    def test_readiness_table(self):
        data = {"SPY": {"status": {"trd_env": "SIMULATE", "real_preflight": {
                    "ok": False, "found": True, "funded": False, "acc_type": "MARGIN", "can_long": False,
                    "can_short": False, "is_pdt": False, "pdt_seq": 3, "ts": "2026-10-17T09:00:00+08:00"}},
                        "trades": [], "decisions": []},
                "QQQ": {"status": {"trd_env": "SIMULATE"}, "trades": [], "decisions": []}}
        text = "\n".join(lr.readiness(data))
        self.assertIn("| SPY | SIMULATE | ✅ | ❌ | MARGIN | ❌ | ❌ | 唔係／剩 3 次 | ❌ 未齊 |", text)
        self.assertIn("| QQQ | SIMULATE | — |", text)


if __name__ == "__main__":
    unittest.main()
