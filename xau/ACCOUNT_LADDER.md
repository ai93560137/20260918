# 戶口總階梯（多產品共用一個 MT5 戶口）— 設計稿 2026-10-21

> 總指揮 10-21 要求。背景：天覆陣「一個產品一個服務」（zhuge-xau、zhuge-eurusd…）共用 demo 928861／真倉戶口，
> 每個服務嘅風控階梯（`rules.ladder`）而家只計**自己 magic** 嘅日蝕／累計，兩個服務各蝕 −5% 都唔會停，但戶口已蝕 −10%。

## 目標
- 日蝕 Ⓑ −20%／Ⓓ 停用（10-22 使用者放寬；原 −3%／−6%）、累計 25%、本金、高水位：以「天覆陣所有產品合計」計，唔計使用者手動單同其他 EA（維持使用者 10-20 規則）。
- 任何一個服務觸發 STOP，所有天覆陣產品都要平倉停機；PAUSE 同理。
- 唔引入服務之間互相讀寫 GCS（各服務只寫自己前綴，`storage._guard`），唔加新基礎設施。

## 方案 A（建議）：由 EA 計合計，每個服務獨立得出同一個數
每張圖表嘅 EA 都睇到整個戶口（`PositionsTotal()`、`HistorySelect`），所以每個 EA 都可以計「所有天覆陣 magic」嘅合計：
- EA v0.35 新參數 `InpBotMagics = "921,922,923,924,925"`（天覆陣所有產品嘅 magic；V23 920 唔計）。
- 心跳加三個欄位（戶口貨幣）：`bots_daily_pnl`（呢組 magic 今日已實現）、`bots_floating`（呢組 magic 浮動）、`bots_realized_total`（呢組 magic 自 `InpLedgerStart` 起已實現）。現有 `daily_pnl`／`floating`／`realized_total`（自己 magic）照送，頁面仍顯示「本產品」。
- 服務 `risk_ladder`：心跳有 `bots_*` 就用佢計日蝕、累計、高水位（本金 `principal_hkd` 係整個戶口，各服務 control.json 填同一個數）；冇就退回自己 magic（舊 EA 兼容）。
- 觸發：每個服務喺自己下一根 M1 各自判斷 → 同一組數 → 同時 STOP／PAUSE，各自排 `close|all|magic=<自己>`，EA 各自平自己嘅單。時差最多 1 分鐘（各自 M1 收盤）。
- 自動重開：各自 `auto_reset_day`，同一日。
- 使用者手動 PAUSE／STOP 仍然係每個服務自己嘅 control.json（可以只停一個產品）。

優點：零跨服務耦合、數據來源一致（同一個終端同一刻嘅帳戶）、舊 EA 兼容。
缺點：兩個 EA 要喺同一個 MT5 終端（而家係），magic 清單要兩邊一致（放 EA 參數，預設寫晒 921–925）。

## 方案 B：GCS 匯總檔
總指揮或一個排程每分鐘讀各服務 `state.json` 嘅 `ladder.daily_pnl_hkd` 合計，寫 `ops/ladder_total.json`，各服務讀佢。
缺點：多一個寫入者同時間差、排程停咗就冇總閘、要放寬 `_guard` 讀跨前綴。唔建議。

## 改動清單（方案 A）
1. EA v0.35：`InpBotMagics`、`IsBotMagic()`、`BotsRealizedSince()`、心跳三個新欄位；`Reject`／`IsMine` 唔變（仍只管自己 magic）。
2. `xau/main.py` `handle_heartbeat`：讀 `bots_daily_pnl`／`bots_floating`／`bots_realized_total` 入 `account.json`；`risk_ladder` 優先用 `bots_*`；`build_status` 加 `account_ladder` 區塊；頁面「模式同風控」顯示「戶口合計（天覆陣全部產品）」同「本產品」兩行。
3. 測試：有 `bots_*` → 用合計；冇 → 用自己；合計 −6% 觸發 STOP 排 close。
4. 文件：README 風控一節、RISK_LADDER §6c 補「多產品合計」（總指揮擁有，由佢改）。
5. 部署：兩個服務都要上新版；EA v0.35 兩張圖表都換。

## 轉真倉前置（補充 TEST_PLAN §4）
- 戶口總階梯已上線並喺 demo 驗證：兩個產品各開一張，縮本金令合計 −6% → 兩個服務同時 STOP、兩張單都平。
