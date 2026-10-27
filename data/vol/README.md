# 波動率與利率日線（IBKR）

由 `scripts/ibkr_vol_export.py` 於 2026-10-27 22:30 產生。資料來自 IBKR，僅供個人研究使用。

| 檔案 | 內容 | IB whatToShow | 起 | 迄 | 筆數 |
|---|---|---|---|---|---|
| `vix.csv` | VIX | TRADES | 2005-10-03 | 2026-10-27 | 5283 |
| `vix3m.csv` | VIX 3 個月 | TRADES | 2009-08-12 | 2026-10-27 | 4328 |
| `tnx.csv` | 10 年期殖利率 ×10 | TRADES | 2009-08-12 | 2026-10-27 | 4326 |
| `tlt.csv` | TLT 還原價 | ADJUSTED_LAST | 2016-02-03 | 2026-10-27 | 2699 |
| `tlt_iv.csv` | TLT 30 天隱含波動率 | OPTION_IMPLIED_VOLATILITY | 2006-01-06 | 2026-10-27 | 3545 |
| `tlt_hv.csv` | TLT 30 天歷史波動率 | HISTORICAL_VOLATILITY | 2005-02-15 | 2026-10-26 | 5452 |
| `ief_iv.csv` | IEF 30 天隱含波動率 | OPTION_IMPLIED_VOLATILITY | 2006-01-09 | 2026-10-27 | 3545 |
| `qqq.csv` | QQQ 還原價（NQ/MNQ 的長歷史替代） | ADJUSTED_LAST | 1999-03-10 | 2026-10-27 | 6953 |
| `spy.csv` | SPY 還原價 | ADJUSTED_LAST | 1996-10-07 | 2026-10-27 | 7560 |
| `gld.csv` | GLD（黃金的長歷史替代） | ADJUSTED_LAST | 2004-11-18 | 2026-10-27 | 5517 |
| `zn.csv` | 10 年公債期貨 | TRADES | 2025-04-04 | 2026-10-27 | 393 |
| `zb.csv` | 30 年公債期貨 | TRADES | 2025-04-04 | 2026-10-27 | 393 |
| `nq.csv` | 那斯達克 100 期貨 | TRADES | 2024-03-18 | 2026-10-27 | 654 |

這次失敗：move（多半是缺該市場的行情訂閱）。
