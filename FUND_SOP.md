# FUND_SOP.md — 基金每日流程：現況盤點與缺口（SOP 顧問報告，2026-10-13）

> 問題：把現有的腳本、排程、工作階段當成一間小型基金，離「每日流程」還差哪幾塊？
> 方法：盤點預設分支 28 個 GitHub workflow、22 個 Claude Routines、Cloud Run 服務、本機與 VM 的推送腳本，
> 按基金一天的七個環節對照。只盤點、不評價策略本身。缺口按「風險」排序，每項附建議負責人與工作量。

## 一、現況盤點

### 1.1 人員（工作階段）

> 2026-10-14 起各陣換新工作階段；以下為新 id，**最新以 `handoff/SESSIONS.md` 為準**（2026-10-14 05:10 全部換完；HTF 策略指南、股票套利、指數套利、外匯數據測試已停用唔換）。

| 角色 | 工作階段 | 分支 | 職責 |
|---|---|---|---|
| 總指揮（風控／營運） | `session_012CwdLPmAQvC91GZs5Jg9XA` | `claude/beautiful-hypatia-8qrgjj` | 富途實倉監控、按陣配對、四陣風險通報、成交通報、對沖狀態通報 |
| ☁️ 雲垂陣（期權 PM） | `session_01RkzmKXKixbBkCNqEjhubCK` | `claude/dazzling-curie-f3xzb8` | HSI／MES 月跨式＋Δ 對沖；每日掃描、16:00／20:30 對沖指令、收市總結 |
| 🌬️ 風揚陣（波幅／週期權 PM） | `session_01X2Qv7MgCQxbyyEyGVzivWC` | `claude/eager-*`／預設分支頁面 | HAR 波幅預測、高低位訊號、方向一每週勒式 |
| 🐍 蛇蟠陣（趨勢 PM） | `session_01B4y7p7QzrJwCXEmDDZCx9M` | `claude/gifted-carson-v2tvhw` | 3 日通道、紙上前向、每日新高／VCP 名單、全市場數據 |
| 地載陣（日內 PM） | `session_01UxZXWN28xveAEbzggo49AR` | — | RSI 逆市四條紙上策略（R138／141／143／145） |
| 🐤 金絲雀（風險預報） | `session_01AqAysUfBVsCKimicXrwwKZ` | `claude/canary-playbook-final-3um9lp` | 每日燈色表、後驗紀錄 |
| 鳥翔／HTF（個股 PM） | `session_018BXPn6zbpuMedYBTga6wp1` | `claude/stock-research-k9nzau` | 月底九國名單、HTF 每日訊號網頁 |
| 外匯 VM 採集 | `session_01YcJyu1yjZaFQTtY37WuQYH` | `claude/dazzling-curie-f3xzb8` | VM 上 L1 EURUSD 報價、6E 期權快照、ZQ 每日結算採集（使用者 10-14：繼續）；外匯研究線工作階段已停 |
| 高息紙上 | `session_01GZ86daPoYtbG3bQk5svCx3` | gifted-carson `paper/` | 月度高息＋備兌模擬盤 |
| 預設分支（登記簿／流水線） | `session_012caA3uVCQjRHHryN5HnMrn` | `claude/gcp-trading-v12-rewrite-bz75t2` | `IDEAS.md`、評分卡、偏離監控、Cloud Run 部署 |

### 1.2 自動化（執行者 × 時間）

**Cloud Run `zhuge-risk-manager`**：事件驅動，MT5 EA 每分鐘心跳；電閘、送單、戶口快照、R171 已實現帳本、R172 富途成交／盈虧入庫、17 個網頁（各頁數據更新時間見 §1.4）。
**本機 `gcp_ib/auto_risk.py`**（R172）：每 15 分鐘推富途持倉與風險 `futu/risk/latest.json`；03:05／05:30／16:35 推成交 → Cloud Run 寫 `futu/deals/<日>.json`。
**VM ib-data**：IB 報價快照（外匯 L1、6E 期權），只讀、不下單。
**GitHub Actions（預設分支）**與 **Claude Routines** 按香港時間排成一天（2026-10-13 更新：總指揮 8 次叫醒改為 4 次新開工作階段＋4 次 Actions；新增晨會簡報、每日對帳）：

