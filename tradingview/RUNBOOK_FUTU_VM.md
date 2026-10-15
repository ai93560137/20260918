# 富途數據 VM（futu-data）設定手冊（R187，方案一）

使用者 2026-10-15 揀方案一：富途 OpenD、auto_risk、富途推送腳本搬去 Google Linux VM（香港區），
MT5 同 `mt5_push` 留喺使用者部機（`gcp_ib\start_all.ps1` 開機自動起）。部機重開唔再影響富途數據。

只讀：讀持倉同報價、推上 Cloud Run；**唔落單、唔 unlock_trade，交易密碼唔放上 VM**。
Claude（雲端工作階段）唔 SSH 入呢部 VM；由使用者用瀏覽器 SSH 做，Claude 逐步教。

## 架構
| 位置 | 跑乜 | 點樣自動 |
|---|---|---|
| VM `futu-data`（Debian 12，asia-east2） | OpenD（Linux 命令列版）、`auto_risk`、`push_to_gcp`、`iv_push` | systemd 服務，開機自動起、死咗 30–60 秒自動重開 |
| VM 自動更新 | 每 10 分鐘睇 `ops/user-machine` 分支，有新版就更新 repo、重開推送服務 | systemd timer `zhuge-update.timer`，紀錄 `~/zhuge/update.log` |
| 使用者部機（Windows） | MT5（EA 心跳）、`mt5_push` | 啟動資料夾 `ZhugeStartAll.cmd` → `start_all.ps1`，`ZHUGE_DAEMONS=mt5_push` |

`ops/user-machine` 只由總指揮喺使用者講「更新部機」先推（由預設分支快進）；其他陣合併入預設分支唔會自動落 VM。

## 步驟
1. **開 VM**（GCP Console → Compute Engine → 建立執行個體）：名 `futu-data`、區域 `asia-east2-a`、`e2-small`、
   Debian 12、磁碟 20 GB；**唔使綁服務帳戶權限**（揀「不允許存取任何 Cloud API」），唔使開外部連入埠。
2. **SSH 入去**，clone repo（公開，唔使權杖）：
   `git clone -q -b ops/user-machine https://github.com/ai93560137/20260918 ~/20260918`
3. **裝 OpenD**：富途官網下載頁（https://www.futunn.com/download/OpenAPI）Ubuntu 版個掣，喺瀏覽器下載清單複製**真正檔案網址**
   （`https://softwaredownload.futunn.com/Futu_OpenD_<版本>_Ubuntu18.04.tar.gz`），VM 上 `wget` 落嚟、`tar xzf`，
   將入面（隔多一層）嘅檔全部 `cp -a` 去 `~/opend/`。
4. **開 telnet**：`~/opend/FutuOpenD.xml` 嘅 `telnet_ip`／`telnet_port` 預設註解咗，要解開（127.0.0.1:22222）。
   ⚠ **OpenD 10.11 唔讀 xml／命令列嘅 `login_account`、`login_pwd_md5`**（MD5 喺登入提示亦唔收），每次開都喺主控台問帳號、密碼、記住密碼。
5. **登入檔 `~/zhuge/opend_login`**（chmod 600；第一行牛牛號、第二行**登入**密碼，唔係交易密碼；用 `read -rs` 喺 VM 填，唔好貼入對話）。
   `zhuge-opend.service` 經 `opend_tmux.sh` 喺 tmux session `opend` 開 OpenD 並自動答；每次開只試一次，
   失敗會寫 `~/zhuge/opend_login.failed` 停止自動試（富途密碼錯有次數限制）＋發 Telegram，改好密碼後刪咗呢個檔再 `sudo systemctl restart zhuge-opend`。
   冇呢個檔就要每次開機人手 `tmux attach -t opend` 登入。
   ⚠ 富途有**登入次數限制**：短時間登入太多次會「登录次数过多,请等待 50 分钟」，OpenD 即刻退出（exit 31）。
   `opend_tmux.sh` 遇到會等 60 分鐘先再試；期間唔好人手 `systemctl restart`／開 OpenD，否則越鎖越耐。
6. **填 `~/zhuge/env`**：照 `gcp_ib/vm_futu/env.example`（可以用 `read -rsp` 逐個填再 `cat > ~/zhuge/env`，唔使 nano）。
   `ZHUGE_COMBINED_EQUITY` 只填純數字港幣（冇逗號、冇 USD）。
7. **安裝**：`bash ~/20260918/gcp_ib/vm_futu/setup.sh`（會裝 tmux；之後 repo 嘅 service／timer 改動由 `update.sh` 自動套用，OpenD 唔自動重開）。
   **第一次喺新機登入要短訊驗證**：`tmux attach -t opend` → 打 `req_phone_verify_code` → `input_phone_verify_code -code=短訊碼`（碼唔好貼入對話）→ Ctrl+B 再 d 離開。
   ⚠ 喺 tmux 入面唔好 Ctrl+C（會停 OpenD）。
8. **驗證**：Claude 睇 GCS `futu/risk/latest.json` 嘅 `run_hkt` 有冇更新；VM 上 `journalctl -u zhuge-auto-risk -n 30`。
9. **部機收窄**：VM 正常之後，部機 `setx ZHUGE_DAEMONS "mt5_push"`、`setx ZHUGE_OPEND_EXE ""`，部機唔再開 OpenD／auto_risk
   （免得兩邊重覆推、富途同一戶口兩部機登入 OpenD 搶行情權限）。

## 改設定
- **推乜數據**（`FUTU_SYMBOLS`、`PUSH_INTERVAL_SEC`、`IV_MARKETS` 等）同 `ZHUGE_ALERT_STOP`：改 repo 嘅 `gcp_ib/vm_futu/settings.env`
  → PR → 合併 →「更新部機」，VM 10 分鐘內自動套用（唔使 SSH）。
- **權杖、密碼、權益、按金緩衝金額**：只喺 VM 嘅 `~/zhuge/env`／`~/zhuge/opend_login` 改（repo 公開），改完
  `sudo systemctl restart zhuge-auto-risk zhuge-futu-push zhuge-iv-push`（唔好重開 `zhuge-opend`，富途有登入次數限制）。

## 常用
- OpenD 畫面：`tmux attach -t opend`（Ctrl+B 放手再撳 d 離開）；唔入去睇：`tmux capture-pane -pt opend | tail`
- 狀態：`systemctl --no-pager status zhuge-opend zhuge-auto-risk zhuge-futu-push zhuge-iv-push`
- 紀錄：`journalctl -u zhuge-auto-risk -n 50`、`cat ~/zhuge/update.log`
- 停晒：`sudo systemctl stop zhuge-auto-risk zhuge-futu-push zhuge-iv-push zhuge-opend`
