//+------------------------------------------------------------------+
//|                                RiskManager_HKD_Zhuge_Final_V22.mq5 |
//|                                  Copyright 2026, AI Trading Lab   |
//|                                            https://mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AI Trading Lab"
#property link      "https://mql5.com"
#property version   "0920 v23" // 出場改為定時、風控線收緊、只做多
#property description "V23：拆掉結構性負期望的 TP/SL，改定時出場；回撤線 90%→20%；只做多"
//
// =====================================================================
// V22 → V23 改了什麼，以及為什麼
// ---------------------------------------------------------------------
// ① 出場：拆掉固定 TP，改為【定時出場】
//    V22 的出場是 InpTakeProfitHKD = 500（≈US$64/oz）配 InpDefaultSLPoints
//    = 8000（US$80/oz）。用 XAUUSD M1 全歷史逐根模擬先碰到哪一邊：
//
//      TP US$64 / SL US$80   1,136 筆   勝率 51.1%   −HK$20,854   平均持倉 658 分鐘
//      逐年 2022 +1,131  2023 +106  2024 +8,289  2025 −24,254  2026 −6,125
//
//    原因是幾何的：80 ÷ (64+80) = 55.6% 才打平，而黃金在這兩條線之間就是
//    隨機漫步，再扣點差必為負。這不是風控，是一台結構性負期望值的機器。
//    而且它把平均持倉拉到 11 小時 —— 規則的優勢活在 2.5 小時內。
//
//    → V23：TP 預設關閉（InpTakeProfitHKD = 0），改用 InpHoldMinutes = 150
//      （10 根 M15）定時全平。8000 點的 SL 保留，但它的角色是【災難停損】，
//      不是出場條件 —— 正常情況下永遠不會碰到它。
//
// ② 風控線：InpMaxTotalDrawdown 90% → 20%
//    整套空城計的曝險公式建立在「可承受回撤 20%」上。V22 要等淨值跌掉 90%
//    才強平鎖戶 —— HK$20,000 的戶口，那條線在 HK$2,000。上層所有紀律設計
//    在那之前早就失效了。
//    InpMaxDailyLossHKD 10000 → 1200（本金的 6%）。GCP 電閘在 −3% 就停止
//    放行新單，EA 在 −6% 才強平，兩層分開。
//
// ③ 只做多：InpLongOnly = true
//    TradingView 全期成交明細 2018-04 → 2026-09 共 1,464 筆：
//      只做多 793 筆 每筆 +HK$6.27 t = +2.14
//      只做空 671 筆 每筆 −HK$0.84 t = −0.25   ← 八年半期望值為零
//    空單唯一的作用是付點差。
//
// ④ 電閘語意改變（配合 GCP main.py 同日改版）
//    雲端的 200/403 不再是「三級共振說現在是趨勢」，而是「五道風控關卡
//    全過」：市場時段 / 波動水位 / 空城計曝險上限 / 單日虧損 / 訓練節奏。
//    三級共振已被量度為沒有優勢（延後一分鐘進場 t 由 +5.28 掉到 −2.18），
//    而本 EA 每 60 秒才輪詢一次，本來就接不住那種訊號。
//
// ⑤ ⚠️ 管轄範圍（V23 新增，這是最容易出事的一條）
//    V22 的 CloseAllPositions / CheckAndSetSLTP 完全沒有過濾 —— 直接掃
//    PositionsTotal()，帳戶上每一張單都會被動到。若這個戶口同時有你的
//    手動單或直覺倉，EA 會幫它們掛 8000 點止損、並在 150 分鐘時平掉。
//    你的手實測年化 11.67%，那不是 EA 該碰的東西。
//    → V23 新增 InpMagicNumber（預設 920）、InpManageSymbolOnly、
//      InpRiskClosesAll（預設 false）。定時出場與掛止損只動自己開的單。
//    ⚠️ 前提：你的進場 EA 下單時要設同一個 magic number（920）。
//      沒設的話 EA 會認不得自己的單，定時出場不會生效。
//
// ⚠ ZhugeOrderCheck() 在本 EA 內部沒有呼叫點 —— 它是給你的進場 EA 用的閘門。
//   V23 的簽名變成 ZhugeOrderCheck(bool is_buy)，有預設值所以舊的呼叫仍能編譯，
//   但那樣只做多就【不會生效】。請把呼叫改成：
//       if(!ZhugeOrderCheck(true))  return;   // 買單
//       if(!ZhugeOrderCheck(false)) return;   // 賣單
//
// ⚠ 上述所有數字都是【樣本內】或【單一市場】的量測。規則的優勢仍未被證實。
//   這些改動降低的是「輸法」，不是提高「贏面」。
// =====================================================================


// 引入交易庫
#include <Trade\Trade.mqh>
CTrade trade;

//--- 輸入參數 ---
input group "=== 帳戶風控設定 (港元計價) ==="
input double   InpMaxDailyLossHKD  = 1200.0;     // 1. 當日最大虧損強平線 (HKD；本金 20,000 的 6%。GCP 在 −3% 就停放行)
input double   InpMaxTotalDrawdown = 20.0;       // 2. 帳戶最大淨值回撤比例 (%)  ← V22 是 90，與空城計的 20% 矛盾
input double   InpTakeProfitHKD    = 0.0;        // 3. 浮盈全平門檻 (HKD)。0 = 停用 ← V22 的 500 經量度為結構性負期望
input int      InpHoursOffset      = 0;          // 4. 手動時區微調 (小時，可正可負)

input group "=== ⚠️ 管轄範圍（V23 新增，預設只碰自己開的單）==="
input long     InpMagicNumber      = 920;         // 只管這個 magic 的持倉。0 = 管帳戶上全部（危險：會平掉你的手動單）
input bool     InpManageSymbolOnly = true;        // 只管 EA 掛載的那個商品
input bool     InpRiskClosesAll    = false;       // 風控觸發時是否連非管轄持倉一起平？預設否

input group "=== 出場（V23：定時，不是 TP/SL）==="
input int      InpHoldMinutes      = 150;        // 持倉滿幾分鐘無條件全平 (150 = 10 根 M15 = 2.5 小時)。0 = 停用
input bool     InpLongOnly         = true;       // 只做多 (全期 671 筆空單 t = −0.25)

input group "=== 單筆訂單災難停損（不是出場條件）==="
input int      InpDefaultSLPoints  = 8000;     // 裸單自動掛的災難停損 (黃金 8000 點 = US$80/oz)。正常情況碰不到
input bool     InpAttachTP         = false;    // 是否同時掛 TP。V23 預設否 —— TP 是定時出場的事

