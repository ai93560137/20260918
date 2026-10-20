# 🌌 天覆陣 階段 B：MT5 落盤測試計劃（2026-10-20，使用者：「天覆陣測試 MT5 落盤，隨時轉真倉」）

> 真倉仍然要使用者親口講「天覆陣轉真倉」先做。任何 `env set`／部署都經總指揮 dry-run＋使用者批准。

## 0. 先要補兩樣嘢（我開 PR，批咗先測）

| 缺口 | 做法 |
|---|---|
| **服務分唔到兩個 EA** | EA v0.3 心跳加 `account`（MT5 登入號）＋ `server`；服務加環境變數 `XAU_ACCOUNT`：只接受呢個登入號嘅心跳（數據＋指令），其他登入號回 `ignored`（唔入 K 線、唔入戶口快照、唔發指令）。留空＝全收（影子階段現狀）。 |
| **實倉模式冇真實持倉** | 而家 `XAU_EXECUTE=1` 時服務仍用紙上倉做判斷（開咗真倉之後 Claude 會以為空倉再開）。改為：實倉模式嘅持倉／止損／止賺由 EA 心跳 `positions[]`（只計 magic 921）嚟；日蝕用 EA 回報嘅 `daily_pnl`（自己 magic 今日已實現）＋浮動；累計用 EA 新欄位 `realized_total`（自己 magic 由 `InpLedgerStart` 起）＋浮動；最長持倉到時由服務排 `close`；止損止賺由伺服器端 SL／TP 執行（EA 開倉時已掛）。紙上模擬只喺影子模式。 |

兩個 EA 嘅權杖可以相同（分辨靠 `account`）。

## 1. 喺邊個戶口測
- **建議：UltimaMarkets demo 戶口**，另開一個 MT5 終端（portable 模式，唔同資料夾），掛 TianfuExecutor `InpDryRun=false`、`InpMagic=921`。
- 真倉戶口嗰個 EA 保持 `InpDryRun=true`；服務 `XAU_ACCOUNT=<demo 登入號>`，所以真戶口嘅心跳會被 `ignored`，真戶口 EA 就算收到指令都唔執行（dry-run 唔入 Execute）——雙重保險。
- 如果 demo 開唔到：真戶口 0.01 手測嘅風險＝每 US$1 金價 ≈ HK$7.8；止損 2–30 美元即每張最多蝕 HK$16–234，再加點差。測試清單第 7 項（日蝕 −6%）喺真戶口**唔做**（要蝕 HK$1,630）。

## 2. `XAU_EXECUTE=1` 嘅影響
- 服務只向 `XAU_ACCOUNT` 嗰個登入號嘅心跳回 `cmd_text`；其他登入號收到 `ignored`，冇指令。
- 真戶口 dry-run EA：即使收到 `cmd_text`，`OnTimer` 印「🧪 [dry-run] 收到指令但唔執行」就 return；`Execute()` 入面每個分支亦再查 `InpDryRun`。
- 指令 10 分鐘內冇 `cmd_ack` 就作廢；EA 用檔案記最近 40 個 id 去重，重啟都唔重複。

## 3. 測試清單（demo，`XAU_EXECUTE=1`、`XAU_ACCOUNT=demo`）
用 `control.json` `mode=PAUSE`（`set_by=user`）令 Claude 唔自己開倉，再用 GCS 檔 `xau/test_cmd.json` 排指令（只限 `XAU_TEST_CMDS=1`＋`XAU_EXECUTE=1`；唔使權杖，服務每個心跳讀一次，用過寫回 `consumed`＋`result`）：

