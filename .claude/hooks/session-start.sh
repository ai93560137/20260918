#!/bin/bash
# SessionStart hook — 只在 Claude Code on the web（雲端容器）執行。
# 1) 安裝 scripts/gcp_agent.py 與本專案需要的 Python 套件
# 2) 若環境變數 GCP_SA_KEY 存在，寫成金鑰檔並匯出 GOOGLE_APPLICATION_CREDENTIALS / GCP_PROJECT
# 3) 盡量安裝 gcloud CLI（網路政策不允許時略過；gcp_agent.py 不依賴 gcloud）
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
ENV_FILE="${CLAUDE_ENV_FILE:-/dev/null}"
log() { echo "[session-start] $*"; }

# ---- 1. Python 套件 ---------------------------------------------------------
# 系統內建的 cryptography 缺 cffi backend，會讓 google-auth 匯入時 panic；裝到 --user 蓋掉它。
pip_install() {  # $1 = requirements 檔；只印非 root 警告的輸出，回傳 pip 的結束碼
  local out rc
  out="$(pip3 install -q --user -r "$1" 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -v -i "warning: running pip as the 'root'" | grep -v '^$' || true
  return $rc
}
pip_install "$ROOT/scripts/requirements-agent.txt" && log "✅ gcp_agent.py 套件就位" || log "⚠️ requirements-agent.txt 安裝有錯誤（見上方輸出）"
pip_install "$ROOT/requirements.txt" || log "⚠️ requirements.txt 安裝有錯誤（不影響 gcp_agent.py）"

# ---- 2. GCP 憑證 ------------------------------------------------------------
if [ -n "${GCP_SA_KEY:-}" ]; then
  CRED_DIR="$HOME/.config/gcp-claude"
  mkdir -p "$CRED_DIR" && chmod 700 "$CRED_DIR"
  CRED_FILE="$CRED_DIR/sa.json"
  if printf '%s' "$GCP_SA_KEY" | grep -q '^{'; then
    printf '%s' "$GCP_SA_KEY" > "$CRED_FILE"
  else
    printf '%s' "$GCP_SA_KEY" | base64 -d > "$CRED_FILE" 2>/dev/null || printf '%s' "$GCP_SA_KEY" > "$CRED_FILE"
  fi
  chmod 600 "$CRED_FILE"
  PROJECT_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("project_id",""))' "$CRED_FILE" 2>/dev/null || true)"
  {
    echo "export GOOGLE_APPLICATION_CREDENTIALS=\"$CRED_FILE\""
    echo "export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=\"$CRED_FILE\""
    [ -n "$PROJECT_ID" ] && [ -z "${GCP_PROJECT:-}" ] && echo "export GCP_PROJECT=\"$PROJECT_ID\""
    [ -n "$PROJECT_ID" ] && echo "export CLOUDSDK_CORE_PROJECT=\"${GCP_PROJECT:-$PROJECT_ID}\""
    echo "export GCP_REGION=\"${GCP_REGION:-asia-east1}\""
  } >> "$ENV_FILE"
  log "✅ GCP 服務帳戶金鑰已就位（專案：${PROJECT_ID:-未知}）"
else
  log "ℹ️ 未設定 GCP_SA_KEY：gcp_agent.py 只能做本機檢查。請在雲端環境設定加入 GCP_SA_KEY（見 AGENTIC.md）。"
fi

# ---- 3. gcloud（可選） --------------------------------------------------------
if ! command -v gcloud >/dev/null 2>&1; then
  if curl -sS -m 8 -o /dev/null https://dl.google.com/dl/cloudsdk/channels/rapid/components-2.json 2>/dev/null; then
    log "安裝 gcloud CLI…"
    if curl -sS -m 120 https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz -o /tmp/gcloud.tgz \
       && mkdir -p "$HOME/.local" && tar -xzf /tmp/gcloud.tgz -C "$HOME/.local" 2>/dev/null; then
      echo "export PATH=\"$HOME/.local/google-cloud-sdk/bin:\$PATH\"" >> "$ENV_FILE"
      log "✅ gcloud 已安裝到 ~/.local/google-cloud-sdk"
    else
      log "⚠️ gcloud 下載/解壓失敗，略過（gcp_agent.py 不需要它）"
    fi
    rm -f /tmp/gcloud.tgz
  else
    log "ℹ️ 網路政策不允許 dl.google.com，略過 gcloud 安裝（gcp_agent.py 不需要它）"
  fi
fi

log "完成"
exit 0