input group "=== 諸葛亮雲端電閘設定 ==="
input string   InpGcpUrl = "https://zhuge-risk-manager-1056099871997.europe-west1.run.app"; // GCP 雲端函式網址

input group "=== 面板視覺設定 ==="
input color    InpXTextColor       = clrWhite;        // 文字顏色
input color    InpXBgColor         = clrMidnightBlue; // 面板背景顏色 
//--- 寬版持倉監控面板尺寸 ---
const int PanelWidth  = 700; 
const int PanelHeight = 720; 

//--- 風控與統計全局變數 ---
datetime LastDayReset = 0;
bool     IsRiskTriggered = false;
string   ObjPrefix = "RM_DB_"; 
double   MaxHistoricalEquity = 0;    
double   DynamicMaxDrawdownHKD = 0;  
int      TotalResetCount = 0;        
int      TotalTakeProfitCount = 0;   

// =========================================================================
// 📡 【諸葛亮電閘全域隔離區】防範 4014 線程阻塞衝突與動態 RRR 接收
// =========================================================================
int      GCP_CurrentGateCode = 403;  // 🎯 核心開關：預設 403 鎖死
bool     GCP_NeedToSendHit   = false; 
int      Zhuge_RejectedCount = 0;    
ulong    LastSentDealTicket = 0;     

double   GCP_WinRate = 0.0;          
double   GCP_Recommended_RRR = 2.0;  
double   DynamicTP_HKD = 200.0;      
datetime g_last_sent_m1_bar_time = 0;

// 🎯 ATR 指標的全域常駐 Handle (解決 0.0 的問題)
int atr_handle_m1  = INVALID_HANDLE;
int atr_handle_m5  = INVALID_HANDLE;
int atr_handle_m15 = INVALID_HANDLE;

//--- 前瞻宣告後半部函數 ---
void CreateDashboard();
void AdjustPanelToCenter();
void UpdateDashboard();
void CloseAllPositions();
double GetDailyRealizedPnL(); 
void CheckCloudGate();
void SendTargetHitToCloud();
bool ZhugeOrderCheck(bool is_buy = true);   // V23：多了方向參數，用來擋空單
void CheckTimeExit();
bool IsManaged(ulong ticket);              
void CheckAndSetSLTP();

//+------------------------------------------------------------------+
//| EA 初始化函數                                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   LastDayReset = TimeCurrent() - (TimeCurrent() % 86400); 
   IsRiskTriggered = false;
   GCP_CurrentGateCode = 403; 
   GCP_NeedToSendHit = false;
   Zhuge_RejectedCount = 0;
   
   DynamicTP_HKD = InpTakeProfitHKD; 
   
   MaxHistoricalEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   DynamicMaxDrawdownHKD = MaxHistoricalEquity * (InpMaxTotalDrawdown / 100.0);
   
   // 🎯 在 EA 啟動時一次性建立常駐 ATR 指標
   atr_handle_m1  = iATR(_Symbol, PERIOD_M1, 14);
   atr_handle_m5  = iATR(_Symbol, PERIOD_M5, 14);
   atr_handle_m15 = iATR(_Symbol, PERIOD_M15, 14);
   
   CreateDashboard();
   AdjustPanelToCenter();
   
   Print("🚀 [啟動測試] EA 初始化完成！準備發射第一次 WebRequest 測試...");
   CheckCloudGate(); 
   
   UpdateDashboard();
   EventSetMillisecondTimer(60000); // 維持 60 秒 (60000 毫秒) 執行一次
   
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, ObjPrefix);
   EventKillTimer(); 
   ChartRedraw(0);
   
   // 🎯 釋放 ATR 指標資源
   if(atr_handle_m1 != INVALID_HANDLE) IndicatorRelease(atr_handle_m1);
   if(atr_handle_m5 != INVALID_HANDLE) IndicatorRelease(atr_handle_m5);
   if(atr_handle_m15 != INVALID_HANDLE) IndicatorRelease(atr_handle_m15);
   
   Print("[DEBUG] EA 已解除掛載。");
}

