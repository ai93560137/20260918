//+------------------------------------------------------------------+
//| 🌌 天覆陣執行器 TianfuExecutor.mq5  v0.3（2026-10-20，未編譯、未測）   |
//| v0.3：心跳加 account（登入號）／server／realized_total（自 InpLedgerStart）|
//|       服務用 XAU_ACCOUNT 分辨 demo／真戶口，只向該登入號發指令。          |
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
//|  · 只管 _Symbol ＋ magic 嘅倉（v0.36 按圖表商品自動）；唔平其他 magic   |
//|  · 回報嘅盈虧只計自己 magic（已實現今日＋浮動），唔用戶口淨值           |
//|  · 開倉一定帶伺服器端 SL（冇 SL 嘅 open 指令拒絕執行）                 |
//|  · cmd id 去重：用 GlobalVariable 記最近執行過嘅 id，重啟都唔重複      |
//|  · 唔做定時出場、唔做帳戶回撤熔斷（呢啲由 Cloud Run 決定）             |
//|  · 日誌唔印權杖同網址                                              |
//| 用法：MT5 → 工具 → 選項 → EA 交易 → 允許 WebRequest 加服務網址；    |
//|       先掛 demo 戶口；InpToken 填 Cloud Run 嘅 WEBHOOK_SECRET_TOKEN  |
//+------------------------------------------------------------------+
#property copyright "zhuge / 天覆陣"
#property version   "0.37"
#property strict
#include <Trade\Trade.mqh>

input string InpUrl        = "";        // Cloud Run 網址（結尾 /）；留空＝按圖表商品自動（XAUUSD→zhuge-xau、EURUSD→zhuge-eurusd…，v0.36 使用者 10-21）
input string InpToken      = "123456";  // WEBHOOK_SECRET_TOKEN（使用者 10-21 確認預設 123456；公開 repo，人人睇到，轉真倉前建議換私人權杖）
input long   InpMagic      = 0;         // 只管呢個 magic 嘅單；0＝按圖表商品自動（XAUUSD 921、EURUSD 922、GBPUSD 923、AUDUSD 924、USDJPY 925；V23 用 920）
input int    InpIntervalSec = 60;       // 心跳間隔（秒）
input int    InpTimeoutMs  = 15000;     // WebRequest 逾時
input int    InpSlippagePts = 50;       // 市價單允許滑點（點）
input double InpMaxLots    = 0.10;      // 單張上限（第二道鎖；Cloud Run 亦有 XAU_MAX_LOTS）
input bool   InpDryRun     = true;      // true = 只印指令唔落單（第一次掛先用）
input string InpLedgerStart = "2026.10.20"; // 自己 magic 累計已實現由呢日起計（realized_total）
input string InpBotMagics  = "921,922,923,924,925,931,932,933,934,935"; // 戶口總階梯（v0.35；v0.37 加訊號書 931–935）：天覆陣全部產品嘅 magic，心跳送合計日蝕／浮動／累計（唔計手動單同其他 EA）

CTrade   trade;
long     g_magic = 0;                    // v0.36：實際用嘅 magic（InpMagic 或按 _Symbol 自動）
string   g_url   = "";                   // v0.36：實際用嘅網址（InpUrl 或按 _Symbol 自動）

//---------------------------------------------------------------- v0.36 EA 參數跟圖表預設（使用者 10-21）
long AutoMagic()
{
   string s = _Symbol; StringToUpper(s);
   if(StringFind(s, "XAUUSD") == 0) return 921;
   if(StringFind(s, "EURUSD") == 0) return 922;
   if(StringFind(s, "GBPUSD") == 0) return 923;
   if(StringFind(s, "AUDUSD") == 0) return 924;
   if(StringFind(s, "USDJPY") == 0) return 925;
   return 929;                                                // 其他商品：同服務 config.PRODUCT 預設一致
}
string AutoUrl()
{
   string s = _Symbol; StringToUpper(s);
   string svc = (StringFind(s, "XAUUSD") == 0) ? "zhuge-xau" : "zhuge-" + StringSubstr(s, 0, 6);
   if(g_magic >= 931 && g_magic <= 935) svc += "-sig";       // v0.37 訊號書（InpMagic=931 就自動指去 zhuge-xau-sig）
   StringToLower(svc);
   return "https://" + svc + "-1056099871997.europe-west1.run.app/";
}
datetime g_last_m1 = 0;
bool     g_need_hist = true;            // 首個心跳回填 M1／M15 歷史；之後服務回 need_history:true 再送
string   g_seen_ids = "";               // 最近執行過嘅 id，以 | 分隔（亦存 GlobalVariable）
#define  SEEN_GV   "TIANFU_SEEN_IDS_"
#define  MAX_SEEN  40