| 時段（HKT） | 誰 | 做什麼 |
|---|---|---|
| 05:30–06:30 | Actions `fetch_equities`（美）、`es_daily_push`、`news_8k`、`bond_daily`、`fetch_stock_data`（港） | 美股收市後數據、債市快報 |
| 06:30 | Actions `canary_daily` → TG | 金絲雀燈色表＋總結 |
| 07:07 | Routine 金絲雀 | 核對 canary workflow 跑對沒有 |
| 07:53 | Actions `hsi_range_report` → TG | 恒指開市前波幅／高低位預測 |
| 08:17 | Actions `external_data_daily` | 外部來源彙整＋抽樣 QC |
| 08:30 | Actions `morning_brief` → TG | 晨會簡報（風控、金絲雀、昨日損益、對帳、偏離、今日事件、今日要做；全文 GCS `ops/brief/`） |
| 09:15 | Actions `daily_topdown` → TG | 三地 200 日線＋新高名單、VCP |
| 09:40／10:10／10:30 | Actions `fx_l1_forward`、`xau_long_forward`、`fx_fomc_forward` | 外匯陣三個紙上前向記錄 |
| 09:45 | Routine 四陣風險通報 v2（每次新開工作階段） | 四陣持倉風險通報（第 1 次；狀態 GCS `ops/risk_notify_state.json`） |
| 每 15 分 | Actions `hsi_touch_alert`、`hsi_peak_signal` → TG | 蛇蟠觸軌、高低位訊號 |
| 12:00 | Routine 蛇蟠 | 午間通道更新＋TG |
| 12:07 | Actions `hsi_range_report` → TG | 午市收市檢討 |
| 12:45 | Routine 四陣風險通報 v2 | 風險通報（第 2 次） |
| 14:30 | Routine 雲垂 | HSI＋MES 每日掃描＋日報 |
| 14:35、15:55 | Actions `ops_notify` → TG | 對沖狀態一行（給雲垂 14:42 報告、16:00 對沖用）；同時 commit `ops/hedge_status_latest.txt` 畀雲垂 git 讀 |
| 16:00 | Routine 雲垂 | HSI Δ 對沖指令＋止損線 |
| 16:37 | Actions `hsi_range_report` → TG | 日市收市檢討 |
| 16:40 | Routine 雲垂 | 觸發 `fetch-quotes` 存正式收盤 |
| 16:35 | 本機 auto_risk | 推日盤成交 → `futu/deals/<日>.json` |
| 16:45 | Routine 四陣風險通報 v2；Routine 蛇蟠 | 收市摘要給四陣（成交由 17:10 另發）；通道更新＋前向結算＋TG |
| 17:10 | Actions `ops_notify` → TG | 富途成交紀錄通報（日盤）；commit `ops/deals_latest.json` 畀雲垂 |
| 17:20 | Actions `ops_daily_books`（總指揮 R173） | 每日對帳表 `research/reconcile/<日>.md`、損益帳 GCS `ops/books/pnl_daily.csv`、風控階梯（Ⓒ／Ⓓ 直接 TG） |
| 17:13 | Routine 鳥翔 | 觸發 HTF 每日訊號 workflow（約 50 分鐘） |
| 20:30／21:30（夏／冬令） | Actions `es_range_report` → TG | ES 開市前／收市報告（六組 cron 處理夏冬令） |
| 21:45 | Routine 四陣風險通報 v2 | 風險通報（第 4 次） |
| 03:13 | Actions `hsi_range_report` → TG | 全日收市檢討 |
| 03:30（倫敦 20:30） | Routine 雲垂 | MES 檢查點＋對沖指令 |
| 03:05 | 本機 auto_risk | 推夜盤成交 |
| 03:40 | Actions `ops_notify` → TG | 富途成交紀錄通報（夜盤，讀今日＋前一日） |
| 04:15（倫敦 21:15） | Routine 雲垂 | 每日總結＋自檢清單 |
| 每 4 小時 | Actions `pelosi_tracker` → TG | 佩洛西申報 |
| 週六 10:17／10:47 | Actions `hkex_option_iv`、`us_futures_daily` | 港交所期權 IV、美期日線 |
| 週日 03:37 | Actions `screener_scorecard` | 篩選器評分卡＋偏離監控（WIF 免金鑰讀 GCS） |
| 週日 11:00 | Actions `insider_research` | 內部人回測重跑 |
| 週五 16:30 後 | 風揚陣（人） | 方向一開新一週勒式；到期日 17:00 Routine 結算 |
| 月底 | Routine 鳥翔 | 九國月底名單三步 |
| 手動 | `gcp_deploy`、`vcp_fullmarket`、`pead_backtest`、`dukascopy_m15`、`hkex_inline`、`canary_broadcast`、`research_hsi_history` | 部署、大型回測、資料補抓 |

### 1.4 網頁數據更新時間（tnt-hk.com，香港時間，平日；2026-10-13 總指揮）

頁面隨時開到，每次開都讀最新一份；下表係「新數據幾時到」。

| 頁面 | 新數據幾時到 | 來源 |
|---|---|---|
| 🌬️ 風揚陣恆指波幅 | 交易時段每幾分鐘；報告 07:53 開市前、12:07 午市、16:37 日市、03:13 全日 | 富途行情推送＋Actions `hsi_range_report` |
| 🇺🇸 風揚陣ES／NQ 波幅 | 交易時段每幾分鐘；報告約 06:07 開市前、21:37 隔夜檢討、04:07 RTH 收市、05:07 全日（美國夏令；冬令遲 1 小時） | 同上＋`es_range_report` |
| 🐍 蛇蟠陣 | 12:00、16:45 通道更新 | 蛇蟠 Routine |
| ⛰️ 地載陣 | 交易時段即時；頁面每 60 秒重載 | 富途 1 分 K |
| ☁️ 雲垂陣 | 14:30 掃描、16:00 對沖、04:15 每日總結；頁面每 2 分鐘重載 | 雲垂 Routine（`yunchui_public.json`） |
| 🐤 金絲雀 | 每日 06:30；頁面每 10 分鐘重載 | Actions `canary_daily` |
| 📈 鳥翔 HTF 掛單 | 每日約 18:05（17:13 觸發，跑約 50 分鐘）；頁面每 10 分鐘重載 | 鳥翔 Routine＋Actions `htf_daily` |
| 🧭 策略總表 | 富途實倉每 15 分鐘；頁面每 60 秒重載 | 本機 auto_risk |
| 📊 基金報告 | 每日 05:30（03:05、16:35 補成交） | 本機 auto_risk（`futu_pnl`） |
| 📄 投資人日誌、⚙️ 控制台 | 即時（MT5 每分鐘心跳、決策日誌） | Cloud Run |
| 🎛️ 關卡開關、🧾 送單參數、✅ 錦囊九十筆 | 使用者手動改先變 | 人手 |
| 🗒️ 錦囊執行單、🏠 首頁 | 固定內容 | — |

### 1.3 已具備的「基金部門」

