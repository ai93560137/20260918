#!/bin/bash
# 長期日線測試：從 canary 分支取出恒指／VHSI／標普／VIX 日線，跑 5 個測試，結果寫到本目錄 *.txt。
# 用法：bash research/hsi_futures_range/long_daily/run.sh（需要先 git fetch origin）
set -e
cd "$(dirname "$0")"
TMP=$(mktemp -d); B=origin/claude/canary-playbook-final-3um9lp
for f in hsi vhsi spx vix; do git show $B:canary/data_external/${f}_daily.csv > $TMP/$f.csv; done
( cd $TMP && sha256sum hsi.csv vhsi.csv spx.csv vix.csv && wc -l hsi.csv vhsi.csv spx.csv vix.csv ) > inputs.txt
python3 snake_long.py $TMP/hsi.csv > snake_long.txt
python3 snake_filter.py $TMP > snake_filter.txt 2>/dev/null
python3 vrp_long.py $TMP > vrp_long.txt
python3 lead_long.py $TMP > lead_long.txt
python3 fade_us_hk50.py $TMP > fade_us_hk50.txt
sha256sum *.py > scripts_sha256.txt
rm -rf $TMP
echo 完成
