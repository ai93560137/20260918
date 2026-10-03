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
   ├─ Cloud Run 服務 zhuge-risk-manager（europe-west1，目前實際在跑；狀態 / 日誌 / 改參數 / 部署 / 回滾）
   ├─ Cloud Functions 第 2 代 receive_tradingview_signal（舊流程，--target function）
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
| `GCP_RUN_REGION` | 可省略，預設 `europe-west1`（Cloud Run 服務所在區域） |
| `GCP_REGION` | 可省略；只有 `--target function` 舊流程會用，預設 `asia-east1` |
| `GCP_PROJECT` | 可省略，金鑰內已含 |

網路存取：需要能連 `*.googleapis.com`（預設的網路政策已可連）。儲存後，**新的**工作階段才會生效。

## 第 3 步：驗證

開一個新的 Claude 工作階段（本 repo），對它說：

> 跑 `python3 scripts/gcp_agent.py whoami` 和 `status`，告訴我服務狀態。

看到帳戶、專案、API 都是 ✅ 就完成了。

---

## 之後怎麼用（範例對話）

| 你說 | Claude 做 |
|---|---|
| 「最近兩小時有沒有送單？」 | `logs --since 2h --grep 已送出`，整理成表 |
| 「電閘現在是什麼狀態？」 | `state`，解讀 regime / armed / hard lock |
| 「把 TARGET_RRR 改成 2」 | `env set TARGET_RRR=2` 先給你看計畫 → 你說「確定」→ `--yes`（建立新修訂，舊修訂保留） |
| 「部署我剛改好的 main.py」 | `py_compile` + 測試 → `deploy`（dry-run：檢查六個部署檔案、列計畫與缺少的權限）→ 你確認 → `deploy --yes` → `check` 五個頁面 |
| 「剛剛那版有問題，退回去」 | `rollback` 先給你看要切回哪個修訂 → 你確認 → `--yes`（只切流量，幾秒生效） |
| 「現在有哪些版本？」 | `revisions` |
| 「五個頁面還正常嗎？」 | `check` |
| 「昨天有沒有 WARNING 以上的錯誤？」 | `logs --since 1d --severity WARNING` |

規則（寫在 `CLAUDE.md`，Claude 每次工作階段都會讀）：**任何會改動 GCP 的動作都先 dry-run、經你確認才執行**；
讀取類動作可自由執行；金鑰與權杖一律遮罩。

---

## 讓 Claude 部署到 Cloud Run 需要的權限

改參數和回滾只需要「Cloud Run 開發人員」＋「以服務帳戶身分執行」（一般已有）。**部署新程式**另外需要兩個權限，
在 GCP 主控台 → **IAM 與管理** → **IAM** → 找到 `claude-agent@…` 那一列 → 鉛筆圖示 → **新增其他角色**：

| 角色 | 用途 |
|---|---|
| **Cloud Build 編輯者**（`roles/cloudbuild.builds.editor`） | 送出建置 |
| **Storage 物件建立者**（`roles/storage.objectCreator`） | 上傳原始碼 zip 到 `run-sources-<專案>-europe-west1` |

加完後請 Claude 跑 `deploy`（dry-run），確認「缺少的權限」清單消失即可。

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

## VM：ib-data 與 claude-ops（2026-09-29 建立）

### 為什麼有兩台 VM
- **`ib-data`**（`asia-east2-a`＝**香港**，e2-small，Debian 12）：跑 IB Gateway（IBC 自動登入）與外匯／指數的 IV 採集。
- **Claude 不支援香港**：在 ib-data 上安裝 Claude Code 會得到「App unavailable in region」的網頁，就算硬裝也連不上。
  **不要用 VPN 或代理去繞過**，那違反使用規定。支援地區以 https://www.anthropic.com/supported-countries 為準（台灣、新加坡、日本、南韓、美國都支援）。
- **`claude-ops`**（`asia-east1-b`＝台灣，e2-small，Debian 13，**不綁服務帳戶**、沒有任何 GCP 權限）：專門跑一個 Claude Code，
  用手機 App／claude.ai/code 遙控（Remote Control），再用低權限使用者 `ssh` 進 ib-data「唯讀查看」。

