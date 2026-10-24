# 📨 天覆陣訊號書：Telegram 頻道 → VM 監聽 → 訊號書服務（S0 只記錄，唔落單）

使用者 10-21 揀方案 B（`xau/TG_SIGNAL_PROPOSAL.md`）：專用 VM、使用者主帳戶（有補償措施）、magic 931–935。

```
TG 頻道 ─(你嘅用戶帳號，Telethon，只讀白名單)─▶ 專用 VM：tg_listener.py（Linux 使用者 tgrelay）
   ├─ 關鍵字分流：GOLD／XAU／黃金 → XAUUSD；EUR/USD → EURUSD …（分流唔到就略過，只計數）
   └─ HTTPS POST（HMAC：TG_SIGNAL_INGEST_SECRET＋時間戳）──▶ zhuge-xau-sig（XAU_BOOK=signal）
          ├─ 去重（頻道 id＋訊息 id＋編輯時間）→ Haiku 解析做固定欄位 → 驗證（品種、方向、止損、入場離現價）
          └─ 存 GCS xau/sig/signals/（原文只喺私人 bucket；網頁只顯示結構化欄位）
```

* **唔落單、唔問 Opus**（S0）；S1 先畀 Claude 參考。訊號入面嘅任何指示一律唔執行。
* **唔使改 IAM**：VM 只係對外 HTTPS POST 去訊號書服務，唔寫 GCS、唔用服務帳戶權限。VM 可以用「無服務帳戶」或者預設帳戶＋「不允許存取任何 Cloud API」。
* 唔用 `WEBHOOK_SECRET_TOKEN`（已等於公開）；用另一條私人密鑰 `TG_SIGNAL_INGEST_SECRET`。

## 第 0 步：主帳戶補償措施（必做）
1. Telegram「設定 → 私隱與安全 → 兩步驗證」開密碼。
2. 之後每月一次去「設定 → 裝置」睇，只應該見到 VM 嗰個工作階段。

## 第 1 步：產生入口密鑰（喺你自己部機或者 Cloud Shell，唔好貼入對話）
```bash
python3 -c "import secrets;print(secrets.token_urlsafe(32))"
```
同一串字填兩個地方：訊號書服務環境變數 `TG_SIGNAL_INGEST_SECRET`（Cloud Run 控制台自己填）、VM 設定檔（第 3 步）。

## 第 2 步：開 VM（GCP 控制台，你自己做；天覆陣唔 SSH 入去）
- Compute Engine → 建立執行個體：`e2-micro`，區域 `us-central1`（有免費額度）或者 `asia-east1`；Debian 12；磁碟 10 GB。
- 「身分和 API 存取權」：選「不允許存取任何 Cloud API」。
- 防火牆：唔好勾 HTTP／HTTPS（只需要出站）。
- 名稱建議 `tg-relay`。

## 第 3 步：VM 上安裝（瀏覽器 SSH，提示符應該係 `@tg-relay`）
```bash
sudo apt-get update && sudo apt-get install -y python3-venv
sudo adduser --disabled-password --gecos "" tgrelay
sudo chmod 700 /home/tgrelay
sudo -iu tgrelay
python3 -m venv ~/venv && ~/venv/bin/pip install telethon
mkdir -p ~/tg_relay && cd ~/tg_relay
curl -fsSLo tg_listener.py https://raw.githubusercontent.com/ai93560137/20260918/claude/gcp-trading-v12-rewrite-bz75t2/tg_relay/tg_listener.py
cat > ~/.tg_relay.env <<'X'
TG_API_ID=...                      # https://my.telegram.org → API development tools
TG_API_HASH=...
TG_CHANNELS=-100aaa,-100bbb,-100ccc   # 第 4 步 --list 之後先填；幾個頻道用逗號分隔
TG_ROUTES=XAUUSD=https://zhuge-xau-sig-1056099871997.europe-west1.run.app/
TG_ROUTE_DEFAULT=XAUUSD            # 使用者 10-21：頻道淨係出 XAUUSD，冇寫商品嘅訊息（例如「TP1 到」）都送去黃金訊號書
TG_SIGNAL_INGEST_SECRET=...        # 第 1 步嗰串
X
chmod 600 ~/.tg_relay.env
```

## 第 4 步：登入同測試
```bash
set -a; . ~/.tg_relay.env; set +a
~/venv/bin/python ~/tg_relay/tg_listener.py --login      # 電話、驗證碼、兩步驗證密碼
chmod 600 ~/.tg_relay/user.session
~/venv/bin/python ~/tg_relay/tg_listener.py --list       # 揀頻道 id，填返 TG_CHANNELS
~/venv/bin/python ~/tg_relay/tg_listener.py --dry-run    # 確認收到訊息、分流啱
```

