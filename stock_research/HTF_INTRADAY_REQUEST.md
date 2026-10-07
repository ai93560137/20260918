# HTF 盤中執行研究：給雲垂的 IBKR 5 分 K 抓取需求（HTF_INTRADAY_REQUEST.md）

背景：HTF（Qullamaggie 高漲旗型）日線版四市場判死（HTF_BACKTEST.md 第二部分），但歸因顯示港、台的
形態比「只是動能股」好（隨機對照第 92–98 百分位），而**入場日停損那 17–21% 的交易幾乎全是「開市低於樞紐、盤中在樞紐價成交」**，
每筆 −5%——日線分不出當日低點在成交前還是後，這批只有盤中數據能判。使用者 2026-10-07 決定往盤中挖，判決門檻稍後再定（探索性）。

## 要抓什麼

輸入：`analysis/htf/ibkr_intraday_request.csv`（欄位 `market,ticker,signal_date,entry_date`；港 374、台 624、美 2,855 筆）。

每一列抓 **entry_date 當天**（只需這一天；之後的日子日線高低價已夠用）的 **5 分 K、只含正常交易時段（useRTH=True）、TRADES**：

```python
ib.reqHistoricalData(contract, endDateTime=f"{entry_date} 23:59:59", durationStr="1 D",
                     barSizeSetting="5 mins", whatToShow="TRADES", useRTH=True)
```

代號轉 IB 合約照 `scripts/ib_stock_verify.py` 的 `to_ib()`（港：去前導 0、SEHK／HKD；美：`-`→空格、SMART／USD；
台：`rsplit('.')[0]`、TWSE／TWD——**雲垂腳本註明 IB 可能沒有台股，先 probe 幾檔；若全部失敗，台灣這段放棄，只做港美**）。

輸出：`data_stock_ibkr/htf_5m/<market>_<ticker>_<entry_date>.csv`（欄位 `time,open,high,low,close,volume`，交易所當地時間）
與 `_status.txt`（每列 ok／失敗原因）。可續抓：已有檔的跳過。節流照 `--pace 2.5`（3,853 列約 3 小時）。只讀，不下單。

優先順序：**港 → 美 → 台**（港最可能有結果；美是「問題在選股不在執行」的對照；台看 IB 有沒有）。

## 數據回來後會做什麼（探索性，不事先定門檻）

同一批日線訊號，換成盤中執行：
1. 入場：開盤區間（前 5 分／前 60 分）高點被突破且高於樞紐點才進場，成交價 = 突破那根 5 分 K 的收市；開盤已高於樞紐 5% 不買（同日線版）。
2. 停損：成交後的**真實當日低點**（Qullamaggie 的 LOD）；當日盤中跌破就出場。
3. 其餘（第 3 日減半、保本、10MA 收市出場）同日線版。
4. 比較三個數字：日線版 vs 盤中版的每筆淨報酬、入場日停損比例、alpha t；以及盤中執行有沒有拉大「HTF 訊號 vs 隨機動能股」的差距
   （隨機對照的股票日也要抓同一天的 5 分 K，清單另附）。

## 給雲垂的指令（請使用者貼過去）

```
HTF 盤中研究：請抓 analysis/htf/ibkr_intraday_request.csv 每列 entry_date 當天的 5 分 K（RTH、TRADES），
規格見 stock_research/HTF_INTRADAY_REQUEST.md（分支 claude/htf-qullamaggie-research）。
cd ~/20260918 && git fetch origin claude/htf-qullamaggie-research
git checkout origin/claude/htf-qullamaggie-research -- analysis/htf/ibkr_intraday_request.csv stock_research/HTF_INTRADAY_REQUEST.md
先 probe 港美台各 2 檔確認合約與權限；OK 後按 港 → 美 → 台 順序跑；輸出 data_stock_ibkr/htf_5m/，跑完 commit + push。
```
