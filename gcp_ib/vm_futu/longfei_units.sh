#!/usr/bin/env bash
# [R209][R215] 龍飛陣程式對齊 settings.env：模擬 LONGFEI_EXTRA_PRODUCTS、真倉 LONGFEI_REAL_PRODUCTS（使用者 10-17：一落指令就用真倉；模擬倉照跑前向測試）。
#   有列：開 zhuge-longfei-real@<產品>（已經開緊就重開，用新程式）。
#   冇列：手上冇倉就停；仲有倉就唔停（停咗冇人守止蝕），放 STOP 檔叫佢平倉停機，下次更新再停。
# 由 update.sh（root）同 setup.sh 叫。冇 ANTHROPIC_API_KEY 就唔開。
set -uo pipefail
U="$1"; H="$2"; REPO="$H/20260918"
KNOWN=" HSI SPY QQQ DIA TLT HYG GLD USO EEM EFA IWM EWJ FXI EWT INDA EZU EWG EWU EWZ EWC "     # 同 hsi_ai_trader/markets.py SPECS 一致
REAL=$(grep -oE '^LONGFEI_REAL_PRODUCTS=.*' "$REPO/gcp_ib/vm_futu/settings.env" | cut -d= -f2 | tr ',' ' ' | tr 'a-z' 'A-Z')
EXTRA=$(grep -oE '^LONGFEI_EXTRA_PRODUCTS=.*' "$REPO/gcp_ib/vm_futu/settings.env" | cut -d= -f2 | tr ',' ' ' | tr 'a-z' 'A-Z')
grep -q '^ANTHROPIC_API_KEY=sk-ant-' "$H/zhuge/env" || { REAL=""; EXTRA=""; }
# [R215] 模擬程式：LONGFEI_EXTRA_PRODUCTS 新加嘅產品自動開（唔使再人手跑 setup.sh）；拎走嘅、冇倉先停
for P in $EXTRA; do
  echo "$KNOWN" | grep -q " $P " || { echo "唔識嘅產品 $P，跳過"; continue; }
  D="$H/zhuge/ai_trader_$P"
  [ -d "$D" ] || { mkdir -p "$D" && chown "$U" "$D" && chmod 700 "$D"; }
  systemctl is-active -q "zhuge-longfei@$P.service" || { systemctl enable --now "zhuge-longfei@$P.service"; echo "已開模擬 $P"; }
done
if [ -n "$EXTRA" ]; then
  for u in $(systemctl list-units --all --plain --no-legend 'zhuge-longfei@*.service' | awk '{print $1}'); do
    P=${u#zhuge-longfei@}; P=${P%.service}
    echo " $EXTRA " | grep -q " $P " && continue
    QTY=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('qty') or 0)" "$H/zhuge/ai_trader_$P/heartbeat" 2>/dev/null || echo 0)
    [ "$QTY" = "0" ] && { systemctl disable --now "$u"; echo "已停模擬 $P（唔喺 LONGFEI_EXTRA_PRODUCTS）"; }
  done
fi
for P in $REAL; do
  echo "$KNOWN" | grep -q " $P " || { echo "唔識嘅產品 $P，跳過"; continue; }
  D="$H/zhuge/ai_trader_real_$P"
  [ -d "$D" ] || { mkdir -p "$D" && chown "$U" "$D" && chmod 700 "$D"; }
  if systemctl is-active -q "zhuge-longfei-real@$P.service"; then
    systemctl restart "zhuge-longfei-real@$P.service"
  else
    systemctl enable --now "zhuge-longfei-real@$P.service"; echo "已開真倉 $P"
  fi
done
for u in $(systemctl list-units --all --plain --no-legend 'zhuge-longfei-real@*.service' | awk '{print $1}'); do
  P=${u#zhuge-longfei-real@}; P=${P%.service}
  echo " $REAL " | grep -q " $P " && continue
  D="$H/zhuge/ai_trader_real_$P"
  QTY=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('qty') or 0)" "$D/heartbeat" 2>/dev/null || echo 0)
  if systemctl is-active -q "$u" && [ "$QTY" != "0" ]; then
    [ -f "$D/STOP" ] || { echo "units: $P 已唔喺 LONGFEI_REAL_PRODUCTS，平倉停機 $(date -u +%F' '%T)" > "$D/STOP"; chown "$U" "$D/STOP"; }
    echo "真倉 $P 仲有 $QTY 倉：已放 STOP 叫佢平倉，下次更新先停"
  else
    systemctl disable --now "$u"; echo "已停真倉 $P（唔喺 LONGFEI_REAL_PRODUCTS）"
  fi
done