//---------------------------------------------------------------- 工具
string P(double x) { return DoubleToString(x, _Digits); }   // v0.34：價格按商品小數位（XAUUSD 2、EURUSD 5），唔再寫死 %.2f
string JsonEsc(string s) { StringReplace(s, "\\", "\\\\"); StringReplace(s, "\"", "\\\""); return s; }

bool IsMine(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   if(PositionGetString(POSITION_SYMBOL) != _Symbol) return false;
   return PositionGetInteger(POSITION_MAGIC) == g_magic;
}

// v0.37：同一商品可以有兩張圖表（921 主服務＋931 訊號書），去重檔要按 magic 分開
string SeenFile() { return "tianfu_seen_" + _Symbol + "_" + IntegerToString(g_magic) + ".txt"; }

void LoadSeen()
{
   string gv = SEEN_GV + _Symbol;
   // GlobalVariable 只存 double，所以 id 清單用 chart 物件唔穩陣；改用檔案
   int h = FileOpen(SeenFile(), FILE_READ | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE) { g_seen_ids = FileReadString(h); FileClose(h); }
}

void SaveSeen()
{
   int h = FileOpen(SeenFile(), FILE_WRITE | FILE_TXT | FILE_ANSI);
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

// 自己 magic 嘅已實現盈虧（含佣金、隔夜利息），由 from 起
double OwnRealizedSince(datetime from)
{
   if(!HistorySelect(from, TimeCurrent())) return 0.0;
   double sum = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != g_magic) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN) continue;
      sum += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
   }
   return sum;
}

double OwnRealizedToday() { return OwnRealizedSince((datetime)(TimeCurrent() - TimeCurrent() % 86400)); }

