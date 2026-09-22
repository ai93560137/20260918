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

## 其他分支怎麼用這批數據

數據只住在 `claude/gifted-carson-v2tvhw` 這條分支（排程每天 commit 進來）。
其他分支不需要合併整條分支，只把需要的目錄拉過來：

```bash
git fetch origin claude/gifted-carson-v2tvhw
git checkout origin/claude/gifted-carson-v2tvhw -- data/stocks/ data/stocks_hkex/ scripts/pointintime/
# 回測引擎/抓取腳本也要的話：
git checkout origin/claude/gifted-carson-v2tvhw -- stock_momentum_backtest.py scripts/
```

拉之前先看 `data/stocks/QC_REPORT.md` 的 🔴。港股選股回測請用
`scripts/pointintime/`（逐年真成分股），不要用 `scripts/pool_hsi_full.txt`
（「現在的名單」，只剩歷史對照用途）。

## 第二來源與每日品質檢查

每次排程抓完 yfinance 後，同一個 workflow 接著：

1. `scripts/fetch_hkex_equity.py` 抓第二來源**港交所官方每日報價表**（Daily Quotations，
   `hkex.com.hk/eng/stat/smstat/dayquot/d<YYMMDD>e.htm`，全市場每檔官方英文簡稱 + 前收/收市/高低/成交）→
   `data/stocks_hkex/quotes_<交易日>.json`（只留我們 universe 的代碼，幾 KB/天）。每次往回補最近 10 天
   沒存過的交易日。首次驗證：2026-09-22 106 檔可比，105 檔與 yfinance 收市價完全一致、其餘 <1%。
   Stooq 已擋自動下載、港交所 widget 端點參數未解，都不用。
2. `scripts/check_data_quality.py --fetch-names` 產生 **`data/stocks/QC_REPORT.md`
   （每日品質日報）**，並更新 `data/stocks/names_yf.json`（yfinance 公司名與改名歷史）。

**Telegram 推送**（方法見 `claude/dazzling-curie-f3xzb8` 的 `tradingview/DATA_PIPELINE.md` 第6節）：
- 通道一（管線內建）：有 🔴 即時發警報（`qc_alert.txt`）；否則每個交易日港股收市那輪
  （09:00 UTC）發日報（`qc_digest.txt`）；手動觸發預設靜默，dispatch 帶 `digest=true` 才發
- 通道二（任意訊息）：寫 `.github/tg_outbox_research.txt` + push，`send-telegram-research.yml` 發送。
  **不要用** `.github/tg_outbox.txt`——那是八陣圖交易指令的通道，共用會衝突/重發
- 基準 2800 超過 6 天沒新數據 → 🔴 `pipeline_stale`（主來源抓取壞了）

日報分三級：🔴 嚴重（會污染回測，先處理）、🟡 注意、✅ 已確認
（`scripts/qc_acks.json`，人工核對過的項目，附理由）。逐根價格檢查只對近 30 天
每天警告，更早的彙總在報告最後的「歷史已知」表。**用這批數據回測前先看日報的 🔴。**

名字檢查特別重要：港交所代碼在公司下市/私有化後會重新分配給別家公司，yfinance
只保留新公司的價格。已確認的例子：`0013.HK` 當年是和記黃埔（2010-2015成分股），
現在的價格是 2021 年上市的和黃醫藥；`1880.HK` 當年是百麗國際（2011-2018），現在是
2022 年上市的中國中免。這類代碼在日報會標 `code_reuse_suspected`。

港股的開/收市價常落在 High-Low 範圍外（開市前競價、收市競價的成交價不一定計入
數據商的持續交易時段高低價），日報標 `ohlc_auction` 屬 🟡，多半是慣例差異不是髒值；
`ohlc_high_lt_low`（High < Low）才是真的損壞。

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
