# 給雲垂分支的 IBKR 數據需求（forex_research/IBKR_DATA_REQUEST.md）

發出：外匯分支 `claude/forex-data-testing-w4q3m2`，2026-09-25。
收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM 上有 IB Gateway paper 帳戶、IBC 常駐、`ib_insync`，見該分支 `gcp_ib/`）。

## 0. 為甚麼要這些數據（一段話）

外匯分支五份登記、17 個正式檢定（趨勢、利差、價值、動量、利率變動、期限利差、VIX、COT、新興市場宇宙）**全部 ☠️**，
swap 加價 0% 也是負的，死因是月頻籃子沒有毛利，不是成本（`forex_research/VERDICTS.md`）。
剩下沒測過、而且需要 IBKR 才拿得到數據的兩個物種：
1. **外匯波動溢價**（賣出對沖過的跨式；雲垂在股指上已證明 t 11.7）——要 CME 外匯期貨的**隱含波動歷史**；
2. **日內策略的真實點差**——要 IDEALPRO 的 **BID_ASK 歷史 K 線**（HistData M1 沒有買賣價）。
拿到第 1 項我就寫波動溢價的預先登記（門檻 t ≥ 3）；第 2 項只是為日內物種過入場券做準備，優先級低。

## 1. 清單（按優先級；P0 先跑，P1 有空才跑）

| 優先 | 合約 | `whatToShow` | K 線 | 每次請求 | 目標回溯 | 輸出檔（`data_forex_ibkr/`） | 用途 |
|---|---|---|---|---|---|---|---|
| **P0** | CME 外匯期貨連續合約：EUR、JPY、GBP、CHF、AUD、CAD、NZD、MXP（`ContFuture(sym,'CME','USD')`） | `OPTION_IMPLIED_VOLATILITY` | 1 day | 1 Y | **能拉多深拉多深**（少於 8 年就不夠做判決，但先拉） | `fut_<CCY>_D1_option_implied_volatility.csv.gz` | 波動溢價的 IV 序列 |
| **P0** | 同上 | `HISTORICAL_VOLATILITY` | 1 day | 1 Y | 同上 | `fut_<CCY>_D1_historical_volatility.csv.gz` | 與我們自己算的實現波動互相核對 |
| **P0** | 同上 | `TRADES`、`BID_ASK` | 1 day | 1 Y | 同上 | `fut_<CCY>_D1_trades.csv.gz`、`_bid_ask.csv.gz` | 期貨基差（機構口徑的實際利差成本）、期貨點差 |
| P1 | IDEALPRO 現貨 EURUSD GBPUSD AUDUSD NZDUSD USDJPY USDCHF USDCAD（`Forex(pair)`） | `BID_ASK` | 5 mins | 1 W | 2 年（約 105 個請求／對，7 對約 3.5 小時） | `spot_<PAIR>_M5_bid_ask.csv.gz` | 真實點差的日內分佈 |
| P2（加進每日採集） | CME 外匯期權：EUR、JPY 前月 ATM 跨式 IV（同 `gcp_ib/ib_collector.py` 的做法，`Option` on `CME`／`tradingClass` 由 `reqSecDefOptParams` 取） | 即時延遲報價 | 每日一次 | — | 前向 | 追加到 `tradingview/data_external/ib_iv_log.csv`（market 欄填 `6E`、`6J`） | 即使歷史 IV 拉不到，也從今天起累積前向樣本 |
| 選配 | 帳戶管理 → Reports → Interest：外匯各貨幣借貸利率表（不是 API，網頁匯出 CSV 或截圖） | — | 一次 | — | — | `data_forex_ibkr/ibkr_interest_rates_<日期>.csv` 或 `.png` | 校正 `FX_COST_MODEL.md` 的加價假設 |

BID_ASK K 線的欄位意義（IB 定義）：Open = 時段平均買價、Close = 時段平均賣價、High = 最高賣價、Low = 最低買價。
所有時間統一 UTC（腳本已處理 `formatDate=2`）。

