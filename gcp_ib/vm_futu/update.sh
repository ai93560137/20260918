#!/usr/bin/env bash
# [R187] 每 10 分鐘：睇 ops/user-machine 分支有冇新版；有就更新 repo 並重開推送服務（OpenD 唔重開）。
# 只跟 ops/user-machine（總指揮喺使用者講「更新部機」先推）；VM 上嘅 repo 唔好人手改，會被蓋。
set -uo pipefail
U="$1"; H="$2"; REPO="$H/20260918"; LOG="$H/zhuge/update.log"
cd "$REPO" || exit 1
old=$(runuser -u "$U" -- git rev-parse HEAD)
runuser -u "$U" -- git fetch -q origin ops/user-machine || { echo "$(date -u +%F' '%T) fetch 失敗" >> "$LOG"; exit 0; }
new=$(runuser -u "$U" -- git rev-parse FETCH_HEAD)
[ "$old" = "$new" ] && exit 0
runuser -u "$U" -- git reset -q --hard "$new"
systemctl daemon-reload
systemctl restart zhuge-auto-risk.service zhuge-futu-push.service zhuge-iv-push.service
echo "$(date -u +%F' '%T) 更新 ${old:0:9} → ${new:0:9}，已重開推送服務" >> "$LOG"
