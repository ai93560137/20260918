#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gcp_agent.py 的離線測試：用假的 AuthorizedSession 模擬 GCP REST 回應，
驗證各子命令打的網址、updateMask、輪詢與安全機制（沒有 --yes 不會改動）。

執行：python3 -m unittest scripts/test_gcp_agent.py -v
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gcp_agent", HERE / "gcp_agent.py")
ga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga)

PROJECT = "demo-proj"
REGION = "asia-east1"
FN = "receive_tradingview_signal"
FN_NAME = f"projects/{PROJECT}/locations/{REGION}/functions/{FN}"
SERVICE = f"projects/{PROJECT}/locations/{REGION}/services/receive-tradingview-signal"
URI = "https://receive-tradingview-signal-abc-de.a.run.app"


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"} if body is not None else {"content-type": "text/plain"}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def fn_body(env=None, state="ACTIVE"):
    return {
        "name": FN_NAME, "state": state, "updateTime": "2026-09-26T01:02:03Z",
        "buildConfig": {"runtime": "python312", "entryPoint": FN},
        "serviceConfig": {"uri": URI, "service": SERVICE, "availableMemory": "512Mi", "timeoutSeconds": 60,
                          "revision": "rev-7", "environmentVariables": env if env is not None else {"WEBHOOK_SECRET_TOKEN": "supersecret123", "TARGET_RRR": "3"}},
    }


class FakeSession:
    """記錄每一次呼叫；用 handlers 決定回應。"""

    def __init__(self, handlers):
        self.calls = []
        self.handlers = handlers  # list of (method, url_substring, response or callable)

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for m, sub, resp in self.handlers:
            if m == method and sub in url:
                return resp(method, url, kw) if callable(resp) else resp
        raise AssertionError(f"未預期的呼叫 {method} {url}")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


def run(argv, session, env_extra=None):
    """跑 CLI，回傳 (stdout, exit_code)。"""
    env = {"GCP_PROJECT": PROJECT, "GCP_REGION": REGION}
    env.update(env_extra or {})
    out = io.StringIO()
    code = 0
    with mock.patch.dict("os.environ", env, clear=False), \
         mock.patch.object(ga.Ctx, "session", new_callable=mock.PropertyMock, return_value=session), \
         mock.patch.object(ga.time, "sleep", lambda *_: None), \
         redirect_stdout(out):
        try:
            ga.main(argv)
        except SystemExit as exc:
            code = exc.code or 0
    return out.getvalue(), code


class StatusAndEnvTests(unittest.TestCase):
    def test_status_masks_secrets(self):
        s = FakeSession([("GET", FN_NAME, FakeResp(200, fn_body()))])
        out, code = run(["status"], s)
        self.assertEqual(code, 0)
        self.assertIn(URI, out)
        self.assertNotIn("supersecret123", out)
        self.assertIn("TARGET_RRR=3", out)

    def test_env_set_without_yes_is_dry_run(self):
        s = FakeSession([("GET", FN_NAME, FakeResp(200, fn_body()))])
        out, code = run(["env", "set", "TARGET_RRR=2"], s)
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertFalse(any(m == "PATCH" for m, _, _ in s.calls))

    def test_env_set_with_yes_patches_only_env_mask(self):
        op_name = f"projects/{PROJECT}/locations/{REGION}/operations/op1"
        polls = iter([
            FakeResp(200, {"name": op_name, "done": False, "metadata": {"stages": [{"name": "SERVICE", "state": "IN_PROGRESS"}]}}),
            FakeResp(200, {"name": op_name, "done": True, "response": fn_body(env={"WEBHOOK_SECRET_TOKEN": "supersecret123", "TARGET_RRR": "2"})}),
        ])
        s = FakeSession([
            ("GET", FN_NAME, FakeResp(200, fn_body())),
            ("PATCH", FN_NAME, FakeResp(200, {"name": op_name, "done": False})),
            ("GET", op_name, lambda *_: next(polls)),
        ])
        out, code = run(["env", "set", "TARGET_RRR=2", "--yes"], s)
        self.assertEqual(code, 0, out)
        patch = next(c for c in s.calls if c[0] == "PATCH")
        self.assertEqual(patch[2]["params"]["updateMask"], "serviceConfig.environmentVariables")
        sent = patch[2]["json"]["serviceConfig"]["environmentVariables"]
        self.assertEqual(sent, {"WEBHOOK_SECRET_TOKEN": "supersecret123", "TARGET_RRR": "2"})  # 合併，不會洗掉既有變數
        self.assertIn("✅ 完成", out)


class LogsAndStateTests(unittest.TestCase):
    def test_logs_filter_and_output(self):
        entries = {"entries": [
            {"timestamp": "2026-09-26T00:00:01Z", "severity": "INFO", "textPayload": "✅ [已送出] BUY 0.01"},
            {"timestamp": "2026-09-26T00:00:00Z", "severity": "WARNING", "jsonPayload": {"message": "news lock"}},
        ]}
        s = FakeSession([("POST", "entries:list", FakeResp(200, entries))])
        out, code = run(["logs", "--since", "30m", "--grep", "已送出", "--severity", "warning"], s)
        self.assertEqual(code, 0)
        body = s.calls[0][2]["json"]
        self.assertIn('service_name="receive-tradingview-signal"', body["filter"])
        self.assertIn(f'function_name="{FN}"', body["filter"])
        self.assertIn('textPayload:"已送出"', body["filter"])
        self.assertIn("severity>=WARNING", body["filter"])
        self.assertEqual(body["resourceNames"], [f"projects/{PROJECT}"])
        self.assertIn("08:00:01", out)  # HK 時間
        self.assertIn("news lock", out)

    def test_state_reads_bucket_objects(self):
        def gcs(method, url, kw):
            if "zhuge_gate_state.json" in url:
                return FakeResp(200, {"regime": "TREND", "armed": True})
            if "gcp_decision_log.json" in url:
                return FakeResp(200, [{"t": 1}, {"t": 2}, {"t": 3}])
            return FakeResp(404, text="not found")
        s = FakeSession([("GET", "/b/zhuge-risk-manager-bucket/o/", gcs)])
        out, code = run(["state", "--tail", "2"], s)
        self.assertEqual(code, 0)
        self.assertIn('"regime": "TREND"', out)
        self.assertIn('{"t": 2}', out)
        self.assertNotIn('{"t": 1}', out)
        self.assertIn("（不存在）", out)


