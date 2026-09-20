# 專案說明（CLAUDE.md）

交易策略倉庫：v12 電閘系統（main.py）、回測器（backtest.py / zgl_backtest.py /
donchian_backtest.py）、TradingView 策略（tradingview/）。
歷史數據在 data/（.csv.gz，格式見 data/README.md）。

**當用戶上傳富途牛牛截圖或提到「對帳」時**：閱讀 journal/RULES.md 並嚴格
按該文件執行每日核對與記錄（journal/log.csv），核對後 commit + push。
