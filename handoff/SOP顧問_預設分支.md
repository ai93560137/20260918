# 交接：SOP 顧問／預設分支工作階段（舊 session_01BzZsgkBzxEaLV6CYPW67i6，標題「Harness learning framework」）

> 2026-10-14 04:20 HKT 寫。使用者要求每個舊工作階段開新接手（上下文太長、用量大）。舊工作階段保留，唔封存。
> 分支：`claude/gcp-trading-v12-rewrite-bz75t2`（預設分支，Cloud Run 由此部署）。repo 公開。

## 一、你係邊個、負責乜
- **SOP 顧問＋預設分支流水線擁有者**。分工（FUND_SOP.md 第二之一節）：**總指揮擁有風控、對帳、損益帳（私人數據）；預設分支擁有流水線、報告、讀取呢啲數據嘅下游**。下游只讀總指揮產出，唔重算。
- 使用者原話：「要配合總指揮，不要重覆和衝突」「你的工作要通知總指揮，金絲雀，和其他不同陣的分支」「你是我的SOP顧問」。
- 回覆使用者用繁體中文（使用者用粵語書面語亦可）。

## 二、你擁有嘅嘢（全部純 Python，GitHub Actions 跑，唔耗 Claude）
| 東西 | 檔案 | 排程（HKT） | 輸出 |
|---|---|---|---|
| 晨會簡報 | `scripts/morning_brief.py`、`morning_brief.yml` | 平日 08:30 | Telegram＋GCS `ops/brief/` |
| 流水線心跳 | `scripts/ops_heartbeat.py`、`ops_heartbeat.yml`、`ops/heartbeat_config.json` | 每日 07:30 | Telegram＋GCS `ops/heartbeat/<日>.txt` |
| 對沖狀態／成交通報 | `scripts/ops_notify.py`、`ops_notify.yml`、`ops/notify_config.json` | 14:35／15:55／17:10／03:40（GitHub 會遲 15–30 分） | Telegram、GCS `ops/hedge_status.txt`、`ops/deals_status.json`、repo `ops/hedge_status_latest.txt`、`ops/deals_latest.json`（無金額，畀雲垂讀） |
| 事件日曆 | `scripts/event_calendar.py`、`event_calendar.yml`；規則 `calendar/rules.json`（**風揚陣擁有**） | 每日 07:00 | `calendar/events.csv`、`calendar/WEEK.md` |
| 週報／月報 | `scripts/ops_reports.py`、`ops_reports.yml` | 週日 09:00／每月 1 日 09:30 | 完整版 Telegram＋GCS `ops/reports/<kind>/`；公開版 GCS `ops/reports/public.json` → tnt-hk.com/?view=fund_report（main.py R174） |
| 篩選器評分卡＋偏離監控 | `scripts/screener_scorecard.py`、`scripts/strategy_divergence.py`、`screener_scorecard.yml`；期望 `research/divergence/expectations.json` | 週日 03:37 | `research/screener_scorecard/SCORECARD.md`、`research/divergence/DIVERGENCE.md`、`dizai_trades.json`（地載紙上成交累積歸檔） |
| 想法登記簿 | `IDEAS.md` | — | 先登記後回測；棄用寫原因 |
| SOP 盤點 | `FUND_SOP.md`（§1.2–1.4 總指揮擁有） | — | 第二之一節進度表要更新 |
| harness learning | `research/harness_learning/`（論文 arXiv:2609.35738 實作，27 測試） | — | — |
| main.py 改動 | R171（MT5 balance → GCS `logs/trade_ledger.json`）、R174（基金報告頁週報／月報區） | — | 現行修訂 `zhuge-risk-manager-00297-hl4`，rollback 目標 `00296-h8s` |

## 三、規矩（務必遵守）
1. **repo 同 Actions 日誌係公開**：任何含權益／保證金／緩衝／金額嘅內文只發 Telegram、存私人 GCS；Actions 用 `ops_notify.print_private()` 只印字數。測試 fixture 用虛構數字（使用者決定 repo 唔留真實權益）。
2. CLAUDE.md 安全規則：部署／改環境變數先 dry-run，使用者明確講「部署」先 `--yes`；部署前 `python3.11 -m py_compile main.py`、`python3 -m unittest scripts/test_gcp_agent.py`、`python3 backtest.py --help`。部署前確認預設分支 main.py 包含總指揮最新改動（佢都會部署 main.py）。
3. `gcp_agent.py put` 只准寫 `ops/` 前綴。
4. 合併其他陣 PR：使用者講「合併」先合；合併前本機 merge-tree 查衝突、跑該 PR 測試（注意有啲測試寫死 `/home/user/20260918` 路徑）。
5. 唔 SSH ib-data、唔改 IAM、唔刪 bucket 物件。

