#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gcp_agent.py — 讓 Claude（或任何人）不用 gcloud 也能操作本專案的 GCP 資源。

只靠 REST API + 服務帳戶金鑰，因此在沒有 gcloud 的 Claude Code 雲端容器裡也能跑。

認證來源（依序）：
  1. 環境變數 GCP_SA_KEY        — 服務帳戶金鑰 JSON 的「內容」（可直接貼 JSON 或 base64）
  2. 環境變數 GOOGLE_APPLICATION_CREDENTIALS — 金鑰檔路徑
  3. Application Default Credentials（本機 gcloud auth application-default login / Cloud Shell）

操作對象（--target 或 GCP_TARGET）：
  run           （預設）Cloud Run 服務 zhuge-risk-manager（europe-west1）— 目前實際在跑的系統
  function      Cloud Functions 第 2 代 receive_tradingview_signal（舊部署方式）

專案 / 區域 / 名稱：
  GCP_PROJECT     （預設取金鑰檔的 project_id）
  GCP_RUN_REGION  run 模式的區域（預設 europe-west1）
  GCP_SERVICE     run 模式的服務名稱（預設 zhuge-risk-manager）
  GCP_REGION      function 模式的區域（預設 asia-east1；香港可用 asia-east2）
  GCP_FUNCTION    function 模式的函式名稱（預設 receive_tradingview_signal）
  GCP_BUCKET      （預設 zhuge-risk-manager-bucket）
  --region 會覆蓋目前模式的區域。

子命令：
  whoami        驗證憑證，列出專案、服務帳戶、已啟用 API
  status        服務 / 函式狀態、網址、執行階段設定、環境變數（值會遮罩）
  logs          讀 Cloud Logging（--since 2h --limit 100 --grep 已送出）
  state         讀 GCS 上的電閘 / 加單 / 決策日誌
  bucket        列出 bucket 物件（--prefix）
  cat           印出 bucket 內任一物件（--object path）
  check         打函式網址的五個頁面，確認都回 200
  env           顯示或修改環境變數（env set KEY=VAL ... --yes）
  deploy        打包部署檔案（main.py、requirements.txt 與各 HTML）並部署（預設 dry-run；真的部署要加 --yes）
  iam-public    讓函式允許未經驗證的叫用（allUsers → roles/run.invoker）

所有會改動 GCP 的命令都需要 --yes；沒有 --yes 只會印出「將會做什麼」。
run 模式（Cloud Run 服務）：
  env set/unset 建立新修訂（沿用目前映像），先 validateOnly 驗證再套用
  revisions     列出修訂、建立時間、映像、流量
  rollback      把 100% 流量切回舊修訂（不建新修訂、不刪任何東西）
  deploy        上傳 zip → Cloud Build（buildpacks，沿用服務的 buildConfig）→ 換新映像建立新修訂
                dry-run 會列出計畫與缺少的權限；--local-only 只做本機來源檢查
  iam-public    run 模式不提供
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
DEPLOY_FILES = ("main.py", "requirements.txt", "gates.html", "order.html",
                "jinnang_sheet.html", "jinnang_tracker.html")
ENTRY_POINT = "receive_tradingview_signal"
DEFAULT_RUNTIME = "python312"
DEFAULT_MEMORY = "512Mi"
DEFAULT_TIMEOUT = 60
DEFAULT_TARGET = "run"
DEFAULT_RUN_REGION = "europe-west1"
DEFAULT_SERVICE = "zhuge-risk-manager"
DEFAULT_FN_REGION = "asia-east1"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
HK_TZ = timezone(timedelta(hours=8))

