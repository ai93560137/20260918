#!/usr/bin/env bash
# [R188] OpenD 10.11 Linux 版唔讀 FutuOpenD.xml／命令列嘅帳號密碼（MD5 亦唔收），每次開都喺主控台問帳號、密碼、記住密碼。
# 所以喺 tmux（session 名 opend）入面開 OpenD，由 ~/zhuge/opend_login（chmod 600；第一行牛牛號、第二行「登入」密碼，
# 唔係交易密碼）自動答。每次開 OpenD 只試一次登入；失敗就寫 ~/zhuge/opend_login.failed，之後唔再自動試
# （富途密碼錯有次數限制，免得鎖戶口），發 Telegram，留喺 tmux 等人手 `tmux attach -t opend`（Ctrl+B 再 d 離開）。
# [R189] OpenD 一退出（例如「登录次数过多,请等待 50 分钟」，exit 31）tmux 會保留最後畫面（remain-on-exit）寫入 log；
# 次數過多就等 60 分鐘先退出，免得 systemd 每 30 秒重開越鎖越耐。
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
# [R227] 登入結果要睇成個畫面：OpenD 10.11 喺「必要数据准备完毕」之後仲會印權限列表，淨睇最後 3 行會誤判失敗
whole() { tmux capture-pane -pt "$S" -S -300 2>/dev/null; }
waitfor() {  # $1 = regex，$2 = 最多等幾秒
  local i; for i in $(seq 1 "$2"); do screen | grep -qE "$1" && return 0; sleep 1; done; return 1
}
answer() {  # 經 tmux buffer 打字，唔會出現喺 ps／log
  printf '%s' "$1" | tmux load-buffer -b zl - && tmux paste-buffer -d -b zl -t "$S" && tmux send-keys -t "$S" Enter
}
alert() { local m; m="$(screen | mask | tr "\n" " ")"; log "⚠ $1：$m"; tg "$1（畫面：$m）。請瀏覽器 SSH 入 futu-data 跑 tmux attach -t opend 人手處理"; }

tmux kill-session -t "$S" 2>/dev/null || true
cd "$H/opend" || { log "搵唔到 $H/opend"; exit 1; }
# 先開空 session 設好 remain-on-exit，再換上 OpenD（OpenD 即刻退出都留低畫面）
tmux new-session -d -s "$S" -x 200 -y 50 "sleep 86400"
tmux set-option -t "$S" remain-on-exit on >/dev/null
tmux respawn-pane -k -t "$S" "$H/opend/FutuOpenD"
log "OpenD 已喺 tmux session '$S' 開咗"
dead() { [ "$(tmux display-message -p -t "$S" '#{pane_dead}' 2>/dev/null || echo 1)" = 1 ]; }

if [ -f "$FAILED" ]; then
  alert "上次自動登入失敗，暫停自動登入（確認密碼後刪 ~/zhuge/opend_login.failed）"
elif [ ! -f "$CRED" ]; then
  alert "冇 ~/zhuge/opend_login，要人手登入"
elif ! waitfor '请输入账号|已退出|次数过多' 60 || ! screen | grep -q '请输入账号'; then
  alert "OpenD 冇問帳號"
else
  { IFS= read -r ACC; IFS= read -r PW; } < "$CRED"
  answer "$ACC"
  if waitfor '请输入密码' 15; then answer "$PW"; fi
  unset ACC PW
  if waitfor '记住密码' 15; then tmux send-keys -t "$S" N Enter; fi
  for _ in $(seq 1 180); do whole | grep -qE '必要数据准备完毕|登录失败|密码错误|验证码' && break; sleep 1; done
  if whole | grep -qE '必要数据准备完毕'; then
    log "OpenD 登入成功"
  elif whole | grep -qE '验证码'; then
    alert "OpenD 要手機驗證碼"
  elif whole | grep -qE '登录失败|密码错误'; then
    : > "$FAILED"                                  # 只有富途明確話登入失敗先暫停自動登入（免得鎖戶口）
    alert "OpenD 自動登入失敗，已暫停自動登入"
  else
    alert "OpenD 3 分鐘內冇講登入成功定失敗（唔暫停自動登入）"
  fi
fi

while ! dead; do sleep 30; done
last="$(screen | mask | tr "\n" " ")"
tmux kill-session -t "$S" 2>/dev/null || true
if echo "$last" | grep -q '次数过多'; then
  log "⚠ OpenD 退出：$last；等 60 分鐘先再試"
  tg "OpenD 登入次數過多（$last），60 分鐘後自動再試；期間唔好人手重開"
  sleep 3600
else
  log "OpenD 已退出（$last），交由 systemd 重開"
fi
exit 1