| 部門 | 已有 | 備註 |
|---|---|---|
| 數據 | 三地日線＋第二來源比對、CME 期貨、港交所 IV、債市、外部 QC、全市場備份到 Release | 等權／PIT 成分股名單齊 |
| 研究 | `IDEAS.md` 100 條登記簿、各陣回測文件、評分卡、預先登記慣例 | 本週剛建立 |
| 投資組合 | 五個陣各有 SOP 文件、持倉在 `POSITIONS.md` | 實倉三個陣＋人手 |
| 風控 | 四次／日風險通報、Δ 通報、止損線使用率、硬止損 HK$750k 壓力測試、偏離監控燈號；`RISK_LADDER.md` 四層階梯（R173） | 仍只通報；Ⓒ／Ⓓ 直接 TG 提示使用者，落單人手 |
| 交易／對帳 | 富途成交 16:35／03:05 入庫、17:10／03:40 通報（Actions）；MT5 已實現帳本（R171）；每日 17:20 三方對帳（R173） | 2026-10-13 起才有 |
| 營運 | `gcp_agent.py` 部署／回滾、WIF 免金鑰 Actions、session-start hook | — |
| 投資人報告 | 八陣圖策略書 `factsheet.html`、各網頁 | 沒有 NAV 時序 |

## 二、缺口（按風險排序）

### 缺口 1｜風控只有「通報」，沒有「階梯」　風險：高

現況：硬止損 HK$750k、各策略止損線、按金緩衝、偏離燈號全部算得出來，也會發 Telegram，但**沒有一份文件寫明每個燈號亮起時誰在多少分鐤內做什麼**。🟡 是減半還是只觀察？🔴 是誰平倉、用什麼價、要不要等使用者確認？按金緩衝跌到多少先減哪一個陣？目前答案散在各陣 SOP 與 Routine prompt 裡，互不一致。

建議：一頁 `RISK_LADDER.md`（總指揮擁有）。四層：Ⓐ 觀察（通報）、Ⓑ 停開新倉、Ⓒ 減半、Ⓓ 全平。每層列觸發條件（按金緩衝、硬止損距離、偏離燈、單陣止損線使用率）、執行者（哪個陣／使用者）、時限、可用價（限價中間價／市價）、事後登記（`POSITIONS.md`、`IDEAS.md` 狀態）。各陣 SOP 引用它，不另寫。
**要使用者決定**：Ⓒ、Ⓓ 是否允許由 Claude 直接提示使用者「現在平」而不等問答，以及夜盤無人時的規則。
工作量：半天文件＋各陣 SOP 加一行引用。

### 缺口 2｜十幾條 Telegram 流，沒有一份晨會簡報　風險：中高

現況：每天至少 12 個獨立 TG 來源（金絲雀、恒指預測、topdown、蛇蟠、雲垂日報、ES 報告、佩洛西、觸軌……）。使用者是唯一讀者，資訊量已超過一個人早上能消化的。基金的做法是晨會：一頁，先風險、再持倉、再今日事件、再各 PM 今日打算。

建議：Actions `morning_brief.yml`，08:30 HKT，只讀不算：讀 `futu/risk/latest.json`（權益、緩衝、Δ、止損線使用率）、`POSITIONS.md`（持倉與到期日）、`DIVERGENCE.md` 燈號、金絲雀今日燈色、當日事件（缺口 4）、各陣昨日 TG 的第一行。輸出一則 TG＋`analysis/brief/<日>.md`。其他 TG 流不動，但晨會是「只看一則也夠」的那則。
工作量：1 天。負責人：總指揮（內容）、預設分支（腳本）。

### 缺口 3｜持倉對帳是半自動　風險：中高

現況：真相有三份——富途快照（自動）、`POSITIONS.md`（人手登記）、各陣 journal／position.json（各自維護）。總指揮用 `FUTU_TEAM_RULES` 配對並把「未配對」發 TG，但沒有一份每日對帳表留底；蛇蟠陣 10-12 反手就出現過快照與登記不一致要靠「你問我、我答你」補。

建議：總指揮 16:45 Routine 已在讀快照，加一步產出 `research/reconcile/<日>.md`：每個合約三方數字並列（快照 qty／`POSITIONS.md`／各陣 journal），不一致標 ⚠ 並列原因欄待填；連續兩日未解釋即升級為缺口 1 的 Ⓑ。
工作量：半天。負責人：總指揮。

### 缺口 4｜沒有事件日曆　風險：中

現況：只有 XAUUSD 有 ForexFactory 新聞鎖（High／Medium）。恒指與 ES 期權是賣方部位，最怕事件週；風揚陣文件自己寫「事件週改鐵鷹或減半——無數據不能測」。FOMC、CPI、NFP、港股假期、期指結算日、指數調整、MSCI 季檢、美股財報季，沒有一處集中。

建議：`calendar/events.csv`（date, time_hkt, market, event, impact, affects）由 Actions 每週一從 ForexFactory 快取、港交所假期表（已有 `futu/calendar/HK.json`）、CME 假期、`universes/calendars/` 合成；晨會與各陣 16:00／週五開倉前讀它。風揚陣的「事件週規則」就有數據可以預先登記。
工作量：1 天。負責人：預設分支（腳本）、風揚陣（事件週規則）。

### 缺口 5｜沒有逐日損益帳（NAV 時序）　風險：中

現況：富途 `futu/pnl/latest.json` 有按合約的已實現（R172，從 2026-09-01 起）、MT5 有 R171 帳本，但沒有**每日一列、按陣拆分**的時序：日期、各陣已實現、未實現、手續費、總權益、對硬止損距離。偏離監控現在靠各陣手填 CSV；月報、歸因、夏普都做不出來。

建議：總指揮 16:45 讀 `futu/pnl/latest.json`＋`futu/risk/latest.json`＋MT5 帳本，追加一列到 `research/pnl/daily.csv`（陣別用 `FUTU_TEAM_RULES` 配對）。月底 Actions 由它產月報（缺口 9）。`ledger_yunchui.csv` 等手填表改為由此派生。
工作量：1 天。負責人：總指揮。

