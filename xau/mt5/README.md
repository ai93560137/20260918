# 🌌 天覆陣執行器 TianfuExecutor — 安裝步驟（影子階段：只做資料源，唔落單）

線上 `RiskManager_HKD_Zhuge_V23` 照舊掛住、照舊指住 zhuge-risk-manager，**唔使改**。
TianfuExecutor 另開一個 XAUUSD 圖表掛上去，`InpDryRun=true`，每 60 秒把 K 線同戶口數據直接送去 zhuge-xau。

## 1. 編譯
1. MT5 → 工具 → MetaQuotes 語言編輯器（或按 F4）。
2. 檔案 → 開啟 → 把 `xau/mt5/TianfuExecutor.mq5` 複製到 `MQL5/Experts/`（MetaEditor 左邊「導航」對 Experts 右鍵 → 在資料夾中開啟）。
3. 開啟檔案，按 **F7** 編譯。工具列「錯誤」分頁要係 0 errors（warnings 可以）。編譯唔過請把錯誤行數同訊息貼畀總指揮。

## 2. 允許 WebRequest
MT5 → 工具 → 選項 → **EA 交易** → 勾「允許 WebRequest 至以下 URL」→ 加：
```
https://zhuge-xau-1056099871997.europe-west1.run.app
```
（唔好刪舊服務嗰條，V23 仲用緊。）

## 3. 掛圖
1. 開一個**新嘅 XAUUSD 圖表**（任何週期都得，建議 M1）。V23 嗰個圖表唔好動。
2. 導航 → EA 交易 → TianfuExecutor 拖入新圖表。
3. 參數：

| 參數 | 填 |
|---|---|
| `InpUrl` | `https://zhuge-xau-1056099871997.europe-west1.run.app/`（結尾有 `/`） |
| `InpToken` | zhuge-xau 嘅 `WEBHOOK_SECRET_TOKEN`（你喺控制台填嘅嗰個；唔好用舊服務嘅） |
| `InpMagic` | `921`（V23 係 920，一定要唔同） |
| `InpIntervalSec` | `60` |
| `InpTimeoutMs` | `15000` |
| **`InpDryRun`** | **`true`**（影子階段一定要 true：OnTimer 收到指令都唔會入 Execute，0 落單路徑） |
| `InpMaxLots` | `0.10` |

4. 「一般」分頁：勾「允許算法交易」（EA 要跑 OnTimer；dry-run 唔會落單）。確定。
   **真倉／demo 落單仲要三個開關全開**：工具列「Algo Trading」綠色、EA 屬性「一般」分頁「允許算法交易」有勾、戶口准 EA 交易。任何一個關，落單回 `auto trading disabled by client`（10027）。v0.32 起心跳帶 `trade_allowed`，頁面「真倉狀態」會顯示邊個關住，EA 收到指令亦會先回報 `trade not allowed: …` 而唔送單。

## 3b. v0.33 起：回填歷史
EA 首個心跳會送最近 330 根 M1＋60 根 M15（「專家」分頁印「📚 回填歷史」），服務即刻夠 20 根 M15 決策；之後服務回 `need_history:true`（例如歷史被重置）EA 就再送一次。

## 4. 確認
- 圖表右上角 EA 名有笑臉；「專家」日誌每分鐘一行 `WebRequest` 冇錯誤（code 200 唔會印；錯誤會印 ⚠️）。
- 約 2 分鐘後打開 `https://zhuge-xau-1056099871997.europe-west1.run.app/`：M1 根數開始增加；30 根 M1＋20 根 M15 後 Claude 先開始決策（M15 要約 5 小時先夠 20 根）。
- 日誌出現 `⚠️ WebRequest 失敗 code=403` → InpToken 唔啱；`code=-1` → 網址未加入 WebRequest 白名單。

## 5. 安全
- `InpDryRun=true` 時：OnTimer 只送心跳；收到 `cmd_text` 會印「🧪 [dry-run] 收到指令但唔執行」然後 return，**唔會**入 `Execute()`，冇任何 `OrderSend`／`PositionClose` 路徑。而且 zhuge-xau `XAU_EXECUTE=0` 時 `cmd_text` 永遠空。
- 心跳只讀：`AccountInfo*`、`PositionGet*`（只數 magic 921）、`CopyRates`、`HistoryDeals`。
- 轉真倉（階段 C）前要：先喺 **demo 戶口** `InpDryRun=false` 測指令執行；使用者講先改。
