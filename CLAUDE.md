# 專案說明（CLAUDE.md）

交易策略倉庫：v12 電閘系統（main.py）、回測器（backtest.py / zgl_backtest.py /
donchian_backtest.py）、TradingView 策略（tradingview/）。
歷史數據在 data/（.csv.gz，格式見 data/README.md）。
全市場股票日線（9 個市場：港日美台韓澳加印新，不進 git、存 GitHub Release）見 stock_research/MARKET_DATA_CATALOG.md，
一鍵下載 `python3 scripts/get_market_data.py`。
股票研究（新高／VCP／Minervini／相場師朗／9 國樣本外）集中在 `stock_research/`：策略／數據／執行見 stock_research/README.md，
判決見 stock_research/VERDICTS.md，接手總結見 stock_research/STOCK_RESEARCH_HANDOFF.md。

**進行任何策略研究/回測前**：先讀 RESEARCH_HANDBOOK.md（方法論鐵律、
已判決結論庫、股票研究守則）——已判決的不重測，鐵律不繞過。

**當用戶上傳富途牛牛截圖或提到「對帳」時**：閱讀 journal/RULES.md 並嚴格
按該文件執行每日核對與記錄（journal/log.csv），核對後 commit + push。
