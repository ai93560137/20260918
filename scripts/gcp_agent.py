#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gcp_agent.py — 讓 Claude（或任何人）不用 gcloud 也能操作本專案的 GCP 資源。

只靠 REST API + 服務帳戶金鑰，因此在沒有 gcloud 的 Claude Code 雲端容器裡也能跑。

認證來源（依序）：
  1. 環境變數 GCP_SA_KEY        — 服務帳戶金鑰 JSON 的「內容」（可直接貼 JSON 或 base64）
  2. 環境變數 GOOGLE_APPLICATION_CREDENTIALS — 金鑰檔路徑
  3. Application Default Credentials（本機 gcloud auth application-default login / Cloud Shell）

專案 / 區域 / 函式名稱：
  GCP_PROJECT   （預設取金鑰檔的 project_id）
  GCP_REGION    （預設 asia-east1；香港可用 asia-east2）
  GCP_FUNCTION  （預設 receive_tradingview_signal）
  GCP_BUCKET    （預設 zhuge-risk-manager-bucket）

子命令：
  whoami        驗證憑證，列出專案、服務帳戶、已啟用 API
  status        Cloud Function 狀態、網址、執行階段設定、環境變數（值會遮罩）
  logs          讀 Cloud Logging（--since 2h --limit 100 --grep 已送出）
  state         讀 GCS 上的電閘 / 加單 / 決策日誌
  bucket        列出 bucket 物件（--prefix）
  cat           印出 bucket 內任一物件（--object path）
  check         打函式網址的五個頁面，確認都回 200
  env           顯示或修改環境變數（env set KEY=VAL ... --yes）
  deploy        打包四個檔案並部署（預設 dry-run；真的部署要加 --yes）
  iam-public    讓函式允許未經驗證的叫用（allUsers → roles/run.invoker）

所有會改動 GCP 的命令都需要 --yes；沒有 --yes 只會印出「將會做什麼」。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("缺少 requests：pip install requests google-auth", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_FILES = ("main.py", "requirements.txt", "gates.html", "order.html")
ENTRY_POINT = "receive_tradingview_signal"
DEFAULT_RUNTIME = "python312"
DEFAULT_MEMORY = "512Mi"
DEFAULT_TIMEOUT = 60
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
HK_TZ = timezone(timedelta(hours=8))

CF_API = "https://cloudfunctions.googleapis.com/v2"
RUN_API = "https://run.googleapis.com/v2"
LOG_API = "https://logging.googleapis.com/v2"
GCS_API = "https://storage.googleapis.com/storage/v1"
SU_API = "https://serviceusage.googleapis.com/v1"

SECRET_ENV_PATTERN = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD|PASS)", re.I)


