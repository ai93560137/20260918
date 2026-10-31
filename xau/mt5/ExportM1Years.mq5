//+------------------------------------------------------------------+
//| ExportM1Years.mq5 — 按年匯出券商 M1 歷史（IDEAS #161 用券商數據核對）      |
//| 用法：MT5 → 檔案 → 開啟資料夾 → MQL5\Scripts 放呢個檔 → 編譯 →    |
//|       拖落 XAUUSD 圖表。輸出 MQL5\Files\XAUUSD_M1_<年>.csv        |
//|       （UTC 秒,open,high,low,close,tick_volume,spread），每年一個檔 |
//| 只讀價格，唔落單、唔連網。                                        |
//+------------------------------------------------------------------+
#property script_show_inputs
input string InpSymbol   = "XAUUSD";
input int    InpFromYear = 2023;
input int    InpToYear   = 2026;

void OnStart()
{
   // 伺服器時間 → UTC：用目前伺服器時間同 GMT 嘅差（券商夏令時切換會有 1 小時誤差，之後用 Dukascopy 對齊校正）
   long off = (long)(TimeTradeServer() - TimeGMT());
   PrintFormat("伺服器時間 − UTC = %d 秒", off);
   for(int y = InpFromYear; y <= InpToYear; y++)
   {
      MqlDateTime a, b;
      ZeroMemory(a); ZeroMemory(b);
      a.year = y; a.mon = 1; a.day = 1;
      b.year = y + 1; b.mon = 1; b.day = 1;
      datetime t0 = StructToTime(a), t1 = StructToTime(b);
      MqlRates r[];
      ArraySetAsSeries(r, false);
      int n = CopyRates(InpSymbol, PERIOD_M1, t0, t1, r);
      if(n <= 0)
      {
         PrintFormat("%d 年：攞唔到 M1（%d，錯誤 %d）。工具→選項→圖表「最大K線數」揀 Unlimited，再開 M1 圖表捲返去下載歷史", y, n, GetLastError());
         continue;
      }
      string fn = StringFormat("%s_M1_%d.csv", InpSymbol, y);
      int h = FileOpen(fn, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(h == INVALID_HANDLE) { PrintFormat("開唔到 %s", fn); continue; }
      FileWrite(h, "utc", "open", "high", "low", "close", "tick_volume", "spread");
      for(int i = 0; i < n; i++)
         FileWrite(h, (long)r[i].time - off, DoubleToString(r[i].open, _Digits), DoubleToString(r[i].high, _Digits),
                   DoubleToString(r[i].low, _Digits), DoubleToString(r[i].close, _Digits), r[i].tick_volume, r[i].spread);
      FileClose(h);
      PrintFormat("%d 年：%d 根 → MQL5\\Files\\%s（由 %s 到 %s 伺服器時間）", y, n, fn,
                  TimeToString(r[0].time), TimeToString(r[n - 1].time));
   }
}