// v0.35 戶口總階梯：天覆陣全部產品（InpBotMagics）嘅合計，任何商品
bool IsBotMagic(long magic)
{
   string parts[];
   int n = StringSplit(InpBotMagics, ',', parts);
   for(int i = 0; i < n; i++) { string t = parts[i]; StringTrimLeft(t); StringTrimRight(t); if(t != "" && StringToInteger(t) == magic) return true; }
   return false;
}
double BotsRealizedSince(datetime from)
{
   if(!HistorySelect(from, TimeCurrent())) return 0.0;
   double sum = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(!IsBotMagic(HistoryDealGetInteger(d, DEAL_MAGIC))) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN) continue;
      sum += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
   }
   return sum;
}
double BotsRealizedToday() { return BotsRealizedSince((datetime)(TimeCurrent() - TimeCurrent() % 86400)); }
double BotsRealizedTotal() { return BotsRealizedSince(StringToTime(InpLedgerStart)); }
double BotsFloating()
{
   double f = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if(!IsBotMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      f += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return f;
}
double OwnRealizedTotal() { return OwnRealizedSince(StringToTime(InpLedgerStart)); }

//---------------------------------------------------------------- 自動交易三個開關（終端掣／EA 屬性／戶口）
bool TerminalAT() { return (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED); }
bool EaAT()       { return (bool)MQLInfoInteger(MQL_TRADE_ALLOWED); }
bool AccountAT()  { return (bool)AccountInfoInteger(ACCOUNT_TRADE_EXPERT) && (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED); }
string TradeAllowedJson()
{
   return StringFormat("{\"terminal\":%s,\"ea\":%s,\"account\":%s}",
                       TerminalAT() ? "true" : "false", EaAT() ? "true" : "false", AccountAT() ? "true" : "false");
}
string TradeBlockedReason()      // "" = 三個都開
{
   string r = "";
   if(!TerminalAT()) r += "terminal Algo Trading off;";
   if(!EaAT())       r += "EA property Allow Algo Trading off;";
   if(!AccountAT())  r += "account trading not allowed;";
   return r;
}

//---------------------------------------------------------------- 歷史回填（v0.33）：330 根 M1＋60 根 M15，服務合併後即刻夠 20 根 M15
string BuildHist()
{
   MqlRates r1[], r15[];
   ArraySetAsSeries(r1, true); ArraySetAsSeries(r15, true);
   string s1 = "", s15 = "";
   int n1 = CopyRates(_Symbol, PERIOD_M1, 1, 330, r1);
   for(int i = n1 - 1; i >= 0; i--)
   {
      if(s1 != "") s1 += ",";
      s1 += StringFormat("[%I64d,%s,%s,%s,%s]", (long)r1[i].time, P(r1[i].open), P(r1[i].high), P(r1[i].low), P(r1[i].close));
   }
   int n15 = CopyRates(_Symbol, PERIOD_M15, 1, 60, r15);
   for(int i = n15 - 1; i >= 0; i--)
   {
      if(s15 != "") s15 += ",";
      s15 += StringFormat("[%I64d,%s,%s,%s,%s]", (long)r15[i].time, P(r15[i].open), P(r15[i].high), P(r15[i].low), P(r15[i].close));
   }
   PrintFormat("📚 回填歷史：M1 %d 根、M15 %d 根", n1, n15);
   return StringFormat(",\"m1_hist\":[%s],\"m15_hist\":[%s]", s1, s15);
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
      pos_json += StringFormat("{\"ticket\":%I64u,\"side\":\"%s\",\"lots\":%.2f,\"entry\":%s,\"sl\":%s,\"tp\":%s,\"open_time\":%I64d}",
                               t, type == POSITION_TYPE_BUY ? "BUY" : "SELL", v, P(PositionGetDouble(POSITION_PRICE_OPEN)),
                               P(PositionGetDouble(POSITION_SL)), P(PositionGetDouble(POSITION_TP)), (long)PositionGetInteger(POSITION_TIME));
   }
   MqlRates r1[], r15[];
   ArraySetAsSeries(r1, true); ArraySetAsSeries(r15, true);
   string m1 = "null", m15 = "null";
   if(CopyRates(_Symbol, PERIOD_M1, 1, 1, r1) > 0)
   {
      bool is_new = (r1[0].time != g_last_m1);
      if(is_new) g_last_m1 = r1[0].time;
      m1 = StringFormat("{\"symbol\":\"%s\",\"time\":%I64d,\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s,\"volume\":%I64d,\"is_new_bar\":%s}",
                        _Symbol, (long)r1[0].time, P(r1[0].open), P(r1[0].high), P(r1[0].low), P(r1[0].close), r1[0].tick_volume, is_new ? "true" : "false");
   }
   if(CopyRates(_Symbol, PERIOD_M15, 1, 1, r15) > 0)
      m15 = StringFormat("{\"time\":%I64d,\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s}",
                         (long)r15[0].time, P(r15[0].open), P(r15[0].high), P(r15[0].low), P(r15[0].close));
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   string hist = g_need_hist ? BuildHist() : "";
   return StringFormat(
      "{\"action\":\"heartbeat\",\"token\":\"%s\",\"ea\":\"TianfuExecutor/0.36\",\"account\":\"%I64d\",\"server\":\"%s\",\"symbol\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"credit\":%.2f,\"margin_level\":%.2f,\"floating\":%.2f,\"daily_pnl\":%.2f,\"realized_total\":%.2f,"
      "\"buy_lots\":%.2f,\"sell_lots\":%.2f,\"net_lots\":%.2f,\"magic\":%I64d,\"dry_run\":%s,\"server_time\":%I64d,\"trade_allowed\":%s,\"bots_daily_pnl\":%.2f,\"bots_floating\":%.2f,\"bots_realized_total\":%.2f,"
      "\"positions\":[%s],\"m1_ohlc\":%s,\"m15_ohlc\":%s%s}",
      JsonEsc(InpToken), (long)AccountInfoInteger(ACCOUNT_LOGIN), JsonEsc(AccountInfoString(ACCOUNT_SERVER)), _Symbol, cur,
      AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_CREDIT), AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), floating, OwnRealizedToday(), OwnRealizedTotal(),
      buy, sell, buy - sell, g_magic, InpDryRun ? "true" : "false", (long)TimeCurrent(), TradeAllowedJson(), BotsRealizedToday(), BotsFloating(), BotsRealizedTotal(), pos_json, m1, m15, hist);
}

