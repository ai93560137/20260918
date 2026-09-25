# 給雲垂分支的 IBKR 數據需求（stock_research/IBKR_DATA_REQUEST.md）

發出：鳥翔（股票研究）分支 `claude/stock-research-k9nzau`，2026-09-25。
收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM 上有 IB Gateway paper 帳戶、IBC 常駐、`ib_insync`，見該分支 `gcp_ib/`）。
格式照外匯分支 `forex_research/IBKR_DATA_REQUEST.md`。

## 0. 為甚麼要這些數據（一段話）

鳥翔策略（趨勢模板股全部等權，月底選股、下一交易日開市成交）已進入前向記錄。主數據是 Yahoo 日線，月底名單的收市價現在用港交所／Nasdaq／證交所／Yahoo!ファイナンス覆核，
但**韓澳加印新沒有獨立第二來源**（只能 Yahoo 重抓），而且沒有任何來源能給我們「下一交易日開市價」——那是回測的成交假設，實盤滑價要對它量。
IBKR 是券商口徑的獨立來源：**訊號日收市**用來覆核名單，**下一交易日開市**用來當執行基準（實際成交 vs 開市價 = 滑價）。
只讀、只要日線、每月一次，每次約 500–700 檔。

## 1. 清單（P0 一種就夠）

| 優先 | 合約 | `whatToShow` | K 線 | 每檔請求 | 需要的欄 | 輸出檔（`data_stock_ibkr/`） | 用途 |
|---|---|---|---|---|---|---|---|
| **P0** | `analysis/tt_all/ibkr_request.csv` 列出的股票（market, ticker, signal_date）：`Stock(symbol, exchange, currency)`，映射在腳本 `to_ib()`：港 SEHK／新 SGX／加 TSE／澳 ASX／美 SMART／日 TSEJ／印 NSE／台 TWSE／韓 KSE | `TRADES` | 1 day，`useRTH=True` | 1 個（`1 M`） | 訊號日收市、下一交易日日期／開市／收市 | `<市場>_<訊號日>.csv` | 名單收市覆核＋執行基準 |

- 印度、台灣、韓國 IB 很可能不提供（非居民／未上架），**預期失敗**：把 `no_contract`／錯誤訊息留在檔內與 `_status.txt` 就好，不要想辦法繞。
- 加拿大 `BAM-A.TO` 之類的類別股，腳本已把 `-` 換成 `.`；美股 `BRK-B` 換成 `BRK B`。若某檔解析不到合約，記 `no_contract` 即可。
- IB 的日線 TRADES 是按拆股還原、不按股息，與我們的 Close 口徑相同，直接比得上。

## 2. 怎樣跑（腳本已寫好在本分支）

```bash
# 在 VM 上，只取需要的檔，不要合併分支
cd <repo>
git fetch origin claude/stock-research-k9nzau
git checkout origin/claude/stock-research-k9nzau -- scripts/ib_stock_verify.py analysis/tt_all/ibkr_request.csv
mkdir -p data_stock_ibkr

# 第一步先 probe：每個市場各試 1 檔，看合約解析與權限（error 162／10167／200 "No security definition"）
python3 scripts/ib_stock_verify.py --port 4002 --job probe
cat data_stock_ibkr/_status.txt

# probe 通過的市場再跑正式（每檔 1 個請求、隔 2.5 秒；600 檔約 25 分鐘；可續抓，ok 的列會跳過）
nohup python3 scripts/ib_stock_verify.py --port 4002 --job closes > data_stock_ibkr/closes.log 2>&1 &
# 只跑某些市場：--market hk sg ca au us jp
```

- 遇 pacing violation 腳本自己等 60 秒重試；同一 clientId（24）不要並行。
- 只讀：不下單、不改帳戶；帳密只在 IBC 的 config.ini，不進 repo、不進對話。

## 3. 交付

1. 把 `data_stock_ibkr/` 整個資料夾（含 `_status.txt` 與 `.log`）**commit 到雲垂分支**（每檔幾十 KB，直接進 git）。
2. commit 訊息寫 `data(ibkr): 鳥翔月底名單 收市／開市覆核 <訊號日>`；鳥翔分支會 `git fetch` 後 `git checkout origin/claude/dazzling-curie-f3xzb8 -- data_stock_ibkr` 取用，
   再跑 `python3 scripts/tt_all_verify.py --ibkr`（把 IBKR 當第三把尺，寫進網頁「覆核」欄與 Telegram）。
3. 若 probe 就被擋（paper 帳戶沒有某交易所的歷史數據權限），**不要買訂閱**——交回錯誤訊息，我們再決定。

## 4. 鳥翔分支收到後會做的檢查

- 每市場：IB 收市 vs 我們的收市，差 ≤ 1% 算一致；不一致的逐檔查（拆股、代號重用、停牌）
- 「下一交易日開市」存檔作**執行基準**：投資人填 `analysis/tt_all/executions.csv` 的成交價後，滑價 = 成交價 ÷ IB 開市價 − 1
- 韓澳加印新若 IB 有數據，就從「只有 Yahoo 重抓」升級為有獨立來源

## 5. 每月

月底名單出來後（10 月 1 日起每月），鳥翔分支會更新 `analysis/tt_all/ibkr_request.csv` 並在交接處說一聲；雲垂只需重跑第 2 節的兩行。

## 6. 不要做的事

- 不要用這些數據跑任何回測或改鳥翔的規則——規格已凍結，跑數在鳥翔分支。
- 不要改 `gcp_ib/ib_collector.py`（這次不需要每日採集）。
- 不要把 `data_stock_ibkr/` 合併回其他分支。
