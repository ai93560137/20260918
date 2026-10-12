#!/usr/bin/env bash
# 外匯分支委託的兩個報價快照 CSV 每週推回雲垂分支（跑在 GCP VM 的 crontab，不在沙盒）。2026-10-12
#   data_forex_ibkr/l1_quotes.csv     ← scripts/ib_l1_quote.py（平日 08:59／11:59 UTC，EURUSD IDEALPRO bid/ask）
#   data_forex_ibkr/vrp_snapshots.csv ← scripts/ib_fx_option_snapshot.py（平日 14:00 UTC，6E 近月 ATM 跨式）
# 兩檔各自一個 commit，訊息固定（外匯分支按訊息找）：data(ibkr): L1 報價快照 ／ data(ibkr): 6E 期權快照。
# 只動這兩個檔；log 不進 git。沒有變動就略過。隨時可手動跑。
# crontab 例（UTC，每週六 02:10；見 data_forex_ibkr/_l1_vrp_install_status.txt）：
#   10 2 * * 6  bash $HOME/20260918/gcp_ib/push_fx_quotes.sh >> $HOME/ib_fx_push.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${CODE_BRANCH:-claude/dazzling-curie-f3xzb8}"
echo "== $(date -u '+%F %T') UTC  推送外匯報價快照 =="
# 這兩個 CSV 被 cron 每天追加，工作樹會「髒」；rebase.autostash 讓 pull --rebase 照樣能走（安裝時已設定，這裡再保險一次）
git config rebase.autostash true
git pull --rebase -q origin "$BRANCH" || echo "⚠️ pull 失敗，仍嘗試提交本地新資料"
push_one() {   # $1=檔案  $2=commit 訊息
  [ -f "$1" ] || { echo "（$1 還沒有資料）"; return 0; }
  git add "$1"
  if git diff --cached --quiet -- "$1"; then echo "（$1 沒有新列）"; return 0; fi
  git commit -q -m "$2" -- "$1"
  echo "commit $(git rev-parse --short HEAD)：$2（$(wc -l < "$1") 列）"
}
push_one data_forex_ibkr/l1_quotes.csv     "data(ibkr): L1 報價快照"
push_one data_forex_ibkr/vrp_snapshots.csv "data(ibkr): 6E 期權快照"
if [ "$(git rev-list --count "origin/$BRANCH..HEAD")" -gt 0 ]; then
  for i in 1 2 3 4; do git push -q -u origin "$BRANCH" && { echo "✅ 已推送"; exit 0; }; sleep $((2 ** i)); done
  echo "❌ 推送失敗（4 次）"; exit 1
fi
echo "沒有東西要推"
