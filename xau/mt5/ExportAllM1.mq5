//+------------------------------------------------------------------+
//| ExportAllM1.mq5 — 一次過匯出多個品種、全部年份嘅券商 M1 歷史          |
//| （11-10 使用者「MT5 一次過匯出所有」；取代逐個品種跑 ExportM1Years）    |
//| 用法：MT5 → 檔案 → 開啟資料夾 → MQL5\Scripts 放呢個檔 → MetaEditor    |
//|       編譯 → 拖落任何一張圖表。                                      |
//| 輸出：MQL5\Files\export\<品種>_M1_<年>.csv                          |
//|       （utc 秒,open,high,low,close,tick_volume,spread），每品種每年一個檔 |
//|       同 MQL5\Files\export\SUMMARY.csv（每個檔幾多根、由幾時到幾時）   |
//| InpSymbols 留空＝「市場報價」入面全部品種（檔案會好大）。              |
//| 只讀價格，唔落單、唔連網。                                          |
//+------------------------------------------------------------------+
#property script_show_inputs
input string InpSymbols  = "XAUUSD,XAGUSD";   // 逗號分隔；留空＝市場報價全部品種
input int    InpFromYear = 2010;
input int    InpToYear   = 2026;
input int    InpRetries  = 10;                 // 歷史未下載好（錯誤 4401 等）時重試次數，每次等 3 秒

int CopyWithRetry(const string sym, datetime t0, datetime t1, MqlRates &r[])
{
   for(int k = 0; k < InpRetries; k++)
   {
      ResetLastError();
      int n = CopyRates(sym, PERIOD_M1, t0, t1, r);
      if(n > 0) return n;
      if(IsStopped()) return -1;
      Sleep(3000);                               // 等 MT5 由伺服器下載歷史
   }
   return -1;
}

void OnStart()
{
   long off = (long)(TimeTradeServer() - TimeGMT());   // 伺服器時間 − UTC（夏令切換有 1 小時誤差，之後用 Dukascopy 對齊）
   PrintFormat("伺服器時間 − UTC = %d 秒", off);

   string syms[];
   if(StringLen(InpSymbols) == 0)
   {
      int total = SymbolsTotal(true);
      ArrayResize(syms, total);
      for(int i = 0; i < total; i++) syms[i] = SymbolName(i, true);
   }
   else
      StringSplit(InpSymbols, ',', syms);

   FolderCreate("export");
   int hs = FileOpen("export\\SUMMARY.csv", FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(hs != INVALID_HANDLE) FileWrite(hs, "symbol", "year", "bars", "first_server_time", "last_server_time", "server_minus_utc_sec");

   for(int s = 0; s < ArraySize(syms); s++)
   {
      string sym = syms[s];
      StringTrimLeft(sym); StringTrimRight(sym);
      if(sym == "") continue;
      if(!SymbolSelect(sym, true)) { PrintFormat("%s：搵唔到呢個品種（券商可能用第二個名，例如 XAGUSD. 或 SILVER）", sym); continue; }
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      for(int y = InpFromYear; y <= InpToYear; y++)
      {
         if(IsStopped()) { Print("使用者停止"); if(hs != INVALID_HANDLE) FileClose(hs); return; }
         MqlDateTime a, b; ZeroMemory(a); ZeroMemory(b);
         a.year = y; a.mon = 1; a.day = 1; b.year = y + 1; b.mon = 1; b.day = 1;
         MqlRates r[]; ArraySetAsSeries(r, false);
         int n = CopyWithRetry(sym, StructToTime(a), StructToTime(b), r);
         if(n <= 0)
         {
            PrintFormat("%s %d 年：攞唔到 M1（錯誤 %d）。券商可能冇咁早嘅歷史；或者工具→選項→圖表「最大K線數」揀 Unlimited 再試", sym, y, GetLastError());
            continue;
         }
         string fn = StringFormat("export\\%s_M1_%d.csv", sym, y);
         int h = FileOpen(fn, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
         if(h == INVALID_HANDLE) { PrintFormat("開唔到 %s", fn); continue; }
         FileWrite(h, "utc", "open", "high", "low", "close", "tick_volume", "spread");
         for(int i = 0; i < n; i++)
            FileWrite(h, (long)r[i].time - off, DoubleToString(r[i].open, digits), DoubleToString(r[i].high, digits),
                      DoubleToString(r[i].low, digits), DoubleToString(r[i].close, digits), r[i].tick_volume, r[i].spread);
         FileClose(h);
         if(hs != INVALID_HANDLE) FileWrite(hs, sym, y, n, TimeToString(r[0].time), TimeToString(r[n - 1].time), off);
         PrintFormat("%s %d 年：%d 根 → MQL5\\Files\\%s", sym, y, n, fn);
      }
   }
   if(hs != INVALID_HANDLE) FileClose(hs);
   Print("完成：請將 MQL5\\Files\\export 成個資料夾壓縮成 zip 上載");
}
