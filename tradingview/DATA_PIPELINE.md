# 期貨/期權數據管線 — 方法文檔（供其他 Claude Code session 學習）

2026-09-22 定稿。本文檔描述本 repo 如何在**無外網的 Claude Code Remote 沙盒**裡
取得恒指與美指的期貨/期權延遲行情。所有代碼都在 repo 內，路徑見各節。

## 0. 核心架構：GitHub Actions 做「外網橋」

CCR 沙盒的出網只允許 GitHub 和套件庫，直接 `requests.get` 任何行情網站都會失敗。
解法：**抓取代碼放在 `.github/workflows/` + `.github/scripts/`，跑在 GitHub Actions
的 runner 上（外網全通），抓完 commit 回分支，session 再 `git pull` 讀檔**。

```
session（無外網）                 GitHub Actions（外網全通）
  │ 觸發 workflow ──────────────▶ fetch 腳本抓 HKEX/Yahoo
  │ sleep ~2min                    │ 掃描器產出報告/警報
  │ git pull ◀────────────────── commit 數據回分支
  │ 讀 data_external/*            （另可發 Telegram）
```

觸發方式（二選一）：
1. MCP 工具：`mcp__github__actions_run_trigger`，method=run_workflow，
   workflow_id=`fetch-quotes.yml`，ref=分支名；可帶 `inputs: {digest:'false'}`
2. 無 MCP 時：改動 `.github/trigger-scan`（任意內容）commit+push——workflow 的
   `on.push.paths` 監聽此檔

等待用 `sleep 170`（背景執行），完成後 `git pull --rebase`。CI 也會 commit 快照，
本地 push 撞車時：`git pull --rebase`，衝突檔（scan_report.md/alert.txt 等
CI 產物）一律 `git checkout --ours` 保留 CI 版本。

## 1. 恒指期貨+期權：HKEX widget API（15 分鐘延遲，免費無需註冊）

實現：`.github/scripts/fetch_hkex_quotes.py`。這是逆向 hkex.com.hk 頁面
widget 的內部 API，四個要點：

### 1.1 Token（必須，每次現抓）
GET 行情頁面 HTML，正則掏 token：
```python
page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
             'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en').text
token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)
```
Token 有時效，**每次執行都重抓**，不要緩存。Headers 要帶瀏覽器 UA +
`Referer: https://www.hkex.com.hk/`，否則拒答。

### 1.2 端點格式（JSONP）
```
https://www1.hkex.com.hk/hkexwidget/data/<endpoint>?lang=eng&token=<token>
    &<params>&qid=<毫秒時間戳>&callback=j
```
回應是 `j({...})`，正則 `^j\((.*)\)\s*$` 剝殼後 json.loads。
`data.responsecode == '000'` 為成功。

### 1.3 三個端點（順序有依賴）
| 端點 | 參數 | 得到 |
|---|---|---|
| `getderivativesfutures` | `ats=HSI&type=0` | 期貨全月份：bd/as（買賣）、se（昨結）、oi、lastupd |
| `getoptioncontractlist` | `ats=HSI&type=0` | 期權月份清單 `data.conlist[]`，**其中 `id`（如 '102026'）才是下一步 con 參數的合法值**——直接猜月份代號會得 "Incomplete Information" |
| `getderivativesoption` | `ats=HSI&con=<id>&fr=null&to=null&type=0` | 該月全鏈：每檔 strike + c/p 各自的 bd/as/iv/oi |

踩過的坑：參數名是 `ats` 不是 `ati`；con 值必須來自 conlist；小型恒指用同一套
（MHI 報價與 HSI 期權同源，行使價/IV 一致，只是乘數不同）。

### 1.4 數據特性
- 15 分鐘延遲；夜盤遠月常無雙邊報價（價差警報只看前兩個月）
- 近月價用**買賣中間價**，無雙邊才退回昨結（se）並標明——se 是昨結不是現價，
  直接當現價用會差半日行情（實測踩過）
- ATM 檔位選「最接近期貨價的檔」，不要用「c/p IV 最接近」（夜盤稀疏報價會漂移）

