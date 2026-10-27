#!/usr/bin/env bash
# [R187][R188][R199] 每 10 分鐘：睇 ops/user-machine 分支有冇新版；有就更新 repo 並重開推送服務（OpenD 唔重開）。
# 只跟 ops/user-machine（總指揮喺使用者講「更新部機」先推）；VM 上嘅 repo 唔好人手改，會被蓋。
set -uo pipefail
U="$1"; H="$2"; REPO="$H/20260918"; LOG="$H/zhuge/update.log"
cd "$REPO" || exit 1
# [R306] 10-23 21:50 HKT 硬碟爆（No space left）：每 10 分鐘清舊 log，唔使等有新版（git fetch 都要硬碟位）
FLOG="$H/.com.futunn.FutuOpenD/Log"                 # OpenD 同 futu-api（每個連線程式）嘅 log
find "$FLOG" -type f -mmin +4320 -delete 2>/dev/null  # 3 日前
J=/etc/systemd/journald.conf.d/zhuge.conf
if [ ! -f "$J" ]; then mkdir -p "${J%/*}"; printf '[Journal]\nSystemMaxUse=300M\n' > "$J"; systemctl restart systemd-journald; fi
AVAIL=$(df --output=avail -m / | tail -1 | tr -d " ")
if [ "${AVAIL:-99999}" -lt 1024 ]; then   # 少過 1GB：清得狠啲
  find "$FLOG" -type f -mmin +360 -delete 2>/dev/null
  journalctl --vacuum-size=100M >/dev/null 2>&1
  echo "$(date -u +%F' '%T) ⚠ 硬碟少過 1GB，已清 Futu log 同 journald" >> "$LOG"
fi
old=$(runuser -u "$U" -- git rev-parse HEAD)
runuser -u "$U" -- git fetch -q origin ops/user-machine || { echo "$(date -u +%F' '%T) fetch 失敗" >> "$LOG"; exit 0; }
# [R307] 10-23 硬碟滿時 FETCH_HEAD 寫唔到，rev-parse 失敗會印返「FETCH_HEAD」字樣當新版，每 10 分鐘重開晒程式：攞唔到就跳過
new=$(runuser -u "$U" -- git rev-parse -q --verify 'FETCH_HEAD^{commit}') || { echo "$(date -u +%F' '%T) 讀唔到 FETCH_HEAD（硬碟滿？），跳過" >> "$LOG"; exit 0; }
[ "$old" = "$new" ] && exit 0
runuser -u "$U" -- git reset -q --hard "$new"
# [R188] repo 入面嘅 service／timer 改咗都即刻生效（OpenD 唔重開，免得要重新登入）
for f in "$REPO"/gcp_ib/vm_futu/*.service "$REPO"/gcp_ib/vm_futu/*.timer; do
  sed -e "s#@USER@#$U#g" -e "s#@HOME@#$H#g" "$f" > "/etc/systemd/system/$(basename "$f")"
done
systemctl daemon-reload
systemctl restart zhuge-auto-risk.service zhuge-futu-push.service zhuge-iv-push.service
# [R220] 先停走唔再列嘅程式、再重開其餘（10-18 OOM 事故：唔好一次過重開晒先停）
bash "$REPO/gcp_ib/vm_futu/longfei_units.sh" "$U" "$H" >> "$LOG" 2>&1   # [R209] 真倉程式跟 LONGFEI_REAL_PRODUCTS 開／停
systemctl try-restart zhuge-longfei-guard.service zhuge-longfei.service 'zhuge-longfei@*.service'   # [R199][R202] 只重開已經開咗嘅
echo "$(date -u +%F' '%T) 更新 ${old:0:9} → ${new:0:9}，已重開推送服務" >> "$LOG"