### 誰能做什麼
| 角色 | 能做 | 不能做 |
|---|---|---|
| **雲端工作階段**（有 `GCP_SA_KEY` 的那個 Claude） | Cloud Run、日誌、bucket、GitHub、改程式開 PR | 不連進 ib-data，也不對它執行指令 |
| **claude-ops 上的 Claude**（手機遙控） | `ssh ibdata` 讀 `/srv/ibshare`；每條會執行程式的指令都先問使用者 | 讀 ib-data 其他檔案、sudo、改排程、連 IB API 下單 |
| **使用者** | 用瀏覽器 SSH 進 ib-data 做任何需要改動的事（改排程、改設定、重啟 Gateway） | — |

### claude-ops 怎麼運作
- systemd 使用者服務 `claude-rc`（`~/.config/systemd/user/claude-rc.service`，已 `enable`＋`loginctl enable-linger`）
  在 tmux 裡執行 `claude remote-control --permission-mode manual --name claude-ops`，工作目錄 `~/work`。
- `~/work/CLAUDE.md` 是給那個 Claude 的規則（只查看、不 sudo、不讀其他使用者檔案、不下單、不印金鑰）。
- 手機 App 的 Code 分頁會看到名為 `claude-ops` 的工作階段。**權限模式**：讀取類指令與寫入 `~/work` 內的檔案不會問；
  執行程式、連網路的指令（例如 `ssh`、`curl`）會跳出詢問。這一點已實測（`curl`、`ssh ibdata whoami` 都有詢問）。
- 已實測（2026-09-29 15:11 HKT 重開機）：重開後手機自動連得上，`hostname` 正常回覆，`curl` 仍然先跳出詢問。
  萬一哪天連不上，SSH 進去跑 `systemctl --user status claude-rc --no-pager | head -12; tmux ls`。

### claude-ops → ib-data 的連線與隔離
- `claude-ops:~/.ssh/config` 有 `Host ibdata`（使用者 `claudeops`、金鑰 `~/.ssh/ib_data_claudeops`，無密碼）。
- ib-data 端 `claudeops` 的 `authorized_keys` 用 `from="10.140.0.2"`（只允許 claude-ops 的內部 IP）、`no-port-forwarding`、
  `no-agent-forwarding`、`no-X11-forwarding`。`claudeops` **沒有 sudo**。
- 使用者 `hengkychansinghing` 的家目錄 `700`、`~/ibc/config.ini`（IB 帳密）`600`。
  這是**硬性**隔離；`CLAUDE.md` 的規則只是軟性的第二道防線。
- **共享資料夾 `/srv/ibshare`**（擁有者 `hengkychansinghing:claudeops`，`2750`）：`~/ibshare_sync.sh` 由 cron 每 5 分鐘複製
  `ib_daily.log`、`fx_autopush.log`、`fx_status.txt`、`ib_iv_log_tail.csv`、`health.txt`（主機負載、磁碟、進程名稱、監聽埠、排程）。
  **不複製**任何設定檔、`ibc/`、`Jts/`、`ibgw.log`。要分享新檔案，先確認裡面沒有帳密，再改 `ibshare_sync.sh`。
- IB Gateway API（4002）用 iptables 限制為只接受本機：
  `iptables -I INPUT -p tcp --dport 4002 ! -s 127.0.0.1 -j DROP`，並用 `@reboot` cron 重新套用（尚未實測重開機）。

### 資料搬運與自動化（不要把 GitHub 憑證交給 claudeops）
- `claudeops` 沒有任何 GitHub 憑證，所以**它產生的檔案推不上 GitHub**，這是刻意的。要把資料交出去，由使用者用 `hengkychansinghing`
  （已有推送設定，每日採集就是用它）操作。**不要靠瀏覽器 SSH 視窗的「下載檔案」搬檔案**（實測常常下載不到）。
- 一次性手動推送的做法（2026-09-29 推 `data/vol` 到 `claude/us-intl-data-stock-market-vgt0yi` 就是這樣做的）：
  暫存 `git worktree` → `sudo cp` 檔案過來 → `git add` → 關鍵字掃描（password／token／secret／api key）→ 使用者輸入完整的 `yes` 才 commit＋push → 清掉暫存。
