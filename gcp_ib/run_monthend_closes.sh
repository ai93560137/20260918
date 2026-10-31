#!/usr/bin/env bash
# 鳥翔月底名單 IBKR 收市／開市覆核——ib-data VM 自動排程（使用者帳號 hengkychansinghing 的 crontab，不在沙盒）。2026-10-31
#
# 做法同 run_vol_daily.sh：
#   - 抓取程式是固定複本 gcp_ib/ib_stock_monthend.py（來源 claude/stock-research-k9nzau 的 scripts/ib_stock_verify.py），
#     不直接執行別的分支；請求檔（只是 CSV 數據）從公開 repo 的鳥翔分支下載。
#   - 結果提交到「專用資料分支」data/stock-ibkr（獨立資料 repo ~/stock-ibkr-data，只含 data_stock_ibkr/），與程式分支分開。
#     取用：git fetch origin data/stock-ibkr && git checkout origin/data/stock-ibkr -- data_stock_ibkr/<市場>_<日>.csv
#   - 只讀行情：readonly 連線、clientId 61（不與其他採集撞）；不下單、不改帳戶。
#   - 全程日誌寫 /srv/ibshare/monthend.log（claude-ops 可唯讀看）；寫不到就寫 ~/monthend.log。
#
# 流程：下載請求檔 → 取最新訊號日 D → 已齊全（每檔 ok 且有下一交易日，或 no_contract／no_data）的市場跳過
#       → probe → 先跑 --no-rth 市場（檔名後綴 _nortrh）→ 再跑正式 → 關鍵字掃描 → commit＋push。
#       失敗可直接重跑：已抓好的列會跳過；未有下一交易日或 no_data 的列會重抓，所以月底後太早跑亦安全。
#
# 用法：
#   bash ~/20260918/gcp_ib/run_monthend_closes.sh --dry   # 試跑：只 probe（寫去暫存資料夾），不提交、不推送
#   bash ~/20260918/gcp_ib/run_monthend_closes.sh         # 正式
# crontab（UTC；每月 1–8 號每日 22:05：美股冬令 21:00／夏令 20:00 收市之後，早於 run_vol_daily 22:30 結束前後、
#          亦早於 Gateway 約 23:50 的每日重啟；名單齊全後每次幾秒就結束）：
#   5 22 1-8 * * bash $HOME/20260918/gcp_ib/run_monthend_closes.sh >> $HOME/monthend_cron.log 2>&1
#
# 結束代碼：0 完成或無事可做；1 一般錯誤；3 未能連上 IB Gateway（TCP 連唔到／握手或啟動同步逾時）；4 關鍵字掃描命中，不推送。
# （抓取程式代碼 5 = 連續冇數據疑似 IB 維護、提早停：照提交已抓部分，下次再補。）
set -uo pipefail
umask 027

REPO="$(cd "$(dirname "$0")/.." && pwd)"                       # 程式 clone（~/20260918）
DATA="${STOCK_IBKR_DATA_DIR:-$HOME/stock-ibkr-data}"
BRANCH="${STOCK_IBKR_BRANCH:-data/stock-ibkr}"
CODE_BRANCH="${CODE_BRANCH:-claude/dazzling-curie-f3xzb8}"
REQ_URL="${MONTHEND_REQ_URL:-https://raw.githubusercontent.com/ai93560137/20260918/claude/stock-research-k9nzau/analysis/tt_all/ibkr_request.csv}"
PORT="${IB_PORT:-4002}"
CLIENT_ID="${MONTHEND_CLIENT_ID:-61}"
PACE="${MONTHEND_PACE:-2.5}"                                   # 每個請求間隔秒數
MARKETS="${MONTHEND_MARKETS:-hk sg au us}"
NORTH_MARKETS="${MONTHEND_NORTH_MARKETS:-au}"                    # 另跑 useRTH=False 對照（收市競價）
LOG="${MONTHEND_LOG:-/srv/ibshare/monthend.log}"
PY="${PYTHON:-python3}"
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

