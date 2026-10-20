//+------------------------------------------------------------------+
//| 🌌 天覆陣執行器 TianfuExecutor.mq5  v0.2（2026-10-20，未編譯、未測）   |
//|                                                                  |
//| 影子階段用法（使用者 10-20：「EA 直接俾 K 線畀新服務」）：            |
//|   InpDryRun=true 掛喺另一個 XAUUSD 圖表，只做資料源：每 60 秒送心跳   |
//|   （M1／M15 K 線、淨值、保證金水平、自己 magic 嘅倉同今日盈虧）去     |
//|   zhuge-xau。dry-run 時 OnTimer 唔會入 Execute()，冇任何落單路徑。    |
//|   線上 V23 照舊指住 zhuge-risk-manager，唔使改。                     |
//|                                                                  |
//| 純執行器：唔自己決策。每 60 秒向 zhuge-xau 送心跳，執行回應入面        |
//| cmd_text 嘅指令（open／close／modify），回報 cmd_ack。               |
//|                                                                  |
//| 設計原則（來自 V23 踩過嘅坑，見 handoff/天覆陣.md §3）：               |
//|  · 只管 _Symbol ＋ InpMagic 嘅倉；唔接手、唔平其他 magic 嘅單         |
//|  · 回報嘅盈虧只計自己 magic（已實現今日＋浮動），唔用戶口淨值           |
//|  · 開倉一定帶伺服器端 SL（冇 SL 嘅 open 指令拒絕執行）                 |
//|  · cmd id 去重：用 GlobalVariable 記最近執行過嘅 id，重啟都唔重複      |
//|  · 唔做定時出場、唔做帳戶回撤熔斷（呢啲由 Cloud Run 決定）             |
//|  · 日誌唔印權杖同網址                                              |
//| 用法：MT5 → 工具 → 選項 → EA 交易 → 允許 WebRequest 加 InpUrl；      |
//|       先掛 demo 戶口；InpToken 填 Cloud Run 嘅 WEBHOOK_SECRET_TOKEN  |
//+------------------------------------------------------------------+
#property copyright "zhuge / 天覆陣"
#property version   "0.20"
#property strict
#include <Trade\Trade.mqh>

input string InpUrl        = "https://zhuge-xau-1056099871997.europe-west1.run.app/"; // Cloud Run 網址（結尾 /）（使用者 10-20：預設填好）
input string InpToken      = "";        // WEBHOOK_SECRET_TOKEN（唔會印出）
input long   InpMagic      = 921;       // 只管呢個 magic 嘅單（線上 V23 用 920，天覆陣用 921）
input int    InpIntervalSec = 60;       // 心跳間隔（秒）
input int    InpTimeoutMs  = 15000;     // WebRequest 逾時
input int    InpSlippagePts = 50;       // 市價單允許滑點（點）
input double InpMaxLots    = 0.10;      // 單張上限（第二道鎖；Cloud Run 亦有 XAU_MAX_LOTS）
input bool   InpDryRun     = true;      // true = 只印指令唔落單（第一次掛先用）

CTrade   trade;
datetime g_last_m1 = 0;
string   g_seen_ids = "";               // 最近執行過嘅 id，以 | 分隔（亦存 GlobalVariable）
#define  SEEN_GV   "TIANFU_SEEN_IDS_"
#define  MAX_SEEN  40

//---------------------------------------------------------------- 工具
string JsonEsc(string s) { StringReplace(s, "\\", "\\\\"); StringReplace(s, "\"", "\\\""); return s; }

bool IsMine(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   if(PositionGetString(POSITION_SYMBOL) != _Symbol) return false;
   return PositionGetInteger(POSITION_MAGIC) == InpMagic;
}

void LoadSeen()
{
   string gv = SEEN_GV + _Symbol;
   // GlobalVariable 只存 double，所以 id 清單用 chart 物件唔穩陣；改用檔案
   int h = FileOpen("tianfu_seen_" + _Symbol + ".txt", FILE_READ | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE) { g_seen_ids = FileReadString(h); FileClose(h); }
}

void SaveSeen()
{
   int h = FileOpen("tianfu_seen_" + _Symbol + ".txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE) { FileWriteString(h, g_seen_ids); FileClose(h); }
}

bool Seen(string id) { return StringFind("|" + g_seen_ids + "|", "|" + id + "|") >= 0; }

void MarkSeen(string id)
{
   string parts[];
   int n = StringSplit(g_seen_ids, '|', parts);
   string out = id;
   int kept = 0;
   for(int i = 0; i < n && kept < MAX_SEEN - 1; i++)
      if(parts[i] != "" && parts[i] != id) { out += "|" + parts[i]; kept++; }
   g_seen_ids = out;
   SaveSeen();
}

// 今日（券商時間）自己 magic 嘅已實現盈虧（含佣金、隔夜利息）
double OwnRealizedToday()
{
   datetime day0 = (datetime)(TimeCurrent() - TimeCurrent() % 86400);
   if(!HistorySelect(day0, TimeCurrent())) return 0.0;
   double sum = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN) continue;
      sum += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
   }
   return sum;
}