void OnTick()
{
   datetime current_day = TimeCurrent() - (TimeCurrent() % 86400);
   if(current_day > LastDayReset)
   {
      LastDayReset = current_day;
      IsRiskTriggered = false;
      TotalResetCount++; 
      
      MaxHistoricalEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      DynamicMaxDrawdownHKD = MaxHistoricalEquity * (InpMaxTotalDrawdown / 100.0);
      
      string resetMessage = "🔄【EA 風控跨日重置通知】\n系統已成功完成跨日數據重置！\n今日新基準淨值：" + DoubleToString(MaxHistoricalEquity, 2) + " HKD";
      SendNotification(resetMessage);
   }

   if(IsRiskTriggered)
   {
      CloseAllPositions();
      UpdateDashboard();
      return;
   }

   double realized_pnl = GetDailyRealizedPnL();
   double floating_pnl = AccountInfoDouble(ACCOUNT_PROFIT); 
   double total_daily_pnl = realized_pnl + floating_pnl;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   
   if(MaxHistoricalEquity <= 0 || equity > MaxHistoricalEquity)
   {
      MaxHistoricalEquity = equity;
      DynamicMaxDrawdownHKD = MaxHistoricalEquity * (InpMaxTotalDrawdown / 100.0);
   }
   
   double drawdown_hkd = MaxHistoricalEquity - equity;
   if(drawdown_hkd < 0) drawdown_hkd = 0;
   double drawdown_percent = (MaxHistoricalEquity > 0) ? (drawdown_hkd / MaxHistoricalEquity) * 100.0 : 0;

   // 1. 【動態獲利全平倉】使用 DynamicTP_HKD
   //    V23：InpTakeProfitHKD = 0 時整段停用。量度結果見檔頭 ①。
   if(InpTakeProfitHKD > 0 && DynamicTP_HKD > 0 && floating_pnl >= DynamicTP_HKD)
   {
      GCP_CurrentGateCode = 403; 
      TotalTakeProfitCount++; 
      
      string tpMessage = "🎉【EA 達標獲利平倉通知】\n當前持倉浮盈已觸發動態目標 " + DoubleToString(DynamicTP_HKD, 2) + " HKD！系統已執行全盤清倉。";
      SendNotification(tpMessage);
      Print("🎉 [獲利平倉] 已達動態目標 +" + DoubleToString(DynamicTP_HKD, 2) + " HKD！本地電閘已同步瞬間鎖死。");
      
      GCP_NeedToSendHit = true; 
      CloseAllPositions();
   }

   // 2. 【虧損與動態淨值雙軌鎖定】
   if((total_daily_pnl < 0 && MathAbs(total_daily_pnl) >= InpMaxDailyLossHKD) || 
      drawdown_percent >= InpMaxTotalDrawdown || 
      drawdown_hkd >= DynamicMaxDrawdownHKD)
   {
      IsRiskTriggered = true;
      GCP_CurrentGateCode = 403;
      Alert("⚠️ [風控鎖定] 已達風控上限，全盤強平並鎖定帳戶！");
      CloseAllPositions();
   }
   
   // 3. 🎯 自動偵測裸單並掛載災難停損
   CheckAndSetSLTP();

   // 4. ⏱️ V23 的真正出場：持倉滿 InpHoldMinutes 就全平。
   CheckTimeExit();
   
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| 自動偵測裸單，動態掛載實體 SL / TP                               |
//+------------------------------------------------------------------+
void CheckAndSetSLTP()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && IsManaged(ticket))          // V23：不碰手動單
      {
         double current_sl = PositionGetDouble(POSITION_SL);
         
         if(current_sl == 0.0)
         {
            string symbol = PositionGetString(POSITION_SYMBOL);
            long type = PositionGetInteger(POSITION_TYPE);
            double open_price = PositionGetDouble(POSITION_PRICE_OPEN);

            double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
            int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

            double sl_price = 0.0;
            double tp_price = 0.0;

            double current_rrr = (GCP_Recommended_RRR > 0) ? GCP_Recommended_RRR : 2.0;
            int dynamic_tp_points = InpAttachTP ? (int)MathRound(InpDefaultSLPoints * current_rrr) : 0;

            // V23：tp_price = 0 表示不掛 TP。出場交給 CheckTimeExit()。
            if(type == POSITION_TYPE_BUY)
            {
               sl_price = open_price - (InpDefaultSLPoints * point);
               tp_price = InpAttachTP ? open_price + (dynamic_tp_points * point) : 0.0;
            }
            else if(type == POSITION_TYPE_SELL)
            {
               sl_price = open_price + (InpDefaultSLPoints * point);
               tp_price = InpAttachTP ? open_price - (dynamic_tp_points * point) : 0.0;
            }

            sl_price = NormalizeDouble(sl_price, digits);
            tp_price = (tp_price > 0.0) ? NormalizeDouble(tp_price, digits) : 0.0;

            if(trade.PositionModify(ticket, sl_price, tp_price))
            {
               if(tp_price > 0.0)
                  PrintFormat("🛡️ [災難停損＋TP 掛載] 單號: %d | RRR: %.2f | SL: %.2f | TP: %.2f", ticket, current_rrr, sl_price, tp_price);
               else
                  PrintFormat("🛡️ [災難停損掛載] 單號: %d | SL: %.2f（US$%.0f/oz）| 無 TP，出場交給定時 %d 分鐘",
                              ticket, sl_price, InpDefaultSLPoints * point, InpHoldMinutes);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 精確計算今日已實現損益 (究極對齊版：完全模擬手機版 Position 視角)        |
//+------------------------------------------------------------------+
double GetDailyRealizedPnL()
{
   double daily_pnl = 0.0;
   TotalTakeProfitCount = 0; 
   
   datetime todayStart = TimeCurrent() - (TimeCurrent() % 86400) - (InpHoursOffset * 3600);
   ulong closed_positions[];
   int pos_count = 0;
   
   if(HistorySelect(todayStart, TimeCurrent()))
   {
      int totalDeals = HistoryDealsTotal();
      for(int i = 0; i < totalDeals; i++)
      {
         ulong ticket = HistoryDealGetTicket(i);
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_INOUT)
         {
             ulong pos_id = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
             bool exists = false;
             for(int k = 0; k < pos_count; k++) { 
                if(closed_positions[k] == pos_id) { exists = true; break; } 
             }
             
             if(!exists) {
                 ArrayResize(closed_positions, pos_count + 1);
                 closed_positions[pos_count] = pos_id;
                 pos_count++;
             }
         }
      }
   }
   
   for(int i = 0; i < pos_count; i++)
   {
       if(HistorySelectByPosition(closed_positions[i]))
       {
           double pos_profit = 0.0, pos_comm = 0.0, pos_swap = 0.0;
           int p_deals = HistoryDealsTotal();
           
           for(int j = 0; j < p_deals; j++)
           {
               ulong p_ticket = HistoryDealGetTicket(j);
               pos_profit += HistoryDealGetDouble(p_ticket, DEAL_PROFIT);
               pos_comm   += HistoryDealGetDouble(p_ticket, DEAL_COMMISSION);
               pos_swap   += HistoryDealGetDouble(p_ticket, DEAL_SWAP);
           }
           
           double pos_net = pos_profit + pos_comm + pos_swap;
           // V23：TP 停用（InpTakeProfitHKD = 0）時，原式變成 pos_net >= −5，
           //      幾乎每一筆都會被算成「達標」。停用時改數真正賺錢的筆數。
           if(InpTakeProfitHKD > 0 ? (pos_net >= InpTakeProfitHKD - 5.0) : (pos_net > 0.0))
              TotalTakeProfitCount++;
           daily_pnl += pos_net;
       }
   }
   
   HistorySelect(0, TimeCurrent());
   return daily_pnl;
}

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id == CHARTEVENT_CHART_CHANGE) AdjustPanelToCenter();
}

void OnTimer()
{
   UpdateDashboard();
   CheckCloudGate();
   
   if(GCP_NeedToSendHit)
   {
      SendTargetHitToCloud();
   }
}

//+------------------------------------------------------------------+
//| ⚠️ V23 新增：這張單歸不歸我管？                                   |
//|                                                                  |
//| V22 完全沒有過濾 —— CloseAllPositions / CheckAndSetSLTP 都是直接  |
//| 掃 PositionsTotal()，等於帳戶上每一張單都會被動到。如果這個戶口   |
//| 同時有你的手動單或直覺倉，EA 會：                                 |
//|   · 幫它們掛上 8000 點的止損                                      |
//|   · 在持倉滿 150 分鐘時把它們平掉                                 |
//| 你的手實測年化 11.67% —— 那不是 EA 該碰的東西。                   |
//+------------------------------------------------------------------+
bool IsManaged(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return(false);
   if(InpManageSymbolOnly && PositionGetString(POSITION_SYMBOL) != _Symbol) return(false);
   if(InpMagicNumber != 0 && PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) return(false);
   return(true);
}

