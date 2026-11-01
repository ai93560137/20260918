//+------------------------------------------------------------------+
//| ExportMaxBars.mq5 — 一次過匯出多個品種、多個時框嘅「全部 K 線」      |
//| （IDEAS #175 之後：日線 B 規則要喺更多市場測，加張數）              |
//|                                                                  |
//| 用法：                                                           |
//|  1. MT5 → 工具 → 選項 → 圖表 →「圖表最大 K 線數」揀 Unlimited，     |
//|     然後重開 MT5（唔改嘅話最多得 10 萬根）。                        |
//|  2. 檔案 → 開啟資料夾 → MQL5\Scripts，放呢個檔，喺 MetaEditor 編譯。 |
//|  3. 拖落任何一個圖表，喺輸入參數改品種清單／時框清單，按確定。        |
//|  4. 跑完喺「專家」分頁睇結果；檔案喺 MQL5\Files\MAX\               |
//|     <品種>_<時框>_MAX.csv，格式同之前上載嘅一樣：                   |
//|     Time,Open,High,Low,Close,Volume（伺服器時間）。                 |
//|  5. 將成個 MAX 資料夾壓縮成 zip 上載。                             |
//|                                                                  |
//| 品種清單留空＝匯出「市場報價」入面所有品種。                        |
//| 品種名要同你券商一樣（有後綴就照打，例如 EURUSD.r）。               |
//| 只讀價格，唔落單、唔改任何設定、唔連外網。                          |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSymbols    = "XAUUSD,XAGUSD,EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,EURJPY,GBPJPY,US500,US30,NAS100,GER40,UK100,JPN225,USOIL,BTCUSD"; // 品種（逗號分隔；留空＝市場報價全部）
input string InpTimeframes = "D1,H4,H1,M30,M15,M5,M1";   // 時框（逗號分隔）
input int    InpLoadTries  = 20;                          // 每個品種／時框等歷史下載嘅次數（每次 0.5 秒）
input string InpSubFolder  = "MAX";                       // 輸出子資料夾（喺 MQL5\Files 入面）

ENUM_TIMEFRAMES TfFromString(string s)
{
   StringToUpper(s);
   StringTrimLeft(s); StringTrimRight(s);
   if(s == "M1")  return PERIOD_M1;
   if(s == "M5")  return PERIOD_M5;
   if(s == "M15") return PERIOD_M15;
   if(s == "M30") return PERIOD_M30;
   if(s == "H1")  return PERIOD_H1;
   if(s == "H4")  return PERIOD_H4;
   if(s == "D1")  return PERIOD_D1;
   if(s == "W1")  return PERIOD_W1;
   if(s == "MN1") return PERIOD_MN1;
   return (ENUM_TIMEFRAMES)-1;
}

// 叫 MT5 去伺服器攞齊歷史：重複問 Bars() 直至數目唔再增加
int LoadHistory(string sym, ENUM_TIMEFRAMES tf)
{
   int last = -1, n = 0;
   for(int k = 0; k < InpLoadTries && !IsStopped(); k++)
   {
      datetime first[];
      CopyTime(sym, tf, (int)(TerminalInfoInteger(TERMINAL_MAXBARS) - 1), 1, first);   // 觸發向後下載
      n = Bars(sym, tf);
      if(n > 0 && n == last && SeriesInfoInteger(sym, tf, SERIES_SYNCHRONIZED))
         break;
      last = n;
      Sleep(500);
   }
   return n;
}

bool ExportOne(string sym, string tfName, ENUM_TIMEFRAMES tf)
{
   int total = LoadHistory(sym, tf);
   if(total <= 0)
   {
      PrintFormat("✗ %s %s：冇 K 線（錯誤 %d）", sym, tfName, GetLastError());
      return false;
   }
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   string fn = StringFormat("%s\\%s_%s_MAX.csv", InpSubFolder, sym, tfName);
   int h = FileOpen(fn, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      PrintFormat("✗ %s %s：開唔到檔案 %s（錯誤 %d）", sym, tfName, fn, GetLastError());
      return false;
   }
   FileWriteString(h, "Time,Open,High,Low,Close,Volume\r\n");
   // 分段由最舊讀到最新，避免一次過讀幾百萬根食晒記憶體
   const int CHUNK = 200000;
   int written = 0;
   datetime t_first = 0, t_last = 0;
   for(int start = total - 1; start >= 0 && !IsStopped(); start -= CHUNK)
   {
      int cnt = MathMin(CHUNK, start + 1);
      MqlRates r[];
      ArraySetAsSeries(r, false);
      int got = CopyRates(sym, tf, start - cnt + 1, cnt, r);   // 位置由最新 0 起計
      if(got <= 0)
      {
         PrintFormat("  %s %s：第 %d 段讀唔到（錯誤 %d）", sym, tfName, start, GetLastError());
         continue;
      }
      for(int i = 0; i < got; i++)
      {
         if(written == 0) t_first = r[i].time;
         t_last = r[i].time;
         FileWriteString(h, StringFormat("%s,%s,%s,%s,%s,%I64d\r\n",
                         TimeToString(r[i].time, TIME_DATE | TIME_SECONDS),
                         DoubleToString(r[i].open, digits), DoubleToString(r[i].high, digits),
                         DoubleToString(r[i].low, digits), DoubleToString(r[i].close, digits),
                         r[i].tick_volume));
         written++;
      }
   }
   FileClose(h);
   PrintFormat("✓ %s %s：%d 根（%s → %s 伺服器時間）→ MQL5\\Files\\%s", sym, tfName, written,
               TimeToString(t_first), TimeToString(t_last), fn);
   return written > 0;
}

void OnStart()
{
   string syms[];
   if(StringLen(InpSymbols) == 0)
   {
      int n = SymbolsTotal(true);
      ArrayResize(syms, n);
      for(int i = 0; i < n; i++) syms[i] = SymbolName(i, true);
   }
   else
      StringSplit(InpSymbols, ',', syms);

   string tfs[];
   StringSplit(InpTimeframes, ',', tfs);

   PrintFormat("開始：%d 個品種 × %d 個時框；圖表最大 K 線數＝%d（要 Unlimited 先攞到全部）",
               ArraySize(syms), ArraySize(tfs), (int)TerminalInfoInteger(TERMINAL_MAXBARS));
   PrintFormat("伺服器時間 − UTC 而家＝%d 秒（之後由程式按券商規則轉 UTC）", (int)(TimeTradeServer() - TimeGMT()));

   int ok = 0, bad = 0;
   for(int s = 0; s < ArraySize(syms) && !IsStopped(); s++)
   {
      string sym = syms[s];
      StringTrimLeft(sym); StringTrimRight(sym);
      if(StringLen(sym) == 0) continue;
      if(!SymbolSelect(sym, true))
      {
         PrintFormat("✗ %s：券商冇呢個品種（檢查名同後綴）", sym);
         bad++;
         continue;
      }
      for(int k = 0; k < ArraySize(tfs) && !IsStopped(); k++)
      {
         string tfName = tfs[k];
         StringTrimLeft(tfName); StringTrimRight(tfName); StringToUpper(tfName);
         ENUM_TIMEFRAMES tf = TfFromString(tfName);
         if((int)tf < 0) { PrintFormat("✗ 唔識呢個時框：%s", tfName); continue; }
         if(ExportOne(sym, tfName, tf)) ok++; else bad++;
      }
   }
   PrintFormat("完成：成功 %d 個檔、失敗 %d 個。檔案喺 MQL5\\Files\\%s\\，壓縮成 zip 上載就得。", ok, bad, InpSubFolder);
}
