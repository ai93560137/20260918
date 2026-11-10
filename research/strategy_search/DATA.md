# XAUUSD 回測數據（GCS bucket `zhuge-risk-manager-bucket`）

| 數據 | GCS 位置 | 範圍 | 備註 |
|---|---|---|---|
| **券商 MT5 原檔**（UltimaMarkets，M1／M5／M15／M30／H1／H4／D1） | `xau/data/mt5/XAUUSD_MAX_2026-10-30.zip` | 2022-08-03→2026-10-30 | 使用者 10-31 上載；時間係伺服器時間（UTC+2 冬／UTC+3 美國夏令時） |
| **券商 MT5 M1（已轉 UTC，逐日）** | `xau/sig/mt5m1/<YYYY-MM-DD>.json` | 同上，1,299 日、147.7 萬根；11-10 由新版 MAX.zip 補 11-01→11-09（同 EA 心跳逐分鐘 100% 相同，只補心跳缺口） | `[[utc, open, high, low, close, tick_volume], …]`；`research/strategy_search/import_mt5.py` 匯入；同 Dukascopy 重疊日收市中位差 0.15–0.24 美元 |
| **券商 MT5 白銀原檔**（XAGUSD，M1／M5／M15／M30／H1／H4／D1） | `xau/data/mt5/XAGUSD_MAX_2026-10-30.zip` | 2022-08-03→2026-10-30 | 使用者 11-01 上載；伺服器時間（UTC+2 冬／UTC+3 美國夏令時）；IDEAS #168 對照 |
| Dukascopy 白銀 H1 | `xau/sig/duka_h1_xagusd/<YYYY-MM>.json` | 2005-01→2026-10 | `xau_duka_h1.yml` sym=XAGUSD |
| **券商 MT5 多品種原檔**（16 個：AUD／EUR／GBP／NZD／USD 外匯、日圓盤、NAS100、GER40、UK100、CL-OIL、BTCUSD、XAU、XAG；M1–D1） | `xau/data/mt5/max/MAX.zip` | 2022-08→2026-10（BTC 2020-08 起） | 使用者 11-01 用 `ExportMaxBars.mq5` 匯出自己上載；伺服器時間 |
| **券商 MT5 多品種 M1（已轉 UTC，研究快取）** | `xau/sig/cache/mt5x/<品種>_m1_<年>.npz`（2026 未完整年＝`_2026p`） | 2022-08→2026-11-10 17:0x UTC（CL-OIL 到 10-30；BTC 2020-08 起、冇 2021） | 11-10 總指揮轉交新版 `max/MAX.zip`（11-01＋11-10 合併）；`research/student_offline/import_mt5_max.py` 匯入；t／o／h／l／c，`data_cache.get('mt5x/XAGUSD_m1_2024.npz')` 讀。時區＝UTC+2 冬／+3 美國夏令（逐月同 Dukascopy H1 核實；SUMMARY 寫嘅 7200 秒只係匯出嗰刻）。**`xau/data/mt5/export.zip` 嘅 utc 欄用固定 7200，夏令月差 1 小時，唔好用**。報告 `research/student_offline/MT5_MAX_IMPORT.md` |
| 經紀 M1（EA 心跳） | `xau/sig/bars/<日>.jsonl` | 10-27 起 | 實時，每次心跳 400 根 |
| Dukascopy 現貨 M1 | `xau/sig/duka/<日>.json` | 2026-07-24 起（另有 2025-01 幾日） | `[[t,o,h,l,c], …]`；`.github/workflows/xau_alt_m1.yml`（src=duka）補 |
| PAXG（Binance）M1 | `xau/sig/alt/paxg/<日>.json` | 2026-07-24→10-30 | 24／7，分析時剔週末 |
| GC=F（yfinance）M1 | `xau/sig/alt/gcf/<日>.json` | 10-23→10-30 | 只得 7 日 |

新嘅 MT5 匯出：**多品種一次過**用 `xau/mt5/ExportMaxBars.mq5`（品種清單＋時框清單，輸出 `MQL5\Files\MAX\<品種>_<時框>_MAX.csv`，格式同 *_MAX.csv 一樣；先將「圖表最大 K 線數」改 Unlimited）；單品種按年用 `xau/mt5/ExportM1Years.mq5`（按年 CSV，已轉 UTC）或者再上載 *_MAX.zip 跑 `import_mt5.py`。
