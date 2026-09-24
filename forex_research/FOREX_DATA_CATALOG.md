# 外匯數據目錄（FOREX_DATA_CATALOG.md）

**26 個商品（七大主要貨幣對、14 個交叉盤、3 個亞洲貨幣、金銀現貨）的 M1／H1／D1 歷史**，2026-09 為外匯策略測試建立。
來源 Dukascopy 免費歷史行情（瑞士銀行，2003 年起，UTC 時間，買價 bid 為主、另存 H1／D1 賣價 ask 供算點差），
第二來源 Yahoo 日線與 FRED（聯儲 H.10 紐約中午匯率）。**數據不進 git**，存 GitHub Release `forex-data`（整個倉庫共用）。

程式在分支 `claude/forex-data-testing-w4q3m2`（由股票研究分支 `claude/gifted-carson-v2tvhw` 合併而來，研究手冊與工具齊全）。

## 1. 一鍵取得

```bash
git fetch origin claude/forex-data-testing-w4q3m2
git merge --no-edit origin/claude/forex-data-testing-w4q3m2   # 或只 checkout scripts/get_forex_data.py + scripts/fetch_forex.py
python3 scripts/get_forex_data.py                             # 全部 26 個商品 → data_forex/<PAIR>/
python3 scripts/get_forex_data.py --group majors              # 只拿七大
python3 scripts/get_forex_data.py --pair EURUSD --merge-m1 /tmp/eurusd_m1.csv   # 順便合併 M1 給回測引擎
python3 scripts/get_forex_data.py --list                      # 看下載網址
```
- 雲端沙盒可以直接下載 Release（與股票數據相同）；沙盒**連不到** Dukascopy／Yahoo／FRED，抓新數據只能在 GitHub Actions
- 更新數據：手動觸發 `.github/workflows/fetch_forex.yml`（group = majors／crosses／asia／metals／all）；
  它先從 Release 還原、只補缺的月／日，抓完重新上傳 Release 並 commit 品質報告

## 2. 商品

| 分組 | 商品 | 小數位 | FRED 第二來源 |
|---|---|---|---|
| majors（七大） | EURUSD、USDJPY、GBPUSD、USDCHF、AUDUSD、USDCAD、NZDUSD | JPY 3、其餘 5 | 直接對應（DEXUSEU、DEXJPUS…） |
| crosses（交叉盤） | EURJPY、GBPJPY、AUDJPY、NZDJPY、CADJPY、CHFJPY、EURGBP、EURCHF、EURAUD、EURCAD、GBPCHF、GBPAUD、AUDNZD、AUDCAD | JPY 3、其餘 5 | 由主要貨幣對相乘／相除推算 |
| asia | USDHKD、USDCNH、USDSGD | 5 | DEXHKUS、DEXCHUS（在岸 CNY，與 CNH 有差）、DEXSIUS |
| metals | XAUUSD、XAGUSD | 3 | 無（只有 Yahoo） |

- 完整清單與 Yahoo 代號：`python3 scripts/fetch_forex.py --list`；定義在 `scripts/fetch_forex.py` 的 `INSTRUMENTS`
- 各商品實際起迄、根數、缺口、點差、第二來源差異：**DATA_QC.md**（總表）與 `data_qc/<PAIR>_qc.md`（逐商品）
- **不加歐洲股市**（使用者規矩）；EUR／GBP／CHF 貨幣對是外匯，不在此限

## 3. 檔案格式

```
data_forex/<PAIR>/
  <PAIR>_M1_<YYYY>.csv.gz     # M1 買價，每年一檔（與 data/ 的 MT5 匯出同一命名）
  <PAIR>_H1.csv.gz            # H1 買價（單檔）        <PAIR>_H1_ask.csv.gz   # H1 賣價
  <PAIR>_D1.csv.gz            # D1 買價（單檔）        <PAIR>_D1_ask.csv.gz   # D1 賣價
  _ref_yahoo.csv.gz           # Yahoo 日線 Date,Open,High,Low,Close（收市可靠、高低價粗糙）
  _ref_fred.csv.gz            # FRED 紐約中午匯率 Date,Close（交叉盤為推算值）
  _done.json / _status.txt    # 已完成的年／月（續抓用）、狀態
```
- 欄位 `Time,Open,High,Low,Close,Volume`；`Time` 為 `YYYY-MM-DD HH:MM:SS` **UTC**（沒有券商時差；`backtest.py` 載入器直接讀，`--broker-offset 0`）
- `Volume` 是 Dukascopy 自己的成交量單位（只作相對比較）
- Dukascopy 週六沒有數據、週日 21:00／22:00 UTC 開始；每根 K 線的時間是開盤時間
- D1 的日界：由 M1 按 UTC 日聚合與 Dukascopy D1 的吻合率判斷（DATA_QC.md「D1 收吻合%」）；若不吻合，日線策略請自己從 M1／H1 聚合
- M1 只有買價；點差用 H1 賣價 − 買價估（按年、按時段中位數在品質報告裡）。**Dukascopy 是 ECN 原始點差，CFD 券商通常寬 2–5 倍**，
  回測成本請按自己券商的實際點差（手冊鐵律 2、3）

