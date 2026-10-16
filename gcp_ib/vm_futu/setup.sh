#!/usr/bin/env bash
# [R187][R188][R199][R202] futu-data VM（Debian 12，香港區）一次性安裝：富途 OpenD（Linux 命令列版）＋ auto_risk ＋ 富途推送腳本＋自動更新。
# 只讀：讀持倉同報價、推上 Cloud Run；唔落單、唔 unlock_trade。由使用者喺瀏覽器 SSH 跑：
#   bash ~/20260918/gcp_ib/vm_futu/setup.sh
# 前置：OpenD 已解壓到 ~/opend（入面有 FutuOpenD 同 FutuOpenD.xml）；~/zhuge/env 已填好（見 env.example）。
set -euo pipefail
U="$(id -un)"; H="$HOME"; REPO="$H/20260918"; VENV="$H/zhuge-venv"
echo "== 1. 套件"
sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip git telnet tmux curl >/dev/null
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip futu-api requests pandas "anthropic>=0.40"
echo "== 2. 檢查"
[ -x "$H/opend/FutuOpenD" ] || { echo "搵唔到 $H/opend/FutuOpenD：先解壓 OpenD 到 ~/opend"; exit 1; }
[ -f "$H/zhuge/env" ] || { echo "搵唔到 ~/zhuge/env：照 env.example 填好再跑"; exit 1; }
chmod 700 "$H/zhuge"; chmod 600 "$H/zhuge/env" "$H/opend/FutuOpenD.xml"
[ -f "$H/zhuge/opend_login" ] && chmod 600 "$H/zhuge/opend_login" || echo "⚠ 冇 ~/zhuge/opend_login：OpenD 開機要人手 tmux attach -t opend 登入（見 RUNBOOK_FUTU_VM.md）"
echo "== 3. systemd 服務"
for f in "$REPO"/gcp_ib/vm_futu/*.service "$REPO"/gcp_ib/vm_futu/*.timer; do
  sed -e "s#@USER@#$U#g" -e "s#@HOME@#$H#g" "$f" | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable zhuge-opend.service && sudo systemctl restart zhuge-opend.service
echo "等 OpenD 登入（最多 180 秒）…"
for i in $(seq 1 36); do journalctl -u zhuge-opend --since "-5min" -q | grep -qE '登入成功|⚠' && break; sleep 5; done
journalctl -u zhuge-opend -n 5 --no-pager -q
journalctl -u zhuge-opend --since "-5min" -q | grep -q '登入成功' && echo "OpenD 登入 OK" || echo "⚠ OpenD 未登入：tmux attach -t opend 睇畫面（Ctrl+B 再 d 離開，唔好 Ctrl+C）"
sudo systemctl enable --now zhuge-auto-risk.service zhuge-futu-push.service zhuge-iv-push.service zhuge-update.timer
# [R199] 🐉 龍飛陣：有 ANTHROPIC_API_KEY 先開（TRD_ENV 由 repo settings.env 定，預設 SIMULATE）
mkdir -p "$H/zhuge/ai_trader" && chmod 700 "$H/zhuge/ai_trader"
if grep -q '^ANTHROPIC_API_KEY=sk-ant-' "$H/zhuge/env"; then
  sudo systemctl enable --now zhuge-longfei-guard.service zhuge-longfei.service
  # [R202] 其他產品：settings.env 嘅 LONGFEI_EXTRA_PRODUCTS（例如 SPY,QQQ,DIA）各開一個 zhuge-longfei@<產品>
  EXTRA=$(grep -oE '^LONGFEI_EXTRA_PRODUCTS=.*' "$REPO/gcp_ib/vm_futu/settings.env" | cut -d= -f2 | tr ',' ' ')
  for P in $EXTRA; do
    mkdir -p "$H/zhuge/ai_trader_$P" && chmod 700 "$H/zhuge/ai_trader_$P"
    sudo systemctl enable --now "zhuge-longfei@$P.service"
  done
  for u in $(systemctl list-units --plain --no-legend 'zhuge-longfei@*.service' | awk '{print $1}'); do
    P=${u#zhuge-longfei@}; P=${P%.service}
    echo " $EXTRA " | grep -q " $P " || { sudo systemctl disable --now "$u"; echo "已停 $u（唔喺 LONGFEI_EXTRA_PRODUCTS）"; }
  done
  sudo systemctl restart zhuge-longfei-guard.service   # 重讀產品清單
  echo "龍飛陣：$(grep -oE '^TRD_ENV=.*' "$REPO/gcp_ib/vm_futu/settings.env")；產品 HSI ${EXTRA}"
else
  echo "⚠ ~/zhuge/env 冇 ANTHROPIC_API_KEY：龍飛陣未開（見 RUNBOOK_FUTU_VM.md）"
fi
systemctl --no-pager --type=service --state=running | grep zhuge || true
echo "完成。紀錄：journalctl -u zhuge-auto-risk -n 30"