- **長期要重複做的事，一律做成使用者帳號的 cron，不要每次靠人或 AI 手動跑**。IBKR 波動率日線（VIX、TLT／IEF 隱含波動率、ZN／ZB／NQ…）
  已寫成 `gcp_ib/run_vol_daily.sh`（PR #23）：平日 UTC 22:30 增量匯出、推到**專用資料分支 `data/ibkr-vol`**（獨立資料 repo `~/ibkr-vol-data`，只含 `data/vol/`，
  與程式分支分開，取用方式：`git fetch origin data/ibkr-vol && git checkout origin/data/ibkr-vol -- data/vol`）。
  匯出程式是固定的一份複本（目前為 `364cb1eb` 版，含 QQQ／SPY／GLD 長歷史），不直接執行別的分支。
  2026-09-29 已在 ib-data 實跑並加入 cron；一次性長歷史回補用 `VOL_EXPORT_ARGS="--backfill --only tlt qqq spy gld" bash gcp_ib/run_vol_daily.sh`。
  排程中斷後（例如 Gateway 停擺）重跑一次 `bash ~/20260918/gcp_ib/run_vol_daily.sh` 就會自動補齊缺的日子；
  但外匯 IV 日誌只記當天快照，**停擺期間的日子補不回來**。
- 已知資料缺口：IBKR 取不到 **MOVE**（缺 NYBOT 指數行情訂閱），用 `tlt_iv`、`ief_iv` 搭配 `tnx` 替代；XAUUSD 由 MT5 提供，不在這條匯出裡。
- 外匯期權每日採集（`gcp_ib/run_daily.sh`，平日 UTC 07:35，含 6E／6J）：2026-09-29 第一次執行時 6J 缺列（剩 1 天的週權當下沒有報價）；
  PR #22 已加上「某一腿拿不到 IV 就改試下一個到期日」與失敗原因日誌。若 6J 之後**每天**都缺，代表延遲行情對這些週權本來就沒有 IV，需要另外處理。
- 跨 session 通知：**離線的雲端 session 用 `SendMessage` 傳不到**（`ListAgents` 不會列出）。改在該分支對應的 PR 留言
  （例如 `claude/us-intl-data-stock-market-vgt0yi` 對應 PR #7），對方下次啟動或使用者打開 PR 時看得到。
- ib-data 上的 IB Gateway 是 **live 模式**（`TradingMode=live`，戶口餘額約 4 美元、不能入金），但使用埠 **4002**；
  部分腳本註解把 4002 稱為「模擬帳戶」，那只是說明文字，不代表實際模式。

### 改動 claudeops 權限或家目錄權限後，必跑這個檢查
在 claude-ops 的 SSH 視窗（使用者自己跑，不要交給 Claude）：
```bash
ssh ibdata 'sudo -n true 2>&1 | head -1; cat /home/hengkychansinghing/ibc/config.ini 2>&1 | head -1; ls /home/hengkychansinghing 2>&1 | head -1'
```
**三行都必須是拒絕**：`sudo: a password is required`、兩行 `Permission denied`。任何一行印出內容，立刻停止，先修權限。
（建立當天這個檢查抓到過問題：家目錄 `755`、`config.ini` 不是 `600`，已修正。）

### IBKR 戶口
- 目前 ib-data 登入的是一個**真實（live）戶口**，但因名字問題**已不能入金**，餘額約 4 美元；`config.ini` 的 `TradingMode=live`、`ReadOnlyApi` 為空。
- 將來入金會用**另一個 IBKR 戶口**。**使用新戶口之前**先過這份清單，不要直接接到現有 Gateway：
  1. API 設成唯讀（`ReadOnlyApi=yes`），除非那台機器真的要下單；
  2. 4002／4001 只接受本機連線，重開機後仍有效；
  3. 移除 claude-ops 的授權金鑰，或確定 `claudeops` 碰不到 API；
  4. 交易程式與資料採集分開（不同帳號或不同機器）。

