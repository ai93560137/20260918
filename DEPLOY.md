# GCP 部署教學（一步一步）

適用版本：v12（四個檔案）。整份照著做約 15 分鐘。

> Console 的按鈕名稱 Google 偶爾會改，以下用「類似」描述時請找意思相同的按鈕。
> 指令列（gcloud）那一套不會變，怕迷路可以直接跳到 **附錄 A**。

---

## 第 0 步：先準備好這四個檔案

```
main.py            ← 進入點，檔名不能改
requirements.txt   ← 套件清單
gates.html         ← 關卡開關頁（獨立版）
order.html         ← 送單參數頁
```

**四個必須放在同一層，不能放子資料夾。** `main.py` 是用自己所在的目錄去找兩個 HTML：

```python
GATES_APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gates.html")
```

貼上時確認頭尾完整：

| 檔案 | 第一行 | 最後一行 |
|---|---|---|
| `main.py` | `# =====…` | `    return response` |
| `gates.html` | `<!DOCTYPE html>` | `</html>` |
| `order.html` | `<!DOCTYPE html>` | `</html>` |

---

## 第 1 步：確認專案與計費

1. 開 https://console.cloud.google.com/
2. 左上角專案選單 → 選你放這個系統的專案（記下專案 ID）。
3. 左側選單 **帳單 (Billing)** → 確認這個專案已連結有效帳單帳戶。
   沒有帳單的專案無法部署 Cloud Functions。

## 第 2 步：啟用需要的 API（只需做一次）

左側選單 **API 和服務 → 程式庫**，搜尋並逐一按「啟用」：

- Cloud Functions API
- Cloud Run Admin API
- Cloud Build API
- Artifact Registry API
- Cloud Storage API
- Vertex AI API（只有要用 Gemini 覆核時需要）

> 用指令一次啟用：
> ```bash
> gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
>   cloudbuild.googleapis.com artifactregistry.googleapis.com \
>   storage.googleapis.com aiplatform.googleapis.com
> ```

## 第 3 步：確認 GCS bucket 存在

系統所有狀態（電閘、加單基準、決策日誌、關卡開關、送單參數）都存在 bucket：

1. 左側選單 **Cloud Storage → 儲存空間**。
2. 找 `zhuge-risk-manager-bucket`。
   - 已經有 → 跳到第 4 步。
   - 沒有 → 按「建立」，名稱填 `zhuge-risk-manager-bucket`，
     位置選跟函式同一個區域，其餘保留預設。

## 第 4 步：建立（或編輯）函式

### 4-1 第一次建立

1. 左側選單 **Cloud Run functions**（舊名 Cloud Functions）→ **建立函式**。
2. 填寫：

   | 欄位 | 填什麼 |
   |---|---|
   | 環境 | 第 2 代 (2nd gen) |
   | 函式名稱 | `receive_tradingview_signal` |
   | 區域 | 選離你近的，例如 `asia-east1`（台灣）。**記住它** |
   | 觸發條件類型 | HTTPS |
   | 驗證 | **允許未經驗證的叫用**（EA 與網頁要能直接打） |

3. 展開 **執行階段、建構作業、連線和安全性設定**：

   | 欄位 | 填什麼 |
   |---|---|
   | 記憶體 | 512 MiB |
   | 逾時 | 60 秒 |
   | 執行階段服務帳戶 | 預設的 Compute Engine 服務帳戶即可 |

4. 同一頁的 **執行階段環境變數**，按「新增變數」加入（詳見第 6 步）。
5. 按 **下一步**，進入來源畫面。

### 4-2 已經有函式（你的情況）

進入該函式 → **編輯** → 一路到 **來源** 分頁。

## 第 5 步：放入四個檔案 ★ 重點

在 **來源** 分頁：

1. 原始碼選 **行內編輯器 (Inline editor)**，執行階段選 **Python 3.12**（3.11 也可以）。
2. 左邊是檔案清單，預設有 `main.py` 和 `requirements.txt`。
3. 先更新 `main.py`：點它 → 全選（Ctrl/Cmd + A）→ 貼上新內容。
4. 點 `requirements.txt` → 全選 → 貼上新內容。
5. 按檔案清單上方的 **＋（新增檔案）**：
   - 檔名輸入 `gates.html` → 貼上整個檔案內容。
   - 再按一次 ＋，檔名輸入 `order.html` → 貼上整個檔案內容。
6. 右上或下方的 **進入點 (Entry point)** 欄位填 `receive_tradingview_signal`
   （必須跟 `main.py` 裡 `def receive_tradingview_signal(request)` 同名）。
7. 按 **部署**。

