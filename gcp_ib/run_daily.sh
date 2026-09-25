#!/usr/bin/env bash
# IB 採集每日例行（跑在 GCP VM 的 crontab，不在沙盒）。
# 前置：本 repo 已 clone 到 VM（用只限本 repo 的 fine-grained PAT 或 deploy key），
#       IB Gateway 已登入常駐（建議 IBC 自動重啟），pip install ib_insync。
# crontab 例（UTC；東京收盤後+法蘭克福盤中）：  35 7 * * 1-5  bash /path/to/gcp_ib/run_daily.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --rebase -q origin claude/dazzling-curie-f3xzb8
python3 gcp_ib/ib_collector.py --port "${IB_PORT:-4002}"
git add tradingview/data_external/ib_iv_log.csv
git diff --cached --quiet || {
  git commit -m "data: IB 延遲 IV 快照（N225/ESTX50 週月斜率，VM 自動）"
  git push -q origin claude/dazzling-curie-f3xzb8
}
