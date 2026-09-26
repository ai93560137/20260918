# 讓 Claude 在你的 GCP 執行任務（Agentic 設定）

目標：在 claude.ai / Claude Code 對 Claude 說「看一下 GCP 日誌」「部署最新的 main.py」
「TARGET_RRR 改成 2」，它就直接在你的 GCP 專案做，並把結果回報給你。

整套做法不需要在 Claude 的容器裝 gcloud（該容器的網路不允許下載 gcloud），全部靠
`scripts/gcp_agent.py` 用 REST API 操作。

```
你（claude.ai / Claude Code）
   │  自然語言指令
   ▼
Claude 工作階段（雲端容器，讀 CLAUDE.md 知道規則）
   │  python3 scripts/gcp_agent.py …   ← 用 GCP_SA_KEY 服務帳戶認證
   ▼
你的 GCP 專案
   ├─ Cloud Functions 第 2 代 receive_tradingview_signal（部署 / 狀態 / 環境變數）
   ├─ Cloud Logging（讀日誌）
   ├─ Cloud Storage zhuge-risk-manager-bucket（電閘、加單、決策日誌、送單參數）
   └─ Cloud Run IAM（允許未經驗證的叫用）
```

另外有一條「零金鑰」路線：Claude 把程式 push 到 GitHub，再觸發 `.github/workflows/gcp_deploy.yml`，
由 GitHub Actions 用 Workload Identity Federation 部署。兩條路線可以同時存在。

---

## 香港 Google 帳戶要注意的事

### 先講最重要的：Google 帳戶是香港的，跟能不能用 claude.ai 無關

- claude.ai 只是「用 Google 登入」，**不會看你的 Google 帳戶是哪個地區**。決定能不能用的是 Anthropic 的支援地區清單，
  以及你實際所在的位置（IP、手機號碼驗證、付款地址）。
- Anthropic 官方清單（https://www.anthropic.com/supported-countries）目前**沒有香港、澳門與中國大陸**；台灣、新加坡、日本都在清單上，
  claude.ai 與 Claude API 皆同。Anthropic 發言人亦曾表示 Claude「從未正式支援香港」。
- 所以：人在香港、用香港 IP 與 +852 號碼註冊或登入 claude.ai 會被拒絕；人在台灣、新加坡、日本等支援地區則可以正常用，
  Google 帳戶是香港的也沒關係。用 VPN 繞過屬於違反 Anthropic 使用政策，帳號可能被停用，本文件不建議。
- **GCP 那一邊完全不受影響**：香港 Google 帳戶開 GCP 專案、部署函式、讓 Claude 透過服務帳戶操作，都沒有問題（見下表）。
  Claude 的工作階段跑在 Anthropic 的雲端容器，連 GCP 的是那個容器，不是你的香港網路。
- Google Cloud 的 Vertex AI Model Garden 也提供 Claude 模型，但同樣受 Anthropic 使用政策約束；是否對香港帳單地址的專案開放，
  請以 Google Cloud 主控台實際能否啟用為準，本文件不作保證。

### GCP 各服務對香港帳戶的狀況

| 項目 | 狀況 |
|---|---|
| 開 GCP 專案、Cloud Functions、Cloud Run、Cloud Storage、Cloud Logging | **香港帳戶完全可用**，帳單可用 HKD 或 USD 信用卡 |
| 區域 | `asia-east2` 就是香港機房，延遲最低；`asia-east1`（台灣）也很近，兩者都支援第 2 代函式。DEPLOY.md 用 `asia-east1`，維持即可；要改就在 `GCP_REGION` 或 `--region` 指定 |
| Vertex AI（`main.py` 的 Gemini 覆核） | Vertex AI 走 GCP 專案，香港帳戶可用；但 Gemini 模型**不在 `asia-east2` 提供**，`main.py` 預設 `AI_LOCATION=us-central1`，不要改成香港。不想用 AI 覆核就設 `AI_REVIEW_ENABLED=0` |
| Google AI Studio（免費 Gemini API key） | 香港**不提供**，所以本專案一律走 Vertex AI，不用 AI Studio 金鑰 |
| Cloud Shell | 可用，建議在 Cloud Shell 跑下面的 bootstrap 腳本，免裝 gcloud |

---

## 第 1 步：在 GCP 建立 Claude 用的服務帳戶（只做一次，約 3 分鐘）

1. 開 https://shell.cloud.google.com （用你的香港 Google 帳戶登入）。
2. 把本 repo 抓下來並執行 bootstrap：

```bash
git clone https://github.com/ai93560137/20260918.git && cd 20260918
bash scripts/gcp_bootstrap.sh 你的專案ID asia-east1
# 想同時設定 GitHub Actions 零金鑰部署：
# bash scripts/gcp_bootstrap.sh 你的專案ID asia-east1 --github ai93560137/20260918
```

腳本會：啟用 API、確認 bucket、建立服務帳戶 `claude-agent@專案.iam.gserviceaccount.com`、
授與以下角色（都是「剛好夠用」，不含刪專案、開機器、看帳單）：