## 四、Routine／排程
- 我**冇**啟用中嘅 Claude Routine。`trig_01CGH8WyZjPNcP3SjhD9RLUc`（舊）停用；`trig_014UUQeZ5rPhXEXVrWVBveRu`（風險通報 v2，每次新開工作階段）**擱置停用**——實測新開工作階段冇 repo、自己 clone 被權限分類器拒絕、冇 send_message（見 `ops/ROUTINE_RISK_NOTIFY.md` 頂部）。唔好再啟用。
- 一次性自檢 `trig_01SGyzundF24zjL9TBmFB4XR` 已觸發完（03:40 成交通報首發成功，04:04 跑）。

## 五、聯絡（send_message）
**以 `handoff/SESSIONS.md` 為準**（下面係換新前嘅舊 id，只作歷史參考）。
- 總指揮 `session_01N1jfpEJciBkfAgwtd4QxgU`（擁有風控、`RISK_LADDER.md`、`daily_books.py`、`POSITIONS.md` 配對、舊風險通報 Routine `trig_01LRrZMZ5mVnFqBYtAFqXxcW`）
- 金絲雀 `session_01KucjwzRvueynnK5qm26y9g`；風揚 `session_01AmKfqsQjNQAkz1xgjRo2Mj`；地載 `session_01QDAzw2CmhvhYWip9SRktBn`；蛇蟠 `session_011i86tjK8gxGxbMdTukZp4B`；雲垂 `session_01QLJsy4RoeHjPNdNha73ibt`
- **2026-10-14 起各陣換新工作階段**，以上 id 會變；以 CLAUDE.md 同 `handoff/` 目錄為準。

## 六、進行中／待辦（2026-10-14 05:10 HKT 更新）
1. **換新工作階段已完成**（10-14 04:15–05:10）：對照表 `handoff/SESSIONS.md`（你維護）。總指揮、雲垂、風揚、蛇蟠、地載、金絲雀、鳥翔、股票市場策略研究、外匯 VM 採集、GCP 資料採集、XAUUSD 都有新工作階段；Routine 全部新建綁新工作階段，舊嘅 `enabled=false` 唔刪。使用者話 HTF 策略指南、股票套利、指數套利、外匯數據測試**已冇用、唔換**（佢哋嘅提醒 trigger 已停用；PR #101／#103／#94／#73 仍開，等使用者決定）。舊工作階段全部保留，**幾時封存由使用者決定**。
   - ⚠ 教訓：`fire_trigger` 手動觸發綁新工作階段嘅 Routine 會另開一個冇 repo 嘅空白工作階段（已封存誤開嗰個）；排程時間到自動觸發就正常（04:27 測試驗證）。要即時做就直接 `send_message`。
   - ⚠ XAUUSD 舊、GCP 舊兩個工作階段冇 `send_message`，要使用者轉話；新開嘅（create_session）有。
   - 新建工作階段用 `create_session`（source_url＋source_revision＝該陣分支），開場 prompt：讀 handoff、唔改嘢、`get_session` 查自己 id、`send_message` 回報。
2. **緩衝風險（10-14 03:54）**：維持保證金由約 18.6 萬跳到約 38.7 萬，緩衝約 14.5 萬，日盤 Ⓑ、夜盤 Ⓒ。新總指揮 04:23 已通報四陣；等使用者 09:15 前決定入金（約 4 萬）或減倉、核實保證金加倍原因、更新部機 risk_book（MHI2610 對沖已平）。
3. **PR #116**（總指揮 POSITIONS.md 更正）等使用者講「合併」；新總指揮已訂閱。
4. **1321.T**：股票市場策略研究已修（gifted-carson `a2afd8f1`：刪 adjustments.csv 1321.T、price_overrides 補 10-05／06、marketdata.py 擴充）；新鳥翔要喺 10-30 前對齊自己分支同 10-31 Routine prompt。
5. 10-18（日）09:00 第一份週報；11-01 第一份月報。
6. 偏離監控：地載 7 行最早 2027-04 判燈。
7. 外匯 VM 採集（L1／6E／ZQ）使用者決定繼續，由外匯 VM 新工作階段負責；07:30 心跳唔包 VM。

## 七、開工第一步
讀 `CLAUDE.md`、`FUND_SOP.md`（第二之一節）、本檔、`ops/ROUTINE_RISK_NOTIFY.md` 頂部、`IDEAS.md` 前 30 行；`python3 scripts/gcp_agent.py whoami`、`status`。
