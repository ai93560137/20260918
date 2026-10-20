# 📨 外部 Telegram 頻道訊號 → 分析 → 人手確認 → MT5（R290）

```
別人的頻道 ──(你的用戶帳號，Telethon)──▶ claude-ops VM：tg_listener.py
      └─ POST action=tg_signal（WEBHOOK_SECRET_TOKEN）──▶ Cloud Run zhuge-risk-manager
            ├─ 去重（GCS tg_signals/<頻道>_<訊息>.json）
            ├─ Gemini 解析自由格式文字 → JSON（只解析，唔決定）
            ├─ 預檢：黃金？有止損？現價離入場幾遠？止損方向／距離？電閘硬鎖／新聞鎖？
            └─ 訊號確認 bot 發訊息＋「✅ 確認下單／❌ 略過」按鈕
你按 ✅ ──▶ Telegram callback ──▶ Cloud Run ?tg=signal（核對 secret_token、chat／使用者白名單）
            ├─ 用當時最新價重新檢查（逾時 15 分鐘作廢）
            └─ build_order → BROKER_API_URL（webhooktrade）→ MT5 EA
```

* **全部要人手確認**：冇按 ✅ 就唔會送單；同一個按鈕只會送一次（GCS 原子 claim）。
* 管理指示（移止損、平倉、止賺到）同閒聊**只發參考訊息**，系統唔會自動平倉或改單。
* 只送 XAUUSD；手數固定 `TG_SIGNAL_LOTS`（預設 0.01，上限 `TG_SIGNAL_MAX_LOTS` 0.10）；只送止損／止賺，唔送移動止損與保本。
* 唔改加單狀態、唔經 AI 覆核關卡、唔計訓練節奏。
* ⚠️ **EA V22 冇 magic 過濾**：手動單會計入 EA 回報嘅持倉。自動策略解除硬鎖後，可能會當呢張單係自己嘅持倉去加碼，
  或者因為「方向衝突」停手；R171 帳本亦會混埋。最穩陣係用**另一個 MT5 戶口**（送單參數頁嘅 `account`）。

## 第 1 步：開一個「訊號確認 bot」（唔好用現有嘅 @HC_Gold_Signal_bot）
1. Telegram 搵 @BotFather → `/newbot` → 攞 bot token。
2. 同新 bot 講一句 `/start`，再用 @userinfobot 攞你自己嘅數字 id（私訊時 chat id = 你嘅 user id）。
3. 自己產生一串隨機字做 webhook secret（例：`python3 -c "import secrets;print(secrets.token_urlsafe(32))"`）。

## 第 2 步：Cloud Run 環境變數（Claude 幫你用 `gcp_agent.py env set`，先睇計畫，你同意先套用）
| 變數 | 值 |
|---|---|
| `TG_SIGNAL_BOT_TOKEN` | 第 1 步 bot token |
| `TG_SIGNAL_CHAT_ID` | 你嘅 user id |
| `TG_SIGNAL_WEBHOOK_SECRET` | 第 1 步隨機字 |
| `TG_SIGNAL_ORDER_ENABLED` | 先 `0`（只分析）；試幾日冇問題先改 `1` |
| 選填 | `TG_SIGNAL_LOTS`、`TG_SIGNAL_MAX_LOTS`、`TG_SIGNAL_CONFIRM_TTL_SEC`（900）、`TG_SIGNAL_MAX_DRIFT_USD`（5）、`TG_SIGNAL_MAX_SL_USD`（30）、`TG_SIGNAL_PRICE_MAX_AGE_SEC`（300）、`TG_SIGNAL_ALLOWED_USERS`、`TG_SIGNAL_AI_MODEL`、`TG_SIGNAL_NOTIFY_ALL` |

**權杖唔好貼入對話**：你喺 Cloud Run 控制台自己填，或者喺你自己部機跑 `gcp_agent.py env set`。

## 第 3 步：claude-ops VM 上跑監聽（用獨立使用者 `tgrelay`）
點解用 claude-ops：長開、喺台灣、唔會好似 Windows 部機咁瞓覺或者重開。
點解要獨立使用者：session 檔等同你嘅 Telegram 帳號，**唔可以畀 claude-ops 上面嘅 Claude 讀到**；家目錄 700 係硬性隔離。

喺 claude-ops 瀏覽器 SSH（提示符應該係 `@claude-ops`），用你自己嘅帳號：
```bash
sudo adduser --disabled-password --gecos "" tgrelay
sudo chmod 700 /home/tgrelay
sudo -iu tgrelay
python3 -m venv ~/venv && ~/venv/bin/pip install telethon
mkdir -p ~/tg_relay && cd ~/tg_relay     # 把 repo 嘅 tg_relay/tg_listener.py 複製到呢度
cat > ~/.tg_relay.env <<'X'
export TG_API_ID=...            # https://my.telegram.org → API development tools
export TG_API_HASH=...
export TG_CHANNELS=-100xxxxxxxxxx
export ZHUGE_GCP_URL=https://你的服務.run.app/
export WEBHOOK_SECRET_TOKEN=...
X
chmod 600 ~/.tg_relay.env && . ~/.tg_relay.env
~/venv/bin/python tg_listener.py --login      # 輸入電話、驗證碼（有兩步驗證就再輸入密碼）
~/venv/bin/python tg_listener.py --list       # 揀頻道 id 填 TG_CHANNELS
~/venv/bin/python tg_listener.py --dry-run    # 確認收到訊息
```
長跑（tmux 最簡單）：`tmux new -s tgrelay '. ~/.tg_relay.env; ~/venv/bin/python ~/tg_relay/tg_listener.py'`。

設定 bot webhook（一次，要多設 `TG_SIGNAL_BOT_TOKEN`、`TG_SIGNAL_WEBHOOK_SECRET` 兩個環境變數）：
`~/venv/bin/python tg_listener.py --set-webhook`

### 改完使用者／家目錄權限之後必跑（AGENTIC.md「必跑這個檢查」）
在 claude-ops 的 SSH 視窗（使用者自己跑，不要交給 Claude）：
```bash
ssh ibdata 'sudo -n true 2>&1 | head -1; cat /home/hengkychansinghing/ibc/config.ini 2>&1 | head -1; ls /home/hengkychansinghing 2>&1 | head -1'
```
**三行都必須是拒絕**（`sudo: a password is required`、兩行 `Permission denied`），請貼返結果。另外加一行確認 Claude 嘅使用者讀唔到 session：
用 claude-ops 上跑 Claude 嗰個使用者執行 `ls /home/tgrelay`，應該係 `Permission denied`。

## 風險
* 用自動化程式登入個人帳號有被 Telegram 限制的風險；只讀、唔發訊息，風險較低，但唔係零。
* 頻道訊號質素未經量度：按 `IDEAS.md` 慣例，先用 `TG_SIGNAL_ORDER_ENABLED=0` 紙上記錄（GCS `tg_signals/`），有足夠樣本先落真倉。
