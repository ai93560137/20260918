#!/usr/bin/env bash
# IB Gateway + IBC 一鍵安裝（跑在 GCP VM，Ubuntu/Debian）。2026-09-25
# 帳密永不經過聊天/repo：只在第 2 步由你本人填進 VM 上的 config.ini（chmod 600）。
# 用法：bash setup_vm.sh   然後照最後印出的三步做。
set -euo pipefail
cd "$HOME"

echo "== 1/4 系統依賴 =="
sudo apt-get update -qq
sudo apt-get install -y -qq openjfx unzip xvfb python3-pip curl > /dev/null
# Debian 12+ 的 PEP668 保護：先試正常裝，被拒就加 --break-system-packages（專用 VM 無妨）
pip3 install -q ib_insync 2>/dev/null || pip3 install -q --break-system-packages ib_insync

echo "== 2/4 IB Gateway（stable, headless 安裝）=="
if [ ! -d "$HOME/Jts" ]; then
  curl -sSLo ibgw.sh \
    https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
  chmod +x ibgw.sh
  ./ibgw.sh -q -dir "$HOME/Jts/ibgateway/stable" || ./ibgw.sh -q
  rm -f ibgw.sh
fi

echo "== 3/4 IBC（自動登入/斷線重啟）=="
if [ ! -d "$HOME/ibc" ]; then
  curl -sSLo ibc.zip \
    "$(curl -sS https://api.github.com/repos/IbcAlpha/IBC/releases/latest |
       grep -o 'https://[^\"]*IBCLinux[^\"]*\.zip' | head -1)"
  mkdir -p "$HOME/ibc" && unzip -q ibc.zip -d "$HOME/ibc" && rm ibc.zip
  chmod +x "$HOME"/ibc/*.sh "$HOME"/ibc/scripts/*.sh 2>/dev/null || true
fi
CFG="$HOME/ibc/config.ini"
if [ ! -f "$CFG" ] || ! grep -q '^IbLoginId=..*' "$CFG" 2>/dev/null; then
  cat > "$CFG" << 'EOF'
# ↓↓ 只需改這兩行（paper 帳戶的登入名/密碼），存檔後 chmod 600 本檔 ↓↓
IbLoginId=FILL_ME
IbPassword=FILL_ME
TradingMode=paper
AcceptIncomingConnectionAction=accept
ReadOnlyApi=yes
IbAutoClosedown=no
AcceptNonBrokerageAccountWarning=yes
OverrideTwsApiPort=4002
EOF
  chmod 600 "$CFG"
fi

echo "== 4/4 開機自啟 + 每日採集 crontab =="
cat > "$HOME/start_ibgw.sh" << EOF
#!/usr/bin/env bash
export DISPLAY=:1
pgrep -f Xvfb > /dev/null || (Xvfb :1 -screen 0 1024x768x24 &)
sleep 2
TWS_MAJOR_VRSN=\$(ls "\$HOME/Jts/ibgateway" | sort | tail -1)
"\$HOME/ibc/scripts/ibcstart.sh" "\$TWS_MAJOR_VRSN" --gateway \
  "--tws-path=\$HOME/Jts" "--ibc-path=\$HOME/ibc" "--ibc-ini=\$HOME/ibc/config.ini" \
  "--mode=paper" > "\$HOME/ibgw.log" 2>&1 &
EOF
chmod +x "$HOME/start_ibgw.sh"
( crontab -l 2>/dev/null | grep -v 'start_ibgw\|run_daily' ;
  echo '@reboot bash $HOME/start_ibgw.sh' ;
  echo '35 7 * * 1-5 bash $HOME/20260918/gcp_ib/run_daily.sh >> $HOME/ib_daily.log 2>&1' ) | crontab -

cat << 'DONE'

安裝完成。剩下三步是你親手做的（帳密不經過任何人）：
  ① nano ~/ibc/config.ini   → 把兩個 FILL_ME 改成 paper 帳戶的登入名/密碼，存檔
  ② bash ~/start_ibgw.sh    → 首次啟動；paper 帳戶通常無需 2FA，等 1 分鐘
  ③ git clone https://github.com/ai93560137/20260918 ~/20260918（用 fine-grained PAT，
     只授這個 repo contents 讀寫）→ cd ~/20260918 && git checkout claude/dazzling-curie-f3xzb8
     → python3 gcp_ib/ib_collector.py --dry   把輸出貼回給 Claude 調試

之後每天 UTC 07:35（HKT 15:35）自動採集推送，無需再管。
DONE