//---------------------------------------------------------------- 心跳封包
string BuildHeartbeat()
{
   double buy = 0, sell = 0, floating = 0;
   string pos_json = "";
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !IsMine(t)) continue;
      double v = PositionGetDouble(POSITION_VOLUME);
      long type = PositionGetInteger(POSITION_TYPE);
      if(type == POSITION_TYPE_BUY) buy += v; else sell += v;
      floating += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      if(pos_json != "") pos_json += ",";
      pos_json += StringFormat("{\"ticket\":%I64u,\"side\":\"%s\",\"lots\":%.2f,\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"open_time\":%I64d}",
                               t, type == POSITION_TYPE_BUY ? "BUY" : "SELL", v, PositionGetDouble(POSITION_PRICE_OPEN),
                               PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP), (long)PositionGetInteger(POSITION_TIME));
   }
   MqlRates r1[], r15[];
   ArraySetAsSeries(r1, true); ArraySetAsSeries(r15, true);
   string m1 = "null", m15 = "null";
   if(CopyRates(_Symbol, PERIOD_M1, 1, 1, r1) > 0)
   {
      bool is_new = (r1[0].time != g_last_m1);
      if(is_new) g_last_m1 = r1[0].time;
      m1 = StringFormat("{\"symbol\":\"%s\",\"time\":%I64d,\"open\":%.2f,\"high\":%.2f,\"low\":%.2f,\"close\":%.2f,\"volume\":%I64d,\"is_new_bar\":%s}",
                        _Symbol, (long)r1[0].time, r1[0].open, r1[0].high, r1[0].low, r1[0].close, r1[0].tick_volume, is_new ? "true" : "false");
   }
   if(CopyRates(_Symbol, PERIOD_M15, 1, 1, r15) > 0)
      m15 = StringFormat("{\"time\":%I64d,\"open\":%.2f,\"high\":%.2f,\"low\":%.2f,\"close\":%.2f}",
                         (long)r15[0].time, r15[0].open, r15[0].high, r15[0].low, r15[0].close);
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   return StringFormat(
      "{\"action\":\"heartbeat\",\"token\":\"%s\",\"ea\":\"TianfuExecutor/0.20\",\"symbol\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"credit\":%.2f,\"margin_level\":%.2f,\"floating\":%.2f,\"daily_pnl\":%.2f,"
      "\"buy_lots\":%.2f,\"sell_lots\":%.2f,\"net_lots\":%.2f,\"magic\":%I64d,\"dry_run\":%s,"
      "\"positions\":[%s],\"m1_ohlc\":%s,\"m15_ohlc\":%s}",
      JsonEsc(InpToken), _Symbol, cur, AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_CREDIT), AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), floating, OwnRealizedToday(),
      buy, sell, buy - sell, InpMagic, InpDryRun ? "true" : "false", pos_json, m1, m15);
}

//---------------------------------------------------------------- HTTP
bool Post(string body, string &reply)
{
   char data[], result[];
   string headers = "Content-Type: application/json\r\n", rh;
   int n = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(data, n - 1);
   ResetLastError();
   int code = WebRequest("POST", InpUrl, headers, InpTimeoutMs, data, result, rh);
   if(code == 200) { reply = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8); return true; }
   PrintFormat("⚠️ WebRequest 失敗 code=%d err=%d", code, GetLastError());
   return false;
}

// 由回應 JSON 抽 "cmd_text":"..."（唔用完整 JSON 解析；值入面冇引號同反斜線）
string ExtractCmdText(string reply)
{
   int k = StringFind(reply, "\"cmd_text\":\"");
   if(k < 0) return "";
   k += 12;
   int e = StringFind(reply, "\"", k);
   if(e < 0) return "";
   string s = StringSubstr(reply, k, e - k);
   StringReplace(s, "\\n", "\n");
   return s;
}

string Field(string &parts[], int n, string key)   // key=value 欄位
{
   for(int i = 0; i < n; i++)
      if(StringFind(parts[i], key + "=") == 0) return StringSubstr(parts[i], StringLen(key) + 1);
   return "";
}

void Ack(string id, bool ok, ulong ticket, string msg)
{
   string body = StringFormat("{\"action\":\"cmd_ack\",\"token\":\"%s\",\"id\":\"%s\",\"ok\":%s,\"ticket\":%I64u,\"message\":\"%s\"}",
                              JsonEsc(InpToken), id, ok ? "true" : "false", ticket, JsonEsc(msg));
   string reply;
   Post(body, reply);
}