//+------------------------------------------------------------------+
//| 平倉。all_including_unmanaged = true 時連不歸我管的也平           |
//| （只有風控熔斷且 InpRiskClosesAll = true 才會這樣叫）             |
//+------------------------------------------------------------------+
void ClosePositions(bool all_including_unmanaged)
{
   int skipped = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket <= 0) continue;
      if(!all_including_unmanaged && !IsManaged(ticket)) { skipped++; continue; }
      trade.PositionClose(ticket);
   }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket <= 0) continue;
      if(!all_including_unmanaged)
      {
         if(!OrderSelect(ticket)) continue;
         if(InpManageSymbolOnly && OrderGetString(ORDER_SYMBOL) != _Symbol) { skipped++; continue; }
         if(InpMagicNumber != 0 && OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) { skipped++; continue; }
      }
      trade.OrderDelete(ticket);
   }
   if(skipped > 0)
      PrintFormat("ℹ️ [管轄範圍] 略過 %d 張不歸本 EA 管的單（magic=%d, symbol=%s）",
                  skipped, InpMagicNumber, InpManageSymbolOnly ? _Symbol : "全部");
}

void CloseAllPositions()
{
   ClosePositions(InpRiskClosesAll);
}

void AdjustPanelToCenter()
{
   int chartWidth  = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int chartHeight = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);
   int centerX = (chartWidth - PanelWidth) / 2;
   int centerY = (chartHeight - PanelHeight) / 2;
   if(centerX < 0) centerX = 0;
   if(centerY < 0) centerY = 0;

   ObjectSetInteger(0, ObjPrefix + "BG", OBJPROP_XDISTANCE, centerX);
   ObjectSetInteger(0, ObjPrefix + "BG", OBJPROP_YDISTANCE, centerY);
   
   int dataX = centerX + 250; 
   int rowGap = 40; 
   
   ObjectSetInteger(0, ObjPrefix + "Title",    OBJPROP_XDISTANCE, centerX + 25);
   ObjectSetInteger(0, ObjPrefix + "Title",    OBJPROP_YDISTANCE, centerY + 20);
   
   string labels[] = {"Sym", "Positions", "Net", "MarginLevel", "Bal", "Real", "Float", "TotalPnL", "DD", "Param_Loss", "Param_DD", "Param_TP", "Status", "GCP_Gate", "RejectCount", "WinRate"};
   
   for(int i = 0; i < ArraySize(labels); i++)
   {
      int yPos = centerY + 60 + (rowGap * i);
      if(i >= 12) yPos += 10; 
      
      ObjectSetInteger(0, ObjPrefix + "L_" + labels[i], OBJPROP_XDISTANCE, centerX + 30);
      ObjectSetInteger(0, ObjPrefix + "L_" + labels[i], OBJPROP_YDISTANCE, yPos);
      ObjectSetInteger(0, ObjPrefix + "D_" + labels[i], OBJPROP_XDISTANCE, dataX);
      ObjectSetInteger(0, ObjPrefix + "D_" + labels[i], OBJPROP_YDISTANCE, yPos);
   }
   ChartRedraw(0);
}

void CreateLabel(string name, string text, int size, color col, bool bold)
{
   string objName = ObjPrefix + name;
   ObjectCreate(0, objName, OBJ_LABEL, 0, 0, 0);
   ObjectSetString(0, objName, OBJPROP_TEXT, text);
   ObjectSetString(0, objName, OBJPROP_FONT, bold ? "Microsoft JhengHei Bold" : "Microsoft JhengHei");
   ObjectSetInteger(0, objName, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, objName, OBJPROP_COLOR, col);
   ObjectSetInteger(0, objName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, objName, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER); 
   ObjectSetInteger(0, objName, OBJPROP_SELECTABLE, false);
}

void CreateDashboard()
{
   string bgName = ObjPrefix + "BG";
   ObjectCreate(0, bgName, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, bgName, OBJPROP_XSIZE, PanelWidth);
   ObjectSetInteger(0, bgName, OBJPROP_YSIZE, PanelHeight);
   ObjectSetInteger(0, bgName, OBJPROP_BGCOLOR, InpXBgColor);
   ObjectSetInteger(0, bgName, OBJPROP_BORDER_COLOR, clrDimGray);
   ObjectSetInteger(0, bgName, OBJPROP_STATE, false);        
   ObjectSetInteger(0, bgName, OBJPROP_SELECTABLE, false);      
   
   CreateLabel("Title", "港元日內風控與 AI 聯動系統 (全捕捉修正版)", 14, clrGold, true);
   
   string leftTexts[] = {"當前持倉商品 :", "當前多單 / 空單 :", "當前對沖淨持倉 :", "預付款比率 :", "帳戶結餘 / 淨值  :", "今日已實現損益 :", "當下浮動盈虧 :", "今日總損益 (實+浮) :", "當前帳戶回撤 :", "DailyLoss:", "Drawdown:", "TakeProfit (動態):", "系統風控狀態 :", "諸葛亮電閘狀態 :", "已成功鎖死攔截 :", "雲端實時勝率 :"};
   string rightNames[] = {"Sym", "Positions", "Net", "MarginLevel", "Bal", "Real", "Float", "TotalPnL", "DD", "Param_Loss", "Param_DD", "Param_TP", "Status", "GCP_Gate", "RejectCount", "WinRate"};
   
   for(int i = 0; i < ArraySize(leftTexts); i++)
   {
      color labelColor = (i >= 9 && i <= 11) ? clrLightGray : InpXTextColor;
      CreateLabel("L_" + rightNames[i], leftTexts[i], 12, labelColor, false);
      CreateLabel("D_" + rightNames[i], "讀取中...", 12, clrWhite, false);
   }
   
   ObjectSetInteger(0, ObjPrefix + "D_Param_Loss", OBJPROP_COLOR, clrGold);
   ObjectSetInteger(0, ObjPrefix + "D_Param_DD", OBJPROP_COLOR, clrGold);
   ObjectSetInteger(0, ObjPrefix + "D_Param_TP", OBJPROP_COLOR, clrGold);
   ObjectSetString(0, ObjPrefix + "D_Status", OBJPROP_FONT, "Microsoft JhengHei Bold"); 
   ObjectSetString(0, ObjPrefix + "D_GCP_Gate", OBJPROP_FONT, "Microsoft JhengHei Bold"); 
}