### 缺口 6｜流水線本身沒有人看　風險：中

現況：28 個 workflow＋22 個 Routine，失敗只在 GitHub 頁面或 Routine 的 last_run 看得到。只有金絲雀有「核對自己的 workflow 跑對沒有」的 Routine；其餘靜默失敗一週才會被發現（本週就發現 `gcp_deploy.yml` 引用的 WIF secrets 從未設過）。

建議：Actions `ops_heartbeat.yml`，每日 07:30 HKT：列昨日所有 schedule 觸發的 run 結論（GitHub API）、各數據檔新鮮度（`data/equities` 最後日期、`futu/risk/latest.json` run_hkt、`levels.json` fetched_at、`canary/tg_daily.txt` 日期），一則 TG 只列紅項；全綠發一行。Routine 的 last_run 由總指揮每週用 `list_triggers` 掃一次。
工作量：半天。負責人：預設分支。

### 缺口 7｜研究治理有登記簿，缺定期檢討會　風險：中低

現況：`IDEAS.md`、評分卡、偏離監控本週建立，週日自動更新並 commit，但沒有人被指派「每週讀一次並改狀態」。基金的投委會是固定時間、固定議程。

建議：`screener_scorecard.yml` 跑完加一步：比較本週與上週 `IDEAS.md` 狀態變化、評分卡判決變化、偏離燈變化，發一則「週報」TG；週一總指揮或預設分支 Routine 讀它，把需要改狀態的列改掉。每季一次「棄用清單重讀」，防止舊想法換名字回來。
工作量：半天。負責人：預設分支。

### 缺口 8｜人手交易沒有規則層　風險：中低

現況：`POSITIONS.md` 有兩列「使用者人手」（EW P7,750、MHI 即日），規則欄寫「人手，冇固定規則」。基金裡 PM 的自主交易也要有限額（名義、每日最大虧損）與事後登記。

建議：在缺口 1 的階梯裡給「人手」一個獨立額度（例如名義 ≤ NAV 50%、單日虧損 ≤ 2% 即停當日），R172 成交入庫後自動對照；超額只通報，不干預。
工作量：寫進 `RISK_LADDER.md` 即可。**要使用者決定額度。**

### 缺口 9｜沒有月報　風險：低

現況：策略書 `factsheet.html` 是靜態說明，無 NAV、無月度表現、無歸因。

建議：缺口 5 的 `daily.csv` 建立一個月後，Actions 月初產 `reports/<YYYY-MM>.md`：NAV 曲線、各陣貢獻、最大回撤、對回測偏離、本月 `IDEAS.md` 變動、下月到期事件。
工作量：1 天，等缺口 5。

### 缺口 10｜營運衛生　風險：低但便宜

- **金鑰輪換**：webhooktrade API key 曾公開（`DEPLOY_20260920.md`）；服務帳戶金鑰、Telegram token 沒有輪換日期。建議每季一次，記在 `AGENTIC.md`。
- **備援**：GCS 狀態（電閘、加單、帳本）是否開了物件版本控制未確認；repo 是程式備援但不是狀態備援。建議開 versioning 並每季做一次「從 bucket 還原到新專案」演練。**要使用者在 GCP 做。**
- **時區**：ES 報告用六組 cron 處理夏冬令，雲垂 Routine 用倫敦時間，其他用 HKT；11 月初美國冬令切換是每年的風險點。建議 `ops_heartbeat` 在切換週前後加一行提醒。
- **文件分散**：各陣 SOP 散在五個分支，入口只有 `CLAUDE.md`。本文件兼作索引；各陣在 1.1 表補自己 SOP 檔的路徑。

## 二之一、進度（2026-10-13 晚更新，避免重覆）