## 4. 怎樣用來回測

```bash
# 現有 M1 引擎（八陣圖通道突破 / ZGL）：合併 M1 後直接跑，時間已是 UTC
python3 scripts/get_forex_data.py --pair EURUSD --merge-m1 /tmp/eurusd_m1.csv
python3 donchian_backtest.py /tmp/eurusd_m1.csv --broker-offset 0 --spread 0.0001 --lookback 2 --mode sar
```
- 八陣圖的損益以「報價單位 × 單位值」解讀：EURUSD 一手 100,000 → 1 pip = 10 USD；JPY 對 1 pip = 1000 JPY；`--spread` 用價格單位（EURUSD 1 pip = 0.0001）
- 已判決（RESEARCH_HANDBOOK.md 第二節）：八陣圖 on 歐元 ☠️（CFD 4 年樣本）、XAUUSD ✅；**判決不重測**，
  新的外匯測試必須是新假設或新市場，而且要先預先登記（見 README.md）
- pandas 讀法：`pd.read_csv("data_forex/EURUSD/EURUSD_H1.csv.gz", parse_dates=["Time"]).set_index("Time")`

## 5. 各商品要注意的地方

| 項目 | 注意 |
|---|---|
| 全部 | Dukascopy 早年（2003–2006）M1 有較多缺口與零波幅 K 線；點差在 2008 前明顯較寬（品質報告按年中位）；假期（聖誕、元旦）平日沒有數據屬正常 |
| JPY 對 | 小數 3 位、1 pip = 0.01；2011-03、2016-06、2022-09／10、2024-07 有日本央行干預，M1 尖刺清單會列出 |
| USDCHF／EURCHF | 2015-01-15 瑞郎脫鉤：EURCHF 一分鐘跌 20% 以上，是真實事件不是壞數據；點差當日極寬 |
| USDHKD | 聯繫匯率 7.75–7.85，日均波幅極小 → 波幅 ÷ 點差通常不及格，只作參考 |
| USDCNH | 離岸人民幣 2011 年後才有；FRED 只有在岸 CNY，差 0.1–1% 屬正常 |
| XAUUSD | `data/XAUUSD_*`（CFD 券商 MT5，2022-08 起）與 Dukascopy 的差異、券商時差（UTC+2／+3 逐月）見 `data_qc/XAUUSD_qc.md` 第 8 節 |
| Yahoo 第二來源 | Yahoo 外匯日線的日界（約 21:00–23:00 UTC）與 Dukascopy 不同，收市差 0.1–0.3% 屬正常，只用來抓 > 2% 的離群天 |
| FRED 第二來源 | 紐約中午買入價（16:00 UTC 夏令／17:00 UTC 冬令），品質檢查兩個時點取較近者；只有平日、美國假期缺 |

## 6. 更新與擴充

- **加商品**：`scripts/fetch_forex.py` 的 `INSTRUMENTS` 加一行（Dukascopy 路徑、小數位、分組、Yahoo 代號、FRED 系列），
  觸發 `fetch_forex.yml`（group = 該分組），更新本目錄第 2 節
- **加時間框架**：Dukascopy 另有 M5／M15／M30／H4 檔（路徑同 H1，改 `candles_min_5` 等），或直接由 M1 聚合
- **M1 賣價**：目前不抓（請求數加倍）；八陣圖類「觸價成交」策略若要精確賣價，用 H1 點差按時段加回去
- **Tick 數據**：Dukascopy 也有逐筆（每小時一檔 `<hh>h_ticks.bi5`），一個商品 20 年約 30 萬個檔，需要時另開工作流程
