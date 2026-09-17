# 部署到 GCP（多檔案版）

v12 不再只有 `main.py`，多了兩個網頁檔。**部署方式沒有變，只是要一次上傳四個檔案，而且四個都必須放在同一層（根目錄）。**

## 一、檔案結構（這就是「來源」的內容）

```
main.py            ← 進入點，必須叫這個名字
requirements.txt   ← 套件清單
gates.html         ← 關卡開關頁（獨立版）
order.html         ← 送單參數頁
```

不要放進子資料夾。`main.py` 是用「自己所在的目錄」去找那兩個 HTML：

```python
GATES_APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gates.html")
```

放到 `templates/`、`static/` 之類的子目錄就會找不到。

部署設定（維持你原本的）：

| 項目 | 值 |
|---|---|
| 進入點 (Entry point) | `receive_tradingview_signal` |
| 執行階段 (Runtime) | Python 3.11 或 3.12 |
| 觸發條件 | HTTP，允許未驗證的叫用 |
| 記憶體 | 256 MB 以上 |
| 逾時 | 60 秒（要比 EA 的 WebRequest 逾時短） |

---

## 二、方法 A：Console 行內編輯器（最接近你現在的做法）

1. 開啟函式 → **編輯** → 下一步到 **來源 (Source)** 分頁。
2. 左側是檔案清單，原本只有 `main.py` 和 `requirements.txt`。
   按清單上方的 **＋（新增檔案）**，檔名輸入 `gates.html`，把整個檔案內容貼進去。
3. 同樣方式再新增 `order.html`。
4. 確認 `main.py` 與 `requirements.txt` 也是最新版本。
5. 按 **部署**，等狀態變成綠勾。

> 貼上時要貼「整個檔案」，包含第一行的 `<!DOCTYPE html>` 和最後的 `</html>`。
> 行內編輯器不會自動存檔，換檔案前先確認內容已經在編輯器裡。

## 三、方法 B：gcloud CLI（推薦，一行搞定）

把四個檔案放在同一個資料夾，在那個資料夾裡執行：

```bash
gcloud functions deploy receive_tradingview_signal \
  --gen2 \
  --runtime=python312 \
  --region=asia-east1 \
  --source=. \
  --entry-point=receive_tradingview_signal \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512Mi \
  --timeout=60s
```

`--source=.` 會把整個資料夾（除了 `.gcloudignore` 排除的）打包上傳，所以之後不管加幾個檔案都是同一行指令。
`--region` 請換成你現在用的區域。

## 四、方法 C：直接從 GitHub 部署

Console 的來源分頁選 **Cloud Source Repository / 從存放區部署**，指向這個 repo 與分支，
「函式進入點」一樣填 `receive_tradingview_signal`，目錄留在根目錄即可。
之後改程式只要 push，再按一次部署（或設定 Cloud Build 觸發器自動部署）。

---

## 五、環境變數（都有預設值，可以不設）

| 變數 | 預設 | 說明 |
|---|---|---|
| `WEBHOOK_SECRET_TOKEN` | `123456` | EA 與管理頁面的權杖 |
| `WEBHOOK_API_KEY` | 內建值 | webhooktrade 的 api_key（也可在送單參數頁改） |
| `ADMIN_API_REQUIRE_TOKEN` | `1` | 關卡開關／送單參數的寫入是否需要權杖 |
| `ADMIN_CORS_ORIGIN` | `*` | 允許哪個網域開這兩個獨立頁；建議收窄成你的網址 |
| `RISK_PCT` | `0.02` | 整組倉位打到止損的最大虧損比例 |
| `BROKER_LEVERAGE` | `500` | **請改成你真實的槓桿** |
| `ACCOUNT_TO_USD_RATE` | `0` | 帳戶不是 USD/HKD 時必填 |
| `AI_REVIEW_ENABLED` | `1` | 是否呼叫 Gemini 覆核 |
| `NEWS_FAIL_CLOSED` | `1` | 日曆載不到時禁止新倉 |

送單參數（手數、商品、止損止盈、移動止損）現在**不用改環境變數**，直接在送單參數頁改即可。

## 六、服務帳號權限

函式使用的服務帳號需要：

- `roles/storage.objectAdmin`（或至少對 `zhuge-risk-manager-bucket` 的讀寫）— 所有狀態都存在這個 bucket。
- `roles/aiplatform.user` — 只有在 `AI_REVIEW_ENABLED=1` 時需要（Vertex AI Gemini）。

## 七、部署後檢查

用瀏覽器打開函式網址，依序確認：

| 網址 | 應該看到 |
|---|---|
| `?view=welcome` | 機械人 logo 與四個磁磚 |
| `?view=gates_app` | 關卡開關（獨立版），狀態自動載入 |
| `?view=order_app` | 送單參數頁，封包預覽有內容 |
| `?view=dashboard` | 控制台 |
| `?view=info` | 投資人日誌 |

**如果 HTML 檔案漏了沒上傳**，系統不會整個壞掉：

- `gates.html` 缺少 → `?view=gates_app` 自動退回內建版關卡開關頁（功能仍可用）。
- `order.html` 缺少 → `?view=order_app` 回傳 `order.html 不存在於部署內容中`，其他頁面不受影響。

Cloud Logging 會有對應的 `⚠️ [關卡開關獨立頁讀取失敗 → 改用內建頁面]` 或 `⚠️ [送單參數頁讀取失敗]` 訊息。