## 2. 美股：Yahoo Finance（yfinance，延遲行情，免費）

實現：`.github/scripts/fetch_us_daily.py` + `fetch_spx_chain.py`。Actions runner
直接 `pip install yfinance` 就能用（沙盒內不行，同樣要跑在 Actions）。

### 2.1 日線與期貨延遲價
```python
yf.download('^VIX', period='max', interval='1d')       # 指數日線（VIX/SPX/VXN/NDX/^HSI/^HSIL 同法）
yf.download('ES=F', period='5d', interval='1h')        # 期貨延遲價（ES=F/NQ=F，取最後一根）
```
防呆：新抓行數 < 舊檔 90% 視為壞抓取，不覆蓋舊檔。

### 2.2 SPX 期權鏈（給 MES 做第二報價源）
```python
t = yf.Ticker('^SPX')
t.options                    # 到期日字串列表 → 選 25–40 天窗口內最近的
ch = t.option_chain('2026-10-16')   # ch.calls / ch.puts：strike, bid, ask, impliedVolatility, openInterest
```
**關鍵校正**：Yahoo 的 IV 用現貨折算、不調 forward/股息 → call IV 系統性偏高、
put 偏低。**跨市場比對一律取 (call_iv + put_iv)/2**，此均值與期貨期權 ATM IV
可比（實測與富途 MES 鏈差 0.04–0.3 波動點）。CME 期貨期權（MES/MHI 鏈）Yahoo
沒有——只能靠使用者貼券商截圖，SPX 鏈是其可自動化的替身。

## 3. Workflow 檔案

- `fetch-quotes.yml`：主管線。dispatch（可帶 digest input）+ push 觸發 →
  US 刷新 → SPX 鏈 → HKEX 抓取 → `tradingview/hsi_scan.py` 掃描（產出
  scan_report.md / digest.txt / alert.txt）→ Telegram 步（警報優先，否則日報）→
  commit 回分支（`git pull --rebase || true` 再 push，容忍並發）
- `send-telegram.yml`：通用出口。session 寫 `.github/tg_outbox.txt` + push，
  workflow 把內容發到 Telegram（secrets：TG_BOT_TOKEN / TG_CHAT_ID）
- 只裝 PyPI 套件（requests/pandas/numpy/yfinance）——**不要 pip 裝 git 倉庫**，
  會觸發不受信代碼攔截

## 4. 驗證紀律（拿到數據先做什麼）

1. **平價**：C − P 中間價 = 隱含遠期，兩個檔位互證應差 <2 點；期貨期權的
   隱含遠期 = 期貨價本身，指數期權 = 現貨 + carry（HSI 股息大，遠期常低於現貨）
2. **新鮮度**：lastupd/資料日期距今 >5 天 → 呆滯警報，別靜默用舊數據
3. **三源比對**：自動源（HKEX/Yahoo）↔ 券商截圖（執行真值）↔ 波指（基準），
   偏差記錄在 `data_external/quality_log.md`，容差：價格 0.3%、IV 0.5–1.0 點
4. 監測數據**永不用於下單**——下單以券商當刻實時價為準，管線只做環境監測

## 5. 快速上手（另一個 session 的最小動作序列)

```bash
# 1. 觸發（或 push .github/trigger-scan）
mcp__github__actions_run_trigger(method=run_workflow, owner=..., repo=...,
                                 workflow_id='fetch-quotes.yml', ref='<branch>')
# 2. 等
sleep 170  # background
# 3. 收
git pull --rebase origin <branch>
cat tradingview/data_external/digest.txt        # 一眼摘要
cat tradingview/data_external/scan_report.md    # 完整報告
ls  tradingview/data_external/quotes/           # HKEX 原始 JSON（時間戳檔名）
ls  tradingview/data_external/quotes_us/        # SPX 鏈快照
cat tradingview/data_external/us_futures_quote.json  # ES/NQ 延遲價
```

## 6. Telegram 發送方法（session → 使用者手機）

沙盒無外網，session 不能直接打 Telegram API——**發送也走 Actions**。
兩條通道都已實測跑通。

### 6.1 一次性設置

