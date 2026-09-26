# 金絲雀燈色表(canary/)

由六隻鳥日線產出**每日燈色 CSV**,規則照 `CANARY_PLAYBOOK.md` §2 現役編制,固定閾值、不調參。
這個目錄**只提供訊號**,不接任何策略;各策略回測自己讀 `canary_daily.csv`。

| 檔案 | 內容 |
|---|---|
| `canary_daily.csv` | 燈色表,2006-07-17 起,每個美股交易日一列 |
| `build_canary_table.py` | 產生器,純 Python 標準庫,不需 pandas |
| `data_external/*_daily.csv` | 六隻鳥日線快照(VIX9D、VIX、VIX3M、VVIX、MOVE、AXVI),來源見下 |

## 欄位

| 欄 | 意義 |
|---|---|
| `date` | 收盤日(美股交易日) |
| `vix9d` `vix` `vix3m` `vvix` `move` `axvi` | 各鳥當日收盤 |
| `slope_9d` | VIX9D − VIX(週/月斜率) |
| `slope_3m` | VIX − VIX3M(月/季斜率) |
| `vvix_p90` `move_p90` `axvi_p90` | 各自滾動 252 日 90 分位(窗口含當日) |
| `red` | 🔴 `slope_9d > 0` |
| `deep_red` | 🟣 `slope_3m > 0` |
| `flat` | ⚪ `−0.5 < slope_9d ≤ 0` |
| `yellow_vvix` `yellow_move` `yellow_axvi` | 🟡 各鳥是否 > 自身 p90 |
| `yellow` | 三隻黃鳥任一亮 |
| `light` | 斜率燈單欄:`深紅` > `紅` > `走平` > `綠`(互斥;黃燈另看 `yellow`) |

布林欄位:`1` 亮、`0` 不亮、空白 = 該日資料不足(例如 2011 年前無 VIX9D、各鳥前 252 日無分位)。

## 使用紀律(§7,不可省)

1. **lag=1**:`date` = T 的燈色,只能用於 T **之後**的交易日。進場日看前一日的燈,不看當日。
2. **不調參**:閾值(>0、p90、252 日)寫死在腳本裡。要換閾值 = 新研究,不是改這張表。
3. **先登記再用**:取用前依 `CANARY_PLAYBOOK.md` §8 在登記冊寫下響應規則(紅/深紅/黃各一句)。
4. **預測波動不預測方向**:燈色決定「要不要進、進多大」,不決定多空。
5. AXVI 是亞洲時段指數,日期上會比美鳥慢一天;對港股當日有效、對美股照 lag=1。
6. **紅與深紅的分工**(手冊 §3 註,2026-09-26 增補):Lim(2026)證實含 VIX9D 的量度對未來 5–10 日實現波動的預測力
   勝過 VIX−VIX3M,紅燈學理地位高於手冊表格所示;但深紅的王牌地位來自「災難月事前預警」,目標不同、不衝突。
   看短期對沖負載看紅,看災難風險看深紅。產生器在最新燈色為紅或深紅時會自動印出此註。

## 更新

```bash
python3 canary/build_canary_table.py --refresh   # 從雲垂陣分支拉最新六隻鳥,重產燈色表
python3 canary/build_canary_table.py             # 只用現有快照重產
```

來源:分支 `claude/dazzling-curie-f3xzb8` 的 `tradingview/data_external/*_daily.csv`,
每日由該分支的 GitHub Actions 更新。本目錄的快照是取用當時的版本,`--refresh` 才會跟上。

## 口徑驗證

滾動分位的純標準庫實作已與 `pandas.Series.rolling(252).quantile(0.9)` 逐點比對,
三隻黃鳥合計 14,842 個點最大差 0;紅、深紅、黃(VVIX)旗標與 pandas 獨立重算逐日一致。
