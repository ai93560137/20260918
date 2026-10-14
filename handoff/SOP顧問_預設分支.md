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
- 總指揮 `session_01N1jfpEJciBkfAgwtd4QxgU`（擁有風控、`RISK_LADDER.md`、`daily_books.py`、`POSITIONS.md` 配對、舊風險通報 Routine `trig_01LRrZMZ5mVnFqBYtAFqXxcW`）
- 金絲雀 `session_01KucjwzRvueynnK5qm26y9g`；風揚 `session_01AmKfqsQjNQAkz1xgjRo2Mj`；地載 `session_01QDAzw2CmhvhYWip9SRktBn`；蛇蟠 `session_011i86tjK8gxGxbMdTukZp4B`；雲垂 `session_01QLJsy4RoeHjPNdNha73ibt`
- **2026-10-14 起各陣換新工作階段**，以上 id 會變；以 CLAUDE.md 同 `handoff/` 目錄為準。

## 六、進行中／待辦
1. **換新工作階段（2026-10-14 04:15 開始）**：已叫 15 個舊工作階段寫 `handoff/<名>.md` 喺各自分支並回覆。之後：每個開新工作階段（同分支）→ 新工作階段讀交接、回報接手 → 喺新工作階段重建 Routine（舊嘅 `update_trigger enabled=false`，唔刪）→ 改 CLAUDE.md 總指揮 id、各 Routine prompt 內寫死嘅 session id（總指揮風險通報發畀四陣）→ 通知各陣新 id。舊工作階段由使用者決定幾時封存。
2. 10-18（日）09:00 第一份週報；11-01 第一份月報（報 10 月）。
3. 等風揚陣如要再改 `calendar/rules.json`。
4. 偏離監控：地載 7 行最早 2027-04 判燈。
5. 用量：使用者問過「Max 20x 夠唔夠」——答：仍 allowed；最大用量係長上下文工作階段被 Routine 叫醒重讀，同使用者開嘅大對話。

## 七、開工第一步
讀 `CLAUDE.md`、`FUND_SOP.md`（第二之一節）、本檔、`ops/ROUTINE_RISK_NOTIFY.md` 頂部、`IDEAS.md` 前 30 行；`python3 scripts/gcp_agent.py whoami`、`status`。