void UpdateDashboard()
{
   string targetedSymbol = "";
   int totalPositions = PositionsTotal();
   if(totalPositions > 0) targetedSymbol = PositionGetSymbol(0); 
   
   if(targetedSymbol == "")
   {
      ObjectSetString(0, ObjPrefix + "D_Sym", OBJPROP_TEXT, "無持倉 (" + _Symbol + ")");
      ObjectSetInteger(0, ObjPrefix + "D_Sym", OBJPROP_COLOR, clrDarkGray);
      ObjectSetString(0, ObjPrefix + "D_Positions", OBJPROP_TEXT, "0.00 買 / 0.00 賣");
      ObjectSetString(0, ObjPrefix + "D_Net", OBJPROP_TEXT, "無淨持倉 (0.00)");
      ObjectSetInteger(0, ObjPrefix + "D_Net", OBJPROP_COLOR, clrWhite);
   }
   else
   {
      ObjectSetString(0, ObjPrefix + "D_Sym", OBJPROP_TEXT, targetedSymbol);
      ObjectSetInteger(0, ObjPrefix + "D_Sym", OBJPROP_COLOR, clrGold);

      double buyLots = 0, sellLots = 0;
      for(int i = totalPositions - 1; i >= 0; i--)
      {
         if(PositionGetSymbol(i) == targetedSymbol)
         {
            double volume = PositionGetDouble(POSITION_VOLUME);
            long type = PositionGetInteger(POSITION_TYPE);
            if(type == POSITION_TYPE_BUY) buyLots += volume;
            else if(type == POSITION_TYPE_SELL) sellLots += volume;
         }
      }
      ObjectSetString(0, ObjPrefix + "D_Positions", OBJPROP_TEXT, DoubleToString(buyLots, 2) + " 買 / " + DoubleToString(sellLots, 2) + " 賣");
      double netLots = buyLots - sellLots;
      if(netLots > 0)
      {
         ObjectSetString(0, ObjPrefix + "D_Net", OBJPROP_TEXT, "淨多單 +" + DoubleToString(netLots, 2) + " 手");
         ObjectSetInteger(0, ObjPrefix + "D_Net", OBJPROP_COLOR, clrLime); 
      }
      else if(netLots < 0)
      {
         ObjectSetString(0, ObjPrefix + "D_Net", OBJPROP_TEXT, "淨空單 -" + DoubleToString(MathAbs(netLots), 2) + " 手");
         ObjectSetInteger(0, ObjPrefix + "D_Net", OBJPROP_COLOR, clrRed); 
      }
      else
      {
         ObjectSetString(0, ObjPrefix + "D_Net", OBJPROP_TEXT, "無淨持倉 (0.00)");
         ObjectSetInteger(0, ObjPrefix + "D_Net", OBJPROP_COLOR, clrWhite);
      }
   }

   double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   if(marginLevel == 0) 
   {
      ObjectSetString(0, ObjPrefix + "D_MarginLevel", OBJPROP_TEXT, "無持倉 (100.00%)");
      ObjectSetInteger(0, ObjPrefix + "D_MarginLevel", OBJPROP_COLOR, clrWhite);
   }
   else
   {
      ObjectSetString(0, ObjPrefix + "D_MarginLevel", OBJPROP_TEXT, DoubleToString(marginLevel, 2) + " %");
      if(marginLevel < 1000.0) ObjectSetInteger(0, ObjPrefix + "D_MarginLevel", OBJPROP_COLOR, clrRed); 
      else ObjectSetInteger(0, ObjPrefix + "D_MarginLevel", OBJPROP_COLOR, clrLime); 
   }

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   // [R87] 順序＝標籤順序：結餘(Balance) / 淨值(Equity)。用語跟 MT5「交易」分頁一致。
   //       淨值 = 結餘 + 信用 + 浮動。有信用時兩者本來就不相等，不是異常。
   ObjectSetString(0, ObjPrefix + "D_Bal", OBJPROP_TEXT, DoubleToString(balance, 2) + " / " + DoubleToString(equity, 2));

   double realized_pnl = GetDailyRealizedPnL(); 
   ObjectSetString(0, ObjPrefix + "D_Real", OBJPROP_TEXT, DoubleToString(realized_pnl, 2) + " HKD");
   if(realized_pnl > 0) ObjectSetInteger(0, ObjPrefix + "D_Real", OBJPROP_COLOR, clrLime);
   else if(realized_pnl < 0) ObjectSetInteger(0, ObjPrefix + "D_Real", OBJPROP_COLOR, clrRed);
   else ObjectSetInteger(0, ObjPrefix + "D_Real", OBJPROP_COLOR, clrWhite);

   double floating_pnl = AccountInfoDouble(ACCOUNT_PROFIT);
   ObjectSetString(0, ObjPrefix + "D_Float", OBJPROP_TEXT, DoubleToString(floating_pnl, 2) + " HKD");
   if(floating_pnl > 0) ObjectSetInteger(0, ObjPrefix + "D_Float", OBJPROP_COLOR, clrLime);     
   else if(floating_pnl < 0) ObjectSetInteger(0, ObjPrefix + "D_Float", OBJPROP_COLOR, clrRed);        
   else ObjectSetInteger(0, ObjPrefix + "D_Float", OBJPROP_COLOR, clrWhite);    

   double total_daily_pnl = realized_pnl + floating_pnl;
   ObjectSetString(0, ObjPrefix + "D_TotalPnL", OBJPROP_TEXT, DoubleToString(total_daily_pnl, 2) + " HKD");
   if(total_daily_pnl > 0) ObjectSetInteger(0, ObjPrefix + "D_TotalPnL", OBJPROP_COLOR, clrLime);
   else if(total_daily_pnl < 0) ObjectSetInteger(0, ObjPrefix + "D_TotalPnL", OBJPROP_COLOR, clrRed);
   else ObjectSetInteger(0, ObjPrefix + "D_TotalPnL", OBJPROP_COLOR, clrWhite);

   double dd_hkd = MaxHistoricalEquity - equity;
   if(dd_hkd < 0) dd_hkd = 0;
   double dd_percent = (MaxHistoricalEquity > 0) ? (dd_hkd / MaxHistoricalEquity) * 100.0 : 0;

   string dd_text = DoubleToString(dd_hkd, 2) + " HKD (" + DoubleToString(dd_percent, 2) + "%) / " + 
                    DoubleToString(DynamicMaxDrawdownHKD, 2) + " HKD (" + DoubleToString(InpMaxTotalDrawdown, 0) + "%)";
   ObjectSetString(0, ObjPrefix + "D_DD", OBJPROP_TEXT, dd_text);
   
   ObjectSetString(0, ObjPrefix + "D_Param_Loss", OBJPROP_TEXT, DoubleToString(InpMaxDailyLossHKD, 2) + " HKD");
   ObjectSetString(0, ObjPrefix + "D_Param_DD",   OBJPROP_TEXT, DoubleToString(InpMaxTotalDrawdown, 2) + " %");
   string tp_text = (InpTakeProfitHKD > 0)
                    ? DoubleToString(DynamicTP_HKD, 2) + " HKD (雲端 RRR 控制)"
                    : "停用 → 定時出場 " + IntegerToString(InpHoldMinutes) + " 分鐘";
   ObjectSetString(0, ObjPrefix + "D_Param_TP",   OBJPROP_TEXT, tp_text);
   
   if(dd_percent >= InpMaxTotalDrawdown * 0.7 || dd_hkd >= DynamicMaxDrawdownHKD * 0.7 || 
      (total_daily_pnl < 0 && MathAbs(total_daily_pnl) >= InpMaxDailyLossHKD * 0.7)) 
   {
      ObjectSetInteger(0, ObjPrefix + "D_DD", OBJPROP_COLOR, clrOrangeRed);
   }
   else ObjectSetInteger(0, ObjPrefix + "D_DD", OBJPROP_COLOR, clrWhite);

   if(IsRiskTriggered)
   {
      ObjectSetString(0, ObjPrefix + "D_Status", OBJPROP_TEXT, "已鎖定 (🚨 達上限)");
      ObjectSetInteger(0, ObjPrefix + "D_Status", OBJPROP_COLOR, clrRed);
   }
   else
   {
      ObjectSetString(0, ObjPrefix + "D_Status", OBJPROP_TEXT, "正常監控中 (🟢)");
      ObjectSetInteger(0, ObjPrefix + "D_Status", OBJPROP_COLOR, clrLime);
   }

   if(GCP_CurrentGateCode == 200)
   {
      ObjectSetString(0, ObjPrefix + "D_GCP_Gate", OBJPROP_TEXT, "開啟放行 (🟢 GCP: 200)");
      ObjectSetInteger(0, ObjPrefix + "D_GCP_Gate", OBJPROP_COLOR, clrLime);
   }
   else if(GCP_CurrentGateCode == 403)
   {
      ObjectSetString(0, ObjPrefix + "D_GCP_Gate", OBJPROP_TEXT, "雲端鎖死 (🚨 GCP: 403)");
      ObjectSetInteger(0, ObjPrefix + "D_GCP_Gate", OBJPROP_COLOR, clrRed);
   }
   else
   {
      ObjectSetString(0, ObjPrefix + "D_GCP_Gate", OBJPROP_TEXT, "連線異常 (⚠️ Code: " + IntegerToString(GCP_CurrentGateCode) + ")");
      ObjectSetInteger(0, ObjPrefix + "D_GCP_Gate", OBJPROP_COLOR, clrOrange);
   }

   ObjectSetString(0, ObjPrefix + "D_RejectCount", OBJPROP_TEXT, IntegerToString(Zhuge_RejectedCount) + " 筆交易訊號");
   if(Zhuge_RejectedCount > 0) ObjectSetInteger(0, ObjPrefix + "D_RejectCount", OBJPROP_COLOR, clrOrange); 
   else ObjectSetInteger(0, ObjPrefix + "D_RejectCount", OBJPROP_COLOR, clrWhite);
   
   ObjectSetString(0, ObjPrefix + "D_WinRate", OBJPROP_TEXT, DoubleToString(GCP_WinRate, 1) + "% (建議 RRR: " + DoubleToString(GCP_Recommended_RRR, 2) + ")");
   ObjectSetInteger(0, ObjPrefix + "D_WinRate", OBJPROP_COLOR, clrGold);

   ChartRedraw(0);
}

