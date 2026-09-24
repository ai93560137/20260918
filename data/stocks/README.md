# data/stocks/（已停用，2026-09-23 遷移）

港股日線原本以 `data/stocks/<TICKER>.csv.gz`（整檔 gzip、每天重寫）存放。這種格式每次更新都讓 git
多存一份完整的二進位檔（8 輪就長了 64MB，照此速度一年約 4GB），已於 2026-09-23 遷移到新格式：

```
data/equities/hk/<TICKER>/prices_<YYYY>.csv   原始日線（每天只有今年那個檔多一行）
data/equities/hk/<TICKER>/actions.csv         股息/拆股（股息已換算成價格幣別）
data/equities/hk/<TICKER>/shares.csv          流通股數
data/equities/hk/QC_REPORT.md                 每日品質報告（原 data/stocks/QC_REPORT.md）
data/equities/hk/_names.json                  yfinance 公司名/行業（原 data/stocks/names_yf.json）
```

格式與讀法見 `data/equities/README.md`、根目錄 `marketdata.py`。**讀價一律用 `marketdata.load_series()`**，
不要直接讀檔——它處理了垃圾列過濾、人工修正（adjustments/price_overrides）與 AdjClose 重算。

遷移驗證：新舊格式跑港股 4 組選股回測（低波動、動量、行業中性、高股息）完整輸出逐字元相同、
行業動量相同、前向模擬盤選股/結算核對 0 不一致；113 檔收市價最大差 0.06%、還原價最大差 0.6%。

舊的 `.csv.gz` 仍在 git 歷史裡（commit b40d8b20 之前），需要可以用 `git show` 取回。

## 其他分支怎麼用

```bash
git fetch origin claude/gifted-carson-v2tvhw
git checkout origin/claude/gifted-carson-v2tvhw -- data/equities/ data/stocks_hkex/ marketdata.py universe.py universes/ scripts/pointintime/
```
