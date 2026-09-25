# 數據目錄（供回測使用）

這個分支負責**提供數據**，回測在其他分支進行。以下兩份數據都由 GitHub Actions 自動更新，
提交到 workflow 所在的分支（PR 合併後就是預設分支 `claude/gcp-trading-v12-rewrite-bz75t2`）。

從其他分支讀取，不必合併：

```bash
B=origin/claude/gcp-trading-v12-rewrite-bz75t2
git fetch origin claude/gcp-trading-v12-rewrite-bz75t2
git archive "$B" data/insider data/pelosi | tar -x -C /tmp/data_src   # 解到任意資料夾，不影響目前分支
```

| 數據 | 路徑 | 範圍 | 更新 | 產生腳本 |
|---|---|---|---|---|
| 內部人公開市場買入（SEC Form 4） | `data/insider/purchases/{年}.csv.gz` | 2006-01 起，所有申報公司（約 16,000 個代號），約 123 萬列 | 每週日 03:00 UTC（重抓最近兩季） | `scripts/insider_fetch.py` |
| 財報事件（SEC 8-K Item 2.02） | `data/news/sp500_earnings_events.csv.gz` | 2005-01 起，申報當時的 S&P 500 成分股，約 4.7 萬筆 | 美股收盤後每日 | `scripts/news_8k_fetch.py` |
| 歷史代號 ↔ CIK | `data/insider/ticker_cik/{季}.csv.gz` | 2006Q1 起，所有 Form 3/4/5 申報公司 | 隨內部人數據每週 | `scripts/insider_fetch.py` |
| 回購授權（美，SEC 8-K 判讀） | `data/buyback/us/events.csv.gz` | 2006-01 起，全市場，約 1.65 萬筆 | 美股收盤後每日 | `scripts/buyback_fetch.py` |
| 實際回購申報（港，披露易） | `data/buyback/hk/reports.csv.gz` | 2007-06 起，約 8.3 萬筆、1,085 檔 | 同上 | `scripts/buyback_fetch.py` |
| 董事會買回決議（台，公開資訊觀測站） | `data/buyback/tw/resolutions.csv.gz` | 2000 起，上市＋上櫃 5,759 筆 | 同上 | `scripts/buyback_fetch.py` |
| 佩洛西交易申報（眾議院 PTR） | `data/pelosi/transactions.json` | 2014-11 起，65 份申報、226 筆交易 | 每 4 小時 | `scripts/pelosi_tracker.py` |

---

## 1. 內部人買入 `data/insider/purchases/{年}.csv.gz`

來源：SEC Insider Transactions Data Sets（Form 3/4/5 的 XML 攤平表）。**只保留非衍生性、交易代碼 `P`
（公開市場買入）、取得（A）的交易**；賣出、授予、行權都不在內。年份 = SEC 收件季度的年份。

| 欄位 | 說明 |
|---|---|
| `quarter` | SEC 資料集季度（如 `2025q1`），更新時以季為單位整批替換 |
| `accession` | 申報編號；同一份申報可能有多筆交易 |
| `filing_date` | 申報日（只有日期，沒有時間）→ 回測應在**隔一個交易日開盤**進場 |
| `trans_date` | 實際交易日 |
| `doc_type` | `4`（117.7 萬列）、`4/A` 修正申報（3.5 萬，會重報同一筆交易）、`5`／`5/A` 年度補報（2.1 萬） |
| `ticker` | 申報上的代號，已轉大寫；可能是舊代號、空白或 `NONE` |
| `issuer_cik` / `issuer_name` | 發行公司（CIK 比代號穩定，改名不變） |
| `owner_cik` / `owner_name` | 申報人 |
| `relationship` | `Director`、`Officer`、`TenPercentOwner`、`Other`，可多個逗號分隔 |
| `title` | 職稱（Officer 才有，如 `CEO`、`Chief Financial Officer`；自由文字） |
| `shares` / `price` / `value` | 股數、每股價、金額（= 股數 × 價；價格缺漏時 `value` 為空） |
| `shares_after` | 交易後持股 |
| `direct` | `D` 直接持有、`I` 間接持有 |

**使用前必讀：**
- **聯名申報會展開成多列（影響很大）**：一份申報有多位申報人（例如基金與其 GP）時，每位申報人各一列，
  **同一筆交易會重複出現**——全表約 55.9 萬列（45%）與其他列共用同一筆交易。
  加總金額或計算筆數前，先以 `(accession, trans_date, shares, price)` 去重。
- **修正申報會重複**：`4/A` 會重報原交易；以 `(owner_cik, ticker, trans_date, shares, price)` 保留最早的申報日。
- **10% 大股東多半是基金**，不是公司內部人：只有 `TenPercentOwner` 身分的列有 47.2 萬（38%）。
  研究「內部人訊號」時通常只留 `relationship` 含 `Director` 或 `Officer` 的列。