| 角色 | 範圍 | 用途 |
|---|---|---|
| Cloud Functions Developer | 專案 | 部署 / 更新函式、改環境變數 |
| Cloud Run Admin | 專案 | 讀函式網址、設定允許未經驗證的叫用 |
| Logs Viewer | 專案 | 讀日誌 |
| Service Usage Viewer | 專案 | `whoami` 列出已啟用 API |
| Artifact Registry Reader | 專案 | 部署時讀建構映像 |
| Storage Object Admin | **只限** `zhuge-risk-manager-bucket` | 讀狀態、必要時修正狀態檔 |
| Service Account User | 只限預設 Compute 服務帳戶 | 部署時以該帳戶為執行階段身分 |

最後印出一行 base64 金鑰。**不要貼進聊天，也不要 commit。**

## 第 2 步：把金鑰交給 Claude 的雲端環境

在 claude.ai/code 的工作階段標題列 → 雲端環境選單 → **Edit**：

| 環境變數 | 值 |
|---|---|
| `GCP_SA_KEY` | bootstrap 印出的那一行 base64（或整段 JSON） |
| `GCP_REGION` | `asia-east1`（或你函式所在區域） |
| `GCP_PROJECT` | 可省略，金鑰內已含 |

網路存取：需要能連 `*.googleapis.com`（預設的網路政策已可連）。儲存後，**新的**工作階段才會生效。

## 第 3 步：驗證

開一個新的 Claude 工作階段（本 repo），對它說：

> 跑 `python3 scripts/gcp_agent.py whoami` 和 `status`，告訴我函式狀態。

看到帳戶、專案、API 都是 ✅ 就完成了。

---

## 之後怎麼用（範例對話）

| 你說 | Claude 做 |
|---|---|
| 「最近兩小時有沒有送單？」 | `logs --since 2h --grep 已送出`，整理成表 |
| 「電閘現在是什麼狀態？」 | `state`，解讀 regime / armed / hard lock |
| 「把 TARGET_RRR 改成 2」 | `env set TARGET_RRR=2` 先給你看計畫 → 你說「確定」→ `--yes` |
| 「部署我剛改好的 main.py」 | `py_compile` → `deploy`（dry-run 檢查四個檔案）→ 你確認 → `deploy --yes` → `check` 五個頁面 |
| 「五個頁面還正常嗎？」 | `check` |
| 「昨天有沒有 WARNING 以上的錯誤？」 | `logs --since 1d --severity WARNING` |

規則（寫在 `CLAUDE.md`，Claude 每次工作階段都會讀）：**任何會改動 GCP 的動作都先 dry-run、經你確認才執行**；
讀取類動作可自由執行；金鑰與權杖一律遮罩。

---

## 讓 Claude 自動排程（選用）

Claude Code 的 Routines 可以每天固定時間開一個新工作階段執行指令，例如：

> 每個交易日香港時間 07:30 開新工作階段，跑 `logs --since 24h --severity WARNING` 與 `state`，
> 有異常就在對話裡摘要。

對 Claude 說「幫我建立每天早上檢查 GCP 的例行工作」即可，它會用 `create_trigger` 建立
（環境必須已設定 `GCP_SA_KEY`）。

---

## 零金鑰路線：GitHub Actions 部署

1. bootstrap 時加 `--github ai93560137/20260918`，把印出的兩個值加到 GitHub repo secrets：
   `GCP_WORKLOAD_IDENTITY_PROVIDER`、`GCP_SERVICE_ACCOUNT`。
2. 把 `gcp_deploy.yml` 合併到預設分支（GitHub 只在預設分支顯示手動 workflow）。
3. Actions → **GCP deploy** → Run workflow：填 ref（要部署的分支）、region、把 dry_run 取消勾選。
   Claude 也可以透過 GitHub 工具替你觸發。

這條路線 GitHub 與 Claude 都不持有任何金鑰，GCP 只信任來自 `ai93560137/20260918` 這個 repo 的 Actions。

---

## 收回權限

```bash
# 撤銷金鑰（Claude 立刻無法再操作）
gcloud iam service-accounts keys list   --iam-account=claude-agent@專案ID.iam.gserviceaccount.com
gcloud iam service-accounts keys delete KEY_ID --iam-account=claude-agent@專案ID.iam.gserviceaccount.com
# 或整個停用服務帳戶
gcloud iam service-accounts disable claude-agent@專案ID.iam.gserviceaccount.com
```

同時到 Claude 雲端環境設定刪掉 `GCP_SA_KEY`。

## 疑難排解

| 症狀 | 處理 |
|---|---|
| `找不到 GCP 憑證` | 環境變數 `GCP_SA_KEY` 沒設，或設完沒開新工作階段 |
| `google-auth 載入失敗` | 執行 `pip install --user -r scripts/requirements-agent.txt`（hook 平常會自動做） |
| `HTTP 403 … PERMISSION_DENIED` | 重跑 bootstrap（它是冪等的），或該 API 沒啟用；看 `whoami` 的 API 清單 |
| `HTTP 404` 讀函式 | 區域不對：`--region asia-east2` 或改 `GCP_REGION` |
| 部署卡在 `BUILD` 超過 10 分鐘 | 到 Console → Cloud Build 看建構日誌，通常是 `requirements.txt` 套件裝不起來 |
| 日誌是空的 | 第 2 代函式的日誌在 Cloud Run 修訂底下；`logs` 已同時查兩種資源，若仍空代表期間內真的沒有請求 |
