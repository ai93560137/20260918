# 港股/美股/日股日線數據（data/equities/，v2 格式）

美股/日股由 `.github/workflows/fetch_equities.yml`、港股由 `.github/workflows/fetch_stock_data.yml`
排程抓取（yfinance），格式與讀法見根目錄 `marketdata.py`。港股 2026-09-23 從舊的 `data/stocks/*.csv.gz`
遷移過來（驗證見 `data/stocks/README.md`）。讀價一律用 `marketdata.load_series()`。

## 目錄

```
data/equities/<market>/<TICKER>/prices_<YYYY>.csv   Date,Open,High,Low,Close,Volume
data/equities/<market>/<TICKER>/actions.csv         Date,Dividend,Split
data/equities/<market>/<TICKER>/shares.csv          Date,Shares（週一更新）
data/equities/<market>/_fetch_status.json           每檔最後抓取結果、AdjClose 重算誤差、失敗次數
data/equities/<market>/_names.json                  yfinance 公司名/sector/industry（週一更新，含改名歷史）
data/equities/<market>/_second/quotes_<date>.json   第二收市源每日快照（美股 Nasdaq.com、日股 Yahoo!ファイナンス）
data/equities/jp/_jpx_listed.json                   JPX 東証上場銘柄一覧（官方日文名、33業種、TOPIX 規模）
data/equities/<market>/QC_REPORT.md                 每日品質報告（含倖存者偏差洞比例）
```

- `<market>`：`hk`（`0700.HK`）、`us`（代碼無後綴，Yahoo 格式 `BRK-B`）、`jp`（`7203.T`）；指數代碼 `^` 存成 `_`
- 股息以**價格幣別**存：Yahoo 的 Dividends 欄是派息幣別（匯豐等 2011 年前以美元宣派、價格是港元），
  抓取時用 Yahoo 自己 Adj Close 的除淨跳幅換算，原值存 `DividendRaw`
- 人工修正：`universes/<market>/adjustments.csv`（Yahoo 漏調的分拆）、`price_overrides.csv`（單日錯價），
  由全量歷史比對抓到、查證後登記，載入時套用，原始檔不改
- 價格是**原始價**：Close 已按拆股還原（Yahoo 慣例）、**未按股息還原**；總回報要用
  `marketdata.load_ohlcv()` / `load_series()` 算出的 AdjClose（除淨日之前的價格乘
  1 − 股息 ÷ 除淨前一日收市，Yahoo/CRSP 法；每檔抓取時都跟 yfinance 的 Adj Close 比對過，
  誤差記在 `_fetch_status.json` 的 `adj_err_max`）
- 1995 年起（S&P 500 PIT 名單 1996 起）

## 為什麼不用港股那種 .csv.gz

整檔 gzip 每天重寫、股息一回溯全部 AdjClose 都變，二進位檔在 git 裡無法做差異壓縮——
港股 100 檔跑 8 輪就讓 repo 長了 64MB（一年約 4GB）。新格式每天只有「今年那個檔」多一行、
舊年份不動，美股 900 檔一天只增加幾十 KB。

## 其他分支怎麼用

```bash
git fetch origin claude/gifted-carson-v2tvhw
git checkout origin/claude/gifted-carson-v2tvhw -- data/equities/ marketdata.py universe.py universes/
```

## 已知限制

- **倖存者偏差**：Yahoo 不保留已下市（被收購/破產）股票的歷史。S&P 500 自 2008 年以來
  約 345 檔被移出，其中被收購/下市的抓不到——這些「消失的公司」在回測裡不存在。
  各年缺口比例見 `QC_REPORT.md` 的「倖存者偏差洞」表，判讀回測時要打折。
- 改代碼的公司（FB→META）Yahoo 只用新代碼保存整段歷史，PIT 名單的舊代碼要對照
  `universes/us/renames.csv` 改掛新代碼（`scripts/build_universe_us.py`）。
