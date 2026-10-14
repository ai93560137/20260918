#!/usr/bin/env bash
# [R188] OpenD 10.11 Linux 版唔讀 FutuOpenD.xml／命令列嘅帳號密碼（MD5 亦唔收），每次開都喺主控台問帳號、密碼、記住密碼。
# 所以喺 tmux（session 名 opend）入面開 OpenD，由 ~/zhuge/opend_login（chmod 600；第一行牛牛號、第二行「登入」密碼，
# 唔係交易密碼）自動答。每次開 OpenD 只試一次登入；失敗就寫 ~/zhuge/opend_login.failed，之後唔再自動試
# （富途密碼錯有次數限制，免得鎖戶口），發 Telegram，留喺 tmux 等人手 `tmux attach -t opend`（Ctrl+B 再 d 離開）。
# 由 zhuge-opend.service 呼叫：bash opend_tmux.sh <HOME>
set -uo pipefail
H="${1:-$HOME}"; S=opend
CRED="$H/zhuge/opend_login"; FAILED="$H/zhuge/opend_login.failed"

log() { echo "$(date -u +%F' '%T) $*"; }
mask() { sed -E 's/[0-9]{6,}/###/g'; }
tg() {
  [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || return 0
  curl -s -m 15 -o /dev/null "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT_ID}" --data-urlencode "text=[futu-data] $*" || true
}
screen() { tmux capture-pane -pt "$S" 2>/dev/null | grep -v '^\s*$' | tail -n 3; }
waitfor() {  # $1 = regex，$2 = 最多等幾秒
  local i; for i in $(seq 1 "$2"); do screen | grep -qE "$1" && return 0; sleep 1; done; return 1
}
answer() {  # 經 tmux buffer 打字，唔會出現喺 ps／log
  printf '%s' "$1" | tmux load-buffer -b zl - && tmux paste-buffer -d -b zl -t "$S" && tmux send-keys -t "$S" Enter
}
alert() { local m; m="$(screen | mask | tr "\n" " ")"; log "⚠ $1：$m"; tg "$1（畫面：$m）。請瀏覽器 SSH 入 futu-data 跑 tmux attach -t opend 人手處理"; }

tmux kill-session -t "$S" 2>/dev/null || true
cd "$H/opend" || { log "搵唔到 $H/opend"; exit 1; }
tmux new-session -d -s "$S" -x 200 -y 50 "$H/opend/FutuOpenD"
log "OpenD 已喺 tmux session '$S' 開咗"

if [ -f "$FAILED" ]; then
  alert "上次自動登入失敗，暫停自動登入（確認密碼後刪 ~/zhuge/opend_login.failed）"
elif [ ! -f "$CRED" ]; then
  alert "冇 ~/zhuge/opend_login，要人手登入"
elif ! waitfor '请输入账号' 60; then
  alert "60 秒內冇見到「请输入账号」"
else
  { IFS= read -r ACC; IFS= read -r PW; } < "$CRED"
  answer "$ACC"
  if waitfor '请输入密码' 15; then answer "$PW"; fi
  unset ACC PW
  if waitfor '记住密码' 15; then tmux send-keys -t "$S" N Enter; fi
  waitfor '必要数据准备完毕|登录失败|验证码' 120
  if screen | grep -qE '必要数据准备完毕'; then
    log "OpenD 登入成功"
  elif screen | grep -qE '验证码'; then
    alert "OpenD 要手機驗證碼"
  else
    : > "$FAILED"
    alert "OpenD 自動登入失敗，已暫停自動登入"
  fi
fi

while tmux has-session -t "$S" 2>/dev/null; do sleep 30; done
log "OpenD 已退出，交由 systemd 重開"
exit 1
