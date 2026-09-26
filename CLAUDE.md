# CLAUDE.md — 給 Claude 的工作說明

本 repo 是「智能諸葛亮」XAUUSD 量化交易系統：`main.py` 是 GCP Cloud Functions（第 2 代）的進入點
`receive_tradingview_signal`，狀態全部存在 GCS bucket `zhuge-risk-manager-bucket`。
`scripts/` 與 `data/` 是 GitHub Actions 跑的研究／追蹤腳本，不會部署到 Cloud Function。

## 你可以直接操作使用者的 GCP

工作階段啟動時 `.claude/hooks/session-start.sh` 會安裝套件，並把環境變數 `GCP_SA_KEY`
（服務帳戶金鑰）寫成憑證檔。之後一律用 **`python3 scripts/gcp_agent.py`**（不需要 gcloud）：

| 想做什麼 | 指令 |
|---|---|
| 確認憑證、專案、已啟用 API | `python3 scripts/gcp_agent.py whoami` |
| 函式狀態、網址、環境變數 | `python3 scripts/gcp_agent.py status` |
| 看日誌 | `python3 scripts/gcp_agent.py logs --since 2h --limit 100 [--grep 已送出] [--severity WARNING]` |
| 電閘／加單／決策日誌 | `python3 scripts/gcp_agent.py state` |
| bucket 內容 | `python3 scripts/gcp_agent.py bucket --prefix logs/`、`cat --object logs/last_order_sent.json` |
| 五個頁面是否正常 | `python3 scripts/gcp_agent.py check` |
| 改環境變數 | `python3 scripts/gcp_agent.py env set KEY=VAL`（先看計畫）→ 加 `--yes` 套用 |
| 部署 | `python3 scripts/gcp_agent.py deploy`（dry-run）→ 加 `--yes` 真的部署 |

區域預設 `asia-east1`；使用者若說函式在別的區域，加 `--region asia-east2` 或設 `GCP_REGION`。
`whoami` 失敗且訊息是「找不到 GCP 憑證」時，請使用者依 `AGENTIC.md` 在雲端環境設定加入 `GCP_SA_KEY`，
不要請他把金鑰貼進對話。

## 安全規則（務必遵守）

1. **這個系統會對真實帳戶送單。** 部署與改環境變數前先跑 dry-run，把「將會做什麼」告訴使用者；
   只有使用者明確要求部署／修改時才加 `--yes`。讀取類命令（status / logs / state / check）可自由執行。
2. 部署前一定先做 `python3 -m py_compile main.py` 與 `deploy` dry-run 的來源檢查；四個檔案
   （`main.py`、`requirements.txt`、`gates.html`、`order.html`）必須完整。
3. 不要印出、記錄或 commit 任何金鑰與權杖（`WEBHOOK_SECRET_TOKEN`、`WEBHOOK_API_KEY`、`GCP_SA_KEY`）。
   `gcp_agent.py` 對含 TOKEN/SECRET/KEY 的值會自動遮罩，請保持。
4. 不要刪 bucket 物件、不要刪函式、不要改 IAM（除了 `iam-public` 這個既定步驟），除非使用者明確要求。
5. 不要用 `gcp_agent.py` 以外的方法繞過 dry-run（例如自己組 REST 請求去部署）。
6. 改完 `main.py` 要部署時，先跑 `python3 -m unittest scripts/test_gcp_agent.py`（工具本身的測試）與
   `python3 backtest.py --help`（確認模組還能匯入），再部署。

## 專案慣例

- 語言：說明文件、commit 訊息、給使用者的回覆用繁體中文；程式註解中英皆可。
- 時間：日誌與報表以香港時間（UTC+8）顯示；`main.py` 內部用 UTC 與美東時間。
- GitHub Actions 的排程 workflow 只在預設分支生效；部署用的 `gcp_deploy.yml` 是手動觸發。
- 部署教學在 `DEPLOY.md`；讓 Claude 代管 GCP 的設定在 `AGENTIC.md`；策略與回測在 `BACKTEST.md`、`research/`。

## 檢查指令

```bash
python3 -m py_compile main.py backtest.py scripts/*.py
python3 -m unittest scripts/test_gcp_agent.py -v
python3 scripts/gcp_agent.py deploy          # 離線也能跑：打包 + 來源檢查
```