1. Telegram 找 **@BotFather** → `/newbot` → 得到 bot token（格式 `123456:ABC-...`）
2. **使用者必須先給 bot 發一條訊息**（按 START）——bot 不能主動開聊，
   沒這步所有發送靜默失敗
3. 拿 chat_id：`curl "https://api.telegram.org/bot<TOKEN>/getUpdates"`，
   讀 `result[].message.chat.id`（純數字）。**注意 getUpdates 的記錄 ~24 小時過期**，
   拿到後立刻存起來，別依賴每次現查
4. Repo → Settings → Secrets and variables → Actions → 建兩個 secret：
   `TG_BOT_TOKEN`、`TG_CHAT_ID`。**Token 永遠只進 Secrets，不進代碼、不進對話**

### 6.2 發送核心（一條 curl）

```bash
curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT_ID}" \
  --data-urlencode "text=$(cat 訊息檔案.txt)" > /dev/null
```
要點：`--data-urlencode` 處理中文/換行/特殊字元；純文字即可（不用 parse_mode，
Markdown 轉義坑多）；訊息上限 4096 字元，日報級長度安全。

### 6.3 通道一：管線自動訊息（fetch-quotes.yml 內建步驟）

掃描器每次跑完寫兩個檔：`alert.txt`（僅有警報時存在）、`digest.txt`（每次都寫）。
workflow 的 telegram 步驟按優先級發：

```yaml
- name: telegram notify
  env:
    TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
    TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
    WANT_DIGEST: ${{ inputs.digest || 'true' }}   # dispatch 可帶 digest=false 靜默跑
  run: |
    MSG=""
    if [ -s tradingview/data_external/alert.txt ]; then
      MSG=tradingview/data_external/alert.txt          # 有警報發警報
    elif [ "$WANT_DIGEST" != "false" ] && [ -s tradingview/data_external/digest.txt ]; then
      MSG=tradingview/data_external/digest.txt         # 否則發日報
    fi
    if [ -n "$MSG" ] && [ -n "$TG_BOT_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
      curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=$(cat $MSG)" > /dev/null && echo "telegram sent: $MSG"
    else
      echo "nothing to send or no token - skip"
    fi
```
`digest=false` 的用途：session 做驗證性/中途刷新時不騷擾使用者，警報仍照發。

### 6.4 通道二：任意訊息（send-telegram.yml，session 隨時可用）

Session 想發任何一條訊息（對沖指令、臨時提醒、月報）：

```bash
echo "🔔 訊息內容" > .github/tg_outbox.txt
git add .github/tg_outbox.txt && git commit -m "notify: ..." && git push
```
`send-telegram.yml` 監聽 `on.push.paths: ['.github/tg_outbox.txt']`，push 即發。
這就是「session 無外網卻能主動推手機」的完整答案：**寫檔 → push → workflow 發**。

### 6.5 踩過的坑

- **字串替換上 YAML 要驗證**：第一版 telegram 步驟因 Edit 錨點不存在而靜默沒加上,
  push 前 `grep` 確認片段真的在檔案裡
- getUpdates 自動偵測 chat_id 只在使用者剛發過訊息時有效（24h 窗）→ 固定存
  `TG_CHAT_ID` secret,別依賴自動偵測
- Actions 日誌會自動遮罩 secrets（顯示 ***），但 echo 整條 URL 仍是壞習慣,別做
- 每次 push tg_outbox.txt 都是一條新訊息——同一內容重複 push 會重複發,
  發送用 commit 訊息區分意圖（`notify: ...`）

## 七、IB 管道（2026-09-25 起建，解鎖日經/歐洲）

沙盒出口只有 GitHub，IB Gateway 需要常駐登入——所以 IB 採集**跑在使用者的
GCP VM**（或任何常開機器），產出 push 回 repo，session 照常讀。與 Actions 橋樑同構。

### 架構
```
GCP VM: IB Gateway(常駐登入) ← ib_collector.py(ib_insync, 延遲數據)
        → ib_iv_log.csv → git push → repo → session 讀取/回測/金絲雀
```