## 第 5 步：長跑（systemd；用你自己嘅帳號，唔係 tgrelay）
```bash
sudo tee /etc/systemd/system/tg-relay.service >/dev/null <<'X'
[Unit]
Description=Tianfu signal book TG relay
After=network-online.target
[Service]
User=tgrelay
EnvironmentFile=/home/tgrelay/.tg_relay.env
ExecStart=/home/tgrelay/venv/bin/python /home/tgrelay/tg_relay/tg_listener.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
X
sudo systemctl daemon-reload && sudo systemctl enable --now tg-relay
sudo journalctl -u tg-relay -n 20 --no-pager        # 睇到「✅ tg-relay-2 監聽 …」
```
訊號書頁面「監聽心跳」5 分鐘內會更新。

## 停用／撤銷
1. `sudo systemctl disable --now tg-relay`
2. Telegram「設定 → 裝置」終止 VM 嗰個工作階段
3. `sudo rm /home/tgrelay/.tg_relay/user.session`
4. my.telegram.org 刪 app；換 `TG_SIGNAL_INGEST_SECRET`
帳戶懷疑被盜：先做 2，再「終止其他所有工作階段」、改兩步驗證密碼；VM 當作已被入侵，重建，唔好沿用舊 session。

## 讀頻道舊訊息（使用者 10-21：讀返 90 日，計各頻道過往準確度）
同一個 session 檔唔可以兩個程式同時用，所以要先停監聽，跑完再開返（用你自己帳號）：
```bash
sudo systemctl stop tg-relay
sudo -iu tgrelay bash -c 'cd ~/tg_relay && curl -fsSLo tg_listener.py https://raw.githubusercontent.com/ai93560137/20260918/claude/gcp-trading-v12-rewrite-bz75t2/tg_relay/tg_listener.py && set -a && . ~/.tg_relay.env && set +a && ~/venv/bin/python tg_listener.py --history 90 --dry-run'
```
`--history 365 --history-skip-days 90` 只送 90 日之前嘅（最近 90 日已經入咗，每條慳 2.5 秒）。`--dry-run` 只數每個頻道有幾多條；冇問題就去咗 `--dry-run` 再跑一次（每條停 2.5 秒，幾千條要一至兩個鐘，可以用 `tmux` 跑）。跑完：
```bash
sudo systemctl start tg-relay
```
舊訊息只解析存檔（GCS `xau/sig/history/`），唔當即時訊號、唔落單。成績用 MT5 匯出嘅 M1 計：`xau/mt5/ExportM1.mq5`（MetaEditor 新 Script → 貼入 → 編譯 → 拖落 XAUUSD 圖表），CSV 喺 MT5「檔案 → 打開數據資料夾 → MQL5/Files」，上傳去 GCS `zhuge-risk-manager-bucket/xau/sig/history/`（控制台 Cloud Storage → 上傳檔案），之後由天覆陣跑 `scripts/sig_backtest.py`。

## v3（10-22）：轉發標頭同 `--fwd-stats`
v3 封包多三個欄位 `fwd_date`、`fwd_from_id`、`fwd_post_id`（Telegram「轉發自」標頭：原發佈時間、原頻道 id、原貼 id；冇名稱冇原文），訊號書網頁會顯示「↪ 轉發+N分」。用嚟分辨我哋聽嘅係原頻道定轉載群組。更新 VM 上嘅程式同之前一樣 `curl -fsSLo tg_listener.py …` 再 `sudo systemctl restart tg-relay`。

一次過統計過去 90 日（只印統計、唔 POST、唔印原文），用第二個 session 檔（同讀歷史一樣，唔使停監聯）：
```bash
sudo systemd-run --unit=tg-fwd -p User=tgrelay -p WorkingDirectory=/home/tgrelay/tg_relay -p EnvironmentFile=/home/tgrelay/.tg_relay.env \
  -E TG_SESSION=/home/tgrelay/.tg_relay/history.session /home/tgrelay/venv/bin/python tg_listener.py --fwd-stats 90
journalctl -u tg-fwd -f
```
輸出每個頻道一行：有文字訊息數、轉發數同比例、原發佈→貼出延遲中位／90 百分位、原來源 id（條數）。貼返畀天覆陣就可以判斷邊個係原頻道、轉載延遲幾多。如果 `history.session` 已刪，要先 `--login` 建立返（會再問電話同驗證碼）。