> 貼上時瀏覽器可能會卡一下（`main.py` 有三千多行），等它反應完再換下一個檔案。
> 換檔案前先確認內容真的在編輯器裡，行內編輯器不會自動儲存。

## 第 6 步：環境變數

在「執行階段環境變數」加入，**全部都有預設值，但這幾個建議設定**：

| 變數 | 建議值 | 為什麼 |
|---|---|---|
| `WEBHOOK_SECRET_TOKEN` | 自己取一組長字串 | EA 與管理頁面的權杖，別再用預設的 `123456` |
| `BROKER_LEVERAGE` | 你真實的槓桿，例如 `500` | 算保證金上限用，填錯會算錯倉位 |
| `ACCOUNT_TO_USD_RATE` | 帳戶非 USD/HKD 時才填 | 例如帳戶是 TWD 就填 `0.031` |
| `ADMIN_CORS_ORIGIN` | 你的頁面網址 | 預設 `*` 代表任何網站都能打這兩個管理 API |
| `AI_REVIEW_ENABLED` | `1` 或 `0` | 不想用 LLM 覆核就填 `0`，可省 Vertex AI 權限 |
| `AI_SHADOW_MODE` | `1`（建議先開） | 見下方說明。AI 照樣判斷並記錄，但**不否決訊號** |
| `BROKER_UTC_OFFSET_HOURS` | `3`（程式預設值已是 3） | MT5 伺服器時間 − UTC。夏令結束後可能要改 `2` |
| `TARGET_RRR` | `3`（程式預設值已是 3） | 止盈 = 止損 × 幾倍。依 8.5 個月回測從 2 改為 3 |
| `DISTANCE_UNIT` | `price`（預設）或 `points` | 選用哪一組距離欄位，見第 8b 步 |
| `ORDER_ACCOUNT` | `1` | webhooktrade 範本的 account 欄位 |

改完要重新部署才生效。**送單參數（手數、商品、止損止盈）不用設環境變數**，部署後直接在送單參數頁改。

### 關於 `AI_SHADOW_MODE`

AI 覆核是一道**只能否決、不能加分**的關卡，而它對獲利因子的貢獻**從來沒有被量測過**
（`BACKTEST.md` 的所有數字都是在 AI 覆核關閉下跑出來的）。

問題在於：被 AI 擋掉的訊號不會下單，也就沒有實際損益，所以在強制執行模式下，
**永遠無法驗證它擋得對不對**。

`AI_SHADOW_MODE=1` 讓 AI 照常判斷並把結論寫進 `ai_training/sft_dataset.jsonl`，
但不否決訊號。等累積夠多已平倉的樣本後，用 `ai_eval.py` 對帳：

```bash
gsutil cp gs://zhuge-risk-manager-bucket/ai_training/sft_dataset.jsonl .
python3 ai_eval.py sft_dataset.jsonl --provider recorded
```

報表會直接回答「AI 攔掉的單，實際結算是賺還是賠」。如果是賺的，代表這道關卡
正在侵蝕獲利，應該把 `ai` 加進 `DEFAULT_BYPASS`。

> ⚠️ 影子模式期間 AI 不再擋單，等於少一層過濾，其餘八道關卡照常運作。
> 要恢復強制執行就把這個變數設回 `0`。

## 第 7 步：給服務帳號權限

1. 左側選單 **IAM 與管理 → IAM**。
2. 找函式用的服務帳號（預設是 `專案編號-compute@developer.gserviceaccount.com`）。
3. 按編輯（鉛筆）→ 新增角色：
   - **Storage 物件管理員**（`roles/storage.objectAdmin`）— 讀寫 bucket，必須有。
   - **Vertex AI 使用者**（`roles/aiplatform.user`）— 只有 `AI_REVIEW_ENABLED=1` 時需要（影子模式也會呼叫 AI，同樣需要）。
4. 儲存。

> 少了 Storage 權限，網頁打得開但所有狀態都讀不到，日誌會一直出現
> `⚠️ [電閘狀態讀取失敗 → 視為 LOCK]`。

## 第 8 步：拿到網址並驗證

部署完成（綠色勾）後，在函式的 **觸發條件** 分頁複製網址，長得像：

```
https://asia-east1-你的專案.cloudfunctions.net/receive_tradingview_signal
```

用瀏覽器依序打開，五個都要正常：

| 網址後面加上 | 應該看到 |
|---|---|
| （不加） | 機械人 logo ＋ 四個磁磚 |
| `?view=gates_app` | 關卡開關（獨立版），右上角顯示「已連線」 |
| `?view=order_app` | 送單參數頁，封包預覽有內容 |
| `?view=dashboard` | 控制台，電閘狀態 |
| `?view=info` | 投資人日誌 |