# =============================================================================
# 認證
# =============================================================================
class Ctx:
    def __init__(self, args):
        self.args = args
        self.project = None
        self.account = None
        self._session = None
        self.region = os.environ.get("GCP_REGION", "asia-east1").strip()
        self.function = os.environ.get("GCP_FUNCTION", ENTRY_POINT).strip()
        self.bucket = os.environ.get("GCP_BUCKET", "zhuge-risk-manager-bucket").strip()
        if getattr(args, "region", None):
            self.region = args.region
        if getattr(args, "function", None):
            self.function = args.function
        if getattr(args, "bucket", None):
            self.bucket = args.bucket
        if getattr(args, "project", None):
            self.project = args.project
        elif os.environ.get("GCP_PROJECT"):
            self.project = os.environ["GCP_PROJECT"].strip()

    # ---- credentials -------------------------------------------------------
    def _load_credentials(self):
        try:
            from google.auth.transport.requests import AuthorizedSession  # noqa: F401  (import check)
            from google.oauth2 import service_account
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:  # noqa: BLE001  — 系統的 cryptography 可能壞掉（pyo3 panic 不是 Exception）
            die(f"google-auth 載入失敗：{type(exc).__name__}: {exc}\n"
                f"請執行：pip install --user -r {REPO_ROOT / 'scripts' / 'requirements-agent.txt'}")

        raw = os.environ.get("GCP_SA_KEY", "").strip()
        info = None
        if raw:
            if not raw.startswith("{"):
                try:
                    raw = base64.b64decode(raw).decode("utf-8")
                except Exception as exc:  # noqa: BLE001
                    die(f"GCP_SA_KEY 不是 JSON 也不是合法 base64：{exc}")
            try:
                info = json.loads(raw)
            except json.JSONDecodeError as exc:
                die(f"GCP_SA_KEY 解析失敗：{exc}")
        else:
            path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    try:
                        info = json.load(fh)
                    except json.JSONDecodeError:
                        info = None  # 可能是 authorized_user 之類，交給 ADC
                if info is not None and info.get("type") != "service_account":
                    info = None

        if info is not None:
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
            self.account = info.get("client_email")
            self.project = self.project or info.get("project_id")
            return creds

        import google.auth

        try:
            creds, adc_project = google.auth.default(scopes=SCOPES)
        except Exception as exc:  # noqa: BLE001
            die(
                "找不到 GCP 憑證。請在 Claude 雲端環境的設定加入環境變數 GCP_SA_KEY（服務帳戶金鑰 JSON），\n"
                "或本機執行 gcloud auth application-default login。\n"
                f"（詳細：{exc}）"
            )
        self.project = self.project or adc_project
        self.account = getattr(creds, "service_account_email", None) or "application-default"
        return creds

    @property
    def session(self):
        if self._session is None:
            from google.auth.transport.requests import AuthorizedSession

            creds = self._load_credentials()
            self._session = AuthorizedSession(creds)
            if not self.project:
                die("無法判斷專案 ID，請設定環境變數 GCP_PROJECT 或加 --project。")
        return self._session

    # ---- helpers -----------------------------------------------------------
    def call(self, method, url, ok=(200,), **kw):
        kw.setdefault("timeout", 60)
        resp = self.session.request(method, url, **kw)
        if resp.status_code not in ok:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:800]
            die(f"{method} {url}\nHTTP {resp.status_code}: {json.dumps(detail, ensure_ascii=False, indent=2)[:2000]}")
        if resp.status_code == 204 or not resp.content:
            return {}
        ctype = resp.headers.get("content-type", "")
        return resp.json() if "json" in ctype else resp.content

    @property
    def fn_parent(self):
        return f"projects/{self.project}/locations/{self.region}"

    @property
    def fn_name(self):
        return f"{self.fn_parent}/functions/{self.function}"


def die(msg, code=1):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def mask(key, value):
    if SECRET_ENV_PATTERN.search(key) and value:
        return value[:2] + "…" + value[-2:] if len(value) > 6 else "••••"
    return value


