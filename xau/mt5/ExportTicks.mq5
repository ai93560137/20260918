//+------------------------------------------------------------------+
//| ExportTicks.mq5 — 天覆陣：匯出 tick 級數據（每秒彙總）做 DAN 微時機研究（提案 §31 (b)，使用者 10-25「先做 Tick 級」）|
//| 用法：MetaEditor 開新 Script，貼入編譯；MT5 打開 XAUUSD 圖表，由「導航 → 腳本」拖落圖表。                      |
//| 輸出：MQL5/Files/<商品>_T1s_<YYYYMMDD>.csv，一日一個檔，每行一秒（只寫有 tick 嘅秒）：                            |
//|   sec（伺服器時間 epoch 秒）、bid_open、bid_high、bid_low、bid_close、ask_close、ticks（該秒 tick 數）、          |
//|   spread_avg（該秒平均 ask−bid，價格單位）、server_minus_utc_sec                                                   |
//| 只讀數據、唔落單、唔改任何設定。Broker 嘅 tick 歷史深度有限，實際攞到幾多日由日誌講。                                 |
//+------------------------------------------------------------------+
#property script_show_inputs
input int InpDays = 30;   // 向前匯出幾多日（broker 冇 tick 嘅日子會跳過）

void OnStart()
{
   long     offset   = (long)(TimeTradeServer() - TimeGMT());
   datetime now      = TimeCurrent();
   datetime day0     = (datetime)(((long)now / 86400) * 86400);
   int      files    = 0;
   long     total    = 0;
   datetime earliest = 0;
   for(int d = InpDays; d >= 0; d--)
   {
      datetime ds = day0 - (datetime)d * 86400;
      datetime de = ds + 86400;
      if(de > now) de = now;
      MqlTick ticks[];
      int n = CopyTicksRange(_Symbol, ticks, COPY_TICKS_INFO, (long)ds * 1000, (long)de * 1000);
      if(n <= 0)
         continue;
      string ymd = TimeToString(ds, TIME_DATE);     // yyyy.mm.dd
      StringReplace(ymd, ".", "");
      string name = StringFormat("%s_T1s_%s.csv", _Symbol, ymd);
      int h = FileOpen(name, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(h == INVALID_HANDLE)
      {
         PrintFormat("❌ 開唔到檔案 %s err=%d", name, GetLastError());
         return;
      }
      FileWrite(h, "sec", "bid_open", "bid_high", "bid_low", "bid_close", "ask_close", "ticks", "spread_avg", "server_minus_utc_sec");
      datetime cur = 0;
      double bo = 0, bh = 0, bl = 0, bc = 0, ac = 0, spr = 0;
      int cnt = 0;
      for(int i = 0; i < n; i++)
      {
         if(ticks[i].bid <= 0) continue;
         datetime s = ticks[i].time;
         if(s != cur)
         {
            if(cnt > 0)
               FileWrite(h, (long)cur, DoubleToString(bo, _Digits), DoubleToString(bh, _Digits), DoubleToString(bl, _Digits),
                         DoubleToString(bc, _Digits), DoubleToString(ac, _Digits), cnt, DoubleToString(spr / cnt, _Digits + 1), offset);
            cur = s; bo = bh = bl = bc = ticks[i].bid; ac = ticks[i].ask; spr = 0; cnt = 0;
         }
         bh = MathMax(bh, ticks[i].bid); bl = MathMin(bl, ticks[i].bid); bc = ticks[i].bid;
         if(ticks[i].ask > 0) { ac = ticks[i].ask; spr += ticks[i].ask - ticks[i].bid; }
         cnt++;
      }
      if(cnt > 0)
         FileWrite(h, (long)cur, DoubleToString(bo, _Digits), DoubleToString(bh, _Digits), DoubleToString(bl, _Digits),
                   DoubleToString(bc, _Digits), DoubleToString(ac, _Digits), cnt, DoubleToString(spr / cnt, _Digits + 1), offset);
      FileClose(h);
      files++; total += n;
      if(earliest == 0) earliest = ticks[0].time;
      PrintFormat("📄 %s：%d ticks", name, n);
   }
   if(files == 0)
   {
      PrintFormat("❌ 攞唔到任何 tick（err=%d）。試吓喺 MT5「工具 → 選項 → 圖表」加大「圖表最大 K 線數」，或者先開 M1 圖表向左拉歷史。", GetLastError());
      return;
   }
   PrintFormat("✅ 已匯出 %d 日、合共 %d ticks（最早 %s 伺服器時間）到 MQL5/Files/%s_T1s_*.csv；時差 %d 秒",
               files, total, TimeToString(earliest), _Symbol, offset);
}
