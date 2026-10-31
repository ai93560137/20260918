# XAUUSD 回測數據（GCS bucket `zhuge-risk-manager-bucket`）

| 數據 | GCS 位置 | 範圍 | 備註 |
|---|---|---|---|
| **券商 MT5 原檔**（UltimaMarkets，M1／M5／M15／M30／H1／H4／D1） | `xau/data/mt5/XAUUSD_MAX_2026-10-30.zip` | 2022-08-03→2026-10-30 | 使用者 10-31 上載；時間係伺服器時間（UTC+2 冬／UTC+3 美國夏令時） |
| **券商 MT5 M1（已轉 UTC，逐日）** | `xau/sig/mt5m1/<YYYY-MM-DD>.json` | 同上，1,299 日、147.7 萬根 | `[[utc, open, high, low, close, tick_volume], …]`；`research/strategy_search/import_mt5.py` 匯入；同 Dukascopy 重疊日收市中位差 0.15–0.24 美元 |
| 經紀 M1（EA 心跳） | `xau/sig/bars/<日>.jsonl` | 10-27 起 | 實時，每次心跳 400 根 |
| Dukascopy 現貨 M1 | `xau/sig/duka/<日>.json` | 2026-07-24 起（另有 2025-01 幾日） | `[[t,o,h,l,c], …]`；`.github/workflows/xau_alt_m1.yml`（src=duka）補 |
| PAXG（Binance）M1 | `xau/sig/alt/paxg/<日>.json` | 2026-07-24→10-30 | 24／7，分析時剔週末 |
| GC=F（yfinance）M1 | `xau/sig/alt/gcf/<日>.json` | 10-23→10-30 | 只得 7 日 |

新嘅 MT5 匯出：用 `xau/mt5/ExportM1Years.mq5`（按年 CSV，已轉 UTC）或者再上載 *_MAX.zip 跑 `import_mt5.py`。