//---------------------------------------------------------------- HTTP
bool Post(string body, string &reply)
{
   char data[], result[];
   string headers = "Content-Type: application/json\r\n", rh;
   int n = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(data, n - 1);
   ResetLastError();
   int code = WebRequest("POST", g_url, headers, InpTimeoutMs, data, result, rh);
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
void Reject(string id, string line, string msg)        // 使用者 10-20：所有拒絕／略過都要喺「專家」分頁有一行紀錄
{
   Print("❌ 拒絕指令：", msg, " ｜ ", line);
   Ack(id, false, 0, msg);
}

void Execute(string line)
{
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 2) { Print("❌ 指令格式錯，略過：", line); return; }
   string op = parts[0], id = Field(parts, n, "id");
   if(id == "") { Print("⚠️ 指令冇 id，略過：", line); return; }
   if(Seen(id)) { Print("↩️ 重複 id，已執行過，略過：", line); return; }   // 心跳重送
   long magic = (long)StringToInteger(Field(parts, n, "magic"));
   if(magic != g_magic) { MarkSeen(id); Reject(id, line, "magic mismatch"); return; }
   MarkSeen(id);                                          // 先記，再執行：寧可漏一次，唔好重複落單
   if(!InpDryRun && TradeBlockedReason() != "")           // 三個自動交易開關任何一個關，先回報原因，唔送單
   { Reject(id, line, "trade not allowed: " + TradeBlockedReason()); return; }
   trade.SetExpertMagicNumber(g_magic);
   trade.SetDeviationInPoints(InpSlippagePts);

   if(op == "open")
   {
      string side = parts[1];
      double lots = NormalizeDouble(StringToDouble(parts[2]), 2);
      double sl = StringToDouble(Field(parts, n, "sl"));
      string tp_s = Field(parts, n, "tp");
      double tp = tp_s == "" ? 0.0 : StringToDouble(tp_s);
      if(lots <= 0 || lots > InpMaxLots) { Reject(id, line, StringFormat("lots out of range (%.2f, max %.2f)", lots, InpMaxLots)); return; }
      if(sl <= 0) { Reject(id, line, "no SL"); return; }                       // 冇止損唔開
      // 只管一張：已有自己嘅倉就唔開
      for(int i = PositionsTotal() - 1; i >= 0; i--) { ulong t = PositionGetTicket(i); if(t != 0 && IsMine(t)) { Reject(id, line, StringFormat("already in position (ticket %I64u)", t)); return; } }
      if(InpDryRun) { PrintFormat("🧪 [dry-run] open %s %.2f sl=%s tp=%s id=%s", side, lots, P(sl), P(tp), id); Ack(id, true, 0, "dry-run"); return; }
      bool ok = (side == "BUY") ? trade.Buy(lots, _Symbol, 0.0, sl, tp, "天覆陣 " + id)
                                : trade.Sell(lots, _Symbol, 0.0, sl, tp, "天覆陣 " + id);
      ulong ticket = ok ? trade.ResultOrder() : 0;
      PrintFormat("%s open %s %.2f sl=%s tp=%s → %s %s", ok ? "✅" : "❌", side, lots, P(sl), P(tp), trade.ResultRetcodeDescription(), id);
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
         if(InpDryRun) { PrintFormat("🧪 [dry-run] %s ticket=%I64u sl=%s tp=%s id=%s", op, t, P(sl), P(tp), id); continue; }
         bool ok = (op == "close") ? trade.PositionClose(t) : trade.PositionModify(t, sl, tp);
         all_ok = all_ok && ok;
         msg += trade.ResultRetcodeDescription() + ";";
         PrintFormat("%s %s ticket=%I64u → %s %s", ok ? "✅" : "❌", op, t, trade.ResultRetcodeDescription(), id);
      }
      if(!any) { Reject(id, line, "no own position"); return; }
      Ack(id, all_ok, 0, InpDryRun ? "dry-run" : msg);
      return;
   }
   Reject(id, line, "unknown op " + op);
}

//---------------------------------------------------------------- 事件
int OnInit()
{
   if(InpToken == "") { Print("❌ InpToken 未填"); return INIT_PARAMETERS_INCORRECT; }
   g_magic = (InpMagic > 0) ? InpMagic : AutoMagic();           // 手填值覆蓋；0＝自動
   g_url   = (InpUrl != "") ? InpUrl : AutoUrl();
   if(StringSubstr(g_url, StringLen(g_url) - 1) != "/") g_url += "/";
   PrintFormat("🔧 參數：url=%s magic=%I64d（%s）", g_url, g_magic, (InpMagic > 0 || InpUrl != "") ? "手填" : "按圖表商品自動");
   LoadSeen();
   EventSetTimer(InpIntervalSec);
   PrintFormat("🌌 天覆陣執行器啟動 symbol=%s magic=%I64d dry_run=%s", _Symbol, g_magic, InpDryRun ? "true" : "false");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   string reply;
   if(!Post(BuildHeartbeat(), reply)) return;
   g_need_hist = (StringFind(reply, "\"need_history\":true") >= 0);   // 服務話 M15 唔夠先再回填
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
