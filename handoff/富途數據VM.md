# 🖥️ 富途數據 VM 交接（2026-11-09，舊工作階段 `session_01AQNMTZvQodzptWVui6deqY` → 新工作階段）

> 只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準。
> repo 公開：唔好寫真實權益、保證金、緩衝、盈虧金額；秘密（富途／IB 密碼、驗證碼、TG token、WEBHOOK_SECRET_TOKEN、GCP 金鑰、Claude API key）唔入對話、repo、log。

## 1. 負責範圍
- 台灣 VM **`futu-data-tw`**（asia-east1-b，e2-standard-2 8GB＋2GB swap，Debian 12）上嘅富途 OpenD、`auto_risk`、`push_to_gcp`、`iv_push`，同 `gcp_ib/vm_futu/` 全部腳本／systemd 檔。
- 龍飛陣程式（`zhuge-longfei*`）亦跑喺呢部機，**程式邏輯歸龍飛陣**；我管機器、OpenD、記憶體／硬碟、update 流程。
- 香港舊機 `futu-data`（asia-east2-a）**11-07 已由使用者刪除**。`ib-data`（香港 IB Gateway）唔關我事。
- 分支：`claude/futu-vm-setup`（PR 經佢開；已 squash 合併嘅舊頭用 merge commit 接，**唔好 force-push**）。

## 2. 點樣運作
| 項目 | 位置／做法 |
|---|---|
| OpenD | `zhuge-opend.service` → `gcp_ib/vm_futu/opend_tmux.sh`：tmux session `opend` 自動答帳號／密碼（`~/zhuge/opend_login`，600，登入密碼唔係交易密碼）；只試一次，明確「登录失败／密码错误」先寫 `~/zhuge/opend_login.failed`（R227）；「次数过多」等 60 分鐘；`OOMScoreAdjust=-900`（R219） |
| 推送 | `zhuge-auto-risk`（每 10 分鐘；**週六 06:00～週一 06:00 HKT 唔跑**，預期）、`zhuge-futu-push`、`zhuge-iv-push`（每 30 分鐘） |
| 持倉來源 | `gcp_ib/futu_positions_quote.py`：`position_list_query`＋成交淨計補倉；R372 剔走已到期合約（`expired()`）；R373 推 `nominal_price`／`average_cost` 等同 `metrics.futu_acc_pl`；R376 正股成交淨計負數而富途冇淡倉就略過（`is_stock()`） |
| 設定 | 唔係秘密：repo `gcp_ib/vm_futu/settings.env`（**唔可以有行尾註解**，systemd 當值）；秘密：VM `~/zhuge/env`（600）。settings.env 蓋過 env |
| 更新 | `zhuge-update.timer` 每 10 分鐘跑 `update.sh`：先清 3 日前 `~/.com.futunn.FutuOpenD/Log`、journald 上限 300M、硬碟 <1GB 再清（R306）；讀唔到 FETCH_HEAD 就跳過（R307）；有新版就 reset、重寫 service、重開推送同龍飛陣 |
| 「更新部機」 | 使用者講先將 `ops/user-machine` 快進到預設分支（**唔 force**）。**而家由總指揮做**；我呢個工作階段推 `ops/user-machine` 會被權限檢查擋。手動即刻套用：`sudo systemctl start zhuge-update.service`（**唔好直接 `bash update.sh`**，要 systemd 傳參數） |
| 交易密碼 | 使用者 10-19「確認 A」：`FUTU_TRADE_PASSWORD` 喺 `~/zhuge/env`，**只畀 `zhuge-longfei-real@<產品>` 解鎖落真單**；解鎖對成個 OpenD 生效，其他程式唔准加落單代碼（AGENTIC.md 已寫） |

## 3. 核實方法（唔使 SSH）
```bash
python3 scripts/gcp_agent.py cat --object futu/risk/latest.json   # script_version、received_utc、positions、metrics
python3 scripts/gcp_agent.py bucket --prefix futu/snapshots/      # QQQ／HSI_FRONT 約 5 分鐘、HSI_IV 30 分鐘
```
- Cloud Run `main.py` 嘅 `_futu_risk_clean_metrics` 用**白名單**：VM 新加 metrics 欄位要總指揮加白名單＋部署主服務先入 GCS；`positions` 冇白名單。
- 改 auto_risk 行為要 bump `gcp_ib/auto_risk.py` 嘅 `SCRIPT_VERSION`，咁 GCS 先睇得出 VM 跑緊邊版。
- Compute API（唯讀）可以睇 VM 狀態／機型；**唔 SSH**，VM 上要做嘅嘢叫使用者用瀏覽器 SSH（先睇提示符 `@futu-data-tw`）。

## 4. 版本號（我用過）
R187–R192、R199、R202（多產品）、R219（OpenD OOM 保護）、R227（登入判斷）、R306（清 log）、R307（FETCH_HEAD）、R372（到期合約）、R373（盈虧口徑）、R376（正股負數）。
開新改動前查預設分支最大 R 號 +1，同總指揮講（撞號試過幾次）。

## 5. 事故紀錄（摘要）
- 10-18 OOM：e2-small 跑 OpenD＋17 個龍飛陣程式，kernel 殺 OpenD → 升 e2-medium（再升 e2-standard-2）＋R219／R220。
- 10-18 快照限速（龍飛陣 R226 共用快取修好）；OpenD 登入被誤判失敗（R227）。
- 10-23 硬碟爆（R306、R307）。
- 11-07 已到期週權殘留（R372）；11-08 SPCX 贈股負數（R376）。

## 6. 待辦／留意
- **R376 核實**：#754 已上 `ops/user-machine`（b1a4c2dc3）；下一份 `futu/risk/latest.json` 應該冇 `US.SPCX` 負數。舊工作階段約咗 22:48 UTC 核實，結果會報總指揮；如果未見報告，新工作階段補做。
- **期貨 `pl_val` 唔可靠**：HSI2611 `futu_pl` 同 `(nominal_price−average_cost)×qty×mult`、戶口 `unrealized_pl` 對唔上；總指揮報告已改用 `nominal_price`。
- **美期（CME）OpenD API 冇行情權限**：要使用者喺富途開通（付費）先用得；ES／NQ 5 分 K 而家由 ib-data IB 延遲數據推。
- **claude-ops**：雲端工作階段發訊息過去要使用者喺信任裝置批准，未批。
- **Claude API key（longfei-vm）續期提醒**：排程 `trig_01H5aYT5rXsxohkNPwrQZD3V`（2026-12-15）。
- 各陣工作階段 id 以 `handoff/SESSIONS.md` 為準；總指揮而家係 `session_01Mt8CWjUZpGvDAD6UBLEAti`。
