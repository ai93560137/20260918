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

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


def run(argv, session, env_extra=None):
    """跑 CLI，回傳 (stdout, exit_code)。"""
    env = {"GCP_PROJECT": PROJECT, "GCP_REGION": REGION, "GCP_TARGET": "function"}
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


RUN_REGION = "europe-west1"
SVC = "zhuge-risk-manager"
SVC_NAME = f"projects/{PROJECT}/locations/{RUN_REGION}/services/{SVC}"
RUN_URL = "https://zhuge-risk-manager-123.europe-west1.run.app"
RUN_ENV = {"GCP_TARGET": "run", "GCP_RUN_REGION": RUN_REGION, "GCP_SERVICE": SVC}


def svc_body(ready=True):
    return {
        "name": SVC_NAME, "updateTime": "2026-09-27T20:02:13Z", "lastModifier": "someone@example.com",
        "uri": "https://zhuge-risk-manager-xyz-ew.a.run.app", "urls": [RUN_URL, "https://zhuge-risk-manager-xyz-ew.a.run.app"],
        "ingress": "INGRESS_TRAFFIC_ALL", "latestReadyRevision": f"{SVC_NAME}/revisions/{SVC}-00231-szd",
        "terminalCondition": {"type": "Ready", "state": "CONDITION_SUCCEEDED" if ready else "CONDITION_FAILED",
                              "message": "" if ready else "container failed to start"},
        "template": {"timeout": "300s", "serviceAccount": "sa@x.iam.gserviceaccount.com",
                     "scaling": {"maxInstanceCount": 20},
                     "containers": [{"image": "europe-west1-docker.pkg.dev/p/cloud-run-source-deploy/zhuge-risk-manager@sha256:abc",
                                     "baseImageUri": "europe-west1-docker.pkg.dev/serverless-runtimes/google-22-full/runtimes/python311",
                                     "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
                                     "env": [{"name": "WEBHOOK_API_KEY", "value": "supersecret123"},
                                             {"name": "BROKER_API_URL", "value": "https://broker.example/hook.php?t=abc123tok&x=1"},
                                             {"name": "DB_PASS", "valueSource": {"secretKeyRef": {"secret": "db-pass", "version": "3"}}}]}]},
        "traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100}],
        "trafficStatuses": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100}],
        "etag": "\"etag-1\"",
        "buildConfig": {"name": "projects/1/locations/europe-west1/builds/old", "functionTarget": FN,
                        "sourceLocation": "gs://run-sources-demo-proj-europe-west1/services/zhuge-risk-manager/1.zip#1",
                        "imageUri": f"europe-west1-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/{SVC}:latest",
                        "baseImage": "europe-west1-docker.pkg.dev/serverless-runtimes/google-22-full/runtimes/python311",
                        "enableAutomaticUpdates": True, "environmentVariables": {"GOOGLE_FUNCTION_TARGET": FN}},
    }


def rev_body(n, ready=True, created="2026-09-27T20:00:00Z"):
    return {"name": f"{SVC_NAME}/revisions/{SVC}-{n:05d}-abc", "createTime": created,
            "conditions": [{"type": "Ready", "state": "CONDITION_SUCCEEDED" if ready else "CONDITION_FAILED"}],
            "containers": [{"image": f"europe-west1-docker.pkg.dev/p/r/{SVC}@sha256:{n:064d}"}]}


REVS = {"revisions": [rev_body(229, created="2026-09-26T10:00:00Z"), rev_body(231, created="2026-09-27T20:02:00Z"),
                      rev_body(230, ready=False, created="2026-09-27T19:00:00Z")]}
OP = f"projects/{PROJECT}/locations/{RUN_REGION}/operations/op-run"


