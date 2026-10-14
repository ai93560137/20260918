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
3. **裝 OpenD**：喺富途官網下載 OpenD 嘅 Linux（Ubuntu）版，解壓後將 `FutuOpenD`、`FutuOpenD.xml` 等檔放入 `~/opend/`。
4. **填 OpenD 設定** `~/opend/FutuOpenD.xml`（使用者自己填，**唔好貼入對話**）：`login_account`、`login_pwd_md5`
   （喺 VM 跑 `echo -n '密碼' | md5sum` 計，跑完 `history -c`）、`api_ip` 127.0.0.1、`api_port` 11111、`telnet_ip` 127.0.0.1、`telnet_port` 22222。
5. **填 `~/zhuge/env`**：照 `gcp_ib/vm_futu/env.example`，`mkdir -p ~/zhuge && nano ~/zhuge/env`。
6. **安裝**：`bash ~/20260918/gcp_ib/vm_futu/setup.sh`。
7. **第一次登入要短訊驗證**時：`telnet 127.0.0.1 22222` → `input_phone_verify_code -code=短訊碼`（碼唔好貼入對話）。
8. **驗證**：Claude 睇 GCS `futu/risk/latest.json` 嘅 `run_hkt` 有冇更新；VM 上 `journalctl -u zhuge-auto-risk -n 30`。
9. **部機收窄**：VM 正常之後，部機 `setx ZHUGE_DAEMONS "mt5_push"`、`setx ZHUGE_OPEND_EXE ""`，部機唔再開 OpenD／auto_risk
   （免得兩邊重覆推、富途同一戶口兩部機登入 OpenD 搶行情權限）。

## 常用
- 狀態：`systemctl --no-pager status zhuge-opend zhuge-auto-risk zhuge-futu-push zhuge-iv-push`
- 紀錄：`journalctl -u zhuge-auto-risk -n 50`、`cat ~/zhuge/update.log`
- 停晒：`sudo systemctl stop zhuge-auto-risk zhuge-futu-push zhuge-iv-push zhuge-opend`