| 缺口 | 狀態 | 誰做的 | 在哪裡 |
|---|---|---|---|
| 1 風控階梯 | ✅ 初稿，使用者已同意 Ⓐ–Ⓓ、夜盤 ×1.5、Ⓒ／Ⓓ 直接 TG 提示 | 總指揮（R173） | `RISK_LADDER.md`、GCS `ops/books/ladder_state.json` |
| 2 晨會簡報 | ✅ 平日 08:30 HKT → Telegram（全文存 GCS `ops/brief/`，私人） | 預設分支 | `scripts/morning_brief.py`、`morning_brief.yml`；七段：風控、金絲雀、昨日損益、對帳、偏離、今日事件、今日要做 |
| 3 每日對帳表 | ✅ 每日 17:20 HKT | 總指揮（R173） | `scripts/daily_books.py`、`ops_daily_books.yml`、`research/reconcile/<日>.md` |
| 4 事件日曆 | ✅ 每日 07:00 HKT 合成；規則待風揚確認 | 預設分支（程式）＋風揚（`calendar/rules.json`） | `scripts/event_calendar.py`、`event_calendar.yml`、`calendar/events.csv`、`calendar/WEEK.md`；晨會簡報、週報讀它 |
| 5 逐日損益帳 | ✅ 每日一列按陣拆分（私人，不進 repo） | 總指揮（R173） | GCS `ops/books/pnl_daily.csv` |
| 6 流水線心跳 | ✅ 每日 07:30 HKT → Telegram（全綠一行、有紅只列紅項） | 預設分支 | `scripts/ops_heartbeat.py`、`ops_heartbeat.yml`；排程 workflow 應跑／實跑／失敗＋數據來源新鮮度＋富途數據 VM `futu-data-tw`（10-16 由香港 `futu-data` 搬台灣 asia-east1-b；Compute 狀態＋auto_risk／push_to_gcp／iv_push 輸出，10-15 加）；每日全文存 GCS `ops/heartbeat/<日>.txt`（週報數紅燈用）；Routine 的 last_run 仍由總指揮每週看 |
| 7 週報／檢討會 | ✅ 週日 09:00 HKT → Telegram＋[基金報告頁](https://tnt-hk.com/?view=fund_report) | 預設分支 | `scripts/ops_reports.py weekly`、`ops_reports.yml`；本週損益、IDEAS／評分卡／偏離對比 7 天前、對帳 ⚠、心跳紅燈、建議改狀態、下週事件 |
| 8 人手交易額度 | ✅ NAV 50%／單日虧損 2%，超額只通報 | 總指揮（R173） | `RISK_LADDER.md` |
| 9 月報 | ✅ 每月 1 日 09:30 HKT（首份有意義嘅係 2026-11-01 報 10 月，帳本由 10-13 起） | 預設分支 | `scripts/ops_reports.py monthly`；網頁公開版唔列權益絕對值（main.py R174 讀 GCS `ops/reports/public.json`） |
| 10 營運衛生 | ⏳ 部分（WIF 免金鑰已開通） | — | — |
| 額外：Claude 用量 | ◐ 4 次純轉發已搬去 Actions（對沖狀態、成交通報）；風險通報「新開工作階段」版 v2 實測做唔到（冇 repo、冇 send_message），維持舊 persistent Routine | 預設分支＋總指揮 | `ops_notify.yml`、`ops/ROUTINE_RISK_NOTIFY.md`（擱置原因） |

分工原則：**總指揮擁有風控、對帳、損益帳（私人數據）；預設分支擁有流水線、報告、讀取這些數據的下游（晨會、心跳、月報）**。
下游只讀總指揮產出的檔，不重算。
**公開 repo 的 Actions 日誌人人睇到**：含權益／金額的內文只發 Telegram、存私人 GCS，日誌只印字數（`ops_notify.print_private`）。

## 二之三、2026-10-15 再盤點：剩餘缺口與 Claude 用量（SOP 顧問）

### 現況一句話
10-13 報告嘅 10 個缺口，9 個已做（見二之一）。**每日流程骨架齊咗**：07:00 事件日曆 → 07:30 心跳（10-15 起連富途 VM）→ 08:30 晨會 →
盤中風險通報（總指揮 4 次）→ 17:10 成交 → 17:20 對帳＋損益帳 → 週日週報／評分卡 → 每月 1 日月報。
自動化：GitHub Actions 27 個排程 workflow（唔耗 Claude）；Claude Routine 平日約 **14 次**（下表）。

### 平日 Claude Routine（2026-10-15 list_triggers）
| 陣 | 次數 | 內容 | 可否改 Actions |
|---|---|---|---|
| 雲垂 | 6 | 14:30 掃描、16:00 HSI Δ、16:40 收市快照、03:30 MES、04:15 總結、05:52 美股定稿 | **16:40、05:52 只係觸發 fetch-quotes.yml → 可改 cron，慳 2 次** |
| 總指揮 | 4 | 09:45／12:45／16:45／21:45 風險通報 | 判斷部分可改 Actions＋Telegram，send_message 部分要 Claude |
| 蛇蟠 | 2 | 12:00、16:45 通道＋ArtifactData | 要寫網頁資料庫，暫時要 Claude |
| 鳥翔 | 1（＋1 回頭） | 17:13 觸發 HTF＋重發網頁 | 觸發部分可改 cron |
| 金絲雀 | 1（每日含週末） | 07:07 核對 Actions 日報 | 核對可寫成 Actions 檢查，有 ❌ 先叫 Claude |

### 🐉 龍飛陣（10-16 成立，10-17 龍飛陣通報；詳細 `handoff/龍飛陣.md` 第 0d 節，龍飛陣分支）
| 時間（HKT） | 做乜 | 執行者 | 耗乜 |
|---|---|---|---|
| 全日每 5 秒 | 24 個模擬程式（HSI＋16 隻 ETF＋科技七雄，10-18 起；報價共用快取 R226）對帳、報價、日蝕上限、止蝕止賺 | 台灣 VM `futu-data-tw` | 唔耗 Claude |
| 全日每 5 分鐘 | 決策：冇倉又唔准開 → 唔問；可開 → Haiku 5.5 篩選；放行或有倉 → Opus 5.5 決策（R218），再經硬性風控 | 同上 | **Claude API（另計，唔係訂閱額度）** |
| 每 5 分鐘 | 狀態／成交／決策推 Cloud Run → 私人 GCS `longfei/<產品>/`；網頁 `?view=longfei` | 同上 | — |
| 週二至六 08:10 | 1 分鐘 K 線存檔 → GCS `longfei/bars/<產品>/<日>.json` | VM timer `zhuge-longfei-bars` | — |
| 每日 08:22 | 覆盤 `scripts/longfei_review.py` → GCS `ops/longfei/reviews/`（API 費用表、Haiku 篩選檢查） | Claude Routine（龍飛陣工作階段） | 訂閱額度 |

- **API 費用（龍飛陣估算）**：R218 後約 US$26／日（10-18 加科技七雄每日再多約 US$7）、約 US$570／月（以前全部 Sonnet 約 US$35／日）；Opus 思考 token 可能令實數更高，第一份實數睇 10-20（二）08:22 覆盤。使用者要求約 10-31 比較 Opus 期同 Sonnet 期成績，冇改善就轉返 Sonnet（`settings.env` `CLAUDE_MODEL`）。
- 全部係富途**模擬戶口**；轉真倉要使用者逐隻落指令（`LONGFEI_REAL_PRODUCTS`），並先做：總指揮配對 PR（`FUTU_TEAM_RULES`）、`RISK_LADDER` §6b、`POSITIONS.md` 登記、意圖價登記 `ops/intents.csv`（龍飛陣分支）。
- 風控階梯：Ⓑ → 龍飛陣全部停開新倉；Ⓒ／Ⓓ 只發 Telegram。
- 部機：10-18 由 e2-small 升 e2-standard-2（8GB）＋2GB swap（每月約多 US$40）；加程式前要估記憶體同富途 API 次數（見 `ops/INCIDENTS.md` 10-18 兩列）。
- 時間表：~~10-24 09:30 出 ETF 真倉建議~~（10-20 改為一週檢討，真倉跟 R244 門檻）；HSI 真倉前置條件：①使用者准隔夜（10-18 已確認）；②伺服器端止蝕單真戶口驗證（10-19 係香港假期，順延 10-20 09:15 後；使用者用真期貨戶口掛遠價止蝕單、即掛即撤；模擬戶口 10-18 測試 GTC／當日止損單都被拒）——掛得到即符合 RISK_LADDER §6b ① 後備止蝕，掛唔到即隔夜冇伺服器端保護，總指揮有保留、由使用者決定；③10-20 模擬日冇出錯（10-19 假期順延）；④OpenD 交易解鎖（10-19 測試全部被拒「没有解锁交易」＝`FUTU_TRADE_PASSWORD` 未設；由使用者喺 VM `~/zhuge/env` 自己加、權限 600、唔入 repo）。⚠ `AGENTIC.md`「VM：futu-data」寫明 VM「只讀：唔落單、唔 unlock_trade；交易密碼唔放上 VM」——放交易密碼上 VM 係改呢條規矩，要使用者明確決定並同總指揮確認，再改 AGENTIC.md。**狀態（10-19）：交易密碼已放好（龍飛陣通報）；龍飛陣轉述使用者揀 A（密碼留 futu-data-tw `~/zhuge/env`、權限 600）；等總指揮確認同富途數據 VM 陣改 AGENTIC.md**（總指揮建議收窄為只有龍飛陣真倉服務解鎖，auto_risk／推送照只讀）。
- **10-20 00:18 HKT 美股真倉停**（使用者 10-19 深夜：「SPY、QQQ 不做真倉，現在所有美股先跑模擬，待結果滿意才做真倉」）：#218（R242）清空 `LONGFEI_REAL_PRODUCTS`，冇倉、富途冇殘留單；真倉期間 5 張單（金額只喺對話）。以下 10-19 上線紀錄保留作參考。
- **轉真倉門檻（R244，使用者 10-20：「你自己不斷批評自己，如果你自己覺得可以轉真倉你通知我」）**：≥30 筆、≥10 個交易日、每筆平均 >0、獲利因子 ≥1.3、t ≥2、前後兩半都賺、扣真倉滑價仍賺、回撤 ≤ 日蝕上限 2 倍、最近 10 筆冇變差——全部過到先建議使用者，由使用者決定。每日 08:22 覆盤＝自我批評＋自主改進；KPI 睇滾動 10 日趨勢、唔追單日。10-24 改做一週檢討（原本嘅 ETF 真倉建議取消）。
- **自主改進紀錄**（龍飛陣自己合併同更新部機，每次通知總指揮同 SOP 顧問）：10-20 #221 R245 龍飛陣頁加滾動 10 日 KPI（筆數、勝率、扣費後每筆平均、獲利因子，▲▼ 對前一日）；#222 R246 第 1 次改進（參考各陣公開策略，只加「唔做咩」）：HSI 日市 16:00、夜市 02:30 後唔追新高新低、唔逆開市突破；美股美東 16:00 後唔開新倉——IDEAS #108、#109 預先登記成功標準，#110 記未用候選。
- **模擬倉自主（#220 R243，使用者批准）**：模擬倉績效係龍飛陣 KPI；模擬倉教學簿同參數由龍飛陣自己改、合併、更新部機，**真倉照舊要使用者批准**。防過度擬合：每次最多改 1–2 樣、先喺 IDEAS.md 登記、少過 10 筆唔改、差咗自動改返。龍飛陣頁有每日／週／月總結（#219 R241，Cloud Run 00328-qfc）。
- **10-19 美股真倉上線**（SPY、QQQ；#212 R233–R235、配對 #213／#214 R237／R238，Cloud Run 00326-rkp）：每單唔設上限、用盡富途槓桿、日蝕每隻／合計上限（金額見龍飛陣私人設定，使用者喺總指揮工作階段確認）。伺服器端後備止蝕（R234）：開倉即掛 GTC 止損，觸發價比程式止蝕再遠 0.3%，平倉前先撤；港期預設關。#217（R240）修正真倉準備檢查誤報。之後加減真倉產品只改 `settings.env`＋更新部機。
  - 配對：`FUTU_TEAM_RULES` 已將 23 隻美股（SPY、QQQ…TSLA）全部歸「龍飛陣」——**其他陣或使用者人手喺富途買賣呢 23 隻，blotter／對帳會歸錯陣**。總指揮 10-19 決定維持 R238（使用者要求簡化配對，取捨已講明），例外用規矩：人手或其他陣買賣呢 23 隻，先登記 POSITIONS.md 並通知總指揮加專屬規則。現時證券戶口只有龍飛陣用。
  - 登記（總指揮 10-19 同意）：POSITIONS.md 只登記一列「🐉 龍飛陣美股真倉（程式自動，運行中）」（龍飛陣開 PR、總指揮審），逐筆睇私人 GCS `longfei/real/`；對帳表龍飛陣只列示 🐉（R237、RISK_LADDER §6b）；成交照入 blotter。
  - API：10-19 美股 23 隻模擬到 22:15 約 US$13，Haiku 篩走 58%。
- ETF／科技股（美股證券戶口）真倉前置：伺服器端止蝕 ✅ 10-19 真戶口驗證通過（STOP、STOP_LIMIT 都可 GTC 掛、改價、App 見到、撤得乾淨）；仲欠證券戶口入金（使用者）。
- 通用規矩（龍飛陣 10-19 建議）：**任何真倉程式上線前，要用一張唔會成交嘅遠價測試單證明真戶口落到單（掛完即撤）**。覆盤多咗真倉候選排名，教學分共用／個別產品教學簿。

### Claude 用量（各工作階段 `usage.cost_usd`，API 等值，非實際帳單；10-14 04:20 → 10-15 16:10 約 36 小時）
| 工作階段 | 美元等值 | 備註 |
|---|---|---|
| 總指揮 | ≈ 79 | 對話＋4 次通報 |
| 風揚 | ≈ 60 | 上下文已 64 萬 tokens，每輪最貴 |
| 圖表形態交易 | ≈ 34 | 使用者手機對話 |
| 雲垂 | ≈ 33 | 6 個 Routine |
| 蛇蟠 | ≈ 18 | |
| 其餘 9 個 | ≈ 50 | 富途 VM 11、鳥翔 10、地載 10、金絲雀 7、SOP 4、股票研究 3、GCP 3、外匯 2、XAUUSD 1 |
| **合計** | **≈ 274（約每日 180）** | 7 日用量已到 **allowed_warning**，10-16（五）20:00 HKT 重置 |

讀法：**大頭係長上下文嘅對話，唔係 Routine**——cache 讀取佔絕大部分 token，上下文愈長每輪愈貴。

### 進度（10-15 使用者：A–E 做，F、G 不做；雲垂兩個純觸發 Routine 改 Actions；風揚換新工作階段）
- A ✅ GCS `ops/claude_usage/<日>.json`＋`latest.json`（SOP 顧問 Routine `trig_016R1X3vYQ9uVyKAGRQ5j6oM` 週日 08:45 用 get_session 寫）；週報【三】列本週各工作階段用量、7 日額度、上下文 > 60 萬嘅建議換新（使用者 10-15 定）。
- D ✅ `ops/INCIDENTS.md`；週報【三】列本週新增＋未結。
- 雲垂 16:40／05:52 → `.github/workflows/yunchui_quote_kicks.yml`（16:40 嗰次另查 hsi／vhsi 日線係 final，唔係就 job 失敗、心跳報 🔴）；兩個 Routine 已停用（唔刪）。
- E ✅（預設分支部分）`scripts/ops_blotter.py`：每次成交通報後將富途成交按 `FUTU_TEAM_RULES` 歸陣、配對 `ops/intents.csv` 意圖價計滑價，寫私人 GCS `ops/blotter/<月>.csv`；月報【二】列按陣筆數同平均滑價。各陣出落單指令時要登記意圖價（`ops/INTENTS_README.md`），由總指揮通知各陣。
- B、C：總指揮草稿 PR #142（R193：`mm_jump` 維持保證金當日升 ≥30% → Telegram；壓力情景 `ops/risk/stress_latest.json`＋`metrics.stress`），10-15 已合併，10-17 核實已生效（VM auto_risk R199、Cloud Run 00314-v2l 寫 `ops/risk/stress_latest.json` 8 個情景）。晨會【一】已改讀壓力情景最差 4 個同按日／夜盤嘅緩衝線（舊寫死 15／10／6 萬已刪；PR #142 生效前顯示「線見 RISK_LADDER.md」）。

### 剩餘缺口（按風險排序）
| # | 缺口 | 風險 | 建議 | 負責 |
|---|---|---|---|---|
| A | **Claude 用量冇預算、冇監控**：已到 7 日用量警告，冇人知邊個陣用幾多 | 高（用盡＝全部 Routine 停，包括風險通報） | 週報加一段「各工作階段用量」（我用 get_session 讀）；上下文 > 60 萬 tokens 就換新工作階段；把純觸發 Routine 改 Actions cron | SOP 顧問；改 Routine 由各陣 |
| B | **保證金變動冇預警**：10-14 維持保證金一日約翻倍，事後先知 | 高 | auto_risk 已有 margin；加「維持保證金單日 +30% → 即時 Telegram」，並收交易所／券商保證金調整公告入事件日曆 | 總指揮（auto_risk、R149） |
| C | **壓力測試冇每日化**：`tradingview/risk_report.py` 有，但唔入晨會 | 中高 | 晨會加一行「恒指 ±5%／VIX +10 情景下緩衝剩幾多」（只 Telegram，唔入 repo） | 總指揮出數，晨會讀 |
| D | **事故冇登記簿**：1321.T 拆股、`_status.txt` 覆蓋、保證金跳升、OpenD 登入鎖，各自散喺 handoff | 中 | 新增 `ops/INCIDENTS.md`：日期、影響、根因、修正 commit、預防；週報數本週新事故 | SOP 顧問 |
| E | **人手落單冇「落單前檢查」紀錄**：POSITIONS／IDEAS 有規矩，但冇每單一行嘅 blotter（意圖價 vs 成交價、滑價） | 中 | `ops/blotter` 由 17:10 成交匯出自動生成，各陣補「意圖價」；月報計滑價 | 總指揮＋預設分支 |
| ~~F~~ | ~~券商月結單對帳~~（使用者 10-15：不做）：日對帳用富途 API，冇同官方月結單核對 | 中低 | 每月 1 日月報提醒使用者下載月結單，對總權益同手續費 | 使用者＋總指揮 |
| ~~G~~ | ~~營運衛生（缺口 10 餘項）~~（使用者 10-15：不做）：服務帳戶金鑰輪換日期、VM 權杖到期、Secrets 清單 | 低 | `ops/SECRETS_INVENTORY.md`（只列名同到期日，唔列值），心跳讀到期日 | SOP 顧問 |

### ES／NQ 數據來源（10-19 起，GCP／VM／IBKR 資料採集通報）
- 5 分 K（`US.ES_FRONT`／`US.NQ_FRONT` K_5M）：ib-data VM cron `*/5 * * * 0-5` 跑 `scripts/ib_es_nq_5m.py`（IB 延遲歷史 K，前月 ESZ6／NQZ6，到期前 8 日轉季；PR #202）。取代部機 MT5 `mt5_push`（10-16 ES 收市同 CME 差約 60 點）。Gateway 約 23:50 UTC 重啟嗰幾輪會缺，下一輪自動補。**10-16 封存 00:00–約 09:00 NY 係 MT5 數據，同 CME 有偏差（使用者 10-19 決定唔補推），回測慎用。**
- 心跳（07:30 HKT＝紐約約 18:30–19:30，CME 開市）：`futu/snapshots/US.ES_FRONT.json`／`US.NQ_FRONT.json` 推送 > 20 分鐘、最後一根落後 > 45 分鐘 → 🔴；source 唔係 `ib_delayed:` → 🔴（使用者 10-19）；CME 休市唔查。
- 日線（K_SESSION）：GitHub Actions `es_daily_push.yml`（yfinance，R230，#201 恢復）；心跳已將佢由「已退役」移返正常檢查。
- 部機 `ZHUGE_DAEMONS=none`：只起 MT5／EA，唔起 Python 推送；OpenD 喺 futu-data-tw。數據問題搵 GCP／VM／IBKR 資料採集工作階段。

## 二之二、VM 與資料推送守則（2026-10-14，claude-ops 經驗整理，使用者同意）

適用：ib-data／claude-ops 兩部 VM、所有把採集數據推上 GitHub 的步驟、教使用者喺 VM 貼指令嘅工作階段。

1. **附加式日誌只追加，唔覆蓋。** 推資料去有憑證嘅帳號時，唔准用 `cp -r` 蓋遠端既有嘅附加式日誌（例如 `data_stock_ibkr/_status.txt`）；
   用 `tail -n +N 新檔 >> 舊檔` 只追加，或者先 `git show <分支>:<檔>` 取舊版合併。**commit 前睇 `git diff --stat`，日誌檔唔准有刪除行。**
   （教訓：`22f1d384`（10-06）用 `cp -r` 將鳥翔 `_status.txt` 313 行歷史蓋成 205 行，CSV 無損；鳥翔陣 10-14 已由 `c3f4a61b` 補回成 518 行，`cd10d0a1`。）
2. **有排程喺 pull 嘅目錄唔好直接切分支**（例如 hengkychansinghing 嘅 `~/20260918`）；要用其他分支就開獨立 `git worktree`，做完 `git worktree remove`。
3. **教使用者貼指令：「復原」指令獨立成一段並清楚標示**，唔好同正常步驟放埋一齊（10-13 使用者連復原嗰行一齊貼，將啱改好嘅 IBC `config.ini` 改返轉頭）。
   使用者回報做完之後，要佢貼輸出、用輸出驗證，唔好假設已生效。
4. **Gateway 每晚約 23:50 UTC（07:50 HKT）由 `ib_keepalive.sh` 重啟。** 重啟後 Paper 免責聲明（Error 10141）會擋 API，
   現靠 `dismiss_paper_warning.sh`（xdotool 座標點擊，視窗必須剛好 501x260）加 IBC `AcceptNonBrokerageAccountWarning=yes`。長時間抓取避開 23:50 UTC 前後。
5. **採集腳本唔可以因 git 狀態整日唔跑。** `run_daily.sh` 有 `set -e`，`git pull` 因未提交修改失敗會令當日採集全部冇跑；已改 `git pull --autostash`（`c8d3033d1`）。
   採集用當下延遲報價，**缺咗嘅日子補唔返，不得估算補值**；缺日要喺 `_status.txt` 記低，唔好填假數。
6. **權限分工與跑別人腳本。** `claudeops` 冇 sudo、冇 GitHub 憑證、讀唔到 `/home/hengkychansinghing`（權限改動照 CLAUDE.md 要附 `AGENTIC.md`「必跑這個檢查」）。
   跑其他分支嘅腳本前先讀過，確認只讀行情、冇任何下單呼叫。背景長任務用 `setsid nohup … < /dev/null &`；喺 ssh 入面直接 `&` 可能唔返回。

## 三、建議順序

| 優先 | 缺口 | 理由 | 負責 | 工作量 |
|---|---|---|---|---|
| 1 | 缺口 1 風控階梯 | 其他全部缺口的動作都要掛在它上面；需要使用者決策，先問 | 總指揮＋使用者 | 0.5 天 |
| 2 | 缺口 6 流水線心跳 | 最便宜，立刻減少靜默失敗 | 預設分支 | 0.5 天 |
| 3 | 缺口 3 每日對帳表 | 總指揮已有 16:45 流程，加一步 | 總指揮 | 0.5 天 |
| 4 | 缺口 5 逐日損益帳 | 月報、歸因、偏離監控的共同地基 | 總指揮 | 1 天 |
| 5 | 缺口 2 晨會簡報 | 等 3、5 有數據後做才有內容 | 預設分支 | 1 天 |
| 6 | 缺口 4 事件日曆 | 期權賣方部位最直接的保護 | 預設分支＋風揚 | 1 天 |
| 7 | 缺口 7、8、9、10 | 低風險或等前項 | 各自 | — |

## 四、一句話

這間「基金」的數據組與研究部已經比多數同規模的團隊完整，缺的是中後台：一份寫死的風控階梯、一份每日對帳表、一條逐日損益帳、一則晨會。這四樣都不需要新策略，兩週內可以補齊。