CF_API = "https://cloudfunctions.googleapis.com/v2"
RUN_API = "https://run.googleapis.com/v2"
LOG_API = "https://logging.googleapis.com/v2"
GCS_API = "https://storage.googleapis.com/storage/v1"
SU_API = "https://serviceusage.googleapis.com/v1"
CB_API = "https://cloudbuild.googleapis.com/v1"
CRM_API = "https://cloudresourcemanager.googleapis.com/v1"
GCS_UPLOAD_API = "https://storage.googleapis.com/upload/storage/v1"

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
        self.target = (getattr(args, "target", None) or os.environ.get("GCP_TARGET") or DEFAULT_TARGET).strip().lower()
        if self.target not in ("run", "function"):
            die(f"--target / GCP_TARGET 只能是 run 或 function：{self.target}")
        if self.target == "run":
            self.region = os.environ.get("GCP_RUN_REGION", DEFAULT_RUN_REGION).strip()
        else:
            self.region = os.environ.get("GCP_REGION", DEFAULT_FN_REGION).strip()
        self.function = os.environ.get("GCP_FUNCTION", ENTRY_POINT).strip()
        self.service = os.environ.get("GCP_SERVICE", DEFAULT_SERVICE).strip()
        self.bucket = os.environ.get("GCP_BUCKET", "zhuge-risk-manager-bucket").strip()
        if getattr(args, "region", None):
            self.region = args.region
        if getattr(args, "function", None):
            self.function = args.function
        if getattr(args, "service", None):
            self.service = args.service
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

    @property
    def svc_name(self):
        return f"{self.fn_parent}/services/{self.service}"

    @property
    def is_run(self):
        return self.target == "run"


def die(msg, code=1):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


URL_QUERY_VALUE = re.compile(r"([?&][^=&#\s]+=)[^&#\s]+")


def mask(key, value):
    if SECRET_ENV_PATTERN.search(key) and value:
        return value[:2] + "…" + value[-2:] if len(value) > 6 else "••••"
    if isinstance(value, str) and "://" in value:
        # 網址的查詢參數常夾帶權杖（例如 BROKER_API_URL 的 ?t=…），一律遮罩
        return URL_QUERY_VALUE.sub(r"\1••••", value)
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
    what = f"Cloud Run 服務：{ctx.service}" if ctx.is_run else f"Cloud Function：{ctx.function}"
    print(f"✅ 憑證可用\n   帳戶：{ctx.account}\n   專案：{ctx.project}\n   模式：{ctx.target}（{what}）\n"
          f"   區域：{ctx.region}\n   Bucket：{ctx.bucket}")
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