def hk_time(ts):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(HK_TZ).strftime("%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return ts


def parse_since(text):
    m = re.fullmatch(r"(\d+)([smhd])", text.strip())
    if not m:
        die("--since 格式：30m / 2h / 1d")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{{"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]: n})


def plan(msg):
    print(f"📝 {msg}")


# =============================================================================
# 子命令
# =============================================================================
def cmd_whoami(ctx: Ctx):
    ctx.session  # 觸發載入憑證
    print(f"✅ 憑證可用\n   帳戶：{ctx.account}\n   專案：{ctx.project}\n   區域：{ctx.region}\n   函式：{ctx.function}\n   Bucket：{ctx.bucket}")
    data = ctx.call("GET", f"{SU_API}/projects/{ctx.project}/services", params={"filter": "state:ENABLED", "pageSize": 200})
    names = sorted(s["config"]["name"] for s in data.get("services", []))
    wanted = ["cloudfunctions", "run", "cloudbuild", "artifactregistry", "storage", "logging", "aiplatform"]
    print("   已啟用 API：")
    for w in wanted:
        hit = next((n for n in names if n.startswith(w + ".")), None)
        print(f"     {'✅' if hit else '⚠️ 未啟用'} {w}.googleapis.com")


def get_function(ctx: Ctx, quiet=False):
    resp = ctx.session.get(f"{CF_API}/{ctx.fn_name}", timeout=60)
    if resp.status_code == 404:
        if not quiet:
            print(f"ℹ️ 函式 {ctx.fn_name} 尚未存在。")
        return None
    if resp.status_code != 200:
        die(f"讀取函式失敗 HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def cmd_status(ctx: Ctx):
    fn = get_function(ctx)
    if not fn:
        return
    sc = fn.get("serviceConfig", {})
    bc = fn.get("buildConfig", {})
    print(f"函式：{fn['name']}")
    print(f"狀態：{fn.get('state')}  更新：{hk_time(fn.get('updateTime', ''))} (HK)")
    print(f"網址：{sc.get('uri') or fn.get('url')}")
    print(f"執行階段：{bc.get('runtime')}  進入點：{bc.get('entryPoint')}")
    print(f"記憶體：{sc.get('availableMemory')}  逾時：{sc.get('timeoutSeconds')}s  服務帳戶：{sc.get('serviceAccountEmail')}")
    print(f"修訂：{sc.get('revision')}  Ingress：{sc.get('ingressSettings')}")
    if fn.get("stateMessages"):
        for m in fn["stateMessages"]:
            print(f"⚠️ {m.get('severity')}: {m.get('message')}")
    env = sc.get("environmentVariables", {})
    print(f"環境變數（{len(env)}）：")
    for k in sorted(env):
        print(f"   {k}={mask(k, env[k])}")


def cmd_logs(ctx: Ctx):
    a = ctx.args
    since = datetime.now(timezone.utc) - parse_since(a.since)
    service = ctx.function.replace("_", "-")
    flt = (
        f'((resource.type="cloud_run_revision" AND resource.labels.service_name="{service}") '
        f'OR (resource.type="cloud_function" AND resource.labels.function_name="{ctx.function}")) '
        f'AND timestamp>="{since.isoformat()}"'
    )
    if a.severity:
        flt += f" AND severity>={a.severity.upper()}"
    if a.grep:
        flt += f' AND textPayload:"{a.grep}"'
    body = {"resourceNames": [f"projects/{ctx.project}"], "filter": flt, "orderBy": "timestamp desc", "pageSize": min(a.limit, 1000)}
    data = ctx.call("POST", f"{LOG_API}/entries:list", json=body)
    entries = data.get("entries", [])
    if not entries:
        print(f"（過去 {a.since} 沒有日誌）")
        return
    for e in reversed(entries):
        payload = e.get("textPayload")
        if payload is None:
            jp = e.get("jsonPayload") or {}
            payload = jp.get("message") or json.dumps(jp, ensure_ascii=False)
        sev = (e.get("severity") or "DEFAULT")[:4]
        print(f"{hk_time(e['timestamp'])} {sev:<4} {str(payload).rstrip()}")
    print(f"—— {len(entries)} 筆（HK 時間）——")


def gcs_get(ctx: Ctx, obj, as_json=True):
    from urllib.parse import quote

    resp = ctx.session.get(f"{GCS_API}/b/{ctx.bucket}/o/{quote(obj, safe='')}", params={"alt": "media"}, timeout=60)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        die(f"讀取 gs://{ctx.bucket}/{obj} 失敗 HTTP {resp.status_code}: {resp.text[:300]}")
    if not as_json:
        return resp.content
    try:
        return resp.json()
    except ValueError:
        return resp.text


def cmd_state(ctx: Ctx):
    for obj, title in (("zhuge_gate_state.json", "電閘 / 趨勢狀態"), ("pyramid_state.json", "加單基準"),
                       ("gate_switches.json", "關卡開關"), ("order_params.json", "送單參數")):
        data = gcs_get(ctx, obj)
        print(f"\n=== {title}（gs://{ctx.bucket}/{obj}）===")
        if data is None:
            print("（不存在）")
            continue
        if isinstance(data, dict):
            data = {k: (mask(k, v) if isinstance(v, str) else v) for k, v in data.items()}
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    log = gcs_get(ctx, "gcp_decision_log.json")
    print(f"\n=== 決策日誌（最後 {ctx.args.tail} 筆）===")
    if isinstance(log, list):
        for item in log[-ctx.args.tail:]:
            print(json.dumps(item, ensure_ascii=False)[:600])
    elif log is None:
        print("（不存在）")
    else:
        print(json.dumps(log, ensure_ascii=False)[:4000])


def cmd_bucket(ctx: Ctx):
    params = {"maxResults": 200, "fields": "items(name,size,updated),nextPageToken"}
    if ctx.args.prefix:
        params["prefix"] = ctx.args.prefix
    data = ctx.call("GET", f"{GCS_API}/b/{ctx.bucket}/o", params=params)
    items = data.get("items", [])
    for it in sorted(items, key=lambda x: x["name"]):
        print(f"{hk_time(it['updated'])}  {int(it['size']):>9}  {it['name']}")
    print(f"—— {len(items)} 個物件{'（尚有更多，請用 --prefix 縮小）' if data.get('nextPageToken') else ''} ——")


def cmd_cat(ctx: Ctx):
    data = gcs_get(ctx, ctx.args.object, as_json=False)
    if data is None:
        die(f"gs://{ctx.bucket}/{ctx.args.object} 不存在")
    text = data.decode("utf-8", errors="replace")
    print(text if not ctx.args.bytes else text[: ctx.args.bytes])


def cmd_check(ctx: Ctx):
    url = ctx.args.url
    if not url:
        fn = get_function(ctx)
        if not fn:
            die("函式不存在，無法檢查。")
        url = fn.get("serviceConfig", {}).get("uri") or fn.get("url")
    print(f"檢查 {url}")
    ok = True
    for view in ("", "gates_app", "order_app", "dashboard", "info"):
        target = url if not view else f"{url}?view={view}"
        try:
            r = requests.get(target, timeout=30)
            good = r.status_code == 200 and len(r.text) > 200
            ok &= good
            print(f"  {'✅' if good else '❌'} {view or '(首頁)':<10} HTTP {r.status_code}  {len(r.text)} bytes")
        except requests.RequestException as exc:
            ok = False
            print(f"  ❌ {view or '(首頁)':<10} {exc}")
    sys.exit(0 if ok else 1)


# ---- env --------------------------------------------------------------------
def parse_kv(items):
    out = {}
    for item in items:
        if "=" not in item:
            die(f"環境變數格式必須是 KEY=VALUE：{item}")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def patch_function(ctx: Ctx, body, update_mask):
    op = ctx.call("PATCH", f"{CF_API}/{ctx.fn_name}", params={"updateMask": update_mask}, json=body)
    return wait_operation(ctx, op)


def wait_operation(ctx: Ctx, op, poll=6, max_wait=900):
    name = op["name"]
    started = time.time()
    while not op.get("done"):
        if time.time() - started > max_wait:
            die(f"操作逾時（{max_wait}s）：{name}")
        time.sleep(poll)
        op = ctx.call("GET", f"{CF_API}/{name}")
        stages = (op.get("metadata") or {}).get("stages") or []
        cur = next((s for s in stages if s.get("state") == "IN_PROGRESS"), None)
        print(f"   ⏳ {int(time.time() - started):>4}s {cur.get('name') if cur else '…'}", flush=True)
    if "error" in op:
        die(f"操作失敗：{json.dumps(op['error'], ensure_ascii=False)}")
    return op.get("response", {})


def cmd_env(ctx: Ctx):
    a = ctx.args
    fn = get_function(ctx)
    if not fn:
        die("函式不存在。")
    env = dict(fn.get("serviceConfig", {}).get("environmentVariables", {}))
    if a.env_action == "get":
        for k in sorted(env):
            print(f"{k}={mask(k, env[k])}")
        return
    changes = parse_kv(a.pairs) if a.env_action == "set" else {}
    removals = a.pairs if a.env_action == "unset" else []
    new_env = dict(env)
    new_env.update(changes)
    for k in removals:
        new_env.pop(k, None)
    if new_env == env:
        print("沒有變更。")
        return
    for k in sorted(set(env) | set(new_env)):
        if k not in env:
            plan(f"新增 {k}={mask(k, new_env[k])}")
        elif k not in new_env:
            plan(f"移除 {k}")
        elif env[k] != new_env[k]:
            plan(f"修改 {k}: {mask(k, env[k])} → {mask(k, new_env[k])}")
    if not a.yes:
        print("（dry-run；加 --yes 才會套用並重新部署）")
        return
    print("🚀 套用環境變數（函式會重新部署一個修訂）…")
    res = patch_function(ctx, {"serviceConfig": {"environmentVariables": new_env}}, "serviceConfig.environmentVariables")
    print(f"✅ 完成，狀態 {res.get('state')}，修訂 {res.get('serviceConfig', {}).get('revision')}")


# ---- deploy -------------------------------------------------------------------
def build_zip(source_dir: Path):
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in DEPLOY_FILES:
            p = source_dir / name
            if not p.exists():
                die(f"缺少部署檔案：{p}")
            data = p.read_bytes()
            manifest.append((name, len(data), hashlib.sha256(data).hexdigest()[:12]))
            zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))  # 可重現
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, data)
    return buf.getvalue(), manifest


def sanity_check_sources(source_dir: Path):
    problems = []
    main_py = (source_dir / "main.py").read_text(encoding="utf-8", errors="replace")
    if f"def {ENTRY_POINT}(" not in main_py:
        problems.append(f"main.py 找不到 def {ENTRY_POINT}(")
    if not main_py.rstrip().endswith("return response"):
        problems.append("main.py 結尾不是 `return response`（檔案可能貼到一半）")
    for html_name in ("gates.html", "order.html"):
        text = (source_dir / html_name).read_text(encoding="utf-8", errors="replace")
        if not text.lstrip().lower().startswith("<!doctype html>") or not text.rstrip().lower().endswith("</html>"):
            problems.append(f"{html_name} 頭尾不完整")
    req = (source_dir / "requirements.txt").read_text(encoding="utf-8", errors="replace")
    if "functions-framework" not in req:
        problems.append("requirements.txt 缺少 functions-framework")
    try:
        compile(main_py, "main.py", "exec")
    except SyntaxError as exc:
        problems.append(f"main.py 語法錯誤：{exc}")
    return problems


def cmd_deploy(ctx: Ctx):
    a = ctx.args
    source_dir = Path(a.source).resolve()
    problems = sanity_check_sources(source_dir)
    zip_bytes, manifest = build_zip(source_dir)
    print(f"📦 部署套件（{len(zip_bytes)} bytes）：")
    for name, size, digest in manifest:
        print(f"   {name:<18} {size:>8} bytes  sha256 {digest}")
    if problems:
        for p in problems:
            print(f"❌ {p}")
        die("來源檔案檢查未通過，停止部署。")
    print("✅ 來源檔案檢查通過")

    env_changes = parse_kv(a.set_env) if a.set_env else {}
    fn = get_function(ctx, quiet=True)
    creating = fn is None
    plan(f"{'建立' if creating else '更新'} {ctx.fn_name}")
    plan(f"runtime={a.runtime} entry={ENTRY_POINT} memory={a.memory} timeout={a.timeout}s")
    if env_changes:
        for k, v in env_changes.items():
            plan(f"環境變數 {k}={mask(k, v)}")
    if creating:
        plan("建立後設定 allUsers → roles/run.invoker（允許未經驗證的叫用）")
    if not a.yes:
        print("（dry-run；確認無誤後加 --yes 才會真的部署。此系統會對真實帳戶送單，請先確認 main.py 是預期版本。）")
        return

    print("⬆️  取得上傳網址…")
    up = ctx.call("POST", f"{CF_API}/{ctx.fn_parent}/functions:generateUploadUrl", json={})
    r = requests.put(up["uploadUrl"], data=zip_bytes, headers={"content-type": "application/zip"}, timeout=120)
    if r.status_code not in (200, 201):
        die(f"上傳失敗 HTTP {r.status_code}: {r.text[:300]}")
    print("✅ 已上傳原始碼")

    existing_env = dict((fn or {}).get("serviceConfig", {}).get("environmentVariables", {}))
    existing_env.update(env_changes)
    body = {
        "buildConfig": {"runtime": a.runtime, "entryPoint": ENTRY_POINT, "source": {"storageSource": up["storageSource"]}},
        "serviceConfig": {
            "availableMemory": a.memory,
            "timeoutSeconds": a.timeout,
            "environmentVariables": existing_env,
            "ingressSettings": "ALLOW_ALL",
        },
    }
    if creating:
        print("🚀 建立函式（約 2–5 分鐘）…")
        op = ctx.call("POST", f"{CF_API}/{ctx.fn_parent}/functions", params={"functionId": ctx.function}, json=body)
    else:
        print("🚀 更新函式（約 2–5 分鐘）…")
        mask_fields = ("buildConfig.runtime,buildConfig.entryPoint,buildConfig.source,"
                       "serviceConfig.availableMemory,serviceConfig.timeoutSeconds,"
                       "serviceConfig.environmentVariables,serviceConfig.ingressSettings")
        op = ctx.call("PATCH", f"{CF_API}/{ctx.fn_name}", params={"updateMask": mask_fields}, json=body)
    res = wait_operation(ctx, op)
    url = res.get("serviceConfig", {}).get("uri") or res.get("url")
    print(f"✅ 部署完成：狀態 {res.get('state')}\n   網址：{url}")
    if creating:
        make_public(ctx, res)
    if not a.no_check:
        ctx.args.url = url
        cmd_check(ctx)


def make_public(ctx: Ctx, fn=None):
    fn = fn or get_function(ctx)
    if not fn:
        die("函式不存在。")
    service = fn.get("serviceConfig", {}).get("service")
    if not service:
        die("找不到對應的 Cloud Run 服務名稱。")
    policy = ctx.call("GET", f"{RUN_API}/{service}:getIamPolicy")
    bindings = policy.get("bindings", [])
    inv = next((b for b in bindings if b.get("role") == "roles/run.invoker"), None)
    if inv and "allUsers" in inv.get("members", []):
        print("ℹ️ 已允許未經驗證的叫用。")
        return
    if inv:
        inv.setdefault("members", []).append("allUsers")
    else:
        bindings.append({"role": "roles/run.invoker", "members": ["allUsers"]})
    policy["bindings"] = bindings
    ctx.call("POST", f"{RUN_API}/{service}:setIamPolicy", json={"policy": policy})
    print("✅ 已設定 allUsers → roles/run.invoker")


def cmd_iam_public(ctx: Ctx):
    if not ctx.args.yes:
        plan("將 allUsers 加入 roles/run.invoker（EA 與網頁才能直接打函式）。加 --yes 執行。")
        return
    make_public(ctx)


# =============================================================================
# CLI
# =============================================================================
def build_parser():
    p = argparse.ArgumentParser(prog="gcp_agent.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", help="GCP 專案 ID（預設取金鑰的 project_id 或 $GCP_PROJECT）")
    p.add_argument("--region", help="區域（預設 $GCP_REGION 或 asia-east1）")
    p.add_argument("--function", help="函式名稱（預設 receive_tradingview_signal）")
    p.add_argument("--bucket", help="狀態 bucket（預設 zhuge-risk-manager-bucket）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="驗證憑證與專案")
    sub.add_parser("status", help="函式狀態")

    s = sub.add_parser("logs", help="讀 Cloud Logging")
    s.add_argument("--since", default="2h")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--grep", help="textPayload 包含的字串，例如 已送出")
    s.add_argument("--severity", help="最低嚴重度，例如 WARNING")

    s = sub.add_parser("state", help="讀 GCS 狀態")
    s.add_argument("--tail", type=int, default=10)

    s = sub.add_parser("bucket", help="列出 bucket 物件")
    s.add_argument("--prefix", default="")

    s = sub.add_parser("cat", help="印出 bucket 物件")
    s.add_argument("--object", required=True)
    s.add_argument("--bytes", type=int, default=0, help="只印前 N 個字元")

    s = sub.add_parser("check", help="檢查五個頁面")
    s.add_argument("--url", help="函式網址（省略則從 status 取）")

    s = sub.add_parser("env", help="環境變數")
    s.add_argument("env_action", choices=["get", "set", "unset"])
    s.add_argument("pairs", nargs="*", help="set: KEY=VAL…；unset: KEY…")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("deploy", help="部署（預設 dry-run）")
    s.add_argument("--source", default=str(REPO_ROOT))
    s.add_argument("--runtime", default=DEFAULT_RUNTIME)
    s.add_argument("--memory", default=DEFAULT_MEMORY)
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    s.add_argument("--set-env", nargs="*", metavar="KEY=VAL")
    s.add_argument("--no-check", action="store_true", help="部署後不打頁面檢查")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("iam-public", help="允許未經驗證的叫用")
    s.add_argument("--yes", action="store_true")
    return p


COMMANDS = {
    "whoami": cmd_whoami, "status": cmd_status, "logs": cmd_logs, "state": cmd_state, "bucket": cmd_bucket,
    "cat": cmd_cat, "check": cmd_check, "env": cmd_env, "deploy": cmd_deploy, "iam-public": cmd_iam_public,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    ctx = Ctx(args)
    # deploy 的 dry-run 若沒有憑證也要能跑（純檢查套件）
    if args.cmd == "deploy" and not args.yes:
        try:
            ctx.session
        except SystemExit:
            print("⚠️ 沒有 GCP 憑證，只做本機套件檢查。")
            problems = sanity_check_sources(Path(args.source).resolve())
            zip_bytes, manifest = build_zip(Path(args.source).resolve())
            print(f"📦 部署套件（{len(zip_bytes)} bytes）：")
            for name, size, digest in manifest:
                print(f"   {name:<18} {size:>8} bytes  sha256 {digest}")
            for pr in problems:
                print(f"❌ {pr}")
            sys.exit(1 if problems else 0)
    COMMANDS[args.cmd](ctx)


if __name__ == "__main__":
    main()
