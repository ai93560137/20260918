# 每日由上而下股票分析（analysis/）

由 `scripts/daily_topdown.py` 產生，`.github/workflows/daily_topdown.yml` 每個交易日早上
（美股收市數據更新後，約 08:00–09:30 香港時間）自動跑並發 Telegram。

| 檔案 | 內容 |
|---|---|
| `DAILY_TOPDOWN.md` | 最新一份完整報告 |
| `archive/<日期>.md` | 每日存檔 |
| `topdown_log.csv` | 每日焦點國家、三地前 3 板塊、個股清單——**樣本外紀錄**，累積數月後用來誠實評估這套篩選 |
| `tg_topdown.txt` | Telegram 摘要 |

三層流程：

1. **國家**：港股 2800.HK、美股 SPY、日股 EWJ（美元計）——動能分數 = 3/6/12 個月報酬平均；
   只在收市高於 200 日線的市場中選焦點（全部在線下 → 標「全面弱勢」）
2. **板塊**：`sector/<指數>/group_index.csv`（`scripts/sector_rotation.py`）的 point-in-time 等權行業指數，
   按 6 個月超額排名取前 3（沿用 SECTOR_ROTATION.md 預先登記的行業動量規格）
3. **個股**：前 3 板塊的現任成分股按 12-1／6／3 個月報酬的平均百分位排序，每板塊前 5，
   標示趨勢、過熱、近月急跌、股息率

**這是描述性篩選，不是回測過的交易訊號**：研究結論見 RESEARCH_HANDBOOK.md——只有港股行業動量
壓線過了預先登記門檻（🔍），美股不確定、日股 ☠️，港股個股動量單獨使用 ☠️。規則寫死在腳本的
`RULES`，不按每天結果調整。