void CheckCloudGate()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double floating = AccountInfoDouble(ACCOUNT_PROFIT);
   string currency = AccountInfoString(ACCOUNT_CURRENCY);
   if(currency == "") currency = "HKD";

   string targetedSymbol = "NONE";
   double buyLots = 0.0, sellLots = 0.0;
   int totalPositions = PositionsTotal();
   
   if(totalPositions > 0)
   {
      targetedSymbol = PositionGetSymbol(0);
      for(int i = totalPositions - 1; i >= 0; i--)
      {
         if(PositionGetSymbol(i) == targetedSymbol)
         {
            double volume = PositionGetDouble(POSITION_VOLUME);
            long type = PositionGetInteger(POSITION_TYPE);
            if(type == POSITION_TYPE_BUY) buyLots += volume;
            else if(type == POSITION_TYPE_SELL) sellLots += volume;
         }
      }
   }
   double netLots = buyLots - sellLots;
   string ohlc_symbol = (targetedSymbol != "NONE") ? targetedSymbol : _Symbol;
   
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   string ohlc_json = "null";
   if(CopyRates(ohlc_symbol, PERIOD_M1, 1, 1, rates) > 0)
   {
      if(rates[0].time != g_last_sent_m1_bar_time)
      {
         g_last_sent_m1_bar_time = rates[0].time;
         ohlc_json = StringFormat(
            "{\"symbol\":\"%s\",\"time\":%d,\"open\":%.2f,\"high\":%.2f,\"low\":%.2f,\"close\":%.2f,\"volume\":%d,\"is_new_bar\":true}",
            ohlc_symbol, (long)rates[0].time, rates[0].open, rates[0].high, rates[0].low, rates[0].close, rates[0].tick_volume
         );
      }
      else
      {
         ohlc_json = StringFormat("{\"time\":%d,\"is_new_bar\":false}", (long)rates[0].time);
      }
   }

   MqlRates rates_m15[];
   ArraySetAsSeries(rates_m15, true);
   string ohlc_json_m15 = "null";
   double atr_m1_val = 0.0, atr_m5_val = 0.0, atr_m15_val = 0.0;
   double atr_buffer[];
   
   // 🎯 直接從常駐 Handle 讀取，確保隨時有最新數據
   if(atr_handle_m1 != INVALID_HANDLE && CopyBuffer(atr_handle_m1, 0, 0, 1, atr_buffer) > 0) atr_m1_val = atr_buffer[0];
   if(atr_handle_m5 != INVALID_HANDLE && CopyBuffer(atr_handle_m5, 0, 0, 1, atr_buffer) > 0) atr_m5_val = atr_buffer[0];
   if(atr_handle_m15 != INVALID_HANDLE && CopyBuffer(atr_handle_m15, 0, 0, 1, atr_buffer) > 0) atr_m15_val = atr_buffer[0];

   if(CopyRates(ohlc_symbol, PERIOD_M15, 1, 1, rates_m15) > 0)
   {
      ohlc_json_m15 = StringFormat(
         "{\"time\":%d,\"open\":%.2f,\"high\":%.2f,\"low\":%.2f,\"close\":%.2f,\"atr_m1\":%.4f,\"atr_m5\":%.4f,\"atr_m15\":%.4f}",
         (long)rates_m15[0].time, rates_m15[0].open, rates_m15[0].high, rates_m15[0].low, rates_m15[0].close,
         atr_m1_val, atr_m5_val, atr_m15_val
      );
   }

   // 🎯 取得精準的今日已實現損益
   double daily_pnl = GetDailyRealizedPnL();

   // 🎯 將 daily_pnl 與完整的 ATR 寫入封包傳給 GCP
   string check_body = StringFormat(
      "{\"action\":\"check_gate\",\"status\":\"MONITORING\",\"symbol\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"floating\":%.2f,\"daily_pnl\":%.2f,\"buy_lots\":%.2f,\"sell_lots\":%.2f,\"net_lots\":%.2f,"
      "\"m1_ohlc\":%s,\"m15_ohlc\":%s}",
      targetedSymbol, currency, balance, equity, floating, daily_pnl, buyLots, sellLots, netLots, ohlc_json, ohlc_json_m15
   );

   char post_data[], result_data[];
   string result_headers;
   int string_len = StringToCharArray(check_body, post_data, 0, WHOLE_ARRAY, CP_UTF8);
   if(string_len > 0) ArrayResize(post_data, string_len - 1); 

   string headers = "Content-Type: application/json\r\n";
   string url_copy = InpGcpUrl;
   StringTrimLeft(url_copy); StringTrimRight(url_copy);

   ResetLastError();
   int http_res = WebRequest("POST", url_copy, headers, 15000, post_data, result_data, result_headers);
   
   if(http_res > 0) 
   {
      GCP_CurrentGateCode = http_res;
      Print("✅ WebRequest 連線成功！狀態碼: ", http_res);
   }
   else 
   {
      GCP_CurrentGateCode = GetLastError();
      Print("⚠️ WebRequest 遭遇致命錯誤！MT5 底層代碼: ", GCP_CurrentGateCode, " | 嘗試連線網址: ", url_copy);
   }
}