- **代號不可直接對價格**：要處理改名（renames）與代號被別家公司重用；建議用 point-in-time 成分股名單配對，
  並檢查價格歷史在入選日前就存在（見 `scripts/insider_backtest.py` 的做法）。
- **小額與缺值**：金額 < $100 的有 2.9 萬列、沒有價格（`value` 空白）的有 1.7 萬列；常見做法是單筆 < $10,000 不算。
- 最新一季要等 SEC 季末後上線才會出現；`data/insider/state.json` 記錄每季的列數與抓取日。

讀取範例：

```python
import csv, glob, gzip
rows = [r for p in sorted(glob.glob("data/insider/purchases/*.csv.gz"))
        for r in csv.DictReader(gzip.open(p, "rt", encoding="utf-8"))]
```

---

## 2. 財報事件 `data/news/sp500_earnings_events.csv.gz`

來源：SEC `data.sec.gov/submissions`，只留 8-K／8-K/A 且 items 含 `2.02`（Results of Operations）。

| 欄位 | 說明 |
|---|---|
| `cik` / `company` | 公司（CIK 為主鍵） |
| `form` | `8-K` 或 `8-K/A`（修正） |
| `accession` | 申報編號 |
| `filing_date` | 申報日 |
| `acceptance` | SEC 收件時間，**UTC**，精確到秒 |
| `acceptance_et` / `session` | 美東時間；`pre`（09:30 前）、`regular`（盤中）、`post`（16:00 後） |
| `items` | 8-K 項目，常見 `2.02,9.01` |
| `ticker` / `price_ticker` | 成分股名單上的代號／價格資料夾用的代號（已套改名） |
| `member_start` | 該段成分股區間起日 |

**使用前必讀：**
- **時間是 UTC**：美股盤後財報約為 20:00–21:30 UTC。決定事件日請用 `session`：`pre` 當天反應，其餘隔一交易日。
- **8-K 時間可能晚於新聞稿**：時段分布為盤前 53%、盤後 32%、盤中 16%。盤中那部分多半是盤前已發新聞稿、
  白天才補交 8-K。用 8-K 時間不會偷看未來，但事件日可能晚一天；計算反應時窗口從 t0 前一日收盤起算，可涵蓋這種情況。
- **8-K/A 與同一季多份 2.02**：常見修正或補充公告，回測通常同一公司 30 天內只取第一份。
- **成分股對照**：`data/news/sp500_cik_map.csv` 記錄每段區間用哪個 CIK（公司重組會分段），
  錯配修正在 `data/news/cik_overrides.csv`；38 段已下市區間對不到 CIK（如 FNMA、VIAB、WAMUQ），這些事件缺漏。
- **價格代號可能被重用**：已下市公司的代號後來可能給了別家（如 CAM、JAVA），價格資料夾裡可能是新公司的股價；
  回測要檢查價格歷史在成分股起日前就存在。

---

## 3. 佩洛西交易 `data/pelosi/transactions.json`

來源：眾議院書記官處 Periodic Transaction Report（PDF 解析）。每個元素是一份申報：

| 欄位 | 說明 |
|---|---|
| `doc_id` / `url` | 申報編號與原始 PDF |
| `filing_date` | 申報日 |
| `transactions[]` | 該申報的交易，欄位如下 |

交易欄位：`owner`（`SP` 配偶…）、`asset`、`ticker`、`asset_type`（`ST` 股票、`OP` 期權、`AB`/`OT` 其他）、
`type`（`P` 買、`S` 賣、`S (partial)` 部分賣、`E` 交換）、`date`（交易日）、`amount`（金額區間文字）、
`amount_min` / `amount_max`、`description`、`option`（期權才有：`action`、`contracts`、`kind`、`strike`、`expiry`）。

**使用前必讀：**
- **金額只有區間**（如 $1,000,001–$5,000,000），沒有股數。
- **申報延遲**：交易日到申報日中位數約 24 天，最長 45 天；回測只能用 `filing_date` 之後的價格。
- **修正申報重複**：例如 2015-07-07 那份重報了 2014-12-17 的 Hertz 交易，以最早申報為準。
- **2014 年版格式較舊**：部分期權只寫「Purchase of N Options」，`option.kind` / `strike` / `expiry` 為空。
- **行使期權**（說明含 `Exercised`）是延續既有部位，不是新的買入決定。
- 每份 PDF 抽出的原文在 `data/pelosi/raw/{doc_id}.txt`，解析規則改了可以 `--reparse` 重跑，不必重新下載。

---

## 4. 回購（美、港、台）`data/buyback/`

三個市場的「回購」意義不同，**不能直接合併比較**：美國是董事會新增授權、香港是實際買回、台灣是董事會買回決議。

### 美國 `us/events.csv.gz`（新增或加碼授權）

