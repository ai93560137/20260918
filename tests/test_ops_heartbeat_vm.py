"""ops_heartbeat.py 的富途 VM 檢查（2026-10-15）。不連網：用假 session。"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ops_heartbeat as hb  # noqa: E402


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _Session:
    def __init__(self, vm_code, vm_body, gcs):
        self.vm_code, self.vm_body, self.gcs = vm_code, vm_body, gcs

    def get(self, url, params=None, timeout=None):
        if "compute.googleapis.com" in url:
            return _Resp(self.vm_code, self.vm_body)
        if "longfei" in url:
            ts = self.gcs.get("longfei")
            return _Resp(200, {"received_ts": ts}) if ts else _Resp(404, {})
        for obj, ts in self.gcs.items():
            if obj.replace("/", "%2F") in url:
                return _Resp(200, {"updated": ts})
        return _Resp(404, {})


NOW = datetime(2026, 10, 15, 7, 30, tzinfo=hb.HKT)   # 週四


class VmCheckTest(unittest.TestCase):
    def test_running_and_fresh(self):
        s = _Session(200, {"status": "RUNNING", "lastStartTimestamp": "2026-10-14T12:50:23.527-07:00"},
                     {"futu/snapshots/US.QQQ.json": "2026-10-14T23:25:00Z",
                      "futu/snapshots/HK.HSI_IV.json": "2026-10-14T23:00:00Z",
                      "longfei": NOW.timestamp() - 600})
        rows, items = hb.vm_checks(NOW, session=s)
        self.assertEqual(rows[0][0], "🟢")
        self.assertIn("10-15 03:50", rows[0][2])
        self.assertTrue(all(r[0] == "🟢" for r in hb.judge_freshness(items, NOW)))

    def test_stopped_vm_is_red(self):
        rows, _ = hb.vm_checks(NOW, session=_Session(200, {"status": "TERMINATED"}, {}))
        self.assertEqual(rows[0][0], "🔴")
        self.assertIn("TERMINATED", rows[0][2])

    def test_no_permission_is_red_not_crash(self):
        rows, items = hb.vm_checks(NOW, session=_Session(403, {}, {}))
        self.assertEqual(rows[0][0], "🔴")
        self.assertIn("compute.instances.get", rows[0][2])
        self.assertTrue(all(r[0] == "🔴" for r in hb.judge_freshness(items, NOW)))   # 讀唔到更新時間

    def test_stale_push_is_red(self):
        s = _Session(200, {"status": "RUNNING"},
                     {"futu/snapshots/US.QQQ.json": "2026-10-14T12:00:00Z",
                      "futu/snapshots/HK.HSI_IV.json": "2026-10-14T23:00:00Z"})
        _, items = hb.vm_checks(NOW, session=s)
        lights = [r[0] for r in hb.judge_freshness(items, NOW)]
        self.assertEqual(lights, ["🔴", "🔴", "🟢"])          # 龍飛陣讀唔到 → 🔴

    def test_longfei_stale_is_red(self):
        s = _Session(200, {"status": "RUNNING"}, {"longfei": NOW.timestamp() - 3600})
        _, items = hb.vm_checks(NOW, session=s)
        self.assertEqual(hb.judge_freshness(items[:1], NOW)[0][0], "🔴")


class EsNq5mTest(unittest.TestCase):
    # 2026-10-20（二）07:30 HKT ＝ 10-19（一）19:30 紐約，CME 開市
    NOW = datetime(2026, 10, 20, 7, 30, tzinfo=hb.HKT)

    def snap(self, age_min, tk, src="ib_delayed:ESZ6"):
        return {"received_ts": self.NOW.timestamp() - age_min * 60, "source": src, "bars": [{"time_key": tk}]}

    def test_fresh_is_green(self):
        r = hb.es_nq_5m_rows(self.NOW, {"US.ES_FRONT": self.snap(4, "2026-10-19 19:10:00")})
        self.assertEqual(r[0][0], "🟢")

    def test_stale_push_and_lagging_bar_red(self):
        r = hb.es_nq_5m_rows(self.NOW, {"US.ES_FRONT": self.snap(30, "2026-10-19 18:30:00")})
        self.assertEqual(r[0][0], "🔴")
        self.assertIn("上限 20", r[0][2])
        self.assertIn("上限 45", r[0][2])

    def test_mt5_source_yellow(self):
        r = hb.es_nq_5m_rows(self.NOW, {"US.ES_FRONT": self.snap(4, "2026-10-19 19:10:00", "mt5:SP500ft")})
        self.assertEqual(r[0][0], "🟡")

    def test_closed_market_skipped(self):
        sun = datetime(2026, 10, 19, 5, 0, tzinfo=hb.HKT)        # 10-18（日）17:00 紐約，未開市
        r = hb.es_nq_5m_rows(sun, {"US.ES_FRONT": None})
        self.assertEqual(r[0][0], "🟢")
        self.assertIn("休市", r[0][2])


if __name__ == "__main__":
    unittest.main()