void SendTargetHitToCloud()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   string currency = AccountInfoString(ACCOUNT_CURRENCY);
   if(currency == "") currency = "HKD";

   string targetedSymbol = "NONE";
   if(PositionsTotal() > 0) targetedSymbol = PositionGetSymbol(0);
   
   // 🎯 完美補上這裡的 daily_pnl，防止獲利瞬間 UI 閃退回 0.0
   double daily_pnl = GetDailyRealizedPnL();

   string hit_body = StringFormat(
      "{\"action\":\"close_gate\",\"status\":\"TARGET_HIT\",\"symbol\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"daily_pnl\":%.2f,\"buy_lots\":0.00,\"sell_lots\":0.00,\"net_lots\":0.00}",
      targetedSymbol, currency, balance, equity, daily_pnl
   );

   char post_data[], result_data[];
   string result_headers;
   int string_len = StringToCharArray(hit_body, post_data, 0, WHOLE_ARRAY, CP_UTF8);
   if(string_len > 0) ArrayResize(post_data, string_len - 1); 

   string headers = "Content-Type: application/json\r\n";
   string url_copy = InpGcpUrl;
   StringTrimLeft(url_copy); StringTrimRight(url_copy);

   ResetLastError();
   int http_res = WebRequest("POST", url_copy, headers, 2000, post_data, result_data, result_headers);

   if(http_res == 200 || http_res == 403)
   {
      GCP_NeedToSendHit = false;
      Print("[🚨 GCP] 獲利達標熔斷封包已送達雲端！");
   }
}

bool ZhugeOrderCheck(bool is_buy = true)
{
   // V23 ①：只做多。全期 1,464 筆中 671 筆空單，每筆 −HK$0.84、t = −0.25。
   if(InpLongOnly && !is_buy)
   {
      Zhuge_RejectedCount++;
      PrintFormat("🚫 [只做多] 拒絕空單（全期 671 筆空單 t = −0.25，期望值為零）。累計攔截: %d 次", Zhuge_RejectedCount);
      return(false);
   }

   if(GCP_CurrentGateCode == 200) return(true);

   Zhuge_RejectedCount++; 
   PrintFormat("❌ [諸葛亮高頻攔截] 因【雲端電閘鎖死/Code: %d】，本地拒絕執行下單！累計攔截: %d 次", GCP_CurrentGateCode, Zhuge_RejectedCount);
   return(false);
}

//+------------------------------------------------------------------+
//| ⏱️ V23 的出場：持倉滿 InpHoldMinutes 就全平                       |
//|                                                                  |
//| 規則本身就是這樣寫的 —— 突破確認後抱 10 根 M15（150 分鐘）無條件  |
//| 出場，沒有價格停損。加價格停損測過四次，四次都變差。              |
//| V22 的 TP US$64 / SL US$80 把平均持倉拉到 658 分鐘，剛好錯過      |
//| 優勢所在的那段，全期 −HK$20,854。                                 |
//+------------------------------------------------------------------+
void CheckTimeExit()
{
   if(InpHoldMinutes <= 0) return;

   datetime now = TimeCurrent();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket <= 0) continue;
      if(!IsManaged(ticket)) continue;             // V23：定時出場只對自己開的單
      if(!PositionSelectByTicket(ticket)) continue;

      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      int held_min = (int)((now - opened) / 60);
      if(held_min < InpHoldMinutes) continue;

      double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      if(trade.PositionClose(ticket))
         PrintFormat("⏱️ [定時出場] 單號 %d 持倉 %d 分鐘（門檻 %d）→ 全平，損益 %.2f HKD",
                     ticket, held_min, InpHoldMinutes, profit);
      else
         PrintFormat("⚠️ [定時出場失敗] 單號 %d 持倉 %d 分鐘，錯誤 %d —— 下一次 OnTimer 會再試",
                     ticket, held_min, GetLastError());
   }
}

