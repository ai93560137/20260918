# CLAUDE.md — 給 Claude 的工作說明

本 repo 是「智能諸葛亮」量化交易系統：`main.py` 的進入點是 `receive_tradingview_signal`（2026-10-20 R253 起只做富途／恒指／CME／各陣頁面；舊 XAUUSD 引擎已移除，黃金由天覆陣 `zhuge-xau`／`xau/` 負責），
狀態全部存在 GCS bucket `zhuge-risk-manager-bucket`。
**目前實際在跑的是 Cloud Run 服務 `zhuge-risk-manager`（區域 `europe-west1`）**，不是 Cloud Function；
專案裡沒有任何 Cloud Function。asia-east1 另有一個同名、部署失敗的舊 Cloud Run 服務（不接流量，別理它）。
`scripts/` 與 `data/` 是 GitHub Actions 跑的研究／追蹤腳本，不會部署到 Cloud Function。

## 你可以直接操作使用者的 GCP

工作階段啟動時 `.claude/hooks/session-start.sh` 會安裝套件，並把環境變數 `GCP_SA_KEY`
（服務帳戶金鑰）寫成憑證檔。之後一律用 **`python3 scripts/gcp_agent.py`**（不需要 gcloud）：

| 想做什麼 | 指令 |
|---|---|
| 確認憑證、專案、已啟用 API | `python3 scripts/gcp_agent.py whoami` |
| 服務狀態、網址、修訂、環境變數 | `python3 scripts/gcp_agent.py status` |
| 看日誌 | `python3 scripts/gcp_agent.py logs --since 2h --limit 100 [--grep 已送出] [--severity WARNING]` |
| 電閘／加單／決策日誌 | `python3 scripts/gcp_agent.py state` |
| bucket 內容 | `python3 scripts/gcp_agent.py bucket --prefix logs/`、`cat --object logs/last_order_sent.json` |
| 頁面是否正常（首頁、策略總表、龍飛陣、基金報告、蛇蟠陣） | `python3 scripts/gcp_agent.py check`（雲端容器的網路政策可能擋 `*.run.app`，被擋時請使用者在環境設定放行） |
| 看環境變數 | `python3 scripts/gcp_agent.py env get` |
| 改參數（環境變數） | `python3 scripts/gcp_agent.py env set KEY=VAL`（先看計畫）→ 使用者同意後加 `--yes` |
| 列出版本與流量 | `python3 scripts/gcp_agent.py revisions` |
| 退回舊版本 | `python3 scripts/gcp_agent.py rollback [--to 修訂名]`（先看計畫）→ 同意後加 `--yes` |
| 部署新程式 | `python3 scripts/gcp_agent.py deploy`（dry-run：來源檢查＋計畫＋缺少的權限）→ 同意後加 `--yes` |
| 只做本機來源檢查 | `python3 scripts/gcp_agent.py deploy --local-only`（不連線） |
| 🌌 天覆陣（`xau/`，獨立服務 `zhuge-xau`） | 全域參數 `--profile xau`，例如 `gcp_agent.py --profile xau status`、`--profile xau deploy`（服務不存在會**建立**，先 dry-run；不改 IAM，「允許未經驗證的叫用」由使用者在控制台開）、`--profile xau env set …` |

預設模式是 `--target run`：Cloud Run 服務 `zhuge-risk-manager`、區域 `europe-west1`
（可用 `GCP_SERVICE`、`GCP_RUN_REGION` 或 `--service`、`--region` 改）。全域參數要放在子命令**前面**，
例如 `gcp_agent.py --region asia-east1 status`。