def get_service(ctx: Ctx, quiet=False):
    resp = ctx.session.get(f"{RUN_API}/{ctx.svc_name}", timeout=60)
    if resp.status_code == 404:
        if not quiet:
            print(f"ℹ️ Cloud Run 服務 {ctx.svc_name} 不存在。")
        return None
    if resp.status_code != 200:
        die(f"讀取 Cloud Run 服務失敗 HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def service_url(svc):
    urls = svc.get("urls") or []
    return urls[0] if urls else svc.get("uri")


def run_env(svc):
    """Cloud Run 容器環境變數 → {name: 顯示用字串}；Secret Manager 參照只顯示來源。"""
    containers = (svc.get("template") or {}).get("containers") or [{}]
    out = {}
    for e in containers[0].get("env", []):
        ref = (e.get("valueSource") or {}).get("secretKeyRef")
        if ref:
            out[e["name"]] = f"<secret {ref.get('secret')}:{ref.get('version', 'latest')}>"
        else:
            out[e["name"]] = mask(e["name"], e.get("value", ""))
    return out


def cmd_status_run(ctx: Ctx):
    svc = get_service(ctx)
    if not svc:
        return
    tpl = svc.get("template") or {}
    c = (tpl.get("containers") or [{}])[0]
    limits = (c.get("resources") or {}).get("limits") or {}
    scaling = tpl.get("scaling") or {}
    term = svc.get("terminalCondition") or {}
    ready = term.get("state") == "CONDITION_SUCCEEDED"
    print(f"服務：{svc['name']}")
    print(f"狀態：{'✅ Ready' if ready else '❌ ' + str(term.get('state'))}  更新：{hk_time(svc.get('updateTime', ''))} (HK)"
          f"  最後修改者：{svc.get('lastModifier')}")
    if not ready and term.get("message"):
        print(f"⚠️ {term['message'][:500]}")
    for u in svc.get("urls") or [svc.get("uri")]:
        print(f"網址：{u}")
    print(f"修訂：{(svc.get('latestReadyRevision') or '').rsplit('/', 1)[-1] or '（無）'}  Ingress：{svc.get('ingress')}")
    print(f"映像：{c.get('image')}")
    print(f"CPU：{limits.get('cpu')}  記憶體：{limits.get('memory')}  逾時：{tpl.get('timeout')}"
          f"  執行個體：{scaling.get('minInstanceCount', 0)}–{scaling.get('maxInstanceCount', '?')}"
          f"  服務帳戶：{tpl.get('serviceAccount')}")
    for t in svc.get("trafficStatuses") or []:
        print(f"流量：{t.get('percent', 0)}% → {t.get('revision') or t.get('type')}")
    env = run_env(svc)
    print(f"環境變數（{len(env)}）：")
    for k in sorted(env):
        print(f"   {k}={env[k]}")


def cmd_status(ctx: Ctx):
    if ctx.is_run:
        return cmd_status_run(ctx)
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
    if ctx.is_run:
        flt = (
            f'resource.type="cloud_run_revision" AND resource.labels.service_name="{ctx.service}" '
            f'AND resource.labels.location="{ctx.region}" AND timestamp>="{since.isoformat()}"'
        )
    else:
        service = ctx.function.replace("_", "-")
        flt = (
            f'((resource.type="cloud_run_revision" AND resource.labels.service_name="{service}") '
            f'OR (resource.type="cloud_function" AND resource.labels.function_name="{ctx.function}")) '
            f'AND timestamp>="{since.isoformat()}"'
        )
    if a.severity:
        flt += f" AND severity>={a.severity.upper()}"
    if a.grep:
        # 結構化日誌的訊息在 jsonPayload.message，純文字在 textPayload
        flt += f' AND (textPayload:"{a.grep}" OR jsonPayload.message:"{a.grep}")'
    body = {"resourceNames": [f"projects/{ctx.project}"], "filter": flt, "orderBy": "timestamp desc", "pageSize": min(a.limit, 1000)}
    data = ctx.call("POST", f"{LOG_API}/entries:list", json=body)
    entries = data.get("entries", [])
    if not entries:
        print(f"（過去 {a.since} 沒有日誌）")
        return
    for e in reversed(entries):
        payload = e.get("textPayload")
        if payload is None and e.get("jsonPayload") is not None:
            jp = e["jsonPayload"]
            payload = jp.get("message") or json.dumps(jp, ensure_ascii=False)
        elif payload is None and e.get("httpRequest"):
            hr = e["httpRequest"]
            payload = f"[HTTP] {hr.get('requestMethod')} {hr.get('status')} {hr.get('latency', '')} {hr.get('requestUrl', '')}"
        elif payload is None:
            payload = ""
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
    if not url and ctx.is_run:
        svc = get_service(ctx)
        if not svc:
            die("Cloud Run 服務不存在，無法檢查。")
        url = service_url(svc)
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


# ---- Cloud Run 寫入（env set/unset、rollback、deploy） ------------------------------
LATEST_TRAFFIC = [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100}]


def short_rev(name):
    return (name or "").rsplit("/", 1)[-1]


def short_image(image):
    image = image or ""
    if "@sha256:" in image:
        return "sha256:" + image.split("@sha256:", 1)[1][:12]
    return image.rsplit("/", 1)[-1]


def traffic_map(svc):
    """{修訂短名: 百分比}，LATEST 類型換成目前的 latestReadyRevision。"""
    out = {}
    for t in svc.get("trafficStatuses") or []:
        rev = short_rev(t.get("revision"))
        if not rev and "LATEST" in (t.get("type") or ""):
            rev = short_rev(svc.get("latestReadyRevision"))
        if rev:
            out[rev] = out.get(rev, 0) + int(t.get("percent", 0) or 0)
    return out


def traffic_follows_latest(svc):
    return any("LATEST" in (t.get("type") or "") and int(t.get("percent", 0) or 0) == 100
               for t in svc.get("traffic") or [])


def wait_run_operation(ctx: Ctx, op, api=RUN_API, label="Cloud Run", poll=5, max_wait=1200):
    name = op["name"]
    started = time.time()
    while not op.get("done"):
        if time.time() - started > max_wait:
            die(f"操作逾時（{max_wait}s）：{name}")
        time.sleep(poll)
        op = ctx.call("GET", f"{api}/{name}")
        print(f"   ⏳ {int(time.time() - started):>4}s {label}…", flush=True)
    if "error" in op:
        die(f"操作失敗：{json.dumps(op['error'], ensure_ascii=False)[:1500]}")
    return op.get("response", {})