## 2. 怎樣跑（腳本已寫好在本分支）

```bash
# 在 VM 上，先把本分支的腳本拿過來（不要合併分支，只取一個檔）
cd <repo>
git fetch origin claude/forex-data-testing-w4q3m2
git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/ib_fx_history.py
mkdir -p data_forex_ibkr

# 第一步一定先 probe：每種請求各試一次，看有沒有權限錯誤（error 162／10167「No market data permissions」）、回傳幾根
python3 scripts/ib_fx_history.py --port 4002 --job probe
cat data_forex_ibkr/_status.txt

# P0（三個 job 可以順序跑；每個請求隔 11 秒，8 個合約 × 每年 1 個請求，20 年約 1 小時）
nohup python3 scripts/ib_fx_history.py --port 4002 --job iv  > data_forex_ibkr/iv.log  2>&1 &
# 等 iv 跑完再跑 fut（同一個 clientId 不要同時開兩個）
nohup python3 scripts/ib_fx_history.py --port 4002 --job fut > data_forex_ibkr/fut.log 2>&1 &
# P1（約 3.5 小時；可用 --years 1 先跑一年）
nohup python3 scripts/ib_fx_history.py --port 4002 --job spot5m --years 2 > data_forex_ibkr/spot.log 2>&1 &
```

- 腳本可續抓：中斷後重跑，會從已有檔的最早一筆之前接著往前補。
- 連續 3 次空回應就停（代表 IB 的歷史深度到了，這本身就是我要的資訊——請把 `_status.txt` 一起交回）。
- 只讀：不下單、不改帳戶；帳密只在 IBC 的 config.ini，不進 repo、不進對話。

## 3. 交付

1. 把 `data_forex_ibkr/` 整個資料夾（含 `_status.txt` 與各 `.log`）**commit 到雲垂分支**（單檔 < 25 MB 直接進 git；5 分鐘 K 線每對約 10–15 MB gz，應該可以）；
   若哪個檔太大，改上傳到 Release `forex-data`（`gh release upload forex-data <檔> --clobber`），並在 `_status.txt` 寫明。
2. 在雲垂分支的 commit 訊息寫 `data(ibkr): 外匯期貨 IV／現貨 BID_ASK 歷史`，外匯分支會 `git fetch` 後 `git checkout origin/claude/dazzling-curie-f3xzb8 -- data_forex_ibkr` 取用。
3. 若 probe 就被擋（paper 帳戶沒有 CME 歷史數據權限），**不要**去買訂閱——先把錯誤訊息交回，我們再決定是否值得訂（CME 期貨數據每月十美元級）。

## 4. 外匯分支收到後會做的檢查（先講清楚，免得來回）

- 每個序列的起迄、筆數、缺月；IV 序列與 FRED 的 EVZ（歐元波動指數，2007 → 2025-03）逐日對照，中位差應 < 1 個波動點；
- `HISTORICAL_VOLATILITY` 與我們用 Dukascopy D1 算的 21 日實現波動對照；
- 期貨 TRADES 收市 vs 現貨中價的基差年化後，與 FRED 三個月利差對照（差額 = 期貨路徑的實際成本，校正 `FX_COST_MODEL.md`）；
- 5 分鐘 BID_ASK 的點差分佈（按小時、按年），與 `forex_research/DATA_QC.md` 的 Dukascopy 點差對照。
通過後才寫波動溢價的預先登記；IV 歷史不足 8 年就只做前向記錄，不做判決。

## 5. 不要做的事

- 不要用這些數據跑任何外匯回測——登記在外匯分支，跑數也在外匯分支（一次）。
- 不要改 `gcp_ib/ib_collector.py` 的既有市場（N225、ESTX50）；P2 只是追加兩個市場。
- 不要把 `data_forex_ibkr/` 合併回其他分支。
