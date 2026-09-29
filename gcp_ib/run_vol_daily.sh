#!/usr/bin/env bash
# IBKR 波動率／利率日線每日匯出（跑在 GCP VM 的 crontab，不在沙盒）。2026-09-29
#
# 抓資料 → 提交到「專用資料分支」data/ibkr-vol（只含 data/vol，沒有程式碼，與程式分支分開）→ 推送。
# 資料放在獨立的資料 repo（預設 ~/ibkr-vol-data），不動 ~/20260918 這個程式 clone。
# 匯出程式是固定的一份複本 gcp_ib/ibkr_vol_export.py（來源：claude/us-intl-data-stock-market-vgt0yi 的
# scripts/ibkr_vol_export.py），不直接執行別的分支，避免別處的修改在有 IB 連線的機器上自動生效。
#
# 前置：IB Gateway 已登入常駐（埠 4002）、pip install ib_insync、程式 clone 的 git 推送設定可用
#       （與 run_daily.sh 相同，不需要新的憑證）。
# crontab 例（UTC，平日 22:30：CME 日線已結束、早於 Gateway 約 23:50 的每日重啟）：
#   30 22 * * 1-5 bash $HOME/20260918/gcp_ib/run_vol_daily.sh >> $HOME/ib_vol_daily.log 2>&1
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"                 # 程式所在 clone（~/20260918）
DATA="${IBKR_VOL_DATA_DIR:-$HOME/ibkr-vol-data}"          # 專用資料 repo
BRANCH="${IBKR_VOL_BRANCH:-data/ibkr-vol}"
PORT="${IB_PORT:-4002}"
EXPORT="${VOL_EXPORT_SCRIPT:-$REPO/gcp_ib/ibkr_vol_export.py}"
CODE_BRANCH="${CODE_BRANCH:-claude/dazzling-curie-f3xzb8}"

echo "== $(date -u '+%F %T') UTC  IBKR 波動率日線匯出 =="

# 1) 更新程式（失敗不擋資料抓取：例如程式 clone 有未提交的修改）
git -C "$REPO" pull --rebase -q origin "$CODE_BRANCH" 2>&1 || echo "⚠️ 程式更新失敗，沿用現有版本"

# 2) 準備資料 repo（第一次才建立）；提交身分與推送設定沿用程式 clone，不新增任何憑證
URL="$(git -C "$REPO" remote get-url origin)"
if [ ! -d "$DATA/.git" ]; then
  mkdir -p "$DATA"
  git -C "$DATA" init -q
  git -C "$DATA" remote add origin "$URL"
fi
cd "$DATA"
git config user.name  "$(git -C "$REPO" config user.name  2>/dev/null || echo ib-data)"
git config user.email "$(git -C "$REPO" config user.email 2>/dev/null || echo ib-data@localhost)"
# （沒有設定時 git config 會回傳失敗；set -e／pipefail 下要吞掉，否則腳本會悄悄中止）
{ git -C "$REPO" config --local --get-all credential.helper 2>/dev/null || true; } | while IFS= read -r h; do
  git config --local --add credential.helper "$h"
done

# 3) 切到資料分支：遠端已有就接上去；第一次則建立沒有歷史的獨立分支
git reset -q --hard 2>/dev/null || true
if git fetch -q origin "$BRANCH" 2>/dev/null; then
  git checkout -q -B "$BRANCH" FETCH_HEAD
else
  git symbolic-ref HEAD "refs/heads/$BRANCH"
  echo "（第一次執行：建立資料分支 $BRANCH，會下載完整歷史）"
fi

# 4) 匯出（增量：已有 CSV 只補最近幾天；只讀 IB，不下單）
#    一次性回補：VOL_EXPORT_ARGS="--backfill --only tlt qqq spy gld" bash run_vol_daily.sh
mkdir -p data/vol
if ! IB_PORT="$PORT" python3 "$EXPORT" --out data/vol ${VOL_EXPORT_ARGS:-}; then
  echo "❌ 匯出沒有任何資料（多半是 IB Gateway 沒登入），本次不提交"
  exit 1
fi

# 5) 提交並推送（沒有變動就略過）
git add data/vol
if git diff --cached --quiet; then
  echo "沒有新資料，略過"
  exit 0
fi
git commit -q -m "data(vol): IBKR 波動率／利率日線 $(date -u +%F)（VM 自動）"
git push -q origin "$BRANCH"
echo "✅ 已推送 $BRANCH：$(git rev-parse --short HEAD)"