def update_service(ctx: Ctx, svc, what):
    """送出整個 Service（含 etag，避免蓋掉別人同時的修改）：先 validateOnly，再真的更新。"""
    body = json.loads(json.dumps(svc))
    (body.get("template") or {}).pop("revision", None)  # 指定修訂名稱會與既有修訂衝突
    url = f"{RUN_API}/{svc['name']}"
    ctx.call("PATCH", url, params={"validateOnly": "true"}, json=body)
    print("✅ GCP 伺服器端驗證通過（validateOnly，尚未改動）")
    print(f"🚀 {what}（約 1–3 分鐘）…")
    op = ctx.call("PATCH", url, json=body)
    wait_run_operation(ctx, op)
    return report_after_update(ctx, svc)


def report_after_update(ctx: Ctx, before):
    svc = get_service(ctx, quiet=True) or {}
    term = svc.get("terminalCondition") or {}
    ready = term.get("state") == "CONDITION_SUCCEEDED"
    old_rev = short_rev(before.get("latestReadyRevision"))
    new_rev = short_rev(svc.get("latestReadyRevision"))
    print(f"{'✅' if ready else '❌'} 服務狀態：{term.get('state')}  最新修訂：{new_rev}")
    if not ready and term.get("message"):
        print(f"⚠️ {term['message'][:500]}")
    print("   流量：" + ("、".join(f"{p}% → {r}" for r, p in traffic_map(svc).items()) or "（無）"))
    if old_rev and old_rev != new_rev:
        print(f"↩️  若有問題，退回上一版：python3 scripts/gcp_agent.py rollback --to {old_rev} --yes")
    return svc


def require_service(ctx: Ctx):
    svc = get_service(ctx)
    if not svc:
        die("Cloud Run 服務不存在。")
    return svc


def cmd_env_run(ctx: Ctx):
    a = ctx.args
    svc = require_service(ctx)
    if a.env_action == "get":
        env = run_env(svc)
        for k in sorted(env):
            print(f"{k}={env[k]}")
        return
    container = svc["template"]["containers"][0]
    env_list = container.get("env", [])
    changes = parse_kv(a.pairs) if a.env_action == "set" else {}
    removals = set(a.pairs) if a.env_action == "unset" else set()
    if not changes and not removals:
        die("請指定要修改的變數，例如：env set TARGET_RRR=2")
    existing = {e["name"] for e in env_list}
    new_list, changed = [], False
    for e in env_list:
        name = e["name"]
        if name in removals:
            plan(f"移除 {name}")
            changed = True
            continue
        if name in changes:
            if (e.get("valueSource") or {}).get("secretKeyRef"):
                die(f"{name} 是 Secret Manager 參照，請到 GCP 主控台修改，本工具不處理。")
            if e.get("value", "") != changes[name]:
                plan(f"修改 {name}: {mask(name, e.get('value', ''))} → {mask(name, changes[name])}")
                changed = True
            new_list.append({"name": name, "value": changes[name]})
        else:
            new_list.append(e)
    for name in changes:
        if name not in existing:
            plan(f"新增 {name}={mask(name, changes[name])}")
            new_list.append({"name": name, "value": changes[name]})
            changed = True
    for name in sorted(removals - existing):
        print(f"ℹ️ {name} 本來就不存在")
    if not changed:
        print("沒有變更。")
        return
    plan(f"以目前的程式碼映像（{short_image(container.get('image'))}）建立新修訂，100% 流量切到新修訂")
    if not traffic_follows_latest(svc):
        plan("⚠️ 目前流量不是跟著最新修訂（可能之前做過 rollback）；套用後流量會改回最新修訂")
    plan(f"目前修訂 {short_rev(svc.get('latestReadyRevision'))} 會保留，可隨時 rollback")
    if not a.yes:
        print("（dry-run；確認無誤後加 --yes 才會套用。此系統會對真實帳戶送單，改參數會立刻影響交易。）")
        return
    container["env"] = new_list
    svc["traffic"] = LATEST_TRAFFIC
    update_service(ctx, svc, "套用環境變數，建立新修訂")


