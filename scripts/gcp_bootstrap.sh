#!/bin/bash
# =============================================================================
# gcp_bootstrap.sh — 一次性設定：讓 Claude 能在你的 GCP 專案執行任務
#
# 在 Google Cloud Shell（https://shell.cloud.google.com，香港帳戶可直接用）或
# 任何已 `gcloud auth login` 的機器上執行：
#
#   bash scripts/gcp_bootstrap.sh <PROJECT_ID> [REGION] [--github OWNER/REPO] [--no-key]
#
#   PROJECT_ID   你的 GCP 專案 ID（不是專案名稱）
#   REGION       Cloud Function 區域，預設 asia-east1（台灣）；香港可填 asia-east2
#   --github     另外建立 Workload Identity Federation，讓 GitHub Actions 不用金鑰也能部署
#   --no-key     不建立服務帳戶金鑰（只走 GitHub Actions 路線時用）
#
# 做的事：
#   1. 啟用需要的 API
#   2. 確認狀態 bucket 存在
#   3. 建立服務帳戶 claude-agent，授與「剛好夠用」的角色
#   4. 建立金鑰 → 印出要貼到 Claude 雲端環境的 GCP_SA_KEY（base64 一行）
#   5. （選）建立 GitHub Actions 用的 Workload Identity Pool / Provider
#
# 這支腳本只會「新增」，不會刪除或改動既有函式與資料；重複執行是安全的。
# =============================================================================
set -euo pipefail

PROJECT_ID="${1:-}"
[ -n "$PROJECT_ID" ] || { sed -n '2,20p' "$0"; exit 1; }
shift
REGION="asia-east1"
GITHUB_REPO=""
MAKE_KEY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --github) GITHUB_REPO="$2"; shift 2 ;;
    --no-key) MAKE_KEY=0; shift ;;
    *) REGION="$1"; shift ;;
  esac
done

SA_ID="claude-agent"
SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
BUCKET="${GCP_BUCKET:-zhuge-risk-manager-bucket}"

say() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

say "0/5 設定專案 $PROJECT_ID（區域 $REGION）"
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
echo "專案編號：$PROJECT_NUMBER"

say "1/5 啟用 API"
gcloud services enable \
  cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com storage.googleapis.com logging.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com aiplatform.googleapis.com

say "2/5 狀態 bucket gs://$BUCKET"
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "已存在"
else
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
fi

say "3/5 服務帳戶 $SA_EMAIL"
if gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  echo "已存在"
else
  gcloud iam service-accounts create "$SA_ID" --display-name="Claude agent (deploy / logs / state)"
fi

echo "授與專案層級角色…"
for ROLE in \
  roles/cloudfunctions.developer \
  roles/run.admin \
  roles/logging.viewer \
  roles/serviceusage.serviceUsageViewer \
  roles/artifactregistry.reader ; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$ROLE" --condition=None --quiet >/dev/null
  echo "  ✓ $ROLE"
done

echo "授與 bucket 層級角色（只限 gs://$BUCKET）…"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin --quiet >/dev/null
echo "  ✓ roles/storage.objectAdmin on gs://$BUCKET"

# 部署函式時，執行階段服務帳戶是預設的 Compute Engine SA；部署者需要能「以它的身分」部署。
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "允許 claude-agent 以執行階段服務帳戶 $RUNTIME_SA 部署…"
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/iam.serviceAccountUser --quiet >/dev/null
echo "  ✓ roles/iam.serviceAccountUser"

echo "確認執行階段服務帳戶本身有 bucket 與 Vertex AI 權限（DEPLOY.md 第 7 步）…"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectAdmin --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/aiplatform.user --condition=None --quiet >/dev/null
echo "  ✓ 完成"

if [ "$MAKE_KEY" = "1" ]; then
  say "4/5 建立金鑰"
  KEY_FILE="$HOME/claude-agent-${PROJECT_ID}.json"
  gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$SA_EMAIL" >/dev/null
  chmod 600 "$KEY_FILE"
  cat <<EOF

================================================================================
把下面這一行（整段 base64）貼到 Claude 雲端環境的環境變數，名稱 GCP_SA_KEY：
  claude.ai/code → 右上角環境選單 → Edit → Environment variables（或 API credentials）
    GCP_SA_KEY = <下面這一行>
    GCP_REGION = $REGION          （選填，預設 asia-east1）
    GCP_PROJECT = $PROJECT_ID     （選填，金鑰內已含 project_id）
儲存後，新的 Claude 工作階段就能執行 scripts/gcp_agent.py。
--------------------------------------------------------------------------------
EOF
  base64 -w0 "$KEY_FILE"
  cat <<EOF

--------------------------------------------------------------------------------
貼完請刪掉本機金鑰檔： rm "$KEY_FILE"
不要把金鑰 commit 進 git，也不要貼到聊天視窗。
要撤銷時： gcloud iam service-accounts keys list --iam-account=$SA_EMAIL
           gcloud iam service-accounts keys delete <KEY_ID> --iam-account=$SA_EMAIL
================================================================================
EOF
else
  say "4/5 略過金鑰（--no-key）"
fi

if [ -n "$GITHUB_REPO" ]; then
  say "5/5 GitHub Actions Workload Identity Federation（$GITHUB_REPO）"
  POOL="github-pool"
  PROVIDER="github"
  if ! gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1; then
    gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub Actions"
  fi
  if ! gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1; then
    gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
      --location=global --workload-identity-pool="$POOL" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
      --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
  fi
  POOL_NAME="$(gcloud iam workload-identity-pools describe "$POOL" --location=global --format='value(name)')"
  gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_REPO}" --quiet >/dev/null
  PROVIDER_NAME="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global --workload-identity-pool="$POOL" --format='value(name)')"
  cat <<EOF

在 GitHub repo → Settings → Secrets and variables → Actions 新增：
  GCP_WORKLOAD_IDENTITY_PROVIDER = $PROVIDER_NAME
  GCP_SERVICE_ACCOUNT            = $SA_EMAIL
之後 .github/workflows/gcp_deploy.yml 就能不靠金鑰部署。
EOF
else
  say "5/5 略過 GitHub Actions WIF（要的話加 --github OWNER/REPO）"
fi

say "完成。驗證：在 Claude 工作階段執行  python3 scripts/gcp_agent.py whoami"