run 模式的寫入流程：`env set/unset` 用目前的程式碼映像建立新修訂；`deploy` 上傳 zip → Cloud Build
（沿用服務的 buildConfig：buildpacks、進入點 `receive_tradingview_signal`）→ 換上新映像建立新修訂。
兩者都先 validateOnly 再套用，100% 流量切到新修訂，舊修訂保留；出事就 `rollback`（只切流量、不建新修訂、不刪東西）。
每次寫入後把 `rollback --to <舊修訂> --yes` 指令告訴使用者。`iam-public` 在 run 模式不提供。
部署需要服務帳戶有 Cloud Build 編輯者與 `run-sources-<專案>-europe-west1` bucket 的物件建立權限；
`deploy` dry-run 會列出缺哪些，缺的話請使用者依 `AGENTIC.md` 到 IAM 加，不要自己改 IAM。
`--target function`（或 `GCP_TARGET=function`）是舊的 Cloud Functions 流程，區域用 `GCP_REGION`（預設 asia-east1）；
在那個模式下 `deploy --yes` 會**另外建立一個新函式**，不會更新正在跑的 Cloud Run 服務，除非使用者明確要求，否則不要用。
`whoami` 失敗且訊息是「找不到 GCP 憑證」時，請使用者依 `AGENTIC.md` 在雲端環境設定加入 `GCP_SA_KEY`，
不要請他把金鑰貼進對話。

## 安全規則（務必遵守）

1. **這個系統會對真實帳戶送單。** 部署與改環境變數前先跑 dry-run，把「將會做什麼」告訴使用者；
   只有使用者明確要求部署／修改時才加 `--yes`。讀取類命令（status / logs / state / check）可自由執行。
2. 部署前一定先做 `python3.11 -m py_compile main.py`（**Cloud Run 執行階段係 Python 3.11**；本機 python3 係 3.13，3.12+ 先容許嘅 f-string 巢狀同款引號會令 Cloud Build 失敗）與 `deploy` dry-run 的來源檢查；部署檔案
   （`main.py`、`requirements.txt`、`bazhentu.html`、`factsheet.html`；R253 起舊 XAUUSD 四頁已移除）必須完整。
   `futu/`、`tests/`、`scripts/`、`data/` 不部署（見 `.gcloudignore`）。
3. 不要印出、記錄或 commit 任何金鑰與權杖（`WEBHOOK_SECRET_TOKEN`、`WEBHOOK_API_KEY`、`GCP_SA_KEY`）。
   `gcp_agent.py` 對含 TOKEN/SECRET/KEY 的值、以及網址的查詢參數（例如 `BROKER_API_URL` 的 `?t=…`）會自動遮罩，請保持。
4. 不要刪 bucket 物件、不要刪函式、不要改 IAM（除了 `iam-public` 這個既定步驟），除非使用者明確要求。
5. 不要用 `gcp_agent.py` 以外的方法繞過 dry-run（例如自己組 REST 請求去部署）。
6. 改完 `main.py` 要部署時，先跑 `python3 -m unittest scripts/test_gcp_agent.py`（工具本身的測試）與
   `python3 tests/test_wsgi_app.py`（確認模組還能匯入、路由正常），再部署。（R253 刪咗舊黃金回測 `backtest.py`）

## VM（ib-data／claude-ops）規則

- 香港不在 Claude 的支援地區，所以香港的 `ib-data` 不能裝 Claude；台灣的 `claude-ops` 跑另一個 Claude 用手機遙控。**不要用 VPN／代理繞過地區限制。**
- 你（雲端工作階段）**不要嘗試 SSH 進 ib-data**，也不要幫使用者建立「遠端執行指令」的通道；需要在 ib-data 上做的事，
  由使用者用瀏覽器 SSH 執行，你一步一步教（先看提示符是 `@ib-data` 還是 `@claude-ops`）。
- 任何改動 `claudeops` 使用者、`/srv/ibshare`、家目錄或 `config.ini` 權限的建議，都要附上 `AGENTIC.md`「必跑這個檢查」那一條，並要求使用者貼回結果，
  **三行都拒絕才算通過**。