### 關鍵設計決定
1. **延遲數據就夠**（`reqMarketDataType(3)`）：監測/研究用，免每月訂閱費。
   下單永遠用券商實時報價（本專案鐵律），所以延遲完全無害。
2. **v1 只收兩個市場**：N225（OSE，日經案 §12.5 復活條件）+ ESTX50（Eurex，
   歐洲金絲雀）。每天各記「最近週權 vs 最近月權 ATM IV + 斜率」一行。
3. 到期/行使價用 `reqSecDefOptParams` 自動發現；IV 優先取 IB modelGreeks，
   缺失時用中間價反推 Black-76（腳本內建 bisection）。

### 使用者要做的一次性設置（沙盒做不了）
1. IB 帳戶：建議**另開 paper 帳戶專供數據**（避開 live 帳 2FA 對 headless 的干擾；
   paper 繼承 live 的數據權限）。
2. VM 裝 IB Gateway + [IBC](https://github.com/IbcAlpha/IBC)（自動登入/重啟）；
   `pip install ib_insync`。
3. Repo clone 到 VM：用 **fine-grained PAT（只授本 repo contents:rw）** 或 deploy key。
4. crontab 掛 `gcp_ib/run_daily.sh`（建議 UTC 07:35：東京收盤後、法蘭克福盤中）。
5. 首跑先 `python3 gcp_ib/ib_collector.py --dry` 看鏈發現是否正常，把輸出貼給 session 調試。

### 安全鐵律
- IB 帳密只存在 VM 的 IBC 設定檔（chmod 600），**永不**進 repo/聊天/日誌。
- PAT 只授單一 repo 讀寫，不用 classic 全域 token。
- 採集器無下單權：Gateway 設定裡把 API 設 read-only（Configure → API → Read-Only API ✓）。

### 之後可擴充
- KOSPI200（KSE）、FTSE（ICEEU）同法加 MARKETS 一行
- 恒指/MES 的 IB 實時對板（quality_log 第四源）
- 日經 VRP 回測數據累積（週月 IV + N225 現貨已有 → 月度模擬可起）

### 排障記錄（2026-09-25 首日接通實錄，後來者按序自查）
1. **Cloud Shell ≠ VM**：最常見的坑。Cloud Shell 是臨時機，裝什麼都會蒸發，
   Gateway 也不在那裡。凡是操作，先認提示符 `@ib-data` 才動手。
2. **Debian 12 pip 被 PEP668 擋** → `--break-system-packages`（setup 已內建後備）。
3. **記憶體**：Gateway 的 Java 在 1–2GB 機上會被 OOM 殺或原生崩潰（曾崩在
   getenv）→ 加 2GB swap（setup 未含，見下）＋自癒器每 5 分鐘重試直到起來。
4. **SSH 登出殺進程** → 啟動一律 `setsid` + `</dev/null`（setup 已修）。
5. **edemo 幽靈**：config.ini 沒改到時 Gateway 用示範帳號登入，永遠報
   Invalid username or password。paper 帳戶要用**專屬**用戶名（Client Portal →
   Settings → Paper Trading Account），不是 live 帳號。
6. **10141 Paper disclaimer**：模擬帳第一次 API 前要在 Gateway 畫面按一次
   「I understand and accept」——headless 下用 `xdotool` 隔空點（座標從
   `import -window root` 截圖量）。
7. **Existing session**：網頁/手機登著同一 paper 帳會搶席位，Gateway 彈
   Reconnect This Session——同樣 xdotool 點掉，平時避免瀏覽器掛著 paper。
8. **採集器三修**：到期窗口 1–14/15–60 天（N225 只有月權）；行使價按距離試
   6 檔（月權網格較疏，鏈上 strikes 是全到期聯集）；延遲數據要輪詢 ~16 秒
   才灌進 modelGreeks。
9. **遙控迴路**：`gcp_ib/ib-trigger`（首行=參數，改 nonce 即觸發）→ VM 看門狗
   每 10 分鐘 pull → 跑採集 → `last_run.log` + CSV 推回。git add 多檔要分開加
   （一檔缺席會整條放棄）。git 首推需 user.name/email + credential store。