class DeployTests(unittest.TestCase):
    def test_deploy_dry_run_makes_no_write(self):
        s = FakeSession([("GET", FN_NAME, FakeResp(200, fn_body()))])
        out, code = run(["deploy"], s)
        self.assertEqual(code, 0, out)
        self.assertIn("main.py", out)
        self.assertIn("dry-run", out)
        self.assertEqual([m for m, _, _ in s.calls], ["GET"])

    def test_deploy_rejects_broken_source(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for name in ga.DEPLOY_FILES:
                (Path(d) / name).write_text("broken", encoding="utf-8")
            s = FakeSession([])
            out, code = run(["deploy", "--source", d], s)
        self.assertEqual(code, 1)
        self.assertIn("找不到 def receive_tradingview_signal", out)

    def test_deploy_create_flow(self):
        op_name = f"projects/{PROJECT}/locations/{REGION}/operations/op2"
        upload = {"uploadUrl": "https://storage.googleapis.com/upload-signed", "storageSource": {"bucket": "gcf-src", "object": "x.zip", "generation": "1"}}
        s = FakeSession([
            ("GET", FN_NAME, FakeResp(404, text="not found")),
            ("POST", "functions:generateUploadUrl", FakeResp(200, upload)),
            ("POST", f"locations/{REGION}/functions", FakeResp(200, {"name": op_name, "done": False})),
            ("GET", op_name, FakeResp(200, {"name": op_name, "done": True, "response": fn_body(env={"TARGET_RRR": "3"})})),
            ("GET", f"{SERVICE}:getIamPolicy", FakeResp(200, {"bindings": [], "etag": "e"})),
            ("POST", f"{SERVICE}:setIamPolicy", FakeResp(200, {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]})),
        ])
        with mock.patch.object(ga.requests, "put", return_value=FakeResp(200, text="ok")) as put:
            out, code = run(["deploy", "--yes", "--no-check", "--set-env", "TARGET_RRR=3"], s)
        self.assertEqual(code, 0, out)
        put.assert_called_once()
        self.assertEqual(put.call_args.args[0], upload["uploadUrl"])
        create = next(c for c in s.calls if c[0] == "POST" and c[1].endswith(f"locations/{REGION}/functions"))
        self.assertEqual(create[2]["params"], {"functionId": FN})
        body = create[2]["json"]
        self.assertEqual(body["buildConfig"]["entryPoint"], FN)
        self.assertEqual(body["buildConfig"]["source"]["storageSource"], upload["storageSource"])
        self.assertEqual(body["serviceConfig"]["environmentVariables"], {"TARGET_RRR": "3"})
        setiam = next(c for c in s.calls if c[1].endswith(":setIamPolicy"))
        self.assertIn({"role": "roles/run.invoker", "members": ["allUsers"]}, setiam[2]["json"]["policy"]["bindings"])
        self.assertIn("部署完成", out)

    def test_deploy_update_flow_preserves_env(self):
        op_name = f"projects/{PROJECT}/locations/{REGION}/operations/op3"
        upload = {"uploadUrl": "https://storage.googleapis.com/upload-signed", "storageSource": {"bucket": "gcf-src", "object": "y.zip"}}
        s = FakeSession([
            ("GET", FN_NAME, FakeResp(200, fn_body())),
            ("POST", "functions:generateUploadUrl", FakeResp(200, upload)),
            ("PATCH", FN_NAME, FakeResp(200, {"name": op_name, "done": True, "response": fn_body()})),
        ])
        with mock.patch.object(ga.requests, "put", return_value=FakeResp(200, text="ok")):
            out, code = run(["deploy", "--yes", "--no-check"], s)
        self.assertEqual(code, 0, out)
        patch = next(c for c in s.calls if c[0] == "PATCH")
        self.assertIn("buildConfig.source", patch[2]["params"]["updateMask"])
        self.assertIn("serviceConfig.environmentVariables", patch[2]["params"]["updateMask"])
        self.assertEqual(patch[2]["json"]["serviceConfig"]["environmentVariables"]["WEBHOOK_SECRET_TOKEN"], "supersecret123")
        self.assertFalse(any(":setIamPolicy" in c[1] for c in s.calls))  # 更新時不動 IAM


class CheckTests(unittest.TestCase):
    def test_check_reports_pages(self):
        def fake_get(url, timeout):
            return FakeResp(200 if "order_app" not in url else 500, text="<html>" + "x" * 300 + "</html>")
        with mock.patch.object(ga.requests, "get", side_effect=fake_get):
            out, code = run(["check", "--url", URI], FakeSession([]))
        self.assertEqual(code, 1)
        self.assertIn("❌ order_app", out)
        self.assertIn("✅ dashboard", out)


if __name__ == "__main__":
    unittest.main()