```bash
# 例：第 1 項 open（sl／tp 按當時金價，止損距離 2–30 美元）
echo "{\"id\":\"t1\",\"ts\":$(date +%s),\"op\":\"open\",\"side\":\"BUY\",\"sl\":4105,\"tp\":4130}" > /tmp/t.json   # ts 必帶；超過 10 分鐘嘅檔唔排
python3 scripts/gcp_agent.py --profile xau put --any-prefix --object xau/test_cmd.json --file /tmp/t.json
# 其他：{"id":"t2","op":"open","side":"BUY","no_sl":true}（第 2 項）、{"id":"t3","op":"modify","sl":4108,"tp":4130}（第 3 項）、{"id":"t4","op":"close"}（第 4 項）
# 核實：GET ?format=json 嘅 pending_cmds（ack 後清空）／live_positions；logs --grep 'test_cmd\|指令回報'；gcp_agent cat --object xau/test_cmd.json 睇 result
```
（2026-10-20：天覆陣工作階段嘅權限分類器唔准佢讀服務權杖同寫 bucket，所以 `put` 由總指揮／使用者執行，天覆陣用 GET／logs 核實記錄。）

| # | 測 | 預期 | 睇邊度 |
|---|---|---|---|
| 1 | `open\|BUY\|0.01\|sl=…\|tp=…` | demo 開到 0.01 手，MT5 持倉有伺服器端 SL／TP，`cmd_ack ok=true ticket=…` | MT5 持倉、服務日誌、頁面「待執行指令」清空 |
| 2 | 冇 SL 嘅 open | EA 拒絕 `no SL`，冇單 | EA 日誌、ack ok=false |
| 3 | `modify\|all\|sl=…` | MT5 止損改咗 | MT5 持倉 |
| 4 | `close\|all` | 平倉；下一個心跳 `positions=[]`，服務持倉清空 | MT5、頁面 |
| 5 | 去重：同一 id 心跳重送兩次 | 只執行一次 | EA 日誌「Seen」 |
| 6 | 斷線重連：MT5 關 3 分鐘再開，期間排一條 open | 指令 10 分鐘內仍執行一次；超過 10 分鐘作廢 | 服務 `pending_cmds` |
| 7 | 緊急停機：`control.json mode=STOP set_by=user` | 下一根 M1 服務排 `close\|all`，EA 平倉；之後唔問 Claude | MT5、頁面模式 |
| 8 | 日蝕 −6%（**只喺 demo**）：開倉後把 `principal_hkd` 暫時改細令 −6% 觸發 | 自動 STOP＋`close\|all`＋Telegram；換日自動 RUN | 頁面、Telegram |
| 9 | 最長持倉：`XAU_MAX_HOLD_MIN=5` 暫時 | 5 分鐘後服務排 `close\|all` | 頁面 |
| 10 | 真戶口 dry-run EA 同時掛住 | 真戶口心跳 `ignored`、冇指令、冇單 | 服務日誌、MT5 真戶口 |

全部通過＋Claude 自己（`mode=RUN`）喺 demo 開／平過 ≥ 3 張單，先算階段 B 完成。

## 4. 轉真倉（使用者親口講先做）
0. **前置條件（10-20 總指揮）**：(a) 確認 LTC（Local Trade Copier 跟單主帳）**仍然停用**，或已按 magic 921 排除——10-20 使用者已 unload LTC，轉真倉當日要再確認；(b) 確認真倉戶口號碼——使用者有多過一個真錢戶口，用邊個未最終確認；號碼係私人資料，見 GCS `xau/control.json`（`live_account`，由總指揮寫入），唔寫入公開 repo；`XAU_ACCOUNT` 要同佢一致。
1. `--profile xau env set XAU_ACCOUNT=<真戶口登入號> XAU_EXECUTE=1 XAU_LOTS=0.01`（總指揮 dry-run → 使用者批 → `--yes`）。
2. 真戶口 EA 參數 `InpDryRun=false`（使用者喺 MT5 改）；demo EA 卸載或 `InpDryRun=true`。
3. 確認頁面「真倉」區顯示持倉來源係 EA、`XAU_ACCOUNT` 正確。
4. 第一張單用 0.01 手，使用者睇住。

## 5. 回退（任何一步出事）
- 最快：真戶口 EA `InpDryRun=true`（MT5 參數，幾秒）；或者 MT5 直接卸載 EA。
- 服務：`--profile xau env set XAU_EXECUTE=0`（dry-run → 批 → `--yes`），或 `rollback --to <上一修訂>`。
- 緊急平倉：`control.json mode=STOP set_by=user`（下一根 M1 排 `close|all`）；MT5 人手平倉亦可，服務下一個心跳會見到 `positions=[]`。
