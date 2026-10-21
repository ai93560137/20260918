//+------------------------------------------------------------------+
//| ExportM1.mq5 — 天覆陣訊號書：匯出 M1 K 線做頻道歷史成績（使用者 10-21：讀返 90 日、用 MT5 匯出）|
//| 用法：MetaEditor 開新 Script，貼入編譯；MT5 打開 XAUUSD 圖表，由「導航 → 腳本」拖落圖表。          |
//| 輸出：MQL5/Files/<商品>_M1_<日數>d.csv（time 係 MT5 伺服器時間 epoch 秒，UltimaMarkets 夏令 UTC+3）|
//| 只讀數據、唔落單、唔改任何設定。                                                                    |
//+------------------------------------------------------------------+
#property script_show_inputs
input int InpDays = 95;   // 匯出幾多日（90 日訊號＋前後緩衝）

void OnStart()
{
   datetime to   = TimeCurrent();
   datetime from = to - (datetime)InpDays * 86400;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int n = CopyRates(_Symbol, PERIOD_M1, from, to, rates);
   if(n <= 0)
   {
      PrintFormat("❌ CopyRates 失敗 err=%d（試吓先喺圖表揀 M1、向左拉多啲歷史，再跑一次）", GetLastError());
      return;
   }
   string name = StringFormat("%s_M1_%dd.csv", _Symbol, InpDays);
   int h = FileOpen(name, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
   {
      PrintFormat("❌ 開唔到檔案 %s err=%d", name, GetLastError());
      return;
   }
   FileWrite(h, "time", "open", "high", "low", "close", "server_minus_utc_sec");
   long offset = (long)(TimeTradeServer() - TimeGMT());
   for(int i = 0; i < n; i++)
      FileWrite(h, (long)rates[i].time, DoubleToString(rates[i].open, _Digits), DoubleToString(rates[i].high, _Digits),
                DoubleToString(rates[i].low, _Digits), DoubleToString(rates[i].close, _Digits), offset);
   FileClose(h);
   PrintFormat("✅ 已匯出 %d 根 M1（%s → %s 伺服器時間）到 MQL5/Files/%s；時差 %d 秒",
               n, TimeToString(rates[0].time), TimeToString(rates[n - 1].time), name, offset);
}