- 使用者提到要用**新的、有資金的 IBKR 戶口**時，先提醒 `AGENTIC.md`「IBKR 戶口」的入金前檢查清單。
- 架構與細節見 `AGENTIC.md`「VM：ib-data 與 claude-ops」。

## 專案慣例

- 語言：說明文件、commit 訊息、給使用者的回覆用繁體中文；程式註解中英皆可。
- 時間：日誌與報表以香港時間（UTC+8）顯示；`main.py` 內部用 UTC 與美東時間。
- GitHub Actions 的排程 workflow 只在預設分支生效；部署用的 `gcp_deploy.yml` 是手動觸發。
- 部署教學在 `DEPLOY.md`；讓 Claude 代管 GCP 的設定在 `AGENTIC.md`；策略與回測在 `BACKTEST.md`、`research/`。
- 全基金的每日流程盤點、各陣工作階段與排程總表、SOP 缺口與優先順序在 `FUND_SOP.md`（2026-10-13 SOP 顧問報告）。
- **總指揮**：工作階段 `session_01ELtWSJc46vAFMT4oh3fCTV`（2026-10-18 起新工作階段；舊 `session_012CwdLPmAQvC91GZs5Jg9XA`、`session_01N1jfpEJciBkfAgwtd4QxgU` 保留；分支 `claude/beautiful-hypatia-8qrgjj`，2026-10-11 使用者委任）負責富途實倉監控、
  按陣配對（`main.py` 的 `FUTU_TEAM_RULES`，策略總表「💼 富途實倉」）、風險警報與通知各陣。喺富途戶口開新實倉前，先登記 `POSITIONS.md`
  並用 `send_message` 通知總指揮加配對規則；配對唔到嘅會入「未配對」並發 Telegram。
- **各陣工作階段 id 以 `handoff/SESSIONS.md` 為準**（2026-10-14 起各陣換新工作階段，舊嘅保留；send_message 前先讀）；各陣交接文件在各自分支 `handoff/<陣>.md`。
- **各陣真實持倉登記在 `POSITIONS.md`**：開倉、平倉要更新並合併到預設分支；開新一輪前先讀它與 GCS `futu/risk/latest.json`（富途即時持倉與按金緩衝）。
- **風控階梯在 `RISK_LADDER.md`**（總指揮擁有）：Ⓐ觀察／Ⓑ停開新倉／Ⓒ減半／Ⓓ全平嘅觸發線、夜盤線、人手額度；各陣 SOP 引用它。
  每日 17:20 HKT workflow `ops_daily_books.yml` 跑 `scripts/daily_books.py`：對帳表 `research/reconcile/<日>.md`（富途快照／POSITIONS.md／各陣 journal 三方並列，
  ⚠ 原因填 `research/reconcile/explanations.json`，連續兩日未解釋升級 Ⓑ）、逐日損益帳 GCS `ops/books/pnl_daily.csv`（含權益，私人，唔推公開 repo）。
- **交易想法登記在 `IDEAS.md`**：先登記（假說、預先登記成功標準、資料區間）後回測；棄用必寫原因。開新實倉前先把該想法改成「實倉」。
  每週 workflow `screener_scorecard.yml` 產生 `research/screener_scorecard/SCORECARD.md`（篩選器前瞻命中率對照隨機成分股）與
  `research/divergence/DIVERGENCE.md`（實倉／紙上對回測期望的偏離燈號，期望登記在 `expectations.json`）；判決變了就回 `IDEAS.md` 改狀態。
  `research/harness_learning/` 是論文 arXiv:2609.35738 的修訂迴圈實作，評分卡的 `*_report.txt` 就是給 proposer 讀的執行報告。

## 檢查指令

```bash
python3.11 -m py_compile main.py          # Cloud Run 係 3.11；本機 python3 太新會漏掉語法錯誤
python3 -m py_compile scripts/*.py
python3 -m unittest scripts/test_gcp_agent.py -v
python3 scripts/gcp_agent.py deploy          # 離線也能跑：打包 + 來源檢查
```
