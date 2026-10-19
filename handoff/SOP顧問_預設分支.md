# 交接：SOP 顧問／預設分支工作階段（舊 session_01BzZsgkBzxEaLV6CYPW67i6，標題「Harness learning framework」）

> 2026-10-14 04:20 HKT 寫。使用者要求每個舊工作階段開新接手（上下文太長、用量大）。舊工作階段保留，唔封存。
> 分支：`claude/gcp-trading-v12-rewrite-bz75t2`（預設分支，Cloud Run 由此部署）。repo 公開。

## 〇、2026-10-14～19 更新（新 SOP 顧問 `session_012caA3uVCQjRHHryN5HnMrn` 寫，10-19 HKT）

> 以本節為準；下面一至七節係舊工作階段 10-14 寫，部分已過時（例如各陣 id、門檻 40 萬）。

### 〇.1 今日（10-18／10-19）改動
| 項目 | 做咗乜 | commit／id |
|---|---|---|
| 換新工作階段 | 雲垂 → `session_013KSbtb9YJejCuaunQBdJDC`、總指揮 → `session_01ELtWSJc46vAFMT4oh3fCTV`（上下文 66／67 萬）；Routine 全部新建綁新嘅、舊嘅停用唔刪；SESSIONS.md、CLAUDE.md 已改 | `5a17aaa79`、`c3771a95e` |
| 改綁 Routine | 雲垂四個：掃描 `trig_01YMAkWjJk26gYK5MnoN8oZu`、HSI 16:00 `trig_01MoBKsKnuXXpLT8Extf7cUf`、MES 檢查 `trig_01Pjo5jzL3Fw2UQv8SJLfRak`、收市總結 `trig_016frwuMEEy6t5pEoTJ8orFg`；總指揮四陣風險通報 `trig_01Pwz5Zf91s3XJ8ND36QJdYL`（prompt 改龍飛陣 HSI＋ETF 全模擬、雲垂新 id、VM futu-data-tw） | — |
| 冬令時間（使用者 10-19） | 雲垂 MES 檢查改 `CRON_TZ=America/New_York 30 15 * * 1-5`、收市總結改 `… 15 16 * * 1-5`，自動跟美股夏令／冬令；Actions `yunchui_quote_kicks.yml` 21:52 UTC 唔使改 | — |
| 事故（INCIDENTS） | 10-18 OOM（e2-small 2GB＋17 個龍飛陣程式 → 升 e2-medium 再升 e2-standard-2 8GB；#193、#194）同富途快照限速（#198 共用快取）兩列，已結；10-14 保證金翻倍因 #142 上線已結 | `4283c12d4`、`43bcbd233`、`260cc4445` |
| 心跳 | VM 改查 `futu-data-tw`（asia-east1-b）；龍飛陣 `longfei/SPY/latest.json`（0.5 小時）、push_to_gcp（1）、iv_push（2）週末唔放寬；ES／NQ 5 分 K（`futu/snapshots/US.*_FRONT.json`，CME 時段：推送 >20 分、K 線落後 >45 分、source 唔係 `ib_delayed:` 都 🔴）；`es_daily_push.yml` 由「已退役」移返正常檢查 | `71bd4303d`、`ea305ad30`、`eefe7b564`、`2fc6e3645`、`afc7f76f4`、`f67bd8939` |
| 用量週快照 | 10-18 08:47 第一次由 Routine 寫 `ops/claude_usage/2026-10-18.json`；本週合計約 US$515（API 等值） | — |
| blotter | 加 `--rematch`（各陣事後更正 intents.csv 後重配）；雲垂 MES 11/20 兩腳已配，合計滑價 −0.25 點 | `2b52bc45e` |
| FUND_SOP | 龍飛陣小節（24 個程式、部機 8GB、API 費用、HSI 真倉前置：准隔夜、伺服器端止蝕真戶口驗證 10-19、模擬日冇錯；10-24 ETF 真倉建議）；ES／NQ 數據來源（5 分 K 改 ib-data `ib_es_nq_5m.py`、日線 `es_daily_push.yml`、10-16 封存混合 MT5 回測慎用、使用者決定唔補推） | `43bcbd233`、`971100588`、`2fc6e3645`、`f67bd8939` |
| SESSIONS 新增 | 🐉 龍飛陣 `session_0139SPVaaCjhGQM81SipbPgp`（HSI＋ETF，全模擬）、🏦 債券每日快報 `session_013x5qHyMDisW7VCLNo6w88x`、🖥️ 富途數據 VM（futu-data-tw） | `38cbe51a8`、`0eb7964c3`、`b01a8265a` |

### 〇.1b 10-19（香港假期）日間改動
| 項目 | 做咗乜 | commit |
|---|---|---|
| 交接 | 本節〇（10-14～19 總結）寫入 | `4b82a52fa` |
| 龍飛陣 HSI 真倉前置 | 10-19 港假，②真戶口止蝕單、③模擬日順延 10-20；新增④OpenD 交易解鎖（10-19 測試被拒「没有解锁交易」＝`FUTU_TRADE_PASSWORD` 未設） | `396674caf` |
| ④同 AGENTIC.md 衝突 | `AGENTIC.md` 第 271 行「VM 只讀：唔落單、唔 unlock_trade；交易密碼唔放上 VM」。龍飛陣**轉述**使用者揀 A（密碼留 futu-data-tw `~/zhuge/env`、權限 600）——我冇喺本對話直接見到使用者講，FUND_SOP 記為「轉述」；等總指揮確認＋富途數據 VM 陣改 AGENTIC.md。總指揮建議收窄：只有龍飛陣真倉服務解鎖，auto_risk／推送照只讀 | `f6b144fb5` |
| 通用規矩 | 任何真倉程式上線前，用唔會成交嘅遠價測試單證明真戶口落到單（即掛即撤） | `396674caf` |
| 美股證券戶口 | 伺服器端止蝕真戶口驗證 ✅（STOP／STOP_LIMIT GTC 掛、改價、App 見到、撤乾淨）；ETF／科技股真倉仲欠證券戶口入金 | `c820b302f` |