def list_revisions(ctx: Ctx):
    data = ctx.call("GET", f"{RUN_API}/{ctx.svc_name}/revisions", params={"pageSize": 100})
    revs = data.get("revisions", [])
    return sorted(revs, key=lambda r: r.get("createTime", ""), reverse=True)


def revision_ready(rev):
    for c in rev.get("conditions") or []:
        if c.get("type") == "Ready":
            return c.get("state") == "CONDITION_SUCCEEDED"
    return None


def cmd_revisions(ctx: Ctx):
    if not ctx.is_run:
        die("revisions 只支援 run 模式。")
    svc = require_service(ctx)
    traffic = traffic_map(svc)
    revs = list_revisions(ctx)[: ctx.args.limit]
    print(f"{'修訂':<32} {'建立時間(HK)':<15} {'狀態':<4} {'流量':>5}  映像")
    for r in revs:
        name = short_rev(r["name"])
        ok = revision_ready(r)
        img = short_image(((r.get("containers") or [{}])[0]).get("image"))
        pct = traffic.get(name, 0)
        print(f"{name:<32} {hk_time(r.get('createTime', '')):<15} {'✅' if ok else ('❌' if ok is False else '？'):<4} {pct:>4}%  {img}")


def cmd_rollback(ctx: Ctx):
    if not ctx.is_run:
        die("rollback 只支援 run 模式。")
    a = ctx.args
    svc = require_service(ctx)
    revs = list_revisions(ctx)
    names = [short_rev(r["name"]) for r in revs]
    current = traffic_map(svc)
    if a.to:
        target = short_rev(a.to)
        if target not in names:
            die(f"找不到修訂 {target}。可用 `revisions` 列出。")
        rev = revs[names.index(target)]
    else:
        # 預設：目前服務中修訂之前、最近一個 Ready 的修訂
        serving = max(current, key=current.get) if current else short_rev(svc.get("latestReadyRevision"))
        idx = names.index(serving) + 1 if serving in names else 0
        rev = next((r for r in revs[idx:] if revision_ready(r)), None)
        if not rev:
            die("找不到可退回的舊修訂。")
        target = short_rev(rev["name"])
    if revision_ready(rev) is False:
        die(f"修訂 {target} 不是 Ready 狀態，不能把流量切過去。")
    if current == {target: 100}:
        print(f"ℹ️ 流量已經 100% 在 {target}。")
        return
    plan("目前流量：" + ("、".join(f"{p}% → {r}" for r, p in current.items()) or "（無）"))
    plan(f"改為 100% → {target}（建立於 {hk_time(rev.get('createTime', ''))} HK，映像 "
         f"{short_image(((rev.get('containers') or [{}])[0]).get('image'))}）")
    plan("不會建立新修訂，也不會刪除任何修訂；之後 env set / deploy 會把流量改回最新修訂")
    if not a.yes:
        print("（dry-run；確認無誤後加 --yes 才會切換流量。）")
        return
    svc["traffic"] = [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION", "revision": target, "percent": 100}]
    update_service(ctx, svc, f"流量切換到 {target}")


def cmd_env(ctx: Ctx):
    a = ctx.args
    if ctx.is_run:
        return cmd_env_run(ctx)
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
    tail = main_py.rstrip()
    if not (tail.endswith("app = _build_wsgi_app()") or tail.endswith("return response")):
        problems.append("main.py 結尾不是 `app = _build_wsgi_app()` 也不是 `return response`（檔案可能貼到一半）")
    for html_name in [n for n in DEPLOY_FILES if n.endswith(".html")]:
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


def git_revision(source_dir: Path):
    import subprocess

    try:
        head = subprocess.run(["git", "-C", str(source_dir), "log", "-1", "--format=%h %ci %s"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(source_dir), "status", "--porcelain", "--", *DEPLOY_FILES],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return head, bool(dirty)
    except Exception:  # noqa: BLE001
        return "", False


def run_sources_bucket(ctx: Ctx):
    return f"run-sources-{ctx.project}-{ctx.region}"


def missing_deploy_permissions(ctx: Ctx, svc):
    """用 testIamPermissions（唯讀）列出部署還缺哪些權限。"""
    missing = []
    r = ctx.session.post(f"{CRM_API}/projects/{ctx.project}:testIamPermissions",
                         json={"permissions": ["cloudbuild.builds.create", "cloudbuild.builds.get"]}, timeout=60)
    have = set((r.json() if r.status_code == 200 else {}).get("permissions", []))
    for perm in ("cloudbuild.builds.create", "cloudbuild.builds.get"):
        if perm not in have:
            missing.append(f"專案層級 {perm}（角色：Cloud Build 編輯者 roles/cloudbuild.builds.editor）")
    bucket = run_sources_bucket(ctx)
    r = ctx.session.get(f"{GCS_API}/b/{bucket}/iam/testPermissions",
                        params={"permissions": ["storage.objects.create"]}, timeout=60)
    if "storage.objects.create" not in (r.json() if r.status_code == 200 else {}).get("permissions", []):
        missing.append(f"bucket {bucket} 的 storage.objects.create（角色：Storage 物件建立者 roles/storage.objectCreator）")
    r = ctx.session.post(f"{RUN_API}/{svc['name']}:testIamPermissions",
                         json={"permissions": ["run.services.update"]}, timeout=60)
    if "run.services.update" not in (r.json() if r.status_code == 200 else {}).get("permissions", []):
        missing.append("服務的 run.services.update（角色：Cloud Run 開發人員 roles/run.developer）")
    return missing


def deploy_run(ctx: Ctx, source_dir: Path, zip_bytes):
    a = ctx.args
    svc = require_service(ctx)
    bc = dict(svc.get("buildConfig") or {})
    if not bc.get("functionTarget") and not bc.get("baseImage"):
        die("這個 Cloud Run 服務不是用原始碼部署的（沒有 buildConfig），本工具不處理。")
    container = svc["template"]["containers"][0]
    image_uri = (bc.get("imageUri") or container.get("image", "")).split("@", 1)[0]
    bucket = run_sources_bucket(ctx)
    head, dirty = git_revision(source_dir)
    print(f"📌 來源版本：{head or '（非 git）'}{'  ⚠️ 部署檔案有尚未 commit 的修改' if dirty else ''}")
    plan(f"上傳原始碼 zip 到 gs://{bucket}/services/{ctx.service}/<時間戳>.zip")
    plan(f"Cloud Build 建置（buildpacks，函式進入點 {bc.get('functionTarget')}，基底 {short_image(bc.get('baseImage'))}）→ {image_uri}")
    plan(f"更新服務 {ctx.svc_name}：換上新映像並建立新修訂，100% 流量切到新修訂")
    plan(f"環境變數保持不變（{len(container.get('env', []))} 個），目前修訂 {short_rev(svc.get('latestReadyRevision'))} 保留可 rollback")
    missing = missing_deploy_permissions(ctx, svc)
    if missing:
        print("⚠️ 服務帳戶還缺以下權限，現在加 --yes 會失敗：")
        for m in missing:
            print(f"   - {m}")
    if not a.yes:
        print("（dry-run；確認無誤後加 --yes 才會真的部署。此系統會對真實帳戶送單，請先確認 main.py 是預期版本。）")
        return
    if missing:
        die("權限不足，停止部署（沒有做任何改動）。")

    from urllib.parse import quote

    obj = f"services/{ctx.service}/{time.time():.6f}.zip"
    print("⬆️  上傳原始碼…")
    up = ctx.call("POST", f"{GCS_UPLOAD_API}/b/{bucket}/o", params={"uploadType": "media", "name": obj},
                  data=zip_bytes, headers={"Content-Type": "application/zip"})
    generation = up.get("generation")
    print(f"✅ 已上傳 gs://{bucket}/{obj}")
    build_req = {
        "storageSource": {"bucket": bucket, "object": obj, **({"generation": generation} if generation else {})},
        "imageUri": image_uri,
        "buildpackBuild": {k: v for k, v in {
            "baseImage": bc.get("baseImage"),
            "functionTarget": bc.get("functionTarget"),
            "enableAutomaticUpdates": bc.get("enableAutomaticUpdates"),
            "environmentVariables": bc.get("environmentVariables"),
        }.items() if v is not None},
    }
    if bc.get("serviceAccount"):
        build_req["serviceAccount"] = bc["serviceAccount"]
    print("🏗️  送出 Cloud Build（約 2–5 分鐘）…")
    sub = ctx.call("POST", f"{RUN_API}/{ctx.fn_parent}/builds:submit", json=build_req)
    if sub.get("baseImageWarning"):
        print(f"⚠️ {sub['baseImageWarning']}")
    build = wait_run_operation(ctx, sub["buildOperation"], api=CB_API, label="Cloud Build")
    if build.get("status") not in (None, "SUCCESS"):
        die(f"建置失敗：{build.get('status')} {build.get('statusDetail', '')}  日誌：{build.get('logUrl', '')}")
    digest = next((i.get("digest") for i in (build.get("results") or {}).get("images", [])
                   if i.get("name", "").split("@")[0] == image_uri and i.get("digest")), None)
    new_image = f"{image_uri}@{digest}" if digest else image_uri
    print(f"✅ 建置完成：{short_image(new_image)}")

    container["image"] = new_image
    bc.pop("name", None)  # output only：上一次建置的名稱
    bc["sourceLocation"] = f"gs://{bucket}/{quote(obj)}" + (f"#{generation}" if generation else "")
    svc["buildConfig"] = bc
    svc["traffic"] = LATEST_TRAFFIC
    after = update_service(ctx, svc, "換上新映像，建立新修訂")
    if not a.no_check:
        ctx.args.url = service_url(after)
        cmd_check(ctx)


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
    if ctx.is_run:
        if a.local_only:
            return
        return deploy_run(ctx, source_dir, zip_bytes)

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
    if ctx.is_run:
        die("run 模式不提供 iam-public：服務的叫用權限請到 GCP 主控台調整，本工具不會改動 IAM。")
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
    p.add_argument("--target", choices=["run", "function"],
                   help="操作對象：run = Cloud Run 服務（預設），function = Cloud Functions（或設 $GCP_TARGET）")
    p.add_argument("--region", help="區域（run 預設 $GCP_RUN_REGION 或 europe-west1；function 預設 $GCP_REGION 或 asia-east1）")
    p.add_argument("--service", help="Cloud Run 服務名稱（預設 $GCP_SERVICE 或 zhuge-risk-manager）")
    p.add_argument("--function", help="函式名稱（預設 receive_tradingview_signal）")
    p.add_argument("--bucket", help="狀態 bucket（預設 zhuge-risk-manager-bucket）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="驗證憑證與專案")
    sub.add_parser("status", help="服務 / 函式狀態")

    s = sub.add_parser("logs", help="讀 Cloud Logging")
    s.add_argument("--since", default="2h")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--grep", help="訊息包含的字串（textPayload 或 jsonPayload.message），例如 已送出")
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
    s.add_argument("--local-only", action="store_true", help="只做本機來源檢查，不連線 GCP")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("revisions", help="列出 Cloud Run 修訂與流量（run 模式）")
    s.add_argument("--limit", type=int, default=10)

    s = sub.add_parser("rollback", help="把流量切回舊修訂（預設 dry-run；run 模式）")
    s.add_argument("--to", help="目標修訂名稱（省略則選目前修訂之前最近一個 Ready 的）")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("iam-public", help="允許未經驗證的叫用")
    s.add_argument("--yes", action="store_true")
    return p


COMMANDS = {
    "whoami": cmd_whoami, "status": cmd_status, "logs": cmd_logs, "state": cmd_state, "bucket": cmd_bucket,
    "cat": cmd_cat, "check": cmd_check, "env": cmd_env, "deploy": cmd_deploy, "iam-public": cmd_iam_public,
    "revisions": cmd_revisions, "rollback": cmd_rollback,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    ctx = Ctx(args)
    # deploy 的 dry-run 若沒有憑證（或指定 --local-only）也要能跑：純檢查套件
    if args.cmd == "deploy" and not args.yes:
        try:
            if args.local_only:
                raise SystemExit
            ctx.session
        except SystemExit:
            print("ℹ️ 只做本機套件檢查（不連線 GCP）。" if args.local_only else "⚠️ 沒有 GCP 憑證，只做本機套件檢查。")
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
