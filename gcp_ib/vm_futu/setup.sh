#!/usr/bin/env bash
# [R187] futu-data VM（Debian 12，香港區）一次性安裝：富途 OpenD（Linux 命令列版）＋ auto_risk ＋ 富途推送腳本＋自動更新。
# 只讀：讀持倉同報價、推上 Cloud Run；唔落單、唔 unlock_trade。由使用者喺瀏覽器 SSH 跑：
#   bash ~/20260918/gcp_ib/vm_futu/setup.sh
# 前置：OpenD 已解壓到 ~/opend（入面有 FutuOpenD 同 FutuOpenD.xml）；~/zhuge/env 已填好（見 env.example）。
set -euo pipefail
U="$(id -un)"; H="$HOME"; REPO="$H/20260918"; VENV="$H/zhuge-venv"
echo "== 1. 套件"
sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip git telnet >/dev/null
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip futu-api requests pandas
echo "== 2. 檢查"
[ -x "$H/opend/FutuOpenD" ] || { echo "搵唔到 $H/opend/FutuOpenD：先解壓 OpenD 到 ~/opend"; exit 1; }
[ -f "$H/zhuge/env" ] || { echo "搵唔到 ~/zhuge/env：照 env.example 填好再跑"; exit 1; }
chmod 700 "$H/zhuge"; chmod 600 "$H/zhuge/env" "$H/opend/FutuOpenD.xml"
echo "== 3. systemd 服務"
for f in "$REPO"/gcp_ib/vm_futu/*.service "$REPO"/gcp_ib/vm_futu/*.timer; do
  sed -e "s#@USER@#$U#g" -e "s#@HOME@#$H#g" "$f" | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now zhuge-opend.service
echo "等 OpenD 起身（最多 120 秒）…"
for i in $(seq 1 24); do ss -ltn | grep -q ':11111 ' && break; sleep 5; done
ss -ltn | grep -q ':11111 ' && echo "OpenD 11111 埠 OK" || echo "⚠ 11111 未開：睇 journalctl -u zhuge-opend -n 50（可能要短訊驗證）"
sudo systemctl enable --now zhuge-auto-risk.service zhuge-futu-push.service zhuge-iv-push.service zhuge-update.timer
systemctl --no-pager --type=service --state=running | grep zhuge || true
echo "完成。紀錄：journalctl -u zhuge-auto-risk -n 30"