在關卡開關頁與送單參數頁，把 **管理權杖** 欄位填成你的 `WEBHOOK_SECRET_TOKEN`，
勾「記住設定」，之後這台裝置就不用再填。

## 第 8b 步：確認距離欄位用哪一組

webhooktrade 有兩組距離欄位，單位不同，**只能擇一送出**：

| 欄位組 | 欄位名稱 | 值的單位 | 系統送出的範例 |
|---|---|---|---|
| **price（預設）** | `sl_distance_price`、`tp_distance_price`、`ts_activation_price`… | 美元 | `"13.00"` |
| points | `sl_distance`、`tp_distance`、`ts_activation`… | 點數 | `"1300"` |

XAUUSD 兩位小數：1 美元 = 100 點，所以同一個止損距離在兩組的數字差 100 倍。

系統預設用 **price（美元）**，因為止損距離是由 ATR 算出來的美元金額，直接送最直覺。
要改成點數就到送單參數頁把「距離單位（欄位組）」改成 `points`（不需重新部署），
或設環境變數 `DISTANCE_UNIT=points`。

第一次部署後仍建議用一張最小手數的單核對：到 MT5 看止損距離，對照送單參數頁
「最後一次實際送出的封包」——止損應該 ≈ `sl_distance_price` 的美元數字。

## 第 9 步：把網址給 MT5 EA

MT5 → **工具 → 選項 → EA 交易** → 勾「允許 WebRequest 至以下 URL」→ 加入函式網址 → 確定。
EA 的參數裡也要填同一個網址與 `WEBHOOK_SECRET_TOKEN`。

---

## 之後要改程式怎麼辦？

1. 函式頁面 → **編輯** → **來源**。
2. 改哪個檔就點哪個檔貼上新內容（沒改的不用動）。
3. **部署**。

只改了環境變數的話，一樣要按一次部署。

---

## 常見問題排查

| 症狀 | 原因與處理 |
|---|---|
| 部署失敗，訊息提到 `requirements` | `requirements.txt` 沒貼完整，或貼成了 `main.py` 的內容 |
| 部署失敗，訊息提到 entry point / function not found | 進入點沒填 `receive_tradingview_signal`，或 `main.py` 貼到一半 |
| 首頁打得開，但 `?view=gates_app` 變成另一個樣子 | `gates.html` 沒上傳；系統自動退回內建版關卡頁（功能仍可用） |
| `?view=order_app` 顯示「order.html 不存在於部署內容中」 | `order.html` 沒上傳，補上去再部署即可 |
| 所有頁面都顯示「讀取失敗」 | 服務帳號缺 Storage 權限，或 bucket 名稱不同（見第 7、3 步） |
| 頁面按儲存時出現 `Unauthorized token` | 權杖欄位沒填，或跟 `WEBHOOK_SECRET_TOKEN` 不一致 |
| 電閘一直是 LOCK | 正常：要先累積約 65 根 M1 K 線，再等 Setup → Trigger。控制台的 M1 雷達會顯示進度 |
| AI 覆核一直失敗 | 缺 Vertex AI 權限，或區域不支援；不想用就設 `AI_REVIEW_ENABLED=0` |
| EA 回報 WebRequest 失敗 | 第 9 步的網址沒加進 MT5 白名單，或網址少了結尾的函式名稱 |

**看日誌**：函式頁面 → **記錄 (Logs)** 分頁，系統每一次決策都會寫在這裡
（`📥 [收到封包]`、`📊 [M1 盤勢監控]`、`🎯 [首單候選]`、`✅ [已送出]`…）。

---

## 附錄 A：用 gcloud 指令部署（最省事）

四個檔案放同一個資料夾，在該資料夾執行：

```bash
gcloud config set project 你的專案ID

gcloud functions deploy receive_tradingview_signal \
  --gen2 \
  --runtime=python312 \
  --region=asia-east1 \
  --source=. \
  --entry-point=receive_tradingview_signal \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512Mi \
  --timeout=60s \
  --set-env-vars=WEBHOOK_SECRET_TOKEN=你的權杖,BROKER_LEVERAGE=500,AI_SHADOW_MODE=1,BROKER_UTC_OFFSET_HOURS=3
```

以後不管加幾個檔案，都是同一行指令（`--source=.` 會打包整個資料夾）。
本專案附的 `.gcloudignore` 會自動排除 `.git`、`__pycache__` 與說明文件。

查看日誌：

```bash
gcloud functions logs read receive_tradingview_signal --region=asia-east1 --limit=50
```

## 附錄 B：從 GitHub 部署

來源分頁選「從存放區部署」，指向本 repo 與分支，目錄留根目錄（`/`），
進入點一樣填 `receive_tradingview_signal`。之後改程式只要 push 再按部署。