### IB Gateway 重啟後卡在「免責聲明」（2026-10-03 實際發生）
- **症狀**：所有採集一起停（`data/ibkr-vol` 與外匯 IV 日誌不再有新日期），但 VM 還開著。2026-09-30 到 10-02 因此缺三天。
  Gateway 重啟後停在登入後的免責聲明，沒人按「接受」就不會開 API 連線。
- **確認**：先在 claude-ops 看 `ssh ibdata 'tail -15 /srv/ibshare/health.txt; tail -8 /srv/ibshare/ib_daily.log'`。
- **處理**：用 VNC 到 ib-data 的 Gateway 視窗按接受。畫面上要看到 API Server `connected`、Market Data Farm 與 Historical Data Farm 都是 `ON`。
  之後在 ib-data 以 `hengkychansinghing` 手動跑一次 `bash ~/20260918/gcp_ib/run_vol_daily.sh` 補日線。
- **安全**：VNC 只能經 **SSH 通道連本機**（`localhost:5900`），**不要對外開 5900 埠**；用完關掉視窗並 `pkill x11vnc`，不要常駐。
  這個步驟由使用者自己做，不要交給 claudeops（它不該碰 Gateway 畫面或帳密）。

### 常見狀況
| 症狀 | 處理 |
|---|---|
| `claude: command not found`，但裝好了 | 指令要**全小寫**（手機輸入常把第一個字母變大寫）；仍找不到就 `~/.local/bin/claude --version`，再把 `~/.local/bin` 加進 `PATH` |
| 採集突然全停、資料日期不再更新 | 多半是 Gateway 卡在免責聲明，見上一節「IB Gateway 重啟後卡在免責聲明」 |
| 貼指令貼到錯的機器 | 貼之前看提示符：`@claude-ops`（台灣）或 `@ib-data`（香港，有 IB 帳密） |
| 遠端桌面畫面上的文字不能複製 | 從對話複製指令貼進去；要搬檔案用 SSH 視窗上方的「上傳檔案／下載檔案」（`.ssh` 資料夾內的檔案要先複製到家目錄才能下載）。**永遠不要搬私鑰** |
| 雲端環境連不到 `*.run.app` | 環境設定 → Network access → **Custom**，Allowed domains 加 `*.run.app`，並勾選「Also include default list of common package managers」 |

## 收回權限

```bash
# 撤銷金鑰（Claude 立刻無法再操作）
gcloud iam service-accounts keys list   --iam-account=claude-agent@專案ID.iam.gserviceaccount.com
gcloud iam service-accounts keys delete KEY_ID --iam-account=claude-agent@專案ID.iam.gserviceaccount.com
# 或整個停用服務帳戶
gcloud iam service-accounts disable claude-agent@專案ID.iam.gserviceaccount.com
```

同時到 Claude 雲端環境設定刪掉 `GCP_SA_KEY`。

**收回 claude-ops 對 ib-data 的存取**（在 ib-data 上）：
```bash
sudo rm -f /home/claudeops/.ssh/authorized_keys      # 金鑰立刻失效
# 更徹底：sudo deluser claudeops
```
要停掉 claude-ops 的遙控：在 claude-ops 上 `systemctl --user disable --now claude-rc`，或直接在主控台停止／刪除該 VM。

## 疑難排解

| 症狀 | 處理 |
|---|---|
| `找不到 GCP 憑證` | 環境變數 `GCP_SA_KEY` 沒設，或設完沒開新工作階段 |
| `google-auth 載入失敗` | 執行 `pip install --user -r scripts/requirements-agent.txt`（hook 平常會自動做） |
| `HTTP 403 … PERMISSION_DENIED` | 重跑 bootstrap（它是冪等的），或該 API 沒啟用；看 `whoami` 的 API 清單 |
| `HTTP 404` 讀函式 | 區域不對：`--region asia-east2` 或改 `GCP_REGION` |
| 部署卡在 `BUILD` 超過 10 分鐘 | 到 Console → Cloud Build 看建構日誌，通常是 `requirements.txt` 套件裝不起來 |
| 日誌是空的 | 第 2 代函式的日誌在 Cloud Run 修訂底下；`logs` 已同時查兩種資源，若仍空代表期間內真的沒有請求 |