//---------------------------------------------------------------- 執行指令
void Execute(string line)
{
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 2) return;
   string op = parts[0], id = Field(parts, n, "id");
   if(id == "") { Print("⚠️ 指令冇 id，略過：", line); return; }
   if(Seen(id)) return;                                   // 已執行過（心跳重送）
   long magic = (long)StringToInteger(Field(parts, n, "magic"));
   if(magic != InpMagic) { Print("⚠️ magic 唔符，略過：", line); MarkSeen(id); Ack(id, false, 0, "magic mismatch"); return; }
   MarkSeen(id);                                          // 先記，再執行：寧可漏一次，唔好重複落單
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePts);

   if(op == "open")
   {
      string side = parts[1];
      double lots = NormalizeDouble(StringToDouble(parts[2]), 2);
      double sl = StringToDouble(Field(parts, n, "sl"));
      string tp_s = Field(parts, n, "tp");
      double tp = tp_s == "" ? 0.0 : StringToDouble(tp_s);
      if(lots <= 0 || lots > InpMaxLots) { Ack(id, false, 0, "lots out of range"); return; }
      if(sl <= 0) { Ack(id, false, 0, "no SL"); return; }                       // 冇止損唔開
      // 只管一張：已有自己嘅倉就唔開
      for(int i = PositionsTotal() - 1; i >= 0; i--) { ulong t = PositionGetTicket(i); if(t != 0 && IsMine(t)) { Ack(id, false, 0, "already in position"); return; } }
      if(InpDryRun) { PrintFormat("🧪 [dry-run] open %s %.2f sl=%.2f tp=%.2f id=%s", side, lots, sl, tp, id); Ack(id, true, 0, "dry-run"); return; }
      bool ok = (side == "BUY") ? trade.Buy(lots, _Symbol, 0.0, sl, tp, "天覆陣 " + id)
                                : trade.Sell(lots, _Symbol, 0.0, sl, tp, "天覆陣 " + id);
      ulong ticket = ok ? trade.ResultOrder() : 0;
      PrintFormat("%s open %s %.2f sl=%.2f tp=%.2f → %s %s", ok ? "✅" : "❌", side, lots, sl, tp, trade.ResultRetcodeDescription(), id);
      Ack(id, ok, ticket, trade.ResultRetcodeDescription());
      return;
   }
   if(op == "close" || op == "modify")
   {
      double sl = StringToDouble(Field(parts, n, "sl"));
      string tp_s = Field(parts, n, "tp");
      double tp = tp_s == "" ? 0.0 : StringToDouble(tp_s);
      bool any = false, all_ok = true;
      string msg = "";
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || !IsMine(t)) continue;
         any = true;
         if(InpDryRun) { PrintFormat("🧪 [dry-run] %s ticket=%I64u sl=%.2f tp=%.2f id=%s", op, t, sl, tp, id); continue; }
         bool ok = (op == "close") ? trade.PositionClose(t) : trade.PositionModify(t, sl, tp);
         all_ok = all_ok && ok;
         msg += trade.ResultRetcodeDescription() + ";";
         PrintFormat("%s %s ticket=%I64u → %s %s", ok ? "✅" : "❌", op, t, trade.ResultRetcodeDescription(), id);
      }
      if(!any) { Ack(id, false, 0, "no own position"); return; }
      Ack(id, all_ok, 0, InpDryRun ? "dry-run" : msg);
      return;
   }
   Print("⚠️ 未知指令：", op);
   Ack(id, false, 0, "unknown op");
}

//---------------------------------------------------------------- 事件
int OnInit()
{
   if(InpToken == "") { Print("❌ InpToken 未填"); return INIT_PARAMETERS_INCORRECT; }
   LoadSeen();
   EventSetTimer(InpIntervalSec);
   PrintFormat("🌌 天覆陣執行器啟動 symbol=%s magic=%I64d dry_run=%s", _Symbol, InpMagic, InpDryRun ? "true" : "false");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   string reply;
   if(!Post(BuildHeartbeat(), reply)) return;
   string cmds = ExtractCmdText(reply);
   if(cmds == "") return;
   if(InpDryRun)                                          // 資料源模式：連 Execute 都唔入，0 落單路徑
   {
      Print("🧪 [dry-run] 收到指令但唔執行：", cmds);
      return;
   }
   string lines[];
   int n = StringSplit(cmds, '\n', lines);
   for(int i = 0; i < n; i++)
   {
      string line = lines[i];
      StringTrimLeft(line); StringTrimRight(line);
      if(line != "") Execute(line);
   }
}
