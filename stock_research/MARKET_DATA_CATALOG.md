# 全市場股票數據目錄（MARKET_DATA_CATALOG.md）

**9 個市場、約 2.3 萬檔股票的日線**，2026-09 為 VCP／Minervini／相場師朗／新高研究建立。不論那些策略結果如何，
這批數據、品質檢查與回測工具**任何分支都可以直接拿來回測其他策略**，或把已有策略拿去別的市場驗證（見 VERDICTS.md 第 2 節的空格）。

程式在分支 `claude/gifted-carson-v2tvhw`；日線**不進 git**，放在 GitHub Release（整個倉庫共用）。

## 1. 一鍵取得

```bash
git fetch origin claude/gifted-carson-v2tvhw
git merge --no-edit origin/claude/gifted-carson-v2tvhw   # 或 checkout 需要的檔（第 3 節）
python3 scripts/get_market_data.py                      # 全部 9 個市場（約 1.2 GB）→ data_full/<m>/，並重建品質排除檔
python3 scripts/get_market_data.py --market in sg       # 只拿幾個
python3 scripts/get_market_data.py --list               # 看下載網址
```
- 已實測：雲端沙盒可直接下載 Release；重建的品質排除檔與原版逐字相同
- GitHub Actions 裡也可以用 `gh release download fullmarket-data -p hk.tar`（港日美）／`gh release download oos-data -p in.tar`（其他）
- Actions 快取按分支隔離，**其他分支拿不到快取，只能用 Release**

## 2. 各市場概況（2026-09-24 快照）

| 代碼 | 市場 | Yahoo 代號 | 候選池（來源） | 有日線 | 品質排除 | 日線最早 | 基準 ETF（Yahoo 起） | 全市場前 N | 每邊成本 | 大小 | Release |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hk | 港股 | `0005.HK` | 2,797（港交所證券名單 股本類 + 恒指歷史成分） | 2,787 | 971 | 2000 | 2800.HK（data/） | 500 | 25 bps | 99 MB | fullmarket-data |
| jp | 日股 | `7203.T` | 3,746（JPX 内国株式 + 日經歷史成分） | 3,707 | 34 | 2000 | 1321.T（data/） | 1000 | 15 bps | 220 MB | fullmarket-data |
| us | 美股 | `AAPL` | 6,281（Nasdaq screener + S&P/NDX/Dow 歷史成分） | 5,834 | 143 | 1995 | SPY（data/） | 1500 | 10 bps | 321 MB | fullmarket-data |
| tw | 台灣 | `2330.TW`／`6488.TWO` | 1,979（證交所 ISIN：上市 1,084、上櫃 893 普通股） | 1,979 | 47 | 2000 | 0050.TW（2009-01） | 500 | 30 bps | 121 MB | oos-data |
| kr | 韓國 | `005930.KS`／`035720.KQ` | 2,552（FinanceDataReader：KOSPI 827、KOSDAQ 1,723；去 SPAC） | 2,544 | 16 | 2000 | 069500.KS（2007-01） | 700 | 15 bps | 149 MB | oos-data |
| au | 澳洲 | `BHP.AX` | 2,047（ASXListedCompanies.csv） | 1,551 | 99 | 1995 | STW.AX（2008-01） | 500 | 10 bps | 61 MB | oos-data |
| ca | 加拿大 | `RY.TO`、`BBD-B.TO` | 2,125（TSX 主板公司目錄，去 ETF／優先股／權證） | 2,115 | 88 | 1995 | XIU.TO（1999-10） | 400 | 10 bps | 65 MB | oos-data |
| in | 印度 | `RELIANCE.NS` | 2,322（NSE EQUITY_L.csv，SERIES EQ） | 2,322 | 23 | 1996 | NIFTYBEES.NS（2009-01） | 700 | 20 bps | 113 MB | oos-data |
| sg | 新加坡 | `D05.SI` | 603（SGX 證券 API：股票＋REIT） | 571 | 59 | 1995 | ES3.SI（2008-01） | 200 | 20 bps | 21 MB | oos-data |

- 候選池快照在 git：`universes/full/<m>_pool.txt`（檔頭寫來源與日期）；品質報告：港日美 `research/vcp_full/<m>_qc.md`，其他 `research/oos/<m>_qc.md`
- 「日線最早」是最早的股票；大部分股票較晚上市。回測樣本起點 = max(引擎設定, 基準 ETF 在 Yahoo 的第一日)
- 全市場前 N 與成本在 `vcp_backtest.FULL_TOP_N`／`FULL_COST`；引擎市場設定在 `newhigh_backtest.MARKETS`

### 檔案格式
`data_full/<m>/<TICKER>.csv.gz`（指數 `^` 換成 `_`，例：`_NSEI.csv.gz`），欄位 `Date,Open,High,Low,Close,AdjClose,Volume`
（yfinance、`auto_adjust=False`：**Close 已按拆股還原、AdjClose 再按股息還原**）。同資料夾：
`_failed.txt`（Yahoo 抓不到的代號）、`_status.txt`、`_qc_exclude.txt`（整檔排除）、`_qc_zombie.json`（殭屍段，載入時丟掉）

