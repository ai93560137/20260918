"""[IDEAS #1463，使用者 11-13「照行，SP500 0.2＋UK100 0.1，…69」] 月尾股債再平衡：日曆、方向、數據解析、trend_live 接駁（唔連網、唔掂 GCS）。"""
import datetime as dt
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "xau"))
import merebal_feed as FD   # noqa: E402
import trend_merebal as MR  # noqa: E402

D = dt.date


def ts(y, m, d, hh=0, mm=0):
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp())


class Calendar(unittest.TestCase):
    def test_key_days(self):
        self.assertEqual(MR.key_days("US", 2026, 11), (D(2026, 11, 20), D(2026, 11, 30)))        # 感恩節 11-26 休市
        self.assertEqual(MR.key_days("UK", 2026, 11), (D(2026, 11, 23), D(2026, 11, 30)))
        self.assertEqual(MR.key_days("US", 2026, 12), (D(2026, 12, 23), D(2026, 12, 31)))        # 12-25 休市
        self.assertEqual(MR.key_days("UK", 2026, 12), (D(2026, 12, 22), D(2026, 12, 31)))        # 12-25、12-28（補 12-26）休市
        self.assertEqual(MR.key_days("US", 2026, 5), (D(2026, 5, 21), D(2026, 5, 29)))           # 陣亡將士紀念日 5-25
        self.assertEqual(MR.key_days("UK", 2026, 5), (D(2026, 5, 21), D(2026, 5, 29)))           # 春季銀行假 5-25
        self.assertEqual(MR.key_days("UK", 2026, 8), (D(2026, 8, 21), D(2026, 8, 28)))           # 夏季銀行假 8-31
        self.assertEqual(MR.easter(2026), D(2026, 4, 5)); self.assertIn(D(2026, 4, 3), MR.holidays("US", 2026)); self.assertIn(D(2026, 4, 6), MR.holidays("UK", 2026))

    def test_phase_and_side(self):
        self.assertEqual(MR.phase("US", ts(2026, 11, 20, 20, 44), 1245), (None, 2026 * 12 + 10))
        self.assertEqual(MR.phase("US", ts(2026, 11, 20, 20, 45), 1245), ("enter", 2026 * 12 + 10))
        self.assertEqual(MR.phase("US", ts(2026, 11, 21, 0, 5), 1245)[0], None)                 # 過咗訊號日唔再入
        self.assertEqual(MR.phase("US", ts(2026, 11, 30, 20, 44), 1245)[0], None)
        self.assertEqual(MR.phase("US", ts(2026, 11, 30, 20, 45), 1245)[0], "exit")
        self.assertEqual(MR.phase("UK", ts(2026, 8, 29, 12, 0), 1245)[0], "exit")               # 月尾日之後（週末／假期）都當出場
        self.assertEqual(MR.side(-0.02, 0.01), 1); self.assertEqual(MR.side(0.02, 0.01), -1); self.assertEqual(MR.side(0.01, 0.01), -1)


class Feed(unittest.TestCase):
    DOC = {"chart": {"result": [{"meta": {"gmtoffset": -18000}, "timestamp": [ts(2026, 10, 30, 14, 30), ts(2026, 11, 19, 14, 30), ts(2026, 11, 20, 14, 30)],
                                 "indicators": {"quote": [{"close": [7000.0, None, 6860.0]}]}}]}}

    def test_parse_and_mtd(self):
        rows = FD.parse_chart(self.DOC)
        self.assertEqual(rows, [(D(2026, 10, 30), 7000.0), (D(2026, 11, 20), 6860.0)])
        v, why = FD.mtd(rows, D(2026, 11, 20)); self.assertAlmostEqual(v, -0.02); self.assertIsNone(why)
        self.assertIsNone(FD.mtd(rows, D(2026, 11, 23))[0]); self.assertIn("未有價", FD.mtd(rows, D(2026, 11, 23))[1])   # 唔新鮮唔用
        self.assertIn("上個月", FD.mtd(rows[1:], D(2026, 11, 20))[1])
        self.assertEqual(FD.parse_chart({}), []); self.assertEqual(FD.parse_chart({"chart": {"result": None}}), [])

    def test_snapshot_and_probe(self):
        idx = [(D(2026, 10, 30), 7000.0), (D(2026, 11, 20), 6860.0)]; bond = [(D(2026, 10, 30), 105.0), (D(2026, 11, 20), 106.05)]
        f = lambda tk: bond if tk == FD.BOND else idx   # noqa: E731
        self.assertEqual(FD.snapshot("^GSPC", D(2026, 11, 20), fetcher=f), {"idx": -0.02, "bond": 0.01})
        self.assertIn("err", FD.snapshot("^GSPC", D(2026, 11, 20), fetcher=lambda tk: []))
        self.assertIn("ZN=F", FD.snapshot("^GSPC", D(2026, 11, 20), fetcher=lambda tk: [] if tk == FD.BOND else idx)["err"])
        self.assertEqual(FD.probe("^GSPC", fetcher=f), {"idx_last": ["2026-11-20", 6860.0], "bond_last": ["2026-11-20", 106.05]})