### 〇.1c 10-19 晚至 10-20 凌晨改動（龍飛陣美股真倉上線再停）
| 項目 | 做咗乜 | commit |
|---|---|---|
| 美股真倉上線 | 10-19 SPY、QQQ 真倉（#212 R233–R235；配對 #213／#214 R237／R238；Cloud Run 00326-rkp）；伺服器端後備止蝕 R234（開倉即掛 GTC 止損，比程式止蝕遠 0.3%）；#217 R240 修準備檢查誤報；交易密碼已放 futu-data-tw | `114ab8fff` |
| 總指揮兩個決定 | ① `FUTU_TEAM_RULES` R238 維持：23 隻美股（SPY…TSLA）全部歸龍飛陣，人手或其他陣買賣呢 23 隻要先登記 POSITIONS.md 並通知總指揮；② POSITIONS.md 只登記一列「🐉 龍飛陣美股真倉（程式自動，運行中）」，逐筆睇私人 GCS `longfei/real/` | `4f0155bfd` |
| 美股真倉停 | 使用者 10-19 深夜：「SPY、QQQ 不做真倉，現在所有美股先跑模擬，待結果滿意才做真倉」；#218 R242 清空 `LONGFEI_REAL_PRODUCTS`，10-20 00:18 HKT 停、冇倉冇殘留單（真倉 5 張，金額只喺對話） | `a6d0ce72e` |
| 模擬倉自主 | #220 R243（使用者批准）：模擬倉績效係龍飛陣 KPI，教學簿同參數龍飛陣自己改／合併／更新部機；真倉照舊要使用者批准；防過度擬合（每次最多改 1–2 樣、先登記 IDEAS.md、少過 10 筆唔改、差咗自動改返）；龍飛陣頁加日／週／月總結（#219 R241，00328-qfc） | `a6d0ce72e` |

### 〇.2 10-14～17 已做（新增你擁有嘅嘢）
- **FUND_SOP 二之二**「VM 與資料推送守則」（claude-ops 經驗六條）、**二之三**「再盤點」（缺口 A–E 做、F／G 使用者話唔做）。
- **A 用量監控**：GCS `ops/claude_usage/`；你嘅 Routine `trig_016R1X3vYQ9uVyKAGRQ5j6oM`（週日 08:45 HKT，get_session 逐個讀）；週報【三】列本週用量、7 日額度、上下文 > **60 萬**（使用者 10-15 定）建議換新。
- **D 事故登記** `ops/INCIDENTS.md`（任何陣可加；週報列本週新增＋未結）。
- **E 落單紀錄** `scripts/ops_blotter.py`：跟 `ops_notify.yml` 17:10／03:40 跑，按 `main.py` `FUTU_TEAM_RULES`（ast 讀）歸陣，配各陣**自己分支**嘅 `ops/intents.csv`（分支清單 `ops/notify_config.json` `intent_branches`），私人 GCS `ops/blotter/<月>.csv`；月報【二】列按陣滑價。
- **B／C**（總指揮 PR #142 R193，已上線）：`mm_jump` 保證金急升預警；壓力情景 `metrics.stress`／`ops/risk/stress_latest.json`，晨會【一】讀最差 4 個同按日／夜盤緩衝線（舊寫死 15／10／6 萬已刪）。
- **雲垂 16:40／05:52** 兩個純觸發 Routine 改 Actions `yunchui_quote_kicks.yml`（16:40 嗰次查 hsi／vhsi 日線係 final）。
- 心跳加富途 VM Compute 狀態＋三個推送輸出。

### 〇.3 規矩（新增）
- 換新門檻：上下文 > 約 **60 萬 tokens**（SESSIONS.md 頂）。換新流程：舊嘅先更新交接、回 commit → `create_session`（source_revision＝該陣分支）→ Routine 新建綁新、舊嘅 `enabled=false` → SESSIONS.md（總指揮另改 CLAUDE.md）→ 通知舊嘅同總指揮。
- 心跳／晨會／週報／月報（預設分支流水線）有新檢查，各陣 send_message 你加，唔好自己開 PR（10-18 PR #204 撞改，已關）。
- repo 公開：INCIDENTS／FUND_SOP 唔寫保證金、權益金額。

### 〇.4 未完成／跟進
1. 龍飛陣 10-20 08:22 覆盤後會報**實際每日 API 美元** → 更新 FUND_SOP 龍飛陣小節同週報。
2. 龍飛陣：美股真倉已停（全部模擬，等使用者再批）；HSI 伺服器端止蝕單真戶口驗證（**順延 10-20** 09:15 後）結果 → 更新 FUND_SOP；龍飛陣自主改模擬參數時留意 IDEAS.md 有冇先登記（防過度擬合規矩）；交易解鎖 AGENTIC.md 改好（富途數據 VM 陣）→ 更新 FUND_SOP 前置④狀態；轉真倉前總指揮要喺 `FUTU_TEAM_RULES` 加龍飛陣（否則 blotter／對帳歸錯陣）。
3. 10-25 下一次週日用量快照；週報「本週」由 10-25 起計得到（10-18 對 10-15 快照）。
4. 11-01 第一份月報（含 blotter 按陣滑價）。
5. 雲垂 Routine prompt 仲寫「20:30 倫敦」字眼（只係文字，雲垂自己改）。

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
