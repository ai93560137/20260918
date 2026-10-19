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


    def test_api_cost_by_model_and_gate(self):
        """[R218] 決策模型同 Haiku 篩選分開計費；舊紀錄冇寫模型當 Sonnet 5.5。"""
        decs = [{"ts": "a", "usage": {"in": 1_000_000, "out": 0}},                                   # Sonnet：$2
                {"ts": "b", "usage": {"in": 0, "out": 100_000, "model": "claude-opus-5-5"}},         # Opus：$2
                {"ts": "c", "gate": "SKIP", "gate_usage": {"in": 1_000_000, "model": "claude-haiku-5-5"}}]
        text = "\n".join(lr.api_cost({"SPY": {"decisions": decs}}))
        self.assertIn("| SPY | 2 | 1 | opus-5-5、sonnet-5-5 | 4.00 | 0.10 | 4.10 |", text)

    def test_gate_audit_uses_1m_bars(self):
        """[R218] 篩走之後大波幅 → 計入「篩走但波幅 ≥ 放行中位數」。"""
        day = {f"09:{m:02d}": [100, 100.2, 99.8, 100, 1] for m in range(60)}
        day.update({f"10:{m:02d}": [100, 100 + m * 0.05, 99.9, 100, 1] for m in range(60)})
        bars = {"SPY": {"2026-10-16": day}}
        decs = [{"ts": "2026-10-16T21:00:00+08:00", "gate": "LOOK", "last": 100},       # 09:00 ET：細波幅（09:05 嗰次睇到 10:05，0.25%）
                {"ts": "2026-10-16T21:05:00+08:00", "gate": "LOOK", "last": 100},
                {"ts": "2026-10-16T22:00:00+08:00", "gate": "SKIP", "last": 100}]       # 10:00 ET：之後升 3%
        text = "\n".join(lr.gate_audit({"SPY": {"decisions": decs}}, bars))
        self.assertIn("| SPY | 2 | 0.25% | 1 | 2.95% | 1（100%） |", text)
        self.assertIn("未有足夠數據", "\n".join(lr.gate_audit({"SPY": {"decisions": decs}}, {})))

    def test_real_candidate_ranking(self):
        """[R224] 真倉候選排名：樣本不足唔下結論；穩定賺錢先係候選；按 t 值排。"""
        good = [{"product": "SPY", "pnl_hkd_net": v, "ts": str(i)} for i, v in enumerate([300, 250, -100, 400, 200,
                                                                                         350, -150, 300, 280, 320])]
        bad = [{"product": "QQQ", "pnl_hkd_net": v, "ts": str(i)} for i, v in enumerate([-300, 100, -200] * 4)]
        few = [{"product": "EWT", "pnl_hkd_net": 500, "ts": "1"}]
        text = "\n".join(lr.ranking(good + bad + few, ["SPY", "QQQ", "EWT", "EWC"]))
        self.assertIn("| 1 | SPY | 10 |", text)
        self.assertIn("✅ 候選", text)
        self.assertIn("樣本不足（1／10 筆）", text)
        self.assertIn("| QQQ | 12 |", text)
        self.assertIn("❌ 唔建議", text)
        self.assertIn("| EWC | 0 |", text)

if __name__ == "__main__":
    unittest.main()