### 各市場要注意的地方
| 市場 | 注意 |
|---|---|
| 全部 | **倖存者偏差**：候選池只有現存股票（下市股大多不在）→ 回測偏高，門檻要從嚴；**數據斷點**：原始收市一日 > +100% 或 < −60% 的縫接／垃圾列（港 437、美 2,682、澳 1,166 個…，2026-09-24 掃描）不在結構檢查排除範圍內——動量／排序類策略必須另外剔除（`tt_momentum_backtest.py` 的 `bad` 規則：斷點前 25 日至後 252 日不作候選，等權基準同樣剔除）；`m.ew_ret` 未剔除這些日子，此前各測試的「相對等權 t」受影響 |
| 港股 | 收市價可靠（對港交所日報表 0 差）；**盤中高低價不可靠**（948 檔收市超出高低價）→ 只用開收市的策略可用 `load_full("hk", repair_hl=True)` 放回這些股票（只作敏感度） |
| 日股 | 最乾淨；第二來源 Yahoo!ファイナンス 歷史價**不按拆股還原**（核對時用 `--split-ok`） |
| 美股 | 小型股尖刺多；Nasdaq 第二來源只有近 10 年 |
| 台灣 | 漲跌停 ±7%（2015-06 前）→ ±10%；證交稅賣方 0.3%；證交所每日收盤行情可做第二來源（只在 Actions 連得到）；**基準 0050.TW 在 Yahoo 只把 2014-01-02 之後按 2025-06 的 1 拆 4 回溯，之前沒調 → 假的 −75% 一日跌幅**（2026-09-24 發現；`universes/full/etf_fixes.csv` 由 `newhigh_backtest.load_series_any` 統一套用；**此前所有台灣回測的 ETF 基準都含這個錯誤**，已重算的見各 `*_BACKTEST.md`） |
| 韓國 | 漲跌停 ±15%（2015-06 前）→ ±30%；KRX KIND 清單下載失敗改用 FinanceDataReader；**SK 海力士（000660.KS）等 8 檔因「還原比例異常」被整檔排除**——做大型股策略要留意 |
| 澳洲 | `^AXJO` Yahoo 沒有（日曆只用 ETF）；微型股多（496 檔抓不到、1.3 萬段殭屍段）→ 用成交額前 N |
| 加拿大 | 只含 TSX 主板（不含創業板 TSXV）；代號的點換成連字號（`BAM.A` → `BAM-A.TO`） |
| 印度 | 個股漲跌幅上限 5／10／20%；Yahoo 的 NIFTYBEES 只到 2009；**NIFTYBEES 2019-12-19、20 兩天價格少一個零**（同月內回復；`etf_fixes.csv` 剔除） |
| 新加坡 | 市場小（571 檔）、價差闊；基準 ES3 在 Yahoo 由 2008 起 |
| 台韓澳加印新 | **沒有免費的最新一日收市第二來源**（台灣上市股除外）；品質只靠結構檢查＋逐筆內部一致性；**候選池 `<m>_pool.txt` 含基準 ETF 與指數代號**（`build_oos_pools.EXTRA`，例 ES3.SI、^STI）——此前這六個市場的回測把它們當股票算進宇宙（每市場 1–2 檔，佔宇宙 0.3–1%，影響極小但存在）；`scripts/tt_all_signal.py` 已剔除，新回測應在 `MarketData` 建宇宙時剔除 `^` 開頭與 `MARKETS[m]['etf']`（2026-09-25 發現） |

## 3. 怎樣用來回測

```python
import newhigh_backtest as nb, vcp_backtest as vb
mk = "in"
pool = [l.strip() for l in open(f"universes/full/{mk}_pool.txt") if l.strip() and not l.startswith("#")]
m = nb.MarketData(mk, pool=pool, loader=nb.load_full(mk), top_n=vb.FULL_TOP_N[mk], cost=vb.FULL_COST[mk])
# m.cal 交易日、m.tickers、m.adj／m.aopen（還原收市／開市矩陣）、m.member（每日成交額前 N 宇宙）、m.etf_ret
# 自訂訊號 ev（股票 × 日 的布林矩陣，t 收市後觸發）→ m.trades_from_events(ev, "x2") → m.evaluate(trades)
rows = nb.load_full(mk)("RELIANCE.NS")    # 單一股票逐日（已套品質排除與殭屍段）
```
- 現成訊號：`vcp.py`（趨勢模板、VCP）、`vcp_minervini.py`（樞紐點＋止損模擬）、`aiba_ppp.features()`（PPP／下半身）、
  `newhigh_backtest.stock_frame()`（3／6／9／12 個月新高、連續天數）
- 多市場樣本外範例：`oos_backtest.py`（漲停鎖死跳過、三市場合併 alpha 檢定）
- 描述性統計（期望值、RRR、累計 vs ETF）：`scripts/expectancy_report.py`
- **研究規矩照 RESEARCH_HANDBOOK.md**：先預先登記再跑；股票策略判決追加到 VERDICTS.md（格式同手冊第二節）

## 4. 已驗證矩陣

哪些策略已在哪些市場測過、結果如何（空格 = 還沒測，歡迎其他分支補）：見 **VERDICTS.md 第 2 節**（判決集中放在那裡）。

## 5. 更新與擴充

- **更新數據**（補最新日線、重傳 Release）：手動觸發 `vcp_fullmarket.yml`（market = hk／jp／us／all，backtest = false）或
  `oos_fullmarket.yml`（market = tw／kr／au／ca／in／sg，或 r1 = 台韓澳、r2 = 加印新）。更新後其他分支重跑 `get_market_data.py`
- **加新市場**（使用者要求不加歐洲）：
  1. `scripts/build_oos_pools.py` 加 `pool_<m>()`（交易所官方清單，附後備來源）與 `EXTRA`（基準 ETF、指數）
  2. `scripts/fetch_full_market.py` 的 `CLOSE` 加收市時間；`scripts/qc_full_market.py` 的 choices（有第二來源就加）
  3. `newhigh_backtest.MARKETS`（ETF、指數、起點、成本、分段日）、`vcp_backtest.FULL_TOP_N`／`FULL_COST`
  4. `.github/workflows/oos_fullmarket.yml` 的 market 選項；`scripts/get_market_data.py` 的 `RELEASE`／`NAME`
  5. 更新本目錄第 2、4 節
