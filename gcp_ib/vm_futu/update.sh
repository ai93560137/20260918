#!/usr/bin/env bash
# [R187][R188][R199] 每 10 分鐘：睇 ops/user-machine 分支有冇新版；有就更新 repo 並重開推送服務（OpenD 唔重開）。
# 只跟 ops/user-machine（總指揮喺使用者講「更新部機」先推）；VM 上嘅 repo 唔好人手改，會被蓋。
set -uo pipefail
U="$1"; H="$2"; REPO="$H/20260918"; LOG="$H/zhuge/update.log"
cd "$REPO" || exit 1
old=$(runuser -u "$U" -- git rev-parse HEAD)
runuser -u "$U" -- git fetch -q origin ops/user-machine || { echo "$(date -u +%F' '%T) fetch 失敗" >> "$LOG"; exit 0; }
new=$(runuser -u "$U" -- git rev-parse FETCH_HEAD)
[ "$old" = "$new" ] && exit 0
runuser -u "$U" -- git reset -q --hard "$new"
# [R188] repo 入面嘅 service／timer 改咗都即刻生效（OpenD 唔重開，免得要重新登入）
for f in "$REPO"/gcp_ib/vm_futu/*.service "$REPO"/gcp_ib/vm_futu/*.timer; do
  sed -e "s#@USER@#$U#g" -e "s#@HOME@#$H#g" "$f" > "/etc/systemd/system/$(basename "$f")"
done
systemctl daemon-reload
systemctl restart zhuge-auto-risk.service zhuge-futu-push.service zhuge-iv-push.service
systemctl try-restart zhuge-longfei-guard.service zhuge-longfei.service 'zhuge-longfei@*.service'   # [R199][R202] 只重開已經開咗嘅（新產品要跑 setup.sh 先開）
echo "$(date -u +%F' '%T) 更新 ${old:0:9} → ${new:0:9}，已重開推送服務" >> "$LOG"
