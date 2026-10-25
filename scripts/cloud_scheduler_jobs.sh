#!/usr/bin/env bash
# [R264] 第一批：GitHub 排程好唔準（hsi_touch_alert 排每 15 分鐘，實際一日 4–5 次），改由 Cloud Scheduler 準時 workflow_dispatch。
# 做法同金絲雀 canary-intraday（使用者 10-25 設定）一樣：Scheduler → GitHub API → workflow_dispatch（ref＝預設分支）。
#
# 用法：使用者自己喺 GCP Cloud Shell 跑（Claude 唔跑，唔經手 PAT）：
#   bash scripts/cloud_scheduler_jobs.sh          # 會問 PAT（唔顯示、唔落檔、唔入 repo）
#   bash scripts/cloud_scheduler_jobs.sh --dry-run  # 只印要建立嘅工作，唔改任何嘢
# PAT：fine-grained，只限 ai93560137/20260918，Actions: Read and write（可以用返金絲雀嗰條）。
# 已存在嘅工作會 update（唔會重複建立）。GitHub 原本嘅 cron 暫時保留做後備（見文末注意）。
set -euo pipefail
PROJECT=sacred-alliance-453716-b7
LOCATION=asia-east1
REPO=ai93560137/20260918
REF=claude/gcp-trading-v12-rewrite-bz75t2
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

# 名  | 時區 | cron | workflow 檔 | inputs（JSON）
JOBS=$(cat <<'T'
zhuge-hsi-touch-alert|UTC|*/15 * * * 1-5|hsi_touch_alert.yml|{}
zhuge-hsi-peak-signal|UTC|4,19,34,49 * * * 1-5|hsi_peak_signal.yml|{"send":"yes"}
zhuge-yunchui-quotes-hk|Asia/Hong_Kong|40 16 * * 1-5|yunchui_quote_kicks.yml|{}
zhuge-yunchui-quotes-us|Asia/Hong_Kong|52 5 * * 2-6|yunchui_quote_kicks.yml|{}
zhuge-ops-notify-1435|Asia/Hong_Kong|35 14 * * 1-5|ops_notify.yml|{"task":"auto"}
zhuge-ops-notify-1555|Asia/Hong_Kong|55 15 * * 1-5|ops_notify.yml|{"task":"auto"}
zhuge-ops-notify-1710|Asia/Hong_Kong|10 17 * * 1-5|ops_notify.yml|{"task":"auto"}
zhuge-ops-notify-0340|Asia/Hong_Kong|40 3 * * 2-6|ops_notify.yml|{"task":"auto"}
zhuge-ops-daily-books|Asia/Hong_Kong|20 17 * * 1-5|ops_daily_books.yml|{}
zhuge-hsi-range-preopen|Asia/Hong_Kong|53 7 * * 1-5|hsi_range_report.yml|{"report":"preopen","send":"yes"}
zhuge-hsi-range-noon|Asia/Hong_Kong|7 12 * * 1-5|hsi_range_report.yml|{"report":"noon","send":"yes"}
zhuge-hsi-range-close|Asia/Hong_Kong|37 16 * * 1-5|hsi_range_report.yml|{"report":"close","send":"yes"}
zhuge-hsi-range-night|Asia/Hong_Kong|13 3 * * 2-6|hsi_range_report.yml|{"report":"night","send":"yes"}
zhuge-es-range-preopen|America/New_York|7 18 * * 0-4|es_range_report.yml|{"report":"preopen","send":"yes"}
zhuge-es-range-noon|America/New_York|37 9 * * 1-5|es_range_report.yml|{"report":"noon","send":"yes"}
zhuge-es-range-close|America/New_York|7 16 * * 1-5|es_range_report.yml|{"report":"close","send":"yes"}
zhuge-es-range-night|America/New_York|7 17 * * 1-5|es_range_report.yml|{"report":"night","send":"yes"}
T
)

if [ $DRY = 0 ]; then
  read -r -s -p "GitHub PAT（唔會顯示）：" PAT; echo
  [ -n "$PAT" ] || { echo "冇 PAT，停"; exit 1; }
  gcloud config set project "$PROJECT" >/dev/null
fi

while IFS='|' read -r NAME TZ CRON WF INPUTS; do
  [ -z "$NAME" ] && continue
  URI="https://api.github.com/repos/$REPO/actions/workflows/$WF/dispatches"
  BODY="{\"ref\":\"$REF\",\"inputs\":$INPUTS}"
  echo "• $NAME  [$TZ] $CRON  → $WF  $INPUTS"
  [ $DRY = 1 ] && continue
  ARGS=(--location="$LOCATION" --schedule="$CRON" --time-zone="$TZ" --uri="$URI" --http-method=POST
        --headers="Authorization=Bearer $PAT,Accept=application/vnd.github+json,X-GitHub-Api-Version=2022-11-28,User-Agent=zhuge-scheduler,Content-Type=application/json"
        --message-body="$BODY" --attempt-deadline=60s --max-retry-attempts=2)
  if gcloud scheduler jobs describe "$NAME" --location="$LOCATION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$NAME" "${ARGS[@]}" --quiet >/dev/null && echo "  ↻ 已更新"
  else
    gcloud scheduler jobs create http "$NAME" "${ARGS[@]}" --quiet >/dev/null && echo "  ✅ 已建立"
  fi
done <<< "$JOBS"
unset PAT

cat <<'N'

完成。試一個：gcloud scheduler jobs run zhuge-hsi-touch-alert --location=asia-east1
然後喺 GitHub Actions 睇有冇一個 workflow_dispatch 嘅 hsi-touch-alert run（success 就得）。
注意：
- GitHub 原本 cron 仲喺度做後備；hsi_range_report 遲到嘅 cron 會按原本時點再發一次，可能重複 Telegram。
  跑順一兩日之後，叫總指揮開 PR 拎走呢幾個 workflow 嘅 schedule。
- yunchui_quote_kicks 經 dispatch 觸發時，「港股收市後檢查 hsi／vhsi 日線 final」嗰步會跳過（佢只認 schedule 事件）；
  總指揮之後會改 workflow 令 dispatch 都做呢個檢查。
- 停晒：gcloud scheduler jobs pause <名> --location=asia-east1；刪：gcloud scheduler jobs delete <名> --location=asia-east1
N
