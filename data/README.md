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

## 已有的研究結論（供參考，不必重做）

- `data/pelosi/backtest/README.md`：申報日跟單，持有 12 個月年化 +27%，但主要是大型科技股 beta，
  且有選人偏差；她 2027 年初卸任後不會再有新申報。
- 內部人買入回測（S&P 500 point-in-time、以等權 S&P 500 為基準）：16 種組合的 t 值都不到 2，
  大型股沒有可靠的超額報酬。報告在 `data/insider/backtest/README.md`。
