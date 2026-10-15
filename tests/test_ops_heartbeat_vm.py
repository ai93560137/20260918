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
        for obj, ts in self.gcs.items():
            if obj.replace("/", "%2F") in url:
                return _Resp(200, {"updated": ts})
        return _Resp(404, {})


NOW = datetime(2026, 10, 15, 7, 30, tzinfo=hb.HKT)   # 週四


class VmCheckTest(unittest.TestCase):
    def test_running_and_fresh(self):
        s = _Session(200, {"status": "RUNNING", "lastStartTimestamp": "2026-10-14T12:50:23.527-07:00"},
                     {"futu/snapshots/US.QQQ.json": "2026-10-14T23:25:00Z",
                      "futu/snapshots/HK.HSI_IV.json": "2026-10-14T23:00:00Z"})
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
        self.assertEqual(lights, ["🔴", "🟢"])


if __name__ == "__main__":
    unittest.main()