if ! touch "$LOG" 2>/dev/null; then LOG="$HOME/monthend.log"; fi
exec > >(tee -a "$LOG") 2>&1
say() { echo "$(date -u '+%F %T') UTC $*"; }

exec 9>"$HOME/.monthend_closes.lock"
if ! flock -n 9; then say "⏭ 另一個 run_monthend_closes 仍在跑，本次略過"; exit 0; fi

say "== 鳥翔月底 IBKR 核對 開始$([ $DRY = 1 ] && echo '（--dry 試跑）') =="
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# 1) 更新程式（失敗不擋：沿用現有版本）
git -C "$REPO" pull --rebase --autostash -q origin "$CODE_BRANCH" 2>&1 || say "⚠️ 程式更新失敗，沿用現有版本"
FETCHER="$REPO/gcp_ib/ib_stock_monthend.py"

# 2) 請求檔
if ! curl -fsSL --retry 3 -o "$WORK/req.csv" "$REQ_URL"; then
  say "❌ 下載請求檔失敗：$REQ_URL"; exit 1
fi
read -r D NREQ < <("$PY" - "$WORK/req.csv" "$MARKETS" <<'EOF'
import csv, sys
mk = set(sys.argv[2].split())
rows = [r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")) if r["market"] in mk]
print(max((r["signal_date"] for r in rows), default="-"), len(rows))
EOF
)
if [ "$D" = "-" ]; then say "❌ 請求檔冇 $MARKETS 嘅列"; exit 1; fi
say "請求檔：訊號日 $D，市場 $MARKETS 共 $NREQ 檔"

# 3) 資料 repo（第一次才建立；身分與推送設定沿用程式 clone，不新增憑證）
URL="$(git -C "$REPO" remote get-url origin)"
if [ ! -d "$DATA/.git" ]; then
  mkdir -p "$DATA"; git -C "$DATA" init -q; git -C "$DATA" remote add origin "$URL"
fi
cd "$DATA" || exit 1
git config user.name  "$(git -C "$REPO" config user.name  2>/dev/null || echo ib-data)"
git config user.email "$(git -C "$REPO" config user.email 2>/dev/null || echo ib-data@localhost)"
if [ -z "$(git config --local --get-all credential.helper 2>/dev/null)" ]; then
  { git -C "$REPO" config --local --get-all credential.helper 2>/dev/null || true; } | while IFS= read -r h; do
    git config --local --add credential.helper "$h"
  done
fi
git reset -q --hard 2>/dev/null || true
if git fetch -q origin "$BRANCH" 2>/dev/null; then
  git checkout -q -B "$BRANCH" FETCH_HEAD
else
  git symbolic-ref HEAD "refs/heads/$BRANCH"
  say "（第一次執行：建立資料分支 $BRANCH）"
fi
mkdir -p data_stock_ibkr

# 4) 邊啲市場未齊（每檔 ok 且有下一交易日，或 no_contract，先算齊）
pending() {  # $1 = 市場清單，$2 = 檔名後綴
  "$PY" - "$WORK/req.csv" "$D" "$1" "$2" "$DATA/data_stock_ibkr" <<'EOF'
import csv, sys
from pathlib import Path
req, d, mks, suf, out = sys.argv[1], sys.argv[2], sys.argv[3].split(), sys.argv[4], Path(sys.argv[5])
want = {}
for r in csv.DictReader(open(req, encoding="utf-8")):
    if r["market"] in mks and r["signal_date"] == d:
        want.setdefault(r["market"], set()).add(r["ticker"])
left = []
for mk, ts in sorted(want.items()):
    p = out / f"{mk}_{d}{suf}.csv"
    got = {r["ticker"]: r for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}
    # no_data 唔當完成：週末維護時歷史數據請求會逾時變 no_data，要下次再試；只有 no_contract（IB 冇呢隻股）先係最終結果
    done = lambda r: r is not None and (r["status"] == "no_contract" or (r["status"] == "ok" and r.get("next_date")))
    if not all(done(got.get(t)) for t in ts):
        left.append(mk)
print(" ".join(left))
EOF
}
TODO="$(pending "$MARKETS" "")"
TODO_N="$(pending "$NORTH_MARKETS" "_nortrh")"
if [ -z "$TODO" ] && [ -z "$TODO_N" ]; then say "✅ $D 已齊全（$MARKETS；no-rth：$NORTH_MARKETS），無事可做"; exit 0; fi
say "待抓：正式 [${TODO:-無}]；no-rth [${TODO_N:-無}]"

run_fetch() {  # 其餘參數照傳；回傳 python 的結束代碼（124 = 超過 MONTHEND_MAX_SEC 被停，防止卡死霸住鎖）
  timeout "${MONTHEND_MAX_SEC:-7200}" "$PY" "$FETCHER" --port "$PORT" --client-id "$CLIENT_ID" --pace "$PACE" --req "$WORK/req.csv" "$@"
}
gw_fail() { say "❌ 未能連上 IB Gateway（127.0.0.1:$PORT），原因見上一行（TCP 連唔到／握手或啟動同步逾時）。今次唔提交；排程下一日會自動再試，亦可以人手重跑。"; exit 3; }

# 5) probe（--dry 寫去暫存資料夾）
ALL="$(echo "$TODO $TODO_N" | tr ' ' '\n' | sort -u | tr '\n' ' ')"
PROBE_OUT="$DATA/data_stock_ibkr"; [ $DRY = 1 ] && PROBE_OUT="$WORK/probe"
run_fetch --job probe --out "$PROBE_OUT" --market $ALL; rc=$?
[ $rc = 3 ] && gw_fail
[ $rc != 0 ] && { say "❌ probe 失敗（代碼 $rc）"; exit 1; }
if [ $DRY = 1 ]; then
  say "probe 結果（暫存，不提交）："; tail -n 20 "$PROBE_OUT/_status.txt"
  say "--dry 完成：正式執行會抓 [${TODO:-無}]，no-rth [${TODO_N:-無}]，推去 $BRANCH"; exit 0
fi

# 6) 先 no-rth（獨立檔名），再正式
if [ -n "$TODO_N" ]; then
  run_fetch --job closes --out "$DATA/data_stock_ibkr" --market $TODO_N --no-rth --suffix _nortrh; rc=$?
  [ $rc = 3 ] && gw_fail
  [ $rc != 0 ] && say "⚠️ no-rth 抓取代碼 $rc（照提交已抓到的部分）"
fi
if [ -n "$TODO" ]; then
  run_fetch --job closes --out "$DATA/data_stock_ibkr" --market $TODO; rc=$?
  [ $rc = 3 ] && gw_fail
  [ $rc != 0 ] && say "⚠️ 正式抓取代碼 $rc（照提交已抓到的部分）"
fi

# 7) 關鍵字掃描 → 提交 → 推送
git add data_stock_ibkr
if git diff --cached --quiet; then say "沒有新資料，略過提交"; exit 0; fi
if git diff --cached -U0 | grep -E '^\+' | grep -inE 'password|passwd|token|secret|api[ _-]?key' | head -5; then
  say "❌ 關鍵字掃描命中（見上），今次唔提交、唔推送；請人手檢查 $DATA/data_stock_ibkr"
  git reset -q; exit 4
fi
LEFT="$(pending "$MARKETS" "")"; LEFT_N="$(pending "$NORTH_MARKETS" "_nortrh")"
git commit -q -m "data(ibkr): 鳥翔月底名單 $D 收市／開市覆核（$MARKETS；no-rth $NORTH_MARKETS；VM 自動）" \
  -m "未齊：正式 [${LEFT:-無}]；no-rth [${LEFT_N:-無}]（下次排程會補）"
ok=0
for i in 1 2 3 4; do
  if git push -q origin "$BRANCH"; then ok=1; break; fi
  sleep $((i * 5))
done
[ $ok = 1 ] || { say "❌ 推送失敗（下次排程會由資料分支重新接上並重抓未推的部分）"; exit 1; }
say "✅ 已推送 $BRANCH：$(git rev-parse --short HEAD)；未齊：正式 [${LEFT:-無}]；no-rth [${LEFT_N:-無}]"