void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      if(trans.deal == LastSentDealTicket) return; 

      HistorySelect(0, TimeCurrent());

      if(!HistoryDealSelect(trans.deal))
      {
         Print("⚠️ [OnTradeTransaction] 無法選取歷史訂單，可能伺服器尚未同步: ", trans.deal);
         return;
      }
      
      LastSentDealTicket = trans.deal;

      long entry_type = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
      if(entry_type == DEAL_ENTRY_OUT || entry_type == DEAL_ENTRY_INOUT)
      {
         double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
         double comm = HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
         double swap = HistoryDealGetDouble(trans.deal, DEAL_SWAP);
         double net_profit = profit + comm + swap;

         double deal_vol = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
         long deal_type_out = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
         string pos_direction = (deal_type_out == DEAL_TYPE_SELL) ? "Buy(多單)" : "Sell(空單)";

         long reason = HistoryDealGetInteger(trans.deal, DEAL_REASON);
         string reason_str = "一般平倉";
         if(reason == DEAL_REASON_SL) reason_str = "SL 止損";
         else if(reason == DEAL_REASON_TP) reason_str = "TP 止盈";
         else if(reason == DEAL_REASON_EXPERT) reason_str = "EA 平倉";
         
         string final_deal_type = pos_direction + " - " + reason_str;

         datetime broker_deal_time = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
         int broker_utc_offset = (int)(TimeCurrent() - TimeGMT());
         datetime utc_deal_time = broker_deal_time - broker_utc_offset;
         string time_str = TimeToString(utc_deal_time, TIME_DATE | TIME_SECONDS);
         StringReplace(time_str, ".", "-");

         string json_body = StringFormat("{\"action\":\"trade_result\",\"ticket\":\"%s\",\"profit\":%.2f,\"volume\":%.2f,\"deal_type\":\"%s\",\"time\":\"%s\"}", 
                                         IntegerToString(trans.deal), net_profit, deal_vol, final_deal_type, time_str);
                                         
         char post_data[], result_data[];
         string result_headers;
         int string_len = StringToCharArray(json_body, post_data, 0, WHOLE_ARRAY, CP_UTF8);
         if(string_len > 0) ArrayResize(post_data, string_len - 1); 

         string headers = "Content-Type: application/json\r\n";
         string url_copy = InpGcpUrl;
         StringTrimLeft(url_copy); StringTrimRight(url_copy);
         
         ResetLastError();
         int http_res = WebRequest("POST", url_copy, headers, 3000, post_data, result_data, result_headers);
         
         if(http_res == 200)
         {
            string response_str = CharArrayToString(result_data);
            
            int wr_pos = StringFind(response_str, "\"win_rate\":");
            int rrr_pos = StringFind(response_str, "\"recommended_rrr\":");
            
            if(wr_pos >= 0 && rrr_pos >= 0)
            {
               int wr_start = wr_pos + 11;
               int wr_end = StringFind(response_str, ",", wr_start);
               if(wr_end == -1) wr_end = StringFind(response_str, "}", wr_start);
               
               int rrr_start = rrr_pos + 18;
               int rrr_end = StringFind(response_str, ",", rrr_start);
               if(rrr_end == -1) rrr_end = StringFind(response_str, "}", rrr_start);

               if (wr_end > wr_start && rrr_end > rrr_start) 
               {
                   string wr_str = StringSubstr(response_str, wr_start, wr_end - wr_start); 
                   string rrr_str = StringSubstr(response_str, rrr_start, rrr_end - rrr_start); 
                   
                   GCP_WinRate = StringToDouble(wr_str);
                   GCP_Recommended_RRR = StringToDouble(rrr_str);
                   
                   double baseRiskHKD = InpTakeProfitHKD / 2.0; 
                   DynamicTP_HKD = baseRiskHKD * GCP_Recommended_RRR;
                   
                   PrintFormat("✅ [AI 動態風控] 最新勝率: %.1f%% | 建議 RRR: %.2f | 動態 HKD 總目標更新為: %.2f", GCP_WinRate, GCP_Recommended_RRR, DynamicTP_HKD);
               }
            }
         }
      }

      string targetedSymbol = (trans.symbol != "") ? trans.symbol : "";
      double lastPrice = trans.price;
      int totalPositions = PositionsTotal();
      double buyLots = 0, sellLots = 0;
      
      if(targetedSymbol == "" && totalPositions > 0) targetedSymbol = PositionGetSymbol(0);
      
      if(targetedSymbol != "" && totalPositions > 0)
      {
         for(int i = totalPositions - 1; i >= 0; i--)
         {
            if(PositionGetSymbol(i) == targetedSymbol)
            {
               double volume = PositionGetDouble(POSITION_VOLUME);
               long type = PositionGetInteger(POSITION_TYPE);
               if(type == POSITION_TYPE_BUY) buyLots += volume;
               else if(type == POSITION_TYPE_SELL) sellLots += volume;
            }
         }
      }
      
      double netLots = buyLots - sellLots;
      string netLotsText = "";
      if(targetedSymbol == "") netLotsText = "無持倉 (0.00手)";
      else if(netLots > 0)     netLotsText = targetedSymbol + " 淨多 +" + DoubleToString(netLots, 2) + "手";
      else if(netLots < 0)     netLotsText = targetedSymbol + " 淨空 -" + DoubleToString(MathAbs(netLots), 2) + "手";
      else                     netLotsText = targetedSymbol + " 已鎖倉 (0.00手)";
      
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      string marginText = (marginLevel == 0) ? "100.00%" : DoubleToString(marginLevel, 2) + "%";
      
      string pushMessage = "交易價格：" + DoubleToString(lastPrice, _Digits) + "\n" +
                           "淨持倉：" + netLotsText + "\n" +
                           "多空手：" + DoubleToString(buyLots, 2) + "買 / " + DoubleToString(sellLots, 2) + "賣\n" +
                           "預付款：" + marginText + "\n" +
                           "餘額/淨值：" + DoubleToString(equity, 2) + " / " + DoubleToString(balance, 2) + " HKD\n" +
                           "策略來源：BOS (GCP RRR 聯動)";
      SendNotification(pushMessage);
   }
}