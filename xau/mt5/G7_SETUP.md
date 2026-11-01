# 934 H1 回調真倉：上線步驟（R361）

## 1. 部署（總指揮做，使用者批）
1. PR merge 之後，總指揮跑 `gcp_agent.py --profile xausig deploy`，先做 dry-run，再由使用者批准 `--yes`。部署完 SIG_G7_LIVE 仍然係 0，即係唔會落單。
2. 開關：總指揮跑 `gcp_agent.py --profile xausig env set SIG_G7_LIVE=1`，先做 dry-run，再由使用者批准 `--yes`。其餘 env 用預設值：0.05 手、日蝕 5000 HKD、同戶口合共最多 3 張倉。

## 2. MT5（使用者喺 …69 做）
1. 喺 …69 開多一張 **XAUUSD** 圖，唔好用 931、933 嗰兩張。
2. 拖 TianfuExecutor **v0.41** 落去，設定：
   - `InpMagic=934`
   - `InpUrl=` zhuge-xau-sig 嘅網址（同 931 一樣）
   - `InpDryRun=false`
   - `InpBotMagics` 已經包咗 931 至 935，唔使改
3. 開咗之後，網頁 `?format=json` 嘅 `g7_live.account.received_utc` 應該喺 3 分鐘以內更新。

## 3. 點運作
- 每個 H1 收盤只判斷一次。H4 EMA50 向上、而 H1 RSI(14) 啱啱跌穿 35 → 買；H4 EMA50 向下、而 H1 RSI 啱啱升穿 65 → 沽。
- H1 收盤後 15 分鐘內用市價入場，指令帶 px／dev，EA v0.41 會擋住滑價超過 1.5 美元嘅單。
- 止損係 1.5 × H1 ATR(14)，止賺係 2R，兩樣都放喺伺服器端。開倉 72 小時仲未完，服務就發 `close|all|magic=934` 平倉。
- 以下情況唔開新倉：control 唔係 RUN、風控階梯到咗 Ⓑ 或 Ⓓ、EA 未准交易、數據公佈封鎖期、934 今日已蝕 ≥ 5000 HKD、同戶口已經有 3 張倉、931 停咗寫 K 線存檔（數據唔新鮮）。

## 4. 建議停條件（要使用者批）
以下任何一項觸發，巡檢會通知總指揮「建議停」，停唔停由使用者決定：
- 934 累計虧損去到 −8R 或以上；
- 連輸 8 張或以上；
- 做滿 20 張之後 PF < 0.9。