class MaskTests(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(ga.mask("WEBHOOK_API_KEY", "abcdefgh"), "ab…gh")
        self.assertEqual(ga.mask("URL", "https://h/p?t=tok#frag"), "https://h/p?t=••••#frag")
        self.assertEqual(ga.mask("URL", "https://h/p"), "https://h/p")
        self.assertEqual(ga.mask("TARGET_RRR", "3"), "3")


class CloudRunTargetTests(unittest.TestCase):
    def test_default_target_is_run_europe_west1(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            ctx = ga.Ctx(ga.build_parser().parse_args(["--project", PROJECT, "status"]))
        self.assertEqual(ctx.target, "run")
        self.assertEqual(ctx.svc_name, SVC_NAME)

    def test_run_ignores_function_region_env(self):
        # session-start hook 會把 GCP_REGION 設成 asia-east1；run 模式不應被它影響
        with mock.patch.dict("os.environ", {"GCP_REGION": "asia-east1"}, clear=True):
            ctx = ga.Ctx(ga.build_parser().parse_args(["--project", PROJECT, "status"]))
        self.assertEqual(ctx.region, RUN_REGION)
        with mock.patch.dict("os.environ", {"GCP_REGION": "asia-east1"}, clear=True):
            ctx = ga.Ctx(ga.build_parser().parse_args(["--project", PROJECT, "--region", "asia-east2", "status"]))
        self.assertEqual(ctx.region, "asia-east2")

    def test_status_run_masks_secrets(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["status"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertEqual(s.calls[0][1], f"{ga.RUN_API}/{SVC_NAME}")
        self.assertIn("✅ Ready", out)
        self.assertIn(RUN_URL, out)
        self.assertIn(f"{SVC}-00231-szd", out)
        self.assertIn("BROKER_API_URL=https://broker.example/hook.php?t=••••&x=••••", out)
        self.assertNotIn("abc123tok", out)
        self.assertIn("DB_PASS=<secret db-pass:3>", out)
        self.assertNotIn("supersecret123", out)

    def test_status_run_not_ready_and_missing(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body(ready=False)))])
        out, _ = run(["status"], s, RUN_ENV)
        self.assertIn("❌ CONDITION_FAILED", out)
        self.assertIn("container failed to start", out)
        s = FakeSession([("GET", SVC_NAME, FakeResp(404, text="nope"))])
        out, code = run(["status"], s, RUN_ENV)
        self.assertEqual(code, 0)
        self.assertIn("不存在", out)

    def test_logs_run_filter(self):
        entries = {"entries": [
            {"timestamp": "2026-09-26T00:00:02Z", "severity": "INFO", "jsonPayload": {"message": "📤 [回應] HTTP 200"}},
            {"timestamp": "2026-09-26T00:00:01Z", "severity": "INFO", "httpRequest": {"requestMethod": "POST", "status": 200, "requestUrl": RUN_URL}},
        ]}
        s = FakeSession([("POST", "entries:list", FakeResp(200, entries))])
        out, code = run(["logs", "--grep", "已送出"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        flt = s.calls[0][2]["json"]["filter"]
        self.assertIn(f'service_name="{SVC}"', flt)
        self.assertIn(f'location="{RUN_REGION}"', flt)
        self.assertNotIn("cloud_function", flt)
        self.assertIn('jsonPayload.message:"已送出"', flt)
        self.assertIn("📤 [回應] HTTP 200", out)
        self.assertIn("[HTTP] POST 200", out)

    def test_check_run_uses_service_url(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        seen = []
        def fake_get(url, timeout):
            seen.append(url)
            return FakeResp(200, text="<html>" + "x" * 300 + "</html>")
        with mock.patch.object(ga.requests, "get", side_effect=fake_get):
            out, code = run(["check"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen[0], RUN_URL)
        self.assertEqual(len(seen), 5)

    def test_env_get_run_masks(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["env", "get"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("BROKER_API_URL=https://broker.example/hook.php?t=••••&x=••••", out)
        self.assertNotIn("abc123tok", out)
        self.assertNotIn("supersecret123", out)

    def test_iam_public_refused_in_run_mode(self):
        s = FakeSession([])
        out, code = run(["iam-public", "--yes"], s, RUN_ENV)
        self.assertEqual(code, 1)
        self.assertEqual(s.calls, [])

    def test_deploy_local_only_makes_no_call(self):
        s = FakeSession([])
        out, code = run(["deploy", "--local-only"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("只做本機套件檢查", out)
        self.assertEqual(s.calls, [])


def writes(session):
    return [c for c in session.calls if c[0] in ("PATCH", "PUT", "DELETE")
            or (c[0] == "POST" and not c[1].endswith(("testIamPermissions", "entries:list")))]


def done_op(name=OP, response=None):
    return FakeResp(200, {"name": name, "done": True, "response": response or {}})


class CloudRunWriteTests(unittest.TestCase):
    def test_env_set_dry_run_no_write_and_masked(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["env", "set", "TARGET_RRR=2", "WEBHOOK_API_KEY=newsecret999"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertEqual(writes(s), [])
        self.assertIn("新增 TARGET_RRR=2", out)
        self.assertIn("修改 WEBHOOK_API_KEY", out)
        self.assertNotIn("newsecret999", out)
        self.assertNotIn("supersecret123", out)
        self.assertIn("dry-run", out)

    def test_env_set_yes_validates_then_patches(self):
        new_svc = svc_body()
        new_svc["latestReadyRevision"] = f"{SVC_NAME}/revisions/{SVC}-00232-new"
        gets = iter([FakeResp(200, svc_body()), FakeResp(200, new_svc)])
        s = FakeSession([
            ("GET", OP, done_op()),
            ("GET", SVC_NAME, lambda *_: next(gets)),
            ("PATCH", SVC_NAME, lambda m, u, kw: done_op() if not kw.get("params") else FakeResp(200, {"name": OP, "done": True})),
        ])
        out, code = run(["env", "set", "TARGET_RRR=2", "--yes"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        patches = [c for c in s.calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[0][2]["params"], {"validateOnly": "true"})
        self.assertNotIn("params", patches[1][2])
        body = patches[1][2]["json"]
        self.assertEqual(body["etag"], "\"etag-1\"")
        env = body["template"]["containers"][0]["env"]
        self.assertIn({"name": "TARGET_RRR", "value": "2"}, env)
        self.assertIn({"name": "WEBHOOK_API_KEY", "value": "supersecret123"}, env)  # 既有變數保留
        self.assertIn("secretKeyRef", json.dumps(env))  # Secret 參照保留
        self.assertEqual(body["traffic"], ga.LATEST_TRAFFIC)
        self.assertEqual(body["template"]["containers"][0]["image"], svc_body()["template"]["containers"][0]["image"])
        self.assertIn(f"rollback --to {SVC}-00231-szd --yes", out)
        self.assertNotIn("supersecret123", out)

    def test_env_set_refuses_secret_ref(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["env", "set", "DB_PASS=x", "--yes"], s, RUN_ENV)
        self.assertEqual(code, 1)
        self.assertEqual(writes(s), [])

    def test_env_unset_and_no_change(self):
        s = FakeSession([("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, _ = run(["env", "unset", "BROKER_API_URL"], s, RUN_ENV)
        self.assertIn("移除 BROKER_API_URL", out)
        out, _ = run(["env", "set", "WEBHOOK_API_KEY=supersecret123"], s, RUN_ENV)
        self.assertIn("沒有變更", out)
        self.assertEqual(writes(s), [])

    def test_revisions_lists_traffic(self):
        s = FakeSession([("GET", f"{SVC_NAME}/revisions", FakeResp(200, REVS)), ("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["revisions"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        lines = [l for l in out.splitlines() if SVC in l]
        self.assertTrue(lines[0].startswith(f"{SVC}-00231"))  # 最新在前
        self.assertIn("❌", lines[1])

    def test_rollback_default_picks_previous_ready(self):
        svc = svc_body()
        svc["latestReadyRevision"] = f"{SVC_NAME}/revisions/{SVC}-00231-abc"
        s = FakeSession([("GET", f"{SVC_NAME}/revisions", FakeResp(200, REVS)), ("GET", SVC_NAME, FakeResp(200, svc))])
        out, code = run(["rollback"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn(f"100% → {SVC}-00229-abc", out)  # 跳過失敗的 00230
        self.assertEqual(writes(s), [])

    def test_rollback_yes_sets_revision_traffic(self):
        svc = svc_body()
        svc["latestReadyRevision"] = f"{SVC_NAME}/revisions/{SVC}-00231-abc"
        s = FakeSession([
            ("GET", f"{SVC_NAME}/revisions", FakeResp(200, REVS)),
            ("GET", OP, done_op()),
            ("GET", SVC_NAME, FakeResp(200, svc)),
            ("PATCH", SVC_NAME, FakeResp(200, {"name": OP, "done": True})),
        ])
        out, code = run(["rollback", "--to", f"{SVC}-00229-abc", "--yes"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        body = [c for c in s.calls if c[0] == "PATCH"][-1][2]["json"]
        self.assertEqual(body["traffic"], [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION", "revision": f"{SVC}-00229-abc", "percent": 100}])
        self.assertEqual(body["template"], svc["template"])  # 不動範本 → 不建新修訂

    def test_rollback_refuses_failed_revision(self):
        s = FakeSession([("GET", f"{SVC_NAME}/revisions", FakeResp(200, REVS)), ("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["rollback", "--to", f"{SVC}-00230-abc", "--yes"], s, RUN_ENV)
        self.assertEqual(code, 1)
        self.assertEqual(writes(s), [])


def perm_handlers(ok=True):
    def crm(m, u, kw):
        return FakeResp(200, {"permissions": kw["json"]["permissions"]} if ok else {})
    def gcs(m, u, kw):
        return FakeResp(200, {"permissions": ["storage.objects.create"]} if ok else {"kind": "x"})
    def run_perm(m, u, kw):
        return FakeResp(200, {"permissions": ["run.services.update"]})
    return [("POST", ":testIamPermissions", lambda m, u, kw: crm(m, u, kw) if "cloudresourcemanager" in u else run_perm(m, u, kw)),
            ("GET", "/iam/testPermissions", gcs)]


class CloudRunDeployTests(unittest.TestCase):
    def test_deploy_dry_run_reports_missing_permissions(self):
        s = FakeSession(perm_handlers(ok=False) + [("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["deploy"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("roles/cloudbuild.builds.editor", out)
        self.assertIn("run-sources-demo-proj-europe-west1", out)
        self.assertIn("dry-run", out)
        self.assertEqual(writes(s), [])

    def test_deploy_yes_without_permissions_stops_before_upload(self):
        s = FakeSession(perm_handlers(ok=False) + [("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["deploy", "--yes", "--no-check"], s, RUN_ENV)
        self.assertEqual(code, 1)
        self.assertEqual(writes(s), [])

    def test_build_id_from_operation(self):
        import base64
        name = f"operations/build/{PROJECT}/" + base64.b64encode(b"05d72ba7-4db3-4ede-ad99-d19c62b91a09").decode().rstrip("=")
        self.assertEqual(ga.build_id_from_operation({"name": name}), "05d72ba7-4db3-4ede-ad99-d19c62b91a09")
        self.assertEqual(ga.build_id_from_operation({"name": "x", "metadata": {"build": {"id": "abc"}}}), "abc")
        self.assertIsNone(ga.build_id_from_operation({"name": "projects/p/locations/l/operations/o"}))

    def test_deploy_yes_full_flow(self):
        import base64
        image = f"europe-west1-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/{SVC}:latest"
        build_op = f"operations/build/{PROJECT}/" + base64.b64encode(b"bid-1").decode()
        build_url = f"projects/{PROJECT}/locations/{RUN_REGION}/builds/bid-1"
        build_polls = iter([
            FakeResp(200, {"id": "bid-1", "status": "WORKING"}),
            FakeResp(200, {"id": "bid-1", "status": "SUCCESS",
                           "results": {"images": [{"name": image, "digest": "sha256:" + "f" * 64}]}}),
        ])
        s = FakeSession(perm_handlers(ok=True) + [
            ("POST", "/upload/storage/v1/b/run-sources-demo-proj-europe-west1/o", FakeResp(200, {"name": "x", "generation": "777"})),
            ("POST", f"locations/{RUN_REGION}/builds:submit", FakeResp(200, {"buildOperation": {"name": build_op, "done": False}})),
            ("GET", build_url, lambda *_: next(build_polls)),
            ("GET", OP, done_op()),
            ("GET", SVC_NAME, FakeResp(200, svc_body())),
            ("PATCH", SVC_NAME, FakeResp(200, {"name": OP, "done": True})),
        ])
        out, code = run(["deploy", "--yes", "--no-check"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        up = next(c for c in s.calls if "/upload/" in c[1])
        self.assertEqual(up[2]["headers"]["Content-Type"], "application/zip")
        self.assertTrue(up[2]["data"].startswith(b"PK"))
        self.assertTrue(up[2]["params"]["name"].startswith(f"services/{SVC}/"))
        submit = next(c for c in s.calls if c[1].endswith("builds:submit"))[2]["json"]
        self.assertEqual(submit["imageUri"], image)
        self.assertEqual(submit["storageSource"]["generation"], "777")
        self.assertEqual(submit["buildpackBuild"]["functionTarget"], FN)
        self.assertTrue(any(c[1].startswith(ga.CB_API) for c in s.calls))  # 建置操作輪詢 Cloud Build
        patches = [c for c in s.calls if c[0] == "PATCH"]
        self.assertEqual(patches[0][2]["params"], {"validateOnly": "true"})
        body = patches[-1][2]["json"]
        self.assertEqual(body["template"]["containers"][0]["image"], f"{image}@sha256:" + "f" * 64)
        self.assertNotIn("name", body["buildConfig"])
        self.assertTrue(body["buildConfig"]["sourceLocation"].endswith("#777"))
        self.assertEqual(body["traffic"], ga.LATEST_TRAFFIC)
        env_names = [e["name"] for e in body["template"]["containers"][0]["env"]]
        self.assertEqual(env_names, ["WEBHOOK_API_KEY", "BROKER_API_URL", "DB_PASS"])  # 環境變數不變
        self.assertNotIn("supersecret123", out)

    def test_deploy_build_failure_does_not_touch_service(self):
        build_op = f"projects/{PROJECT}/locations/{RUN_REGION}/operations/build-2"
        s = FakeSession(perm_handlers(ok=True) + [
            ("POST", "/upload/storage/", FakeResp(200, {"generation": "1"})),
            ("POST", "builds:submit", FakeResp(200, {"buildOperation": {"name": build_op, "done": True,
                                                                           "metadata": {"build": {"id": "bid-2"}}}})),
            ("GET", "/builds/bid-2", FakeResp(200, {"id": "bid-2", "status": "FAILURE", "logUrl": "https://log"})),
            ("GET", SVC_NAME, FakeResp(200, svc_body())),
        ])
        out, code = run(["deploy", "--yes", "--no-check"], s, RUN_ENV)
        self.assertEqual(code, 1)
        self.assertFalse(any(c[0] == "PATCH" for c in s.calls))


class CheckTests(unittest.TestCase):
    def test_check_reports_pages(self):
        def fake_get(url, timeout):
            return FakeResp(200 if "longfei" not in url else 500, text="<html>" + "x" * 300 + "</html>")
        with mock.patch.object(ga.requests, "get", side_effect=fake_get):
            out, code = run(["check", "--url", URI], FakeSession([]))
        self.assertEqual(code, 1)
        self.assertIn("❌ longfei", out)
        self.assertIn("✅ strategies", out)


XAU_SVC_NAME = f"projects/{PROJECT}/locations/{RUN_REGION}/services/zhuge-xau"


def create_perm_handlers(ok=True):
    perms = (["cloudbuild.builds.create", "cloudbuild.builds.get", "run.services.create", "run.services.get"] if ok else [])
    return [("POST", f"projects/{PROJECT}:testIamPermissions", FakeResp(200, {"permissions": perms})),
            ("GET", "run-sources-demo-proj-europe-west1/iam/testPermissions",
             FakeResp(200, {"permissions": ["storage.objects.create"] if ok else []}))]


class XauProfileTests(unittest.TestCase):
    """[R291] 天覆陣 profile：打包 xau/、服務 zhuge-xau、進入點 xau_entry、服務不存在就建立（唔改 IAM）。"""

    def test_local_only_packs_xau_files(self):
        s = FakeSession([])
        out, code = run(["--profile", "xau", "deploy", "--local-only"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("profile zhuge-xau", out)
        for name in ("brain.py", "rules.py", "reference/legacy_rules.md"):
            self.assertIn(name, out)
        self.assertNotIn("gates.html", out)
        self.assertEqual(s.calls, [])

    def test_xau_files_cover_all_py_and_imports(self):
        files = ga.profile_files(ga.PROFILES["xau"])
        src = ga.PROFILES["xau"]["source"]
        for p in src.glob("*.py"):
            self.assertIn(p.name, files)
        self.assertIn("reference/legacy_rules.md", files)
        self.assertEqual(ga.missing_local_imports(src, files), [])
        # 漏咗一個模組 → 來源檢查要擋（10-20 真實事故：冇 notify.py，修訂 exit(82)）
        short = tuple(f for f in files if f != "notify.py")
        self.assertEqual(ga.missing_local_imports(src, short), ["notify.py"])
        problems = ga.sanity_check_sources(src, {**ga.PROFILES["xau"], "files": short})
        self.assertTrue(any("notify.py" in p for p in problems), problems)

    def test_status_uses_profile_service(self):
        s = FakeSession([("GET", XAU_SVC_NAME, FakeResp(404, text="nf"))])
        out, code = run(["--profile", "xau", "status"], s, RUN_ENV)
        self.assertIn("zhuge-xau", out)

    def test_dry_run_create_plans_without_writing(self):
        s = FakeSession(create_perm_handlers(ok=True) + [
            ("GET", XAU_SVC_NAME, FakeResp(404, text="nf")),
            ("GET", SVC_NAME, FakeResp(200, svc_body())),          # 樣板：沿用舊服務 baseImage
        ])
        out, code = run(["--profile", "xau", "deploy", "--set-env", "XAU_EXECUTE=0"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("建立新 Cloud Run 服務", out)
        self.assertIn("xau_entry", out)
        self.assertIn("python311", out)
        self.assertIn("唔會**自動開放未經驗證叫用", out)
        self.assertIn("dry-run", out)
        self.assertEqual(writes(s), [])

    def test_dry_run_create_reports_missing_permissions(self):
        s = FakeSession(create_perm_handlers(ok=False) + [
            ("GET", XAU_SVC_NAME, FakeResp(404, text="nf")), ("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["--profile", "xau", "deploy"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("run.services.create", out)
        self.assertEqual(writes(s), [])

    def test_yes_create_flow(self):
        build_op = {"name": f"operations/build/{PROJECT}/abc", "done": False}
        build_done = {"name": build_op["name"], "done": True, "response": {"status": "SUCCESS", "results": {"images": [
            {"name": f"europe-west1-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/zhuge-xau:latest", "digest": "sha256:new"}]}}}
        created = {**svc_body(), "name": XAU_SVC_NAME, "latestReadyRevision": f"{XAU_SVC_NAME}/revisions/zhuge-xau-00001-abc"}
        s = FakeSession(create_perm_handlers(ok=True) + [
            ("GET", XAU_SVC_NAME, lambda m, u, kw: FakeResp(404, text="nf") if not any(c[0] == "POST" and c[1].endswith("/services") and "validateOnly" not in (c[2].get("params") or {}) for c in s.calls) else FakeResp(200, created)),
            ("GET", SVC_NAME, FakeResp(200, svc_body())),
            ("POST", "run-sources-demo-proj-europe-west1/o", FakeResp(200, {"generation": "7"})),
            ("POST", "builds:submit", FakeResp(200, {"buildOperation": build_op})),
            ("GET", build_op["name"], FakeResp(200, build_done)),
            ("POST", f"locations/{RUN_REGION}/services", FakeResp(200, {"name": "projects/p/locations/l/operations/o9", "done": True, "response": created})),
        ])
        out, code = run(["--profile", "xau", "deploy", "--yes", "--no-check", "--set-env", "XAU_EXECUTE=0", "CLAUDE_MODEL=claude-opus-5-5",
                         "--copy-env", "WEBHOOK_API_KEY"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        creates = [c for c in s.calls if c[0] == "POST" and c[1].endswith("/services")]
        self.assertEqual(len(creates), 2, "validateOnly 一次、真建立一次")
        self.assertEqual(creates[0][2]["params"], {"serviceId": "zhuge-xau", "validateOnly": "true"})
        body = creates[1][2]["json"]
        self.assertNotIn("name", body)
        self.assertEqual(body["buildConfig"]["functionTarget"], "xau_entry")
        self.assertEqual(body["template"]["containers"][0]["image"],
                         f"europe-west1-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/zhuge-xau:latest@sha256:new")
        self.assertEqual({e["name"]: e["value"] for e in body["template"]["containers"][0]["env"]},
                         {"XAU_EXECUTE": "0", "CLAUDE_MODEL": "claude-opus-5-5", "WEBHOOK_API_KEY": "supersecret123"})
        self.assertNotIn("supersecret123", out, "抄過嚟嘅值唔可以印出")
        self.assertEqual(body["template"]["serviceAccount"], "sa@x.iam.gserviceaccount.com")
        self.assertEqual(body["template"]["containers"][0]["baseImageUri"],
                         "europe-west1-docker.pkg.dev/serverless-runtimes/google-22-full/runtimes/python311", "建立時要抄 baseImageUri，否則容器冇 runtime")
        self.assertFalse(any(c[1].endswith(":setIamPolicy") for c in s.calls), "唔改 IAM")

    def test_update_path_adds_missing_base_image_uri(self):
        """10-20 真實事故：zhuge-xau 容器冇 baseImageUri，enableAutomaticUpdates=true → direct exec 失敗。更新路徑要補上，dry-run 要印。"""
        broken = {**svc_body(), "name": XAU_SVC_NAME}
        broken["template"]["containers"][0].pop("baseImageUri")
        s = FakeSession(perm_handlers(ok=True) + [("GET", XAU_SVC_NAME, FakeResp(200, broken))])
        out, code = run(["--profile", "xau", "deploy"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("⚠️ 容器冇 baseImageUri", out)
        self.assertIn("python311", out)
        self.assertEqual(writes(s), [])
        ok_svc = {**svc_body(), "name": XAU_SVC_NAME}
        s2 = FakeSession(perm_handlers(ok=True) + [("GET", XAU_SVC_NAME, FakeResp(200, ok_svc))])
        out2, _ = run(["--profile", "xau", "deploy"], s2, RUN_ENV)
        self.assertNotIn("⚠️ 容器冇 baseImageUri", out2)   # 只對計畫嗰行（commit 訊息都可能有呢幾個字）


SIG_SVC_NAME = f"projects/{PROJECT}/locations/{RUN_REGION}/services/zhuge-xau-sig"


class XauSigProfileTests(unittest.TestCase):
    """TG 訊號書 profile（使用者 10-21 揀方案 B）：服務 zhuge-xau-sig；建立時自動加 XAU_BOOK=signal；
    更新時環境變數唔一致就拒絕（否則會變成第二個寫 xau/ 嘅主服務）。"""

    def test_local_only_packs_signals(self):
        s = FakeSession([])
        out, code = run(["--profile", "xausig", "deploy", "--local-only"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("profile zhuge-xau-sig", out)
        self.assertIn("signals.py", out)
        self.assertEqual(s.calls, [])

    def test_create_dry_run_adds_required_env(self):
        s = FakeSession(create_perm_handlers(ok=True) + [
            ("GET", SIG_SVC_NAME, FakeResp(404, text="nf")), ("GET", SVC_NAME, FakeResp(200, svc_body()))])
        out, code = run(["--profile", "xausig", "deploy", "--set-env", "XAU_BOOK=claude"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("XAU_BOOK=signal", out)
        self.assertIn("zhuge-xau-sig", out)
        self.assertEqual(writes(s), [])

    def test_update_refuses_when_env_mismatch(self):
        svc = {**svc_body(), "name": SIG_SVC_NAME}
        s = FakeSession(perm_handlers(ok=True) + [("GET", SIG_SVC_NAME, FakeResp(200, svc))])
        out, code = run(["--profile", "xausig", "deploy"], s, RUN_ENV)
        self.assertNotEqual(code, 0, out)                 # die() 訊息寫 stderr
        self.assertNotIn("dry-run", out)
        self.assertEqual(writes(s), [])

    def test_update_ok_when_env_matches(self):
        svc = {**svc_body(), "name": SIG_SVC_NAME}
        svc["template"]["containers"][0]["env"] = [{"name": "XAU_BOOK", "value": "signal"}, {"name": "XAU_SYMBOL", "value": "XAUUSD"}]
        s = FakeSession(perm_handlers(ok=True) + [("GET", SIG_SVC_NAME, FakeResp(200, svc))])
        out, code = run(["--profile", "xausig", "deploy"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("dry-run", out)
        self.assertEqual(writes(s), [])


class VmCreateTests(unittest.TestCase):
    """天覆陣訊號書 VM：預設 dry-run、冇服務帳戶、OS Login、已存在就停、唔改 IAM。"""

    def test_body_has_no_service_account(self):
        b = ga.vm_body(PROJECT, "tg-relay", "us-central1-a", "e2-micro")
        self.assertEqual(b["serviceAccounts"], [])
        self.assertIn({"key": "enable-oslogin", "value": "TRUE"}, b["metadata"]["items"])
        self.assertTrue(b["shieldedInstanceConfig"]["enableSecureBoot"])

    def test_dry_run_no_writes(self):
        s = FakeSession([("GET", "zones/us-central1-a/instances/tg-relay", FakeResp(404, text="nf"))])
        out, code = run(["vm-create"], s, RUN_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("冇服務帳戶", out)
        self.assertIn("dry-run", out)
        self.assertEqual(writes(s), [])

    def test_existing_vm_stops(self):
        s = FakeSession([("GET", "zones/us-central1-a/instances/tg-relay", FakeResp(200, {"name": "tg-relay"}))])
        out, code = run(["vm-create", "--yes"], s, RUN_ENV)
        self.assertNotEqual(code, 0)
        self.assertEqual(writes(s), [])


if __name__ == "__main__":
    unittest.main()
