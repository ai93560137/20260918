# 股票/指數日線數據目錄（data/stocks/）

由 `.github/workflows/fetch_stock_data.yml` 排程自動抓取（yfinance），
與 `data/` 根目錄下的 MT5 M1 期貨/CFD 數據是不同格式、不同用途，分開存放。

## 格式

```
data/stocks/<TICKER>.csv.gz     # yfinance 代碼，^ 換成 _（如 ^HSI -> _HSI.csv.gz）
```

欄位：`Date,Open,High,Low,Close,AdjClose,Volume`

- `Date` 為 `YYYY-MM-DD`（交易日，無時區問題，日線不需要 broker-offset）。
- `AdjClose` 已還原股息與拆股（yfinance `auto_adjust=False` 的 `Adj Close`）——
  算總回報基準（RESEARCH_HANDBOOK.md 第三節第7條）一律用這欄，不要用 `Close`。
- 每次排程執行對每個 ticker 重抓全部歷史並整檔覆寫，不做增量合併。

## 已知限制（回測前必讀 RESEARCH_HANDBOOK.md 第三節）

- `scripts/universe_hk.txt` / `scripts/universe_us.txt` 目前是自動化管線的
  起手清單，**不是權威的 point-in-time 成分股表**——只用今天還在市場上的
  名單去回測會有倖存者偏差，正式回測前需對照官方歷史成分股名單或明示打折。
- yfinance 的港股數據品質、除權息調整、停牌處理不如 MT5 券商數據穩定，
  用於個股回測前先抽樣核對幾檔已知數字（如 2800.HK 對比盈富基金官方淨值）。

## 用法

```bash
# 手動補跑（本機需要 pip install -r scripts/requirements.txt）
python3 scripts/fetch_stock_data.py scripts/universe_hk.txt scripts/universe_us.txt

# 讀取範例
zcat data/stocks/2800.HK.csv.gz | head
```