class Live(unittest.TestCase):
    def setUp(self):
        import config
        import trend_live as T
        self.T, self.c = T, config
        self.old = (config.TREND_MAGIC, config.TREND_RULES, config.TREND_BOOKS, config.TREND_MEREBAL_CAL, config.TREND_MEREBAL_IDX, config.PRICE_DIGITS)
        config.TREND_MAGIC, config.TREND_RULES, config.TREND_BOOKS, config.TREND_MEREBAL_CAL, config.TREND_MEREBAL_IDX, config.PRICE_DIGITS = 945, ("merebal",), (), "US", "^GSPC", 2
        self.logs = []; self.m = types.SimpleNamespace(log_event=lambda msg, **k: self.logs.append((msg, k.get("severity"))))

    def tearDown(self):
        c = self.c
        c.TREND_MAGIC, c.TREND_RULES, c.TREND_BOOKS, c.TREND_MEREBAL_CAL, c.TREND_MEREBAL_IDX, c.PRICE_DIGITS = self.old

    def _state(self, now):
        T = self.T; day = now // 86400
        return {**T.empty_state(), "d1": {str(day): {"o": 7600, "h": 7610, "l": 7590, "c": 7600, "t0": now - 600, "t1": now - 30}}}

    def test_enter_long_then_exit(self):
        T = self.T; now = ts(2026, 11, 20, 20, 46); st = self._state(now); days = T.days_of(st["d1"]); mk = 2026 * 12 + 10
        idx = [(D(2026, 10, 30), 7000.0), (D(2026, 11, 20), 6860.0)]; bond = [(D(2026, 10, 30), 105.0), (D(2026, 11, 20), 106.05)]
        self.assertIn("未有股債數據", T.plan(st, days, None, 7600.0, now, None, [])[1])
        T.merebal_prefetch(self.m, st, None, now, fetcher=lambda tk: bond if tk == "ZN=F" else idx)
        self.assertEqual((st["mr"]["mk"], st["mr"]["idx"], st["mr"]["bond"]), (mk, -0.02, 0.01)); self.assertEqual(st["mr_probe"]["day"], now // 86400)
        act, why = T.plan(st, days, None, 7600.0, now, None, [])
        self.assertEqual(act[0], "open"); self.assertEqual((act[1]["rule"], act[1]["side"], act[1]["sl"], act[1]["period"]), ("merebal", 1, 6840.0, mk)); self.assertIn("做多", why)
        self.assertIsNone(T.plan(st, days, None, 7600.0, now, "EA dry_run", [])[0])
        self.assertIsNone(T.plan({**st, "used": {"merebal": mk}}, days, None, 7600.0, now, None, [])[0])       # 今個月已用
        self.assertIsNone(T.plan(st, days, None, 7600.0, ts(2026, 11, 20, 20, 30), None, [])[0])               # 未到時間
        pos = {"rule": "merebal", "side": 1, "sl": 6840.0, "period": mk}; live = {"side": 1, "lots": 0.2, "entry": 7600.0, "stop": 6840.0}
        self.assertIsNone(T.plan({**st, "pos": pos}, days, live, 7650.0, ts(2026, 11, 27, 21, 0), None, [])[0])  # 未到月尾
        act, why = T.plan({**st, "pos": pos}, days, live, 7650.0, ts(2026, 11, 30, 20, 46), None, []); self.assertEqual(act, ("close", "月尾收市平"))
        self.assertEqual(T.plan({**st, "pos": pos}, days, live, 7650.0, ts(2026, 12, 1, 0, 5), None, [])[0], ("close", "月尾已過，平"))

    def test_short_side_and_feed_failure(self):
        T = self.T; now = ts(2026, 11, 20, 20, 50); st = self._state(now); days = T.days_of(st["d1"])
        T.merebal_prefetch(self.m, st, None, now, fetcher=lambda tk: [])
        self.assertIn("err", st["mr"]); self.assertTrue(any(sev == "WARNING" for _, sev in self.logs)); self.assertIsNone(T.plan(st, days, None, 7600.0, now, None, [])[0])
        n = len(self.logs); T.merebal_prefetch(self.m, st, None, now + 60, fetcher=lambda tk: [])                 # 10 分鐘內唔重試
        self.assertEqual(len(self.logs), n)
        idx = [(D(2026, 10, 30), 7000.0), (D(2026, 11, 20), 7140.0)]; bond = [(D(2026, 10, 30), 105.0), (D(2026, 11, 20), 105.0)]
        T.merebal_prefetch(self.m, st, None, now + 601, fetcher=lambda tk: bond if tk == "ZN=F" else idx)
        st["d1"][str(now // 86400)]["t1"] = now + 590                                                          # K 線要新鮮先會開
        act, why = T.plan(st, days, None, 7600.0, now + 601, None, [])
        self.assertEqual((act[1]["side"], act[1]["sl"]), (-1, 8360.0)); self.assertIn("做空", why)
        self.assertIn("merebal", T.NAMES)


if __name__ == "__main__":
    unittest.main()