來源：SEC 全文搜尋找含回購授權用語的 8-K → 下載內文逐句判讀。逐月原始結果在 `us/months/{YYYY-MM}.csv.gz`
（含判為舊計畫、無關的申報與全部候選句），`events.csv.gz` 只留判為新授權的。

| 欄位 | 說明 |
|---|---|
| `adsh` / `cik` / `company` | 申報編號、公司 |
| `ticker` | 申報上的代號；**約 28% 空白**（舊申報沒有），請用 `cik` 對 `data/insider/ticker_cik/` 的當季代號 |
| `file_date` / `acceptance_et` / `session` | 申報日；SEC 收件時間（美東）；`pre`／`regular`／`post` |
| `items` | 8-K 項目；含 `2.02` 表示與財報同時宣布 |
| `amount_usd` / `shares` / `pct` | 授權金額（美元）、股數、占流通股比例；加碼時為增加的部分；**約 16% 三者皆空** |
| `sentence` / `candidates` | 判讀依據的原句、所有候選句（供稽核與改規則重判） |

**使用前必讀：**
- **判讀準確率約 90%**（樣本外 50 筆，信賴區間約 78%–96%），見 `us/AUDIT.md`。誤判多為「回顧已公告的授權」，
  事件日會偏晚，對策略不利、不會美化結果。
- 事件日請用 `session`：`pre` 當天開盤可進場，其餘隔一交易日。
- 同一公司常在財報 8-K 與另一份 8-K 各提一次，回測要以公司去重（例如 180 天內只取第一次）。
- 價格資料是 Yahoo 全市場，有倖存者偏差（下市公司缺價）。

### 香港 `hk/reports.csv.gz`（實際買回申報）

來源：披露易「翌日披露報表 → Share Buyback」（2009 起）與舊「Share Buyback Reports」（2007-06 至 2008）。
港股每年股東大會都會給一般授權，「授權」沒有訊號意義，所以抓的是**實際買回**的申報。

| 欄位 | 說明 |
|---|---|
| `stock_code` / `stock_name` | 股票代號（5 位數）；2009 年前的彙總報表一列可能含多檔，以 `|` 分隔 |
| `date_time` | 發佈時間（香港時間，`DD/MM/YYYY HH:MM`），通常是買回當日傍晚 → 下一交易日才能用 |
| `title` / `category` / `file_link` | 標題、分類、PDF 連結（`https://www1.hkexnews.hk` + 連結） |

**使用前必讀：**
- **只能回溯到 2007-06**（披露易此分類的起點）。
- 只有標題資料，沒有買回股數與金額（在 PDF 內）。可用的訊號是「沉寂一段時間後開始買回」或買回頻率。
- `(Cancelled and Reissued)` 開頭的分類是重發，與原申報重複，去重時以股票代號＋日期為準。

### 台灣 `tw/resolutions.csv.gz`（董事會買回決議）

來源：公開資訊觀測站「買回自己公司股份彙總統計表」（t35sc09），上市 `sii`＋上櫃 `otc`。

| 欄位 | 說明 |
|---|---|
| `co_id` / `name` / `market` | 公司代號、名稱、上市或上櫃 |
| `resolution_date` | 董事會決議日；重大訊息須在**次一營業日開盤前**公告 → 決議日隔天開盤可進場 |
| `purpose` | 1 = 轉讓員工、2 = 股權轉換、3 = 維護公司信用及股東權益（最接近「股價被低估」） |
| `planned_shares` / `price_low` / `price_high` / `period_start` / `period_end` | 預定買回股數、價格區間、期間 |
| `legal_cap_twd` | 法定上限金額（依最新財報），不是這次預定買回的金額 |
| `completed` ~ `incomplete_reason` | 執行結果 |

**使用前必讀：**
- **執行結果欄位（已買回股數、比例、金額、未執行原因）要到期間結束後才知道**，回測只能當事後分析，不能當進場訊號。
- 沒有流通股數，規模比例要另外用股價資料換算（預定股數 × 價格 ÷ 市值）。
- 股災年份決議特別多（2008 年 696 筆），事件在時間上高度集中，檢定時要按月份分組。

---

## 已有的研究結論（供參考，不必重做）

- `data/pelosi/backtest/README.md`：申報日跟單，持有 12 個月年化 +27%，但主要是大型科技股 beta，
  且有選人偏差；她 2027 年初卸任後不會再有新申報。
- 內部人買入回測（S&P 500 point-in-time、以等權 S&P 500 為基準）：16 種組合的 t 值都不到 2，
  大型股沒有可靠的超額報酬。報告在 `data/insider/backtest/README.md`。
- PEAD（財報後 2 天異常報酬 ≥ +5% 且量 ≥ 2 倍，持有 60 日）：逐筆超額 t = 0.17，9 格鄰域沒有一格 t ≥ 1.5，
  大型股財報後沒有可交易的漂移。報告在 `data/news/backtest/README.md`，規格在 `research/news_trade/STRATEGY.md`。
