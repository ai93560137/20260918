#!/usr/bin/env bash
# IB Gateway 模擬帳免責聲明自動點掉（跑在 GCP VM 的 crontab，不在沙盒）。2026-10-12
# 症狀：API 連線回 Error 10141「Paper trading disclaimer must first be accepted」、採集 TimeoutError；
#       Gateway 畫面（Xvfb :1）有一個標題 Warning、501x260 的對話框，唯一按鈕「I understand and accept」。
#       IBC 的 AcceptNonBrokerageAccountWarning=yes 理應自動按，10/07 起某次重登後沒按到，見排障記錄第 6 項。
# 保險：只在「標題正好是 Warning」且「視窗大小正好 501x260」時才點，按鈕座標依視窗位置換算（相對 +249,+240）。
#       其他 Warning／大小不同的框一律不碰、只記 log。不下單、不改設定。
# crontab 例（每 10 分鐘）：
#   */10 * * * * bash $HOME/20260918/gcp_ib/dismiss_paper_warning.sh >> $HOME/ib_warning_click.log 2>&1
export DISPLAY="${DISPLAY:-:1}"
EXPECT_W=501; EXPECT_H=260; BTN_DX=249; BTN_DY=240
pgrep -f ibgateway > /dev/null || exit 0                       # Gateway 沒在跑就沒事
for w in $(xdotool search --onlyvisible --name '^Warning$' 2>/dev/null); do
  geo="$(xdotool getwindowgeometry --shell "$w" 2>/dev/null)" || continue
  eval "$geo"                                                   # 設定 X Y WIDTH HEIGHT
  if [ "$WIDTH" = "$EXPECT_W" ] && [ "$HEIGHT" = "$EXPECT_H" ]; then
    xdotool mousemove $((X + BTN_DX)) $((Y + BTN_DY)) click 1
    echo "$(date -u '+%F %T') UTC 點掉 10141 免責聲明：視窗 $w 位置 $X,$Y 大小 ${WIDTH}x${HEIGHT}"
  else
    echo "$(date -u '+%F %T') UTC 有 Warning 視窗但大小 ${WIDTH}x${HEIGHT}≠${EXPECT_W}x${EXPECT_H}，不碰（請截圖：DISPLAY=:1 import -window root ~/gw.png）"
  fi
done
