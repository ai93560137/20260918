# =============================================================================
# 智能諸葛亮 AI 量化交易系統 — GCP Cloud Function (v12 rewrite)
# -----------------------------------------------------------------------------
# Rewrite of v11 that resolves logic-review findings R1–R67 (security still out
# of scope, as requested). Tags like [R4] mark where a finding is addressed.
#
# BEHAVIOUR CHANGES — read before deploying
#   * No dry-run mode: every approved signal is sent LIVE to the real account.
#   * Gate + trend state is ONE JSON document (regime, direction, armed,
#     hard lock, news lock) updated with GCS generation checks.      [R4 R9 R35]
#   * 2026-09-20 — 開閘依據改寫。三級共振第一次被量度（README §22/§23）：
#     修正 look-ahead 後 1~360 分鐘每個持倉長度的毛利 t 值都在 ±1.6 內，
#     延後一分鐘進場由 t=+5.28 掉到 −2.18，而 EA 每 60 秒才輪詢一次。
#     → 它退出開閘決策，只留在儀表板當雷達看。電閘改由五道風控關卡驅動：
#       市場時段 / 波動水位 / 空城計曝險上限 / 單日虧損 / 訓練節奏。
#       缺任何一項數據一律當成不過關（fail-closed）。   [R70 R72 R73]
#     GATE_DRIVER=REGIME 可一鍵回退成舊行為，只為了能並排比對。
#   * ⚠️ 但三級共振【沒有完全退場】：PureGCPPyramidingSession.evaluate_and_trigger
#     的第一行仍然讀 gate_state["dir"]，而那個 dir 是三級共振寫的。所以現在是：
#         armed（准不准下單）← 風控六關    ✅ 已量度
#         dir  （往哪個方向）← 三級共振    ❌ 未量度，且已證實無優勢
#     RANGE 時 dir = None，引擎直接 return None → 實際上 87.3% 的時間不會下單。
#     再加上 LONG_ONLY=1，等於「只在三級共振說 UP 的時候做多」。
#     → 進場規則本身仍然沒有任何回測支持。見 README §27。  [R77]
#   * LONG_ONLY 預設開啟：全期 1,464 筆中 671 筆空單每筆 −HK$0.84、
#     t = −0.25，八年半期望值為零，唯一作用是付點差。            [R71]
#   * 2026-09-20 — 進場引擎換成【錦囊 v4】（ENTRY_ENGINE=JINNANG）。   [R78]
#     舊的 PureGCPPyramidingSession 第一次被量度（README §28）：全期去掉最賺
#     5% → −HK$16,945、最大回撤 23.4%，而三級共振給的方向在配對檢驗下
#     t = +0.82（置換第 79.3 百分位）—— 不顯著。三級共振至此完全退場。
#     錦囊 v4：M15 區間突破 · 只做多 · ATR(14)÷價格 ≥ 0.10% · 抱 10 根 ·
#     無價格停損；出場由 EA 的 InpHoldMinutes = 150 分鐘定時全平。
#     TradingView 全期 513 筆（2018-03 → 2026-09）：年化 +2.47%、
#     最大回撤 5.72%。⚠️ 樣本外 −0.82%/年、異常值佔淨利 106% —— 未證實。
#     ENTRY_ENGINE=PYRAMID 可回退成舊引擎，只為了能並排比對。
#   * TARGET_HIT and manual LOCK are HARD locks that the state machine cannot
#     reopen. The dashboard "OPEN" button became "release hard lock / resume
#     auto"; the gate then reopens once the five risk checks pass.      [R10 R29]
#   * Position cap is risk-based: equity × RISK_PCT ÷ (SL distance × 100),
#     also capped by margin and HARD_MAX_LOTS.                              [R11]
#   * Entry rules are deterministic Python. The LLM is an optional reviewer
#     with ONE fail policy (AI_FAIL_OPEN, default = reject).        [R2 R5 R13 R14]
#   * Pyramid base price and pending SFT entries are written only after the
#     broker accepts the order.                                         [R3 R24f]
#   * News lock = ±30 min around High-impact USD events, from the FF JSON
#     feed (explicit UTC offsets). Unknown calendar blocks new entries.
#                                                                [R13e R16 R17]
#   * 2026-09-27 — [R94] action=futu_data 有了處理器：本地 Futu OpenD 推上來的
#     K 線與期權 IV 驗權杖後存進 futu/latest_snapshot.json，控制台顯示，
#     ?view=futu&format=json 可讀回。回 status "stored"，不再是 "ignored"。
#     只存、只顯示，不影響電閘與下單。
#   * 2026-09-27 — [R95] 外部來源按日封存：MT5 每根 M1、Futu 每次推送的 K 線與
#     期權 IV，存 archive/<source>/<instrument>/<日期>.json；?view=archive&format=json
#     &date=YYYY-MM-DD 讀回，給預設分支的每日彙整拉進 data/external/。
#     Futu 支援多代號（futu/snapshots/<代號>.json，?view=futu&format=json&symbol=）。
#   * 2026-09-27 — [R96] kline_type=K_DAY 的封包（本地腳本 v4 的每日日線抽樣，給數據
#     品質比對用）只按日封存，不覆蓋控制台與 ?view=futu 的即時快照。
#   * 2026-10-04 — [R97] 即月期貨（代號以 _FRONT 結尾，例 HK.HSI_FRONT）的「交易日 K」
#     （kline_type=K_SESSION，本地腳本 v7 合成：09:00 至翌日 09:00，日市＋當晚夜市算同一天）
#     按日封存並合併成一條序列 futu/daily/<代號>.json，不覆蓋即時快照；新頁面 ?view=futu_range
#     （&symbol=，預設 HK.HSI_FRONT）顯示過去一年每日波幅與最新 OHLC，&format=json 讀數據。
#     只存、只顯示，不影響下單。
#   * 2026-10-04 — [R98] 波幅頁加 HAR 波幅預測：當天預測與 80% 區間、逐日前推回測（誤差、區間命中率）、
#     圖上預測線；每個交易日第一包 K_SESSION 到達時把當天預測記到 futu/forecast/<代號>.json
#     （實時紀錄，事後對照）。只顯示，不影響下單。
#   * 2026-10-04 — [R99] 每個交易日四個時點：開市前預測當天波幅與高位／低位（ref ± 過去中位比例 × HAR 波幅），
#     12:00、16:30、03:00 檢討（由 5 分 K 封存按時間截取，排程晚到也不影響）。
#     ?view=futu_range&report=preopen|noon|close|night（&format=text）給 GitHub 排程發 Telegram；
#     檢討存 futu/reviews/<代號>.json；本地腳本送來的港股交易日曆存 futu/calendar/HK.json。只顯示，不影響下單。
#   * 2026-10-04 — [R100] 只有 5 分 K（或舊版沒標類型的封包）會更新即時快照；其他 K 線（日 K、交易日 K、
#     本地腳本 v9 匯出的 15／30／60 分 K 歷史）一律只按日封存，給「高低位是否已出現」的回測用。
#   * 2026-10-04 — [R101] 「今日／本週／本月的高位、低位已出現」三個策略（A 耗盡回落、B 機率法、C 時間點，
#     參數用回測最好那組）：每包即月期貨 5 分 K 到達時重算，任一策略第一次觸發就記到 futu/signals/<代號>.json，
#     ?view=futu_range&report=signals 給 GitHub 排程發 Telegram（&ack= 標記已發）；四次報告與波幅頁列出三個策略的現況。
#     回測見 research/hsi_futures_range/HIGH_LOW_IN_REPORT.md。只顯示，不影響下單。
#   * 2026-10-04 — [R102] 這套恒指即月期貨波幅系統在八陣登記為「風揚陣」（research/hsi_futures_range/FENGYANG.md）：
#     Telegram 訊息開頭加【風揚陣】，波幅頁標題與控制台連結加陣名。只改顯示文字。
#   * 2026-10-04 — [R103] 波幅頁改版給投資人看：今日／本週／本月三個區塊，各自顯示預測波幅（週、月 = 第一天
#     HAR × √交易日數 × 校準比例）、已走幾成、目前高低，以及 A／B／C 三個訊號的白話狀態；統計、明細表、說明收進下方。
#   * 2026-10-04 — [R104] 日／週／月過去每一次預測的誤差與命中率（逐日／逐段前推重算，日有實時紀錄就用紀錄）；
#     三張卡片各顯示過去 7 次預測與全部歷史的命中率，?view=futu_range&report=accuracy 給全部紀錄。
#   * 2026-10-04 — [R105] 今日／本週／本月卡片標題加日期（休市日今日卡改稱「下個交易日」）；每頁導覽列加「🌬️ 風揚陣波幅」。
#   * 2026-10-04 — [R106] 波幅頁加「💰 怎樣用來賺錢（四個方向）」：方向一比較恒指週期權價平 IV 與預測年化波幅、
#     方向二放盈虧回測結論（不賺錢，research/hsi_futures_range/MONEY_REPORT.md）、方向三四顯示今天的止蝕／倉位與波幅位置。
#   * 2026-10-04 — [R107] 方向一用 VHSI（HK.800125）合成回測：VHSI ÷ 預測 ≥ 1.2 時賣週期權有正回報（待真實報價校準）；
#     卡片即時顯示 VHSI ÷ 預測與是否達標（本地 FUTU_SYMBOLS 要加 HK.800125）。
#   * 2026-10-04 — [R108] 過去 7 次預測表加「預計範圍」；「80% 區間／命中」改成白話「預計範圍（十次有八次落在這裡）／落在範圍內」。
#   * 2026-10-04 — [R109] 今日卡的過去 7 次：改列預測高位／低位與預計範圍，高、低都落在範圍內才算 ✅（週、月照舊看波幅）。
#     另：方向二卡加一行「預先在預測高低位掛單、止蝕在範圍外」的回測結論（band_limit.py，每筆約 0）。
#   * 2026-10-04 — [R110] 方向二卡加「蛇蟠陣定方向＋預測位掛單」回測結論（snake_band.py，每筆 −12.5 點、RRR 0.90）。
#   * 2026-10-04 — [R111] 方向二卡加「跟蛇持倉多日＋週範圍止蝕」20 組回測結論（snake_week.py，附逐筆紀錄與獨立核對）。
#   * 2026-10-04 — [R112] 方向二卡加「日範圍止蝕」20 組回測結論（snake_week.py --stop day）。
#   * 2026-10-04 — [R113] 方向二卡加「預測高低位都出現後入・1:2 RRR」回測結論（hl_both.py）。
#   * 2026-10-04 — [R114] 方向二卡加訊號版（高位／低位已出現都亮後入・1:2 RRR）回測結論（hl_signal.py）。
#   * 2026-10-04 — [R115] 方向二卡加 R 測試結論（r_sweep.py，Futu＋HK50 差價合約）。
#   * 2026-10-04 — [R116] 📒 紙上交易：回測挑出的三條策略（🐍 蛇蟠陣、🅱️＋跟蛇＋3R、🅰️＋跟蛇＋2R）跟實時 5 分 K 走，
#     每包 K 線到達時記入市／出場，狀態與逐筆紀錄存 futu/paper/<代號>.json，通知經 report=signals 一起發 Telegram；
#     波幅頁加「📒 紙上交易」區，?view=futu_range&report=paper 給統計與逐筆；開市前預測多記九成日範圍邊（edge95）。
#     只是紙上紀錄，不接下單。
#   * 2026-10-04 — [R117] 方向一卡改用真實數據結論（港交所週／月期權結算價與 IV，research/hsi_futures_range/vrp_real.py）。只改顯示文字。
#   * 2026-10-04 — [R118] 📒 紙上交易加「波幅開閘」：今日 R̂ ÷ 過去 250 日 R̂ 中位 ≥ 1.2 就開閘，開閘日入市記 2 張、其餘 1 張，
#     固定 1 張與開閘雙倍兩條並記（research/hsi_futures_range/vol_gate.py：🅱️／🅰️ 的利潤集中在開閘日入市的交易，蛇沒有）。開市前預測多記
#     rhat_med250／gate_ratio／gate_open；預測、四次報告、入市通知與波幅頁都顯示今日開閘與否。
#   * 2026-10-05 — [R119] 預測高位／低位的「預計範圍」由 80%（10%／90% 分位）改為 96%（2%／98% 分位，HL_BAND_Q）：
#     逐日前推 558 天，高、低各自命中 96%、兩邊同時 92%（原本 80%／67%），平均範圍由 494 點擴到 849 點。
#     開市前紀錄多記 band_q；舊紀錄（80% 範圍）在準繩統計裡改用逐日前推重算，令全部歷史同一口徑。全日波幅的預計範圍不變（80%）。
#   * 2026-10-06 — [R128] 收市後、下一個交易日未開（恒指 03:00–09:00）：波幅頁改顯示下一個交易日的開市前預測，最新交易日標「已完結」、
#     狀態「休市／未開市」（之前要到 09:00 才換日，07:53 記下的預測在頁上看不到，而且推送仍在所以誤標「交易中」）。
#   * 2026-10-05 — [R127] 🇺🇸 ES 波幅頁（?view=es_range，代號 US.ES_FRONT）：與風揚陣恒指頁同一套程式，加「市場設定」（MARKETS）——
#     美股用紐約時間、交易日 = CME 全段（前一天 18:00 至 17:00，日期取收市那天）、不用港股日曆、開市前紀錄時段 18:00–19:00 ET。
#     數據由 GitHub Actions（es_daily_push.yml，yfinance ES=F 日線）以 K_SESSION 封包每日推入；沒有 5 分 K，所以沒有日內訊號、
#     紙上交易與四個方向（頁上註明）。所有頁頂連結加「🇺🇸 ES 波幅」。
#   * 2026-10-05 — [R126] ✓ 的門檻按時間長度分：今日 1%、本週 2%、本月 4%（HL_OK_PCT_BY；誤差約與交易日數的平方根成正比，
#     真實數據高位誤差中位日 0.52%、週 1.2%、月 2.1%；用這三個門檻，高低都在門檻內的比率日 65%、週 60%、月 59%）。
#   * 2026-10-05 — [R125] 過去 7 次表：實際高／低下面的差距加百分比（差距 ÷ 預測）；綠字 ✓ 改為「相差 1% 以內」才給，
#     超過 1% 紅字（↑ 實際較高、↓ 較低）；統計行加「高、低都在 1% 內」的比率（HL_OK_PCT）。預計範圍與落在範圍的統計不變。
#   * 2026-10-05 — [R124] 本週／本月卡加「🔄 最新預測」（邊走邊改）：已出現的高／低 ＋ 剩餘日子的預測（今日 R̂ × √剩餘日數 × 過去比例），
#     比例用過去各段每一天的「（之後的高 − 當日收）÷ 剩餘預測」逐段前推校準；段首的原始預測照舊留在表裡計分。
#     更新後範圍的分位 ROLL_BAND_Q（週 2%、月 5%）。真實數據（逐段前推，走到一半時評分）：週範圍寬 2,114 → 867 點、高低都中 97%；
#     月 4,082 → 1,647 點、96%；高位平均差週 159 點、月 193 點。
#   * 2026-10-05 — [R123] 本週／本月的高位／低位預計範圍再擴闊：分位由 2% 改 1%（HL_BAND_Q_PERIOD）。逐段前推：週兩邊同時 87% → 89%
#     （高 95%、低 92%，平均範圍寬 1,666 → 2,114 點）；月 73% → 82%（只有 22 段，1% 分位等於歷史極值）。今日不變（2%）。
#     注意：擴闊範圍只提高「落在範圍內」的比率，不會縮小實際與預測的差距（週高位平均差 365 點、月 807 點是預測本身的誤差）。
#   * 2026-10-05 — [R122] 過去 7 次表：實際高／實際低下面多一行「實際 − 預測」的差距，實際比預測高 → 綠字、低 → 紅字（日、週、月）。
#   * 2026-10-05 — [R121] 過去 7 次表：實際高／實際低落在範圍內 → 綠字加 ✓，跑出範圍照舊紅字加 ↑／↓；拿走「結果」欄（日、週、月）。
#   * 2026-10-05 — [R120] 本週／本月卡與今日卡同一套項目：加預測高位／低位與預計範圍（週、月的（高−段首昨收）÷R、（段首昨收−低）÷R
#     比例逐段前推校準，PERIOD_CAL_MIN 段後才評分），過去 7 次表同樣列預測高／實際高／預測低／實際低，✅ = 兩邊都落在範圍。
#   * New GCS objects (legacy files are left untouched):
#       zhuge_gate_state.json, pyramid_state.json, gcp_decision_log.json,
#       ai_training/pending_signals_v2.json, cache/ff_calendar_thisweek.json
# =============================================================================
import bisect
import hashlib
import html
import json
import math
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import functions_framework
import requests
from flask import jsonify, redirect
from google import genai
from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage
from google.genai import types


# =============================================================================
# ⚙️ Configuration (all overridable with environment variables)
# =============================================================================
def _env_str(name, default):
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Auth (unchanged; security out of scope) ---------------------------------
GCP_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "123456")

# --- Execution ----------------------------------------------------------------
ORDER_SIZE = _env_float("ORDER_SIZE", 0.01)
# [R82] 這個 URL 的 ?t=... 是你個人的接收端權杖 —— 跟 api_key 一樣算憑證，
#       原本寫死在這裡，而這個 repo 是【公開】的。改成環境變數，沒設就不送單。
BROKER_API_URL = _env_str("BROKER_API_URL", "")
BROKER_TIMEOUT_SEC = _env_int("BROKER_TIMEOUT_SEC", 8)            # keep total request < EA WebRequest timeout
# [R83] 券商的商品名要一字不差（UltimaMarkets 可能是 XAUUSD 或 XAUUSD+）。
#       送錯名字會被拒單，或更糟 —— 成交在另一個商品上。
#       不靠人記：EA 的心跳裡帶著圖表商品名（m1_ohlc.symbol），
#       GCP 會拿它跟這個值比對，不一樣就在 Log 與儀表板上示警。見 broker_symbol_mismatch()。
ORDER_SYMBOL = _env_str("ORDER_SYMBOL", "XAUUSD")                    # 必須與券商商品列表完全一致
ORDER_ACCOUNT = _env_str("ORDER_ACCOUNT", "1")                       # webhooktrade 範本的 account 欄位
# webhooktrade 有兩組距離欄位，單位不同，只能擇一送出：
#   price  → sl_distance_price / tp_distance_price / ts_activation_price / …   值＝美元（13.00）
#   points → sl_distance       / tp_distance       / ts_activation       / …   值＝點數（1300）
DISTANCE_UNIT = _env_str("DISTANCE_UNIT", "price").lower()
POINTS_PER_UNIT = _env_float("POINTS_PER_UNIT", 100.0)               # XAUUSD 兩位小數：1 美元 = 100 點

DISTANCE_FIELDS = {
    "price": {"sl": "sl_distance_price", "tp": "tp_distance_price", "ts_activation": "ts_activation_price",
              "ts_distance": "ts_distance_price", "breakeven": "breakeven_distance_price"},
    "points": {"sl": "sl_distance", "tp": "tp_distance", "ts_activation": "ts_activation",
               "ts_distance": "ts_distance", "breakeven": "breakeven_distance"},
}


def distance_fields(params):
    return DISTANCE_FIELDS.get(params.get("distance_unit"), DISTANCE_FIELDS["price"])
ORDER_SETTLE_SEC = _env_int("ORDER_SETTLE_SEC", 180)                  # [R12c R25]
LOCKED_HTTP_STATUS = _env_int("LOCKED_HTTP_STATUS", 403)              # [R63] 403 kept for EA compatibility

ORDER_TEMPLATE = {
    "username": "Webhook8",
    # [R82] 絕對不要在這裡放預設值 —— 這個 repo 是【公開】的。
    #       原本寫死的那把金鑰已經在 GitHub 上公開過，必須視為外洩，請重新產生。
    #       沒設 WEBHOOK_API_KEY 時留空，送單會被券商拒絕（fail-closed），
    #       比帶著一把公開過的金鑰去下單安全。
    "api_key": os.environ.get("WEBHOOK_API_KEY", ""),
    "broker": "metatrader",
    "account_type": "real",
    "symbol": ORDER_SYMBOL,
    "action": "PENDING",
    "size": f"{ORDER_SIZE:.2f}",
    "strategy": "GCP",
    "comment": "1M BOS GCP AI",
}

# Exit parameters are passed to the bridge as-is. Units/semantics depend on
# webhooktrade — verify them against its documentation before going live. [R33]
# 2026-01→09 的回測：任何一組移動止損設定都把獲利因子從 1.31 壓到 0.58–0.89
# （勝率上升但大單被提前砍掉）。預設關閉；設成大於 0 才會送出對應欄位。
TS_ACTIVATION_PRICE = _env_str("TS_ACTIVATION_PRICE", "0")
TS_DISTANCE_PRICE = _env_str("TS_DISTANCE_PRICE", "0")
BREAKEVEN_DISTANCE_PRICE = _env_str("BREAKEVEN_DISTANCE_PRICE", "0")
BREAKEVEN_PROFIT = _env_str("BREAKEVEN_PROFIT", "30")

# --- Risk -----------------------------------------------------------------------
CONTRACT_SIZE = 100.0                                                 # XAUUSD: 1 lot = 100 oz
ACCOUNT_CURRENCY_DEFAULT = _env_str("ACCOUNT_CURRENCY", "HKD")
FX_TO_USD = {"USD": 1.0, "HKD": 1.0 / 7.8}                            # [R11c]
ACCOUNT_TO_USD_RATE = _env_float("ACCOUNT_TO_USD_RATE", 0.0)           # used for any other currency
RISK_PCT = _env_float("RISK_PCT", 0.02)                               # [R11] risk of full pyramid at SL
BROKER_LEVERAGE = _env_float("BROKER_LEVERAGE", 500.0)                # [R11d] set your REAL leverage
MAX_MARGIN_PCT = _env_float("MAX_MARGIN_PCT", 0.20)
HARD_MAX_LOTS = _env_float("HARD_MAX_LOTS", 1.00)
MIN_SL_DISTANCE = _env_float("MIN_SL_DISTANCE", 6.0)
SL_ATR_MULT = _env_float("SL_ATR_MULT", 1.5)
# 2026-01→09 的 8.5 個月 M1 回測顯示 3R 在樣本內外都優於 2R（勝率低、獲利來自少數大單）。
# 可用環境變數覆寫，或在送單參數頁即時調整（覆寫檔優先於這個預設值）。
TARGET_RRR = _env_float("TARGET_RRR", 3.0)                            # [R15] fixed, no feedback loop
ADD_SPACING_ATR = _env_float("ADD_SPACING_ATR", 0.5)
REENTRY_COOLDOWN_SEC = _env_int("REENTRY_COOLDOWN_SEC", 300)          # [R25b]
FIRST_ENTRY_MODE = _env_str("FIRST_ENTRY_MODE", "BREAKOUT").upper()   # BREAKOUT | MID   [R5]
M15_CLOSE_POSITION_MIN = _env_float("M15_CLOSE_POSITION_MIN", 0.7)    # [R5c]
RSI_BUY_MAX = _env_float("RSI_BUY_MAX", 85.0)
RSI_SELL_MIN = _env_float("RSI_SELL_MIN", 15.0)
BREAKEVEN_EPS = _env_float("BREAKEVEN_EPS", 1.0)                      # [R24c] |profit| <= this = break-even
STATS_WINDOW = _env_int("STATS_WINDOW", 100)
# [R42] MT5 伺服器時間 − UTC。BACKTEST.md 實測本券商為 UTC+3（夏令），回測指令
# 一路用 --broker-offset 3；設錯會讓 pair_trade_result() 配到錯的進場訊號。
# 夏令時結束後券商可能變 UTC+2，屆時用環境變數覆寫。
BROKER_UTC_OFFSET_HOURS = _env_float("BROKER_UTC_OFFSET_HOURS", 3.0)

# --- M1 regime radar -----------------------------------------------------------
MIN_M1_BARS = _env_int("MIN_M1_BARS", 65)                             # [R47] 60-min window + margin
M1_HISTORY_MAX = 200
M1_GAP_RESET_SEC = _env_int("M1_GAP_RESET_SEC", 15 * 60)              # [R21]
NOISE_K = _env_float("NOISE_K", 1.0)                                  # [R31] threshold = K·σ·√minutes

# --- 🛡️ 風控電閘（取代三級共振做開閘決策）-------------------------------------
# [R70] 2026-09-20：三級共振第一次被量度（README §22/§23）。修正 look-ahead 後，
#       1~360 分鐘每個持倉長度的毛利 t 值都在 ±1.6 內，而且延後一分鐘進場就由
#       +5.28 掉到 −2.18。EA 每 60 秒才輪詢一次，這個架構本來就接不住這種訊號。
#       → 三級共振改為「僅供觀察」，不再參與開閘。電閘改由風控條件驅動。
GATE_DRIVER = _env_str("GATE_DRIVER", "RISK").upper()                 # RISK | REGIME（舊行為，僅供回退）
LONG_ONLY = _env_bool("LONG_ONLY", True)                              # [R71] 全期 671 筆空單 t=−0.25
DD_TOLERANCE_PCT = _env_float("DD_TOLERANCE_PCT", 20.0)               # 可承受回撤（空城計基準）
# [R81] 這個數字要對應【持倉長度】，不是隨便抄一個「黃金最壞單日」。
#       錦囊抱 10 根 M15 = 150 分鐘。全歷史 13,696 個 10 根窗口的實測逆行：
#           最壞 7.55%　99.9 百分位 3.79%　（對照：最壞單日 9.60%、最壞日內 13.94%）
#       取 7.6 = 實測最壞，不是估的。
#       為什麼不能用 10 或 14：1 盎司在 HK$20,000、金價 4,378 是 1.68x 曝險，
#       而 可用曝險 = (20% − 回撤) ÷ gap。代進去：
#           gap=14% → 回撤 0.0% 就鎖死（一開始就不能下單）
#           gap=10% → 回撤 2.5%（HK$500 ＝ 1.4 次最壞虧損）就鎖死
#           gap=7.6%→ 回撤 6.2%（HK$1,240 ＝ 3.4 次最壞虧損）才鎖死
#       用 TradingView 全期 513 筆重播：gap=10 擋掉 6 筆，gap=7.6 一筆都不擋。
WORST_GAP_PCT = _env_float("WORST_GAP_PCT", 7.6)
EXPOSURE_HARD_CAP = _env_float("EXPOSURE_HARD_CAP", 2.0)
# [R90] 高水位是用哪一把尺量的。R88 把風控淨值從「淨值」改成「淨值 − 信用」之後，
#       舊的高水位（含信用）跟新的淨值不能比 —— 差額是信用，不是虧損，卻會被
#       讀成一筆從未發生的回撤，把空城計鎖死。換尺就重新起算。
EQUITY_PEAK_BASIS = "risk_equity_v2"

# [R93] 回撤煞車。曝險公式限制的是【單次槓桿】，擋不住【連續小額停損的累積】——
#       README §28 的金字塔回測 1,111 次停損 × 約 HK$94 就吃掉 23.4% 回撤，
#       超過整套空城計建立在上面的 20% 容忍。所以要一條直接對累積回撤的閘。
#       達到門檻就停當日新單（紐約日界線換日後重評）。0 = 停用。
DD_BRAKE_PCT = _env_float("DD_BRAKE_PCT", 15.0)              # 曝險硬上限（名目 ÷ 淨值）
DAILY_LOSS_LIMIT_PCT = _env_float("DAILY_LOSS_LIMIT_PCT", 3.0)        # 單日虧損上限（佔淨值）
# [R72] 波動門檻用 EA 已經在傳的 atr_m15。校準見 README §24：只做多、抱 10 根、
#       扣 US$0.40 來回時，打平點是 ATR(14)/價格 = 0.0837%。預設取 0.10%（打平點
#       之上、非最佳化值）。設 0 可停用。
VOL_FLOOR_ATR_PCT = _env_float("VOL_FLOOR_ATR_PCT", 0.10)
TRAINING_MAX_PER_DAY = _env_int("TRAINING_MAX_PER_DAY", 2)            # 90 筆訓練的節奏；0 = 不限

# --- 🎯 進場引擎：錦囊 v4 ---------------------------------------------------
# [R78] 2026-09-20：舊的 PureGCPPyramidingSession（結構／K 線／RSI／加單間距）
#       第一次被量度（README §28）：全期去掉最賺 5% → −HK$16,945，最大回撤 23.4%，
#       而三級共振給的方向在配對檢驗下 t = +0.82（置換第 79.3 百分位）—— 不顯著。
#       錦囊 v4 至少有 8.46 年、513 筆的 TradingView 實測：年化 +2.47%、
#       最大回撤 5.72%、樣本外 −0.82%/年。兩個都未證實，但後者量過、前者沒有。
ENTRY_ENGINE = _env_str("ENTRY_ENGINE", "JINNANG").upper()            # JINNANG | PYRAMID（舊，保留回退）
JN_LEN_TREND      = _env_int("JN_LEN_TREND", 60)                      # 八陣圖 M15 原廠值，以下同
JN_R2_MIN         = _env_float("JN_R2_MIN", 0.48)
JN_SLOPE_MIN      = _env_float("JN_SLOPE_MIN", 0.025)
JN_LEN_RANGE      = _env_int("JN_LEN_RANGE", 20)
JN_RANGE_MAX_ATR  = _env_float("JN_RANGE_MAX_ATR", 3.8)
JN_RANGE_MIN_BARS = _env_int("JN_RANGE_MIN_BARS", 8)
JN_BOX_MAX_AGE    = _env_int("JN_BOX_MAX_AGE", 30)
JN_BUF_ATR        = _env_float("JN_BUF_ATR", 0.25)
JN_CONFIRM_BARS   = _env_int("JN_CONFIRM_BARS", 1)
JN_ATR_LEN        = _env_int("JN_ATR_LEN", 14)
JN_HOLD_BARS      = _env_int("JN_HOLD_BARS", 10)                      # 10 根 M15 = 150 分鐘＝EA 的 InpHoldMinutes
# 錦囊沒有價格停損 —— 出場是 EA 的定時。這裡送的是【災難停損】，正常碰不到。
JN_DISASTER_SL_ATR = _env_float("JN_DISASTER_SL_ATR", 8.0)
# [R79] 倉位大小不能照災難停損算。calculate_max_lots 的 2% 風險模型假設
#       「止損就是出場點」，但錦囊是時間出場、根本沒有價格停損。
#       用 ATR×8 去算，在金價 4,300 附近會算出 0.00 手 —— 系統會安靜地永遠不下單。
#       正確的基準是【這條規則實測的最壞單筆虧損】：8.46 年 276 筆裡
#       最壞的一筆是進場價的 −1.097%（US$46.45/oz = HK$362 = 戶口的 1.81%）。
#       取 1.10% 當倉位計算距離 —— 意思是「最壞的一筆剛好等於 RISK_PCT」。
#       （最大逆行 MAE 最壞 1.638%，但那沒有造成虧損：沒有停損就不會被掃掉。）
JN_SIZING_ADVERSE_PCT = _env_float("JN_SIZING_ADVERSE_PCT", 1.10)
JN_MIN_BARS       = _env_int("JN_MIN_BARS", 100)                      # 判定前要累積多少根已收盤 M15
# [R80] EA 送的 m15_ohlc 是「已收盤」還是「正在形成」的那一根？
#       RiskManager V22/V23 用的是 CopyRates(symbol, PERIOD_M15, 1, 1, ...) —— shift=1，
#       也就是【最後一根已收盤】的 K 線。所以整份 M15 歷史都是收盤資料，
#       判定時要用 history 全部，不能再砍掉最後一根（砍了會晚 15 分鐘進場）。
#       若之後換成會送 shift=0（正在形成）的 EA，把這個設成 0，程式會自動丟掉最後一根。
JN_M15_LAST_CLOSED = _env_bool("JN_M15_LAST_CLOSED", True)

# --- News -----------------------------------------------------------------------
NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"  # [R17] ISO dates with UTC offset
NEWS_LOCK_BEFORE_MIN = _env_int("NEWS_LOCK_BEFORE_MIN", 30)           # [R16]
NEWS_LOCK_AFTER_MIN = _env_int("NEWS_LOCK_AFTER_MIN", 30)
NEWS_LOCK_IMPACTS = {s.strip() for s in _env_str("NEWS_LOCK_IMPACTS", "High").split(",") if s.strip()}
NEWS_CACHE_TTL_SEC = 900
NEWS_FAIL_BACKOFF_SEC = 300                                           # [R53]
NEWS_MAX_STALE_SEC = 12 * 3600
NEWS_FAIL_CLOSED = _env_bool("NEWS_FAIL_CLOSED", True)                # [R13e]

# --- AI reviewer ---------------------------------------------------------------
AI_REVIEW_ENABLED = _env_bool("AI_REVIEW_ENABLED", True)
AI_FAIL_OPEN = _env_bool("AI_FAIL_OPEN", False)                       # [R2 R13f R13g] one policy
AI_SHADOW_MODE = _env_bool("AI_SHADOW_MODE", False)                   # 覆核照跑、判斷照記，但不否決訊號
FEW_SHOT_LIMIT = _env_int("FEW_SHOT_LIMIT", 3)                        # [R6] 動態 few-shot 取幾條虧損教訓
AI_MODEL = _env_str("AI_MODEL", "gemini-2.5-flash")
AI_LOCATION = _env_str("AI_LOCATION", "us-central1")
AI_THINKING_BUDGET = _env_int("AI_THINKING_BUDGET", 0)                # [R14] 0 = no thinking (Flash only)

# --- Storage ---------------------------------------------------------------------
BUCKET_NAME = "zhuge-risk-manager-bucket"
ACCOUNT_FILE = "mt5_account_snapshot.txt"
GATE_STATE_FILE = "zhuge_gate_state.json"
PYRAMID_STATE_FILE = "pyramid_state.json"
DECISION_LOG_FILE = "gcp_decision_log.json"
M1_VERDICT_LOG_FILE = "m1_ai_verdict.txt"
M1_HISTORY_FILE = "m1_history/XAUUSD_M1.json"
M15_HISTORY_FILE = "m15_history/XAUUSD_M15.json"
TRADE_HISTORY_FILE = "risk_management/trade_history.jsonl"
SFT_DATASET_FILE = "ai_training/sft_dataset.jsonl"
TRADING_RULES_FILE = "ai_training/trading_rules.txt"
PENDING_SIGNALS_FILE = "ai_training/pending_signals_v2.json"
WEBHOOK_LOG_FILE = "logs/latest_webhook_payload.json"
NEWS_CACHE_FILE = "cache/ff_calendar_thisweek.json"

DECISION_LOG_MAX = 50
SFT_MAX_LINES = 2000                                                  # [R6c]
PENDING_TTL_SEC = 7 * 86400                                           # [R24]
PENDING_MAX = 300

UTC = timezone.utc
NY_TZ = ZoneInfo("America/New_York")

REGIME_RANGE = "RANGE"
REGIME_SETUP = "SETUP"
REGIME_TREND = "TREND"
REGIME_PAUSE = "PAUSE"      # verdict only
REGIME_NODATA = "NODATA"    # verdict only

DIR_WORD = {"UP": "多頭", "DOWN": "空頭"}
CANDLE_WORD = {"BULL": "收陽", "BEAR": "收陰", "DOJI": "收十字"}


# =============================================================================
# 🧰 Utilities
# =============================================================================
def now_ts():
    return time.time()


def fmt_utc(ts=None, fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.fromtimestamp(now_ts() if ts is None else ts, UTC).strftime(fmt)


def fmt_ny(ts):
    return datetime.fromtimestamp(ts, NY_TZ).strftime("%m-%d %H:%M 紐約")


def to_float(value, default=None):
    """Safe float parse: None/''/'N/A'/NaN/bool -> default.  [R23]"""
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def esc(value):
    return html.escape("" if value is None else str(value))


def fmt_num(value, spec="{:,.2f}"):
    number = to_float(value)
    return "—" if number is None else spec.format(number)


def countdown_text(seconds):
    seconds = int(abs(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} 天 {hours} 小時"
    if hours:
        return f"{hours} 小時 {minutes} 分鐘"
    return f"{minutes} 分鐘"


def normalize_symbol(symbol):
    """'XAUUSD.m', 'XAUUSDm', 'GOLD#' -> 'XAUUSD'.  [R24d]"""
    text = str(symbol or "").strip().upper()
    for sep in ".#-_ ":
        text = text.split(sep)[0]
    if text.startswith("XAUUSD") or text.startswith("GOLD"):
        return "XAUUSD"
    return text


def next_ny_rollover_ts(now=None):
    """Next 17:00 New York (gold daily rollover)."""
    ny_now = datetime.fromtimestamp(now_ts() if now is None else now, NY_TZ)
    target = ny_now.replace(hour=17, minute=0, second=0, microsecond=0)
    if ny_now >= target:
        target += timedelta(days=1)
    return target.timestamp()


def _startup_warnings():
    if not str(BROKER_API_URL or "").strip():
        print("🚨 [設定缺失] BROKER_API_URL 未設定 —— 不會送出任何訂單。"
              "請在環境變數裡設好完整網址（含 ?t=... 權杖）。[R82]", flush=True)
    if not str(ORDER_TEMPLATE.get("api_key") or "").strip():
        print("🚨 [設定缺失] WEBHOOK_API_KEY 未設定 —— 送單一定會被券商拒絕。"
              "請在 Cloud Function 的環境變數裡設好（不要寫進原始碼，這個 repo 是公開的）。[R82]",
              flush=True)
    print(f"⚙️ [啟動] 🔴 實盤下單模式 (account_type={ORDER_TEMPLATE['account_type']}) | "
          f"RISK_PCT={RISK_PCT} | LEVERAGE={BROKER_LEVERAGE} | FIRST_ENTRY_MODE={FIRST_ENTRY_MODE}", flush=True)
    activation, distance = to_float(TS_ACTIVATION_PRICE, 0.0), to_float(TS_DISTANCE_PRICE, 0.0)
    if activation <= 0 or distance <= 0:
        print("ℹ️ [出場參數] 移動止損已停用（TS_ACTIVATION / TS_DISTANCE = 0，封包不會帶這兩個欄位）", flush=True)
    if activation > 0 and distance > 0 and distance > activation:
        print(f"⚠️ [出場參數] TS_DISTANCE ({distance}) > TS_ACTIVATION ({activation})：啟動移動止損時止損可能仍在進場價之下，"
              f"請確認 webhooktrade 語義。[R33]", flush=True)
    _fields = DISTANCE_FIELDS.get(DISTANCE_UNIT, DISTANCE_FIELDS["price"])
    print(f"ℹ️ [送單欄位] 距離單位={DISTANCE_UNIT} → 送出 {_fields['sl']} / {_fields['tp']} 等欄位"
          f"（{'美元' if DISTANCE_UNIT != 'points' else '點數'}）", flush=True)
    if FIRST_ENTRY_MODE not in ("BREAKOUT", "MID"):
        print(f"⚠️ [設定] FIRST_ENTRY_MODE={FIRST_ENTRY_MODE} 無效，將視為 BREAKOUT。", flush=True)


_startup_warnings()


# =============================================================================
# 💾 GCS layer — every read-modify-write is generation-checked  [R35 R36 R50]
# =============================================================================
class StorageError(Exception):
    pass


_storage_client = None
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"


def _bucket():
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client.bucket(BUCKET_NAME)


def gcs_read_text(name):
    """Return the object's text, None if it does not exist. Raises StorageError."""
    try:
        blob = _bucket().get_blob(name)
        if blob is None:
            return None
        return blob.download_as_bytes().decode("utf-8")
    except NotFound:
        return None
    except Exception as exc:
        raise StorageError(f"read {name}: {exc}") from exc


def gcs_read_json(name, default):
    text = gcs_read_text(name)
    if text is None or not text.strip():
        return default
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StorageError(f"corrupt JSON in {name}: {exc}") from exc


def gcs_write_text(name, text):
    try:
        _bucket().blob(name).upload_from_string(text, content_type=TEXT_CONTENT_TYPE)
    except Exception as exc:
        raise StorageError(f"write {name}: {exc}") from exc


def jsonl_loads(text):
    rows, bad = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            bad += 1
    if bad:
        print(f"⚠️ [JSONL] 略過 {bad} 行損毀資料", flush=True)
    return rows


def jsonl_dumps(rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _backoff(attempt):
    time.sleep(random.uniform(0.05, 0.2) * (1.5 ** attempt))


def _load_for_update(name, loads, default_factory, reset_on_corrupt):
    blob = _bucket().get_blob(name)
    if blob is None:
        return 0, default_factory()
    generation = blob.generation
    raw = blob.download_as_bytes(if_generation_match=generation).decode("utf-8")
    if not raw.strip():
        return generation, default_factory()
    try:
        return generation, loads(raw)
    except ValueError as exc:
        if not reset_on_corrupt:
            raise StorageError(f"corrupt data in {name}: {exc}") from exc
        print(f"⚠️ [GCS] {name} 內容損毀，已重設為預設值: {exc}", flush=True)   # [R40]
        return generation, default_factory()


def gcs_update(name, mutate, *, loads=json.loads, dumps=None, default_factory=dict,
               reset_on_corrupt=False, attempts=10):
    """Atomic read-modify-write.

    mutate(data) -> (new_data, result). Return new_data=None to skip the write.
    mutate may run several times (on conflicts), so it must not have side effects.
    Raises StorageError if the object cannot be read or written.
    """
    dumps = dumps or (lambda data: json.dumps(data, ensure_ascii=False))
    for attempt in range(attempts):
        try:
            generation, data = _load_for_update(name, loads, default_factory, reset_on_corrupt)
        except (PreconditionFailed, NotFound):
            _backoff(attempt)
            continue
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"read {name}: {exc}") from exc

        new_data, result = mutate(data)
        if new_data is None:
            return result
        try:
            _bucket().blob(name).upload_from_string(
                dumps(new_data), if_generation_match=generation, content_type=TEXT_CONTENT_TYPE)
            return result
        except PreconditionFailed:
            _backoff(attempt)
        except Exception as exc:
            raise StorageError(f"write {name}: {exc}") from exc
    raise StorageError(f"update {name}: gave up after {attempts} concurrent-write retries")


# =============================================================================
# 📝 Decision log (keyed de-duplication)  [R37 R38 R59 R64]
# =============================================================================
def log_decision(message, key=None):
    """Consecutive entries with the same key replace each other, so per-minute
    'waiting' messages cannot push real decisions out of the window."""
    print(message, flush=True)
    entry = {"t": fmt_utc(fmt="%m-%d %H:%M:%S"), "k": key or "", "m": message}

    def mutate(logs):
        logs = logs if isinstance(logs, list) else []
        if logs and logs[0].get("m") == message:
            return None, None
        if key and logs and logs[0].get("k") == key:
            logs[0] = entry
        else:
            logs.insert(0, entry)
        return logs[:DECISION_LOG_MAX], None

    try:
        gcs_update(DECISION_LOG_FILE, mutate, default_factory=list, reset_on_corrupt=True)
    except StorageError as exc:
        print(f"⚠️ [決策日誌寫入失敗] {exc}", flush=True)


def read_decision_logs():
    try:
        logs = gcs_read_json(DECISION_LOG_FILE, [])
        return logs if isinstance(logs, list) else []
    except StorageError as exc:
        print(f"⚠️ [決策日誌讀取失敗] {exc}", flush=True)
        return []


# =============================================================================
# 💰 Account snapshot
# =============================================================================
def save_account_snapshot(payload, m15_ohlc, m15_levels):
    # Missing numbers are stored as None (shown as "—"), never as fake defaults.  [R61]
    # [R83] EA 無持倉時 symbol 回報 "NONE"，但 m1_ohlc.symbol 一定是圖表商品名
    #       ——那就是券商商品列表裡的真名。拿它來對照 ORDER_SYMBOL。
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    broker_symbol = str(m1.get("symbol") or "").strip()
    if not broker_symbol:
        held = str(payload.get("symbol") or "").strip()
        broker_symbol = held if held and held != "NONE" else ""
    snapshot = {
        "status": str(payload.get("status") or "").strip().upper(),
        "symbol": str(payload.get("symbol") or "NONE"),
        "broker_symbol": broker_symbol or (read_account_snapshot().get("broker_symbol") or ""),
        "currency": str(payload.get("currency") or ACCOUNT_CURRENCY_DEFAULT),
        "net_lots": to_float(payload.get("net_lots")),
        "buy_lots": to_float(payload.get("buy_lots")),
        "sell_lots": to_float(payload.get("sell_lots")),
        "equity": to_float(payload.get("equity")),
        "credit": to_float(payload.get("credit")),                  # [R88] 券商的錢，不算進風控
        "balance": to_float(payload.get("balance")),
        "floating": to_float(payload.get("floating")),
        "daily_pnl": to_float(payload.get("daily_pnl")),
        "m15_ohlc": m15_ohlc or {},
        "m15_levels": m15_levels or {},
        "received_utc": fmt_utc(),
    }
    try:
        gcs_write_text(ACCOUNT_FILE, json.dumps(snapshot, ensure_ascii=False))
    except StorageError as exc:
        print(f"⚠️ [戶口快照寫入失敗] {exc}", flush=True)
    return snapshot


def broker_symbol_mismatch(snapshot=None):
    """[R83] ORDER_SYMBOL 與 EA 回報的券商商品名不一致時回一句話，否則 None。

    EA 的 m1_ohlc.symbol 是圖表商品，也就是券商商品列表裡的真名。
    人會記錯 XAUUSD / XAUUSD+，程式不會。
    """
    snap = snapshot if isinstance(snapshot, dict) else read_account_snapshot()
    seen = str(snap.get("broker_symbol") or "").strip()
    if not seen:
        return None
    ours = str(read_order_params()[0].get("symbol") or ORDER_SYMBOL).strip()
    if seen == ours:
        return None
    return (f"送單用的商品名是「{ours}」，但 EA 回報券商上的是「{seen}」。"
            f"不一致會被拒單，或成交在另一個商品上。"
            f"請到送單參數頁把 symbol 改成「{seen}」。")


def risk_equity(src):
    """[R88] 風控用的淨值 = 淨值 − 信用。只算自己的錢。

    MT5：淨值 = 結餘 + 信用 + 浮動。信用是券商給的額度，隨時可收回，虧損時
    通常第一個被扣 —— 拿它當安全邊際，等於把煞車借給別人踩。扣掉之後
    RISK_PCT 的 2% 和 DD_TOLERANCE_PCT 的 20% 才真的是自己本金的 2% 和 20%，
    而且入金出金會自動跟上，不需要任何換算係數。

    舊版 EA 的封包沒有 credit 欄位，那就退回 min(淨值, 結餘)：結餘本來就不含
    信用，所以有信用時這個值等於結餘，仍然是保守的。兩個都沒有才回 None。
    """
    if not isinstance(src, dict):
        return None
    eq = to_float(src.get("equity"))
    credit = to_float(src.get("credit"))
    if credit is not None:
        if eq is None:
            return None
        return max(eq - max(credit, 0.0), 0.0)
    bal = to_float(src.get("balance"))
    if eq is None:
        return bal
    return min(eq, bal) if bal is not None else eq


def broker_symbol_unverified(snapshot=None):
    """[R86] 還沒從 EA 看過券商商品名時，要說「沒核對過」，不要沉默。

    m1_ohlc.symbol 只在新的 M1 K 線才會帶（EA 第 706-717 行），所以休市期間
    一直收不到。沉默會讓儀表板看起來像「核對過、沒問題」，其實是從沒對過。
    """
    snap = snapshot if isinstance(snapshot, dict) else read_account_snapshot()
    if str(snap.get("broker_symbol") or "").strip():
        return None
    ours = str(read_order_params()[0].get("symbol") or ORDER_SYMBOL).strip()
    return (f"還沒從 EA 收到券商上的商品名，所以送單用的「{ours}」**沒有被核對過**。"
            f"EA 只在新的 M1 K 線才會帶商品名，開市後第一根 M1 收盤就會自動補上。")


def read_account_snapshot():
    try:
        data = gcs_read_json(ACCOUNT_FILE, {})
        return data if isinstance(data, dict) else {}
    except StorageError as exc:
        print(f"⚠️ [戶口快照讀取失敗] {exc}", flush=True)
        return {}


# =============================================================================
# 🚦 Gate + trend state (single machine-readable document)  [R4 R8 R9 R10 R30 R35]
# =============================================================================
def default_gate_state():
    return {
        "regime": REGIME_RANGE,   # RANGE | SETUP | TREND
        "dir": None,              # UP | DOWN | None
        "armed": False,           # True only after SETUP -> same-direction TREND
        "hard_lock": None,        # {"reason", "since_utc", "until_ts" (None = until manual release)}
        "news_lock": False,
        "risk": {},               # [R70] 風控電閘最近一次評估（開閘的真正依據）
        "equity_peak": 0.0,       # [R74] 歷史淨值高水位，空城計的回撤基準
        "equity_peak_basis": "",  # [R90] 上面那個高水位是用哪一把尺量的
        "dd_brake_day": "",       # [R93] 回撤煞車在哪一個紐約交易日踩下（當日鎖存）
        "trades_today": {},       # {"ny_date": "YYYY-MM-DD", "count": n}  [R73]
        "last_m1_bar_time": 0,    # idempotency for M1 packets  [R25]
        "last_m15_bar_time": 0,   # [R78] 錦囊：同一根已收盤 M15 只評估一次
        "last_reason": "",
        "updated_utc": None,
    }


def _merge_gate_state(raw):
    state = default_gate_state()
    if isinstance(raw, dict):
        state.update({key: raw[key] for key in state if key in raw})
    return state


def hard_lock_active(state, now=None):
    lock = state.get("hard_lock")
    if not isinstance(lock, dict):
        return False
    until = to_float(lock.get("until_ts"))
    return until is None or (now_ts() if now is None else now) < until


def gate_status(state, now=None):
    """[R70] armed 由風控電閘決定（GATE_DRIVER=RISK），不再由三級共振決定。
    GATE_DRIVER=REGIME 保留舊行為，只為了能一鍵回退比對。"""
    if hard_lock_active(state, now) or state.get("news_lock"):
        return "LOCK"
    if not state.get("armed"):
        return "LOCK"
    if GATE_DRIVER == "REGIME":
        return "OPEN" if (state.get("regime") == REGIME_TREND and state.get("dir") in ("UP", "DOWN")) else "LOCK"
    return "OPEN"


def read_gate_state():
    """Fails safe: an unreadable state is reported as LOCK.  [R13a]"""
    try:
        return _merge_gate_state(gcs_read_json(GATE_STATE_FILE, None))
    except StorageError as exc:
        print(f"⚠️ [電閘狀態讀取失敗 → 視為 LOCK] {exc}", flush=True)
        state = default_gate_state()
        state["last_reason"] = "電閘狀態讀取失敗"
        return state


def update_gate_state(fn, reset_on_corrupt=False):
    """fn(state) mutates state in place and returns (changed, result)."""
    def mutate(raw):
        state = _merge_gate_state(raw)
        changed, result = fn(state)
        if not changed:
            return None, result
        state["updated_utc"] = fmt_utc()
        return state, result

    return gcs_update(GATE_STATE_FILE, mutate, default_factory=dict, reset_on_corrupt=reset_on_corrupt)


def next_trend_state(state, verdict, skip_setup=False):
    """Pure transition function. Returns (regime, dir, armed, reason).

    RANGE/NODATA            -> RANGE, disarm
    PAUSE(d)                -> keep SETUP(d)/TREND(d) as-is, otherwise RANGE          [R8]
    SETUP(d)                -> pullback inside an armed TREND(d) keeps it armed,
                               otherwise SETUP(d), disarmed                             [R8b]
    TREND(d)                -> after SETUP(d): TRIGGER, armed
                               after TREND(d): keep armed flag
                               otherwise (no setup / opposite direction): TREND(d), disarmed [R30]
    """
    regime, cur_dir, armed = state.get("regime"), state.get("dir"), bool(state.get("armed"))
    v_regime, v_dir = verdict.get("regime"), verdict.get("dir")
    word = DIR_WORD.get(v_dir, "")

    if v_regime in (REGIME_RANGE, REGIME_NODATA):
        return REGIME_RANGE, None, False, "❌ 橫行或數據不足，取消開閘"
    if v_regime == REGIME_PAUSE:
        if regime == REGIME_TREND and cur_dir == v_dir:
            return regime, cur_dir, armed, f"{word}趨勢中 M1 短暫停頓，維持原狀態"
        if regime == REGIME_SETUP and cur_dir == v_dir:
            return regime, cur_dir, False, f"{word} Setup 中 M1 停頓，繼續等待 Trigger"
        return REGIME_RANGE, None, False, "M1 停頓但缺少同向趨勢背景，視為橫行"
    if v_regime == REGIME_SETUP:
        if regime == REGIME_TREND and cur_dir == v_dir and armed:
            return REGIME_TREND, cur_dir, True, f"{word}趨勢中的健康回調，維持開閘"
        return REGIME_SETUP, v_dir, False, f"{word} Setup 醞釀中，等待同向 Trigger"
    if v_regime == REGIME_TREND:
        if regime == REGIME_SETUP and cur_dir == v_dir:
            return REGIME_TREND, v_dir, True, f"Trigger 觸發：{word} Setup → 同向趨勢確認"
        if regime == REGIME_TREND and cur_dir == v_dir:
            if skip_setup and not armed:
                return REGIME_TREND, v_dir, True, f"{word}趨勢延續，Setup 確認關卡已略過 → 開閘"
            return REGIME_TREND, v_dir, armed, f"{word}趨勢延續（{'開閘中' if armed else '未經 Setup 確認，維持鎖定'}）"
        if skip_setup:
            return REGIME_TREND, v_dir, True, f"{word}趨勢出現，Setup 確認關卡已略過 → 直接開閘"
        return REGIME_TREND, v_dir, False, f"缺乏同向 Setup 的突發{word}趨勢，拒絕開閘"
    return REGIME_RANGE, None, False, f"❌ 未知判定 {v_regime}，取消開閘"


# -----------------------------------------------------------------------------
# 🛡️ 風控電閘  [R70 R71 R72 R73]
#
# 舊版：三級共振說「趨勢中」→ 開閘。量度後證實那沒有優勢（README §22/§23）。
# 新版：電閘不再預測方向，只回答一個問題——「現在讓你下單，最壞會怎樣？」
#       六道關卡全過才開閘，任何一道不過就鎖死並寫明原因。
# -----------------------------------------------------------------------------
def _ny_date(now=None):
    return datetime.fromtimestamp(now_ts() if now is None else now, NY_TZ).strftime("%Y-%m-%d")


def trades_today_count(state, now=None):
    box = state.get("trades_today")
    if not isinstance(box, dict) or box.get("ny_date") != _ny_date(now):
        return 0
    return int(to_float(box.get("count"), 0) or 0)


def bump_trades_today():
    """交易日以紐約日界線為準，與 EA 的跨日重置同源。  [R73]"""
    def fn(state):
        today = _ny_date()
        box = state.get("trades_today")
        count = int(to_float(box.get("count"), 0) or 0) if isinstance(box, dict) and box.get("ny_date") == today else 0
        state["trades_today"] = {"ny_date": today, "count": count + 1}
        return True, count + 1

    try:
        return update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [當日交易計數寫入失敗] {exc}", flush=True)
        return None


def evaluate_risk_gate(snapshot, state, now=None):
    """六道關卡。回傳 {"open": bool, "checks": [...], "reason": str, ...}。

    缺數據一律當成不過關（fail-closed），與 read_gate_state 的失敗語意一致。 [R13a]
    """
    now = now_ts() if now is None else now
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    m15 = snapshot.get("m15_ohlc") if isinstance(snapshot.get("m15_ohlc"), dict) else {}
    equity = risk_equity(snapshot)                                   # [R88] 扣掉信用
    balance = to_float(snapshot.get("balance"))
    daily = to_float(snapshot.get("daily_pnl"))
    lots = abs(to_float(snapshot.get("net_lots"), 0.0) or 0.0)
    price = to_float(m15.get("close"))
    atr15 = to_float(m15.get("atr_m15"))
    checks = []

    def add(key, name, ok, detail):
        checks.append({"key": key, "name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # ① 市場要開著
    market = GoldIndicatorSession.is_gold_market_open(now)
    add("market", "市場時段", market, "開市中" if market else "黃金休市")

    # ② 波動要夠付點差  [R72]
    if VOL_FLOOR_ATR_PCT <= 0:
        add("vol", "波動水位", True, "已停用（VOL_FLOOR_ATR_PCT=0）")
        atr_pct = None
    elif not atr15 or not price:
        atr_pct = None
        add("vol", "波動水位", False, "缺 atr_m15 或價格，無法判定")
    else:
        atr_pct = atr15 / price * 100
        ok = atr_pct >= VOL_FLOOR_ATR_PCT
        add("vol", "波動水位", ok,
            f"ATR(14)/價格 = {atr_pct:.4f}%，門檻 {VOL_FLOOR_ATR_PCT:.4f}%"
            f"（打平點 0.0837%）{'' if ok else ' → 波動不足以付點差'}")

    # ③ 空城計曝險上限：可用曝險 = (可承受回撤 − 目前回撤) ÷ 最壞跳空
    #    [R74] 回撤要對「歷史高水位」量。max(equity, balance) 不是高水位：
    #    虧損一旦實現就併進 balance，回撤會讀成 0，這一關等於沒有。
    exp_now = cap_eff = dd_now = None
    if not equity or equity <= 0:
        add("exposure", "曝險上限", False, "缺淨值，無法試算")
    else:
        # [R90] 尺換了就不能沿用舊高水位，否則差額會被當成回撤。
        stored_peak = (to_float(state.get("equity_peak"), 0.0) or 0.0) \
            if state.get("equity_peak_basis") == EQUITY_PEAK_BASIS else 0.0
        peak = max(stored_peak, equity, balance or 0.0)
        dd_now = max(0.0, (peak - equity) / peak * 100) if peak > 0 else 0.0
        cap_dyn = max(0.0, (DD_TOLERANCE_PCT - dd_now) / WORST_GAP_PCT) if WORST_GAP_PCT > 0 else 0.0
        cap_eff = min(EXPOSURE_HARD_CAP, cap_dyn)
        # [R79] 要檢查的是【下單之後】的曝險。原本只看目前持倉，空手時永遠是 0，
        #       等於第一張單完全不受上限管 —— 1 盎司（1.68x）可能已經超過可用曝險。
        pending = ORDER_SIZE if ENTRY_ENGINE == "JINNANG" else 0.0
        notional = (lots + pending) * CONTRACT_SIZE * (price or 0.0)
        rate = FX_TO_USD.get(str(snapshot.get("currency") or ACCOUNT_CURRENCY_DEFAULT).upper()) \
            or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
        equity_usd = equity * rate if rate else None          # 與 calculate_max_lots 同一個方向
        if price and equity_usd and equity_usd > 0:
            exp_now = notional / equity_usd
            ok = exp_now <= cap_eff
            detail = (f"下單後 {exp_now:.2f}x / 可用 {cap_eff:.2f}x"
                      f"（高水位 {peak:,.0f} → 回撤 {dd_now:.1f}% / 容忍 {DD_TOLERANCE_PCT:.0f}%，"
                      f"最壞跳空 {WORST_GAP_PCT:g}%）")
            # [R81] 分清楚兩種擋法。空手卻還是超標 = 戶口對這個最小手數來說太小，
            #       而且【停了就回不來】：不能交易 → 權益不變 → 回撤不會縮小。
            #       這是要人介入的狀態，不是等一等就會好，所以訊息要講清楚。
            if not ok and lots <= 0:
                need_eq = (pending * CONTRACT_SIZE * price / cap_eff / rate) if cap_eff > 0 else None
                detail += ("　🔒 空手就已超標 = 這個戶口做不了 "
                           f"{pending:g} 手。停了之後權益不會再變，回撤也不會縮小 —— "
                           "要加本金或縮小手數，等下去沒有用。")
                if need_eq:
                    detail += f"（本金要 ≥ {need_eq:,.0f}）"
            add("exposure", "曝險上限", ok, detail)
        else:
            add("exposure", "曝險上限", False, "缺價格或匯率，無法試算曝險")

    # ④ 單日虧損上限
    if daily is None or not equity or equity <= 0:
        add("daily", "單日虧損", False, "缺當日損益或淨值，無法判定")
    else:
        limit = equity * DAILY_LOSS_LIMIT_PCT / 100
        ok = daily > -limit
        add("daily", "單日虧損", ok,
            f"今日 {daily:,.0f} / 上限 −{limit:,.0f}（淨值的 {DAILY_LOSS_LIMIT_PCT:.1f}%）")

    # ⑤ 訓練節奏  [R73]
    used = trades_today_count(state, now)
    if TRAINING_MAX_PER_DAY <= 0:
        add("pace", "訓練節奏", True, f"不限筆數（今日已 {used} 筆）")
    else:
        ok = used < TRAINING_MAX_PER_DAY
        add("pace", "訓練節奏", ok, f"今日 {used} / {TRAINING_MAX_PER_DAY} 筆"
                                    f"{'' if ok else ' → 今日額滿，明天再來'}")

    # ⑥ 回撤煞車  [R93]
    #    踩下之後當日鎖存 —— 盤中回撤縮回去也不放行，否則那不叫煞車。
    brake_hit = False
    latched = str(state.get("dd_brake_day") or "") == _ny_date(now)
    if DD_BRAKE_PCT <= 0:
        add("brake", "回撤煞車", True, f"已停用（DD_BRAKE_PCT=0）")
    elif dd_now is None:
        add("brake", "回撤煞車", False, "缺淨值，算不出回撤")
    else:
        brake_hit = dd_now >= DD_BRAKE_PCT
        engaged = brake_hit or latched
        detail = f"回撤 {dd_now:.1f}% / 煞車 {DD_BRAKE_PCT:.0f}%"
        if engaged:
            detail += ("　🛑 今日不再開新倉"
                       f"{'（今日稍早踩下，已鎖存）' if latched and not brake_hit else ''}。"
                       "已開的倉不受影響，EA 的定時出場照常。"
                       "紐約日界線換日後重評 —— 回撤沒縮小的話明天仍會煞停，"
                       "那要人介入（加本金、縮手數，或確認高水位是對的），等下去不會自己好。")
        add("brake", "回撤煞車", not engaged, detail)

    failed = [c for c in checks if not c["ok"]]
    return {
        "open": not failed,
        "checks": checks,
        "reason": "六關全過 → 開閘" if not failed else "｜".join(f"{c['name']}：{c['detail']}" for c in failed),
        "atr_pct": atr_pct, "exposure": exp_now, "exposure_cap": cap_eff, "drawdown_pct": dd_now,
        "equity_peak": max(
            (to_float(state.get("equity_peak"), 0.0) or 0.0)
            if state.get("equity_peak_basis") == EQUITY_PEAK_BASIS else 0.0,     # [R90]
            equity or 0.0, balance or 0.0),
        "equity_peak_basis": EQUITY_PEAK_BASIS,
        "trades_today": used, "evaluated_utc": fmt_utc(now),
        "dd_brake_hit": brake_hit,                                               # [R93]
    }


def apply_risk_to_gate(snapshot, news_locked):
    """把風控評估寫進電閘。這是 GATE_DRIVER=RISK 下唯一設定 armed 的地方。"""
    def fn(state):
        before = gate_status(state)
        risk = evaluate_risk_gate(snapshot, state)
        armed = risk["open"]
        reason = risk["reason"]
        if news_locked and armed:
            armed = False
            reason = "❌ 新聞風控期間不開閘"
        # [R75] 每 60 秒一次心跳 = 一天 1,440 次寫入。只有實際變動才寫。
        #       evaluated_utc 每次都不同，比較時要排除它。
        prev = state.get("risk") if isinstance(state.get("risk"), dict) else {}
        def shape(r):
            return (r.get("open"), r.get("reason"),
                    tuple((c.get("key"), c.get("ok"), c.get("detail")) for c in r.get("checks", [])))
        # [R90] 換尺時新高水位會【變小】，上面那個 > 比較抓不到，所以要單獨判一次，
        #       否則基準標記永遠寫不進去，舊尺的高水位會一直把電閘鎖著。
        basis_changed = state.get("equity_peak_basis") != risk["equity_peak_basis"]
        # [R93] 煞車踩下要鎖存到當日結束。evaluate_risk_gate 必須無副作用（儀表板
        #       也會呼叫它試算），所以鎖存寫在這裡，不寫在評估裡。
        brake_day = str(state.get("dd_brake_day") or "")
        if risk.get("dd_brake_hit"):
            brake_day = _ny_date()
        brake_changed = brake_day != str(state.get("dd_brake_day") or "")
        changed = (shape(prev) != shape(risk) or bool(state.get("armed")) != armed
                   or bool(state.get("news_lock")) != bool(news_locked)
                   or basis_changed or brake_changed
                   or risk["equity_peak"] > (to_float(state.get("equity_peak"), 0.0) or 0.0) + 1e-9)
        if brake_changed:
            print(f"🛑 [回撤煞車] 回撤 {risk.get('drawdown_pct') or 0:.1f}% 達到 "
                  f"{DD_BRAKE_PCT:g}% —— {brake_day}（紐約）不再開新倉。"
                  f"已開的倉不受影響。[R93]", flush=True)
        if basis_changed:
            print(f"ℹ️ [高水位重新起算] 風控淨值的定義變了（{state.get('equity_peak_basis') or '未標記'}"
                  f" → {risk['equity_peak_basis']}），舊高水位 "
                  f"{to_float(state.get('equity_peak'), 0.0) or 0.0:,.2f} 不再沿用，"
                  f"改由 {risk['equity_peak']:,.2f} 起算。[R90]", flush=True)
        state.update(risk=risk, armed=armed, news_lock=bool(news_locked), last_reason=reason,
                     equity_peak=risk["equity_peak"],
                     equity_peak_basis=risk["equity_peak_basis"],
                     dd_brake_day=brake_day)                                     # [R93]
        after = gate_status(state)
        return changed, {"before": before, "after": after, "reason": reason, "risk": risk}

    try:
        return update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [風控電閘寫入失敗 → 維持原狀] {exc}", flush=True)
        return None


def _state_label(state_tuple):
    regime, direction, armed = state_tuple
    name = {REGIME_RANGE: "橫行", REGIME_SETUP: "Setup", REGIME_TREND: "趨勢"}.get(regime, str(regime))
    word = DIR_WORD.get(direction, "")
    return f"{word}{name}" + ("（🟢 已開閘）" if armed else "")


def apply_verdict_to_gate(verdict, news_locked, skip_setup=False):
    def fn(state):
        before = gate_status(state)
        prev = (state.get("regime"), state.get("dir"), bool(state.get("armed")))
        regime, direction, armed, reason = next_trend_state(state, verdict, skip_setup)
        if news_locked and armed:
            # Disarm during news: a fresh Setup→Trigger is required after the event.  [R49]
            armed = False
            reason += "｜❌ 新聞風控期間取消開閘，事件後需重新 Setup→Trigger"
        state.update(regime=regime, dir=direction, armed=armed, news_lock=bool(news_locked), last_reason=reason)
        return True, {"before": before, "after": gate_status(state), "reason": reason,
                      "prev": prev, "now": (regime, direction, armed)}

    return update_gate_state(fn)


def claim_m15_bar(bar_time):
    """True 只對第一個帶著這根 M15 時間的封包成立。  [R78]"""
    def fn(state):
        if bar_time <= int(to_float(state.get("last_m15_bar_time"), 0)):
            return False, False
        state["last_m15_bar_time"] = bar_time
        return True, True

    try:
        return update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [M15 去重寫入失敗，本根略過] {exc}", flush=True)
        return False


def claim_m1_bar(bar_time):
    """True only for the first packet carrying this bar time.  [R25]"""
    def fn(state):
        if bar_time <= int(to_float(state.get("last_m1_bar_time"), 0)):
            return False, False
        state["last_m1_bar_time"] = bar_time
        return True, True

    try:
        return update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [M1 去重寫入失敗，本根略過] {exc}", flush=True)
        return False


def set_hard_lock(reason, until_ts=None):
    """Hard lock the gate. An existing stronger/longer lock is kept.  [R10]"""
    def fn(state):
        current = state.get("hard_lock")
        if hard_lock_active(state) and isinstance(current, dict):
            current_until = to_float(current.get("until_ts"))
            if current_until is None or (until_ts is not None and current_until >= until_ts):
                was_armed = state.get("armed")
                state["armed"] = False
                return bool(was_armed), None
        state["hard_lock"] = {"reason": reason, "since_utc": fmt_utc(), "until_ts": until_ts}
        state["armed"] = False
        state["last_reason"] = f"硬鎖：{reason}"
        return True, None

    update_gate_state(fn, reset_on_corrupt=True)


def clear_hard_lock():
    def fn(state):
        state["hard_lock"] = None
        state["last_reason"] = "管理員解除硬鎖，恢復自動（需重新 Setup→Trigger）"
        return True, None

    update_gate_state(fn, reset_on_corrupt=True)


def disarm_gate(reason):
    def fn(state):
        if not state.get("armed"):
            return False, None
        state["armed"] = False
        state["last_reason"] = reason
        return True, None

    try:
        update_gate_state(fn)
    except StorageError as exc:
        print(f"⚠️ [取消開閘寫入失敗] {exc}", flush=True)


# =============================================================================
# 📌 Pyramid state (base price, last order, last close)
# =============================================================================
def read_pyramid_state():
    data = gcs_read_json(PYRAMID_STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def update_pyramid_state(**fields):
    def mutate(data):
        data = data if isinstance(data, dict) else {}
        data.update(fields)
        data["updated_utc"] = fmt_utc()
        return data, data

    return gcs_update(PYRAMID_STATE_FILE, mutate, default_factory=dict, reset_on_corrupt=True)


# =============================================================================
# 🧩 M1 history, indicators and regime verdict
# =============================================================================
def wilder_rsi_last(closes, period=14):
    """Wilder RSI of the last close. Seed uses changes 1..period, smoothing starts
    at period+1 (fixes the double-counted change).  [R22]"""
    if len(closes) <= period:
        return None

    def rsi(avg_gain, avg_loss):
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    return round(rsi(avg_gain, avg_loss), 2)


def _verdict(regime, direction, text):
    return {"regime": regime, "dir": direction, "text": text}


class GoldIndicatorSession:
    @staticmethod
    def is_gold_market_open(now=None):
        ny = datetime.fromtimestamp(now_ts() if now is None else now, NY_TZ)
        weekday, hour = ny.weekday(), ny.hour
        if weekday == 5:
            return False
        if weekday == 4 and hour >= 17:
            return False
        if weekday == 6 and hour < 18:
            return False
        if weekday in (0, 1, 2, 3) and hour == 17:
            return False
        return True  # holidays not handled  [R44]

    @staticmethod
    def parse_bar(ohlc):
        """Validated bar or None. Assumes the EA sends the bar that just CLOSED
        when is_new_bar is true.  [R46]"""
        if not isinstance(ohlc, dict):
            return None
        bar_time = to_float(ohlc.get("time"))
        values = {key: to_float(ohlc.get(key)) for key in ("open", "high", "low", "close")}
        if bar_time is None or bar_time <= 0 or any(v is None or v <= 0 for v in values.values()):
            return None
        if values["high"] < max(values["open"], values["close"]) - 1e-6 or \
                values["low"] > min(values["open"], values["close"]) + 1e-6:
            return None
        if values["open"] == values["high"] == values["low"] == values["close"]:
            print("⚠️ [M1] 收到 O=H=L=C 的 K 線：請確認 EA 傳的是『剛收盤』而非『剛開盤』的 K 線。[R46]", flush=True)
        return {"time": int(bar_time), **values}

    @staticmethod
    def read_bars():
        try:
            bars = gcs_read_json(M1_HISTORY_FILE, [])
            return bars if isinstance(bars, list) else []
        except StorageError as exc:
            print(f"⚠️ [M1 歷史讀取失敗] {exc}", flush=True)
            return []

    @staticmethod
    def ingest_bar(bar):
        """Append in time order; drop out-of-order bars; restart history after a gap.  [R21]"""
        def mutate(history):
            history = history if isinstance(history, list) else []
            if history:
                last_time = history[-1]["time"]
                if bar["time"] < last_time:
                    print(f"⚠️ [M1] 忽略亂序 K 線 {bar['time']} < {last_time}", flush=True)
                    return None, history
                if bar["time"] == last_time:
                    if history[-1] == bar:
                        return None, history
                    history[-1] = bar
                else:
                    if bar["time"] - last_time > M1_GAP_RESET_SEC:
                        print(f"ℹ️ [M1] 偵測到 {int((bar['time'] - last_time) / 60)} 分鐘缺口，重新累積歷史。", flush=True)
                        history = []
                    history.append(bar)
            else:
                history.append(bar)
            history = history[-M1_HISTORY_MAX:]
            return history, history

        return gcs_update(M1_HISTORY_FILE, mutate, default_factory=list, reset_on_corrupt=True)

    @staticmethod
    def _move_over(bars, minutes):
        """(price move, actual minutes) between the last bar and the bar ~minutes earlier,
        using timestamps instead of bar counts.  [R21]"""
        last = bars[-1]
        target = last["time"] - minutes * 60
        tolerance = max(60, minutes * 6)
        for bar in reversed(bars[:-1]):
            if bar["time"] <= target:
                if target - bar["time"] > tolerance:
                    return None
                return last["close"] - bar["close"], (last["time"] - bar["time"]) / 60.0
        return None

    @staticmethod
    def compute_verdict(bars):
        """Machine-readable regime from M1 closes over 60/24/4-minute windows.
        Thresholds scale with measured per-minute volatility × √minutes.  [R8 R9 R31]"""
        n = len(bars)
        if n < MIN_M1_BARS:
            return _verdict(REGIME_NODATA, None, f"【數據累積中⏳】 連續 M1 K 線 {n}/{MIN_M1_BARS} 根，暫不判定。")

        diffs = [bars[i]["close"] - bars[i - 1]["close"]
                 for i in range(n - 60, n) if bars[i]["time"] - bars[i - 1]["time"] == 60]
        if len(diffs) < 30:
            return _verdict(REGIME_NODATA, None, "【數據不足⏳】 最近 60 分鐘缺漏 K 線過多，暫不判定。")
        mean = sum(diffs) / len(diffs)
        sigma = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
        if sigma <= 0:
            return _verdict(REGIME_RANGE, None, "【明確橫行💤】 價格近乎無波動。")

        signs, parts = {}, []
        for label, minutes in (("M15", 60), ("M5", 24), ("M1", 4)):
            found = GoldIndicatorSession._move_over(bars, minutes)
            if found is None:
                return _verdict(REGIME_NODATA, None, f"【數據不足⏳】 {label} 窗口（{minutes} 分鐘）缺少對應 K 線。")
            move, actual = found
            threshold = NOISE_K * sigma * math.sqrt(actual)
            signs[label] = 1 if move > threshold else (-1 if move < -threshold else 0)
            parts.append(f"{label}:{move / actual:+.3f}/分 門檻±{threshold / actual:.3f}")
        detail = ", ".join(parts)

        big = signs["M15"]
        if big != 0 and signs["M5"] == big:
            direction = "UP" if big > 0 else "DOWN"
            word = DIR_WORD[direction]
            if signs["M1"] == big:
                return _verdict(REGIME_TREND, direction, f"【單邊趨勢中✅】 三級共振{'向上' if big > 0 else '向下'} ({detail})")
            if signs["M1"] == -big:
                return _verdict(REGIME_SETUP, direction,
                                f"【突破整理邊緣🔆】 大級別{word}，M1 {'回調' if big > 0 else '反彈'} ({detail})")
            return _verdict(REGIME_PAUSE, direction, f"【趨勢停頓⏸️】 大級別{word}，M1 暫時持平 ({detail})")
        return _verdict(REGIME_RANGE, None, f"【明確橫行💤】 M15/M5 未同向越過雜訊門檻 ({detail})")

    @staticmethod
    def _append_verdict_log(text):
        line = f"[{fmt_utc()} UTC] {text}"

        def mutate(lines):
            lines = [row for row in (lines or []) if row.strip()]
            lines.insert(0, line)
            return lines[:50], None

        try:
            gcs_update(M1_VERDICT_LOG_FILE, mutate, loads=lambda s: s.splitlines(),
                       dumps=lambda rows: "\n".join(rows), default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [M1 判定日誌寫入失敗] {exc}", flush=True)

    def process_m1_bar(self, bar, news_locked, skip_setup=False):
        """[R70] GATE_DRIVER=RISK 時本函式只更新雷達顯示，不碰 armed。
        三級共振量度後已退出開閘決策（README §22/§23）；保留是因為看盤有用，
        不是因為它有優勢。"""
        history = self.ingest_bar(bar)
        archive_mt5_bar(bar)                        # [R95] 按日封存，失敗只記 Log
        verdict = self.compute_verdict(history)
        rsi = wilder_rsi_last([b["close"] for b in history])
        print(f"📊 [M1 盤勢監控｜僅供觀察] {verdict['text']}", flush=True)
        self._append_verdict_log(verdict["text"])

        if GATE_DRIVER != "REGIME":
            def fn(state):
                prev = (state.get("regime"), state.get("dir"))
                state.update(regime=verdict["regime"] if verdict["regime"] in
                             (REGIME_RANGE, REGIME_SETUP, REGIME_TREND) else REGIME_RANGE,
                             dir=verdict.get("dir"))
                return prev != (state.get("regime"), state.get("dir")), None
            try:
                update_gate_state(fn)
            except StorageError as exc:
                print(f"⚠️ [雷達顯示寫入失敗] {exc}", flush=True)
            short = verdict["text"].split(" (")[0]
            log_decision(f"📡 [盤勢雷達｜不參與開閘] {short}", key="monitor")
            return {"verdict": verdict, "rsi": rsi, "bars": len(history)}

        result = apply_verdict_to_gate(verdict, news_locked, skip_setup)
        before, after, reason = result["before"], result["after"], result["reason"]
        print(f"🔍 [狀態機] {before} → {after} | {reason}", flush=True)
        if before != after:
            log_decision(f"{'🟢' if after == 'OPEN' else '🔒'} [電閘 {before}→{after}] {reason}", key="gate")
        elif result["prev"] != result["now"]:
            log_decision(f"🔄 [狀態轉換] {_state_label(result['prev'])} → {_state_label(result['now'])}：{reason}",
                         key="regime")
        else:
            short = verdict["text"].split(" (")[0]
            log_decision(f"📡 [盤勢監控] {short}｜電閘 {after}：{reason}", key="monitor")
        return {"verdict": verdict, "rsi": rsi, "bars": len(history)}


gold_indicator_session = GoldIndicatorSession()


# =============================================================================
# 📊 M15 Bollinger levels — writer and pure reader are separate  [R20 R26 R50]
# =============================================================================
class MTFDynamicLevelsSession:
    bb_period = 20
    bb_std_dev = 2.0
    # [R78] 錦囊 v4 需要 60 根迴歸 + 20 根區間 + 14 根 ATR + 30 根區間壽命，
    #       而且要能重播區間狀態機，所以留 200 根（約 50 小時）。
    history_max = _env_int("M15_HISTORY_MAX", 200)

    @staticmethod
    def parse_bar(m15_ohlc):
        if not isinstance(m15_ohlc, dict):
            return None
        bar_time = to_float(m15_ohlc.get("time"))
        values = {key: to_float(m15_ohlc.get(key)) for key in ("open", "high", "low", "close")}
        if bar_time is None or bar_time <= 0 or any(v is None or v <= 0 for v in values.values()):
            return None
        if values["high"] < values["low"]:
            return None
        return {"time": int(bar_time), **values}

    def ingest(self, m15_ohlc):
        """POST path only: store the bar (if valid and changed) and return levels."""
        bar = self.parse_bar(m15_ohlc)
        if bar is None:
            print("⚠️ [M15] 收到不完整的 M15 K 線，拒絕寫入歷史。[R26]", flush=True)
            return self.read_levels()

        def mutate(history):
            history = history if isinstance(history, list) else []
            if history and bar["time"] < history[-1]["time"]:
                return None, history
            if history and bar["time"] == history[-1]["time"]:
                if history[-1] == bar:
                    return None, history
                # [R80] 同一根時間、但 OHLC 變了。只有當這根就是【當下】那一根時，
                #       才代表 EA 送的是正在形成的 K 線。舊 K 線被改寫是另一回事
                #       （券商重新同步歷史，或歷史檔混進了別的商品），不能叫人改設定。[R85]
                if ENTRY_ENGINE == "JINNANG":
                    prev = history[-1]
                    age = now_ts() - (bar["time"] - BROKER_UTC_OFFSET_HOURS * 3600)
                    moved = ", ".join(
                        f"{k} {prev.get(k)}→{bar.get(k)}"
                        for k in ("open", "high", "low", "close")
                        if prev.get(k) != bar.get(k))
                    if not moved:
                        # OHLC 四個值一樣卻判定為「變了」= 存檔的形狀跟現在不一樣
                        # （多餘欄位、或 time 型別不同），不是行情在動，跟 K 線新舊
                        # 無關，所以這條要先判，不能落到下面的「正在形成」。[R85]
                        print(f"⚠️ [M15] K 線（{bar['time']}）的 OHLC 四個值完全相同，"
                              f"卻被判定為有變動 —— 差異在存檔格式，不是行情在動。"
                              f"別動 JN_M15_LAST_CLOSED。"
                              f"舊={sorted(prev)} 新={sorted(bar)}  [R85]", flush=True)
                    elif age < 2 * 900:
                        if JN_M15_LAST_CLOSED:
                            print(f"⚠️ [M15] 當下這根 K 線（{bar['time']}）的 OHLC 被更新 —— "
                                  f"你的 EA 送的是【正在形成】的 K 線，但 JN_M15_LAST_CLOSED=1。"
                                  f"請把它設成 0，否則錦囊會用半根 K 線判訊號。"
                                  f"（{moved}）[R80]", flush=True)
                    else:
                        print(f"⚠️ [M15] 已收盤 {age / 3600:.1f} 小時的 K 線（{bar['time']}）"
                              f"被改寫。這不是「正在形成」，別動 JN_M15_LAST_CLOSED。"
                              f"一次性多半是券商重新同步歷史；反覆出現要查歷史檔是不是"
                              f"混了兩個商品（XAUUSD / XAUUSD+ 報價不同）。"
                              f"（{moved}）[R85]", flush=True)
                history[-1] = bar
            else:
                history.append(bar)
            history = history[-self.history_max:]
            return history, history

        try:
            history = gcs_update(M15_HISTORY_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [M15 歷史寫入失敗] {exc}", flush=True)
            return {"status": "unavailable"}
        return self.compute_levels(history)

    def read_levels(self):
        """Read-only (safe for GET pages)."""
        try:
            history = gcs_read_json(M15_HISTORY_FILE, [])
        except StorageError as exc:
            print(f"⚠️ [M15 歷史讀取失敗] {exc}", flush=True)
            return {"status": "unavailable"}
        return self.compute_levels(history if isinstance(history, list) else [])

    def compute_levels(self, history):
        valid = [b for b in history if to_float(b.get("close"), 0.0) > 0]
        if len(valid) < self.bb_period:
            return {"status": "insufficient_data", "count": len(valid)}
        # The window includes the forming bar, like MT5's current-bar BB.  [R51]
        closes = [b["close"] for b in valid[-self.bb_period:]]
        sma20 = sum(closes) / self.bb_period
        std_dev = math.sqrt(sum((x - sma20) ** 2 for x in closes) / self.bb_period)
        upper, lower = sma20 + self.bb_std_dev * std_dev, sma20 - self.bb_std_dev * std_dev
        bandwidth = (upper - lower) / sma20 * 100.0 if sma20 else 0.0
        return {
            "status": "ready",
            "M15_R1": round(upper, 2),
            "M15_MID": round(sma20, 2),
            "M15_S1": round(lower, 2),
            "M15_BB_WIDTH": round(bandwidth, 2),
        }


mtf_levels_session = MTFDynamicLevelsSession()


# =============================================================================
# 🎯 錦囊 v4 進場引擎  [R78]
#
# 規則（TradingView `zhugeliang_jinnang_v4.pine` 的 Python 移植）：
#   XAUUSD M15 · 八陣圖原廠門檻 · 只做多 · ATR(14)÷價格 ≥ VOL_FLOOR_ATR_PCT
#   橫行區間確認 → 收盤突破上緣 + bufATR → 下一根進場 → 抱 10 根 → 無價格停損
#
# 出場【不在這裡】：EA 的 CheckTimeExit() 在 InpHoldMinutes = 150 分鐘時全平。
# 這裡送出的 SL 是災難停損（JN_DISASTER_SL_ATR × ATR），正常情況碰不到。
#
# ⚠️ 與 TradingView 的已知差異：ATR(14) 的 RMA 在這裡只用最近 200 根 M15 起算，
#    TradingView 從圖表最左邊起算。邊界訊號（剛好卡在門檻上）兩邊可能不同。
#    2026-09-20 對數實測吻合 88.8%，詳見 README §29。
# =============================================================================
class JinnangSession:
    @staticmethod
    def _wilder_atr(bars, length):
        """Wilder RMA 的 ATR。bars 必須是時間排序的已收盤 K 線。"""
        if len(bars) < length + 1:
            return None
        trs = []
        for i in range(1, len(bars)):
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[:length]) / length
        for tr in trs[length:]:
            atr = (atr * (length - 1) + tr) / length
        return atr

    @staticmethod
    def _slope_r2(closes):
        """最小平方迴歸的斜率，以及 Pine `ta.correlation(close, bar_index, n)^2`。"""
        n = len(closes)
        if n < 3:
            return 0.0, 0.0
        xs = list(range(n))
        mx, my = (n - 1) / 2.0, sum(closes) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, closes))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in closes)
        if sxx <= 0 or syy <= 0:
            return 0.0, 0.0
        slope = sxy / sxx
        r = sxy / math.sqrt(sxx * syy)
        return slope, r * r

    @classmethod
    def _atr_series(cls, bars, length):
        """每根一個 ATR（Wilder RMA）。前 length 根是 None。"""
        n = len(bars)
        out = [None] * n
        if n < length + 1:
            return out
        trs = [None]
        for i in range(1, n):
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[1:length + 1]) / length
        out[length] = atr
        for i in range(length + 1, n):
            atr = (atr * (length - 1) + trs[i]) / length
            out[i] = atr
        return out

    @classmethod
    def evaluate(cls, history):
        """history = 已收盤的 M15 K 線（時間排序）。最後一根 = 剛收盤那一根。

        訊號成立時，下一根開盤進場（EA 收到 200 後自行下單）。
        """
        bars = [b for b in (history or []) if to_float(b.get("close"), 0.0) > 0]
        need = max(JN_LEN_TREND, JN_LEN_RANGE, JN_ATR_LEN + 1, JN_MIN_BARS)
        if len(bars) < need:
            return {"ready": False, "signal": None,
                    "text": f"【累積中⏳】已收盤 M15 {len(bars)}/{need} 根"}

        n = len(bars)
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        atrs = cls._atr_series(bars, JN_ATR_LEN)

        # 一次算完每根的 st（1 上升 / −1 下降 / 0 橫行 / 2 其他）
        first = max(JN_LEN_TREND - 1, JN_LEN_RANGE - 1, JN_ATR_LEN)
        st = [None] * n
        for i in range(first, n):
            atr = atrs[i]
            if not atr or atr <= 0:
                continue
            slope, r2v = cls._slope_r2(closes[i - JN_LEN_TREND + 1:i + 1])
            sn = slope / atr
            w = (max(highs[i - JN_LEN_RANGE + 1:i + 1])
                 - min(lows[i - JN_LEN_RANGE + 1:i + 1])) / atr
            if r2v >= JN_R2_MIN and sn >= JN_SLOPE_MIN:
                st[i] = 1
            elif r2v >= JN_R2_MIN and sn <= -JN_SLOPE_MIN:
                st[i] = -1
            else:
                st[i] = 0 if w <= JN_RANGE_MAX_ATR else 2

        # 線性重播狀態機，與 Pine 的 barstate.isconfirmed 分支一一對應
        box_top = box_bot = None
        box_live = False
        last_range_bar = -1
        run = pend_dir = pend_cnt = 0
        for i in range(first, n):
            if st[i] is None:
                continue
            run = run + 1 if st[i] == 0 else 0
            if st[i] == 0 and run >= JN_RANGE_MIN_BARS:
                box_top = max(highs[i - JN_LEN_RANGE:i])
                box_bot = min(lows[i - JN_LEN_RANGE:i])
                box_live, last_range_bar = True, i
            elif box_live and last_range_bar >= 0 and i - last_range_bar > JN_BOX_MAX_AGE:
                box_live = False
            if not box_live or not atrs[i]:
                pend_dir = pend_cnt = 0
                continue
            up_level = box_top + JN_BUF_ATR * atrs[i]
            dn_level = box_bot - JN_BUF_ATR * atrs[i]
            raw = 1 if closes[i] > up_level else (-1 if closes[i] < dn_level else 0)
            if raw != 0 and raw == pend_dir:
                pend_cnt += 1
            elif raw != 0:
                pend_dir, pend_cnt = raw, 1
            else:
                pend_dir = pend_cnt = 0
            # [R78] Pine 的 `boxLive := false` 在 `if takeUp ...` 區塊裡面：
            #       只有【真的會下單】的訊號才消耗掉區間。被只做多或波動門檻擋掉
            #       的不算。這一行讓重播和 Pine 一致，否則同一個區間會重複觸發。
            if i < n - 1 and pend_dir == 1 and pend_cnt == JN_CONFIRM_BARS:
                a = atrs[i]
                pct_i = (a / closes[i] * 100) if a and closes[i] else None
                if VOL_FLOOR_ATR_PCT <= 0 or (pct_i is not None and pct_i >= VOL_FLOOR_ATR_PCT):
                    box_live = False

        atr_now, price = atrs[-1], closes[-1]
        atr_pct = (atr_now / price * 100) if atr_now and price else None
        confirm_up = box_live and pend_dir == 1 and pend_cnt == JN_CONFIRM_BARS
        vol_ok = VOL_FLOOR_ATR_PCT <= 0 or (atr_pct is not None and atr_pct >= VOL_FLOOR_ATR_PCT)
        base = {"ready": True, "atr_pct": atr_pct, "atr": atr_now, "price": price,
                "box_top": box_top, "box_bot": box_bot, "box_live": box_live,
                "bar_time": bars[-1]["time"]}
        pct = f"{atr_pct:.3f}%" if atr_pct is not None else "—"

        if pend_dir == -1 and pend_cnt == JN_CONFIRM_BARS and box_live:
            return {**base, "signal": None,
                    "text": f"【略過·只做多】向下跌破 {box_bot:.2f}，v4 不做空"}
        if not confirm_up:
            why = "區間未成形" if not box_live else "未突破上緣"
            return {**base, "signal": None, "text": f"【等待🔍】{why}（ATR {pct}）"}
        if not vol_ok:
            return {**base, "signal": None,
                    "text": f"【略過·波動不足】突破成立但 ATR {pct} < 門檻 "
                            f"{VOL_FLOOR_ATR_PCT:g}%（打平點 0.0837%）"}
        return {**base, "signal": "BUY",
                "text": f"【錦囊進場訊號✅】向上突破 {box_top:.2f} + {JN_BUF_ATR:g}ATR，"
                        f"ATR {pct}（門檻 {VOL_FLOOR_ATR_PCT:g}%），抱 {JN_HOLD_BARS} 根"}


jinnang_session = JinnangSession()


def m15_close_position(m15_ohlc):
    """(close - low) / (high - low) of the forming M15 bar, or None."""
    if not isinstance(m15_ohlc, dict):
        return None
    high, low, close = (to_float(m15_ohlc.get(k)) for k in ("high", "low", "close"))
    if high is None or low is None or close is None or high <= low:
        return None
    return round((close - low) / (high - low), 2)


# =============================================================================
# ⚖️ Trade history and statistics  [R7 R15 R28 R34 R42]
# =============================================================================
class RiskManagerSession:
    @staticmethod
    def read_trades():
        return jsonl_loads(gcs_read_text(TRADE_HISTORY_FILE) or "")

    def record_trade(self, trade):
        """Returns (stats, is_new). Raises StorageError instead of faking stats.  [R34b]"""
        def mutate(trades):
            if any(t.get("ticket") == trade["ticket"] for t in trades):
                return None, (trades, False)
            trades.append(trade)
            return trades, (trades, True)

        trades, is_new = gcs_update(TRADE_HISTORY_FILE, mutate, loads=jsonl_loads,
                                    dumps=jsonl_dumps, default_factory=list)
        return self.calculate_stats(trades), is_new

    def get_current_stats(self):
        try:
            return self.calculate_stats(self.read_trades())
        except StorageError as exc:
            print(f"⚠️ [交易歷史讀取失敗] {exc}", flush=True)
            stats = self.calculate_stats([])
            stats["error"] = True
            return stats

    @staticmethod
    def _summarize(profits):
        wins = [p for p in profits if p > BREAKEVEN_EPS]
        losses = [p for p in profits if p < -BREAKEVEN_EPS]
        decided = len(wins) + len(losses)
        return {
            "trades": len(profits),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(profits) - decided,
            "win_rate": round(len(wins) / decided * 100, 2) if decided else 0.0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(abs(sum(losses)) / len(losses), 2) if losses else 0.0,
            "expectancy": round(sum(profits) / len(profits), 2) if profits else 0.0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        }

    def calculate_stats(self, trades):
        """TP ratio is a configured setting (送單參數頁), never derived from the stats.  [R15]
        Break-even exits are counted separately from wins and losses.  [R24c]"""
        profits = [to_float(t.get("profit"), 0.0) for t in trades]
        all_time = self._summarize(profits)
        recent = self._summarize(profits[-STATS_WINDOW:])
        return {
            "win_rate": all_time["win_rate"],
            "recommended_rrr": current_target_rrr(),
            "total_trades": all_time["trades"],
            "all_time": all_time,
            "recent": recent,
        }


risk_manager_session = RiskManagerSession()


# =============================================================================
# 🧠 SFT pipeline — compact contexts, matched pairing  [R6 R7 R24]
# =============================================================================
def build_signal_meta(candidate, m15_levels, m15_ohlc, rsi):
    return {
        "time_utc": fmt_utc(),
        "symbol": candidate["ticker"],
        "signal": candidate["signal"],
        "kind": candidate["kind"],
        "price": round(candidate["price"], 2),
        "trend_dir": candidate["direction"],
        "rsi_m1": rsi,
        "m15_r1": m15_levels.get("M15_R1"),
        "m15_mid": m15_levels.get("M15_MID"),
        "m15_s1": m15_levels.get("M15_S1"),
        "m15_bw": m15_levels.get("M15_BB_WIDTH"),
        "m15_close_pos": m15_close_position(m15_ohlc),
        "atr_m15": round(candidate["atr_m15"], 2),
        "sl_distance": candidate["sl_distance"],
        "exposure": candidate["exposure"],
        "max_lots": candidate["max_lots"],
    }


def format_signal_meta(meta):
    def num(key):
        value = to_float(meta.get(key))
        return "N/A" if value is None else f"{value:.2f}"

    def dist(key):
        price, level = to_float(meta.get("price")), to_float(meta.get(key))
        return "N/A" if price is None or level is None else f"{price - level:+.2f}"

    kind = "首單" if meta.get("kind") == "FIRST" else "加單"
    return (f"{meta.get('signal')} {kind} @ {num('price')} | 趨勢:{DIR_WORD.get(meta.get('trend_dir'), 'N/A')} | "
            f"RSI14(M1):{num('rsi_m1')} | M15 BB 上/中/下:{num('m15_r1')}/{num('m15_mid')}/{num('m15_s1')} "
            f"(帶寬 {num('m15_bw')}%) | 距上軌:{dist('m15_r1')} 距中軌:{dist('m15_mid')} 距下軌:{dist('m15_s1')} | "
            f"M15收盤位置:{num('m15_close_pos')} | ATR15:{num('atr_m15')} | SL距離:{num('sl_distance')} | "
            f"持倉:{num('exposure')}/{num('max_lots')}手")


def outcome_label(profit):
    if profit > BREAKEVEN_EPS:
        return "APPROVE"
    if profit < -BREAKEVEN_EPS:
        return "REJECT"
    return "BREAKEVEN"


class SFTDataPipeline:
    @staticmethod
    def get_trading_rules():
        try:
            text = gcs_read_text(TRADING_RULES_FILE)
        except StorageError as exc:
            print(f"⚠️ [規則庫讀取失敗] {exc}", flush=True)
            text = None
        body = text.strip()[:4000] if text and text.strip() else "目前無額外規則。"
        return "【自我反思與進化規則庫】\n" + body

    @staticmethod
    def get_dynamic_few_shot(limit=FEW_SHOT_LIMIT):
        """Last losing signals as compact one-liners WITH their outcome.  [R6 R6b]
        Legacy rows (without 'meta') are ignored, so old nested prompts never re-enter."""
        try:
            text = gcs_read_text(SFT_DATASET_FILE) or ""
        except StorageError as exc:
            print(f"⚠️ [SFT 讀取失敗] {exc}", flush=True)
            return ""
        lessons = []
        for row in reversed(jsonl_loads(text)[-300:]):
            if not isinstance(row, dict):
                continue
            meta, outcome = row.get("meta"), row.get("outcome")
            if not isinstance(meta, dict) or not isinstance(outcome, dict) or outcome.get("label") != "REJECT":
                continue
            lessons.append(f"- {format_signal_meta(meta)} → 實盤結算 {to_float(outcome.get('profit'), 0.0):+.2f}")
            if len(lessons) >= limit:
                break
        return ("【歷史虧損教訓 (Dynamic Few-Shot)】\n" + "\n".join(lessons)) if lessons else ""

    @staticmethod
    def save_pending_signal(meta, ai_verdict=None):
        item = {"id": uuid.uuid4().hex, "symbol": normalize_symbol(meta.get("symbol")), "ts": now_ts(), "meta": meta}
        if isinstance(ai_verdict, dict):
            item["ai_verdict"] = ai_verdict        # 平倉配對時一併寫進 SFT 資料集

        def mutate(queue):
            queue = queue if isinstance(queue, list) else []
            queue.append(item)
            cutoff = now_ts() - PENDING_TTL_SEC
            kept = [q for q in queue if to_float(q.get("ts"), 0) >= cutoff][-PENDING_MAX:]
            if len(kept) < len(queue):
                print(f"⚠️ [SFT 佇列] 丟棄 {len(queue) - len(kept)} 筆過期/超量待配對訊號", flush=True)
            return kept, None

        try:
            gcs_update(PENDING_SIGNALS_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [SFT 暫存失敗] {exc}", flush=True)

    @staticmethod
    def pair_trade_result(symbol, profit, ticket, entry_ts=None):
        """Match a closed deal to its entry signal. With entry_ts (UTC seconds) the
        latest pending signal sent before that time is used; otherwise FIFO.  [R24b]
        Limitation: one position closed in several partial deals consumes several signals."""
        target_symbol = normalize_symbol(symbol)

        def mutate(queue):
            queue = queue if isinstance(queue, list) else []
            indexes = [i for i, q in enumerate(queue) if q.get("symbol") == target_symbol]
            if not indexes:
                return None, None
            chosen = indexes[0]
            if entry_ts is not None:
                before = [i for i in indexes if to_float(queue[i].get("ts"), 0) <= entry_ts + 120]
                if before:
                    chosen = max(before, key=lambda i: to_float(queue[i].get("ts"), 0))
            item = queue.pop(chosen)
            return queue, item

        try:
            item = gcs_update(PENDING_SIGNALS_FILE, mutate, default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [SFT 配對失敗] {exc}", flush=True)
            return
        if not item or not isinstance(item.get("meta"), dict):
            return

        label = outcome_label(profit)
        example = {
            "contents": [
                {"role": "user", "parts": [{"text": format_signal_meta(item["meta"])}]},
                {"role": "model", "parts": [{"text": f"{label} | 實盤結算 {profit:+.2f}"}]},
            ],
            "meta": item["meta"],
            "outcome": {"label": label, "profit": profit, "ticket": ticket, "closed_utc": fmt_utc()},
        }
        if isinstance(item.get("ai_verdict"), dict):
            # 「AI 當時說了什麼」＋「實際賺賠」配成一對——ai_eval.py 算判別力就靠這個。
            example["ai_verdict"] = item["ai_verdict"]

        def append(rows):
            rows.append(example)
            return rows[-SFT_MAX_LINES:], None

        try:
            gcs_update(SFT_DATASET_FILE, append, loads=jsonl_loads, dumps=jsonl_dumps, default_factory=list)
        except StorageError as exc:
            print(f"⚠️ [SFT 寫入失敗] {exc}", flush=True)


sft_pipeline_session = SFTDataPipeline()


# =============================================================================
# 📦 Raw payload log
# =============================================================================
class WebhookLogSession:
    @staticmethod
    def save_payload(payload):
        entry = {"timestamp_utc": fmt_utc(), "payload": payload}

        def mutate(history):
            history = history if isinstance(history, list) else ([history] if isinstance(history, dict) else [])
            history.insert(0, entry)
            return history[:30], None

        try:
            gcs_update(WEBHOOK_LOG_FILE, mutate, dumps=lambda d: json.dumps(d, ensure_ascii=False, indent=2),
                       default_factory=list, reset_on_corrupt=True)
        except StorageError as exc:
            print(f"⚠️ [Payload 紀錄異常] {exc}", flush=True)

    @staticmethod
    def get_last_payload():
        try:
            data = gcs_read_json(WEBHOOK_LOG_FILE, [])
        except StorageError:
            return "封包紀錄讀取失敗。"
        if not data:
            return "尚未收到任何封包。"
        if not isinstance(data, list):
            return json.dumps(data, ensure_ascii=False, indent=2)
        blocks = []
        for idx, item in enumerate(data, 1):
            body = json.dumps(item.get("payload", {}), ensure_ascii=False, indent=2)
            blocks.append(f"// ────── 封包 #{idx} [{item.get('timestamp_utc', '未知時間')} UTC] ──────\n{body}")
        return "\n\n".join(blocks)


webhook_log_session = WebhookLogSession()


# =============================================================================
# 🗄️ 外部來源按日封存（MT5 M1、Futu K 線與期權）  [R95]
# -----------------------------------------------------------------------------
# M1 快取只留 M1_HISTORY_MAX（200）根 ≈ 3 小時，Futu 快照只留最新一次。
# 每日彙整（預設分支的 external_data_daily 工作流程）一天只拉一次，所以
# 另存一份按日切的封存：archive/<source>/<instrument>/<日期>.json。
# 日期用來源自己的時區：MT5 = 券商伺服器時間，Futu = 美東（time_key 本身）。
# ⚠️ 封存寫不進去只記 Log，絕不擋交易流程。
# =============================================================================
ARCHIVE_PREFIX = "archive"
ARCHIVE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARCHIVE_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def archive_blob_name(source, instrument, day):
    return (f"{ARCHIVE_PREFIX}/{ARCHIVE_SAFE_RE.sub('_', source)}/"
            f"{ARCHIVE_SAFE_RE.sub('_', instrument)}/{day}.json")


def archive_merge(source, instrument, day, rows, key_fields):
    """Merge rows into one day's archive by key (later rows win). Returns the row count.
    Raises StorageError."""
    if not rows or not ARCHIVE_DATE_RE.match(str(day)):
        return 0

    def key_of(row):
        return tuple(str(row.get(field)) for field in key_fields)

    def mutate(existing):
        merged = {key_of(row): row for row in (existing if isinstance(existing, list) else [])
                  if isinstance(row, dict)}
        before = dict(merged)
        for row in rows:
            merged[key_of(row)] = row
        if merged == before:
            return None, len(merged)
        ordered = [merged[key] for key in sorted(merged)]
        return ordered, len(ordered)

    return gcs_update(archive_blob_name(source, instrument, day), mutate, default_factory=list)


def archive_list(day):
    """{'<source>/<instrument>': rows} for every archive object of that day."""
    if not ARCHIVE_DATE_RE.match(str(day)):
        return {}
    suffix = f"/{day}.json"
    try:
        blobs = list(_bucket().list_blobs(prefix=f"{ARCHIVE_PREFIX}/", match_glob=f"**{suffix}"))
    except Exception as exc:
        raise StorageError(f"list {ARCHIVE_PREFIX}/: {exc}") from exc
    result = {}
    for blob in blobs:
        name = getattr(blob, "name", "")
        if not name.endswith(suffix):
            continue
        parts = name.split("/")
        if len(parts) != 4:
            continue
        rows = gcs_read_json(name, [])
        result[f"{parts[1]}/{parts[2]}"] = rows if isinstance(rows, list) else []
    return result


def handle_archive_api_get(req):
    day = str(req.args.get("date") or fmt_utc(fmt="%Y-%m-%d"))
    if not ARCHIVE_DATE_RE.match(day):
        return _json_response({"status": "error", "message": "date must be YYYY-MM-DD"}, 400)
    try:
        data = archive_list(day)
    except StorageError as exc:
        log_event(f"⚠️ [封存讀取失敗] {exc}", severity="ERROR", component="archive")
        return _json_response({"status": "error", "message": "storage read failed"}, 503)
    return _json_response({"status": "ok", "date": day, "generated_utc": fmt_utc(),
                           "series": {key: len(rows) for key, rows in data.items()},
                           "data": data}, 200)


def archive_mt5_bar(bar, symbol="XAUUSD"):
    """一根剛收盤的 M1（券商伺服器時間的 epoch 秒）→ archive/mt5_m1/<symbol>/<券商日期>.json。"""
    try:
        day = datetime.fromtimestamp(int(bar["time"]), UTC).strftime("%Y-%m-%d")
        row = {"time": int(bar["time"]),
               "time_server": datetime.fromtimestamp(int(bar["time"]), UTC).strftime("%Y-%m-%d %H:%M:%S"),
               "time_utc": fmt_utc(int(bar["time"]) - BROKER_UTC_OFFSET_HOURS * 3600),
               **{key: bar.get(key) for key in ("open", "high", "low", "close")}}
        archive_merge("mt5_m1", symbol, day, [row], ("time",))
    except Exception as exc:                        # never let archiving break the trading path
        print(f"⚠️ [MT5 封存失敗] {type(exc).__name__}: {exc}", flush=True)


# =============================================================================
# 📡 Futu OpenD 行情（本地 push_to_gcp.py 推上來的 K 線與期權 IV）  [R94]
# -----------------------------------------------------------------------------
# 之前 action=futu_data 沒有處理器：回 HTTP 200 + status "ignored"，資料直接丟掉，
# 本地腳本只看狀態碼就印「大滿貫成功」。現在：驗權杖 → 清洗 → 存 GCS →
# 回 status "stored"，控制台與 ?view=futu&format=json 看得到。
# ⚠️ 只存、只顯示：不進電閘、不進錦囊、不影響任何下單。QQQ 不是 XAUUSD，
#    要拿它當訊號之前先回測。
# =============================================================================
FUTU_SNAPSHOT_FILE = "futu/latest_snapshot.json"
FUTU_SYMBOL_DIR = "futu/snapshots"                                     # [R95] 每個代號一份最新快照
FUTU_MAX_BARS = max(1, _env_int("FUTU_MAX_BARS", 500))
FUTU_MAX_OPTIONS = 200
FUTU_STALE_SEC = max(60, _env_int("FUTU_STALE_SEC", 900))           # 推送間隔 300 秒 × 3
FUTU_BAR_FIELDS = ("open", "high", "low", "close", "volume")
FUTU_OPTION_FIELDS = ("strike", "iv", "delta", "gamma", "vega", "theta",
                      "last", "bid", "ask", "volume", "open_interest")


def _futu_text(value, max_len):
    return str(value if value is not None else "").strip()[:max_len]


def futu_clean_bars(raw):
    """Futu K 線（DataFrame.to_dict('records')）→ 依 time_key 排序、去重、只留最後 FUTU_MAX_BARS 根。"""
    if not isinstance(raw, list):
        return []
    bars = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        time_key = _futu_text(row.get("time_key") or row.get("time"), 19)
        close = to_float(row.get("close"))
        if not time_key or close is None:
            continue
        bar = {"time_key": time_key}
        bar.update({field: to_float(row.get(field)) for field in FUTU_BAR_FIELDS})
        bars[time_key] = bar                      # 同一根重複送 → 留最後一份
    return [bars[key] for key in sorted(bars)][-FUTU_MAX_BARS:]


def futu_clean_options(payload):
    """新版腳本送 options（清單，含 strike / iv / delta…）；舊版只送 options_iv {code: iv}。"""
    rows = []
    raw = payload.get("options")
    if isinstance(raw, list):
        for row in raw[:FUTU_MAX_OPTIONS]:
            if not isinstance(row, dict):
                continue
            code = _futu_text(row.get("code"), 40)
            if not code:
                continue
            item = {"code": code,
                    "option_type": _futu_text(row.get("option_type"), 4).upper(),
                    "expiry": _futu_text(row.get("expiry"), 10)}
            item.update({field: to_float(row.get(field)) for field in FUTU_OPTION_FIELDS})
            rows.append(item)
    legacy = payload.get("options_iv")
    if not rows and isinstance(legacy, dict):
        for code, iv in list(legacy.items())[:FUTU_MAX_OPTIONS]:
            code = _futu_text(code, 40)
            if code:
                rows.append({"code": code, "iv": to_float(iv)})
    return rows


def handle_futu_data(payload):
    """權杖已在 _dispatch_post 驗過。成功 → 200 stored；沒內容 → 422；寫不進 GCS → 503。"""
    symbol = _futu_text(payload.get("symbol"), 32).upper()
    if not symbol:
        return jsonify({"status": "error", "message": "futu_data: missing symbol"}), 422
    bars = futu_clean_bars(payload.get("data"))
    options = futu_clean_options(payload)
    if not bars and not options:
        return jsonify({"status": "error", "message": "futu_data: no usable bars or options"}), 422

    ivs = [row["iv"] for row in options if row.get("iv")]
    warnings = []
    if options and not ivs:
        warnings.append("所有期權 IV 都是 0 或空值（舊版腳本讀錯欄位名稱）")
    latest = bars[-1] if bars else {}
    snapshot = {
        "symbol": symbol,
        "source": _futu_text(payload.get("source"), 32) or "futu_opend",
        "kline_type": _futu_text(payload.get("kline_type"), 16),
        "client_time": _futu_text(payload.get("timestamp"), 32),
        "script_version": _futu_text(payload.get("script_version"), 16),
        "received_utc": fmt_utc(),
        "received_ts": now_ts(),
        "bars": bars,
        "options": options,
        "warnings": warnings,
    }
    daily = snapshot["kline_type"].upper() not in ("", "K_5M")    # [R96][R97][R100] 只有 5 分 K 更新即時快照
    try:
        if not daily:
            text = json.dumps(snapshot, ensure_ascii=False)
            gcs_write_text(FUTU_SNAPSHOT_FILE, text)
            gcs_write_text(futu_symbol_file(symbol), text)        # [R95] 多代號各一份
    except StorageError as exc:
        log_event(f"⚠️ [Futu 行情寫入失敗] {exc}", severity="ERROR", component="futu")
        return jsonify({"status": "error", "message": "storage write failed"}), 503
    warnings.extend(futu_archive(snapshot))
    if isinstance(payload.get("trading_calendar"), dict):              # [R99] 本地腳本送來的港股交易日曆
        warnings.extend(futu_calendar_save(payload["trading_calendar"]))
    if snapshot["kline_type"].upper() == "K_SESSION" and symbol.endswith(FUTU_SERIES_SUFFIX):
        warnings.extend(futu_daily_merge(symbol, bars, snapshot["source"]))
        warnings.extend(futu_forecast_log(symbol, bars))            # [R98] 當天預測只記一次
    if not daily and symbol.endswith(FUTU_SERIES_SUFFIX):            # [R101] 高低位是否已出現
        warnings.extend(futu_peak_update(symbol))
        warnings.extend(futu_paper_update(symbol))                   # [R116] 紙上交易跟新 K 線走

    log_event(f"📡 [Futu 行情] {symbol} K線 {len(bars)} 根（最新 {latest.get('time_key', '—')} "
              f"收 {fmt_num(latest.get('close'))}）期權 {len(options)} 檔（IV 有值 {len(ivs)}）",
              severity="WARNING" if warnings else "INFO", component="futu", symbol=symbol,
              bars=len(bars), options=len(options), iv_count=len(ivs))
    return jsonify({"status": "stored", "symbol": symbol, "bars": len(bars),
                    "latest_time": latest.get("time_key"), "latest_close": latest.get("close"),
                    "options": len(options), "iv_count": len(ivs), "warnings": warnings}), 200


def futu_symbol_file(symbol):
    return f"{FUTU_SYMBOL_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def futu_archive(snapshot):
    """K 線按 time_key 的日期（美東）分檔；期權每次推送記一列，日期跟最新 K 線同一天。
    回傳警告清單（封存失敗不影響 stored）。"""
    symbol = snapshot["symbol"]
    kline = (snapshot.get("kline_type") or "K_5M").lower()
    by_day = {}
    for bar in snapshot.get("bars") or []:
        by_day.setdefault(bar["time_key"][:10], []).append(bar)
    bars = snapshot.get("bars") or []
    option_day = bars[-1]["time_key"][:10] if bars else snapshot["received_utc"][:10]
    spot = bars[-1].get("close") if bars else None
    asof_ts = round(float(snapshot["received_ts"]), 3)
    option_rows = [{"asof_utc": snapshot["received_utc"], "asof_ts": asof_ts, "spot": spot, **row}
                   for row in snapshot.get("options") or []]
    try:
        for day, rows in by_day.items():
            archive_merge(f"futu_{kline}", symbol, day, rows, ("time_key",))
        archive_merge("futu_options", symbol, option_day, option_rows, ("asof_ts", "code"))
        return []
    except StorageError as exc:
        log_event(f"⚠️ [Futu 封存失敗] {exc}", severity="WARNING", component="futu")
        return ["按日封存寫入失敗（最新快照已存，下一次推送會補 K 線）"]


def read_futu_snapshot(symbol=None):
    try:
        data = gcs_read_json(futu_symbol_file(symbol) if symbol else FUTU_SNAPSHOT_FILE, {})
        return data if isinstance(data, dict) else {}
    except StorageError as exc:
        print(f"⚠️ [Futu 行情讀取失敗] {exc}", flush=True)
        return {"error": str(exc)}


def futu_age_sec(snap, now=None):
    received = to_float(snap.get("received_ts"))
    return None if received is None else max(0.0, (now or now_ts()) - received)


# =============================================================================
# 📏 即月期貨日線序列與波幅頁  [R97]
# =============================================================================
FUTU_DAILY_DIR = "futu/daily"
FUTU_SERIES_SUFFIX = "_FRONT"                    # 本地腳本 v6 的即月期貨別名
FUTU_DAILY_KEEP = 800                            # 約三年交易日
FUTU_RANGE_DEFAULT = "HK.HSI_FRONT"
FUTU_SESSION_CUT_HOUR = 9                        # 交易日 = 09:00 至翌日 09:00（日市＋當晚夜市）
HK_TZ = ZoneInfo("Asia/Hong_Kong")
NY_TZ = ZoneInfo("America/New_York")
# [R127] 市場設定：代號前綴 → 時區、交易日切法、文字。shift = 把當地時間加多少小時後取日期就是交易日
#   HK：09:00 起算同一天（日市＋當晚夜市）→ shift −9；US：CME 全段 18:00（前一天）至 17:00，日期取收市那天 → shift +6。
MARKETS = {
    "HK": {"tz": HK_TZ, "shift": -9, "calendar": True, "preopen": ("03:05", "09:15"), "end": (1, "03:00"),
           "zh": "恒指即月期貨", "title": "🌬️ 風揚陣・恒指即月期貨波幅", "view": "futu_range", "icon": "🌬️",
           "session_zh": "日市＋當晚夜市", "hours_zh": "交易日 = 日市 09:15–16:30 ＋ 當晚夜市至翌日 03:00",
           "day_zh": "香港時間 09:00 至翌日 09:00：日市 09:15–16:30 加當晚夜市 17:15–翌日 03:00（跟富途日 K 不同）",
           "open_zh": "09:15 開市後", "unit_zh": "恒指期貨每點 HK$50，小型恒指 HK$10", "intraday": True},
    "US": {"tz": NY_TZ, "shift": 6, "calendar": False, "preopen": ("18:00", "19:00"), "end": (0, "17:00"),
           "zh": "ES 標普 500 期貨", "title": "🇺🇸 風揚陣・ES 標普 500 期貨波幅", "view": "es_range", "icon": "🇺🇸",
           "session_zh": "CME 全段 23 小時", "hours_zh": "交易日 = CME 全段：紐約時間前一天 18:00 至當天 17:00（香港 06:00／07:00 至翌日 05:00／06:00）",
           "day_zh": "紐約時間前一天 18:00 至當天 17:00（CME 全段 23 小時），日期取收市那天；數據是 yfinance 的連續合約日線，轉月不做價差調整",
           "open_zh": "有 5 分 K 推送後", "unit_zh": "ES 每點 US$50，小型 MES US$5", "intraday": False},
}
ES_SYMBOL = "US.ES_FRONT"


def futu_market(symbol=None):
    return MARKETS["US" if str(symbol or "").upper().startswith("US.") else "HK"]


def futu_session_today(now=None, symbol=None):
    """現在屬於哪個交易日（HK：香港時間 09:00 前算前一天；US：紐約時間 18:00 起算下一天）。"""
    m = futu_market(symbol)
    t = (now or datetime.now(timezone.utc)).astimezone(m["tz"])
    return (t + timedelta(hours=m["shift"])).strftime("%Y-%m-%d")


def futu_session_end_passed(day, now, symbol=None):
    """[R127] 交易日 day 的收市時間過了沒有（HK：翌日 03:00 香港時間；US：當天 17:00 紐約時間）。"""
    m = futu_market(symbol)
    t = (now or datetime.now(timezone.utc)).astimezone(m["tz"])
    end = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=m["end"][0])).strftime("%Y-%m-%d") + " " + m["end"][1]
    return t.strftime("%Y-%m-%d %H:%M") >= end


def futu_daily_file(symbol):
    return f"{FUTU_DAILY_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def futu_daily_merge(symbol, bars, source):
    """日 K 依日期合併進 futu/daily/<代號>.json（後到的蓋掉同一天）。回傳警告清單。"""
    rows = [{**bar, "time_key": bar["time_key"][:10], "source": source}
            for bar in bars if ARCHIVE_DATE_RE.match(bar["time_key"][:10])]
    if not rows:
        return []

    def mutate(existing):
        merged = {row.get("time_key"): row for row in (existing if isinstance(existing, list) else [])
                  if isinstance(row, dict)}
        before = dict(merged)
        merged.update({row["time_key"]: row for row in rows})
        if merged == before:
            return None, len(merged)
        ordered = [merged[key] for key in sorted(merged)][-FUTU_DAILY_KEEP:]
        return ordered, len(ordered)

    try:
        gcs_update(futu_daily_file(symbol), mutate, default_factory=list)
        return []
    except StorageError as exc:
        log_event(f"⚠️ [Futu 日線序列寫入失敗] {exc}", severity="WARNING", component="futu")
        return ["日線序列寫入失敗（按日封存已存，下一次推送會補）"]


def futu_range_rows(bars):
    """交易日 K → 每天一列（含昨收算出的波幅%、真實波幅、漲跌）。"""
    rows, prev_close = [], None
    for bar in bars:
        o, h, l, c = (to_float(bar.get(k)) for k in ("open", "high", "low", "close"))
        day = str(bar.get("time_key", ""))[:10]
        if None in (o, h, l, c) or not ARCHIVE_DATE_RE.match(day):
            continue
        rng = h - l
        tr = max(h, prev_close) - min(l, prev_close) if prev_close else rng
        rows.append({"date": day, "open": o, "high": h, "low": l, "close": c,
                     "volume": to_float(bar.get("volume")), "source": bar.get("source") or "",
                     "range": round(rng, 2), "true_range": round(tr, 2),
                     "range_pct": round(rng / prev_close * 100, 3) if prev_close else None,
                     "prev_close": prev_close,
                     "change": round(c - prev_close, 2) if prev_close else None})
        prev_close = c
    return rows


# ---- HAR 波幅預測  [R98] ------------------------------------------------------
# 回測（research/hsi_futures_range/）：恒指指數 2012 起 3,628 天，HAR（對數）對 20 日平均顯著較好
# （Diebold-Mariano p<0.001），80% 區間命中 81%；期貨 194 天各策略分不出高下。
# ln r_t = b0 + b1·ln r_{t−1} + b5·ln 平均(r_{t−5..t−1}) + b22·ln 平均(r_{t−22..t−1})，r = 波幅 ÷ 昨收。
# 每天只用之前的數據重新擬合（擴展視窗），預測 = exp(擬合值) × 殘差平滑係數，80% 區間 = 殘差 10%／90% 分位。
HAR_MIN_DAYS = 60
HAR_RESID_WINDOW = 500
FENGYANG_TAG = "【風揚陣】"                      # [R102] 八陣登記名，Telegram 訊息開頭


def _solve_linear(a, y):
    """小型線性方程組（高斯消去，部分選主元）。奇異 → None。"""
    n = len(y)
    m = [list(a[i]) + [y[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(m[i][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for i in range(col + 1, n):
            f = m[i][col] / m[col][col]
            for j in range(col, n + 1):
                m[i][j] -= f * m[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def _quantile(sorted_values, q):
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def har_forecasts(rows, last_n=None):
    """rows：已完結的交易日（依日期）。逐日前推：位置 t 的預測只用 t 之前的列。
    回傳 {位置 t: (預測點數, 80% 下限, 80% 上限)}；t = len(rows) 是下一個交易日。
    last_n：只算最後 last_n 個位置（擬合仍用全部歷史）。"""
    keep = [i for i, row in enumerate(rows) if row.get("range_pct") and row["range_pct"] > 0]
    n = len(keep)
    if n < HAR_MIN_DAYS:
        return {}
    r = [rows[i]["range_pct"] / 100 for i in keep]
    lr = [math.log(x) for x in r]

    def feat(t):
        return [1.0, lr[t - 1], math.log(sum(r[t - 5:t]) / 5), math.log(sum(r[t - 22:t]) / 22)]

    xtx = [[0.0] * 4 for _ in range(4)]
    xty = [0.0] * 4
    feats, out = {}, {}
    first = max(HAR_MIN_DAYS, n + 1 - last_n) if last_n else HAR_MIN_DAYS
    for t in range(22, n + 1):
        if t >= first:
            beta = _solve_linear(xtx, xty)
            if beta is not None:
                start = max(22, t - HAR_RESID_WINDOW)
                res = sorted(lr[s] - sum(a * b for a, b in zip(feats[s], beta)) for s in range(start, t))
                smear = sum(math.exp(e) for e in res) / len(res)
                fitted = sum(a * b for a, b in zip(feat(t), beta))
                ref = rows[keep[t]]["prev_close"] if t < n else rows[-1]["close"]     # 昨收
                out[keep[t] if t < n else len(rows)] = (round(math.exp(fitted) * smear * ref, 1),
                                   round(math.exp(fitted + _quantile(res, 0.10)) * ref, 1),
                                   round(math.exp(fitted + _quantile(res, 0.90)) * ref, 1))
        if t < n:
            x = feats[t] = feat(t)
            for i in range(4):
                xty[i] += x[i] * lr[t]
                for j in range(4):
                    xtx[i][j] += x[i] * x[j]
    return out


def futu_range_stats(bars, today):
    """交易日 K（已排序）→ 每天的波幅與過去一年的統計。today：目前的交易日 YYYY-MM-DD。
    波幅 = 高 − 低；真實波幅 TR = max(高, 昨收) − min(低, 昨收)；波幅% = 波幅 ÷ 昨收。
    日期 ≥ today 的最後一根還在交易（日市或當晚夜市未完），不進平均。"""
    since = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    all_rows = futu_range_rows(bars)
    all_partial = bool(all_rows) and all_rows[-1]["date"] >= today
    completed = all_rows[:-1] if all_partial else all_rows
    shown = sum(1 for row in completed if row["date"] >= since)
    har = har_forecasts(completed)                                # [R98] 逐日前推的 HAR 預測（[R104] 全部歷史，給命中率用）
    for i, row in enumerate(completed):
        if i in har:
            row["forecast"], row["forecast_lo"], row["forecast_hi"] = har[i]
    nxt = har.get(len(completed))
    if all_partial and nxt:
        all_rows[-1]["forecast"], all_rows[-1]["forecast_lo"], all_rows[-1]["forecast_hi"] = nxt
    rows = [row for row in all_rows if row["date"] >= since]
    partial = all_partial
    done = rows[:-1] if partial else rows
    ranges = sorted(row["range"] for row in done)

    def avg(values):
        return round(sum(values) / len(values), 2) if values else None

    last = done[-1] if done else None
    summary = {
        "days": len(done),
        "first_date": done[0]["date"] if done else None,
        "last_date": last["date"] if last else None,
        "avg_range": avg(ranges),
        "median_range": (ranges[len(ranges) // 2] if len(ranges) % 2 else
                         round((ranges[len(ranges) // 2 - 1] + ranges[len(ranges) // 2]) / 2, 2)) if ranges else None,
        "avg_range_20": avg([row["range"] for row in done[-20:]]),
        "atr_14": avg([row["true_range"] for row in done[-14:]]),
        "avg_range_pct": avg([row["range_pct"] for row in done if row["range_pct"] is not None]),
        "max_range": max(done, key=lambda row: row["range"]) if done else None,
        "min_range": min(done, key=lambda row: row["range"]) if done else None,
        "year_high": max((row["high"] for row in done), default=None),
        "year_low": min((row["low"] for row in done), default=None),
        "last_range_percentile": (round(sum(1 for r in ranges if r <= last["range"]) / len(ranges) * 100)
                                  if last and ranges else None),
    }
    tested = [row for row in done if row.get("forecast")]
    errors = [row["forecast"] - row["range"] for row in tested]
    backtest = {
        "days": len(tested),
        "mae": avg([abs(e) for e in errors]),
        "bias": avg(errors),
        "coverage_80": (round(sum(1 for row in tested if row["forecast_lo"] <= row["range"] <= row["forecast_hi"])
                              / len(tested) * 100) if tested else None),
    }
    forecast = None
    if nxt:
        forecast = {"date": all_rows[-1]["date"] if all_partial else "next", "range": nxt[0], "lo": nxt[1], "hi": nxt[2],
                    "ref_close": completed[-1]["close"] if completed else None, "model": "HAR(1,5,22) 對數"}
    return {"rows": rows, "partial": partial, "summary": summary, "forecast": forecast, "backtest": backtest,
            "_completed": completed, "_har": har}


FUTU_FORECAST_DIR = "futu/forecast"
FUTU_FORECAST_KEEP = 1000


def futu_forecast_file(symbol):
    return f"{FUTU_FORECAST_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def futu_forecast_log(symbol, bars, now=None):
    """目前交易日的第一包交易日 K 到達時，若開市前沒記到預測，補記一次（之後不改）。回傳警告清單。"""
    today = futu_session_today(now, symbol)
    if not any(str(bar.get("time_key", ""))[:10] == today for bar in bars):
        return []
    try:
        futu_forecast_record(symbol, today)
        return []
    except StorageError as exc:
        log_event(f"⚠️ [波幅預測紀錄失敗] {exc}", severity="WARNING", component="futu")
        return ["波幅預測紀錄失敗（下一包會再試）"]


def futu_forecast_track(log, rows):
    """實時紀錄對照實際：只算已完結的交易日。"""
    actual = {row["date"]: row["range"] for row in rows}
    by_date = {row["date"]: row for row in rows}
    pairs = [(e, actual[e["date"]]) for e in log if isinstance(e, dict) and e.get("date") in actual]
    if not pairs:
        return {"days": 0, "entries": [e for e in log if isinstance(e, dict)][-10:]}
    errs = [e["range"] - a for e, a in pairs]
    out = {"days": len(pairs), "mae": round(sum(abs(x) for x in errs) / len(errs), 1),
           "bias": round(sum(errs) / len(errs), 1),
           "coverage_80": round(sum(1 for e, a in pairs if e["lo"] <= a <= e["hi"]) / len(pairs) * 100),
           "entries": [e for e in log if isinstance(e, dict)][-10:]}
    hl = [(e, by_date[e["date"]]) for e, _ in pairs if e.get("high") is not None]     # [R99] 高低位
    if hl:
        out.update(hl_days=len(hl),
                   high_mae=round(sum(abs(e["high"] - row["high"]) for e, row in hl) / len(hl), 1),
                   low_mae=round(sum(abs(e["low"] - row["low"]) for e, row in hl) / len(hl), 1))
    return out


# ---- 高低位預測與四個時點的檢討  [R99] ----------------------------------------
HL_MIN_DAYS = 120                               # 估高低位比例至少要這麼多天的逐日前推預測
HL_BAND_Q = 0.02                                # [R119] 高位／低位預計範圍的分位（2%／98% → 每邊約 96%、兩邊同時約 92%）
HL_BAND_ZH = "二十次有十九次落在這裡"            # 白話（每邊）
HL_BAND_Q_PERIOD = 0.01                         # [R123] 本週／本月用 1%／99% 分位（段數少，約等於歷史極值）
HL_OK_PCT_BY = {"day": 1.0, "week": 2.0, "month": 4.0}   # [R125][R126] 實際與預測相差這個百分比以內才算 ✓


def _hl_band_q(kind):
    return HL_BAND_Q if kind == "day" else HL_BAND_Q_PERIOD
FUTU_CALENDAR_FILE = "futu/calendar/HK.json"
FUTU_REVIEW_DIR = "futu/reviews"
FUTU_REVIEW_KEEP = 2000
WEEKDAY_ZH = "一二三四五六日"
REVIEW_KINDS = {                                # 種類：(圖示, 標題, 截止時間)
    "noon": ("🕛", "午市收市檢討", "12:00"),
    "close": ("🕟", "日市收市檢討", "16:30"),
    "night": ("🌙", "全日收市檢討（日市＋夜市）", None),
}
PREOPEN_WINDOW = ("03:05", "09:15")             # 開市前預測只在這段時間記錄（前一天夜市已收、今天未開）


def futu_review_file(symbol):
    return f"{FUTU_REVIEW_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def futu_calendar_save(cal):
    """{'from', 'to', 'days': [...]} → futu/calendar/HK.json（內容沒變就不寫）。回傳警告清單。"""
    days = sorted({d for d in (cal.get("days") or []) if isinstance(d, str) and ARCHIVE_DATE_RE.match(d)})
    start, end = str(cal.get("from", "")), str(cal.get("to", ""))
    if not (ARCHIVE_DATE_RE.match(start) and ARCHIVE_DATE_RE.match(end)):
        return []
    new = {"market": "HK", "from": start, "to": end, "days": days}

    def mutate(existing):
        old = {k: existing.get(k) for k in new} if isinstance(existing, dict) else {}
        return (None, 0) if old == new else ({**new, "updated_utc": fmt_utc()}, 1)

    try:
        gcs_update(FUTU_CALENDAR_FILE, mutate, default_factory=dict)
        return []
    except StorageError as exc:
        log_event(f"⚠️ [交易日曆寫入失敗] {exc}", severity="WARNING", component="futu")
        return ["交易日曆寫入失敗"]


def futu_trading_day(day, calendar):
    """日曆涵蓋的日子照日曆；沒涵蓋（腳本未更新）就把週一至五當交易日。"""
    if isinstance(calendar, dict) and str(calendar.get("from", "9")) <= day <= str(calendar.get("to", "")):
        return day in set(calendar.get("days") or [])
    return datetime.strptime(day, "%Y-%m-%d").weekday() < 5


def futu_session_of(time_key, symbol=None):
    """5 分 K 時間（當地時間）→ 交易日（HK：09:00 前算前一天；US：18:00 起算下一天）。"""
    t = datetime.strptime(str(time_key)[:19], "%Y-%m-%d %H:%M:%S")
    return (t + timedelta(hours=futu_market(symbol)["shift"])).strftime("%Y-%m-%d")


def futu_day_forecast(completed, target):
    """completed：target 之前已完結的交易日。回傳波幅與高位／低位預測；數據不足 → None。
    高位 = 昨收 + a×R̂，低位 = 昨收 − b×R̂；a、b = 過去每天（高−昨收）÷R̂、（昨收−低）÷R̂ 的中位數（逐日前推），
    預計範圍取同一組比例的 HL_BAND_Q／1−HL_BAND_Q 分位（R119 起 2%／98%）。回測見 research/hsi_futures_range/RESULTS.md。"""
    har = har_forecasts(completed)
    nxt = har.get(len(completed))
    if not nxt:
        return None
    rng, lo, hi = nxt
    ref = completed[-1]["close"]
    out = {"date": target, "range": rng, "lo": lo, "hi": hi, "ref_close": ref,
           "model": "HAR(1,5,22) 對數", "days_used": len(completed)}
    past = [har[i][0] for i in range(max(0, len(completed) - PAPER_GATE_LOOKBACK), len(completed)) if i in har]
    if len(past) >= PAPER_GATE_MIN_DAYS:                              # [R118] 波幅開閘：今日 R̂ ÷ 過去 250 日 R̂ 中位
        med = _quantile(sorted(past), 0.5)
        out.update(rhat_med250=round(med, 1), gate_ratio=round(rng / med, 3), gate_open=bool(rng >= PAPER_GATE_TH * med))
    ups, downs = [], []
    for i, row in enumerate(completed):
        f = har.get(i)
        if f and row.get("prev_close"):
            ups.append((row["high"] - row["prev_close"]) / f[0])
            downs.append((row["prev_close"] - row["low"]) / f[0])
    if len(ups) >= HL_MIN_DAYS:
        su, sd = sorted(ups), sorted(downs)
        q = HL_BAND_Q
        out.update(high=round(ref + _quantile(su, 0.5) * rng), high_lo=round(ref + _quantile(su, q) * rng),
                   high_hi=round(ref + _quantile(su, 1 - q) * rng), low=round(ref - _quantile(sd, 0.5) * rng),
                   low_lo=round(ref - _quantile(sd, 1 - q) * rng), low_hi=round(ref - _quantile(sd, q) * rng), band_q=q,
                   high_edge95=round(ref + _quantile(su, 0.95) * rng),            # [R116] 九成日範圍邊（紙上交易止蝕）
                   low_edge95=round(ref - _quantile(sd, 0.95) * rng))
    return out


def futu_series_rows(symbol):
    series = gcs_read_json(futu_daily_file(symbol), [])
    return futu_range_rows(sorted((b for b in series if isinstance(b, dict)),
                                  key=lambda b: str(b.get("time_key", ""))))


def futu_logged_forecast(symbol, day):
    log = gcs_read_json(futu_forecast_file(symbol), [])
    return next((e for e in reversed(log if isinstance(log, list) else [])
                 if isinstance(e, dict) and e.get("date") == day), None)


def futu_forecast_record(symbol, target):
    """記下 target 那天開始前的預測（每天一次、之後不改）。已有就回傳舊的；數據不足 → None。"""
    old = futu_logged_forecast(symbol, target)
    if old:
        return old
    completed = [row for row in futu_series_rows(symbol) if row["date"] < target]
    fc = futu_day_forecast(completed, target)
    if not fc:
        return None
    fc["made_utc"] = fmt_utc()

    def mutate(existing):
        items = [e for e in (existing if isinstance(existing, list) else []) if isinstance(e, dict)]
        if any(e.get("date") == target for e in items):
            return None, len(items)
        items = sorted(items + [fc], key=lambda e: e["date"])[-FUTU_FORECAST_KEEP:]
        return items, len(items)

    gcs_update(futu_forecast_file(symbol), mutate, default_factory=list)
    log_event(f"🔮 [波幅預測] {symbol} {target} HAR {fc['range']:,.0f} 點（80%：{fc['lo']:,.0f}–{fc['hi']:,.0f}）"
              + (f" 高 {fc['high']:,} 低 {fc['low']:,}" if fc.get("high") is not None else ""),
              component="futu", symbol=symbol)
    return futu_logged_forecast(symbol, target) or fc


def futu_session_5m(symbol, day):
    """某交易日的 5 分 K（日市＋當晚夜市，含翌日凌晨），只取有成交的，依時間排序。"""
    nxt = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    bars = []
    for d in (day, nxt):
        bars += [b for b in gcs_read_json(archive_blob_name("futu_k_5m", symbol, d), []) if isinstance(b, dict)]
    out = {b["time_key"]: b for b in bars if b.get("time_key") and to_float(b.get("volume"))
           and futu_session_of(b["time_key"], symbol) == day}
    return [out[k] for k in sorted(out)]


def _day_label(day):
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.month}-{d.day:02d}（{WEEKDAY_ZH[d.weekday()]}）"


def _ohlc(bars):
    return (bars[0]["open"], max(b["high"] for b in bars), min(b["low"] for b in bars), bars[-1]["close"])


def _level_line(name, actual, fc, band_lo, band_hi, upper, final):
    """高位（upper=True）／低位的比較句。final：全日收市，報誤差與是否在預計範圍。"""
    if final:
        ok = band_lo <= actual <= band_hi
        return (f"{name} {actual:,.0f}，預測 {fc:,.0f}（誤差 {actual - fc:+,.0f}），"
                f"{'✅ 在' if ok else '❌ 不在'} 預計範圍 {band_lo:,.0f}–{band_hi:,.0f}")
    beyond = actual >= fc if upper else actual <= fc
    edge = band_hi if upper else band_lo
    out_of_band = actual > band_hi if upper else actual < band_lo
    if beyond:
        return (f"{name} {actual:,.0f}：已{'越過' if upper else '跌穿'}預測 {fc:,.0f}"
                + (f"，並超出預計範圍（{edge:,.0f}）" if out_of_band else f"（預計範圍到 {edge:,.0f}）"))
    return f"{name} {actual:,.0f}：未到預測 {fc:,.0f}（差 {abs(fc - actual):,.0f} 點）"


def futu_preopen_text(fc, day, contract, summary, peak=None):
    lines = [f"📏{FENGYANG_TAG}恒指即月期貨 {_day_label(day)} 開市前預測",
             f"參考：上個交易日收市 {fc['ref_close']:,.0f}" + (f"（{contract}）" if contract else ""),
             f"全日波幅（日市＋夜市）：約 {fc['range']:,.0f} 點（80%：{fc['lo']:,.0f}–{fc['hi']:,.0f}）"]
    if fc.get("gate_ratio") is not None:                                # [R118]
        lines.append(f"波幅開閘：{_paper_gate_text(fc)}（過去 {PAPER_GATE_LOOKBACK} 日 R̂ 中位 {fc['rhat_med250']:,.0f} 點；紙上交易今日張數）")
    if fc.get("high") is not None:
        lines += [f"高位：約 {fc['high']:,.0f}（預計範圍 {fc['high_lo']:,.0f}–{fc['high_hi']:,.0f}）",
                  f"低位：約 {fc['low']:,.0f}（預計範圍 {fc['low_lo']:,.0f}–{fc['low_hi']:,.0f}，{HL_BAND_ZH}）"]
    if summary:
        lines.append(f"近 20 日平均波幅 {summary.get('avg_range_20') or 0:,.0f} 點；"
                     f"模型過去一年平均誤差 ±{summary.get('bt_mae') or 0:,.0f} 點")
    lines += peak or []
    lines.append("統計估計，不是交易建議。")
    return "\n".join(lines)


def futu_review(kind, day, fc, bars, track=None, peak=None):
    """四個時點中的三個檢討；沒有這一天的 K 線（休市）→ None。"""
    icon, title, cut = REVIEW_KINDS[kind]
    seg = [b for b in bars if b["time_key"] <= f"{day} {cut}:00"] if cut else bars
    if not seg:
        return None
    o, h, l, c = _ohlc(seg)
    rng = h - l
    label = {"noon": "上午", "close": "日市", "night": "全日"}[kind]
    lines = [f"{icon}{FENGYANG_TAG}恒指即月期貨 {_day_label(day)} {title}",
             f"{label}：開 {o:,.0f}　高 {h:,.0f}　低 {l:,.0f}　收 {c:,.0f}"]
    if kind == "night":
        day_seg = [b for b in bars if b["time_key"] <= f"{day} 16:30:00"]
        night_seg = [b for b in bars if b["time_key"] > f"{day} 16:30:00"]
        if day_seg and night_seg:
            lines.append(f"日市 高 {max(b['high'] for b in day_seg):,.0f} 低 {min(b['low'] for b in day_seg):,.0f}；"
                         f"夜市 高 {max(b['high'] for b in night_seg):,.0f} 低 {min(b['low'] for b in night_seg):,.0f}")
    numbers = {"open": o, "high": h, "low": l, "close": c, "range": rng, "bars": len(seg)}
    if fc:
        if kind == "night":
            ok = fc["lo"] <= rng <= fc["hi"]
            lines.append(f"全日波幅 {rng:,.0f} 點，預測 {fc['range']:,.0f}（誤差 {rng - fc['range']:+,.0f}），"
                         f"{'✅ 在' if ok else '❌ 不在'} 80% 區間 {fc['lo']:,.0f}–{fc['hi']:,.0f}")
            numbers.update(range_error=round(rng - fc["range"], 1), range_in_band=ok)
        else:
            lines.append(f"波幅 {rng:,.0f} 點，已走全日預測 {fc['range']:,.0f} 的 {rng / fc['range'] * 100:.0f}%")
            numbers["used_pct"] = round(rng / fc["range"] * 100, 1)
        if fc.get("high") is not None:
            final = kind == "night"
            lines.append(_level_line("高位", h, fc["high"], fc["high_lo"], fc["high_hi"], True, final))
            lines.append(_level_line("低位", l, fc["low"], fc["low_lo"], fc["low_hi"], False, final))
            if final:
                numbers.update(high_error=round(h - fc["high"], 1), low_error=round(l - fc["low"], 1))
    else:
        lines.append(f"波幅 {rng:,.0f} 點（這一天沒有開市前預測紀錄）")
    if kind == "night" and track and track.get("days"):
        tail = (f"；高位 ±{track['high_mae']:,.0f}、低位 ±{track['low_mae']:,.0f}" if track.get("hl_days") else "")
        lines.append(f"實時紀錄 {track['days']} 天：波幅誤差 ±{track['mae']:,.0f}，命中 {track['coverage_80']}%{tail}")
    lines += peak or []
    lines.append("統計估計，不是交易建議。")
    return {"date": day, "kind": kind, "made_utc": fmt_utc(), "text": "\n".join(lines), **numbers}


def futu_review_save(symbol, review):
    def mutate(existing):
        items = [e for e in (existing if isinstance(existing, list) else []) if isinstance(e, dict)
                 and not (e.get("date") == review["date"] and e.get("kind") == review["kind"])]
        items = sorted(items + [review], key=lambda e: (e["date"], list(REVIEW_KINDS).index(e["kind"])))
        return items[-FUTU_REVIEW_KEEP:], len(items)
    gcs_update(futu_review_file(symbol), mutate, default_factory=list)


def futu_report(symbol, kind, now=None):
    """GitHub 排程呼叫：回 {'status': ok|skip, 'text': ...}。"""
    market = futu_market(symbol)                                      # [R127]
    now_hk = (now or datetime.now(timezone.utc)).astimezone(market["tz"])
    hhmm = now_hk.strftime("%H:%M")
    rows = futu_series_rows(symbol)
    snap = read_futu_snapshot(symbol)
    contract = str(snap.get("source") or "").partition(":")[2] if isinstance(snap, dict) else ""
    if kind == "preopen":
        day = futu_session_today(now, symbol) if not market["calendar"] else now_hk.strftime("%Y-%m-%d")
        if not futu_trading_day(day, gcs_read_json(FUTU_CALENDAR_FILE, {}) if market["calendar"] else {}):
            return {"status": "skip", "reason": f"{day} 不是交易日"}
        if market["preopen"][0] <= hhmm < market["preopen"][1]:
            fc = futu_forecast_record(symbol, day)
        else:                                       # 不在時段內只預覽、不記錄（前一天夜市可能未收）
            fc = futu_logged_forecast(symbol, day) or futu_day_forecast([r for r in rows if r["date"] < day], day)
        if not fc:
            return {"status": "skip", "reason": f"已完結交易日不足 {HAR_MIN_DAYS} 天"}
        stats = futu_range_stats([dict(time_key=r["date"] + " 00:00:00", **{k: r[k] for k in
                                  ("open", "high", "low", "close", "volume", "source")}) for r in rows if r["date"] < day], day)
        summary = {"avg_range_20": stats["summary"].get("avg_range_20"), "bt_mae": stats["backtest"].get("mae")}
        return {"status": "ok", "kind": kind, "date": day, "forecast": fc,
                "text": futu_preopen_text(fc, day, contract, summary, futu_peak_lines(symbol, now) + futu_paper_lines(symbol))}
    if kind not in REVIEW_KINDS:
        return {"status": "error", "reason": "report 只接受 preopen、noon、close、night"}
    day = futu_session_today(now, symbol)
    bars = futu_session_5m(symbol, day)
    fc = futu_logged_forecast(symbol, day)
    log = gcs_read_json(futu_forecast_file(symbol), [])
    done = [r for r in rows if r["date"] <= day] if kind == "night" else [r for r in rows if r["date"] < day]
    track = futu_forecast_track(log if isinstance(log, list) else [], done) if kind == "night" else None
    review = futu_review(kind, day, fc, bars, track,
                         futu_peak_lines(symbol, now) + futu_paper_lines(symbol, bars[-1]["close"] if bars else None))
    if not review:
        return {"status": "skip", "reason": f"{day} 沒有 5 分 K（休市或推送停了）"}
    futu_review_save(symbol, review)
    return {"status": "ok", **review}



# ---- 高低位是否已出現：A 耗盡回落、B 機率法、C 時間點  [R101] ----------------------
# 回測（research/hsi_futures_range/HIGH_LOW_IN_REPORT.md，2023-12 至 2026-10 的 15 分 K）：
# B 在日、週、月都校準良好（準確率 ≈ 1 − p）；A、C 準確率 82–100%，但只在約四成的段會觸發。
PEAK_A = (0.8, 0.5)                              # 已走 ≥ 0.8×R̂ 且回落 ≥ 0.5×R̂
PEAK_B = 0.05                                    # 再創新高（低）機率 < 5%
PEAK_C_BETA = 0.4                                # 到時間點時回落 ≥ 0.4×R̂
PEAK_C_CUT = {"day": "16:30", "week": 4, "month": 15}   # 日 16:30；週第 4 個、月第 15 個交易日收市
PEAK_KINDS = ("day", "week", "month")
PEAK_ZH = {"day": "今日", "week": "本週", "month": "本月"}
PEAK_STRAT_ZH = {"A": "A 耗盡回落", "B": "B 機率法", "C": "C 時間點"}
# 週、月預測波幅 = 第一天 HAR 預測 × √交易日數 × 比例；比例取 2023-12 至 2026-09 實際 ÷ 預測 的 10%／50%／90% 分位
# （逐段前推回測：週 MAE 312 點、80% 區間命中 79%（130 週）；月 MAE 763 點、命中 71%（21 個月））
PERIOD_RANGE_RATIO = {"week": (0.627, 0.957, 1.537), "month": (0.665, 1.038, 1.671)}
FUTU_SIGNAL_DIR = "futu/signals"
FUTU_SIGNAL_KEEP = 3000
# 各 15 分鐘時段佔一個交易日變異的比例（2025-09 至 2026-10 的 250 個交易日估；鍵是 K 線結束時間）
PEAK_PROFILE_15M = {
    "09:30": 0.0609,
    "09:45": 0.13309,
    "10:00": 0.04394,
    "10:15": 0.0399,
    "10:30": 0.03277,
    "10:45": 0.02775,
    "11:00": 0.02391,
    "11:15": 0.0185,
    "11:30": 0.01814,
    "11:45": 0.01386,
    "12:00": 0.00612,
    "13:15": 0.03183,
    "13:30": 0.0177,
    "13:45": 0.01765,
    "14:00": 0.0181,
    "14:15": 0.01493,
    "14:30": 0.00984,
    "14:45": 0.01133,
    "15:00": 0.00723,
    "15:15": 0.01311,
    "15:30": 0.00881,
    "15:45": 0.00669,
    "16:00": 0.00599,
    "16:15": 0.00898,
    "16:30": 0.00668,
    "17:15": 0.01056,
    "17:30": 0.0203,
    "17:45": 0.00474,
    "18:00": 0.00459,
    "18:15": 0.0063,
    "18:30": 0.00373,
    "18:45": 0.00447,
    "19:00": 0.0026,
    "19:15": 0.03589,
    "19:30": 0.00484,
    "19:45": 0.00474,
    "20:00": 0.00391,
    "20:15": 0.00523,
    "20:30": 0.00723,
    "20:45": 0.01292,
    "21:00": 0.00526,
    "21:15": 0.00645,
    "21:30": 0.00528,
    "21:45": 0.02831,
    "22:00": 0.01787,
    "22:15": 0.0133,
    "22:30": 0.01029,
    "22:45": 0.0215,
    "23:00": 0.01764,
    "23:15": 0.02055,
    "23:30": 0.02087,
    "23:45": 0.01169,
    "00:00": 0.00949,
    "00:15": 0.00673,
    "00:30": 0.00794,
    "00:45": 0.00899,
    "01:00": 0.00561,
    "01:15": 0.00839,
    "01:30": 0.00756,
    "01:45": 0.00633,
    "02:00": 0.00499,
    "02:15": 0.00803,
    "02:30": 0.00435,
    "02:45": 0.0051,
    "03:00": 0.00769,
}
# 固定參數的回測準確率（B 用全部樣本；A、C 用後半段測試期）：期間/邊/策略
PEAK_ACCURACY = {
    "day/high/A": 0.912,
    "day/high/B": 0.958,
    "day/high/C": 0.897,
    "day/low/A": 0.923,
    "day/low/B": 0.949,
    "day/low/C": 0.931,
    "week/high/A": 0.971,
    "week/high/B": 0.95,
    "week/high/C": 1.0,
    "week/low/A": 0.941,
    "week/low/B": 0.957,
    "week/low/C": 1.0,
    "month/high/A": 0.818,
    "month/high/B": 0.97,
    "month/high/C": 0.833,
    "month/low/A": 0.818,
    "month/low/B": 1.0,
    "month/low/C": 0.9,
}


def futu_signal_file(symbol):
    return f"{FUTU_SIGNAL_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def _session_minutes(time_key):
    """交易日內的分鐘數（09:00 = 0，翌日 03:00 = 1080）。"""
    t = str(time_key)[11:16] if len(str(time_key)) > 5 else str(time_key)
    return ((int(t[:2]) - 9) % 24) * 60 + int(t[3:5])


def peak_remaining_share(time_key):
    """這根 K 線收市後，當天還剩的變異比例（按 15 分鐘時段比例，時段內按時間攤分）。"""
    t = _session_minutes(time_key)
    total = 0.0
    for slot, share in PEAK_PROFILE_15M.items():
        end = _session_minutes(slot)
        if end > t:
            total += share * min(1.0, (end - t) / 15)
    return total


def _peak_key(day, kind):
    if kind == "day":
        return day
    d = datetime.strptime(day, "%Y-%m-%d")
    if kind == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return day[:7]


def _peak_future_days(today, kind, calendar):
    """這段時間在 today 之後還有哪些交易日（交易日曆；沒涵蓋就把週一至五當交易日）。"""
    if kind == "day":
        return []
    out, d = [], datetime.strptime(today, "%Y-%m-%d")
    for _ in range(31):
        d += timedelta(days=1)
        day = d.strftime("%Y-%m-%d")
        if _peak_key(day, kind) != _peak_key(today, kind):
            break
        if futu_trading_day(day, calendar):
            out.append(day)
    return out


def futu_peak_status(symbol, now=None):
    """今日／本週／本月的高位、低位是否已出現：三個策略的現況。數據不足 → None。"""
    now = now or datetime.now(timezone.utc)
    market = futu_market(symbol)                                      # [R127]
    now_hk = now.astimezone(market["tz"])
    today = futu_session_today(now, symbol)
    rows = futu_series_rows(symbol)
    completed = [r for r in rows if r["date"] < today]
    if len(completed) < HAR_MIN_DAYS:
        return None
    har = har_forecasts(completed)
    nxt = har.get(len(completed))
    if not nxt:
        return None
    fc_by_date = {completed[i]["date"]: v[0] for i, v in har.items() if i < len(completed)}
    fc_today, ref = nxt[0], completed[-1]["close"]
    calendar = gcs_read_json(FUTU_CALENDAR_FILE, {}) if market["calendar"] else {}
    bars = futu_session_5m(symbol, today)
    trading_today = bool(bars) or futu_trading_day(today, calendar)
    ended = futu_session_end_passed(today, now, symbol)
    price = bars[-1]["close"] if bars else ref
    rem_today = 0.0 if (ended or not trading_today) else (peak_remaining_share(bars[-1]["time_key"]) if bars else 1.0)
    sigma_day = fc_today / 1.596 / ref
    out = {"today": today, "asof": bars[-1]["time_key"] if bars else None, "price": price, "periods": {}}
    for kind in PEAK_KINDS:
        key = _peak_key(today, kind)
        prior = [r for r in completed if _peak_key(r["date"], kind) == key] if kind != "day" else []
        sessions = [r["date"] for r in prior] + ([today] if trading_today else [])
        highs = [r["high"] for r in prior] + [b["high"] for b in bars]
        lows = [r["low"] for r in prior] + [b["low"] for b in bars]
        if not sessions or not highs:
            continue
        future = _peak_future_days(today, kind, calendar)
        n = len(sessions) + len(future)
        r_first = fc_today if sessions[0] == today else fc_by_date.get(sessions[0])
        if not r_first:
            continue
        big_r = r_first * math.sqrt(n)
        rem = rem_today + len(future)
        hs, ls = max(highs), min(lows)
        # C：到時間點時的高低與收市
        cut = PEAK_C_CUT[kind]
        c_state = None                                             # None = 未到
        if kind == "day":
            upto = [b for b in bars if b["time_key"] <= f"{today} {cut}:00"]
            if bars and bars[-1]["time_key"] >= f"{today} {cut}:00" and upto:
                c_state = (max(b["high"] for b in upto), min(b["low"] for b in upto), upto[-1]["close"])
        else:
            done = [(r["high"], r["low"], r["close"]) for r in prior]
            if ended and bars:
                done.append((max(b["high"] for b in bars), min(b["low"] for b in bars), bars[-1]["close"]))
            if len(done) >= cut:
                first = done[:cut]
                c_state = (max(x[0] for x in first), min(x[1] for x in first), first[-1][2])
        period = {"key": key, "sessions_done": len(prior) + (1 if ended and trading_today else 0), "sessions": n,
                  "R": round(big_r, 1), "over": rem <= 0, "range": round(hs - ls, 1), "first": sessions[0],
                  "rem": round(rem, 3), "r_today": round(fc_today, 1), "price": price}      # [R124] 給最新預測用
        if kind in PERIOD_RANGE_RATIO:                                # [R103] 週、月的預測波幅（已校準）
            q10, q50, q90 = PERIOD_RANGE_RATIO[kind]
            period["forecast"] = {"range": round(big_r * q50), "lo": round(big_r * q10), "hi": round(big_r * q90)}
        for side in ("high", "low"):
            ext = hs if side == "high" else ls
            dist = (hs - price) if side == "high" else (price - ls)
            if rem <= 0:
                prob = 0.0
            else:
                sig = sigma_day * math.sqrt(rem) * price
                prob = math.erfc(dist / sig / math.sqrt(2)) if dist > 0 and sig > 0 else 1.0
            c_ok = None
            if c_state:
                c_dist = (c_state[0] - c_state[2]) if side == "high" else (c_state[2] - c_state[1])
                c_ok = c_dist >= PEAK_C_BETA * big_r
            period[side] = {"ext": ext, "dist": round(dist, 1), "prob": round(prob, 4),
                            "A": (hs - ls) >= PEAK_A[0] * big_r and dist >= PEAK_A[1] * big_r,
                            "B": dist > 0 and prob < PEAK_B, "C": c_ok}
        out["periods"][kind] = period
    return out


def _peak_signal_text(kind, side, strat, period, s, price):
    zh = "高位" if side == "high" else "低位"
    acc = PEAK_ACCURACY.get(f"{kind}/{side}/{strat}")
    lines = [f"⚠️{FENGYANG_TAG}恒指即月期貨 {PEAK_ZH[kind]}{zh}可能已出現｜{PEAK_STRAT_ZH[strat]}",
             f"{PEAK_ZH[kind]}{zh} {s['ext']:,.0f}，現價 {price:,.0f}（離{zh} {s['dist']:,.0f} 點）",
             f"B 機率法：之後再創新{'高' if side == 'high' else '低'}的機率 {s['prob'] * 100:.0f}%"]
    if acc is not None:
        lines.append(f"回測：這類通知 {acc:.0%} 準確（{ {'day': '交易日', 'week': '週', 'month': '月'}[kind]}{zh}，{PEAK_STRAT_ZH[strat]}）")
    lines.append("統計判斷，不是交易建議。")
    return "\n".join(lines)


def futu_peak_update(symbol, now=None):
    """每包 5 分 K 到達時重算；任一策略第一次觸發就記一筆通知（同一段、同一邊、同一策略只記一次）。"""
    try:
        st = futu_peak_status(symbol, now)
        if not st:
            return []
        fresh = []
        for kind, per in st["periods"].items():
            if per["over"]:
                continue
            for side in ("high", "low"):
                s = per[side]
                for strat in ("A", "B", "C"):
                    if s[strat]:
                        fresh.append({"id": f"{kind}:{per['key']}:{side}:{strat}", "kind": kind, "key": per["key"],
                                      "side": side, "strat": strat, "asof": st["asof"], "price": st["price"],
                                      "ext": s["ext"], "dist": s["dist"], "prob": s["prob"], "made_utc": fmt_utc(),
                                      "sent": False, "text": _peak_signal_text(kind, side, strat, per, s, st["price"])})
        if not fresh:
            return []

        def mutate(existing):
            items = [e for e in (existing if isinstance(existing, list) else []) if isinstance(e, dict)]
            seen = {e.get("id") for e in items}
            add = [f for f in fresh if f["id"] not in seen]
            if not add:
                return None, 0
            return (items + add)[-FUTU_SIGNAL_KEEP:], len(add)

        added = gcs_update(futu_signal_file(symbol), mutate, default_factory=list)
        if added:
            log_event(f"⚠️ [高低位已出現] {symbol} 新通知 {added} 則", component="futu", symbol=symbol)
        return []
    except StorageError as exc:
        log_event(f"⚠️ [高低位判斷失敗] {exc}", severity="WARNING", component="futu")
        return ["高低位判斷失敗（下一包會再算）"]


def futu_signals_report(symbol, ack=None):
    """排程取未發的通知；ack=逗號分隔的 id → 標記已發。"""
    if ack:
        ids = {x for x in str(ack).split(",") if x}

        def mark(items):
            hit = 0
            for e in items:
                if isinstance(e, dict) and e.get("id") in ids and not e.get("sent"):
                    e["sent"], e["sent_utc"] = True, fmt_utc()
                    hit += 1
            return hit

        def mutate(existing):
            items = [e for e in (existing if isinstance(existing, list) else []) if isinstance(e, dict)]
            hit = mark(items)
            return (items, hit) if hit else (None, 0)

        def mutate_paper(existing):                                 # [R116] 紙上交易的通知放在狀態檔裡
            if not isinstance(existing, dict) or not existing.get("notices"):
                return None, 0
            hit = mark(existing["notices"])
            return (existing, hit) if hit else (None, 0)

        n = gcs_update(futu_signal_file(symbol), mutate, default_factory=list)
        if any(x.startswith("paper:") for x in ids):
            n += gcs_update(futu_paper_file(symbol), mutate_paper, default_factory=dict)
        return {"status": "ok", "acked": n}
    items = gcs_read_json(futu_signal_file(symbol), [])
    pending = [{"id": e["id"], "text": e["text"]} for e in (items if isinstance(items, list) else [])
               if isinstance(e, dict) and not e.get("sent")]
    paper = futu_paper_state(symbol)                                 # [R116]
    pending += [{"id": e["id"], "text": e["text"]} for e in (paper or {}).get("notices", [])
                if isinstance(e, dict) and not e.get("sent")]
    return {"status": "ok", "signals": pending}


def futu_peak_lines(symbol, now=None, status=None, signals=None):
    """四次報告用：今日／本週／本月三個策略的現況（數據不足 → 空）。"""
    try:
        st = status if status is not None else futu_peak_status(symbol, now)
        sig = signals if signals is not None else gcs_read_json(futu_signal_file(symbol), [])
    except StorageError:
        return []
    if not st or not st["periods"]:
        return []
    fired = {e.get("id"): e for e in (sig if isinstance(sig, list) else []) if isinstance(e, dict)}
    lines = ["高低位是否已出現（A 耗盡回落｜B 再創新高機率｜C 時間點）"]
    for kind, per in st["periods"].items():
        parts = []
        for side in ("high", "low"):
            s, zh = per[side], ("高" if side == "high" else "低")

            def mark(strat):
                e = fired.get(f"{kind}:{per['key']}:{side}:{strat}")
                if not e:
                    return "—" if strat != "C" or s["C"] is not None else "未到"
                beyond = s["ext"] > e["ext"] if side == "high" else s["ext"] < e["ext"]
                return "❌已再創新" + zh if beyond else "✅"
            b_fired = " ✅" if fired.get(f"{kind}:{per['key']}:{side}:B") else ""
            parts.append(f"{zh} {s['ext']:,.0f}：A {mark('A')}｜B {s['prob'] * 100:.0f}%{b_fired}｜C {mark('C')}")
        tail = "（已結束）" if per["over"] else f"（已收市 {per['sessions_done']}／{per['sessions']} 個交易日）" if kind != "day" else ""
        lines.append(f"{PEAK_ZH[kind]}{tail} " + "；".join(parts))
    return lines


# ---- 日／週／月：過去每一次預測的誤差與命中率  [R104] ----------------------------
# 全部用逐日／逐段前推重算（只用當時已知的數據），日的部分有開市前實時紀錄就用紀錄（那是當天真正發出的預測）。
# 命中 = 實際落在 80% 區間內；理想命中率 ≈ 80%。週、月的比例（PERIOD_RANGE_RATIO）在這裡也逐段前推重估，
# 前 PERIOD_CAL_MIN 段只用來估比例、不計分。
ACC_SHOW = 7
PERIOD_CAL_MIN = 12
ROLL_MIN_SAMPLES = 30                           # [R124] 邊走邊改的比例至少要這麼多個（段 × 日）樣本
ROLL_BAND_Q = {"week": 0.02, "month": 0.05}     # [R124] 更新後範圍的分位（走到一半時：週 867 點寬／97%、月 1,647 點／96%）


def _acc_summary(recs, extra=(), ok_pct=1.0):
    done = [r for r in recs if r.get("hit") is not None]
    errs = [r["err"] for r in done]
    out = {"n": len(done), "hits": sum(1 for r in done if r["hit"]),
           "hit_rate": round(sum(1 for r in done if r["hit"]) / len(done) * 100) if done else None,
           "mae": round(sum(abs(e) for e in errs) / len(errs), 1) if errs else None,
           "bias": round(sum(errs) / len(errs), 1) if errs else None,
           "recent": done[-ACC_SHOW:]}
    out["recent_hits"] = sum(1 for r in out["recent"] if r["hit"])
    for key in extra:                                             # 日：波幅、高位、低位各自落在預計範圍的比率
        vals = [r[key] for r in recs if r.get(key) is not None]
        out[f"{key}_n"] = len(vals)
        out[f"{key}_rate"] = round(sum(vals) / len(vals) * 100) if vals else None
    for key in ("err_high", "err_low"):                           # [R109] 日：高位、低位平均差
        vals = [abs(r[key]) for r in done if r.get(key) is not None]
        if vals:
            out[key.replace("err", "mae")] = round(sum(vals) / len(vals), 1)
    hl = [r for r in done if r.get("err_high") is not None and r.get("high") and r.get("low")]
    if hl:                                                         # [R125] 高、低都在門檻內的比率（門檻按日／週／月）
        ok = [abs(r["err_high"]) / r["high"] * 100 <= ok_pct and abs(r["err_low"]) / r["low"] * 100 <= ok_pct for r in hl]
        out["within_n"] = len(ok); out["within_rate"] = round(sum(ok) / len(ok) * 100); out["ok_pct"] = ok_pct
        out["recent_within"] = sum(1 for r in out["recent"] if r.get("err_high") is not None and r.get("high")
                                   and abs(r["err_high"]) / r["high"] * 100 <= ok_pct and abs(r["err_low"]) / r["low"] * 100 <= ok_pct)
    return out


def futu_accuracy(completed, har, log=None, open_keys=None):
    """completed：已完結的交易日；har：har_forecasts(completed)；log：開市前實時紀錄；
    open_keys：{種類: 還沒結束的那段 key}，那段不計分。回傳 {day|week|month: 摘要＋records}。"""
    logged = {e["date"]: e for e in (log or []) if isinstance(e, dict) and e.get("date") and e.get("range")}
    open_keys = open_keys or {}
    day, ups, downs = [], [], []
    for i, row in enumerate(completed):
        f = har.get(i)
        if not f or not row.get("prev_close"):
            continue
        rec = {"key": row["date"], "forecast": f[0], "lo": f[1], "hi": f[2], "live": False}
        if len(ups) >= HL_MIN_DAYS:
            ref = row["prev_close"]
            q = HL_BAND_Q
            rec.update(high=ref + _quantile(ups, 0.5) * f[0], low=ref - _quantile(downs, 0.5) * f[0],
                       high_lo=ref + _quantile(ups, q) * f[0], high_hi=ref + _quantile(ups, 1 - q) * f[0],
                       low_lo=ref - _quantile(downs, 1 - q) * f[0], low_hi=ref - _quantile(downs, q) * f[0])
        bisect.insort(ups, (row["high"] - row["prev_close"]) / f[0])
        bisect.insort(downs, (row["prev_close"] - row["low"]) / f[0])
        e = logged.get(row["date"])
        if e and None not in (e.get("lo"), e.get("hi")):          # 當天真正發出的預測
            rec.update(forecast=e["range"], lo=e["lo"], hi=e["hi"], live=True)
            if e.get("high_lo") is not None and e.get("band_q") == HL_BAND_Q:     # [R119] 舊紀錄（80% 範圍）改用重算的
                rec.update(high=e.get("high"), low=e.get("low"), high_lo=e["high_lo"], high_hi=e["high_hi"],
                           low_lo=e["low_lo"], low_hi=e["low_hi"])
        actual = row["range"]
        hl = "high_lo" in rec and rec.get("high") is not None
        rec.update(actual=actual, err=round(actual - rec["forecast"], 1),
                   hit_range=rec["lo"] <= actual <= rec["hi"],
                   actual_high=row["high"], actual_low=row["low"],
                   hit_high=(rec["high_lo"] <= row["high"] <= rec["high_hi"]) if hl else None,
                   hit_low=(rec["low_lo"] <= row["low"] <= rec["low_hi"]) if hl else None,
                   err_high=round(row["high"] - rec["high"], 1) if hl else None,
                   err_low=round(row["low"] - rec["low"], 1) if hl else None)
        rec["hit"] = (rec["hit_high"] and rec["hit_low"]) if hl else None     # [R109] 日：高、低都落在預計範圍才算 ✅
        for k in ("forecast", "lo", "hi", "high", "low", "high_lo", "high_hi", "low_lo", "low_hi"):
            if rec.get(k) is not None:
                rec[k] = round(rec[k], 1)
        day.append(rec)
    out = {"day": {**_acc_summary(day, ("hit_range", "hit_high", "hit_low"), HL_OK_PCT_BY["day"]), "records": day}}
    for kind in ("week", "month"):
        groups = {}
        for i, row in enumerate(completed):
            groups.setdefault(_peak_key(row["date"], kind), []).append(i)
        recs, ratios, pups, pdowns = [], [], [], []
        for key, idx in groups.items():
            if key == open_keys.get(kind):
                continue
            f = har.get(idx[0])
            if not f:
                continue
            big_r = f[0] * math.sqrt(len(idx))
            p_high, p_low = max(completed[i]["high"] for i in idx), min(completed[i]["low"] for i in idx)
            actual = p_high - p_low
            ref = completed[idx[0]].get("prev_close")                  # [R120] 段首的昨收
            rec = {"key": key, "first": completed[idx[0]]["date"], "sessions": len(idx), "R": round(big_r, 1),
                   "actual": round(actual, 1), "actual_high": p_high, "actual_low": p_low, "hit": None, "hit_range": None}
            if len(ratios) >= PERIOD_CAL_MIN:
                srt = sorted(ratios)
                rec.update(forecast=round(big_r * _quantile(srt, 0.5)), lo=round(big_r * _quantile(srt, 0.1)),
                           hi=round(big_r * _quantile(srt, 0.9)))
                rec.update(err=round(actual - rec["forecast"], 1), hit_range=rec["lo"] <= actual <= rec["hi"])
                rec["hit"] = rec["hit_range"]
                if ref and len(pups) >= PERIOD_CAL_MIN:                   # [R120] 週、月的高位／低位與預計範圍（同今日卡）
                    hl = _hl_levels(ref, big_r, sorted(pups), sorted(pdowns), _hl_band_q(kind))
                    rec.update(hl, hit_high=hl["high_lo"] <= p_high <= hl["high_hi"], hit_low=hl["low_lo"] <= p_low <= hl["low_hi"],
                               err_high=round(p_high - hl["high"], 1), err_low=round(p_low - hl["low"], 1))
                    rec["hit"] = rec["hit_high"] and rec["hit_low"]
            ratios.append(actual / big_r)
            if ref:
                pups.append((p_high - ref) / big_r); pdowns.append((ref - p_low) / big_r)
            recs.append(rec)
        roll = _roll_calibrate(completed, har, groups, open_keys.get(kind), ROLL_BAND_Q[kind])      # [R124]
        out[kind] = {**_acc_summary(recs, ("hit_range", "hit_high", "hit_low"), HL_OK_PCT_BY[kind]), "records": recs,
                     "cal": ({"ups": sorted(pups), "downs": sorted(pdowns)} if len(pups) >= PERIOD_CAL_MIN else None),
                     "cal_roll": roll["cal"], "roll_mid": roll["mid"]}
    return out


def _roll_calibrate(completed, har, groups, open_key, q):
    """[R124] 邊走邊改的比例：每段每一天 k（已走 k 日）記 (之後的最高 − 當日收) ÷ (翌日 R̂ × √剩餘日數)、(當日收 − 之後的最低) ÷ 同一數。
    逐段前推；另在每段走到一半時用之前各段的比例評分（高、低都落在更新後的範圍）。回傳 {cal, mid}。"""
    ups, downs, mid = [], [], []
    n_periods = 0
    for key, idx in groups.items():
        if key == open_key or len(idx) < 2:
            continue
        n = len(idx)
        rows_p = [completed[i] for i in idx]
        this_ups, this_downs = [], []
        k_mid = n // 2
        for k in range(1, n):
            f = har.get(idx[k])
            if not f:
                continue
            c = rows_p[k - 1]["close"]
            r_rem = f[0] * math.sqrt(n - k)
            rem_hi = max(r["high"] for r in rows_p[k:]); rem_lo = min(r["low"] for r in rows_p[k:])
            this_ups.append((rem_hi - c) / r_rem); this_downs.append((c - rem_lo) / r_rem)
            if k == k_mid and n_periods >= PERIOD_CAL_MIN and len(ups) >= ROLL_MIN_SAMPLES:
                hs = max(r["high"] for r in rows_p[:k]); ls = min(r["low"] for r in rows_p[:k])
                lv = _roll_levels(hs, ls, c, r_rem, sorted(ups), sorted(downs), q)
                p_hi = max(r["high"] for r in rows_p); p_lo = min(r["low"] for r in rows_p)
                mid.append({"hit_high": lv["high_lo"] <= p_hi <= lv["high_hi"], "hit_low": lv["low_lo"] <= p_lo <= lv["low_hi"],
                            "width": (lv["high_hi"] - lv["high_lo"] + lv["low_hi"] - lv["low_lo"]) / 2,
                            "err_high": p_hi - lv["high"], "err_low": p_lo - lv["low"]})
        ups += this_ups; downs += this_downs
        n_periods += 1
    cal = {"ups": sorted(ups), "downs": sorted(downs)} if n_periods >= PERIOD_CAL_MIN and len(ups) >= ROLL_MIN_SAMPLES else None
    summary = None
    if mid:
        summary = {"n": len(mid), "hit_rate": round(sum(m["hit_high"] and m["hit_low"] for m in mid) / len(mid) * 100),
                   "hit_high_rate": round(sum(m["hit_high"] for m in mid) / len(mid) * 100),
                   "hit_low_rate": round(sum(m["hit_low"] for m in mid) / len(mid) * 100),
                   "width": round(sum(m["width"] for m in mid) / len(mid)),
                   "mae_high": round(sum(abs(m["err_high"]) for m in mid) / len(mid), 1),
                   "mae_low": round(sum(abs(m["err_low"]) for m in mid) / len(mid), 1)}
    return {"cal": cal, "mid": summary}


def _roll_levels(hs, ls, c, r_rem, ups_sorted, downs_sorted, q):
    """[R124] 最新預測：已出現的高／低 與 「當日收 ± 比例 × 剩餘預測」取較極端的一邊。"""
    up = lambda p: max(hs, c + _quantile(ups_sorted, p) * r_rem)
    dn = lambda p: min(ls, c - _quantile(downs_sorted, p) * r_rem)
    return {"high": round(up(0.5)), "high_lo": round(up(q)), "high_hi": round(up(1 - q)),
            "low": round(dn(0.5)), "low_lo": round(dn(1 - q)), "low_hi": round(dn(q))}


def _hl_levels(ref, big_r, ups_sorted, downs_sorted, q=None):
    """[R120] 由昨收、預測波幅與過去比例算預測高位／低位與預計範圍（分位 q，預設 HL_BAND_Q）。"""
    q = HL_BAND_Q if q is None else q
    return {"high": round(ref + _quantile(ups_sorted, 0.5) * big_r), "high_lo": round(ref + _quantile(ups_sorted, q) * big_r),
            "high_hi": round(ref + _quantile(ups_sorted, 1 - q) * big_r), "low": round(ref - _quantile(downs_sorted, 0.5) * big_r),
            "low_lo": round(ref - _quantile(downs_sorted, 1 - q) * big_r), "low_hi": round(ref - _quantile(downs_sorted, q) * big_r)}


# ---- 「怎樣用來賺錢」四個方向  [R106] ---------------------------------------------
# 方向二的數字來自 research/hsi_futures_range/fade_pnl.py（MONEY_REPORT.md）；其餘三個方向未回測，只顯示今天的數字。
FUTU_IV_SYMBOL = "HK.800000"                    # 恒指週期權（本地腳本每 5 分鐘推價平附近 10 檔）
FUTU_VHSI_SYMBOL = "HK.800125"                  # [R107] 恒指波幅指數 VHSI（FUTU_SYMBOLS 加上它才有即時值）
VHSI_SELL_RATIO = 1.2                           # [R107] VHSI ÷ 預測 ≥ 1.2 才賣（回測約四週一次，research/.../vol_premium.py）
RANGE_TO_SIGMA = 1.596                          # 布朗運動：期望波幅 ≈ 1.596 × σ


def futu_iv_compare(fc, now=None):
    """方向一：恒指期權價平 IV 對風揚陣預測的年化波幅。沒有期權或預測 → None。
    最新 K 線離現在超過 20 分鐘（休市、週末）→ fresh=False，報價不可信。"""
    har = None
    if fc and fc.get("range") and fc.get("ref_close"):
        har = fc["range"] / RANGE_TO_SIGMA / fc["ref_close"] * math.sqrt(252) * 100
    out = {"har_vol": round(har, 1) if har else None}
    vsnap = read_futu_snapshot(FUTU_VHSI_SYMBOL)                  # [R107] 回測用的是 VHSI，判斷以它為準
    vbars = (vsnap.get("bars") or []) if isinstance(vsnap, dict) and not vsnap.get("error") else []
    vhsi = to_float(vbars[-1].get("close")) if vbars else None
    if vhsi:
        out.update(vhsi=round(vhsi, 2), vhsi_time=str(vbars[-1].get("time_key", ""))[:16],
                   vhsi_ratio=round(vhsi / har, 2) if har else None)
    snap = read_futu_snapshot(FUTU_IV_SYMBOL)
    bars = (snap.get("bars") or []) if isinstance(snap, dict) and not snap.get("error") else []
    spot = to_float(bars[-1].get("close")) if bars else None
    opts = [o for o in (snap.get("options") or [] if bars else []) if to_float(o.get("iv")) and to_float(o.get("strike"))]
    if spot and opts:
        strike = min({o["strike"] for o in opts}, key=lambda k: abs(k - spot))
        ivs = [o["iv"] for o in opts if o["strike"] == strike]
        iv = sum(ivs) / len(ivs)
        now_hk = (now or datetime.now(timezone.utc)).astimezone(HK_TZ).replace(tzinfo=None)
        try:
            lag = (now_hk - datetime.strptime(str(bars[-1]["time_key"])[:16], "%Y-%m-%d %H:%M")).total_seconds()
        except ValueError:
            lag = None
        out.update(iv=round(iv, 1), strike=strike, expiry=opts[0].get("expiry"), spot=spot,
                   ratio=round(iv / har, 2) if har else None, fresh=lag is not None and -600 <= lag <= 1200)
    return out if ("iv" in out or "vhsi" in out) else None


# ---- 📒 紙上交易：三條策略跟實時 5 分 K 走，逐筆記錄  [R116] -------------------------------
# 回測挑出來的三條（規格與回測見 research/hsi_futures_range/PAPER_TRADING.md）：
#   SNAKE   🐍 蛇蟠陣本身：前 3 個蛇日（日市屬當天、夜市屬翌日）的最高／最低做通道，觸價反手、永遠在場；
#           止損單成交（開市已越過用開市價），每個蛇日每個方向最多一次。
#   B_S_R3  🅱️ 機率法「高位已出現」「低位已出現」都亮後的下一根開市入，方向跟蛇當時持倉，止蝕 = 九成日範圍邊
#           （固定），3R 止賺，蛇反手就平倉，可持倉多日；一天最多一筆。
#   A_S_R2  🅰️ 耗盡回落同上，2R 止賺。
# 每包即月期貨 5 分 K 到達時處理新 K 線；狀態、逐筆紀錄與待發通知存 futu/paper/<代號>.json，
# 通知跟高低位通知一起由 ?view=futu_range&report=signals 給排程發 Telegram。
# 第一次啟動用之前 PAPER_BOOT_DAYS 個交易日的 K 線（5 分 K 不夠就用 15 分 K 封存）把蛇的持倉算出來，那段不記交易、不發通知。
# 只是紙上紀錄，不接任何下單。
PAPER_DIR = "futu/paper"
PAPER_VERSION = 1
PAPER_COST = 3.0                                 # 每筆來回成本（點），跟回測相同
PAPER_SNAKE_N = 3                                # 蛇蟠陣：前 3 個蛇日通道
PAPER_BOOT_DAYS = 12                             # 第一次啟動回看的交易日數
PAPER_BOOT_MIN_BARS = 20                         # 一個交易日的 5 分 K 少於這個數就改用 15 分 K 封存
PAPER_KEEP = 2000
PAPER_NOTICE_KEEP = 300
PAPER_STRATS = {                                 # 名稱 → 顯示名、用哪個訊號、止賺倍數（None = 蛇本身）
    "SNAKE": {"zh": "🐍 蛇蟠陣", "signal": None, "rr": None, "css": "",
              "desc": "前 3 個蛇日的最高／最低做通道，觸價反手、永遠在場（回測 36 年有效，近年優勢變小）"},
    "B_S_R3": {"zh": "🅱️＋跟蛇＋3R", "signal": "B", "rr": 3.0, "css": "week",
               "desc": "機率法「高位已現」「低位已現」都亮後下一根開市入，方向跟蛇，止蝕九成日範圍邊，3R 止賺，蛇反手就平"},
    "A_S_R2": {"zh": "🅰️＋跟蛇＋2R", "signal": "A", "rr": 2.0, "css": "month",
               "desc": "耗盡回落兩邊都亮後同樣規則入市，2R 止賺"},
}
PAPER_TAG = f"📒{FENGYANG_TAG}紙上交易"
PAPER_SIDE_ZH = {1: "做多", -1: "做空", 0: "空手"}
PAPER_GATE_TH = 1.2                              # [R118] 開閘門檻：今日 R̂ ÷ 過去 250 日 R̂ 中位 ≥ 1.2（vol_gate.py）
PAPER_GATE_LOOKBACK = 250
PAPER_GATE_MIN_DAYS = 60                         # 歷史預測少於這麼多天就沒有開閘指標（一律 1 張）
PAPER_GATE_LOTS = 2                              # 開閘日入市的張數（其餘 1 張）
PAPER_LEVEL_KEYS = ("high_edge95", "low_edge95", "high", "low", "range", "ref_close", "rhat_med250", "gate_ratio", "gate_open")


def _paper_lots(lv):
    """[R118] 今日入市張數與開閘比值：開閘 → 2 張，否則（含沒有指標）1 張。"""
    lv = lv or {}
    return (PAPER_GATE_LOTS if lv.get("gate_open") else 1), lv.get("gate_ratio")


def _paper_gate_text(lv):
    lv = lv or {}
    r = lv.get("gate_ratio")
    if r is None:
        return "開閘指標未有（歷史預測不足）→ 1 張"
    if lv.get("gate_open"):
        return f"⚡ 今日開閘（R̂ ÷ {PAPER_GATE_LOOKBACK} 日中位 {r:.2f} ≥ {PAPER_GATE_TH:g}）→ {PAPER_GATE_LOTS} 張"
    return f"🚪 今日未開閘（R̂ ÷ {PAPER_GATE_LOOKBACK} 日中位 {r:.2f} < {PAPER_GATE_TH:g}）→ 1 張"


def futu_paper_file(symbol):
    return f"{PAPER_DIR}/{ARCHIVE_SAFE_RE.sub('_', symbol)}.json"


def _paper_new_state(symbol):
    return {"version": PAPER_VERSION, "symbol": symbol, "started_utc": fmt_utc(), "last_bar": None, "last_session": None,
            "snake": {"pos": 0, "px": None, "entry_time": None, "cur": None, "hist": [], "used": [],
                      "phase": None, "session": None, "upper": None, "lower": None, "boot": False},
            "open": {}, "trades": [], "notices": [], "day": {"date": None, "levels": None, "done": []}}


def _paper_phase(bar, session):
    """蛇日的兩段：日市（09:00–16:59，屬當天）、夜市（屬下一個蛇日）。"""
    t = bar["time_key"]
    return "day" if t[:10] == session and "09:00" <= t[11:16] < "17:00" else "night"


def _paper_hhmm(time_key):
    return f"{time_key[5:10]} {time_key[11:16]}"


def _paper_trade(strat, side, entry_time, entry_px, exit_time, exit_px, why, cost, stop=None, target=None, boot=False,
                 lots=1, gate=None):
    gross = (exit_px - entry_px) * side
    risk = abs(entry_px - stop) if stop is not None else None
    return {"strat": strat, "side": side, "entry_time": entry_time, "entry_price": entry_px, "stop": stop, "target": target,
            "exit_time": exit_time, "exit_price": exit_px, "exit_reason": why, "gross": round(gross, 1), "cost": cost,
            "net": round(gross - cost, 1), "risk": risk,
            "r_multiple": round((gross - cost) / risk, 3) if risk else None, "boot": boot,
            "lots": lots, "gate": gate}                                  # [R118] 入市日張數（開閘 2、否則 1）與 R̂ 比值


def _paper_dd(xs):
    eq = peak = dd = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def _paper_stats(trades):
    nets = [t["net"] for t in trades]
    if not nets:
        return {"n": 0}
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    aw = sum(wins) / len(wins) if wins else None
    al = sum(losses) / len(losses) if losses else None
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    lots = [t.get("lots") or 1 for t in trades]                         # [R118] 開閘雙倍那條帳：淨點數 × 入市日張數
    tilt = [x * k for x, k in zip(nets, lots)]
    gate = [x for x, k in zip(nets, lots) if k > 1]
    return {"n": len(nets), "win": len(wins) / len(nets), "avg_win": aw, "avg_loss": al,
            "rrr": (aw / -al) if aw and al else None, "mean": sum(nets) / len(nets), "total": sum(nets), "dd": _paper_dd(nets),
            "R": sum(rs) / len(rs) if rs else None,
            "total_tilt": sum(tilt), "dd_tilt": _paper_dd(tilt), "gate_n": len(gate), "gate_total": sum(gate),
            "rest_total": sum(nets) - sum(gate)}


def _paper_snake_step(st, b, session, cost, live, lv=None):
    """一根 K 線：日市收完就換蛇日，再按通道觸價反手。回傳這根的反手 [(新持倉, 成交價, 被平掉那筆的紀錄或 None)]。
    lv：這個交易日的九成邊與開閘指標（新持倉的張數照它記）。"""
    sn = st["snake"]
    phase = _paper_phase(b, session)
    if sn["phase"] == "day" and (phase == "night" or session != sn["session"]):
        if sn["cur"]:
            sn["hist"] = (sn["hist"] + [sn["cur"]])[-PAPER_SNAKE_N:]
        sn["cur"], sn["used"] = None, []
        if len(sn["hist"]) >= PAPER_SNAKE_N:
            sn["upper"], sn["lower"] = max(h for h, _ in sn["hist"]), min(l for _, l in sn["hist"])
    sn["phase"], sn["session"] = phase, session
    flips = []
    if sn["upper"] is not None:
        for side in (("down", "up") if sn["pos"] > 0 else ("up", "down")):
            if side == "up" and sn["pos"] <= 0 and "up" not in sn["used"] and b["high"] >= sn["upper"]:
                fill, new = max(sn["upper"], b["open"]), 1
            elif side == "down" and sn["pos"] >= 0 and "down" not in sn["used"] and b["low"] <= sn["lower"]:
                fill, new = min(sn["lower"], b["open"]), -1
            else:
                continue
            closed = None
            if sn["pos"] and live:
                closed = _paper_trade("SNAKE", sn["pos"], sn["entry_time"], sn["px"], b["time_key"], fill, "蛇反手", cost,
                                      boot=sn.get("boot", False), lots=sn.get("lots") or 1, gate=sn.get("gate"))
            lots, gate = _paper_lots(lv)
            sn.update(pos=new, px=fill, entry_time=b["time_key"], boot=not live, lots=lots, gate=gate)
            sn["used"].append(side)
            flips.append((new, fill, closed))
    sn["cur"] = [b["high"], b["low"]] if not sn["cur"] else [max(sn["cur"][0], b["high"]), min(sn["cur"][1], b["low"])]
    return flips


def _paper_exit(tr, b, flips):
    """持倉管理（與 hl_signal.simulate 相同）：回傳 (出場價, 原因) 或 None。"""
    s, stop, tg, rr = tr["side"], tr["stop"], tr["target"], tr["rr"]
    if (b["open"] - stop) * s <= 0:
        return b["open"], "止蝕（跳空）"
    if tg is not None and (b["open"] - tg) * s >= 0:
        return b["open"], f"{rr:g}R 止賺"
    hit = (b["low"] <= stop) if s > 0 else (b["high"] >= stop)
    against = [f for f in flips if f[0] == -s]
    if hit or against:
        c = ([(stop, "止蝕")] if hit else []) + ([(against[0][1], "蛇反手")] if against else [])
        return min(c, key=lambda x: x[0] * s)
    if tg is not None and ((b["high"] >= tg) if s > 0 else (b["low"] <= tg)):
        return tg, f"{rr:g}R 止賺"
    return None


def _paper_trigger(signals, session):
    """今天每個訊號兩邊都亮了嗎？→ {訊號: 後亮那邊的 K 線時間}。"""
    out = {}
    for strat, cfg in PAPER_STRATS.items():
        k = cfg["signal"]
        if not k:
            continue
        hi = signals.get(f"day:{session}:high:{k}")
        lo = signals.get(f"day:{session}:low:{k}")
        if hi and lo and hi.get("asof") and lo.get("asof"):
            out[strat] = max(str(hi["asof"]), str(lo["asof"]))
    return out


def _paper_notice(st, kind, strat, time_key, text):
    st["notices"] = (st["notices"] + [{"id": f"paper:{strat}:{kind}:{time_key}", "strat": strat, "kind": kind,
                                       "made_utc": fmt_utc(), "sent": False, "text": text}])[-PAPER_NOTICE_KEEP:]


def _paper_totals(st, strat):
    s = _paper_stats([t for t in st["trades"] if t["strat"] == strat])
    return (f"策略累計 {s['n']} 筆 {s['total']:+,.0f} 點（開閘雙倍 {s['total_tilt']:+,.0f}）" if s["n"] else "策略第一筆")


def _paper_run(st, sessions, bars_by, levels_by, trig_by, boot, cost):
    """純函數：把新 K 線跑過三條策略，直接改 st。boot 裡的交易日是啟動期（只算蛇的持倉，不記交易、不發通知）。"""
    zh = {k: v["zh"] for k, v in PAPER_STRATS.items()}
    for session in sessions:
        live = session not in boot
        if st["day"].get("date") != session:
            st["day"] = {"date": session, "levels": levels_by.get(session), "done": []}
        elif levels_by.get(session) and (not st["day"].get("levels") or "gate_ratio" not in st["day"]["levels"]):
            st["day"]["levels"] = levels_by[session]                  # 沒算到、或 R118 前的舊紀錄沒有開閘指標 → 補上
        lv, trig = st["day"].get("levels") or {}, trig_by.get(session, {})
        for b in bars_by.get(session, []):
            t = b["time_key"]
            if st["last_bar"] and t <= st["last_bar"]:
                continue
            prev = st["last_bar"] if st["last_session"] == session else None
            pos_before = st["snake"]["pos"]
            flips = _paper_snake_step(st, b, session, cost, live, lv)
            if live:
                for new, fill, closed in flips:
                    if closed:
                        st["trades"] = (st["trades"] + [closed])[-PAPER_KEEP:]
                    txt = (f"{PAPER_TAG} {zh['SNAKE']}：{'反手' if closed else ''}{PAPER_SIDE_ZH[new]} {fill:,.0f}（{_paper_hhmm(t)}）"
                           f"×{st['snake']['lots']} 張\n"
                           f"通道 {st['snake']['upper']:,.0f}／{st['snake']['lower']:,.0f}"
                           + (f"；上一筆 {closed['net']:+,.0f} 點" + (f"（×{closed['lots']} 張 = {closed['net'] * closed['lots']:+,.0f}）"
                                                                    if (closed.get("lots") or 1) > 1 else "")
                              + f"，{_paper_totals(st, 'SNAKE')}" if closed else "")
                           + f"\n{_paper_gate_text(lv)}\n紙上紀錄，不是真實下單。")
                    _paper_notice(st, "flip", "SNAKE", t, txt)
            for strat, cfg in PAPER_STRATS.items():
                if not cfg["signal"]:
                    continue
                tr = st["open"].get(strat)
                later = trig.get(strat)
                if (not tr and live and later and strat not in st["day"]["done"] and t > later and (prev is None or prev <= later)
                        and pos_before and lv.get("high_edge95") is not None):
                    st["day"]["done"].append(strat)
                    side, px = pos_before, b["open"]
                    stop = lv["low_edge95"] if side > 0 else lv["high_edge95"]
                    if (stop - px) * side < 0:
                        risk = abs(px - stop)
                        lots, gate = _paper_lots(lv)
                        tr = {"side": side, "entry_time": t, "entry_price": px, "stop": stop, "risk": risk, "rr": cfg["rr"],
                              "target": px + side * cfg["rr"] * risk, "session": session, "snake_at_entry": pos_before,
                              "lots": lots, "gate": gate}
                        st["open"][strat] = tr
                        _paper_notice(st, "entry", strat, t,
                                      f"{PAPER_TAG} {zh[strat]}：{PAPER_SIDE_ZH[side]} {px:,.0f}（{_paper_hhmm(t)}）×{lots} 張\n"
                                      f"止蝕 {stop:,.0f}（九成日範圍邊）・目標 {tr['target']:,.0f}（{cfg['rr']:g}R）・風險 {risk:,.0f} 點\n"
                                      f"兩邊「{'機率法' if cfg['signal'] == 'B' else '耗盡回落'}」訊號都已亮；蛇蟠陣目前{PAPER_SIDE_ZH[side]}。\n"
                                      f"{_paper_gate_text(lv)}\n紙上紀錄，不是真實下單。")
                if tr:
                    done = _paper_exit(tr, b, flips)
                    if done:
                        px, why = done
                        rec = _paper_trade(strat, tr["side"], tr["entry_time"], tr["entry_price"], t, px, why, cost,
                                           tr["stop"], tr["target"], lots=tr.get("lots") or 1, gate=tr.get("gate"))
                        st["trades"] = (st["trades"] + [rec])[-PAPER_KEEP:]
                        st["open"].pop(strat, None)
                        if strat not in st["day"]["done"]:
                            st["day"]["done"].append(strat)
                        _paper_notice(st, "exit", strat, t,
                                      f"{PAPER_TAG} {zh[strat]}：平倉 {px:,.0f}（{_paper_hhmm(t)}）{why}\n"
                                      f"{PAPER_SIDE_ZH[tr['side']]} {tr['entry_price']:,.0f} → {px:,.0f}：{rec['net']:+,.0f} 點"
                                      f"（{rec['r_multiple']:+.2f}R）"
                                      + (f"×{rec['lots']} 張 = {rec['net'] * rec['lots']:+,.0f} 點" if rec["lots"] > 1 else "")
                                      + f"；{_paper_totals(st, strat)}。")
            st["last_bar"], st["last_session"] = t, session
    return st


def _paper_levels(symbol, session, rows_fn):
    """那天的九成日範圍邊與開閘指標：開市前紀錄有就用紀錄，沒有就即時算（R116 起才記 edge95、R118 起才記 gate_*）。"""
    fc = futu_logged_forecast(symbol, session)
    if not fc or fc.get("high_edge95") is None or "gate_ratio" not in fc:
        fc = futu_day_forecast([r for r in rows_fn() if r["date"] < session], session) or {}
    if fc.get("high_edge95") is None:
        return None
    return {k: fc.get(k) for k in PAPER_LEVEL_KEYS}


def _paper_session_bars(symbol, session, boot):
    bars = futu_session_5m(symbol, session)
    if boot and len(bars) < PAPER_BOOT_MIN_BARS:                 # 5 分 K 封存不夠（剛開始推送）→ 15 分 K
        nxt = (datetime.strptime(session, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        alt = {}
        for d in (session, nxt):
            for b in gcs_read_json(archive_blob_name("futu_k_15m", symbol, d), []):
                if isinstance(b, dict) and b.get("time_key") and to_float(b.get("volume")) and futu_session_of(b["time_key"], symbol) == session:
                    alt[b["time_key"]] = b
        if len(alt) > len(bars):
            bars = [alt[k] for k in sorted(alt)]
    return bars


def futu_paper_update(symbol, now=None):
    """每包 5 分 K 到達時：把新 K 線跑過三條策略，狀態寫回 futu/paper/<代號>.json。回傳警告清單。"""
    try:
        today = futu_session_today(now, symbol)
        prev = gcs_read_json(futu_paper_file(symbol), {})
        fresh = not (isinstance(prev, dict) and prev.get("version") == PAPER_VERSION)
        rows = []

        def rows_fn():
            if not rows:
                rows.extend(futu_series_rows(symbol))
            return rows
        if fresh or prev.get("last_session") != today:
            dates = sorted({r["date"] for r in rows_fn()} | {today})
            if fresh:
                sessions = dates[max(0, dates.index(today) - PAPER_BOOT_DAYS):]
            else:
                last = prev.get("last_session") or today
                sessions = [d for d in dates if last <= d <= today]
        else:
            sessions = [today]
        boot = {s for s in sessions if fresh and s < today}
        bars_by = {s: _paper_session_bars(symbol, s, s in boot) for s in sessions}
        if not any(bars_by.values()):
            return []
        day = prev.get("day") or {}
        levels_by = {}
        if day.get("date") == today and day.get("levels") and "gate_ratio" in day["levels"]:
            levels_by[today] = day["levels"]
        else:
            lv = _paper_levels(symbol, today, rows_fn)
            if lv:
                levels_by[today] = lv
        sig = gcs_read_json(futu_signal_file(symbol), [])
        signals = {e.get("id"): e for e in (sig if isinstance(sig, list) else []) if isinstance(e, dict)}
        trig_by = {today: _paper_trigger(signals, today)}

        def mutate(existing):
            st = existing if (isinstance(existing, dict) and existing.get("version") == PAPER_VERSION) else _paper_new_state(symbol)
            before = len(st["notices"]), len(st["trades"]), st["last_bar"]
            _paper_run(st, sessions, bars_by, levels_by, trig_by, boot, PAPER_COST)
            if (len(st["notices"]), len(st["trades"]), st["last_bar"]) == before:
                return None, 0
            return st, len(st["notices"]) - before[0]

        added = gcs_update(futu_paper_file(symbol), mutate, default_factory=dict)
        if added:
            log_event(f"📒 [紙上交易] {symbol} 新通知 {added} 則", component="futu", symbol=symbol)
        return []
    except StorageError as exc:
        log_event(f"⚠️ [紙上交易更新失敗] {exc}", severity="WARNING", component="futu")
        return ["紙上交易更新失敗（下一包會再算）"]


def futu_paper_state(symbol):
    st = gcs_read_json(futu_paper_file(symbol), {})
    return st if isinstance(st, dict) and st.get("version") == PAPER_VERSION else None


def futu_paper_report(symbol):
    st = futu_paper_state(symbol)
    if not st:
        return {"status": "empty", "symbol": symbol, "message": "紙上交易還沒開始（等第一包 5 分 K）"}
    stats = {k: _paper_stats([t for t in st["trades"] if t["strat"] == k]) for k in PAPER_STRATS}
    lv = (st.get("day") or {}).get("levels") or {}
    return {"status": "ok", "symbol": symbol, "started_utc": st["started_utc"], "last_bar": st["last_bar"],
            "snake": st["snake"], "open": st["open"], "stats": stats, "trades": st["trades"][-200:],
            "pending_notices": sum(1 for e in st["notices"] if not e.get("sent")), "cost": PAPER_COST,
            "gate": {"date": (st.get("day") or {}).get("date"), "threshold": PAPER_GATE_TH, "lookback": PAPER_GATE_LOOKBACK,
                     "lots_open": PAPER_GATE_LOTS, "text": _paper_gate_text(lv),
                     **{k: lv.get(k) for k in ("rhat_med250", "gate_ratio", "gate_open", "range")}}}   # [R118]


def futu_paper_lines(symbol, price=None, st=None):
    """四次報告用：三條策略的持倉與累計。"""
    try:
        st = st if st is not None else futu_paper_state(symbol)
    except StorageError:
        return []
    if not st:
        return []
    parts = []
    sn = st["snake"]
    for strat, cfg in PAPER_STRATS.items():
        if strat == "SNAKE":
            pos, px, since, lots = sn["pos"], sn["px"], sn["entry_time"], sn.get("lots") or 1
        else:
            tr = st["open"].get(strat) or {}
            pos, px, since, lots = tr.get("side", 0), tr.get("entry_price"), tr.get("entry_time"), tr.get("lots") or 1
        s = _paper_stats([t for t in st["trades"] if t["strat"] == strat])
        acc = f"累計 {s['n']} 筆 {s['total']:+,.0f}（開閘雙倍 {s['total_tilt']:+,.0f}）" if s["n"] else "未有完成交易"
        if pos and px is not None:
            flo = f"，浮動 {(price - px) * pos:+,.0f}" if price else ""
            parts.append(f"{cfg['zh']} {PAPER_SIDE_ZH[pos]} {px:,.0f}×{lots} 張（{_paper_hhmm(since)} 起{flo}）；{acc}")
        else:
            parts.append(f"{cfg['zh']} 空手；{acc}")
    return [f"📒 紙上交易（不下單）{_paper_gate_text((st.get('day') or {}).get('levels'))}：" + "｜".join(parts)]


def futu_range_data(symbol):
    symbol = _futu_text(symbol, 32).upper() or FUTU_RANGE_DEFAULT
    bars = gcs_read_json(futu_daily_file(symbol), [])
    bars = sorted((b for b in bars if isinstance(b, dict)), key=lambda b: str(b.get("time_key", "")))
    today = futu_session_today(symbol=symbol)
    market = futu_market(symbol)
    calendar = gcs_read_json(FUTU_CALENDAR_FILE, {}) if market["calendar"] else {}
    after_close = False                                              # [R128] 收市後、下一個交易日未開 → 以下一個交易日為「今日」
    if futu_session_end_passed(today, None, symbol) and any(str(b.get("time_key", ""))[:10] == today for b in bars):
        nxt = datetime.strptime(today, "%Y-%m-%d")
        for _ in range(10):
            nxt += timedelta(days=1)
            if futu_trading_day(nxt.strftime("%Y-%m-%d"), calendar):
                break
        today, after_close = nxt.strftime("%Y-%m-%d"), True
    data = futu_range_stats(bars, today)
    snap = read_futu_snapshot(symbol)
    snap_bars = (snap.get("bars") or []) if isinstance(snap, dict) and not snap.get("error") else []
    traded = [b for b in snap_bars if to_float(b.get("volume"))]       # 略過開市前成交量 0 的佔位 K 線
    five = (traded or snap_bars or [{}])[-1]
    age = futu_age_sec(snap) if snap and not snap.get("error") else None
    log = gcs_read_json(futu_forecast_file(symbol), [])
    done_rows = data["rows"][:-1] if data["partial"] else data["rows"]
    data["live_track"] = futu_forecast_track(log if isinstance(log, list) else [], done_rows)
    logged = next((e for e in reversed(log if isinstance(log, list) else [])
                   if isinstance(e, dict) and e.get("date") == today), None)
    if logged:                                                   # 當天已記錄的預測優先（不會因為事後補數據而變）
        data["forecast"] = {**logged, "logged": True}
    elif data.get("forecast"):                                   # [R99] 未記錄：即時算，含高位／低位
        all_rows = futu_range_rows(bars)
        completed = [r for r in all_rows if r["date"] < today] if data["partial"] else all_rows
        full = futu_day_forecast(completed, today if after_close else data["forecast"]["date"])   # [R128] 收市後 → 下一個交易日
        if full:
            data["forecast"] = full
    data["peak"] = futu_peak_status(symbol)                       # [R101][R103] 算一次，頁面與文字共用
    periods = (data["peak"] or {}).get("periods") or {}
    if after_close and "day" in periods:                            # [R128] 已收市的那天不再當「今日」卡
        periods = {k: v for k, v in periods.items() if k != "day"}
        data["peak"] = {**data["peak"], "periods": periods}
    open_keys = {k: _peak_key(today, k) for k in PEAK_KINDS}       # [R104] 還沒結束的那段不計分
    open_keys.update({k: (None if p["over"] else p["key"]) for k, p in periods.items()})
    data["accuracy"] = futu_accuracy(data.pop("_completed"), data.pop("_har"),
                                     log if isinstance(log, list) else [], open_keys)
    for kind in ("week", "month"):                                   # [R120] 本週／本月的預測高位／低位（同今日卡）
        per, cal = periods.get(kind), (data["accuracy"].get(kind) or {}).get("cal")
        if not per or not per.get("forecast") or not cal:
            continue
        ref = next((r.get("prev_close") for r in done_rows if r["date"] == per["first"]), None)
        if ref is None and per["first"] == today and done_rows:
            ref = done_rows[-1]["close"]
        if ref:
            per["forecast"].update(_hl_levels(ref, per["R"], cal["ups"], cal["downs"], _hl_band_q(kind)), band_q=_hl_band_q(kind))
        roll = (data["accuracy"].get(kind) or {}).get("cal_roll")                       # [R124] 最新預測（邊走邊改）
        if roll and per.get("rem") is not None and per.get("high") and per.get("low"):
            hs, ls, price = per["high"]["ext"], per["low"]["ext"], per["price"]
            if per["rem"] <= 0:
                per["forecast"]["roll"] = {"high": hs, "high_lo": hs, "high_hi": hs, "low": ls, "low_lo": ls, "low_hi": ls, "done": True}
            else:
                r_rem = per["r_today"] * math.sqrt(per["rem"])
                per["forecast"]["roll"] = {**_roll_levels(hs, ls, price, r_rem, roll["ups"], roll["downs"], ROLL_BAND_Q[kind]),
                                           "done": False, "r_rem": round(r_rem)}
            per["forecast"]["roll_mid"] = (data["accuracy"].get(kind) or {}).get("roll_mid")
    sig = gcs_read_json(futu_signal_file(symbol), [])
    data["signals"] = {e.get("id"): e for e in (sig if isinstance(sig, list) else []) if isinstance(e, dict)}
    data["peak_lines"] = futu_peak_lines(symbol, status=data["peak"], signals=sig)
    data["paper"] = futu_paper_state(symbol)                          # [R116] 紙上交易
    review_day = data["rows"][-1]["date"] if data["rows"] else None
    reviews = gcs_read_json(futu_review_file(symbol), [])
    data["reviews"] = [e for e in (reviews if isinstance(reviews, list) else [])
                       if isinstance(e, dict) and e.get("date") == review_day]
    nxt = datetime.strptime(today, "%Y-%m-%d")                       # [R105] 卡片標題的日期：下一個交易日
    while not data["partial"] and not after_close:                   # [R128] 收市後 today 已是下一個交易日
        nxt += timedelta(days=1)
        if futu_trading_day(nxt.strftime("%Y-%m-%d"), calendar) or nxt.year > 2100:
            break
    data["iv_compare"] = futu_iv_compare(data.get("forecast"))     # [R106] 方向一：期權 IV 對預測波幅
    data.update({"symbol": symbol, "today_hk": today, "next_day": nxt.strftime("%Y-%m-%d"), "after_close": after_close,
                 "contract": str(snap.get("source") or "").partition(":")[2] if snap else "",
                 "latest_5m": five or None,
                 "latest_5m_age_sec": None if age is None else int(age)})
    return data


def handle_futu_range_get(req, default_symbol=FUTU_RANGE_DEFAULT):
    if req.args.get("report"):                                   # [R99] 四個時點的預測／檢討
        symbol = _futu_text(req.args.get("symbol"), 32).upper() or default_symbol
        try:
            kind = req.args.get("report")
            if kind == "signals":                                    # [R101] 排程取未發的通知
                result = futu_signals_report(symbol, req.args.get("ack"))
            elif kind == "peak":
                result = {"status": "ok", **(futu_peak_status(symbol) or {})}
            elif kind == "paper":                                    # [R116] 紙上交易狀態、統計、逐筆紀錄
                result = futu_paper_report(symbol)
            elif kind == "accuracy":                                 # [R104] 日／週／月過去每一次預測的誤差
                acc = futu_range_data(symbol)["accuracy"]
                result = {"status": "ok", "symbol": symbol,
                          **{k: {**v, "recent": None} for k, v in acc.items()}}
            else:
                result = futu_report(symbol, kind)
        except StorageError as exc:
            print(f"⚠️ [Futu 報告失敗] {exc}", flush=True)
            result = {"status": "error", "reason": "storage"}
        if req.args.get("format") == "text":
            body = result.get("text") or f"[{result.get('status')}] {result.get('reason', '')}"
            return body, (200 if result["status"] in ("ok", "skip", "empty") else 503), {"Content-Type": "text/plain; charset=utf-8"}
        return _json_response(result, 200 if result["status"] in ("ok", "skip", "empty") else 503)
    try:
        data = futu_range_data(req.args.get("symbol") or default_symbol)
    except StorageError as exc:
        print(f"⚠️ [Futu 波幅讀取失敗] {exc}", flush=True)
        if req.args.get("format") == "json":
            return _json_response({"status": "error", "message": "storage read failed"}, 503)
        return html_page("風揚陣・即月期貨波幅", "<div class='banner' style='background:#fff3cd; color:#856404;'>"
                                         "⚠️ 讀取失敗，請查看 Cloud Logging。</div>"), 503
    if req.args.get("format") == "json":
        return _json_response({"status": "ok" if data["rows"] else "empty", **data}, 200)
    return build_futu_range_page(data)


def futu_range_chart(rows):
    """每日波幅柱狀圖＋20 日平均線（單一 y 軸），每根柱有原生提示框。"""
    if len(rows) < 2:
        return ""
    w, h, pad_l, pad_b, pad_t = 1000, 260, 52, 26, 12
    top = max(row["range"] for row in rows) * 1.08 or 1
    step = (w - pad_l - 8) / len(rows)
    bar_w = max(1.0, step - 2)                   # 柱間留 2px 空隙
    y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - v / top)
    ticks = [top / 4 * i for i in range(5)]
    grid = "".join(f"<line x1='{pad_l}' x2='{w - 8}' y1='{y(t):.1f}' y2='{y(t):.1f}' stroke='#e9ecef'/>"
                   f"<text x='{pad_l - 6}' y='{y(t) + 4:.1f}' text-anchor='end' font-size='11' fill='#6c757d'>{t:,.0f}</text>"
                   for t in ticks)
    bars, avg_pts = [], []
    for i, row in enumerate(rows):
        x = pad_l + i * step + 1
        top_y = y(row["range"])
        pct = "—" if row["range_pct"] is None else f"{row['range_pct']:.2f}%"
        bars.append(f"<rect x='{x:.1f}' y='{top_y:.1f}' width='{bar_w:.1f}' height='{max(0.5, h - pad_b - top_y):.1f}' "
                    f"rx='{min(2.0, bar_w / 2):.1f}' fill='#4f83cc'><title>{esc(row['date'])}  波幅 {row['range']:,.0f}（{pct}）"
                    f"\n開 {row['open']:,.0f}  高 {row['high']:,.0f}  低 {row['low']:,.0f}  收 {row['close']:,.0f}"
                    + (f"\nHAR 預測 {row['forecast']:,.0f}（80%：{row['forecast_lo']:,.0f}–{row['forecast_hi']:,.0f}）"
                       if row.get("forecast") else "") + "</title></rect>")
        window = [r["range"] for r in rows[max(0, i - 19):i + 1]]
        if len(window) == 20:
            avg_pts.append(f"{x + bar_w / 2:.1f},{y(sum(window) / 20):.1f}")
    line = (f"<polyline points='{' '.join(avg_pts)}' fill='none' stroke='#161616' stroke-width='2'/>"
            if len(avg_pts) > 1 else "")
    har_pts = [f"{pad_l + i * step + 1 + bar_w / 2:.1f},{y(min(row['forecast'], top)):.1f}"
               for i, row in enumerate(rows) if row.get("forecast")]
    if len(har_pts) > 1:                          # [R98] HAR 預測線（虛線，跟平均線用線型區分）
        line += (f"<polyline points='{' '.join(har_pts)}' fill='none' stroke='#d97706' stroke-width='2' "
                 f"stroke-dasharray='5 3'/>")
    months, labels = set(), []
    for i, row in enumerate(rows):
        if row["date"][:7] not in months:
            months.add(row["date"][:7])
            if i and pad_l + i * step < w - 40:          # 太靠右邊的月份標籤會被切掉，略過
                labels.append(f"<text x='{pad_l + i * step:.1f}' y='{h - 8}' font-size='11' fill='#6c757d'>{row['date'][2:7]}</text>")
    legend = ("<div style='display:flex; gap:16px; font-size:12px; color:#6c757d; margin-bottom:6px;'>"
              "<span><span style='display:inline-block; width:10px; height:10px; background:#4f83cc; border-radius:2px;'></span> 每日波幅（高−低）</span>"
              "<span><span style='display:inline-block; width:14px; height:2px; background:#161616; vertical-align:middle;'></span> 20 日平均</span>"
              "<span><span style='display:inline-block; width:14px; border-top:2px dashed #d97706; vertical-align:middle;'></span> HAR 預測（當天開始前）</span></div>")
    return (f"{legend}<svg viewBox='0 0 {w} {h}' style='width:100%; height:auto;' role='img' "
            f"aria-label='過去一年每日波幅柱狀圖'>{grid}{''.join(bars)}{line}{''.join(labels)}</svg>")


FY_CSS = """<style>
.fy-hero { display:flex; flex-wrap:wrap; gap:8px 18px; align-items:center; background:var(--card); border-radius:14px;
           padding:14px 18px; margin-bottom:18px; box-shadow:0 4px 15px rgba(0,0,0,.04); font-size:14px; }
.fy-hero b { font-size:20px; }
.fy-legend { font-size:12px; color:var(--muted); margin:-8px 0 18px; }
.fy-grid { display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); margin-bottom:24px; }
.fy-card { background:var(--card); border-radius:16px; padding:18px 18px 14px; box-shadow:0 4px 15px rgba(0,0,0,.04);
           border-top:4px solid var(--primary); }
.fy-card.week { border-top-color:#0aa06e; } .fy-card.month { border-top-color:#6d5bd0; }
.fy-card h2 { font-size:17px; margin:0 0 2px; } .fy-date { font-size:14px; font-weight:600; color:var(--muted); margin-left:4px; } .fy-sub { font-size:12px; color:var(--muted); margin-bottom:12px; }
.fy-big { font-size:28px; font-weight:800; line-height:1.1; } .fy-band { font-size:13px; color:var(--muted); }
.fy-row { display:flex; justify-content:space-between; gap:8px; font-size:14px; padding:6px 0; border-bottom:1px dashed #e9ecef; }
.fy-bar { height:8px; background:#eef1f4; border-radius:4px; overflow:hidden; margin:4px 0 2px; }
.fy-bar > div { height:100%; background:var(--primary); border-radius:4px; }
.fy-side { margin-top:12px; } .fy-side h3 { font-size:14px; margin:0 0 6px; }
.fy-sig { font-size:13px; line-height:1.55; padding:3px 0 3px 2px; }
.fy-note { font-size:11.5px; color:var(--muted); margin-top:10px; line-height:1.5; }
.fy-hist { margin-top:14px; padding-top:10px; border-top:2px solid #eef1f4; } .fy-hist h3 { font-size:14px; margin:0 0 6px; }
.fy-hist table { width:100%; border-collapse:collapse; font-size:12.5px; } .fy-hist th { font-weight:600; color:var(--muted); text-align:right; padding:3px 4px; }
.fy-hist td { text-align:right; padding:4px; border-bottom:1px solid #f1f3f5; white-space:nowrap; } .fy-hist td:first-child, .fy-hist th:first-child { text-align:left; }
.fy-rate { font-size:13px; line-height:1.6; margin-bottom:6px; }
.fy-rng { font-size:11px; color:var(--muted); font-weight:400; }
.fy-hist.day table { font-size:11.5px; } .fy-hist.day td, .fy-hist.day th { padding:4px 2px; }
.fy-hist.day .fy-rng { font-size:10px; }
details.fy-more { background:var(--card); border-radius:16px; padding:14px 18px; margin-bottom:16px; box-shadow:0 4px 15px rgba(0,0,0,.04); }
details.fy-more summary { cursor:pointer; font-weight:700; }
</style>"""
PERIOD_TITLE = {"day": ("📅", "今日", ""), "week": ("🗓️", "本週", "week"), "month": ("🈷️", "本月", "month")}
PEAK_CUT_TEXT = {"day": "16:30", "week": "第 4 個交易日收市", "month": "第 15 個交易日收市"}


def _n(v):
    return "—" if v is None else f"{v:,.0f}"


def _fy_signal_lines(kind, per, side, fired):
    """一邊（高位或低位）的 A／B／C 白話狀態。"""
    s, R = per[side], per["R"]
    high = side == "high"
    zh, new = ("高位", "新高") if high else ("低位", "新低")

    def fired_text(strat):
        e = fired.get(f"{kind}:{per['key']}:{side}:{strat}")
        if not e:
            return None
        when = str(e.get("asof") or e.get("made_utc") or "")[5:16]
        beyond = s["ext"] > e["ext"] if high else s["ext"] < e["ext"]
        if beyond:
            return f"❌ {when} 曾通知，之後又創{new}（判斷錯）"
        return f"✅ {when} 已通知（當時{zh} {_n(e['ext'])}），至今未再創{new}"

    def acc(strat):
        a = PEAK_ACCURACY.get(f"{kind}/{side}/{strat}")
        return f"（回測準確 {a:.0%}）" if a is not None else ""

    if per["over"]:                                               # 已結束：只說有沒有通知過
        return [f"{icon} {name}{acc(k)}：{fired_text(k) or '— 這段沒有觸發'}"
                for k, icon, name in (("A", "🅰️", "耗盡回落"), ("B", "🅱️", "機率法"), ("C", "🅲", "時間點"))]
    a_txt = fired_text("A") or (
        "✅ 條件已達成" if s["A"] else
        f"⏳ 未觸發：已走 {per['range'] / R * 100:.0f}% 預期波幅（要 ≥ 80%），"
        f"離{zh} {_n(s['dist'])} 點（要 ≥ {_n(PEAK_A[1] * R)} 點）")
    b_txt = fired_text("B") or (
        f"✅ 之後再創{new}的機率只有 {s['prob'] * 100:.0f}%" if s["B"] else
        f"⏳ 之後再創{new}的機率 {s['prob'] * 100:.0f}%（低於 5% 才通知）")
    if s["C"] is None:
        c_txt = f"⏳ {PEAK_CUT_TEXT[kind]}才判斷（屆時要離{zh} ≥ {_n(PEAK_C_BETA * R)} 點）"
    else:
        c_txt = fired_text("C") or ("✅ 條件已達成" if s["C"] else f"✖️ {PEAK_CUT_TEXT[kind]}時離{zh}不夠遠，這段不觸發")
    return [f"🅰️ 耗盡回落{acc('A')}：{a_txt}", f"🅱️ 機率法{acc('B')}：{b_txt}", f"🅲 時間點{acc('C')}：{c_txt}"]


def _fy_md(day):
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.month}月{d.day}日（{WEEKDAY_ZH[d.weekday()]}）"


def _fy_period_dates(kind, day):
    """[R105] 卡片標題旁的日期：今日 = 那個交易日；本週 = 週一至週五；本月 = 年月。"""
    if not day or not ARCHIVE_DATE_RE.match(day):
        return ""
    if kind == "day":
        return _fy_md(day)
    d = datetime.strptime(day, "%Y-%m-%d")
    if kind == "week":
        mon = d - timedelta(days=d.weekday())
        return f"{_fy_md(mon.strftime('%Y-%m-%d'))} 至 {_fy_md((mon + timedelta(days=4)).strftime('%Y-%m-%d'))}"
    return f"{d.year}年{d.month}月"


def _fy_hist_label(kind, rec):
    if kind == "day":
        d = datetime.strptime(rec["key"], "%Y-%m-%d")
        return f"{rec['key'][5:]}{WEEKDAY_ZH[d.weekday()]}"
    if kind == "week":
        return f"{rec['first'][5:]} 起"
    return rec["key"]


def _fy_history(kind, acc):
    """[R104] 過去 7 次預測對實際，加全部歷史落在預計範圍的比率。
    [R109] 日：預測高位、低位各有預計範圍，兩邊都落在範圍內才算 ✅；週、月只預測波幅，看波幅。"""
    if not acc or not acc.get("n"):
        return ""
    unit = {"day": "天", "week": "週", "month": "個月"}[kind]
    label = {"day": "交易日", "week": "週", "month": "月"}[kind]
    okp = HL_OK_PCT_BY[kind]                                          # [R126] ✓ 的門檻按日／週／月
    body = ""
    if acc.get("hit_high_n") and all(r.get("high") is not None for r in acc["recent"]):   # [R120] 日、週、月同一格式
        rng_zh = {"day": "全日波幅", "week": "全週波幅", "month": "全月波幅"}[kind]
        rate = (f"🎯 <b>高、低都落在預計範圍：{acc['hit_rate']}%</b>（{acc['n']} {unit}中 {acc['hits']} 次）"
                + (f"・<b>都在 {okp:g}% 內：{acc['within_rate']}%</b>" if acc.get("within_rate") is not None else "") + "<br>"
                f"🕖 近 {len(acc['recent'])} 次有 {acc['recent_hits']} 次落在範圍、{acc.get('recent_within', 0)} 次在 {okp:g}% 內・"
                f"預測高位平均差 {_n(acc.get('mae_high'))} 點、低位 {_n(acc.get('mae_low'))} 點<br>"
                f"📏 各自計：高位 {acc.get('hit_high_rate')}%・低位 {acc.get('hit_low_rate')}%・"
                f"{rng_zh} {acc.get('hit_range_rate')}%（{acc.get('hit_range_n')} {unit}）")

        def side(pred, lo, hi, actual):                               # [R125] 相差 1% 內 → 綠字 ✓；超過 → 紅字 ↑／↓
            diff = actual - pred                                          # [R122] 實際 − 預測：高 → 綠、低 → 紅
            pct = diff / pred * 100 if pred else 0.0
            mark = " ✓" if abs(pct) <= okp else (" ↑" if diff > 0 else " ↓")
            return (f"<td>{_n(pred)}<br><span class='fy-rng'>{_n(lo)}–{_n(hi)}</span></td>"
                    f"<td><b class='{'pos' if mark == ' ✓' else 'neg'}'>{_n(actual)}{mark}</b>"
                    f"<br><span class='fy-rng {pnl_class(diff)}'>{diff:+,.0f}<br>{pct:+.2f}%</span></td>")

        head = (f"<tr><th>{label}</th><th>預測高<br><span class='fy-rng'>預計範圍</span></th><th>實際高</th>"
                "<th>預測低<br><span class='fy-rng'>預計範圍</span></th><th>實際低</th></tr>")
        for r in reversed(acc["recent"]):
            body += (f"<tr><td>{'📝 ' if r.get('live') else ''}{esc(_fy_hist_label(kind, r))}</td>"
                     + side(r["high"], r["high_lo"], r["high_hi"], r["actual_high"])
                     + side(r["low"], r["low_lo"], r["low_hi"], r["actual_low"]) + "</tr>")
        band_zh = f"{HL_BAND_ZH}（每邊約 96%）" if kind == "day" else "按過去各段的極端比例定（1%／99% 分位，每邊約 95%）"
        legend = (f"<div class='fy-note'>📐 <b>預計範圍</b>：按過去預測的準繩，{band_zh}。"
                  f"綠字 ✓ = 實際與預測相差 {okp:g}% 以內（今日 1%、本週 2%、本月 4%，按時間長度放寬）；"
                  f"紅字 = 相差超過 {okp:g}%（↑ 實際較高、↓ 實際較低）。"
                  "實際下面的小字 = 實際 − 預測（點數與百分比；綠 = 實際比預測高、紅 = 比預測低）。"
                  "「落在預計範圍」另計：兩邊同時落在範圍約九成屬正常"
                  + ("；範圍比 10-05 前寬約七成（R119）。" if kind == "day" else "；週、月的段數少，比率會較波動。") + "</div>")
        note = ("📝 = 開市前實時紀錄；其餘為逐日前推重算（只用當時已知的數據）。" if kind == "day" else
                "逐段前推重算：每段只用之前的數據預測，比例也只用之前已完結的段估計。")
    else:
        # [R108] 白話：「80% 區間」→「預計範圍（十次有八次落在這裡）」，「命中」→「落在範圍內」
        rate = (f"🎯 <b>落在預計範圍：{acc['hit_rate']}%</b>（{acc['n']} {unit}中 {acc['hits']} 次；目標約八成）<br>"
                f"🕖 近 {len(acc['recent'])} 次有 {acc['recent_hits']} 次落在範圍內・預測與實際平均差 {_n(acc['mae'])} 點"
                f"（整體{'預測偏低' if acc['bias'] > 0 else '預測偏高'} {_n(abs(acc['bias']))} 點）")
        head = (f"<tr><th>{label}</th><th>預測<br><span class='fy-rng'>預計範圍</span></th>"
                "<th>實際</th><th>差距</th></tr>")
        for r in reversed(acc["recent"]):
            mark = " ↑" if r["actual"] > r["hi"] else (" ↓" if r["actual"] < r["lo"] else " ✓")     # [R121]
            body += (f"<tr><td>{esc(_fy_hist_label(kind, r))}</td>"
                     f"<td>{_n(r['forecast'])}<br><span class='fy-rng'>{_n(r['lo'])}–{_n(r['hi'])}</span></td>"
                     f"<td><b class='{'pos' if mark == ' ✓' else 'neg'}'>{_n(r['actual'])}{mark}</b></td>"
                     f"<td class='{'pos' if r['err'] >= 0 else 'neg'}'>{r['err']:+,.0f}</td></tr>")
        legend = ("<div class='fy-note'>📐 <b>預計範圍</b>：按過去預測的準繩，十次有八次實際波幅會落在這裡。"
                  "綠字 ✓ = 實際落在範圍內；紅字 = 跑出範圍（↑ 比上限大、↓ 比下限細）。差距 = 實際 − 預測。</div>")
        note = "逐段前推重算：每段只用之前的數據預測，比例也只用之前已完結的段估計。"
    return (f"<div class='fy-hist {'day' if '實際高' in head else ''}'><h3>📜 過去 {len(acc['recent'])} 次預測</h3><div class='fy-rate'>{rate}</div>"
            f"<table>{head}{body}</table>{legend}<div class='fy-note'>{note}</div></div>")


def _fy_period_card(kind, per, fc, fired, today_label, waiting=None, acc=None, day=None):
    icon, title, css = PERIOD_TITLE[kind]
    dates = _fy_period_dates(kind, day)
    if kind == "day" and not per and today_label.startswith("下一個交易日"):      # 休市日顯示的是下一個交易日
        title = "下個交易日"
    if per:
        done = (f"已收市 {per['sessions_done']}／{per['sessions']} 個交易日" if kind != "day" else "日市＋當晚夜市")
        sub = f"{done}" + ("・🏁 已結束" if per["over"] else "")
    else:
        sub = today_label
    html = [f"<div class='fy-card {css}'><h2>{icon} {title}"
            + (f" <span class='fy-date'>{esc(dates)}</span>" if dates else "") + f"</h2><div class='fy-sub'>{esc(sub)}</div>"]
    if fc:
        html.append(f"<div>🔮 預測波幅</div><div class='fy-big'>{_n(fc['range'])} 點</div>"
                    f"<div class='fy-band'>📐 預計範圍 {_n(fc['lo'])}–{_n(fc['hi'])} 點（十次有八次落在這裡）</div>")
        if fc.get("high") is not None:
            html.append(f"<div class='fy-row'><span>🎯 預測高位</span><b>{_n(fc['high'])}</b></div>"
                        + (f"<div class='fy-band'>📐 預計範圍 {_n(fc['high_lo'])}–{_n(fc['high_hi'])}</div>" if fc.get("high_lo") is not None else "")
                        + f"<div class='fy-row'><span>🎯 預測低位</span><b>{_n(fc['low'])}</b></div>"
                        + (f"<div class='fy-band'>📐 預計範圍 {_n(fc['low_lo'])}–{_n(fc['low_hi'])}（{HL_BAND_ZH if kind == 'day' else '按過去極端比例，每邊約 95%'}）</div>" if fc.get("low_lo") is not None else ""))
        rl = fc.get("roll")                                               # [R124] 本週／本月：邊走邊改的最新預測
        if rl and per:
            done_zh = f"已收市 {per['sessions_done']}／{per['sessions']} 個交易日"
            if rl.get("done"):
                html.append(f"<div class='fy-row'><span>🔄 最新預測</span><b>🏁 已結束：高 {_n(rl['high'])}／低 {_n(rl['low'])}</b></div>")
            else:
                html.append(f"<div class='fy-row'><span>🔄 最新預測高位（{done_zh}）</span><b>{_n(rl['high'])}</b></div>"
                            f"<div class='fy-band'>📐 更新後範圍 {_n(rl['high_lo'])}–{_n(rl['high_hi'])}</div>"
                            f"<div class='fy-row'><span>🔄 最新預測低位</span><b>{_n(rl['low'])}</b></div>"
                            f"<div class='fy-band'>📐 更新後範圍 {_n(rl['low_lo'])}–{_n(rl['low_hi'])}</div>")
            rm = fc.get("roll_mid")
            html.append("<div class='fy-note'>🔄 最新預測 = 已出現的高／低，加上「現價 ± 剩餘日子的預測波幅 × 過去比例」；每包 K 線更新，"
                        "範圍隨日子過去收窄。上面「預測高位／低位」是段首定一次的原始預測，過去 7 次表按它計分。"
                        + (f"過去各段走到一半時，最新預測的範圍平均寬 {rm['width']:,} 點、高低都中 {rm['hit_rate']}%"
                           f"（高位平均差 {_n(rm['mae_high'])}、低位 {_n(rm['mae_low'])} 點）。" if rm else "") + "</div>")
    if per:
        used = per["range"] / fc["range"] * 100 if fc and fc.get("range") else None
        html.append(f"<div class='fy-row'><span>📏 已走</span><b>{_n(per['range'])} 點"
                    + (f"（{used:.0f}%）" if used is not None else "") + "</b></div>")
        if used is not None:
            html.append(f"<div class='fy-bar'><div style='width:{min(used, 100):.0f}%'></div></div>")
        html.append(f"<div class='fy-row'><span>⬆️ 目前高位</span><b>{_n(per['high']['ext'])}</b></div>"
                    f"<div class='fy-row'><span>⬇️ 目前低位</span><b>{_n(per['low']['ext'])}</b></div>")
        for side, head in (("high", "⬆️ 高位已出現了嗎？"), ("low", "⬇️ 低位已出現了嗎？")):
            lines = _fy_signal_lines(kind, per, side, fired)
            html.append(f"<div class='fy-side'><h3>{head}</h3>"
                        + "".join(f"<div class='fy-sig'>{esc(x)}</div>" for x in lines) + "</div>")
    elif waiting:
        html.append(f"<div class='fy-note'>{esc(waiting)}</div>")
    html.append(_fy_history(kind, acc))
    if kind == "week":
        html.append("<div class='fy-note'>週預測 = 第一天預測 × √交易日數（按過去數據校準）。</div>")
    elif kind == "month":
        html.append("<div class='fy-note'>月預測同理；月的樣本少，結果僅供參考。</div>")
    html.append("</div>")
    return "".join(html)


def _n2(v):
    return "—" if v is None else f"{v:.2f}"


MONEY_SELL = {                                  # [R107] 方向一合成回測摘要（vol_premium.py，2024-05 至 2026-10，125 週，每腳成本 4 點）
    "status": "📊 真實數據 1 年：每週沽 1σ 勒式 +55 點、84% 週賺・利潤集中在 2026 上半年",
    "lines": [
        "📊 VHSI 平均 22.9%，實際波動約 19.5%：市場長期高估波幅，賣方有優勢。",
        "💵 每週沽價平跨式：平均 +86 點、68% 週數賺；但最差一週 −2,096 點（2024 年 9 月救市急升），2024 年整體虧。",
        f"🎯 只在 VHSI ÷ 預測 ≥ {VHSI_SELL_RATIO} 時賣（約四週一次，37 週）：跨式平均 +188 點、最差 −597；"
        "鐵鷹（1σ 沽、2σ 買保護）平均 +69 點、最差 −362，三年每年都賺。",
        "🧭 前半段挑門檻、後半段測試（28 週）：四種賣法平均都賺。",
        "📊 [R117] 真實數據（港交所週期權結算價與 IV，2025-10 至 2026-10，51 週）：價平 IV 平均 18.3%，比 VHSI 低 15%、"
        "幾乎等於風揚陣預測；每週沽價平跨式 +63 點（61% 週賺、最差 −825），沽 1σ 勒式 +55 點（84% 週賺、最差 −472、t 2.85），"
        "鐵鷹 +17；月期權跨式每月 −127。利潤集中在 2026 年 1 至 5 月，2025 年第四季與 2026 年下半年跨式都虧。",
        "⚠️ 「VHSI ÷ 預測 ≥ 1.2 才賣」在真實數據上對跨式沒幫助（+5），對鐵鷹略好（+27）；週期權 IV 對預測的比值也沒有預測力。"
        "港交所只保留 12 個月報告，之後每週自動續抓，累積到 2 年再定。",
    ],
}


MONEY_FADE = {                                  # 方向二回測摘要（fade_pnl.py，2023-12 至 2026-10，15 分 K）
    "status": "❌ 回測不賺錢・不建議用",
    "lines": [
        "📉 交易日：A／B／C 之後反向做，不扣成本每筆 −4 至 +7 點（t 值都 < 1，等於零）；扣 3 點成本後幾乎全虧。",
        "🔍 原因：「頂底已現」判斷很準（B 約 96%），但通知時價格已離高位約 230 點，之後升跌各半——頂已見不代表會回頭。",
        "🎯 前半段挑最好的參數（每筆 +15 至 +35 點），後半段六組有五組變負：過度擬合。",
        "🗓️ 週：沽空邊後半段有賺，但同時間無條件沽空也賺，部分組合賺更多——功勞是那段時間恒指偏弱，不是訊號。",
        "👉 用法改為「不追」提示：高位已現就不要再追買，低位已現就不要再追沽。",
        "📌 另測：預先在預測高位掛沽、預測低位掛買，止蝕放在預計範圍外邊——止蝕率只有約一成，"
        "但每筆平均約 0（範圍說明價格大概不會去哪，不會說它會去哪），要配合 🐍 蛇蟠陣判斷方向。",
        "🐍 再測：蛇蟠陣做多才在預測低位買、做空才在預測高位沽——每筆 −12.5 點、RRR 0.90，仍然不賺；"
        "蛇的優勢在持倉多日追趨勢，每天收市平倉就拿不到。",
        "🐍 跟蛇持倉多日、週預計範圍止蝕（20 組）：都跑不贏蛇本身（每筆約 +76 點）；週止蝕平均離約 1,300 點，"
        "蛇自己的反手先到，幾乎用不上。只有「週目標止賺」前後半段都賺，未顯著。",
        "🐍 改用日預計範圍（九成）止蝕：略好過蛇本身（每筆 +81 點）；加週目標止賺最穩——回撤最小、"
        "前後半段和三年都賺（t 1.34，未顯著），建議先紙上交易。",
        "🎯 預測高低位都出現後才入、1:2 RRR：只有 9% 日子出現、約 40 筆；跟蛇每筆 +56 點（好過開市就入），"
        "但樣本太少、不及蛇本身，反向回歸則虧。",
        "📶 訊號版（「高位已出現」「低位已出現」都亮後才入、跟蛇、1:2）：🅰️ 耗盡回落每筆 +122 點、三年都賺"
        "（t 1.33，後半段轉負，未顯著）；🅱️ 機率法 +44 點。建議與蛇本身並排紙上交易。",
        "📐 R 測試（Futu 3 年＋HK50 差價合約 4 年）：訊號＋跟蛇幾乎每個 R 都正期望值；最穩是 🅱️＋跟蛇＋3R 止賺"
        "（每筆 +0.10R 至 +0.13R、RRR 2.3 至 2.7、勝率約 35%），R 再大目標很少碰到，期望值不再增加。",
    ],
}


def _fy_money(data):
    """[R106] 💰 四個方向：狀態＋今天的數字。全部只是研究，不接下單。"""
    fc = data.get("forecast") or {}
    rng = fc.get("range")
    s = data.get("summary") or {}
    ivc = data.get("iv_compare")
    cards = []

    def card(icon, title, status, body, css=""):
        cards.append(f"<div class='fy-card {css}'><h2>{icon} {title}</h2><div class='fy-sub'>{status}</div>{body}</div>")

    # 一、賣波幅（期權）  [R107] 用 VHSI 判斷（回測用的就是它），週期權 IV 只作參考
    now_txt = ""
    if ivc and ivc.get("har_vol"):
        now_txt += f"<div class='fy-row'><span>🔮 風揚陣預測（年化）</span><b>{ivc['har_vol']:.1f}%</b></div>"
        if ivc.get("vhsi"):
            ok = ivc.get("vhsi_ratio") is not None and ivc["vhsi_ratio"] >= VHSI_SELL_RATIO
            now_txt += (f"<div class='fy-row'><span>📈 VHSI（{esc(ivc.get('vhsi_time') or '')}）</span><b>{ivc['vhsi']:.1f}%</b></div>"
                        f"<div class='fy-row'><span>⚖️ VHSI ÷ 預測</span><b>{_n2(ivc.get('vhsi_ratio'))}</b></div>"
                        + (f"<div class='fy-sig'>✅ 達到 {VHSI_SELL_RATIO}：合成回測的賣出條件（真實 1 年數據：對鐵鷹略有幫助、對跨式沒有）</div>" if ok else
                           f"<div class='fy-sig'>⏸️ 未到 {VHSI_SELL_RATIO}：合成回測中這種週不賣（真實數據顯示這個門檻作用不大）</div>"))
        else:
            now_txt += ("<div class='fy-note'>➕ 本地腳本 FUTU_SYMBOLS 加上 HK.800125（VHSI），這裡就會即時判斷賣不賣。</div>")
        if ivc.get("iv") is not None:
            now_txt += (f"<div class='fy-row'><span>🎟️ 週期權價平 IV（{esc(ivc.get('expiry') or '')} 到期）</span>"
                        f"<b>{ivc['iv']:.1f}%{'' if ivc.get('fresh') else '（休市，舊報價）'}</b></div>")
    else:
        now_txt = "<div class='fy-note'>⏳ 等開市前預測與 Futu 數據。</div>"
    body = "".join(f"<div class='fy-sig'>{esc(x)}</div>" for x in MONEY_SELL["lines"])
    card("💹", "方向一：賣波幅（期權）", MONEY_SELL["status"],
         "<div class='fy-sig'>期權價格裡有市場預期的波幅（IV）。IV 長期高於實際波幅，賣期權就能賺這個差價；"
         "VHSI 明顯高於風揚陣預測才賣。</div>" + body + now_txt +
         "<div class='fy-note'>⚠️ 賺小蝕大，要細倉、優先用有保護的鐵鷹。合成回測用 VHSI（30 日 IV）代替週期權 IV，"
         "要先用真實週期權報價校準幾星期。詳見 MONEY_REPORT.md。之後跟 ☁️ 雲垂陣共用。</div>", "month")
    # 二、反向做（日內）
    if MONEY_FADE:
        body = "".join(f"<div class='fy-sig'>{esc(x)}</div>" for x in MONEY_FADE["lines"])
        status = MONEY_FADE["status"]
    else:
        body, status = "<div class='fy-note'>回測進行中。</div>", "🧪 回測中"
    card("🔄", "方向二：頂底已現 → 反向做", status,
         "<div class='fy-sig'>當天（或本週）已走完預測波幅，A／B／C 確認高位或低位已出現 → 在區間邊緣反向做，止蝕放在高（低）位之外。</div>"
         + body + "<div class='fy-note'>3 年 15 分 K 回測，每筆扣 3 點成本；恒指期貨每點 HK$50，小型恒指 HK$10。"
         "詳見 research/hsi_futures_range/MONEY_REPORT.md。</div>", "week")
    # 三、風險管理
    avg = s.get("avg_range")
    if rng:
        size = f"{avg / rng:.2f} 倍" if avg else "—"
        today = (f"<div class='fy-row'><span>🛡️ 示例止蝕（½ 個預測波幅）</span><b>{_n(rng / 2)} 點</b></div>"
                 f"<div class='fy-row'><span>⚖️ 倉位係數（一年平均 ÷ 今日預測）</span><b>{size}</b></div>")
    else:
        today = ""
    card("🛡️", "方向三：管理風險", "💡 建議・未回測",
         "<div class='fy-sig'>不直接賺錢，但令其他策略更穩：止蝕距離跟預測波幅走（大波幅日放寬、小波幅日收窄）；"
         "倉位按預測波幅調整，令每天風險差不多。</div>" + today +
         "<div class='fy-note'>之後會接到 🐍 蛇蟠陣：預測高位遠低於通道上軌時，當天突破機會較低，可以不追。</div>")
    # 四、小波幅日做突破
    past = sorted(r["forecast"] for r in data.get("rows") or [] if r.get("forecast"))
    if rng and past:
        pct = sum(1 for x in past if x <= rng) / len(past) * 100
        flag = "✅ 屬於小波幅日（≤ 20%）" if pct <= 20 else "— 不是小波幅日"
        today = (f"<div class='fy-row'><span>📊 今日預測在一年中的位置</span><b>{pct:.0f}%</b></div>"
                 f"<div class='fy-sig'>{flag}</div>")
    else:
        today = ""
    card("🚀", "方向四：小波幅日做突破", "💡 想法・未回測",
         "<div class='fy-sig'>預測波幅特別小（一年中最低 20%）的日子，之後常有大波動；配合突破策略，突破才追。</div>" + today)
    return ("<div class='section-header'>💰 怎樣用來賺錢（四個方向）</div>"
            "<div class='fy-legend'>全部是研究，不接下單；方向一、二做了盈虧回測，三、四未回測。下單以券商即時報價為準。</div>"
            f"<div class='fy-grid'>{''.join(cards)}</div>")


def _fy_paper(data):
    """[R116] 📒 紙上交易：三條策略的持倉、今日訊號、累計與最近交易。"""
    st = data.get("paper")
    price = (data.get("latest_5m") or {}).get("close")
    head = ("<div class='section-header'>📒 紙上交易（三條策略，跟實時 5 分 K 走）</div>"
            "<div class='fy-legend'>回測挑出來的三條，每包 5 分 K 到達時按規則記入市、出場，入市和出場都發 Telegram；"
            f"每筆扣 {PAPER_COST:g} 點成本；只是紀錄，不下單。規則見 research/hsi_futures_range/PAPER_TRADING.md。<br>"
            f"⚡ <b>波幅開閘</b>（R118）：今日 HAR 預測 R̂ ÷ 過去 {PAPER_GATE_LOOKBACK} 日 R̂ 中位 ≥ {PAPER_GATE_TH:g} 就開閘，"
            f"開閘日入市記 {PAPER_GATE_LOTS} 張、其餘 1 張；每條策略「固定 1 張」與「開閘雙倍」兩條帳並記"
            "（回測：🅱️／🅰️ 的利潤集中在開閘日入市的交易、蛇沒有，research/hsi_futures_range/vol_gate/REPORT.md、gate_tilt/REPORT.md）。</div>")
    if not st:
        return head + ("<div class='section'>⏳ 等第一包即月期貨 5 分 K 到達就開始"
                       f"（第一次會先用之前 {PAPER_BOOT_DAYS} 個交易日算出蛇蟠陣的持倉）。</div>")
    cards, sn, sigs = [], st["snake"], data.get("signals") or {}
    day = st.get("day") or {}
    today, lv = day.get("date"), day.get("levels") or {}
    gate_cls = "pos" if lv.get("gate_open") else ("neg" if lv.get("gate_ratio") is not None else "")
    gate_box = (f"<div class='section'><b class='{gate_cls}'>{esc(_paper_gate_text(lv))}</b>"
                + (f"　今日 R̂ {_n(lv.get('range'))} 點／{PAPER_GATE_LOOKBACK} 日中位 {_n(lv.get('rhat_med250'))} 點"
                   if lv.get("gate_ratio") is not None else "")
                + (f"　（{esc(_day_label(today))}）" if today else "") + "</div>")
    for strat, cfg in PAPER_STRATS.items():
        trades = [t for t in st["trades"] if t["strat"] == strat]
        s = _paper_stats(trades)
        if strat == "SNAKE":
            pos, px, since = sn["pos"], sn["px"], sn["entry_time"]
            detail = (f"<div class='fy-row'><span>📏 通道（前 {PAPER_SNAKE_N} 個蛇日高／低）</span><b>{_n(sn['upper'])}／{_n(sn['lower'])}</b></div>"
                      if sn.get("upper") is not None else f"<div class='fy-note'>⏳ 要先有 {PAPER_SNAKE_N} 個完整蛇日才有通道。</div>")
        else:
            tr = st["open"].get(strat) or {}
            pos, px, since = tr.get("side", 0), tr.get("entry_price"), tr.get("entry_time")
            if tr:
                detail = (f"<div class='fy-row'><span>🛡️ 止蝕（九成日範圍邊）</span><b>{_n(tr['stop'])}</b></div>"
                          f"<div class='fy-row'><span>🎯 目標（{cfg['rr']:g}R）</span><b>{_n(tr['target'])}</b></div>")
            else:
                k = cfg["signal"]
                hi, lo = sigs.get(f"day:{today}:high:{k}"), sigs.get(f"day:{today}:low:{k}")
                detail = (f"<div class='fy-sig'>今日訊號：高位已現 {'✅' if hi else '⏳'}　低位已現 {'✅' if lo else '⏳'}"
                          + ("　→ 兩邊都亮，下一根開市跟蛇入市" if hi and lo and strat not in day.get("done", []) else "") + "</div>"
                          + (f"<div class='fy-row'><span>📐 今日止蝕位（做多／做空）</span>"
                             f"<b>{_n(lv.get('low_edge95'))}／{_n(lv.get('high_edge95'))}</b></div>" if lv.get("high_edge95") is not None else ""))
        if pos and px is not None:
            flo = (price - px) * pos if price else None
            lots = (sn.get("lots") if strat == "SNAKE" else (st["open"].get(strat) or {}).get("lots")) or 1
            status = (f"<div class='fy-big'>{PAPER_SIDE_ZH[pos]} <span style='font-size:18px'>{_n(px)}</span>"
                      f" <span style='font-size:13px'>×{lots} 張</span></div>"
                      f"<div class='fy-band'>{esc(_paper_hhmm(since))} 起"
                      + (f"・浮動 <b class='{pnl_class(flo)}'>{flo:+,.0f}</b> 點" + (f"（×{lots} = {flo * lots:+,.0f}）" if lots > 1 else "")
                         if flo is not None else "") + "</div>")
        else:
            status = "<div class='fy-big'>空手</div><div class='fy-band'>等訊號</div>"
        if s["n"]:
            r_txt = f"・{s['R']:+.2f}R" if s.get("R") is not None else ""
            stat = (f"<div class='fy-row'><span>📊 累計（固定 1 張）</span><b>{s['n']} 筆・{s['total']:+,.0f} 點</b></div>"
                    f"<div class='fy-row'><span>每筆／勝率／RRR</span><b>{s['mean']:+,.0f}・{s['win']:.0%}・{_n2(s['rrr'])}</b></div>"
                    f"<div class='fy-row'><span>最大回撤{'／每筆 R' if r_txt else ''}</span><b>{_n(s['dd'])}{r_txt}</b></div>"
                    f"<div class='fy-row'><span>⚡ 開閘雙倍累計／回撤</span><b class='{pnl_class(s['total_tilt'])}'>{s['total_tilt']:+,.0f}</b>"
                    f"<b>／{_n(s['dd_tilt'])}</b></div>"
                    f"<div class='fy-row'><span>開閘日入市 {s['gate_n']} 筆／其餘 {s['n'] - s['gate_n']} 筆（1 張）</span>"
                    f"<b>{s['gate_total']:+,.0f}／{s['rest_total']:+,.0f}</b></div>")
            rows = "".join(f"<tr><td>{esc(_paper_hhmm(t['entry_time']))}</td><td>{PAPER_SIDE_ZH[t['side']]}</td><td>{_n(t['entry_price'])}</td>"
                           f"<td>{_n(t['exit_price'])}</td><td>{esc(t['exit_reason'])}</td>"
                           f"<td class='{pnl_class(t['net'])}'>{t['net']:+,.0f}</td><td>{'⚡2' if (t.get('lots') or 1) > 1 else '1'}</td></tr>"
                           for t in reversed(trades[-5:]))
            stat += (f"<div class='fy-hist'><h3>最近 {min(5, len(trades))} 筆</h3><table>"
                     f"<tr><th>入市</th><th>方向</th><th>入</th><th>出</th><th>原因</th><th>淨點數</th><th>張</th></tr>{rows}</table></div>")
        else:
            stat = "<div class='fy-note'>還沒有完成的交易。</div>"
        cards.append(f"<div class='fy-card {cfg['css']}'><h2>{cfg['zh']}</h2><div class='fy-sub'>{esc(cfg['desc'])}</div>"
                     f"{status}{detail}{stat}</div>")
    asof = f"最新處理到 {esc(_paper_hhmm(st['last_bar']))}" if st.get("last_bar") else "還沒處理過 K 線"
    return (head + gate_box + f"<div class='fy-grid'>{''.join(cards)}</div>"
            f"<div class='fy-legend'>{asof}・逐筆紀錄 JSON：?view=futu_range&amp;report=paper</div>")


def build_futu_range_page(data):
    rows, s, symbol = data["rows"], data["summary"], data["symbol"]
    m = futu_market(symbol)                                           # [R127] 市場設定（恒指／ES）
    nav = (f"<div class='nav'><div class='brand'><div class='brand-logo'>{BRAND_LOGO_SVG}</div>"
           f"<h1 class='page-title'>{m['title']}</h1></div>"
           f"{page_nav(m['view'], extra=[('?view=dashboard', '📡 回 Futu 行情')] if m['intraday'] else [])}</div>")
    if not rows:
        hint = (f"本地執行 push_to_gcp.py 的 <span class='mono'>--backfill {esc(symbol)}</span> 補歷史，之後每 5 分鐘會自動更新。" if m["intraday"]
                else "GitHub Actions 的 es_daily_push.yml 每個交易日收市後推入 yfinance 的 ES 連續合約日線；第一次要手動 dispatch 補歷史。")
        body = nav + f"<div class='section'>還沒有交易日 K 數據。{hint}</div>"
        return html_page(m["title"], body, head_extra=FY_CSS)
    latest = rows[-1]
    five = data.get("latest_5m") or {}
    age = data.get("latest_5m_age_sec")
    stale = age is None or age > FUTU_STALE_SEC
    peak = data.get("peak") or {}
    periods = peak.get("periods") or {}
    trading = data["partial"] and not stale
    if m["intraday"]:
        state = "🟢 交易中" if trading else ("⚠️ 推送可能已停止" if data["partial"] else "🌙 休市／未開市")
        upd = f"⏱️ {esc(countdown_text(age)) + ' 前更新' if age is not None else '—'}"
    else:                                                             # [R127] 只有日線：顯示最新收市日
        state = "📅 每日收市後更新（沒有日內 5 分 K）"
        upd = f"🗂️ 最新收市日 {esc(latest['date'])}"
    hero = (f"<div class='fy-hero'><span>💹 {'現價' if m['intraday'] else '最新收市'} <b>{_n(five.get('close') or peak.get('price') or latest['close'])}</b></span>"
            f"<span>📄 合約 {esc(data.get('contract') or (latest['source'].partition(':')[2] if latest.get('source') else '—'))}</span>"
            f"<span>{upd}</span>"
            f"<span>{state}</span></div>"
            f"<div class='fy-legend'>🅰️ 耗盡回落｜🅱️ 機率法｜🅲 時間點　✅ 已通知／已達成　⏳ 未到　❌ 通知後又破　{m['hours_zh']}</div>")
    fc = data.get("forecast")
    day_fc = fc if fc else None
    day_date = ((periods.get("day") or {}).get("first")
                or (fc.get("date") if fc and fc.get("date") not in (None, "next") else data.get("next_day")))
    period_day = peak.get("today") or day_date                     # [R105] 本週／本月以目前交易日所在的那段為準
    today_label = m["session_zh"] if fc and fc.get("date") not in (None, "next") else "下一個交易日（開市前預測）"
    waiting = (f"⏳ {m['open_zh']}開始判斷高低位是否已出現。" if m["intraday"] else
               "ℹ️ ES 暫時只有日線，沒有日內「已走」與高低位訊號；預測、預計範圍與過去紀錄照常。") if "day" not in periods else None
    accs = data.get("accuracy") or {}
    cards = ("<div class='fy-grid'>"
             + _fy_period_card("day", periods.get("day"), day_fc, data.get("signals") or {}, today_label, waiting,
                               accs.get("day"), day_date)
             + _fy_period_card("week", periods.get("week"), (periods.get("week") or {}).get("forecast"),
                               data.get("signals") or {}, "本週未開始", acc=accs.get("week"), day=period_day)
             + _fy_period_card("month", periods.get("month"), (periods.get("month") or {}).get("forecast"),
                               data.get("signals") or {}, "本月未開始", acc=accs.get("month"), day=period_day)
             + "</div>")
    review_html = "".join(f"<div class='log-card'><div class='log-ctx' style='white-space:pre-wrap;'>{esc(e.get('text', ''))}</div></div>"
                          for e in data.get("reviews") or [])
    reviews = (f"<details class='fy-more' open><summary>🧾 {esc(latest['date'])} 的檢討（12:00／16:30／03:00）</summary>{review_html}</details>"
               if review_html else "")
    bt, lt = data.get("backtest") or {}, data.get("live_track") or {}
    live = (f"實時紀錄 {lt['days']} 天：平均差 {_n(lt.get('mae'))} 點、落在預計範圍 {lt.get('coverage_80')}%" if lt.get("days")
            else "實時紀錄：從開始運作起每天累積")
    pct = lambda v: "—" if v is None else f"{v:.2f}%"
    stats = f"""
    <div class='grid'>
      <div class='card'><div class='card-title'>🎯 預測準確度（回測 {bt.get('days') or 0} 天）</div><div class='card-value'>±{_n(bt.get('mae'))}</div>
        <div class='card-desc'>預測與實際平均差（點）・落在預計範圍 {bt.get('coverage_80') if bt.get('coverage_80') is not None else '—'}%<br>{esc(live)}</div></div>
      <div class='card'><div class='card-title'>📊 一年平均波幅</div><div class='card-value'>{_n(s['avg_range'])}</div>
        <div class='card-desc'>中位數 {_n(s['median_range'])}・平均 {pct(s['avg_range_pct'])}</div></div>
      <div class='card'><div class='card-title'>📉 近 20 日平均波幅</div><div class='card-value'>{_n(s['avg_range_20'])}</div>
        <div class='card-desc'>ATR(14) {_n(s['atr_14'])}</div></div>
      <div class='card'><div class='card-title'>📌 {esc(s['last_date'] or '—')} 波幅位置</div><div class='card-value'>{'—' if s['last_range_percentile'] is None else str(s['last_range_percentile']) + '%'}</div>
        <div class='card-desc'>一年中 ≤ 這個波幅的日子佔比</div></div>
      <div class='card'><div class='card-title'>🗂️ 最新交易日 {esc(latest['date'])}{'（交易中）' if data['partial'] else '（已完結）'}</div>
        <div class='card-small'>開 {_n(latest['open'])}　高 {_n(latest['high'])}<br>低 {_n(latest['low'])}　收 {_n(latest['close'])}</div>
        <div class='card-desc'>波幅 {_n(latest['range'])}（{pct(latest['range_pct'])}）</div></div>
      <div class='card'><div class='card-title'>🏔️ 一年最大／最小波幅</div>
        <div class='card-small'>{_n((s['max_range'] or {}).get('range'))}（{esc((s['max_range'] or {}).get('date', '—'))}）<br>{_n((s['min_range'] or {}).get('range'))}（{esc((s['min_range'] or {}).get('date', '—'))}）</div>
        <div class='card-desc'>一年高 {_n(s['year_high'])}・低 {_n(s['year_low'])}</div></div>
    </div>"""
    table_rows = "".join(
        f"<tr><td>{esc(r['date'])}</td><td>{_n(r['open'])}</td><td>{_n(r['high'])}</td>"
        f"<td>{_n(r['low'])}</td><td>{_n(r['close'])}</td>"
        f"<td class='{pnl_class(r['change'])}'>{fmt_num(r['change'], '{:+,.0f}')}</td>"
        f"<td><b>{_n(r['range'])}</b></td><td>{pct(r['range_pct'])}</td>"
        f"<td>{_n(r.get('forecast'))}</td>"
        f"<td class='muted'>{(_n(r.get('forecast_lo')) + '–' + _n(r.get('forecast_hi'))) if r.get('forecast') else '—'}</td>"
        f"<td class='{'' if not r.get('forecast') else ('pos' if r['forecast_lo'] <= r['range'] <= r['forecast_hi'] else 'neg')}'>"
        f"{'—' if not r.get('forecast') else ('✅' if r['forecast_lo'] <= r['range'] <= r['forecast_hi'] else '❌')} "
        f"{fmt_num((r['range'] - r['forecast']) if r.get('forecast') else None, '{:+,.0f}')}</td>"
        f"<td class='muted'>{esc(r['source'].partition(':')[2] or r['source'])}</td></tr>"
        for r in reversed(rows))
    extras = (_fy_paper(data) + _fy_money(data)) if m["intraday"] else (                 # [R127] ES 沒有 5 分 K
        "<div class='section-header'>📒 紙上交易／💰 四個方向</div>"
        "<div class='fy-legend'>ES 暫時只有每日收市後的日線，紙上交易、高低位訊號與期權方向要等有 5 分 K 推送才開；"
        "研究結果見 research/us_futures/（NQ 差價合約 4.2 年：蛇蟠陣無效，波幅預測比恒指準）。</div>")
    body = nav + hero + cards + reviews + extras + f"""
    <div class='section-header'>📊 過去一年</div>
    {stats}
    <div class='section'><h2>📈 每日波幅與預測（{esc(s['first_date'] or '—')} 至 {esc(latest['date'])}，{len(rows)} 個交易日）</h2>
      {futu_range_chart(rows)}
    </div>
    <details class='fy-more'><summary>📋 每日 OHLC 與波幅明細</summary>
      <div class='scroll' style='max-height:520px; margin-top:10px;'><table>
        <tr><th>交易日</th><th>開</th><th>高</th><th>低</th><th>收</th><th>漲跌</th><th>波幅</th><th>波幅%</th><th>HAR 預測</th><th>預計範圍（八成）</th><th>實際−預測</th><th>合約</th></tr>
        {table_rows}</table></div>
    </details>
    <details class='fy-more'><summary>ℹ️ 怎樣算的</summary>
      <div class='fy-note' style='font-size:13px;'>
        <p>📅 <b>交易日</b> = {m['day_zh']}。
        即月期貨在最後交易日當天轉下月，不做價差調整。</p>
        <p>🔮 <b>波幅預測（HAR）</b>：用前 1 天、前 5 天、前 22 天的波幅預測今天，每天只用之前的數據重新計算；預計範圍（十次有八次落在這裡，即統計上的 80% 區間）來自過去的預測誤差。
        高位 ≈ 昨收 + 0.43 × 預測波幅，低位 ≈ 昨收 − 0.39 × 預測波幅。週、月 = 第一天預測 × √交易日數（已按過去數據校準）。</p>
        <p>🅰️ <b>耗盡回落</b>：已走 ≥ 80% 預期波幅，而且離高（低）位 ≥ 50% 預期波幅。
        🅱️ <b>機率法</b>：按剩餘時間估「之後再創新高（低）」的機率，低於 5% 就通知；回測中機率與實際命中一致。
        🅲 <b>時間點</b>：今日 16:30、本週第 4 個、本月第 15 個交易日收市時，離高（低）位 ≥ 40% 預期波幅。
        任一訊號第一次出現就發 Telegram（每 15 分鐘送一次）。</p>
        <p>⚠️ 統計估計，不是交易建議；只顯示，不影響下單。3 年回測見 research/hsi_futures_range/BACKTEST_REPORT.md。
        原始數據：<a href='?view=futu_range&amp;format=json&amp;symbol={esc(symbol)}'>JSON</a></p>
      </div>
    </details>"""
    return html_page(f"風揚陣・即月期貨波幅 {symbol}", body, head_extra=FY_CSS)


def handle_futu_api_get(symbol=None):
    snap = read_futu_snapshot(_futu_text(symbol, 32).upper() or None)
    if snap.get("error"):
        return _json_response({"status": "error", "message": "storage read failed"}, 503)
    if not snap:
        return _json_response({"status": "empty", "message": "尚未收到 Futu 行情"}, 200)
    age = futu_age_sec(snap)
    return _json_response({"status": "ok", "age_sec": None if age is None else int(age),
                           "stale": age is None or age > FUTU_STALE_SEC, **snap}, 200)


def futu_dashboard_html():
    snap = read_futu_snapshot()
    if snap.get("error"):
        return ("<div class='section-header'>📡 Futu 行情</div>"
                "<div class='banner' style='background:#fff3cd; color:#856404;'>⚠️ Futu 行情讀取失敗，請查看 Cloud Logging。</div>")
    if not snap:
        return ("<div class='section-header'>📡 Futu 行情</div>"
                "<div class='muted' style='margin-bottom:24px;'>尚未收到 Futu 行情。本地執行 push_to_gcp.py 後，這裡會顯示最新 K 線與期權 IV。</div>")
    bars = snap.get("bars") or []
    latest = bars[-1] if bars else {}
    age = futu_age_sec(snap)
    stale = age is None or age > FUTU_STALE_SEC
    age_text = "—" if age is None else countdown_text(age)
    age_html = (f"<span class='neg'>⚠️ {esc(age_text)} 前（超過 {FUTU_STALE_SEC // 60} 分鐘，推送可能已停止）</span>"
                if stale else f"<span class='pos'>{esc(age_text)} 前</span>")
    warn = "".join(f"<div class='banner' style='background:#fff3cd; color:#856404;'>⚠️ {esc(w)}</div>"
                   for w in snap.get("warnings") or [])
    rows = "".join(
        f"<tr><td class='mono'>{esc(o.get('code'))}</td><td>{esc(o.get('option_type') or '—')}</td>"
        f"<td>{esc(o.get('expiry') or '—')}</td><td>{fmt_num(o.get('strike'))}</td>"
        f"<td>{fmt_num(o.get('iv'), '{:.2f}%')}</td><td>{fmt_num(o.get('delta'), '{:+.3f}')}</td></tr>"
        for o in (snap.get("options") or [])[:20])
    table = (f"<div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:13px;'>"
             f"<tr><th align='left'>合約</th><th align='left'>類型</th><th align='left'>到期</th>"
             f"<th align='left'>行使價</th><th align='left'>IV</th><th align='left'>Delta</th></tr>{rows}</table></div>"
             if rows else "<div class='muted'>本次沒有期權資料。</div>")
    return f"""
    <div class='section-header'>📡 Futu 行情（{esc(snap.get('symbol'))}）｜收到：{esc(snap.get('received_utc', '—'))} UTC，{age_html}</div>
    {warn}
    <div class='grid'>
      <div class='card'><div class='card-title'>最新收盤</div><div class='card-value'>{fmt_num(latest.get('close'))}</div><div class='card-desc'>K 線時間（美東）{esc(latest.get('time_key', '—'))}</div></div>
      <div class='card'><div class='card-title'>K 線</div><div class='card-small'>{len(bars)} 根 {esc(snap.get('kline_type') or '')}</div></div>
      <div class='card'><div class='card-title'>期權</div><div class='card-small'>{len(snap.get('options') or [])} 檔</div></div>
    </div>
    <div class='section' style='margin-bottom:24px;'>{table}
      <div class='muted' style='font-size:12px; margin-top:8px;'>只存、只顯示：Futu 行情不進電閘、不進錦囊、不影響下單。原始 JSON：<a href='?view=futu&format=json'>?view=futu&amp;format=json</a>・<a href='?view=futu_range'>📏 風揚陣：恒指即月期貨波幅</a></div>
    </div>"""


# =============================================================================
# 📰 Macro news calendar  [R13e R16 R17 R32 R52 R53 R54]
# =============================================================================
class MacroNewsSession:
    def __init__(self):
        self._memory = None

    def _load(self, now):
        memory = self._memory
        if memory and memory.get("events") is not None and now - to_float(memory.get("fetched_ts"), 0) < NEWS_CACHE_TTL_SEC:
            return memory

        try:
            doc = gcs_read_json(NEWS_CACHE_FILE, None)          # shared across instances  [R52]
            doc = doc if isinstance(doc, dict) else None
        except StorageError:
            doc = None
        if doc and doc.get("events") is not None and now - to_float(doc.get("fetched_ts"), 0) < NEWS_CACHE_TTL_SEC:
            self._memory = doc
            return doc

        base = doc or memory or {}
        if now - to_float(base.get("last_fail_ts"), 0) < NEWS_FAIL_BACKOFF_SEC:   # [R53]
            self._memory = base
            return base

        try:
            response = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            events = response.json()
            if not isinstance(events, list):
                raise RuntimeError("unexpected feed format")
            fresh = {"fetched_ts": now, "events": events, "last_fail_ts": 0, "error": None}
        except Exception as exc:
            fresh = {**base, "last_fail_ts": now, "error": str(exc)[:200]}

        self._memory = fresh
        try:
            gcs_write_text(NEWS_CACHE_FILE, json.dumps(fresh, ensure_ascii=False))
        except StorageError:
            pass
        return fresh

    def status(self, now=None):
        """{'known', 'locked', 'reason', 'events', 'warning'}"""
        now = now_ts() if now is None else now
        doc = self._load(now)
        raw_events = doc.get("events")
        warning = f"日曆更新失敗：{doc['error']}" if doc.get("error") else None
        if raw_events is None or now - to_float(doc.get("fetched_ts"), 0) > NEWS_MAX_STALE_SEC:
            return {"known": False, "locked": False, "reason": warning or "日曆資料不可用",
                    "events": [], "warning": warning}

        events, lock = [], None
        for event in raw_events:
            if not isinstance(event, dict) or (event.get("country") or "") != "USD":
                continue
            impact = event.get("impact") or ""
            if impact not in ("High", "Medium"):
                continue
            try:
                event_dt = datetime.fromisoformat(str(event.get("date") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_dt.tzinfo is None:
                continue  # never guess a timezone  [R17]
            diff = event_dt.timestamp() - now
            title = event.get("title") or "未命名數據"
            in_lock = impact in NEWS_LOCK_IMPACTS and -NEWS_LOCK_AFTER_MIN * 60 <= diff <= NEWS_LOCK_BEFORE_MIN * 60
            if in_lock and lock is None:
                lock = (title, diff)
            if -3600 <= diff <= 4 * 86400:
                events.append({
                    "title": title, "impact": impact, "ts": event_dt.timestamp(),
                    "time_utc": event_dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
                    "countdown": f"{countdown_text(diff)}後" if diff > 0 else f"已發布 {countdown_text(diff)}",
                    "is_imminent": in_lock,
                })
        events.sort(key=lambda e: e["ts"])

        if lock:
            title, diff = lock
            timing = f"將於 {countdown_text(diff)}後發布" if diff > 0 else f"已發布 {countdown_text(diff)}，冷卻中"
            reason = f"【重大數據熔斷】{title} {timing}"
        else:
            reason = "目前無重大美元數據威脅"
        return {"known": True, "locked": bool(lock), "reason": reason, "events": events, "warning": warning}


macro_news_session = MacroNewsSession()


def news_blocks_entries(news):
    return bool(news.get("locked")) or (not news.get("known") and NEWS_FAIL_CLOSED)


def ai_prompt_diagnostics(rules_text, few_shot, prompt=""):
    """量化「AI 手上到底有多少材料」——投資人日誌與雲端日誌共用這組數字。

    build_prompt() 要 AI「參考規則庫與歷史虧損教訓，判斷是否與過去虧損情境相似」。
    若這兩樣都是空的，那句指令就是空轉，AI 只能靠通用直覺猜。"""
    body = (rules_text or "").split("\n", 1)[-1].strip()
    return {
        "ai_model": AI_MODEL,
        "ai_mode": "shadow" if AI_SHADOW_MODE else "enforce",
        "prompt_chars": len(prompt),
        "rules_chars": 0 if body in ("", "目前無額外規則。") else len(body),
        "few_shot_lessons": sum(1 for line in (few_shot or "").splitlines() if line.startswith("- ")),
    }


# =============================================================================
# 🤖 Optional LLM reviewer — one consistent fail policy  [R2 R5 R13f R13g R14 R66]
# =============================================================================
class AIReviewSession:
    def __init__(self):
        self.client = None
        if not AI_REVIEW_ENABLED:
            print("ℹ️ [Vertex AI] AI_REVIEW_ENABLED=0，AI 覆核停用。", flush=True)
            return
        try:
            self.client = genai.Client(vertexai=True, location=AI_LOCATION)
            print("✅ [Vertex AI] Gemini 客戶端初始化成功。", flush=True)
        except Exception as exc:
            print(f"⚠️ [Vertex AI] 初始化失敗：{exc}（訊號依 AI_FAIL_OPEN={AI_FAIL_OPEN} 處理）", flush=True)

    @staticmethod
    def _fallback(why):
        return AI_FAIL_OPEN, f"{why} → 依 AI_FAIL_OPEN 設定{'放行' if AI_FAIL_OPEN else '拒絕'}"

    @staticmethod
    def _config():
        kwargs = {"temperature": 0.0, "max_output_tokens": 256}
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=AI_THINKING_BUDGET)
        except Exception:
            pass
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def build_prompt(meta, rules_text, few_shot):
        rsi_note = "" if meta.get("rsi_m1") is not None else "（RSI 目前不可用，請勿當作 50 解讀）"
        return (
            "Role: XAUUSD 風險覆核員。\n"
            "此訊號已通過程式化硬性規則（趨勢方向、M15 布林帶結構、RSI 極值、風險倉位上限、ATR 加碼距離）。"
            "請勿重新驗算這些數字條件。\n"
            "你的任務：參考規則庫與歷史虧損教訓，判斷此訊號是否與過去虧損情境高度相似，或有明顯不利的風險背景。\n\n"
            f"訊號：{format_signal_meta(meta)}{rsi_note}\n\n"
            f"{rules_text}\n\n"
            f"{few_shot or '【歷史虧損教訓】目前無。'}\n\n"
            "OUTPUT FORMAT (CRITICAL): 只回覆一行，格式為「APPROVE | 理由」或「REJECT | 理由」。"
            "不要使用 JSON、Markdown 或多行。"
        )

    def review(self, meta):
        if not AI_REVIEW_ENABLED:
            return True, "AI 覆核已停用 (AI_REVIEW_ENABLED=0)"
        if self.client is None:
            return self._fallback("Vertex AI 未初始化")
        rules_text = sft_pipeline_session.get_trading_rules()
        few_shot = sft_pipeline_session.get_dynamic_few_shot()
        prompt = self.build_prompt(meta, rules_text, few_shot)
        diag = ai_prompt_diagnostics(rules_text, few_shot, prompt)

        # 這幾個數字決定了 AI 判斷的品質上限：prompt 叫它「比對過去虧損情境」，
        # 但若動態 few-shot 是空的，它手上根本沒有可比對的東西。
        log_event(f"🤖 [AI 送出覆核] {AI_MODEL}｜{'影子' if AI_SHADOW_MODE else '強制'}模式｜"
                  f"prompt {diag['prompt_chars']} 字元｜規則庫 {diag['rules_chars']} 字元｜"
                  f"虧損教訓 {diag['few_shot_lessons']} 條", component="ai", **diag)
        if diag["few_shot_lessons"] == 0:
            log_event("⚠️ [AI 知識庫] 動態 few-shot 是空的：SFT 資料集沒有可用的歷史虧損，"
                      "AI 無法執行「與過去虧損比對」，只能靠通用直覺判斷。",
                      severity="WARNING", component="ai", **diag)
        if diag["rules_chars"] == 0:
            log_event("⚠️ [AI 知識庫] 規則庫是空的：ai_training/trading_rules.txt 沒有內容。",
                      severity="WARNING", component="ai", **diag)

        started = time.time()
        try:
            response = self.client.models.generate_content(model=AI_MODEL, contents=prompt, config=self._config())
            text = (response.text or "").strip()
        except Exception as exc:
            log_event(f"💥 [AI 呼叫失敗] {str(exc)[:200]}（{int((time.time() - started) * 1000)} ms）",
                      severity="ERROR", component="ai",
                      latency_ms=int((time.time() - started) * 1000), **diag)
            return self._fallback(f"AI API 錯誤：{str(exc)[:150]}")

        elapsed_ms = int((time.time() - started) * 1000)
        log_event(f"🔍 [AI 原始回應] {text[:300] or '（空回應）'}", component="ai",
                  latency_ms=elapsed_ms, raw_response=text[:500], **diag)
        if not text:
            return self._fallback("AI 空回應")

        first_line = text.splitlines()[0]
        decision, separator, reason = first_line.partition("|")
        decision = decision.strip().strip("*`'\" ").upper()
        reason = reason.strip() or "（無理由）"
        if not separator:
            return self._fallback(f"AI 回應格式錯誤：{first_line[:80]}")
        if decision in ("APPROVE", "REJECT"):
            # 投資人日誌看得到的一行：AI 說了什麼、根據多少材料、花了多久。
            log_decision(f"{'👍' if decision == 'APPROVE' else '🚫'} [AI 覆核] {decision}"
                         f"｜{AI_MODEL}｜教訓 {diag['few_shot_lessons']} 條・規則 {diag['rules_chars']} 字"
                         f"・{elapsed_ms} ms｜理由：{reason[:70]}", key="ai_review")
            return decision == "APPROVE", reason
        return self._fallback(f"AI 回應無法辨識：{first_line[:80]}")


ai_review_session = AIReviewSession()


# =============================================================================
# 🧾 送單參數（環境變數為預設值，GCS 覆寫檔為現行值）
# =============================================================================
ORDER_PARAMS_FILE = "order_params.json"
LAST_ORDER_FILE = "logs/last_order_sent.json"

# key, 中文標籤, 型別, 說明, 限制
ORDER_PARAM_DEFS = [
    ("username", "webhooktrade 帳號", "text", "封包的 username 欄位。", {"max_len": 64}),
    ("api_key", "webhooktrade API Key", "secret", "封包的 api_key 欄位；讀取時一律遮蔽，留空代表不修改。", {"max_len": 128}),
    ("broker", "券商橋接", "text", "封包的 broker 欄位（例如 metatrader）。", {"max_len": 32}),
    ("account_type", "帳戶類型", "choice", "real＝實盤下單，demo＝模擬帳戶。", {"choices": ["real", "demo"]}),
    ("account", "券商帳戶編號", "text", "封包的 account 欄位（webhooktrade 範本為 \"1\"）。", {"max_len": 16}),
    ("symbol", "商品代號", "text", "送單用的 symbol；EA 無持倉時回報 NONE，所以這裡固定由本頁決定。", {"max_len": 20}),
    ("size", "每張單手數", "number", "封包的 size；也是加單時每次增加的手數。", {"min": 0.01, "max": HARD_MAX_LOTS, "step": 0.01}),
    ("strategy", "策略標籤", "text", "封包的 strategy 欄位。", {"max_len": 32}),
    ("comment", "訂單註解", "text", "封包的 comment 欄位，會出現在 MT5 訂單註解。", {"max_len": 64}),
    ("sl_atr_mult", "止損 = ATR(M15) ×", "number", "決定 sl_distance_price：ATR(M15) 乘上這個倍數。", {"min": 0.1, "max": 10.0, "step": 0.1}),
    ("min_sl_distance", "最小止損距離（美元）", "number", "sl_distance_price 的下限，避免 ATR 過小時止損太貼。", {"min": 0.5, "max": 200.0, "step": 0.5}),
    ("target_rrr", "止盈 = 止損 ×", "number", "決定 tp_distance_price：止損距離乘上這個倍數。", {"min": 0.2, "max": 20.0, "step": 0.1}),
    ("ts_activation_price", "移動止損啟動距離（0＝停用）", "number", "0 代表整個欄位不送出（停用）。封包的 ts_activation_price，語義依 webhooktrade 定義。", {"min": 0.0, "max": 10000.0, "step": 0.1}),
    ("ts_distance_price", "移動止損距離（0＝停用）", "number", "0 代表整個欄位不送出（停用）。封包的 ts_distance_price。", {"min": 0.0, "max": 10000.0, "step": 0.1}),
    ("breakeven_distance_price", "保本啟動距離（0＝停用）", "number", "0 代表整個欄位不送出（停用）。封包的 breakeven_distance_price。", {"min": 0.0, "max": 10000.0, "step": 0.1}),
    ("breakeven_profit", "保本鎖利", "number", "只有在「保本啟動距離」大於 0 時才會送出。封包的 breakeven_profit。", {"min": 0.0, "max": 100000.0, "step": 1.0}),
    ("distance_unit", "距離單位（欄位組）", "choice",
     "price＝送 sl_distance_price 等欄位，值是美元（13.00）；"
     "points＝送 sl_distance 等欄位，值是點數（1300，XAUUSD 1 美元 = 100 點）。兩組只能擇一。",
     {"choices": ["price", "points"]}),
]
ORDER_PARAM_KEYS = [d[0] for d in ORDER_PARAM_DEFS]
ORDER_PARAM_KINDS = {d[0]: d[2] for d in ORDER_PARAM_DEFS}
ORDER_PARAM_LIMITS = {d[0]: d[4] for d in ORDER_PARAM_DEFS}
# 這幾個欄位是每次訊號現算的，不能直接輸入
def computed_fields(params):
    """每次訊號現算、不能直接輸入的欄位（名稱隨 distance_unit 變動）。"""
    field = distance_fields(params)
    return {
        "action": "由電閘趨勢方向決定（BUY／SELL）。",
        field["sl"]: "max(最小止損距離, ATR(M15) × 止損倍數)。",
        field["tp"]: "止損距離 × 止盈倍數。",
    }


def mask_secret(value):
    text = str(value or "")
    if not text:
        return "（未設定）"
    return (text[:4] + "…" + text[-3:]) if len(text) > 10 else "（已設定）"


def default_order_params():
    return {
        "username": ORDER_TEMPLATE["username"],
        "api_key": ORDER_TEMPLATE["api_key"],
        "broker": ORDER_TEMPLATE["broker"],
        "account_type": ORDER_TEMPLATE["account_type"],
        "account": ORDER_ACCOUNT,
        "symbol": ORDER_SYMBOL,
        "size": round(ORDER_SIZE, 2),
        "strategy": ORDER_TEMPLATE["strategy"],
        "comment": ORDER_TEMPLATE["comment"],
        "sl_atr_mult": SL_ATR_MULT,
        "min_sl_distance": MIN_SL_DISTANCE,
        "target_rrr": TARGET_RRR,
        "ts_activation_price": to_float(TS_ACTIVATION_PRICE, 0.0),
        "ts_distance_price": to_float(TS_DISTANCE_PRICE, 0.0),
        "breakeven_distance_price": to_float(BREAKEVEN_DISTANCE_PRICE, 0.0),
        "breakeven_profit": to_float(BREAKEVEN_PROFIT, 0.0),
        "distance_unit": DISTANCE_UNIT,
    }


def validate_order_params(raw):
    """回傳 (clean, errors)。無效欄位會退回預設值，並在 errors 中說明。"""
    defaults = default_order_params()
    clean, errors = {}, {}
    for key in ORDER_PARAM_KEYS:
        kind, limits, value = ORDER_PARAM_KINDS[key], ORDER_PARAM_LIMITS[key], raw.get(key)
        if value is None:
            clean[key] = defaults[key]
            continue
        if kind == "number":
            number = to_float(value)
            if number is None:
                errors[key] = "必須是數字"
            elif number < limits["min"] or number > limits["max"]:
                errors[key] = f"必須介於 {limits['min']} 與 {limits['max']} 之間"
            else:
                clean[key] = round(number, 2)
                continue
        elif kind == "choice":
            if value not in limits["choices"]:
                errors[key] = "必須是 " + " 或 ".join(limits["choices"])
            else:
                clean[key] = value
                continue
        else:                                              # text / secret
            text = str(value).strip()
            if any(ord(ch) < 32 for ch in text):
                errors[key] = "不可含控制字元"
            elif not text:
                errors[key] = "不可留空"
            elif len(text) > limits["max_len"]:
                errors[key] = f"最長 {limits['max_len']} 個字元"
            else:
                clean[key] = text
                continue
        clean[key] = defaults[key]
    return clean, errors


def read_order_params():
    """回傳 (params, meta)。覆寫檔讀不到或欄位無效時，該欄位退回環境變數預設。"""
    defaults = default_order_params()
    try:
        doc = gcs_read_json(ORDER_PARAMS_FILE, None)
    except StorageError as exc:
        print(f"⚠️ [送單參數讀取失敗 → 使用環境變數預設] {exc}", flush=True)
        return defaults, {"source": "default", "updated_utc": None, "error": str(exc)[:200]}
    if not isinstance(doc, dict) or not isinstance(doc.get("params"), dict) or not doc["params"]:
        # 沒有覆寫檔，或覆寫檔已被清空（還原預設）
        updated = doc.get("updated_utc") if isinstance(doc, dict) else None
        return defaults, {"source": "default", "updated_utc": updated, "error": None}
    clean, errors = validate_order_params({**defaults, **doc["params"]})
    if errors:
        print(f"⚠️ [送單參數] 覆寫檔欄位無效，改用預設：{errors}", flush=True)
    return clean, {"source": "override", "updated_utc": doc.get("updated_utc"),
                   "error": None, "invalid_fields": errors or None}


def write_order_params(params):
    doc = {"params": params, "updated_utc": fmt_utc()}
    gcs_write_text(ORDER_PARAMS_FILE, json.dumps(doc, ensure_ascii=False))
    return doc


def clear_order_params():
    gcs_write_text(ORDER_PARAMS_FILE, json.dumps({"params": {}, "updated_utc": fmt_utc()}, ensure_ascii=False))


def current_target_rrr():
    try:
        return read_order_params()[0]["target_rrr"]
    except Exception:
        return TARGET_RRR


def save_last_order(order, result):
    """把真的送出去的封包留一份（API Key 遮蔽），送單參數頁會顯示。"""
    doc = {"sent_utc": fmt_utc(), "order": {**order, "api_key": mask_secret(order.get("api_key"))},
           "result": result}
    try:
        gcs_write_text(LAST_ORDER_FILE, json.dumps(doc, ensure_ascii=False, indent=2))
    except StorageError as exc:
        print(f"⚠️ [最後送出封包紀錄失敗] {exc}", flush=True)


def read_last_order():
    try:
        doc = gcs_read_json(LAST_ORDER_FILE, None)
        return doc if isinstance(doc, dict) else None
    except StorageError:
        return None


# =============================================================================
# 🎯 Deterministic entry / pyramiding engine  [R3 R4 R5 R11 R12 R13 R25]
# =============================================================================
class PureGCPPyramidingSession:
    @staticmethod
    def calculate_max_lots(equity, currency, price, sl_distance, ignore_risk=False):
        """Max total exposure so that the whole pyramid stopped out loses about
        RISK_PCT of equity, also limited by margin and HARD_MAX_LOTS.  [R11]"""
        rate = FX_TO_USD.get(str(currency).upper()) or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
        if not rate or equity <= 0 or price <= 0 or sl_distance <= 0:
            return 0.0, f"無法換算 {currency} → USD（請設定 ACCOUNT_TO_USD_RATE）"
        equity_usd = equity * rate
        risk_lots = equity_usd * RISK_PCT / (sl_distance * CONTRACT_SIZE)
        margin_lots = equity_usd * MAX_MARGIN_PCT / (price * CONTRACT_SIZE / BROKER_LEVERAGE)
        lots = min(margin_lots, HARD_MAX_LOTS) if ignore_risk else min(risk_lots, margin_lots, HARD_MAX_LOTS)
        note = f"風險 {risk_lots:.3f}{'（已略過）' if ignore_risk else ''} / 保證金 {margin_lots:.3f} / 硬上限 {HARD_MAX_LOTS:.2f}"
        return math.floor(lots * 100 + 1e-9) / 100.0, note

    @staticmethod
    def _first_entry_structure(side, close, levels, m15_ohlc):
        r1, mid, s1 = levels["M15_R1"], levels["M15_MID"], levels["M15_S1"]
        if FIRST_ENTRY_MODE == "MID":
            if side == "BUY" and close <= mid:
                return False, f"價格 {close:.2f} 未站上 M15 中軌 {mid:.2f}"
            if side == "SELL" and close >= mid:
                return False, f"價格 {close:.2f} 未跌破 M15 中軌 {mid:.2f}"
            return True, ""
        # BREAKOUT: the rule that used to live only in the AI prompt, now exact.  [R5]
        if side == "BUY" and close <= r1:
            return False, f"價格 {close:.2f} 未突破 M15 上軌 {r1:.2f}"
        if side == "SELL" and close >= s1:
            return False, f"價格 {close:.2f} 未跌破 M15 下軌 {s1:.2f}"
        position = m15_close_position(m15_ohlc)
        if position is None:
            return False, "M15 K 線高低點資料不足"
        if side == "BUY" and position < M15_CLOSE_POSITION_MIN:
            return False, f"M15 收盤位置 {position:.2f} 未靠近高點（需 ≥ {M15_CLOSE_POSITION_MIN:.2f}）"
        if side == "SELL" and position > 1 - M15_CLOSE_POSITION_MIN:
            return False, f"M15 收盤位置 {position:.2f} 未靠近低點（需 ≤ {1 - M15_CLOSE_POSITION_MIN:.2f}）"
        return True, ""

    def evaluate_and_trigger(self, payload, gate_state, m15_levels, bar, rsi, now=None, bypass=frozenset(),
                             params=None):
        """Returns a candidate dict or None. Nothing here sends orders or moves the
        pyramid base price (except re-anchoring when no base exists)."""
        now = now_ts() if now is None else now
        params = params or read_order_params()[0]
        order_size = params["size"]
        direction = gate_state.get("dir")
        if gate_status(gate_state, now) != "OPEN" or direction not in ("UP", "DOWN"):
            return None
        side = "BUY" if direction == "UP" else "SELL"
        symbol = params["symbol"]   # EA sends symbol "NONE" when flat, so never trust payload symbol for orders

        buy_lots, sell_lots = to_float(payload.get("buy_lots")), to_float(payload.get("sell_lots"))
        equity = risk_equity(payload)                                                  # [R88] 扣掉信用
        if buy_lots is None or sell_lots is None or equity is None or equity <= 0:      # [R13c]
            log_decision("⏸️ [資料不足] 封包缺少 buy_lots / sell_lots / equity，本根不交易。", key="data")
            return None
        buy_lots, sell_lots = round(buy_lots, 2), round(sell_lots, 2)                   # [R12]
        reported_net = to_float(payload.get("net_lots"))
        if reported_net is not None and abs(round(reported_net, 2) - round(buy_lots - sell_lots, 2)) >= 0.01:
            print(f"⚠️ [淨敞口不一致] EA net_lots={reported_net} 但 buy-sell={buy_lots - sell_lots:.2f}（以 buy/sell 為準）[R12b]", flush=True)

        if m15_levels.get("status") != "ready":                                         # [R13d]
            log_decision(f"⏸️ [結構未就緒] M15 布林帶狀態：{m15_levels.get('status')}，暫停交易。", key="data")
            return None
        m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}
        atr = to_float(m15_ohlc.get("atr_m15"))
        if atr is None or atr <= 0:
            log_decision("⏸️ [資料不足] 缺少有效的 ATR(M15)，本根不交易。", key="data")
            return None

        close, open_price = bar["close"], bar["open"]
        sl_distance = max(params["min_sl_distance"], round(atr * params["sl_atr_mult"], 2))
        currency = str(payload.get("currency") or ACCOUNT_CURRENCY_DEFAULT)
        max_lots, sizing_note = self.calculate_max_lots(equity, currency, close, sl_distance,
                                                        ignore_risk="risk_cap" in bypass)

        try:
            pstate = read_pyramid_state()
        except StorageError as exc:                                                      # [R13b]
            log_decision(f"⏸️ [狀態讀取失敗] 加單狀態不可用，本根不交易：{exc}", key="data")
            return None

        gross = round(buy_lots + sell_lots, 2)
        since_order = now - to_float(pstate.get("last_order_ts"), 0.0)
        if since_order < ORDER_SETTLE_SEC and abs(gross - to_float(pstate.get("exposure_at_order"), -1.0)) < 0.005:
            log_decision(f"⏳ [等待成交回報] 上一張訂單送出 {int(since_order)} 秒，持倉尚未更新，暫停決策。", key="settle")
            return None                                                                  # [R12c]
        if buy_lots > 0 and sell_lots > 0:
            log_decision(f"⏸️ [對沖持倉] Buy {buy_lots:.2f} / Sell {sell_lots:.2f}，系統不處理對沖倉，暫停交易。", key="risk")
            return None

        if "rsi" not in bypass and rsi is not None and ((side == "BUY" and rsi >= RSI_BUY_MAX) or (side == "SELL" and rsi <= RSI_SELL_MIN)):
            log_decision(f"⏳ [RSI 極值] RSI14(M1)={rsi:.2f}，拒絕追{'多' if side == 'BUY' else '空'}。", key="filter")
            return None

        candle = "BULL" if close > open_price else ("BEAR" if close < open_price else "DOJI")   # [R39]
        candle_ok = candle == ("BULL" if side == "BUY" else "BEAR")
        word = DIR_WORD[direction]
        base = {"signal": side, "ticker": symbol, "price": close, "direction": direction,
                "sl_distance": sl_distance, "atr_m15": atr, "max_lots": max_lots, "exposure": gross}

        # ---- First entry: only in the gate's trend direction  [R4] ----
        if gross == 0:
            since_close = now - to_float(pstate.get("last_close_ts"), 0.0)
            if "cooldown" not in bypass and since_close < REENTRY_COOLDOWN_SEC:                                       # [R25b]
                log_decision(f"⏳ [平倉冷卻] 距上次平倉 {int(since_close)} 秒（需 {REENTRY_COOLDOWN_SEC} 秒）。", key="wait")
                return None
            if not candle_ok and "candle" not in bypass:
                log_decision(f"⏳ [首單過濾] {word}趨勢，但 M1 {CANDLE_WORD[candle]}，等待同向 K 線。", key="filter")
                return None
            ok, why = (True, "") if "structure" in bypass else self._first_entry_structure(side, close, m15_levels, m15_ohlc)
            if not ok:
                log_decision(f"⏳ [首單過濾] {word}趨勢：{why}。", key="filter")
                return None
            if max_lots + 1e-9 < order_size:
                log_decision(f"🛑 [資金控管] 風險上限 {max_lots:.2f} 手 < 單筆 {order_size:.2f} 手（{sizing_note}），不開首單。", key="risk")
                return None
            log_decision(f"🎯 [首單候選] {side} @ {close:.2f}（{word}趨勢，上限 {max_lots:.2f} 手），送交新聞與 AI 覆核。{bypass_note(bypass)}", key="candidate")
            return {**base, "kind": "FIRST"}

        # ---- Pyramid add ----
        exposure_dir = "UP" if buy_lots > 0 else "DOWN"
        if exposure_dir != direction:
            log_decision(f"🛑 [方向衝突] 持倉為{DIR_WORD[exposure_dir]}，但電閘趨勢為{word}，不加碼。", key="risk")
            return None
        if gross + order_size > max_lots + 1e-9:
            log_decision(f"🛑 [資金控管] 持倉 {gross:.2f} + {order_size:.2f} 將超過風險上限 {max_lots:.2f} 手（{sizing_note}），停止加單。", key="risk")
            return None                                                                  # [R11e] never reduces
        if not candle_ok and "candle" not in bypass:
            log_decision(f"⏳ [動能過濾] 持{word}倉，但 M1 {CANDLE_WORD[candle]}，本根不加單。", key="filter")
            return None
        mid = m15_levels["M15_MID"]
        if "structure" not in bypass and ((side == "BUY" and close < mid) or (side == "SELL" and close > mid)):
            log_decision(f"🛑 [結構破壞] 價格 {close:.2f} 已{'跌破' if side == 'BUY' else '站上'} M15 中軌 {mid:.2f}，停止加{'多' if side == 'BUY' else '空'}。", key="structure")
            return None

        anchor = to_float(pstate.get("last_entry_price"))
        if not anchor or pstate.get("last_entry_dir") != direction:                      # [R13b]
            try:
                update_pyramid_state(last_entry_price=close, last_entry_dir=direction)
            except StorageError as exc:
                print(f"⚠️ [加單基準寫入失敗] {exc}", flush=True)
                return None
            log_decision(f"📌 [重設加單基準] 找不到同向的上次進場價，以 {close:.2f} 為新基準，本根不加單。", key="anchor")
            return None

        spacing = round(atr * ADD_SPACING_ATR, 2)
        target = anchor + spacing if side == "BUY" else anchor - spacing
        if "add_spacing" not in bypass and ((side == "BUY" and close < target) or (side == "SELL" and close > target)):
            log_decision(f"⏳ [冷卻等待] 前次:{anchor:.2f} ➔ 需{'突破' if side == 'BUY' else '跌破'}:{target:.2f}，目前:{close:.2f}。", key="wait")
            return None
        log_decision(f"🎯 [加單候選] {side} @ {close:.2f} 越過加碼距離 (目標:{target:.2f})，持倉 {gross:.2f}/{max_lots:.2f} 手，送交覆核。{bypass_note(bypass)}", key="candidate")
        return {**base, "kind": "ADD"}


pure_gcp_session = PureGCPPyramidingSession()


# =============================================================================
# 🚀 Execution: news → AI → broker → commit state  [R1 R1b R3 R24f R64 R65]
# =============================================================================
def format_distance(value, params):
    """price 模式送美元（13.00）；points 模式送點數（1300）。欄位名稱也會跟著換。"""
    if params.get("distance_unit") == "points":
        return f"{round(value * POINTS_PER_UNIT):d}"
    return f"{value:.2f}"


def build_order(candidate, params=None):
    """送給 webhooktrade 的封包。距離欄位依 distance_unit 選用 *_price（美元）或無後綴（點數）。"""
    params = params or read_order_params()[0]
    sl = candidate["sl_distance"]
    field = distance_fields(params)

    order = {
        "username": params["username"],
        "api_key": params["api_key"],
        "broker": params["broker"],
        "account_type": params["account_type"],
        "account": params["account"],
        "symbol": candidate["ticker"],
        "action": candidate["signal"],
        "size": f"{params['size']:.2f}",
        "strategy": params["strategy"],
        "comment": params["comment"],
    }
    order[field["sl"]] = format_distance(sl, params)
    # [R78] 錦囊的出場是 EA 的定時，不是 TP。candidate 明確帶 tp_distance=None 時
    #       整個 TP 欄位不送出 —— 送 0 有被解讀成「距離 0」的風險。
    tp = candidate.get("tp_distance", round(sl * params["target_rrr"], 2)) \
        if "tp_distance" in candidate else round(sl * params["target_rrr"], 2)
    if tp is not None:
        order[field["tp"]] = format_distance(tp, params)

    # 移動止損與保本：設成 0 代表停用，此時整個欄位不送出。
    # 送 "0.00" 有被解讀成「距離 0」的風險（止損貼著現價），不送最保險。
    if params["ts_activation_price"] > 0 and params["ts_distance_price"] > 0:
        order[field["ts_activation"]] = format_distance(params["ts_activation_price"], params)
        order[field["ts_distance"]] = format_distance(params["ts_distance_price"], params)
    if params["breakeven_distance_price"] > 0:
        order[field["breakeven"]] = format_distance(params["breakeven_distance_price"], params)
        order["breakeven_profit"] = f"{params['breakeven_profit']:g}"
    return order


def execute_signal(candidate, payload, m15_levels, rsi, news, bypass=frozenset(), params=None):
    signal, price = candidate["signal"], candidate["price"]
    label = "首單" if candidate["kind"] == "FIRST" else "加單"

    # [R71] 只做多。全期 1,464 筆裡 671 筆空單，每筆 −HK$0.84、t = −0.25：
    #       八年半期望值是零，唯一作用是付點差。README §23。
    if LONG_ONLY and str(signal).upper() not in ("BUY", "LONG"):
        log_decision(f"🚫 [只做多] {label} {signal} @ {price:.2f} 取消："
                     f"空單全期 671 筆 t=−0.25，已停用（LONG_ONLY=0 可恢復）", key="long_only")
        return {"status": "long_only_rejected",
                "reason": "LONG_ONLY=1：空單經 8.4 年量度期望值為零"}

    m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}
    meta = build_signal_meta(candidate, m15_levels, m15_ohlc, rsi)

    if "news" not in bypass and news_blocks_entries(news):
        reason = news["reason"] if news.get("known") else f"日曆狀態未知（{news.get('reason')}），NEWS_FAIL_CLOSED=1"
        log_decision(f"📰 [新聞攔截] {label} {signal} @ {price:.2f} 取消：{reason}", key="news_reject")
        return {"status": "news_rejected", "reason": reason}

    # 判斷與執行分家：影子模式要「照跑、照記、但不否決」。被 AI 反對的訊號若真的
    # 被擋掉，那筆交易就不存在，也就永遠沒有實際損益可以回頭驗證它判斷得對不對。
    if "ai" in bypass:
        ai_verdict = {"approved": True, "reason": "AI 覆核關卡已略過", "mode": "bypass", "enforced": False}
    else:
        approved, ai_reason = ai_review_session.review(meta)
        ai_verdict = {"approved": bool(approved), "reason": ai_reason,
                      "mode": "shadow" if AI_SHADOW_MODE else "enforce",
                      "enforced": not AI_SHADOW_MODE}

    # ⚠️ review() 在 API 出錯時會依 AI_FAIL_OPEN 回傳拒絕（預設 False）。那是「錯誤」
    #    不是「判斷」，影子模式下必須照樣放行，否則會變成「影子模式反而擋單」。
    log_event(f"⚖️ [AI 判決] {label} {signal} @ {price:.2f} → "
              f"{'APPROVE' if ai_verdict['approved'] else 'REJECT'}"
              f"（{ai_verdict['mode']}，{'擋單' if not ai_verdict['approved'] and ai_verdict['enforced'] else '放行'}）"
              f"｜{ai_verdict['reason'][:120]}",
              component="ai", direction="verdict", ai_approved=ai_verdict["approved"],
              ai_mode=ai_verdict["mode"], ai_enforced=ai_verdict["enforced"],
              ai_reason=ai_verdict["reason"][:200], kind=candidate["kind"], signal=signal, price=price)

    if not ai_verdict["approved"]:
        if ai_verdict["enforced"]:
            log_decision(f"❌ [AI 攔截] {label} {signal} @ {price:.2f} 理由：{ai_verdict['reason']}", key="ai_reject")
            return {"status": "ai_rejected", "reason": ai_verdict["reason"]}
        log_decision(f"👁️ [AI 影子攔截] {label} {signal} @ {price:.2f} 仍照常送出，僅記錄供事後對帳。"
                     f"理由：{ai_verdict['reason']}", key="ai_shadow")
        log_event(f"👁️ [影子模式] 這筆若在強制執行模式下會被擋掉，現在照常送出以取得實際損益。",
                  severity="WARNING", component="ai", direction="shadow_pass",
                  signal=signal, price=price, ai_reason=ai_verdict["reason"][:200])

    order = build_order(candidate, params)
    summary = (f"{label} {signal} {candidate['ticker']} @ {price:.2f} | SL:{order['sl_distance_price']} "
               f"TP:{order['tp_distance_price']} | 持倉 {candidate['exposure']:.2f}/{candidate['max_lots']:.2f} 手")

    print(f"🚀 [實盤下單 JSON] {json.dumps(order, ensure_ascii=False)}", flush=True)
    sent_at = now_ts()
    commit = {"last_entry_price": price, "last_entry_dir": candidate["direction"],
              "last_order_ts": sent_at, "exposure_at_order": candidate["exposure"]}
    try:
        response = requests.post(BROKER_API_URL, json=order, timeout=BROKER_TIMEOUT_SEC)
    except requests.Timeout:
        # The order may have been placed: block decisions until exposure changes.  [R1b]
        try:
            update_pyramid_state(**commit, last_order_status="UNKNOWN")
        except StorageError as exc:
            print(f"⚠️ [狀態寫入失敗] {exc}", flush=True)
        save_last_order(order, {"status": "broker_timeout"})
        log_decision(f"⚠️ [下單逾時] {summary}：訂單可能已成交，暫停 {ORDER_SETTLE_SEC} 秒等待持倉回報。", key="broker_error")
        return {"status": "broker_timeout", "executed_signal": signal}
    except requests.RequestException as exc:
        save_last_order(order, {"status": "broker_error", "reason": str(exc)[:150]})
        log_decision(f"❌ [下單失敗] {summary}：{str(exc)[:150]}", key="broker_error")
        return {"status": "broker_error", "reason": str(exc)[:150]}

    body = (response.text or "")[:300]
    print(f"📨 [券商回應] HTTP {response.status_code}: {body}", flush=True)
    save_last_order(order, {"status": "sent" if response.ok else "broker_error",
                            "http_status": response.status_code, "body": body[:200]})
    if not response.ok:
        log_decision(f"❌ [下單失敗] {summary}：HTTP {response.status_code} {body[:120]}", key="broker_error")
        return {"status": "broker_error", "http_status": response.status_code}

    # Only now: move the pyramid base and queue the SFT context.  [R3 R24f]
    try:
        update_pyramid_state(**commit, last_order_status="SENT")
    except StorageError as exc:
        print(f"🚨 [嚴重] 訂單已送出但加單狀態寫入失敗：{exc}", flush=True)
    sft_pipeline_session.save_pending_signal(meta, ai_verdict)
    used = bump_trades_today()                                                       # [R73] 訓練節奏
    log_decision(f"✅ [已送出] {summary}"
                 + (f"｜今日第 {used} 筆"
                    + (f"／{TRAINING_MAX_PER_DAY}" if TRAINING_MAX_PER_DAY > 0 else "")
                    if used else ""), key="entry_sent")
    return {"status": "success", "executed_signal": signal, "trades_today": used}


# =============================================================================
# 📡 POST handlers
# =============================================================================
def parse_payload(req):
    try:
        raw = req.get_data().decode("utf-8")
    except UnicodeDecodeError:
        return None
    clean = raw.replace("\x00", "").strip()          # MT5 char arrays often end with \0  [R60]
    if not clean:
        return {}
    try:
        data = json.loads(clean)
    except ValueError:
        data = req.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def locked_response(state):
    lock = state.get("hard_lock") if hard_lock_active(state) else None
    risk = state.get("risk") if isinstance(state.get("risk"), dict) else {}
    return jsonify({
        "status": "forbidden", "message": "Gate is LOCK", "current_gate": "LOCK",
        "regime": state.get("regime"), "dir": state.get("dir"), "news_lock": state.get("news_lock"),
        "hard_lock": lock.get("reason") if lock else None,
        # [R76] 讓 EA 的 log 看得出是哪一關擋的，不用再開網頁猜。
        "failed_checks": [c.get("key") for c in (risk.get("checks") or []) if not c.get("ok")],
        "reason": state.get("last_reason"),
    }), LOCKED_HTTP_STATUS


def handle_trade_result(payload):
    entry = str(payload.get("entry") or payload.get("deal_entry") or "").strip().upper()
    if entry in ("IN", "DEAL_ENTRY_IN"):                                                 # [R24e]
        return jsonify({"status": "ignored", "message": "opening deal"}), 200
    profit = to_float(payload.get("profit"))
    if profit is None:
        return jsonify({"status": "error", "message": "missing profit"}), 400

    now = now_ts()
    volume = to_float(payload.get("volume"), 0.0)
    deal_type = str(payload.get("deal_type") or "")
    broker_time = str(payload.get("time") or "").strip()
    symbol = payload.get("symbol") or ORDER_TEMPLATE["symbol"]
    ticket = str(payload.get("ticket") or "").strip()
    if not ticket:                                                                       # [R28]
        digest = hashlib.sha1(f"{broker_time}|{profit}|{volume}|{deal_type}|{symbol}".encode()).hexdigest()
        ticket = f"noticket-{digest[:16]}"

    trade = {
        "ticket": ticket, "profit": profit, "volume": volume, "deal_type": deal_type,
        "symbol": normalize_symbol(symbol), "position_id": str(payload.get("position_id") or ""),
        "time": broker_time or fmt_utc(now), "time_source": "broker" if broker_time else "server_utc",   # [R42]
        "received_utc": fmt_utc(now),
    }
    try:
        stats, is_new = risk_manager_session.record_trade(trade)                         # dedupe FIRST  [R7]
    except StorageError as exc:
        print(f"⚠️ [交易歷史寫入失敗] {exc}", flush=True)
        return jsonify({"status": "error", "message": "trade history unavailable"}), 500

    if is_new:
        entry_ts = to_float(payload.get("entry_time"))   # optional: MT5 position open time (server epoch)
        if entry_ts is not None:
            entry_ts -= BROKER_UTC_OFFSET_HOURS * 3600
        sft_pipeline_session.pair_trade_result(symbol, profit, ticket, entry_ts)
        try:
            update_pyramid_state(last_close_ts=now)
        except StorageError as exc:
            print(f"⚠️ [平倉時間寫入失敗] {exc}", flush=True)

    return jsonify({"status": "success" if is_new else "duplicate",
                    "win_rate": stats["win_rate"], "recommended_rrr": stats["recommended_rrr"]}), 200


def jinnang_entry(payload, now, bypass, params):
    """錦囊 v4 的進場判定。回傳 candidate dict，或一句說明為什麼沒有下單。  [R78]

    只在【一根 M15 剛收盤】時評估，同一根只評估一次。
    錦囊沒有加碼（Pine 的 pyramiding = 0），所以有持倉就不再進場。
    """
    buy_lots, sell_lots = to_float(payload.get("buy_lots")), to_float(payload.get("sell_lots"))
    equity = risk_equity(payload)                                                      # [R88] 扣掉信用
    if buy_lots is None or sell_lots is None or equity is None or equity <= 0:
        return "封包缺少 buy_lots / sell_lots / equity"
    if round(buy_lots + sell_lots, 2) > 0:
        return "已有持倉，錦囊不加碼（pyramiding = 0），等 EA 定時出場"

    try:
        history = gcs_read_json(M15_HISTORY_FILE, [])
    except StorageError as exc:
        print(f"⚠️ [M15 歷史讀取失敗] {exc}", flush=True)
        return "M15 歷史不可用"
    history = history if isinstance(history, list) else []
    if len(history) < 2:
        return f"M15 歷史只有 {len(history)} 根"

    # [R80] EA（V22/V23）送的是 shift=1 的 K 線，整份歷史都已收盤 → 全部拿來用。
    #       JN_M15_LAST_CLOSED=0 時才丟掉最後一根（會送正在形成那根的 EA）。
    closed = history if JN_M15_LAST_CLOSED else history[:-1]
    if len(closed) < 2:
        return f"已收盤的 M15 只有 {len(closed)} 根"
    last_closed = closed[-1]
    if not claim_m15_bar(int(last_closed["time"])):
        return "這根 M15 已經評估過了"

    v = jinnang_session.evaluate(closed)
    print(f"🎯 [錦囊 v4] {v['text']}", flush=True)
    if not v.get("ready"):
        log_decision(f"⏳ [錦囊] {v['text']}", key="jinnang")
        return v["text"]
    if v.get("signal") != "BUY":
        log_decision(f"📡 [錦囊] {v['text']}", key="jinnang")
        return v["text"]

    atr = v["atr"]
    # 錦囊沒有價格停損 —— 真正的出場是 EA 的 InpHoldMinutes = 150 分鐘定時全平。
    # 這裡送的是災難停損，正常碰不到；tp_distance = None 代表不送 TP 欄位。
    sl_distance = max(params["min_sl_distance"], round(atr * JN_DISASTER_SL_ATR, 2))
    price = to_float(payload.get("price")) or v["price"]
    # [R79] 倉位大小用【實測最壞單筆虧損】當距離，不是用災難停損 —— 理由見常數區。
    sizing_distance = max(params["min_sl_distance"],
                          round(price * JN_SIZING_ADVERSE_PCT / 100.0, 2))
    max_lots, note = PureGCPPyramidingSession.calculate_max_lots(
        equity, str(payload.get("currency") or ACCOUNT_CURRENCY_DEFAULT), price, sizing_distance,
        ignore_risk="risk_cap" in bypass)
    if max_lots + 1e-9 < params["size"]:
        ceil_px = jinnang_price_ceiling(equity, payload.get("currency"))
        msg = (f"風險上限 {max_lots:.2f} 手 < 單筆 {params['size']:.2f} 手"
               f"（以實測最壞虧損 {JN_SIZING_ADVERSE_PCT:g}% = US${sizing_distance:.2f} 計；{note}）")
        if ceil_px:
            msg += (f"。這個戶口在 RISK_PCT={RISK_PCT*100:g}% 之下最高只能做到金價 "
                    f"US${ceil_px:,.0f}，目前 {price:,.0f} —— 要繼續做就得加本金，不是調鬆風控。")
        log_decision(f"🛑 [錦囊·資金控管] {msg}", key="risk")
        return msg

    log_decision(f"🎯 [錦囊候選] BUY @ {price:.2f}｜{v['text']}｜抱 {JN_HOLD_BARS} 根後由 EA 定時出場",
                 key="candidate")
    return {"signal": "BUY", "ticker": params["symbol"], "price": price, "direction": "UP",
            "sl_distance": sl_distance, "tp_distance": None, "atr_m15": atr,
            "max_lots": max_lots, "exposure": 0.0, "kind": "FIRST", "engine": "JINNANG"}


def handle_heartbeat(payload, can_trade):
    now = now_ts()
    action = payload.get("action")
    status_signal = str(payload.get("status") or "").strip().upper()
    m15_ohlc = payload.get("m15_ohlc") if isinstance(payload.get("m15_ohlc"), dict) else {}   # [R23b]

    # 1) Hard events first, so nothing below can skip them.  [R10 R62]
    if status_signal in ("TARGET_HIT", "RISK_HIT"):
        until = next_ny_rollover_ts(now)
        lock_reason = "當日獲利達標 (TARGET_HIT)" if status_signal == "TARGET_HIT" else "EA 帳戶風控觸發 (RISK_HIT)"
        try:
            set_hard_lock(lock_reason, until)
            update_pyramid_state(last_entry_price=None, last_entry_dir=None)
        except StorageError as exc:
            print(f"🚨 [嚴重] TARGET_HIT 硬鎖寫入失敗：{exc}", flush=True)
        log_decision(f"🛑 [{lock_reason}] 電閘硬鎖至 {fmt_ny(until)}，重置加單基準價。", key="target_hit")
    elif action == "close_gate":
        disarm_gate("❌ EA 要求 close_gate：取消開閘，需重新 Setup→Trigger")                  # [R19]

    # 2) M15 levels (writer path) and account snapshot.
    m15_levels = mtf_levels_session.ingest(m15_ohlc) if m15_ohlc else mtf_levels_session.read_levels()
    snapshot = save_account_snapshot(payload, m15_ohlc, m15_levels)

    warn = broker_symbol_mismatch(snapshot)                                              # [R83]
    if warn:
        print(f"🚨 [商品名不一致] {warn}", flush=True)
        log_decision(f"🚨 [商品名不一致] {warn}", key="symbol_mismatch")

    # 2b) 🛡️ 風控電閘：每一次心跳都重評，這是 armed 的唯一來源。  [R70]
    m1_result, bar, news = None, None, None
    bypass = read_gate_bypass()
    if GATE_DRIVER != "REGIME":
        news = macro_news_session.status(now)
        risk_result = apply_risk_to_gate(snapshot, news["locked"] and "news" not in bypass)
        if isinstance(risk_result, dict) and risk_result["before"] != risk_result["after"]:
            log_decision(f"{'🟢' if risk_result['after'] == 'OPEN' else '🔒'} "
                         f"[電閘 {risk_result['before']}→{risk_result['after']}] {risk_result['reason']}", key="gate")

    # 3) M1 bar: validate, de-duplicate, update the radar (display only under RISK).
    m1_ohlc = payload.get("m1_ohlc")
    if isinstance(m1_ohlc, dict) and m1_ohlc.get("is_new_bar"):
        bar = gold_indicator_session.parse_bar(m1_ohlc)
        if bar is None:
            print("⚠️ [M1] 無效的 m1_ohlc，略過。", flush=True)
        elif not gold_indicator_session.is_gold_market_open(now):
            print("ℹ️ [M1] 休市時段，略過。", flush=True)
            log_decision("🌙 [休市] 黃金休市時段，暫停盤勢判定。", key="monitor")
        elif not claim_m1_bar(bar["time"]):
            print(f"ℹ️ [M1] 重複的 K 線封包 {bar['time']}，略過。", flush=True)
        else:
            news = news or macro_news_session.status(now)
            try:
                m1_result = gold_indicator_session.process_m1_bar(
                    bar, news["locked"] and "news" not in bypass, skip_setup="setup_trigger" in bypass)
            except Exception as exc:
                print(f"⚠️ [M1 盤勢狀態機異常] {exc}", flush=True)

    # 4) Gate check.
    gate_state = read_gate_state()
    if gate_status(gate_state, now) != "OPEN":
        return locked_response(gate_state)
    if not can_trade:                                                                    # [R18]
        return jsonify({"status": "error", "message": "Unauthorized token"}), 403
    order_params = read_order_params()[0]

    # 4b) [R86] 商品名確定不一致就不送單。只有兩邊都知道、而且不同時才會擋，
    #     所以不會因為「還沒核對過」把自己鎖死。回 monitoring，EA 收到就是不動作。
    sym_warn = broker_symbol_mismatch(snapshot)
    if sym_warn:
        log_decision(f"🚨 [商品名不一致・已擋單] {sym_warn}", key="symbol_mismatch_block")
        return jsonify({"status": "monitoring", "current_gate": "OPEN",
                        "message": f"商品名不一致，拒絕送單。{sym_warn}"}), 200

    # 5) 進場引擎 → 執行。
    if ENTRY_ENGINE == "JINNANG":                                                        # [R78]
        candidate = jinnang_entry(payload, now, bypass, order_params)
        if not isinstance(candidate, dict):
            return jsonify({"status": "monitoring", "message": candidate or "Waiting for 錦囊 v4 signal",
                            "current_gate": "OPEN"}), 200
        rsi = m1_result["rsi"] if m1_result else None
        news = news or macro_news_session.status(now)
        return jsonify(execute_signal(candidate, payload, m15_levels, rsi, news, bypass, order_params)), 200

    if m1_result is None:
        return jsonify({"status": "monitoring", "message": "No new M1 bar to evaluate", "current_gate": "OPEN"}), 200
    candidate = pure_gcp_session.evaluate_and_trigger(payload, gate_state, m15_levels, bar, m1_result["rsi"], now,
                                                      bypass=bypass, params=order_params)
    if not candidate:
        return jsonify({"status": "monitoring", "message": "Waiting for pure GCP criteria", "current_gate": "OPEN"}), 200
    return jsonify(execute_signal(candidate, payload, m15_levels, m1_result["rsi"], news, bypass, order_params)), 200


# =============================================================================
# 🌐 Web pages (read-only except the explicit dashboard actions)
# =============================================================================
BASE_CSS = """
:root { --primary:#0f62fe; --success:#198754; --danger:#dc3545; --warning:#d97706; --bg:#f4f7fb; --card:#fff; --text:#161616; --muted:#6c757d; }
* { box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); padding:20px 15px; margin:0; }
.container { max-width:1050px; margin:0 auto; }
.nav { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:24px; padding:15px 20px; background:var(--card); border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.03); }
.nav a { color:var(--primary); text-decoration:none; font-weight:bold; font-size:14px; margin-left:15px; }
.nav-links { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.nav-link { display:inline-block; padding:7px 12px; border-radius:20px; font-size:13px; font-weight:700;
            text-decoration:none; color:var(--primary); background:#eef4ff; white-space:nowrap; }
.nav-link:hover { background:#dbe7ff; }
.nav-current { background:#0f62fe; color:#fff; cursor:default; }
.brand { display:flex; align-items:center; gap:10px; min-width:0; }
.brand-logo { width:34px; height:34px; flex-shrink:0; }
.brand-logo svg { width:100%; height:100%; display:block; }
.page-title { font-size:18px; font-weight:bold; margin:0; }
.grid { display:grid; gap:16px; margin-bottom:24px; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); }
.card { background:var(--card); padding:20px; border-radius:16px; box-shadow:0 4px 15px rgba(0,0,0,.04); }
.card-title { font-size:13px; color:var(--muted); margin-bottom:8px; font-weight:600; }
.card-value { font-size:24px; font-weight:bold; }
.card-small { font-size:16px; font-weight:bold; }
.card-desc { font-size:12px; color:#adb5bd; margin-top:8px; }
.section { background:var(--card); padding:25px; border-radius:16px; box-shadow:0 4px 15px rgba(0,0,0,.04); margin-bottom:24px; }
.section-header { font-size:16px; font-weight:700; margin:30px 0 15px; padding-bottom:10px; border-bottom:2px solid #e9ecef; }
h2 { font-size:17px; margin:0 0 16px; }
.pos { color:var(--success)!important; } .neg { color:var(--danger)!important; } .muted { color:var(--muted)!important; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { padding:10px 12px; text-align:left; border-bottom:1px solid #f1f3f5; }
th { color:var(--muted); font-weight:600; background:#f8f9fa; position:sticky; top:0; }
.scroll { max-height:350px; overflow:auto; }
.mono { font-family:"Courier New",Courier,monospace; white-space:pre-wrap; }
.log-box { background:#f8f9fa; border-left:4px solid var(--primary); padding:12px 16px; border-radius:0 8px 8px 0; max-height:300px; overflow-y:auto; }
.log-line { margin-bottom:6px; font-size:13px; border-bottom:1px dashed #e9ecef; padding-bottom:4px; }
.log-card { background:#f8f9fa; border-left:4px solid var(--primary); padding:14px 18px; margin-bottom:12px; border-radius:0 8px 8px 0; }
.log-ctx { color:#495057; line-height:1.6; font-size:13px; margin-bottom:8px; word-break:break-word; }
.log-res { font-weight:bold; font-size:14px; padding-top:8px; border-top:1px dashed #dee2e6; }
.badge { padding:4px 8px; border-radius:4px; font-weight:bold; font-size:11px; }
.badge-high { background:#f8d7da; color:#721c24; } .badge-medium { background:#fff3cd; color:#856404; }
.badge-imminent { background:var(--danger); color:#fff; animation:blink 1.5s infinite; }
@keyframes blink { 50% { opacity:.5; } }
.btn { display:inline-block; padding:14px 24px; border-radius:8px; margin:6px; font-weight:bold; color:#fff; text-decoration:none; }
.btn-open { background:var(--success); } .btn-lock { background:var(--danger); } .btn-primary { background:var(--primary); } .btn-dark { background:#212529; }
.banner { padding:12px; margin-bottom:20px; border-radius:8px; font-weight:bold; }
.level-box { background:#f8f9fa; padding:16px; border-radius:8px; }
"""

LOG_KEY_COLORS = {
    "candidate": "#0d6efd", "entry_sent": "#198754", "gate": "#3730a3", "regime": "#3730a3", "monitor": "#6c757d", "admin": "#d97706",
    "wait": "#6c757d", "filter": "#6c757d", "settle": "#6c757d", "anchor": "#6c757d",
    "data": "#d97706", "risk": "#dc3545", "structure": "#dc3545", "ai_reject": "#dc3545",
    "news_reject": "#dc3545", "broker_error": "#dc3545", "target_hit": "#dc3545",
    "ai_review": "#7c3aed", "ai_shadow": "#d97706",
}

CHART_SCRIPT = """
<script>
(function () {
  var el = document.getElementById('pnlChart');
  if (!el || typeof Chart === 'undefined') return;
  var ctx = el.getContext('2d');
  var gradient = ctx.createLinearGradient(0, 0, 0, 280);
  gradient.addColorStop(0, 'rgba(15, 98, 254, 0.2)');
  gradient.addColorStop(1, 'rgba(15, 98, 254, 0)');
  var labels = __LABELS__, data = __DATA__;
  new Chart(ctx, { type: 'line',
    data: { labels: labels.length ? labels : ['Init'],
            datasets: [{ label: '累計已實現損益', data: data.length ? data : [0], borderColor: '#0f62fe',
                         backgroundColor: gradient, borderWidth: 2.5, fill: true, tension: 0.25, pointRadius: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } } });
})();
</script>
"""


# 每一頁頁頂都有同一組連結，current 那一項不做連結
# [R91] 八陣圖指令台（大恒指人手掛單）住在 claude.ai 的 artifact 上，不在這裡託管 ——
#       它用 window.claude.use("db") 自動載入每日高低點，那個執行環境只有 artifact 有。
#       導覽列上開一個連出去的口就好。
BAZHENTU_URL = "https://claude.ai/artifact/Qovghgidoao32zWai3gffX"

PAGE_LINKS = [
    ("welcome", "🏠 首頁"),
    ("info", "📄 投資人日誌"),
    ("gates_app", "🎛️ 關卡開關"),
    ("order_app", "🧾 送單參數"),
    ("jinnang_sheet", "🗒️ 錦囊執行單"),
    ("jinnang_tracker", "✅ 錦囊九十筆"),
    ("futu_range", "🌬️ 風揚陣波幅"),                       # [R105] 每頁頂都能到風揚陣
    ("es_range", "🇺🇸 ES 波幅"),                            # [R127] ES 標普 500 期貨
    (BAZHENTU_URL, "⚔️ 八陣圖指令台"),
    ("dashboard", "⚙️ 控制台"),
]


def page_nav(current, extra=()):
    def one(view, label):
        # [R91] 完整網址 = 站外的頁，直接連出去並另開分頁；其餘照舊用 ?view=。
        if view.startswith("http"):
            return (f"<a class='nav-link' href='{esc(view)}' target='_blank' "
                    f"rel='noopener noreferrer'>{label} ↗</a>")
        if view == current:
            return f"<span class='nav-link nav-current'>{label}</span>"
        return f"<a class='nav-link' href='?view={view}'>{label}</a>"

    items = "".join(one(view, label) for view, label in PAGE_LINKS)
    items += "".join(f"<a class='nav-link' href='{href}'>{esc(label)}</a>" for href, label in extra)
    return f"<nav class='nav-links' aria-label='頁面導覽'>{items}</nav>"


def html_page(title, body, head_extra=""):
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
            f"<title>{esc(title)}</title><style>{BASE_CSS}</style>{head_extra}</head>"
            f"<body><div class='container'>{body}</div></body></html>")


def pnl_class(value):
    number = to_float(value)
    if number is None or number == 0:
        return "muted"
    return "pos" if number > 0 else "neg"


def gate_summary(state):
    """Short investor-facing description of why the gate is open/locked.  [R27b]"""
    if hard_lock_active(state):
        lock = state["hard_lock"]
        until = to_float(lock.get("until_ts"))
        return "neg", f"🛑 硬鎖：{lock.get('reason')}" + (f"（至 {fmt_ny(until)}）" if until else "（需手動解除）")
    if state.get("news_lock"):
        return "neg", "📰 新聞風控中"
    if GATE_DRIVER == "REGIME":
        if gate_status(state) == "OPEN":
            return "pos", f"✅ 放行（{DIR_WORD.get(state.get('dir'), '')}趨勢）"
        regime_text = {REGIME_RANGE: "橫行", REGIME_SETUP: "Setup 醞釀",
                       REGIME_TREND: "趨勢未確認"}.get(state.get("regime"), "—")
        return "muted", f"⏸️ 等待趨勢確認（{regime_text}）"
    risk = state.get("risk") if isinstance(state.get("risk"), dict) else {}
    if gate_status(state) == "OPEN":
        bits = []
        if risk.get("atr_pct") is not None:
            bits.append(f"波動 {risk['atr_pct']:.3f}%")
        if risk.get("exposure") is not None and risk.get("exposure_cap") is not None:
            bits.append(f"曝險 {risk['exposure']:.2f}x/{risk['exposure_cap']:.2f}x")
        return "pos", "✅ 放行" + (f"（{'、'.join(bits)}）" if bits else "")
    failed = [c["name"] for c in risk.get("checks", []) if not c.get("ok")]
    return "muted", "⏸️ " + ("、".join(failed) + " 未過關" if failed else "風控未評估")


# =============================================================================
# 🪶 品牌 Logo（彩色）：羽扇（諸葛亮）＋ 上升走勢，藍→綠漸層徽章
#   - 純內嵌 SVG，不依賴字型或外部圖檔；同一頁只出現一次，漸層 id 不會相撞
# =============================================================================
BRAND_LOGO_SVG = """
<svg viewBox='0 0 64 64' role='img' aria-label='智能諸葛亮' focusable='false'>
  <defs>
    <linearGradient id='zgBadge' x1='0' y1='0' x2='1' y2='1'>
      <stop offset='0%' stop-color='#6aa9ff'/><stop offset='46%' stop-color='#0f62fe'/>
      <stop offset='100%' stop-color='#0aa06e'/>
    </linearGradient>
    <linearGradient id='zgVisor' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0%' stop-color='#17356f'/><stop offset='100%' stop-color='#0b1f45'/>
    </linearGradient>
    <linearGradient id='zgSpark' x1='0' y1='1' x2='1' y2='0'>
      <stop offset='0%' stop-color='#ffd166'/><stop offset='100%' stop-color='#ff8c1a'/>
    </linearGradient>
  </defs>
  <rect x='2' y='2' width='60' height='60' rx='18' fill='url(#zgBadge)'/>
  <rect x='2' y='2' width='60' height='60' rx='18' fill='none' stroke='#ffffff' stroke-opacity='.22' stroke-width='1.5'/>
  <path d='M32 16.5v-4' stroke='#ffffff' stroke-width='2.6' stroke-linecap='round'/>
  <circle cx='32' cy='9.5' r='4.6' fill='#ffffff' fill-opacity='.28'/>
  <circle cx='32' cy='9.5' r='3' fill='url(#zgSpark)'/>
  <path d='M22 48h20a7 7 0 0 1 7 7v3H15v-3a7 7 0 0 1 7-7z' fill='#ffffff' fill-opacity='.72'/>
  <rect x='8.5' y='26' width='5.5' height='11' rx='2.75' fill='#ffffff' fill-opacity='.8'/>
  <rect x='50' y='26' width='5.5' height='11' rx='2.75' fill='#ffffff' fill-opacity='.8'/>
  <rect x='13' y='16' width='38' height='33' rx='13' fill='#ffffff'/>
  <rect x='18.5' y='21.5' width='27' height='18' rx='9' fill='url(#zgVisor)'/>
  <circle cx='26.5' cy='28.8' r='3.5' fill='#8fe3ff'/><circle cx='25.4' cy='27.6' r='1.25' fill='#ffffff'/>
  <circle cx='37.5' cy='28.8' r='3.5' fill='#8fe3ff'/><circle cx='36.4' cy='27.6' r='1.25' fill='#ffffff'/>
  <path d='M27.6 34.4q4.4 3.4 8.8 0' fill='none' stroke='#8fe3ff' stroke-width='2.1' stroke-linecap='round'/>
  <circle cx='16.6' cy='34.5' r='2.1' fill='#ff8c1a' fill-opacity='.5'/>
  <circle cx='47.4' cy='34.5' r='2.1' fill='#ff8c1a' fill-opacity='.5'/>
  <circle cx='24.6' cy='55' r='1.9' fill='#0aa06e' fill-opacity='.75'/>
  <path d='M29.6 55h12' stroke='#0f62fe' stroke-opacity='.32' stroke-width='2.4' stroke-linecap='round'/>
</svg>
"""

WELCOME_CSS = """
<style>
.hub { max-width:840px; margin:36px auto 0; }
.hub-head { display:flex; align-items:center; justify-content:center; gap:16px; margin-bottom:30px; }
.hub-logo { width:76px; height:76px; flex-shrink:0; filter:drop-shadow(0 6px 14px rgba(15,98,254,.28)); }
.hub-logo svg { width:100%; height:100%; display:block; }
.hub-names { text-align:left; }
.hub-word { font-size:30px; font-weight:900; letter-spacing:3px; margin:0; color:#0f62fe; line-height:1.15; }
@supports ((background-clip:text) or (-webkit-background-clip:text)) {
  .hub-word { background:linear-gradient(95deg,#0f62fe 10%,#0aa06e 90%); -webkit-background-clip:text; background-clip:text; color:transparent; }
}
.hub-sub { font-size:12px; color:var(--muted); letter-spacing:2px; margin-top:4px; }
.hub .nav-links { justify-content:center; margin-bottom:22px; }
.tiles { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; }
.tile { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px;
        padding:26px 14px 22px; min-height:186px; background:var(--card); border-radius:24px;
        box-shadow:0 6px 18px rgba(0,0,0,.06); text-decoration:none; border:2px solid transparent;
        transition:transform .12s ease, box-shadow .12s ease; }
.tile svg { width:74px; height:74px; flex-shrink:0; }
.tile-text { text-align:center; }
.tile-label { font-size:16px; font-weight:800; color:var(--text); letter-spacing:.5px; }
.tile-sub { font-size:11px; color:var(--muted); margin-top:3px; letter-spacing:.5px; }
.tile:hover { transform:translateY(-3px); box-shadow:0 10px 24px rgba(0,0,0,.12); }
.tile:active { transform:scale(.97); }
.tile:focus-visible { outline:none; border-color:currentColor; box-shadow:0 0 0 4px rgba(15,98,254,.25); }
.hub-foot { text-align:center; font-size:11px; color:#c7ccd1; margin:32px 0 10px; letter-spacing:.5px; }
@media (max-width:640px) {
  .hub { margin-top:16px; }
  .hub-head { gap:12px; margin-bottom:20px; }
  .hub-logo { width:58px; height:58px; }
  .hub-word { font-size:23px; letter-spacing:2px; }
  .tiles { grid-template-columns:repeat(2,1fr); gap:13px; }
  .tile { min-height:150px; padding:18px 10px 16px; gap:9px; border-radius:20px; }
  .tile svg { width:58px; height:58px; }
  .tile-label { font-size:14px; }
  .tiles a:last-child:nth-child(odd) { grid-column:span 2; flex-direction:row; min-height:92px; gap:16px; }
  .tiles a:last-child:nth-child(odd) .tile-text { text-align:left; }
}
@media (prefers-reduced-motion:reduce) { .tile { transition:none; } .tile:hover, .tile:active { transform:none; } }
</style>
"""

SVG_OPEN = ("<svg viewBox='0 0 48 48' fill='none' stroke='currentColor' stroke-width='2.6' "
            "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' focusable='false'>")

HUB_ICONS = {
    # 投資人日誌：K 線走勢圖
    "info": SVG_OPEN + ("<path d='M7 6v36h34'/>"
                        "<rect x='13' y='21' width='9' height='14' rx='2.5'/><path d='M17.5 14v7M17.5 35v5'/>"
                        "<rect x='29' y='12' width='9' height='13' rx='2.5'/><path d='M33.5 7v5M33.5 25v6'/>"
                        "</svg>"),
    # 關卡開關（獨立版）：視窗裡的開關
    "gates_app": SVG_OPEN + ("<rect x='5' y='8' width='38' height='32' rx='5'/><path d='M5 17h38'/>"
                             "<path d='M10 12.5h.02M14 12.5h.02'/>"
                             "<rect x='11' y='21' width='16' height='8' rx='4'/><circle cx='23' cy='25' r='2.2'/>"
                             "<rect x='11' y='31.5' width='16' height='8' rx='4'/><circle cx='15' cy='35.5' r='2.2'/>"
                             "<path d='M31 25h6M31 35.5h6'/></svg>"),
    # 關卡開關（內建版）：雲端（函式內建）＋下方的開關
    "gates": SVG_OPEN + ("<path d='M15 27h17a8.5 8.5 0 0 0 1.4-16.9A11.5 11.5 0 0 0 11.6 11 7.5 7.5 0 0 0 13 27h2'/>"
                         "<rect x='13' y='32' width='22' height='11' rx='5.5'/>"
                         "<circle cx='29.5' cy='37.5' r='3'/></svg>"),
    # 送單參數：JSON 封包送出
    "order_app": SVG_OPEN + ("<path d='M11 7h20l7 7v27a2 2 0 0 1-2 2H11a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z'/>"
                             "<path d='M30 7v8h8'/>"
                             "<path d='M19 23c-2 0-3 1-3 2.8v1.6c0 1.3-.9 1.8-1.8 1.8.9 0 1.8.5 1.8 1.8v1.6c0 1.8 1 2.8 3 2.8'/>"
                             "<path d='M28 23c2 0 3 1 3 2.8v1.6c0 1.3.9 1.8 1.8 1.8-.9 0-1.8.5-1.8 1.8v1.6c0 1.8-1 2.8-3 2.8'/>"
                             "</svg>"),
    # 錦囊執行單：夾板上的單據與打勾
    "jinnang_sheet": SVG_OPEN + ("<path d='M16 8H12a2 2 0 0 0-2 2v30a2 2 0 0 0 2 2h24a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-4'/>"
                                 "<rect x='17' y='5' width='14' height='7' rx='2.2'/>"
                                 "<path d='M16 22h16M16 29h16'/>"
                                 "<path d='M16 35.5l2.6 2.6L23 33.5'/></svg>"),
    # 錦囊九十筆：九宮格，最後一格打勾
    "jinnang_tracker": SVG_OPEN + ("<rect x='7' y='7' width='10' height='10' rx='2.2'/>"
                                   "<rect x='19' y='7' width='10' height='10' rx='2.2'/>"
                                   "<rect x='31' y='7' width='10' height='10' rx='2.2'/>"
                                   "<rect x='7' y='19' width='10' height='10' rx='2.2'/>"
                                   "<rect x='19' y='19' width='10' height='10' rx='2.2'/>"
                                   "<rect x='31' y='19' width='10' height='10' rx='2.2'/>"
                                   "<rect x='7' y='31' width='10' height='10' rx='2.2'/>"
                                   "<rect x='19' y='31' width='10' height='10' rx='2.2'/>"
                                   "<rect x='31' y='31' width='10' height='10' rx='2.2'/>"
                                   "<path d='M33.4 36l2.1 2.1L39 34.6'/></svg>"),
    # 系統控制台：儀表板指針
    "dashboard": SVG_OPEN + ("<path d='M8 35a16 16 0 1 1 32 0'/><path d='M24 35l9-9'/><circle cx='24' cy='35' r='3'/>"
                             "<path d='M24 13v3M12.6 18.6l2.1 2.1M35.4 18.6l-2.1 2.1M8 35h3M37 35h3'/></svg>"),
}

# href, 圖示, 標籤, 副標, 圖示顏色
HUB_TILES = [
    ("?view=info", "info", "投資人日誌", "實盤績效與 GCP 決策", "#0f62fe"),
    ("?view=gates_app", "gates_app", "關卡開關", "逐關開關與逐關測試", "#d97706"),
    ("?view=order_app", "order_app", "送單參數", "webhook 封包欄位", "#0aa06e"),
    ("?view=jinnang_sheet", "jinnang_sheet", "錦囊執行單", "思考流程與單筆執行單", "#2c6b7a"),
    ("?view=jinnang_tracker", "jinnang_tracker", "錦囊九十筆", "人手下單的合規訓練", "#6d5bd0"),
    ("?view=dashboard", "dashboard", "系統控制台", "管理員・電閘與帳戶", "#212529"),
]


def render_welcome_page():
    tiles = "".join(
        f"<a class='tile' href='{href}' title='{esc(label)}（{esc(sub)}）' aria-label='{esc(label)}，{esc(sub)}'>"
        f"<span style='color:{color}; display:flex;'>{HUB_ICONS[icon]}</span>"
        f"<span class='tile-text'><div class='tile-label'>{esc(label)}</div>"
        f"<div class='tile-sub'>{esc(sub)}</div></span></a>"
        for href, icon, label, sub, color in HUB_TILES
    )
    body = f"""
    <div class='hub'>
      <div class='hub-head'>
        <div class='hub-logo'>{BRAND_LOGO_SVG}</div>
        <div class='hub-names'>
          <h1 class='hub-word'>智能諸葛亮</h1>
          <div class='hub-sub'>AI 量化風控樞紐 v12</div>
        </div>
      </div>
      {page_nav("welcome")}
      <div class='tiles'>{tiles}</div>
      <div class='hub-foot'>&copy; 2026 AI Trading Lab</div>
    </div>"""
    return html_page("智能諸葛亮 AI 量化交易系統", body, head_extra=WELCOME_CSS)


def jinnang_price_ceiling(equity, currency=None):
    """[R79] 這個戶口在 RISK_PCT 之下，最高能做到金價多少（1 張 ORDER_SIZE）。

    倉位風險 = 價格 × JN_SIZING_ADVERSE_PCT% × CONTRACT_SIZE × ORDER_SIZE ≤ 淨值 × RISK_PCT
    黃金越貴、1 盎司的名目越大，同一個戶口能承受的就越少。這是限制，不是故障。
    """
    rate = FX_TO_USD.get(str(currency or ACCOUNT_CURRENCY_DEFAULT).upper()) \
        or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
    if not rate or not equity or equity <= 0 or JN_SIZING_ADVERSE_PCT <= 0:
        return None
    return (equity * rate * RISK_PCT) / (ORDER_SIZE * CONTRACT_SIZE * JN_SIZING_ADVERSE_PCT / 100.0)


def _jinnang_html():
    """儀表板上的錦囊 v4 進場引擎狀態。  [R78]"""
    if ENTRY_ENGINE != "JINNANG":
        return ""
    try:
        history = gcs_read_json(M15_HISTORY_FILE, [])
    except StorageError:
        history = []
    history = history if isinstance(history, list) else []
    v = jinnang_session.evaluate(history[:-1]) if len(history) >= 2 else {
        "ready": False, "text": f"【累積中⏳】M15 歷史 {len(history)} 根"}
    sig = v.get("signal")
    color = "#0f7b3f" if sig == "BUY" else "#5b6470"
    rows = [("判定", v.get("text", "—"))]
    warn = broker_symbol_mismatch()
    if warn:
        rows.append(("🚨 商品名不一致", warn))
    else:
        unverified = broker_symbol_unverified()                                          # [R86]
        if unverified:
            rows.append(("⚠️ 商品名未核對", unverified))
    if v.get("ready"):
        rows += [
            ("波動水位", (f"ATR(14)÷價格 = {v['atr_pct']:.4f}%　門檻 {VOL_FLOOR_ATR_PCT:g}%"
                      f"　打平 0.0837%") if v.get("atr_pct") is not None else "—"),
            ("橫行區間", (f"{v['box_bot']:.2f} ~ {v['box_top']:.2f}"
                      f"（突破線 {v['box_top'] + JN_BUF_ATR * v['atr']:.2f}）")
             if v.get("box_live") and v.get("box_top") else "尚未成形"),
            ("現價", f"{v['price']:.2f}" if v.get("price") else "—"),
        ]
        snap = read_account_snapshot()
        eq = risk_equity(snap)                                                         # [R88] 扣掉信用
        ceil_px = jinnang_price_ceiling(eq, snap.get("currency"))
        if eq and eq > 0 and v.get("price") and WORST_GAP_PCT > 0:
            # 曝險 × 最壞跳空 ≤ 容忍 − 回撤 → 解出會停止下單的回撤水準
            expo = ORDER_SIZE * CONTRACT_SIZE * v["price"] / (eq * FX_TO_USD.get(
                str(snap.get("currency") or ACCOUNT_CURRENCY_DEFAULT).upper(), FX_TO_USD["HKD"]))
            stop_dd = DD_TOLERANCE_PCT - expo * WORST_GAP_PCT
            rows.append(("回撤多少會停",
                         f"{max(0.0, stop_dd):.1f}%（約 {eq * max(0.0, stop_dd) / 100:,.0f}）"
                         f"　停了之後權益不會變，要加本金才解得開"))
        if ceil_px and v.get("price"):
            head = min(100.0, (ceil_px / v["price"] - 1) * 100)
            rows.append(("可做到的金價上限",
                         f"US${ceil_px:,.0f}（現價 {v['price']:,.0f}，還有 {head:+.1f}% 空間）"
                         + ("　⚠️ 超過就下不了單" if head < 10 else "")))
    body = "".join(f"<tr><td style='white-space:nowrap;font-weight:600;width:110px;'>{esc(k)}</td>"
                   f"<td style='font-size:13px;'>{esc(str(val))}</td></tr>" for k, val in rows)
    return (f"<div class='section-header'>🎯 錦囊 v4 進場引擎（只做多 · 抱 {JN_HOLD_BARS} 根 · 無價格停損）</div>"
            f"<div class='section' style='border-left:4px solid {color};'>"
            f"<table style='width:100%; border-collapse:collapse;'>{body}</table>"
            f"<div class='muted' style='font-size:12px; margin-top:8px;'>"
            f"出場不在這裡：EA 的 InpHoldMinutes = {JN_HOLD_BARS * 15} 分鐘定時全平。"
            f"全期實測年化 +2.47%、最大回撤 5.72%，但<b>樣本外 −0.82%/年、異常值佔淨利 106%，"
            f"優勢未被證實</b>。</div></div>")


def _risk_gate_html(state):
    """儀表板上的風控電閘區塊。回傳 (六關表格, 雷達標籤, 雷達註解, 電閘細節, 恢復自動註解)。"""
    if GATE_DRIVER == "REGIME":
        detail = (f"趨勢狀態：{esc(state.get('regime'))} / {esc(DIR_WORD.get(state.get('dir'), '—'))} / "
                  f"{'🟢 開閘：是' if state.get('armed') else '❌ 開閘：否'}")
        return "", "", "", detail, "恢復自動後，電閘仍需完成 Setup→Trigger 才會開啟。"

    tag = ("<span style='font-size:12px; font-weight:600; color:#8a6d3b; background:#fcf8e3; "
           "border:1px solid #faebcc; border-radius:10px; padding:2px 8px; margin-left:8px;'>僅供觀察・不參與開閘</span>")
    note = ("<div class='muted' style='font-size:12px; margin:-4px 0 10px;'>"
            "三級共振已於 2026-09-20 量度（README §22/§23）：修正 look-ahead 後 1~360 分鐘每個持倉長度的"
            "毛利 t 值都在 ±1.6 內，延後一分鐘進場由 +5.28 掉到 −2.18。它留在這裡是因為看盤有用，"
            "不是因為它有優勢。開閘由下方五道風控關卡決定。</div>")

    risk = state.get("risk") if isinstance(state.get("risk"), dict) else {}
    checks = risk.get("checks") or []
    if not checks:
        rows = "<tr><td colspan='3' class='muted'>尚未收到心跳，風控電閘未評估（fail-closed：視為 LOCK）。</td></tr>"
    else:
        rows = "".join(
            f"<tr><td style='width:34px; font-size:16px;'>{'✅' if c.get('ok') else '⛔'}</td>"
            f"<td style='white-space:nowrap; font-weight:600;'>{esc(c.get('name'))}</td>"
            f"<td class='{'muted' if c.get('ok') else ''}' style='font-size:13px;"
            f"{'' if c.get('ok') else ' color:#b02a37; font-weight:600;'}'>{esc(c.get('detail'))}</td></tr>"
            for c in checks)
    block = (f"<div class='section-header'>🛡️ 風控電閘六關"
             f"（{'只做多' if LONG_ONLY else '多空皆可'}）</div>"
             f"<div class='section'><table style='width:100%; border-collapse:collapse;'>{rows}</table>"
             f"<div class='muted' style='font-size:12px; margin-top:8px;'>"
             f"六關全過才開閘。缺數據一律當成不過關。評估時間："
             f"{esc(risk.get('evaluated_utc') or '—')} UTC</div></div>")

    passed = sum(1 for c in checks if c.get("ok"))
    detail = (f"風控關卡：{passed}/{len(checks) or 5} 通過 / "
              f"{'🟢 開閘：是' if state.get('armed') else '❌ 開閘：否'}")
    return block, tag, note, detail, "恢復自動後，電閘仍需五道風控關卡全過才會開啟。"


def build_dashboard_page(msg):
    state = read_gate_state()
    status = gate_status(state)
    acc = read_account_snapshot()
    stats = risk_manager_session.get_current_stats()
    currency = acc.get("currency") or ACCOUNT_CURRENCY_DEFAULT
    bars_count = len(gold_indicator_session.read_bars())
    try:
        verdict_log = gcs_read_text(M1_VERDICT_LOG_FILE) or "等待 M1 盤勢監控模組收集 K 棒..."
    except StorageError:
        verdict_log = "M1 判定日誌讀取失敗。"

    banners = {
        "auto": ("#d4edda", "#155724", "⚡ 已解除硬鎖並恢復自動。電閘會在下一次 Setup→Trigger 後開啟。"),
        "locked": ("#f8d7da", "#721c24", "🔒 已啟動緊急硬鎖。狀態機不會自動重新開閘，需手動恢復自動。"),
        "error": ("#fff3cd", "#856404", "⚠️ 電閘狀態寫入失敗，請查看 Cloud Logging。"),
    }
    banner = ""
    if msg in banners:
        bg, fg, text = banners[msg]
        banner = f"<div class='banner' style='background:{bg}; color:{fg};'>{text}</div>"

    bypass = read_gate_bypass()
    gates_warning = (f"<div class='banner' style='background:#fff3cd; color:#8a4b00;'>⚠️ {esc(detect_gate_mode(bypass))}："
                     f"已略過 {len(bypass)} 個關卡{esc(bypass_note(bypass))} → <a href='?view=gates'>關卡開關頁面</a></div>") if bypass else ""
    gate_color = "#198754" if status == "OPEN" else "#dc3545"
    gate_bg = "#d1e7dd" if status == "OPEN" else "#f8d7da"
    summary_class, summary_text = gate_summary(state)
    recent = stats.get("recent", {})
    risk_html, radar_tag, radar_note, gate_detail, auto_note = _risk_gate_html(state)
    risk_html = _jinnang_html() + risk_html

    body = f"""
    <div class='nav'><div class='brand'><div class='brand-logo'>{BRAND_LOGO_SVG}</div><h1 class='page-title'>⚙️ 核心控制台</h1></div>
      {page_nav("dashboard")}</div>
    {banner}{gates_warning}
    <div class='section-header'>🧠 M1 動能雷達（{bars_count} 根連續 K 線，需 {MIN_M1_BARS}）{radar_tag}</div>
    {radar_note}
    <div class='log-box mono' style='color:#3730a3; font-weight:600; max-height:200px;'>{esc(verdict_log)}</div>

    {risk_html}

    <div class='section' style='text-align:center; border-top:5px solid {gate_color}; margin-top:24px;'>
      <div class='muted' style='font-weight:600;'>雲端風控電閘狀態 (Gate Status)</div>
      <div style='display:inline-block; background:{gate_bg}; color:{gate_color}; padding:8px 20px; border-radius:30px; font-weight:800; font-size:24px; margin:15px 0;'>【 {status} 】</div>
      <div class='{summary_class}' style='font-weight:600; margin-bottom:6px;'>{esc(summary_text)}</div>
      <div class='muted' style='font-size:13px;'>{gate_detail}｜{esc(state.get('last_reason'))}</div>
      <div style='margin-top:15px;'>
        <a href='?view=dashboard&action=auto' class='btn btn-open'>🟢 解除硬鎖・恢復自動</a>
        <a href='?view=dashboard&action=lock' class='btn btn-lock'>🔴 緊急硬鎖 (LOCK)</a>
        <a href='?view=reset' class='btn' style='background:#6c757d; color:#fff;'>🧹 重置歷史紀錄</a>
      </div>
      <div class='muted' style='font-size:12px; margin-top:6px;'>{auto_note}🔴 實盤下單模式</div>
    </div>

    <div class='section-header'>💰 帳戶即時資金狀態 ({esc(currency)})｜更新：{esc(acc.get('received_utc', '—'))} UTC</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>Equity (淨值)</div><div class='card-value'>{fmt_num(acc.get('equity'))}</div></div>
      <div class='card'><div class='card-title'>Balance (餘額)</div><div class='card-value'>{fmt_num(acc.get('balance'))}</div></div>
      <div class='card'><div class='card-title'>今日已實現損益</div><div class='card-value {pnl_class(acc.get('daily_pnl'))}'>{fmt_num(acc.get('daily_pnl'), '{:+,.2f}')}</div></div>
      <div class='card'><div class='card-title'>浮動損益</div><div class='card-value {pnl_class(acc.get('floating'))}'>{fmt_num(acc.get('floating'), '{:+,.2f}')}</div></div>
    </div>

    <div class='section-header'>📡 MT5 實盤持倉狀態</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>Symbol</div><div class='card-small'>{esc(acc.get('symbol', 'NONE'))}</div></div>
      <div class='card'><div class='card-title'>Net Lots (多+/空-)</div><div class='card-small {pnl_class(acc.get('net_lots'))}'>{fmt_num(acc.get('net_lots'), '{:+.2f}')}</div></div>
      <div class='card'><div class='card-title'>Buy / Sell Lots</div><div class='card-small'><span class='pos'>{fmt_num(acc.get('buy_lots'))}</span> / <span class='neg'>{fmt_num(acc.get('sell_lots'))}</span></div></div>
    </div>

    <div class='section-header'>📈 近 {STATS_WINDOW} 筆交易統計{'（讀取失敗）' if stats.get('error') else ''}</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>勝率（不含保本）</div><div class='card-small'>{recent.get('win_rate', 0):.1f}%</div><div class='card-desc'>{recent.get('wins', 0)} 勝 / {recent.get('losses', 0)} 負 / {recent.get('breakeven', 0)} 保本</div></div>
      <div class='card'><div class='card-title'>平均獲利 / 平均虧損</div><div class='card-small'>{recent.get('avg_win', 0):,.2f} / {recent.get('avg_loss', 0):,.2f}</div></div>
      <div class='card'><div class='card-title'>每筆期望值</div><div class='card-small {pnl_class(recent.get('expectancy'))}'>{recent.get('expectancy', 0):+,.2f}</div></div>
      <div class='card'><div class='card-title'>TP 倍數</div><div class='card-small'>{stats['recommended_rrr']:.2f}R</div></div>
    </div>

    {futu_dashboard_html()}

    <div class='section-header'>📦 最新接收封包 (Raw Payload)</div>
    <div class='mono' style='background:#1e1e1e; color:#d4d4d4; border-left:4px solid var(--primary); padding:16px 20px; border-radius:0 8px 8px 0; font-size:13px; max-height:350px; overflow:auto;'>{esc(webhook_log_session.get_last_payload())}</div>
    """
    return html_page("智能諸葛亮量化儀表板 - 核心控制台", body)


def _ai_status_html():
    """投資人日誌上的「AI 覆核」面板：這道關卡現在到底在做什麼、手上有什麼材料。"""
    if not AI_REVIEW_ENABLED:
        return ("<div class='muted'>AI 覆核已停用（<code>AI_REVIEW_ENABLED=0</code>）——"
                "所有訊號都不會經過 LLM。</div>")

    try:
        rules_text = sft_pipeline_session.get_trading_rules()
        few_shot = sft_pipeline_session.get_dynamic_few_shot()
    except Exception as exc:                                  # 這個面板壞掉不該影響整頁
        return f"<div class='muted'>AI 知識庫讀取失敗：{esc(str(exc)[:120])}</div>"
    diag = ai_prompt_diagnostics(rules_text, few_shot)

    if AI_SHADOW_MODE:
        mode_html = ("<span style='color:#d97706; font-weight:700;'>👁️ 影子模式</span>"
                     "<div class='card-desc'>AI 照常判斷並記錄，但<b>不會擋單</b>；"
                     "事後可用 ai_eval.py 對帳，算出它擋對還是擋錯。</div>")
    else:
        mode_html = ("<span style='color:#dc3545; font-weight:700;'>🚫 強制執行</span>"
                     "<div class='card-desc'>AI 說 REJECT 就真的不下單。被擋掉的訊號沒有損益，"
                     "所以<b>無法驗證它擋得對不對</b>。</div>")

    lessons, rules_chars = diag["few_shot_lessons"], diag["rules_chars"]
    warn = ""
    if lessons == 0:
        warn += ("<div class='log-line' style='color:#d97706;'>⚠️ 動態 few-shot 是空的："
                 "SFT 資料集沒有可用的歷史虧損，prompt 裡會寫「目前無」。"
                 "AI 無法執行「與過去虧損比對」，只能靠通用直覺判斷。</div>")
    if rules_chars == 0:
        warn += ("<div class='log-line' style='color:#d97706;'>⚠️ 規則庫是空的："
                 "<code>ai_training/trading_rules.txt</code> 沒有內容。</div>")
    if not warn:
        warn = ("<div class='log-line' style='color:#198754;'>✅ AI 手上有規則庫與歷史教訓，"
                "「與過去虧損比對」這件事是有材料可做的。</div>")

    return f"""
      <div class='grid' style='grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); margin-bottom:10px;'>
        <div class='level-box'><div class='card-title'>執行模式</div><div class='card-small'>{mode_html}</div></div>
        <div class='level-box'><div class='card-title'>模型</div>
          <div class='card-small' style='font-size:14px;'>{esc(AI_MODEL)}</div>
          <div class='card-desc'>出錯時{'放行' if AI_FAIL_OPEN else '拒絕'}（AI_FAIL_OPEN）</div></div>
        <div class='level-box'><div class='card-title'>歷史虧損教訓</div>
          <div class='card-small {'neg' if lessons == 0 else 'pos'}'>{lessons} 條</div>
          <div class='card-desc'>取最近 {FEW_SHOT_LIMIT} 筆已平倉的虧損單</div></div>
        <div class='level-box'><div class='card-title'>規則庫</div>
          <div class='card-small {'neg' if rules_chars == 0 else 'pos'}'>{rules_chars} 字元</div>
          <div class='card-desc'>trading_rules.txt，上限 4000</div></div>
      </div>
      <div class='log-box' style='max-height:160px;'>{warn}</div>"""


def _legacy_decision_log_html():
    """Shown only while the v12 log is still empty: last lines of the v11 text log."""
    try:
        legacy = gcs_read_text("gcp_decision_log.txt") or ""
    except StorageError:
        legacy = ""
    lines = [line for line in legacy.splitlines() if line.strip()][:30]
    if not lines:
        return "<div class='muted'>系統正在等待首次決策...</div>"
    return ("<div class='muted' style='margin-bottom:8px; font-weight:600;'>v12 尚無紀錄，以下為 v11 舊版決策紀錄：</div>"
            + "".join(f"<div class='log-line muted'>{esc(line)}</div>" for line in lines))


def _trade_sort_key(trade):
    return str(trade.get("time") or "").replace(".", "-")     # MT5 "2026.09.16 10:00" -> sortable  [R57]


def build_info_page():
    # ---- trades & realized PnL curve ----
    try:
        trades = sorted(risk_manager_session.read_trades(), key=_trade_sort_key)
        history_note = ""
    except StorageError as exc:
        print(f"⚠️ [交易歷史讀取失敗] {exc}", flush=True)
        trades, history_note = [], "（交易歷史讀取失敗）"
    stats = risk_manager_session.calculate_stats(trades)

    labels, series, cumulative = [], [], 0.0
    for trade in trades:
        cumulative += to_float(trade.get("profit"), 0.0)
        labels.append(_trade_sort_key(trade)[5:16] or "未知")                           # [R56]
        series.append(round(cumulative, 2))

    trade_rows = "".join(
        f"<tr><td>{esc(t.get('time', '未知'))}<span class='muted' style='font-size:11px;'> "
        f"{'MT5' if t.get('time_source') == 'broker' else ('UTC' if t.get('time_source') else '')}</span></td>"
        f"<td>{esc(t.get('ticket'))}</td>"
        f"<td>{(esc(fmt_num(t.get('volume'))) + ' 手 ' + esc(t.get('deal_type'))) if t.get('deal_type') else '舊資料'}</td>"
        f"<td class='{pnl_class(t.get('profit'))}' style='font-weight:bold;'>{fmt_num(t.get('profit'), '{:+,.2f}')}</td></tr>"
        for t in reversed(trades[-300:])
    ) or "<tr><td colspan='4' class='muted' style='text-align:center;'>尚無結算紀錄</td></tr>"

    # ---- SFT log (last 50 only)  [R6d] ----
    sft_cards = ""
    try:
        rows = jsonl_loads(gcs_read_text(SFT_DATASET_FILE) or "")[-50:]
    except StorageError:
        rows = []
    outcome_display = {"APPROVE": ("🎯 獲利交易", "#198754"), "REJECT": ("🛡️ 虧損交易", "#d97706"),
                       "BREAKEVEN": ("⚖️ 保本出場", "#6c757d")}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        try:
            meta = row.get("meta")
            context = format_signal_meta(meta) if isinstance(meta, dict) else str(row["contents"][0]["parts"][0]["text"])
            result_text = str(row["contents"][1]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError):
            continue
        if len(context) > 600:
            context = context[:600] + "…（舊版格式已截斷）"
        label = (row.get("outcome") or {}).get("label") or ("APPROVE" if result_text.upper().startswith("APPROVE") else "REJECT")
        title, color = outcome_display.get(label, outcome_display["REJECT"])
        sft_cards += (f"<div class='log-card'><div class='log-ctx'>{esc(context)}</div>"
                      f"<div class='log-res' style='color:{color};'>[{title}] {esc(result_text)}</div></div>")
    sft_cards = sft_cards or "<div class='log-card muted' style='text-align:center;'>等待首筆實盤結算後寫入日誌...</div>"

    # ---- gate, account, news ----
    state = read_gate_state()
    gate_class, gate_text = gate_summary(state)
    snapshot = read_account_snapshot()
    daily_pnl = snapshot.get("daily_pnl")

    news = macro_news_session.status()
    if not news["known"]:
        calendar_html = f"<span class='neg'>⚠️ {esc(news['reason'])}</span>"                # [R27c]
    elif news["locked"]:
        calendar_html = f"<span class='neg'>🛑 {esc(news['reason'])}</span>"
    elif news["warning"]:
        calendar_html = f"<span style='color:#d97706;'>⚠️ 使用快取｜{esc(news['warning'])}</span>"  # [R32]
    else:
        calendar_html = f"<span class='pos'>✅ 連線正常 ({len(news['events'])} 個數據已就緒)</span>"

    news_rows = ""
    for event in news["events"][:8]:
        badge = "badge-imminent" if event["is_imminent"] else ("badge-high" if event["impact"] == "High" else "badge-medium")
        event_dt = datetime.fromtimestamp(event["ts"], UTC)
        news_rows += (
            f"<tr><td>{esc(event['time_utc'])}</td>"
            f"<td style='color:#0f62fe; font-weight:600;'>{event_dt.astimezone(ZoneInfo('Europe/London')).strftime('%m-%d %H:%M')}</td>"
            f"<td style='color:#198754; font-weight:600;'>{event_dt.astimezone(ZoneInfo('Asia/Hong_Kong')).strftime('%m-%d %H:%M')}</td>"
            f"<td><span class='badge {badge}'>{esc(event['impact'])}</span></td><td style='font-weight:600;'>{esc(event['title'])}</td>"
            f"<td style='font-weight:bold;'>{esc(event['countdown'])}{' ⚠️ 避險中' if event['is_imminent'] else ''}</td></tr>")
    news_rows = news_rows or "<tr><td colspan='6' class='muted' style='text-align:center;'>近期無重大美元數據</td></tr>"

    # ---- levels & indicators (read-only)  [R20 R27d R58] ----
    levels = mtf_levels_session.read_levels()
    ready = levels.get("status") == "ready"
    r1, mid, s1 = (levels.get(k, "等待中") if ready else "等待中" for k in ("M15_R1", "M15_MID", "M15_S1"))
    bandwidth = f"{levels['M15_BB_WIDTH']}%" if ready else "..."
    bars = gold_indicator_session.read_bars()
    rsi = wilder_rsi_last([b["close"] for b in bars])
    snap_m15 = snapshot.get("m15_ohlc") if isinstance(snapshot.get("m15_ohlc"), dict) else {}   # [R23c]
    atr_text = " / ".join(esc(snap_m15.get(k, "N/A")) for k in ("atr_m1", "atr_m5", "atr_m15"))

    log_lines = "".join(
        f"<div class='log-line' style='color:{LOG_KEY_COLORS.get(entry.get('k'), '#3730a3')};'>"
        f"[{esc(entry.get('t'))} UTC] {esc(entry.get('m'))}</div>"
        for entry in read_decision_logs()
    ) or _legacy_decision_log_html()

    all_time = stats["all_time"]
    chart = CHART_SCRIPT.replace("__LABELS__", json.dumps(labels).replace("</", "<\\/")) \
                        .replace("__DATA__", json.dumps(series))

    body = f"""
    <div class='nav'><div class='brand'><div class='brand-logo'>{BRAND_LOGO_SVG}</div><h1 class='page-title'>📊 投資人數據中心</h1></div>{page_nav("info")}</div>
    <div class='grid'>
      <div class='card'><div class='card-title'>累計已實現損益 ({esc(ACCOUNT_CURRENCY_DEFAULT)})</div>
        <div class='card-value {pnl_class(cumulative)}'>{cumulative:+,.2f}</div><div class='card-desc'>全部已結算交易{history_note}</div></div>
      <div class='card'><div class='card-title'>今日已實現損益</div>
        <div class='card-value {pnl_class(daily_pnl)}'>{fmt_num(daily_pnl, '{:+,.2f}')}</div><div class='card-desc'>MT5 心跳同步</div></div>
      <div class='card'><div class='card-title'>實盤勝率（不含保本）</div>
        <div class='card-value'>{all_time['win_rate']:.1f}%</div>
        <div class='card-desc'>{all_time['trades']} 筆｜期望值 {all_time['expectancy']:+,.2f}｜TP {stats['recommended_rrr']:.1f}R</div></div>
      <div class='card'><div class='card-title'>諸葛亮電閘</div>
        <div class='card-small {gate_class}' style='padding-top:6px;'>{esc(gate_text)}</div><div class='card-desc'>趨勢狀態機 + 硬鎖 + 新聞風控</div></div>
      <div class='card'><div class='card-title'>ForexFactory 連線狀態</div>
        <div style='font-size:14px; font-weight:bold; padding-top:6px;'>{calendar_html}</div><div class='card-desc'>重大財經數據監控引擎</div></div>
    </div>

    <div class='section'><h2>🧠 AI 覆核關卡現況</h2>
      <p class='muted' style='font-size:12px;'>這道關卡只能否決、不能加分，所以「它手上有多少材料」決定了它的判斷品質上限。
        舊版格式的訓練資料無法使用，可到 <a href='?view=reset'>🧹 重置歷史紀錄</a> 清空後從乾淨的基準重新累積。</p>
      {_ai_status_html()}</div>

    <div class='section'><h2>🤖 純 GCP 交易大腦即時決策還原</h2>
      <p class='muted' style='font-size:12px;'>每一次候選訊號、覆核結果與實際送單都會記錄於此。
      紫色是 AI 的判斷、橘色是影子模式下「本來會被擋、但仍照常送出」的訊號。</p>
      <div class='log-box'>{log_lines}</div></div>

    <div class='section'><h2>🎯 核心決策水位與指標基準</h2>
      <div class='grid' style='grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); margin-bottom:10px;'>
        <div class='level-box' style='border-left:4px solid #dc3545;'><div class='card-title'>M15 上軌 (R1)</div><div class='card-small neg'>{esc(r1)}</div></div>
        <div class='level-box' style='border-left:4px solid #0f62fe;'><div class='card-title'>M15 中軌 (SMA20)</div><div class='card-small' style='color:#0f62fe;'>{esc(mid)}</div><div class='card-desc'>帶寬: {esc(bandwidth)}</div></div>
        <div class='level-box' style='border-left:4px solid #198754;'><div class='card-title'>M15 下軌 (S1)</div><div class='card-small pos'>{esc(s1)}</div></div>
      </div>
      <div style='background:#eef2ff; border-radius:8px; padding:12px 16px; font-size:13px; color:#3730a3;'>
        📡 <b>即時技術背景</b> ➔ <b>RSI(14, M1):</b> {fmt_num(rsi) if rsi is not None else '計算中'} | <b>ATR (M1/M5/M15):</b> {atr_text}</div></div>

    <div class='section'><h2>📅 ForexFactory 總經事件預警表 (USD High/Medium)</h2>
      <p class='muted' style='font-size:12px;'>{'/'.join(sorted(NEWS_LOCK_IMPACTS))} 級事件發布前 {NEWS_LOCK_BEFORE_MIN} 分鐘至發布後 {NEWS_LOCK_AFTER_MIN} 分鐘禁止新倉。</p>
      <div class='scroll'><table><tr><th>發布時間 (UTC)</th><th style='color:#0f62fe;'>倫敦</th><th style='color:#198754;'>香港</th><th>衝擊</th><th>經濟指標</th><th>倒數</th></tr>{news_rows}</table></div></div>

    <div class='section'><h2>📈 累計已實現損益曲線 (Realized PnL)</h2>
      <p class='muted' style='font-size:12px;'>僅含已平倉損益，不含浮動盈虧與出入金。</p>
      <div style='position:relative; height:280px;'><canvas id='pnlChart'></canvas></div></div>

    <div class='section'><h2>💰 實盤結算歷史</h2>
      <div class='scroll'><table><tr><th>結算時間</th><th>交易單號</th><th>平倉組成</th><th>淨損益</th></tr>{trade_rows}</table></div></div>

    <div class='section'><h2>🧠 AI 決策與風控日誌 (最近 50 筆)</h2><div class='scroll' style='max-height:400px;'>{sft_cards}</div></div>
    {chart}
    """
    return html_page("實盤績效與 AI 決策日誌 - 投資人專區", body,
                     head_extra="<script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'></script>")


# =============================================================================
# 🎛️ 關卡開關 (gate switches) — stored separately from the gate state machine
# =============================================================================
GATE_SWITCHES_FILE = "gate_switches.json"

# key, 名稱, 正常時檢查什麼, 略過後的效果, 風險提示
GATE_SWITCH_DEFS = [
    ("setup_trigger", "趨勢確認：Setup → Trigger",
     "必須先出現同向回調（Setup），再出現同向趨勢，電閘才開啟。",
     "只要判定為「單邊趨勢」就直接開閘，不等回調。",
     "容易在急拉急跌的末端追價。"),
    ("structure", "M15 布林帶結構",
     "首單：多單須突破上軌（空單跌破下軌），且 M15 收盤靠近高點（低點）。加單：價格須在中軌正確一側。",
     "首單與加單都不看布林帶位置。",
     "可能在帶內震盪區或逆結構位置進場。"),
    ("candle", "M1 收線方向",
     "多單須當根 M1 收陽，空單須收陰。",
     "不看當根 M1 陰陽。",
     "可能在反向 K 線上進場。"),
    ("risk_cap", "2% 風險倉位上限",
     "整組倉位打到止損時，虧損不超過淨值 × RISK_PCT。",
     "改用保證金上限（淨值 × MAX_MARGIN_PCT）與 HARD_MAX_LOTS 硬上限。",
     "⚠️ 整組止損的虧損可能是正常的數倍，請看下方試算。"),
    ("rsi", "RSI 極值",
     "多單 RSI(14, M1) 須低於 RSI_BUY_MAX，空單須高於 RSI_SELL_MIN。",
     "不看 RSI。",
     "可能在超買追多、超賣追空。"),
    ("news", "新聞風控",
     "高衝擊美元事件前後鎖閘；日曆無法載入時也禁止新倉。",
     "數據公布期間照常交易，日曆失效也照常交易。",
     "⚠️ 數據行情跳空與滑價可能遠超止損距離。"),
    ("ai", "AI 覆核",
     "LLM 須回覆 APPROVE；出錯或格式錯誤時依 AI_FAIL_OPEN 處理。"
     "AI_SHADOW_MODE=1 時照樣呼叫並記錄判斷，但不否決訊號。",
     "不呼叫 LLM，直接放行，連判斷紀錄都不會留下。",
     "少一層定性過濾。"),
    ("cooldown", "平倉後冷卻",
     "平倉後須等 REENTRY_COOLDOWN_SEC 秒才開新首單。",
     "平倉後可立即再開首單。",
     "止損後可能馬上再次進場。"),
    ("add_spacing", "加單 ATR 間距",
     "加單須比上次進場價多走 ADD_SPACING_ATR × ATR(M15)。",
     "每根符合條件的 K 線都可加單，直到倉位上限。",
     "⚠️ 加單會非常密集，平均成本貼近現價。"),
]
GATE_SWITCH_KEYS = [d[0] for d in GATE_SWITCH_DEFS]
GATE_SWITCH_NAMES = {d[0]: d[1] for d in GATE_SWITCH_DEFS}

# Data / safety preconditions: no switch is offered for these.
GATE_ALWAYS_ON_NOTES = [
    "M1 數據累積（約 65 根）與 M15 布林帶、ATR(M15) 資料就緒",
    "封包缺少 equity / buy_lots / sell_lots",
    "多空對沖持倉、持倉方向與趨勢相反",
    "上一張訂單送出後等待成交回報（防重複下單）",
    "加單基準價不存在時先記錄基準、本根不加單",
    "硬鎖、券商回應失敗",
]

# 依 2026-01→09（251,006 根 M1）的回測：關掉這兩關在樣本內（+22.7%）與樣本外
# （+17.4%、回撤僅 4.5%）都最穩定。其餘七關維持開啟。
DEFAULT_BYPASS = frozenset({"setup_trigger", "structure"})

GATE_MODES = {
    "recommended": ("📊 回測建議（預設）", DEFAULT_BYPASS),
    "strict": ("🛡️ 全部關卡開啟", frozenset()),
    "relaxed": ("🟡 寬鬆模式", frozenset({"setup_trigger", "structure", "candle", "risk_cap"})),
    "aggressive": ("🔥 激進模式", frozenset({"setup_trigger", "structure", "candle", "risk_cap", "rsi", "news", "ai"})),
}


# -----------------------------------------------------------------------------
# 🔢 關卡實際使用的門檻值（關卡頁顯示用）
#    env  = 環境變數，改了要重新部署；order = 送單參數頁可即時修改
# -----------------------------------------------------------------------------
def _pv(name, value, note="", source="env"):
    return {"name": name, "value": str(value), "note": note, "source": source}


def gate_parameter_values(params=None):
    """每個關卡判斷時實際用到的數值。"""
    params = params or read_order_params()[0]
    return {
        "setup_trigger": [
            _pv("NOISE_K", f"{NOISE_K:g}", "門檻 = K × σ × √分鐘；σ 取最近 60 分鐘每分鐘變化的標準差"),
            _pv("MIN_M1_BARS", MIN_M1_BARS, "要累積這麼多根連續 M1 才開始判定"),
            _pv("時間窗", "60 / 24 / 4 分鐘", "M15 / M5 / M1 三個窗口，需同方向越過門檻"),
        ],
        "structure": [
            _pv("FIRST_ENTRY_MODE", FIRST_ENTRY_MODE, "BREAKOUT＝突破布林帶；MID＝站上中軌"),
            _pv("M15_CLOSE_POSITION_MIN", f"{M15_CLOSE_POSITION_MIN:g}",
                f"多單收盤位置需 ≥ {M15_CLOSE_POSITION_MIN:g}，空單需 ≤ {1 - M15_CLOSE_POSITION_MIN:g}"),
            _pv("布林帶", f"{MTFDynamicLevelsSession.bb_period} 根 ± {MTFDynamicLevelsSession.bb_std_dev:g}σ",
                "M15 週期與標準差倍數"),
        ],
        "candle": [
            _pv("（無數值門檻）", "收陽 / 收陰", "只看當根 M1 的 close 與 open 相對位置"),
        ],
        "risk_cap": [
            _pv("RISK_PCT", f"{RISK_PCT:g}", f"整組倉位打到止損時最多虧損淨值的 {RISK_PCT * 100:g}%"),
            _pv("MAX_MARGIN_PCT", f"{MAX_MARGIN_PCT:g}", f"保證金佔用上限 {MAX_MARGIN_PCT * 100:g}%"),
            _pv("HARD_MAX_LOTS", f"{HARD_MAX_LOTS:g}", "手數硬上限，任何模式都不會超過"),
            _pv("BROKER_LEVERAGE", f"{BROKER_LEVERAGE:g}", "算保證金用，請與券商實際槓桿一致"),
            _pv("CONTRACT_SIZE", f"{CONTRACT_SIZE:g}", "XAUUSD：1 手 = 100 盎司"),
        ],
        "rsi": [
            _pv("RSI_BUY_MAX", f"{RSI_BUY_MAX:g}", "RSI 高於此值不追多"),
            _pv("RSI_SELL_MIN", f"{RSI_SELL_MIN:g}", "RSI 低於此值不追空"),
            _pv("RSI 週期", "14（M1，Wilder）", ""),
        ],
        "news": [
            _pv("NEWS_LOCK_BEFORE_MIN", NEWS_LOCK_BEFORE_MIN, "事件前鎖閘分鐘數"),
            _pv("NEWS_LOCK_AFTER_MIN", NEWS_LOCK_AFTER_MIN, "事件後鎖閘分鐘數"),
            _pv("NEWS_LOCK_IMPACTS", "/".join(sorted(NEWS_LOCK_IMPACTS)), "哪些影響等級會鎖閘（USD 事件）"),
            _pv("NEWS_FAIL_CLOSED", "是" if NEWS_FAIL_CLOSED else "否", "日曆載不到時是否禁止新倉"),
        ],
        "ai": [
            _pv("AI_REVIEW_ENABLED", "是" if AI_REVIEW_ENABLED else "否", "是否呼叫 LLM"),
            _pv("AI_MODEL", AI_MODEL, ""),
            _pv("AI_FAIL_OPEN", "放行" if AI_FAIL_OPEN else "拒絕", "AI 出錯或格式錯誤時怎麼處理"),
            _pv("AI_SHADOW_MODE", "👁️ 影子（記錄但不否決）" if AI_SHADOW_MODE else "強制執行",
                "影子模式下 AI 的反對不擋單，但會寫進 SFT 資料集供事後對帳"),
        ],
        "cooldown": [
            _pv("REENTRY_COOLDOWN_SEC", REENTRY_COOLDOWN_SEC,
                f"平倉後要等 {REENTRY_COOLDOWN_SEC // 60} 分 {REENTRY_COOLDOWN_SEC % 60} 秒才開新首單"),
        ],
        "add_spacing": [
            _pv("ADD_SPACING_ATR", f"{ADD_SPACING_ATR:g}", "加單需比上次進場價多走 ATR(M15) × 此倍數"),
        ],
    }


def system_parameter_values(params=None):
    """不屬於任何單一關卡、但會影響下單的其餘數值。"""
    params = params or read_order_params()[0]
    currencies = "、".join(f"{k}→{v:.4f}" for k, v in FX_TO_USD.items())
    return [
        {"group": "🛡️ 風控電閘（開閘的真正依據）", "items": [
            _pv("GATE_DRIVER", GATE_DRIVER,
                "RISK＝風控六關決定開閘（現行）；REGIME＝舊的三級共振（已量度為無優勢，僅供回退比對）"),
            _pv("LONG_ONLY", "只做多" if LONG_ONLY else "多空皆可",
                "全期 1,464 筆中 671 筆空單，每筆 −HK$0.84、t=−0.25（README §23）"),
            _pv("VOL_FLOOR_ATR_PCT", f"{VOL_FLOOR_ATR_PCT:g}%" if VOL_FLOOR_ATR_PCT > 0 else "停用",
                "波動下限＝ATR(14)/價格。打平點實測 0.0837%，低於此點差吃掉全部毛利"),
            _pv("DD_TOLERANCE_PCT", f"{DD_TOLERANCE_PCT:g}%", "空城計可承受回撤"),
            _pv("WORST_GAP_PCT", f"{WORST_GAP_PCT:g}%", "最壞日內跳空（黃金實測 −13.94%）"),
            _pv("EXPOSURE_HARD_CAP", f"{EXPOSURE_HARD_CAP:g}x", "曝險硬上限：名目 ÷ 淨值"),
            _pv("DAILY_LOSS_LIMIT_PCT", f"{DAILY_LOSS_LIMIT_PCT:g}%", "單日虧損上限（佔淨值）"),
            _pv("TRAINING_MAX_PER_DAY", TRAINING_MAX_PER_DAY if TRAINING_MAX_PER_DAY > 0 else "不限",
                "90 筆訓練的節奏；以紐約日界線計算"),
        ]},
        {"group": "🎯 進場引擎（錦囊 v4）", "items": [
            _pv("ENTRY_ENGINE", ENTRY_ENGINE,
                "JINNANG＝錦囊 v4（TradingView 全期 513 筆實測）；PYRAMID＝舊的加單引擎（從未回測，README §28）"),
            _pv("規則", "M15 區間突破 → 只做多 → 抱 10 根 → 無價格停損",
                "出場由 EA 的 InpHoldMinutes = 150 分鐘定時全平，不是 TP"),
            _pv("JN_HOLD_BARS", f"{JN_HOLD_BARS} 根 M15（{JN_HOLD_BARS*15} 分鐘）",
                "要和 EA 的 InpHoldMinutes 一致"),
            _pv("VOL_FLOOR_ATR_PCT", f"{VOL_FLOOR_ATR_PCT:g}%", "ATR(14)÷價格；打平點實測 0.0837%"),
            _pv("JN_DISASTER_SL_ATR", f"{JN_DISASTER_SL_ATR:g} × ATR",
                "災難停損，正常碰不到。錦囊本身沒有價格停損，TP 欄位不送出"),
            _pv("JN_MIN_BARS", f"{JN_MIN_BARS} 根",
                f"判定前要累積這麼多根已收盤 M15（約 {JN_MIN_BARS*15//60} 小時）"),
            _pv("全期實測", "513 筆／年化 +2.47%／最大回撤 5.72%",
                "TradingView 2018-03 → 2026-09。⚠️ 樣本外 −0.82%/年，異常值佔淨利 106%，優勢未證實"),
        ]},
        {"group": "🧾 送單（送單參數頁可即時修改）", "items": [
            _pv("size", f"{params['size']:.2f} 手", "每張單的手數", "order"),
            _pv("symbol", params["symbol"], "送單用的商品代號", "order"),
            _pv("target_rrr", f"{params['target_rrr']:g}R", "止盈 = 止損 × 此倍數", "order"),
            _pv("sl_atr_mult", f"{params['sl_atr_mult']:g}", "止損 = ATR(M15) × 此倍數", "order"),
            _pv("min_sl_distance", f"{params['min_sl_distance']:g} 美元", "止損距離下限", "order"),
            _pv("distance_unit", params["distance_unit"],
                "price＝送 *_price 欄位（美元）；points＝送點數", "order"),
            _pv("移動止損", ("停用" if params["ts_activation_price"] <= 0 or params["ts_distance_price"] <= 0
                         else f"啟動 {params['ts_activation_price']:g} / 跟隨 {params['ts_distance_price']:g}"),
                "0 代表整個欄位不送出", "order"),
            _pv("保本", ("停用" if params["breakeven_distance_price"] <= 0
                       else f"啟動 {params['breakeven_distance_price']:g} / 鎖利 {params['breakeven_profit']:g}"),
                "0 代表整個欄位不送出", "order"),
        ]},
        {"group": "💰 帳戶與匯率", "items": [
            _pv("ACCOUNT_CURRENCY", ACCOUNT_CURRENCY_DEFAULT, "EA 未回報幣別時的預設值"),
            _pv("FX_TO_USD", currencies, "內建匯率"),
            _pv("ACCOUNT_TO_USD_RATE", f"{ACCOUNT_TO_USD_RATE:g}", "其他幣別要自行設定，0＝未設定"),
        ]},
        {"group": "⏱️ 資料與時間", "items": [
            _pv("M1_HISTORY_MAX", M1_HISTORY_MAX, "M1 歷史最多保留幾根"),
            _pv("M1_GAP_RESET_SEC", f"{M1_GAP_RESET_SEC}（{M1_GAP_RESET_SEC // 60} 分鐘）",
                "超過此缺口就清空 M1 歷史重新累積"),
            _pv("ORDER_SETTLE_SEC", f"{ORDER_SETTLE_SEC}（{ORDER_SETTLE_SEC // 60} 分鐘）",
                "送單後持倉未變動前，暫停決策的時間"),
            _pv("BROKER_TIMEOUT_SEC", BROKER_TIMEOUT_SEC, "送單 HTTP 逾時"),
            _pv("BROKER_UTC_OFFSET_HOURS", f"{BROKER_UTC_OFFSET_HOURS:g}", "成交紀錄配對用的券商時差"),
        ]},
        {"group": "📈 統計", "items": [
            _pv("STATS_WINDOW", STATS_WINDOW, "控制台「近 N 筆」的 N"),
            _pv("BREAKEVEN_EPS", f"{BREAKEVEN_EPS:g}", "損益絕對值小於此值視為保本，不計入勝負"),
        ]},
    ]


# [R78] 目前的進場引擎實際會讀哪幾個 bypass key。
#       錦囊只看 risk_cap（資金控管）、news（新聞）、ai（覆核）；
#       其餘（setup_trigger / structure / candle / rsi / cooldown / add_spacing）
#       是舊 PureGCPPyramidingSession 專用的，換成錦囊後不會被讀到。
JINNANG_BYPASS_KEYS = frozenset({"risk_cap", "news", "ai"})
ACTIVE_BYPASS_KEYS = (JINNANG_BYPASS_KEYS if ENTRY_ENGINE == "JINNANG"
                      else frozenset(key for key, *_ in GATE_SWITCH_DEFS))


def read_gate_bypass():
    """Set of switched-off gates.

    還沒有設定檔時採用 DEFAULT_BYPASS（回測建議值）；
    讀取失敗時退回「全部關卡照常檢查」，這是比較安全的一邊。
    """
    try:
        doc = gcs_read_json(GATE_SWITCHES_FILE, {})
    except StorageError as exc:
        print(f"⚠️ [關卡開關讀取失敗 → 全部關卡照常檢查] {exc}", flush=True)
        return frozenset()
    bypass = doc.get("bypass") if isinstance(doc, dict) else None
    if not isinstance(bypass, list):                 # 尚未在頁面存過任何設定
        return DEFAULT_BYPASS
    return frozenset(k for k in bypass if k in GATE_SWITCH_KEYS)


def read_gate_switch_doc():
    try:
        doc = gcs_read_json(GATE_SWITCHES_FILE, {})
        return doc if isinstance(doc, dict) else {}
    except StorageError:
        return {}


def write_gate_bypass(bypass, mode_label):
    doc = {
        "bypass": sorted(k for k in bypass if k in GATE_SWITCH_KEYS),
        "mode": mode_label,
        "updated_utc": fmt_utc(),
    }
    gcs_write_text(GATE_SWITCHES_FILE, json.dumps(doc, ensure_ascii=False))
    return doc


def solo_test_status(bypass):
    """逐關測試：剛好只略過一個關卡時，回報目前測到第幾關。"""
    keys = list(bypass)
    total = len(GATE_SWITCH_KEYS)
    if len(keys) != 1 or keys[0] not in GATE_SWITCH_KEYS:
        return {"active": False, "index": None, "key": None, "title": None, "total": total}
    index = GATE_SWITCH_KEYS.index(keys[0])
    return {"active": True, "index": index + 1, "key": keys[0],
            "title": GATE_SWITCH_NAMES[keys[0]], "total": total}


def next_solo_bypass(bypass, step):
    """start / next / prev / stop -> 下一組 bypass（一次只略過一個關卡，走到底會繞回第一關）。"""
    total = len(GATE_SWITCH_KEYS)
    status = solo_test_status(bypass)
    if step == "stop":
        return frozenset()
    if step == "start" or not status["active"]:
        return frozenset({GATE_SWITCH_KEYS[0]})
    offset = 1 if step == "next" else (-1 if step == "prev" else 0)
    return frozenset({GATE_SWITCH_KEYS[(status["index"] - 1 + offset) % total]})


def detect_gate_mode(bypass):
    for key, (label, keys) in GATE_MODES.items():
        if bypass == keys:
            return label
    status = solo_test_status(bypass)
    if status["active"]:
        return f"🧪 逐關測試 {status['index']}/{status['total']}：{status['title']}"
    return "✏️ 自訂"


def bypass_note(bypass):
    if not bypass:
        return ""
    return "｜⚠️ 已略過：" + "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in bypass)


GATES_CSS = """
<style>
.gate-row { display:flex; gap:14px; align-items:flex-start; padding:16px; border-radius:12px; margin-bottom:12px;
            background:#f8f9fa; border-left:5px solid #198754; }
.gate-row.off { background:#fff4e5; border-left-color:#d97706; }
.gate-body { flex:1; min-width:0; }
.gate-title { font-weight:700; font-size:15px; margin-bottom:4px; }
.gate-state { font-size:12px; font-weight:700; padding:2px 8px; border-radius:10px; margin-left:6px; white-space:nowrap; }
.gate-state.on { background:#d1e7dd; color:#146c43; } .gate-state.off { background:#ffe5b4; color:#8a4b00; }
.gate-text { font-size:13px; color:#495057; line-height:1.55; margin-top:4px; }
.gate-risk { font-size:12px; color:#b45309; margin-top:4px; }
.param-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
.param-chip { background:#eef2ff; border-radius:8px; padding:6px 10px; font-size:12px; color:#3730a3;
              line-height:1.45; max-width:100%; overflow-wrap:anywhere; }
.param-chip b { font-family:"Courier New",monospace; font-weight:700; }
.param-chip em { display:block; font-style:normal; color:#6c757d; font-size:11px; margin-top:2px; }
.switch { position:relative; display:inline-block; width:52px; height:30px; flex-shrink:0; margin-top:2px; }
.switch input { opacity:0; width:0; height:0; }
.slider { position:absolute; cursor:pointer; inset:0; background:#d97706; border-radius:30px; transition:.2s; }
.slider:before { content:""; position:absolute; height:24px; width:24px; left:3px; top:3px; background:#fff; border-radius:50%; transition:.2s; }
.switch input:checked + .slider { background:#198754; }
.switch input:checked + .slider:before { transform:translateX(22px); }
.mode-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }
.mode-btn { width:100%; border:none; border-radius:10px; padding:16px; font-size:16px; font-weight:700; color:#fff; cursor:pointer; }
.mode-desc { font-size:12px; color:#6c757d; margin-top:6px; line-height:1.5; }
.save-bar { position:sticky; bottom:0; background:rgba(244,247,251,.96); padding:12px 0; }
</style>
"""


def _risk_cap_preview():
    """Uses the last account snapshot to show what switching off the 2% cap means."""
    snap = read_account_snapshot()
    m15 = snap.get("m15_ohlc") if isinstance(snap.get("m15_ohlc"), dict) else {}
    equity = risk_equity(snap)                                                         # [R88] 扣掉信用
    price, atr = to_float(m15.get("close")), to_float(m15.get("atr_m15"))
    currency = str(snap.get("currency") or ACCOUNT_CURRENCY_DEFAULT)
    if not equity or not price or not atr:
        return "（尚無足夠的帳戶與 ATR 資料可試算）"
    order_params = read_order_params()[0]
    sl = max(order_params["min_sl_distance"], round(atr * order_params["sl_atr_mult"], 2))
    normal, _ = PureGCPPyramidingSession.calculate_max_lots(equity, currency, price, sl)
    loose, _ = PureGCPPyramidingSession.calculate_max_lots(equity, currency, price, sl, ignore_risk=True)
    rate = FX_TO_USD.get(currency.upper()) or (ACCOUNT_TO_USD_RATE if ACCOUNT_TO_USD_RATE > 0 else None)
    if not rate:
        return "（無法換算帳戶貨幣）"
    loss_normal = normal * sl * CONTRACT_SIZE / rate
    loss_loose = loose * sl * CONTRACT_SIZE / rate
    pct_loose = loss_loose / equity * 100 if equity else 0
    return (f"以最新快照試算（淨值 {equity:,.0f} {currency}、止損 {sl:.2f} 美元）："
            f"啟用時上限 {normal:.2f} 手，整組止損約 {loss_normal:,.0f} {currency}；"
            f"停用後上限 {loose:.2f} 手，整組止損約 {loss_loose:,.0f} {currency}（淨值的 {pct_loose:.0f}%）。")


# -----------------------------------------------------------------------------
# 🔌 JSON API for the standalone gates.html  (GET/POST ?view=gates&format=json)
# -----------------------------------------------------------------------------
ADMIN_API_REQUIRE_TOKEN = _env_bool("ADMIN_API_REQUIRE_TOKEN",
                                    _env_bool("GATES_API_REQUIRE_TOKEN", True))   # writes need the webhook token
ADMIN_CORS_ORIGIN = _env_str("ADMIN_CORS_ORIGIN", _env_str("GATES_CORS_ORIGIN", "*"))  # narrow to your page origin
GATES_APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gates.html")


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": ADMIN_CORS_ORIGIN,
        "Access-Control-Allow-Headers": "Content-Type, X-Gate-Token",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Max-Age": "3600",
        "Vary": "Origin",
    }


def _json_response(payload, status=200):
    response = jsonify(payload)
    for key, value in _cors_headers().items():
        response.headers[key] = value
    return response, status


def cors_preflight():
    return _json_response({"status": "ok"})


def gates_state_payload(message=None):
    """Everything the standalone page needs, so the page holds no rule text of its own."""
    bypass = read_gate_bypass()
    doc = read_gate_switch_doc()
    state = read_gate_state()
    order_params = read_order_params()[0]
    gate_values = gate_parameter_values(order_params)
    summary_class, summary_text = gate_summary(state)
    lock = state.get("hard_lock") if hard_lock_active(state) else None
    until = to_float(lock.get("until_ts")) if isinstance(lock, dict) else None
    return {
        "status": "ok",
        "message": message,
        "server_utc": fmt_utc(),
        "gate": {
            "status": gate_status(state),
            "regime": state.get("regime"),
            "dir": state.get("dir"),
            "dir_word": DIR_WORD.get(state.get("dir")),
            "armed": bool(state.get("armed")),
            "driver": GATE_DRIVER,
            "entry_engine": ENTRY_ENGINE,
            "risk": state.get("risk") if isinstance(state.get("risk"), dict) else {},
            "long_only": LONG_ONLY,
            "trades_today": trades_today_count(state),
            "trades_max_per_day": TRAINING_MAX_PER_DAY,
            "news_lock": bool(state.get("news_lock")),
            "last_reason": state.get("last_reason"),
            "summary": summary_text,
            "summary_class": summary_class,
            "hard_lock": ({"reason": lock.get("reason"), "since_utc": lock.get("since_utc"),
                           "until_ts": until, "until_text": fmt_ny(until) if until else None}
                          if isinstance(lock, dict) else None),
        },
        "switches": {
            "engine": ENTRY_ENGINE,
            "mode": detect_gate_mode(bypass),
            "bypass": sorted(bypass),
            "updated_utc": doc.get("updated_utc"),
            # [R78] applies=False 的關卡在目前的進場引擎下【根本不會被讀到】，
            #       開關仍然存著（換回舊引擎就恢復），但頁面要標示清楚。
            "gates": [{"key": key, "title": title, "normal": normal, "skipped": skipped,
                       "risk": risk, "enabled": key not in bypass, "params": gate_values.get(key, []),
                       "applies": key in ACTIVE_BYPASS_KEYS,
                       "na_note": (None if key in ACTIVE_BYPASS_KEYS else
                                   f"錦囊 v4 不讀這個關卡（它屬於舊的加單引擎）。"
                                   f"ENTRY_ENGINE=PYRAMID 才會生效。")}
                      for key, title, normal, skipped, risk in GATE_SWITCH_DEFS],
        },
        "modes": [{"key": key, "label": label, "bypass": sorted(keys)} for key, (label, keys) in GATE_MODES.items()],
        "test": solo_test_status(bypass),
        "risk_preview": _risk_cap_preview(),
        "symbol_mismatch": broker_symbol_mismatch(),
        "always_on": GATE_ALWAYS_ON_NOTES,
        "system_params": system_parameter_values(order_params),
        "auth_required": ADMIN_API_REQUIRE_TOKEN,
    }


def handle_gates_api_get():
    return _json_response(gates_state_payload())


def _admin_token_ok(req, body):
    """Reads are open (like the other pages); writes need the token unless disabled."""
    if not ADMIN_API_REQUIRE_TOKEN:
        return True
    token = req.headers.get("X-Gate-Token") or (body or {}).get("token") or req.args.get("token")
    return isinstance(token, str) and token.strip() == GCP_SECRET_TOKEN.strip()


def handle_gates_api_post(req):
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "請求內容不是 JSON 物件"}, 400)
    if not _admin_token_ok(req, body):
        return _json_response({"status": "error", "message": "Unauthorized token"}, 403)

    op = body.get("op")
    try:
        if op == "mode":
            mode = body.get("mode")
            if mode not in GATE_MODES:
                return _json_response({"status": "error", "message": f"未知模式：{mode}"}, 400)
            label, new_bypass = GATE_MODES[mode]
            write_gate_bypass(new_bypass, label)
        elif op == "solo":                               # 逐關測試：一次只略過一個關卡
            key, step = body.get("key"), body.get("step")
            if key is not None:
                if key not in GATE_SWITCH_KEYS:
                    return _json_response({"status": "error", "message": f"未知的關卡代號：{key}"}, 400)
                new_bypass = frozenset({key})
            elif step in ("start", "next", "prev", "stop"):
                new_bypass = next_solo_bypass(read_gate_bypass(), step)
            else:
                return _json_response({"status": "error", "message": "solo 需要 key，或 step=start/next/prev/stop"}, 400)
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
        elif op == "save":
            requested = body.get("bypass")
            if not isinstance(requested, list) or not all(isinstance(k, str) for k in requested):
                return _json_response({"status": "error", "message": "bypass 必須是關卡代號字串陣列"}, 400)
            unknown = sorted(set(requested) - set(GATE_SWITCH_KEYS))
            if unknown:
                return _json_response({"status": "error", "message": f"未知的關卡代號：{'、'.join(unknown)}"}, 400)
            new_bypass = frozenset(requested)
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
        else:
            return _json_response({"status": "error", "message": "op 必須是 'mode'、'solo' 或 'save'"}, 400)
    except StorageError as exc:
        print(f"⚠️ [關卡開關 API 寫入失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "儲存失敗，設定未改變，請查看 Cloud Logging。"}, 500)

    names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in new_bypass) or "無"
    log_decision(f"🎛️ [關卡開關·獨立頁] {detect_gate_mode(new_bypass)}｜略過：{names}", key="admin")
    return _json_response(gates_state_payload("設定已儲存，下一根 M1 K 線生效。"))


def serve_gates_app():
    """Serves the standalone page from the deployed source, so one file covers both uses."""
    try:
        with open(GATES_APP_FILE, encoding="utf-8") as handle:
            return handle.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except OSError as exc:
        print(f"⚠️ [關卡開關獨立頁讀取失敗 → 改用內建頁面] {exc}", flush=True)
        return build_gates_page(None)



# -----------------------------------------------------------------------------
# 🔌 JSON API for order.html  (GET/POST ?view=order&format=json)
# -----------------------------------------------------------------------------
def order_preview(params):
    """用最新的 M15 快照試算一張 BUY 首單，顯示實際會送出的封包。"""
    snapshot = read_account_snapshot()
    m15 = snapshot.get("m15_ohlc") if isinstance(snapshot.get("m15_ohlc"), dict) else {}
    price, atr = to_float(m15.get("close")), to_float(m15.get("atr_m15"))
    live = price is not None and price > 0 and atr is not None and atr > 0
    if not live:
        price, atr = 2000.00, 6.00
    # [R78] 預覽必須跟著【實際在跑的引擎】走，否則這一頁會顯示一張不會被送出的封包。
    if ENTRY_ENGINE == "JINNANG":
        sl = max(params["min_sl_distance"], round(atr * JN_DISASTER_SL_ATR, 2))
        candidate = {"signal": "BUY", "ticker": params["symbol"], "price": price, "direction": "UP",
                     "sl_distance": sl, "tp_distance": None, "atr_m15": atr,
                     "max_lots": 0.0, "exposure": 0.0, "kind": "FIRST", "engine": "JINNANG"}
        engine_note = (f"錦囊 v4：止損 = ATR × {JN_DISASTER_SL_ATR:g}（災難停損，正常碰不到）；"
                       f"【不送 TP】—— 出場是 EA 的 {JN_HOLD_BARS * 15} 分鐘定時全平")
    else:
        sl = max(params["min_sl_distance"], round(atr * params["sl_atr_mult"], 2))
        candidate = {"signal": "BUY", "ticker": params["symbol"], "price": price, "direction": "UP",
                     "sl_distance": sl, "atr_m15": atr, "max_lots": 0.0, "exposure": 0.0, "kind": "FIRST"}
        engine_note = (f"舊加單引擎：止損 = ATR × {params['sl_atr_mult']:g}，"
                       f"止盈 = 止損 × {params['target_rrr']:g}")
    order = build_order(candidate, params)
    order["api_key"] = mask_secret(order["api_key"])
    return {
        "order": order,
        "live": live,
        "price": price,
        "atr_m15": atr,
        "sl_distance": sl,
        "engine": ENTRY_ENGINE,
        "engine_note": engine_note,
        "note": ("以最新 M15 快照試算（BUY 首單）" if live else "尚未收到 M15 快照，以 價格 2000 / ATR 6 示範"),
    }


def order_state_payload(params=None, meta=None, message=None, errors=None):
    if params is None:
        params, meta = read_order_params()
    defaults = default_order_params()
    visible = {key: (mask_secret(value) if ORDER_PARAM_KINDS[key] == "secret" else value)
               for key, value in params.items()}
    visible_defaults = {key: (mask_secret(value) if ORDER_PARAM_KINDS[key] == "secret" else value)
                        for key, value in defaults.items()}
    return {
        "status": "ok",
        "message": message,
        "errors": errors or {},
        "server_utc": fmt_utc(),
        "meta": meta or {},
        "params": visible,
        "defaults": visible_defaults,
        "fields": [{"key": key, "label": label, "kind": kind, "description": description, **limits}
                   for key, label, kind, description, limits in ORDER_PARAM_DEFS],
        "computed": computed_fields(params),
        "broker_url": BROKER_API_URL.split("?")[0] + "?…",
        "preview": order_preview(params),
        "last_sent": read_last_order(),
        "auth_required": ADMIN_API_REQUIRE_TOKEN,
    }


def handle_order_api_get():
    return _json_response(order_state_payload())


def _merge_submitted_params(submitted):
    """空字串的 secret 欄位代表『不修改』，其餘欄位照收。"""
    current = read_order_params()[0]
    merged = dict(current)
    for key in ORDER_PARAM_KEYS:
        if key not in submitted:
            continue
        value = submitted[key]
        if ORDER_PARAM_KINDS[key] == "secret" and (value is None or str(value).strip() == ""):
            continue
        merged[key] = value
    return merged


def handle_order_api_post(req):
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "請求內容不是 JSON 物件"}, 400)
    op = body.get("op")

    if op == "preview":                                   # 唯讀試算，不寫入、不需要權杖
        submitted = body.get("params")
        if not isinstance(submitted, dict):
            return _json_response({"status": "error", "message": "params 必須是物件"}, 400)
        clean, errors = validate_order_params(_merge_submitted_params(submitted))
        return _json_response(order_state_payload(clean, {"source": "preview", "updated_utc": None},
                                                  "預覽（尚未儲存）", errors))

    if not _admin_token_ok(req, body):
        return _json_response({"status": "error", "message": "Unauthorized token"}, 403)

    try:
        if op == "save":
            submitted = body.get("params")
            if not isinstance(submitted, dict):
                return _json_response({"status": "error", "message": "params 必須是物件"}, 400)
            clean, errors = validate_order_params(_merge_submitted_params(submitted))
            if errors:                                     # 有任何欄位無效就整批不寫入
                return _json_response({"status": "error", "message": "欄位有誤，設定未變更。",
                                       "errors": errors}, 400)
            write_order_params(clean)
        elif op == "reset":
            clear_order_params()
            clean = default_order_params()
        else:
            return _json_response({"status": "error", "message": "op 必須是 'preview'、'save' 或 'reset'"}, 400)
    except StorageError as exc:
        print(f"⚠️ [送單參數寫入失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "儲存失敗，設定未變更，請查看 Cloud Logging。"}, 500)

    log_decision(f"🧾 [送單參數] {'還原為環境變數預設' if op == 'reset' else '已更新'}｜"
                 f"{clean['symbol']} {clean['size']:.2f} 手｜{clean['account_type']}｜"
                 f"SL=ATR×{clean['sl_atr_mult']}（最小 {clean['min_sl_distance']}）｜TP={clean['target_rrr']}R",
                 key="admin")
    params, meta = read_order_params()
    return _json_response(order_state_payload(params, meta,
                                              "已還原為環境變數預設。" if op == "reset" else "已儲存，下一張訂單生效。"))


ORDER_APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "order.html")


def serve_order_app():
    try:
        with open(ORDER_APP_FILE, encoding="utf-8") as handle:
            return handle.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except OSError as exc:
        print(f"⚠️ [送單參數頁讀取失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "order.html 不存在於部署內容中"}, 500)

# -----------------------------------------------------------------------------
# 🗒️ 錦囊：執行單 + 九十筆訓練進度表
#     兩頁都是靜態 HTML；進度表的紀錄存在 GCS，換裝置／換瀏覽器也看得到。
#         執行單      ?view=jinnang_sheet
#         進度表      ?view=jinnang_tracker
#         進度表資料  ?view=jinnang&format=json   （GET 讀、POST 寫）
#     兩頁互相有連結，頁首的分頁列切換。
# -----------------------------------------------------------------------------
_JINNANG_DIR = os.path.dirname(os.path.abspath(__file__))
JINNANG_SHEET_FILE = os.path.join(_JINNANG_DIR, "jinnang_sheet.html")
JINNANG_TRACKER_FILE = os.path.join(_JINNANG_DIR, "jinnang_tracker.html")
JINNANG_STATE_FILE = "jinnang_training.json"      # GCS 物件名
JINNANG_SLOTS = 90


def _serve_static_html(path, label):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except OSError as exc:
        print(f"⚠️ [{label}讀取失敗] {exc}", flush=True)
        return _json_response({"status": "error",
                               "message": f"{os.path.basename(path)} 不存在於部署內容中"}, 500)


def serve_jinnang_sheet():
    return _serve_static_html(JINNANG_SHEET_FILE, "錦囊執行單")


def serve_jinnang_tracker():
    return _serve_static_html(JINNANG_TRACKER_FILE, "錦囊進度表")


def _jinnang_clean(raw):
    """只收白名單欄位、長度固定 90；格式不對的那一格當成空的。"""
    text_keys = ("date", "dir", "inTime", "outTime", "px", "pnl")
    rows = raw if isinstance(raw, list) else []
    out = []
    for i in range(JINNANG_SLOTS):
        row = rows[i] if i < len(rows) else None
        if not isinstance(row, dict):
            out.append(None)
            continue
        rec = {k: str(row.get(k, ""))[:32] for k in text_keys}
        for k in ("c1", "c2", "c3"):
            rec[k] = bool(row.get(k))
        used = any(rec[k] for k in text_keys) or rec["c1"] or rec["c2"] or rec["c3"]
        out.append(rec if used else None)
    return out


def handle_jinnang_api_get():
    try:
        doc = gcs_read_json(JINNANG_STATE_FILE, None)
    except StorageError as exc:
        print(f"⚠️ [錦囊紀錄讀取失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "讀取失敗"}, 500)
    doc = doc if isinstance(doc, dict) else {}
    return _json_response({"status": "ok",
                           "trades": _jinnang_clean(doc.get("trades")),
                           "updated_utc": doc.get("updated_utc")})


def handle_jinnang_api_post(req):
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "請求內容不是 JSON 物件"}, 400)
    trades = _jinnang_clean(body.get("trades"))
    stamp = fmt_utc()
    try:
        gcs_write_text(JINNANG_STATE_FILE,
                       json.dumps({"trades": trades, "updated_utc": stamp}, ensure_ascii=False))
    except StorageError as exc:
        print(f"⚠️ [錦囊紀錄寫入失敗] {exc}", flush=True)
        return _json_response({"status": "error", "message": "寫入失敗"}, 500)
    done = sum(1 for t in trades if t)
    ok = sum(1 for t in trades if t and t["c1"] and t["c2"] and t["c3"])
    print(f"🗒️ [錦囊] 已記 {done}/{JINNANG_SLOTS} 筆，其中合規 {ok}", flush=True)
    return _json_response({"status": "ok", "trades": trades, "updated_utc": stamp})



def build_gates_page(msg):
    bypass = read_gate_bypass()
    doc = read_gate_switch_doc()
    state = read_gate_state()
    status = gate_status(state)
    summary_class, summary_text = gate_summary(state)
    mode_label = detect_gate_mode(bypass)

    banners = {
        "saved": ("#d4edda", "#155724", "✅ 設定已儲存，下一根 M1 K 線生效。"),
        "mode": ("#d4edda", "#155724", "✅ 模式已套用，下一根 M1 K 線生效。"),
        "test": ("#e7f1ff", "#084298", "🧪 逐關測試已更新，下一根 M1 K 線生效。"),
        "error": ("#f8d7da", "#721c24", "❌ 儲存失敗，設定未改變，請查看 Cloud Logging。"),
    }
    banner = ""
    if msg in banners:
        bg, fg, text = banners[msg]
        banner = f"<div class='banner' style='background:{bg}; color:{fg};'>{text}</div>"

    order_params = read_order_params()[0]
    gate_values = gate_parameter_values(order_params)

    def param_chips(items):
        if not items:
            return ""
        chips = "".join(
            f"<span class='param-chip'><b>{esc(i['name'])}</b> = {esc(i['value'])}"
            + (f"<em>{esc(i['note'])}</em>" if i["note"] else "") + "</span>"
            for i in items)
        return f"<div class='param-chips'>{chips}</div>"

    rows = ""
    for key, title, normal, skipped, risk in GATE_SWITCH_DEFS:
        is_on = key not in bypass
        extra = param_chips(gate_values.get(key, []))
        if key == "risk_cap":
            extra += f"<div class='gate-text'>{esc(_risk_cap_preview())}</div>"
        rows += (
            f"<div class='gate-row {'' if is_on else 'off'}'>"
            f"<label class='switch'><input type='checkbox' name='on_{key}' value='1' {'checked' if is_on else ''}>"
            f"<span class='slider'></span></label>"
            f"<div class='gate-body'><div class='gate-title'>{esc(title)}"
            f"<span class='gate-state {'on' if is_on else 'off'}'>{'✅ 檢查中' if is_on else '⚠️ 已略過'}</span></div>"
            f"<div class='gate-text'><b>啟用：</b>{esc(normal)}</div>"
            f"<div class='gate-text'><b>略過：</b>{esc(skipped)}</div>"
            f"<div class='gate-risk'>{esc(risk)}</div>{extra}</div></div>"
        )

    def mode_card(key, color, desc, confirm_text):
        label = GATE_MODES[key][0]
        onsubmit = f" onsubmit=\"return confirm('{confirm_text}');\"" if confirm_text else ""
        return (f"<form method='POST' action='?view=gates'{onsubmit}>"
                f"<input type='hidden' name='op' value='mode'><input type='hidden' name='mode' value='{key}'>"
                f"<button type='submit' class='mode-btn' style='background:{color};'>{label}</button>"
                f"<div class='mode-desc'>{desc}</div></form>")

    relaxed_names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in GATE_MODES["relaxed"][1])
    aggressive_extra = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS
                                 if k in GATE_MODES["aggressive"][1] and k not in GATE_MODES["relaxed"][1])
    recommended_names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in DEFAULT_BYPASS)
    modes = (
        "<div class='mode-grid'>"
        + mode_card("recommended", "#0f62fe",
                    f"略過：{esc(recommended_names)}。依 8.5 個月回測，樣本內外都最穩定。",
                    "套用回測建議的預設狀態？")
        + mode_card("relaxed", "#d97706", f"略過：{esc(relaxed_names)}。", "確認套用寬鬆模式？")
        + mode_card("aggressive", "#dc3545", f"寬鬆模式再加上略過：{esc(aggressive_extra)}。",
                    "激進模式會同時略過倉位上限、新聞風控與 AI 覆核，實盤風險很高。確認套用？")
        + mode_card("strict", "#198754", "全部關卡恢復檢查（預設）。", "")
        + "</div>"
    )

    updated = esc(doc.get("updated_utc") or "—")
    always_on = "".join(f"<li>{esc(note)}</li>" for note in GATE_ALWAYS_ON_NOTES)

    system_blocks = "".join(
        f"<h3 style='font-size:14px; margin:18px 0 8px; color:var(--muted);'>{esc(group['group'])}</h3>"
        + param_chips(group["items"])
        for group in system_parameter_values(order_params))

    test = solo_test_status(bypass)
    test_line = (f"目前測試第 {test['index']} / {test['total']} 關：{esc(test['title'])}"
                 f"（其餘 {test['total'] - 1} 關維持檢查）"
                 if test["active"] else "目前不在逐關測試（略過的關卡不是剛好一個）")

    def solo_form(fields, label, color, confirm=""):
        hidden = "".join(f"<input type='hidden' name='{k}' value='{v}'>" for k, v in fields.items())
        onsubmit = f" onsubmit=\"return confirm('{confirm}');\"" if confirm else ""
        return (f"<form method='POST' action='?view=gates' style='display:inline-block; margin:4px;'{onsubmit}>"
                f"<input type='hidden' name='op' value='solo'>{hidden}"
                f"<button type='submit' class='mode-btn' style='background:{color}; width:auto; padding:12px 18px; "
                f"font-size:14px;'>{label}</button></form>")

    first_name = esc(GATE_SWITCH_NAMES[GATE_SWITCH_KEYS[0]])
    test_buttons = (
        solo_form({"step": "start"}, f"▶️ 開始測試（只略過「{first_name}」）", "#0f62fe",
                  f"開始逐關測試：只略過「{first_name}」，其餘關卡維持檢查。確認？")
        + solo_form({"step": "prev"}, "⬅️ 上一關", "#6c757d")
        + solo_form({"step": "next"}, "➡️ 下一關", "#0f62fe")
        + solo_form({"step": "stop"}, "⏹️ 結束測試（全部恢復檢查）", "#198754")
    )
    jump_options = "".join(
        f"<option value='{key}'{' selected' if test['key'] == key else ''}>{i}. {esc(GATE_SWITCH_NAMES[key])}</option>"
        for i, key in enumerate(GATE_SWITCH_KEYS, 1))
    test_jump = (
        "<form method='POST' action='?view=gates' style='display:inline-block; margin:4px;' "
        "onsubmit=\"return confirm('直接跳到這一關？該關卡會被略過，其餘維持檢查。');\">"
        "<input type='hidden' name='op' value='solo'>"
        f"<select name='key' style='padding:11px 12px; border:1px solid #dee2e6; border-radius:8px; font-size:14px;'>{jump_options}</select> "
        "<button type='submit' class='mode-btn' style='background:#d97706; width:auto; padding:12px 18px; font-size:14px;'>跳到這一關</button></form>"
    )
    body = f"""
    <div class='nav'><div class='brand'><div class='brand-logo'>{BRAND_LOGO_SVG}</div><h1 class='page-title'>🎛️ 關卡開關（內建版）</h1></div>
      {page_nav("gates_app", extra=[("?view=gates_app", "🆕 獨立版")])}</div>
    {banner}
    <div class='section' style='text-align:center;'>
      <div class='muted' style='font-weight:600;'>目前模式</div>
      <div style='font-size:24px; font-weight:800; margin:8px 0;'>{esc(mode_label)}</div>
      <div class='muted' style='font-size:13px;'>略過 {len(bypass)} / {len(GATE_SWITCH_KEYS)} 個關卡｜最後更新：{updated} UTC</div>
      <div style='margin-top:12px; font-size:14px;'>電閘：<b>{status}</b>｜<span class='{summary_class}'>{esc(summary_text)}</span></div>
      <div class='muted' style='font-size:12px; margin-top:6px;'>硬鎖（TARGET_HIT、RISK_HIT、緊急鎖死）不受本頁影響，請到控制台解除。</div>
    </div>

    <div class='section'><h2>⚡ 一鍵模式</h2>{modes}</div>

    <div class='section'><h2>🧪 逐關測試模式</h2>
      <p class='muted' style='font-size:12px;'>從「全部檢查中」出發，一次只略過一個關卡、其餘維持檢查，逐關往下走，
      用來確認是哪一關擋住訊號。走到最後一關後會繞回第一關。</p>
      <div class='gate-row' style='border-left-color:#0f62fe;'><div class='gate-body'>
        <div class='gate-title'>{test_line}</div>
        <div class='gate-risk'>⚠️ 這是實盤：被略過的那一關在測試期間不會保護你，請測完按「結束測試」。</div>
      </div></div>
      <div>{test_buttons}</div>
      <div style='margin-top:8px;'>{test_jump}</div>
    </div>

    <div class='section'><h2>🔧 逐關調整</h2>
      <p class='muted' style='font-size:12px;'>綠色＝該關卡照常檢查；橙色＝略過。調整後按最下方「儲存」。</p>
      <form method='POST' action='?view=gates'>
        <input type='hidden' name='op' value='save'>
        {rows}
        <div class='save-bar'><button type='submit' class='mode-btn' style='background:#0f62fe;'>💾 儲存逐關設定</button></div>
      </form>
    </div>

    <div class='section'><h2>⚙️ 其餘系統參數</h2>
      <p class='muted' style='font-size:12px;'>這些不屬於單一關卡，但會影響下單。標「送單參數頁」的可即時修改，
      其餘是環境變數，改了要重新部署。</p>
      {system_blocks}
    </div>

    <div class='section'><h2>🔒 本頁無法略過的檢查</h2>
      <div class='gate-text'>以下是資料或安全前提，略過後系統無法正確計算方向、止損或持倉，因此不提供開關：</div>
      <ul class='gate-text'>{always_on}</ul>
    </div>
    """
    return html_page("關卡開關頁面 - 智能諸葛亮", body, head_extra=GATES_CSS)


def handle_gates_post(req):
    form = req.form
    op = form.get("op")
    try:
        if op == "mode" and form.get("mode") in GATE_MODES:
            label, keys = GATE_MODES[form.get("mode")]
            write_gate_bypass(keys, label)
            new_bypass, msg = keys, "mode"
        elif op == "solo":                               # 逐關測試：一次只略過一個關卡
            key, step = form.get("key"), form.get("step")
            if key in GATE_SWITCH_KEYS:
                new_bypass = frozenset({key})
            elif step in ("start", "next", "prev", "stop"):
                new_bypass = next_solo_bypass(read_gate_bypass(), step)
            else:
                return redirect("?view=gates")
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
            msg = "test"
        elif op == "save":
            new_bypass = frozenset(k for k in GATE_SWITCH_KEYS if form.get(f"on_{k}") != "1")
            write_gate_bypass(new_bypass, detect_gate_mode(new_bypass))
            msg = "saved"
        else:
            return redirect("?view=gates")
    except StorageError as exc:
        print(f"⚠️ [關卡開關寫入失敗] {exc}", flush=True)
        return redirect("?view=gates&msg=error")

    names = "、".join(GATE_SWITCH_NAMES[k] for k in GATE_SWITCH_KEYS if k in new_bypass) or "無"
    log_decision(f"🎛️ [關卡開關] {detect_gate_mode(new_bypass)}｜略過：{names}", key="admin")
    return redirect(f"?view=gates&msg={msg}")


# =============================================================================
# 🧹 重置：把歷史紀錄清空，用這個版本重新開始
# -----------------------------------------------------------------------------
# 刻意「分組」而不是一鍵全清——不同紀錄清掉的後果差很多，有些會讓系統停擺一小時。
# 設定檔（送單參數、關卡開關）不在任何一組裡，重置不會動到你調好的設定。
# =============================================================================
RESET_GROUPS = [
    ("ai", "AI 訓練資料", [SFT_DATASET_FILE, PENDING_SIGNALS_FILE], False,
     "歷史虧損教訓與待配對訊號。清掉後 AI 的 few-shot 會是空的，要重新累積。"
     "舊版格式的資料本來就無法使用，清掉可讓「教訓 N 條」這個數字從乾淨的基準開始。"),
    ("rules", "AI 規則庫", [TRADING_RULES_FILE], False,
     "trading_rules.txt 的內容。"),
    ("logs", "決策日誌與封包紀錄", [DECISION_LOG_FILE, M1_VERDICT_LOG_FILE, WEBHOOK_LOG_FILE, LAST_ORDER_FILE], False,
     "只是顯示用的紀錄，清掉不影響交易邏輯。"),
    ("cache", "新聞日曆快取", [NEWS_CACHE_FILE], False,
     "下次需要時會自動重抓。"),
    ("trades", "交易績效紀錄", [TRADE_HISTORY_FILE], True,
     "⚠️ 累計已實現損益、實盤勝率、期望值會全部歸零，且<b>無法復原</b>。"
     "MT5 那邊的歷史不受影響，但這個系統算出來的績效統計會從零開始。"
     "<br>✅ 從 DEMO 換到實盤時<b>應該清</b>——模擬單的損益混進實盤統計會讓勝率與期望值失真，"
     "而期望值會回頭影響建議的 TP 倍數。"),
    ("market", "M1／M15 行情快取", [M1_HISTORY_FILE, M15_HISTORY_FILE], True,
     f"⚠️ 清掉後要重新累積約 {MIN_M1_BARS} 根 M1 K 線（<b>約一小時</b>）才能再次開閘交易。"),
    ("state", "執行狀態", [GATE_STATE_FILE, PYRAMID_STATE_FILE, ACCOUNT_FILE], True,
     "⚠️ 電閘回到 LOCK、加單基準價清空、帳戶快照清除"
     "（EA 下次心跳會重建）。若此刻有未平倉部位，加單基準會遺失。"),
]
RESET_GROUP_MAP = {key: (label, files, danger, desc) for key, label, files, danger, desc in RESET_GROUPS}
RESET_KEEPS = [("送單參數", ORDER_PARAMS_FILE), ("關卡開關設定", GATE_SWITCHES_FILE)]
RESET_CONFIRM_WORD = "RESET"

# 常見情境的預設勾選組合，避免手動勾錯——特別是誤勾行情快取會白等一小時。
RESET_PRESETS = {
    "live": ("🔁 DEMO → 實盤", {"ai", "trades", "logs", "state"},
             "換帳戶用。demo 的損益、訊號與狀態全部清掉，實盤統計從零開始。"
             f"<b>不含行情快取</b>——K 線是商品行情，demo 與實盤看到的 XAUUSD 是同一份，"
             f"清掉只會白等 {MIN_M1_BARS} 分鐘重新累積。"),
    "ai": ("🧠 只重置 AI 訓練資料", {"ai", "logs"},
           "保留交易績效，只把 AI 的教訓與日誌歸零。舊版格式的 SFT 資料無法使用時用這個。"),
}


def perform_reset(keys):
    """把選到的檔案寫成空字串——所有讀取端都把「空」當成預設值，等同清除。

    用覆寫而不是刪除：少一種權限與 generation 的失敗模式，行為也比較好預期。"""
    cleared, failed = [], []
    for key in keys:
        label, files, _danger, _desc = RESET_GROUP_MAP[key]
        for name in files:
            try:
                gcs_write_text(name, "")
                cleared.append(name)
            except StorageError as exc:
                print(f"⚠️ [重置失敗] {name}：{exc}", flush=True)
                failed.append(name)
    labels = "、".join(RESET_GROUP_MAP[k][0] for k in keys)
    log_event(f"🧹 [重置] 已清空：{labels}｜檔案 {len(cleared)} 個"
              + (f"｜失敗 {len(failed)} 個" if failed else ""),
              severity="WARNING" if failed else "INFO", component="admin",
              reset_groups=list(keys), cleared=cleared, failed=failed)
    log_decision(f"🧹 [管理員重置] 已清空：{labels}"
                 + (f"（{len(failed)} 個檔案失敗）" if failed else ""), key="admin")
    return cleared, failed


def build_reset_page(msg=None, error=None, preset=None):
    banner = ""
    if msg:
        banner = f"<div class='level-box' style='border-left:4px solid #198754;'>{esc(msg)}</div>"
    elif error:
        banner = f"<div class='level-box' style='border-left:4px solid #dc3545;'>{esc(error)}</div>"

    preselected = RESET_PRESETS.get(preset, (None, set(), ""))[1]
    preset_html = "".join(
        f"<a href='?view=reset&preset={esc(key)}' class='level-box' "
        f"style='display:block; margin-bottom:8px; text-decoration:none; "
        f"border-left:4px solid {'#0f62fe' if preset == key else '#c7ccd1'};'>"
        f"<b>{label}</b>{' ✔️ 已套用' if preset == key else ''}"
        f"<div class='card-desc' style='margin-top:4px;'>{desc}</div></a>"
        for key, (label, _keys, desc) in RESET_PRESETS.items())

    rows = ""
    danger_tag = " <span style='color:#dc3545; font-weight:700;'>（高風險）</span>"
    for key, label, files, danger, desc in RESET_GROUPS:
        colour = "#dc3545" if danger else "#6c757d"
        file_list = "、".join(f"<code>{esc(f)}</code>" for f in files)
        checked = " checked" if key in preselected else ""
        rows += (f"<div class='level-box' style='border-left:4px solid {colour}; margin-bottom:8px;'>"
                 f"<label style='display:flex; gap:10px; align-items:flex-start; cursor:pointer;'>"
                 f"<input type='checkbox' name='g_{esc(key)}' value='1' style='margin-top:4px;'{checked}>"
                 f"<span><b>{esc(label)}</b>{danger_tag if danger else ''}"
                 f"<div class='card-desc' style='margin-top:4px;'>{desc}</div>"
                 f"<div class='card-desc' style='margin-top:4px;'>{file_list}</div>"
                 f"</span></label></div>")

    # 先告訴你「即將刪掉什麼」——盲按按鈕是這種頁面最容易出事的地方。
    try:
        trade_count = len(risk_manager_session.read_trades())
        realised = sum(to_float(t.get("profit"), 0.0) for t in risk_manager_session.read_trades())
        trades_note = (f"目前有 <b>{trade_count}</b> 筆已結算交易，"
                       f"累計 <b>{realised:+,.2f} {esc(ACCOUNT_CURRENCY_DEFAULT)}</b>")
    except Exception as exc:
        trades_note = f"交易紀錄讀取失敗：{esc(str(exc)[:80])}"
    try:
        account_type = str(read_order_params()[0].get("account_type") or "?")
    except Exception:
        account_type = "?"
    account_html = (f"<span style='color:#dc3545; font-weight:700;'>🔴 real（實盤）</span>"
                    if account_type == "real" else
                    f"<span style='color:#d97706; font-weight:700;'>🟡 {esc(account_type)}</span>"
                    + ("　⚠️ 送單參數仍是 demo，換實盤前記得到送單參數頁改成 real。"
                       if account_type == "demo" else ""))

    keeps = "、".join(f"<code>{esc(f)}</code>（{esc(name)}）" for name, f in RESET_KEEPS)
    body = f"""
    <div class='nav'><div class='brand'><div class='brand-logo'>{BRAND_LOGO_SVG}</div>
      <h1 class='page-title'>🧹 重置歷史紀錄</h1></div>{page_nav("reset")}</div>
    {banner}
    <div class='section'>
      <p class='muted' style='font-size:13px;'>
        用這個版本重新開始：勾選要清空的紀錄。<b>這個動作無法復原</b>，請先確認沒有正在等待配對的交易。
      </p>
      <div class='level-box' style='border-left:4px solid #0f62fe; margin-bottom:12px;'>
        <div class='card-title'>目前狀態</div>
        <div style='margin-top:4px;'>{trades_note}<br>下單模式：{account_html}</div>
      </div>
      <div class='level-box' style='border-left:4px solid #198754; margin-bottom:12px;'>
        ✅ <b>不會被清掉的東西</b>：{keeps}。你調好的設定會原封不動保留。
        <div class='card-desc' style='margin-top:6px;'>
          另外，重置這個動作本身一定會留下一筆稽核紀錄（即使你清掉決策日誌），
          不會讓破壞性操作沒有痕跡。
        </div>
      </div>
      <div class='card-title' style='margin-bottom:6px;'>常見情境（點一下自動勾好）</div>
      {preset_html}
      <form method='POST' action='?view=reset'>
        <div class='card-title' style='margin:14px 0 6px;'>逐項確認</div>
        {rows}
        <div class='level-box' style='margin-top:12px;'>
          <div class='card-title'>管理權杖</div>
          <input type='password' name='token' placeholder='WEBHOOK_SECRET_TOKEN'
                 style='width:100%; padding:8px; margin-top:4px;' autocomplete='off'>
        </div>
        <div class='level-box' style='margin-top:8px; border-left:4px solid #dc3545;'>
          <div class='card-title'>輸入 <code>{RESET_CONFIRM_WORD}</code> 以確認</div>
          <input type='text' name='confirm' placeholder='{RESET_CONFIRM_WORD}'
                 style='width:100%; padding:8px; margin-top:4px;' autocomplete='off'>
        </div>
        <button type='submit' style='margin-top:12px; padding:10px 18px; font-weight:700;
                background:#dc3545; color:#fff; border:none; border-radius:6px; cursor:pointer;'>
          🧹 清空勾選的紀錄
        </button>
      </form>
    </div>"""
    return html_page("重置歷史紀錄 - 智能諸葛亮", body)


def handle_reset_post(req):
    form = req.form
    if ADMIN_API_REQUIRE_TOKEN:
        token = form.get("token")
        if not (isinstance(token, str) and token.strip() == GCP_SECRET_TOKEN.strip()):
            return build_reset_page(error="管理權杖不正確，沒有清除任何東西。")
    if (form.get("confirm") or "").strip().upper() != RESET_CONFIRM_WORD:
        return build_reset_page(error=f"請在確認欄輸入 {RESET_CONFIRM_WORD}，沒有清除任何東西。")

    keys = [key for key, *_ in RESET_GROUPS if form.get(f"g_{key}") == "1"]
    if not keys:
        return build_reset_page(error="沒有勾選任何項目，沒有清除任何東西。")

    cleared, failed = perform_reset(keys)
    labels = "、".join(RESET_GROUP_MAP[k][0] for k in keys)
    if failed:
        return build_reset_page(error=f"已清空 {len(cleared)} 個檔案，但有 {len(failed)} 個失敗："
                                      f"{'、'.join(failed)}。請查看 Cloud Logging。")
    note = "　接下來要等 M1 K 線重新累積才能開閘。" if "market" in keys else ""
    return build_reset_page(msg=f"✅ 已清空「{labels}」，共 {len(cleared)} 個檔案。{note}")


def handle_get(req):
    view = req.args.get("view", "welcome")
    action = req.args.get("action")
    if view == "gates" and req.args.get("format") == "json":     # standalone gates.html reads state
        return handle_gates_api_get()
    if view == "gates_app":                                      # standalone gates.html, served here
        return serve_gates_app()
    if view == "order" and req.args.get("format") == "json":     # standalone order.html reads params
        return handle_order_api_get()
    if view == "order_app":                                      # standalone order.html, served here
        return serve_order_app()
    if view == "jinnang" and req.args.get("format") == "json":   # 進度表讀取訓練紀錄
        return handle_jinnang_api_get()
    if view == "jinnang_sheet":                                  # 錦囊執行單
        return serve_jinnang_sheet()
    if view == "jinnang_tracker":                                # 錦囊九十筆進度表
        return serve_jinnang_tracker()
    if view == "futu" and req.args.get("format") == "json":      # [R94] 最新 Futu 行情（&symbol= 指定代號）
        return handle_futu_api_get(req.args.get("symbol"))
    if view == "archive" and req.args.get("format") == "json":   # [R95] 按日封存，給每日彙整拉取
        return handle_archive_api_get(req)
    if view in ("futu_range", "hsi_range"):                      # [R97] 即月期貨一年波幅與最新 OHLC
        return handle_futu_range_get(req)
    if view == "es_range":                                       # [R127] ES 標普 500 期貨，同一套程式
        return handle_futu_range_get(req, default_symbol=ES_SYMBOL)
    if view == "info":
        return build_info_page()
    if view == "reset":
        return build_reset_page(preset=req.args.get("preset"))
    if view == "gates":
        return build_gates_page(req.args.get("msg"))
    if view == "dashboard":
        if action in ("auto", "open"):          # "open" kept for old bookmarks  [R29]
            try:
                clear_hard_lock()
                log_decision("🟢 [管理員] 解除硬鎖，恢復自動模式。", key="gate")
                return redirect("?view=dashboard&msg=auto")
            except StorageError as exc:
                print(f"⚠️ [電閘寫入失敗] {exc}", flush=True)
                return redirect("?view=dashboard&msg=error")
        if action == "lock":
            try:
                set_hard_lock("管理員緊急鎖死", None)
                log_decision("🔒 [管理員] 啟動緊急硬鎖。", key="gate")
                return redirect("?view=dashboard&msg=locked")
            except StorageError as exc:
                print(f"⚠️ [電閘寫入失敗] {exc}", flush=True)
                return redirect("?view=dashboard&msg=error")
        return build_dashboard_page(req.args.get("msg"))
    return render_welcome_page()


# =============================================================================
# 📈 Entry point
# =============================================================================
def log_event(message, severity="INFO", **fields):
    """One structured log line. Cloud Run turns JSON on stdout into jsonPayload
    with a real severity, so it is visible under the default "Info" filter."""
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False, default=str), flush=True)


def _payload_summary(payload):
    m1 = payload.get("m1_ohlc") if isinstance(payload.get("m1_ohlc"), dict) else {}
    return {
        "action": payload.get("action"),
        "status_signal": payload.get("status"),
        "symbol": payload.get("symbol"),
        "equity": payload.get("equity"),
        "buy_lots": payload.get("buy_lots"),
        "sell_lots": payload.get("sell_lots"),
        "m1_time": m1.get("time"),
        "is_new_bar": m1.get("is_new_bar"),
        "ticket": payload.get("ticket"),
        "profit": payload.get("profit"),
    }


def _response_info(response):
    body, code = (response[0], response[1]) if isinstance(response, tuple) else (response, 200)
    if hasattr(body, "get_json"):
        body = body.get_json(silent=True)
    return code, (body or {}).get("status") if isinstance(body, dict) else None


def _dispatch_post(payload):
    action = payload.get("action")
    if action == "trade_result":
        return handle_trade_result(payload)

    token = payload.get("token")
    token_ok = isinstance(token, str) and token.strip() == GCP_SECRET_TOKEN.strip()

    if action in ("check_gate", "close_gate") or "net_lots" in payload or "equity" in payload:
        # MT5 heartbeats carrying equity are trusted, same as v11.
        return handle_heartbeat(payload, can_trade=("equity" in payload) or token_ok)

    if not token_ok:
        return jsonify({"status": "error", "message": "Unauthorized token"}), 403
    if action == "update_levels":
        return jsonify({"status": "success", "message": "TV levels received but intentionally ignored."}), 200
    if action == "futu_data":                        # [R94] 本地 Futu OpenD 推上來的行情
        return handle_futu_data(payload)
    return jsonify({"status": "ignored", "message": "No handler for this payload"}), 200


@functions_framework.http
def receive_tradingview_signal(request):
    if request.method == "OPTIONS":                  # CORS preflight from the standalone page
        return cors_preflight()
    if request.method == "GET":
        return handle_get(request)
    if request.args.get("view") == "gates":          # posts from the gate switch pages
        if request.args.get("format") == "json" or (request.content_type or "").startswith("application/json"):
            return handle_gates_api_post(request)
        return handle_gates_post(request)
    if request.args.get("view") == "order":          # posts from the order parameter page
        return handle_order_api_post(request)
    if request.args.get("view") == "jinnang":        # 錦囊進度表寫入訓練紀錄
        return handle_jinnang_api_post(request)
    if request.args.get("view") == "reset":          # 重置頁的表單（需權杖＋確認字串）
        return handle_reset_post(request)

    payload = parse_payload(request)
    if payload is None:
        log_event("📥 [收到封包] 無法解碼的請求內容", severity="WARNING", component="webhook")
        return jsonify({"status": "error", "message": "Invalid bytes coding"}), 400

    summary = _payload_summary(payload)
    log_event(f"📥 [收到封包] action={summary['action']} status={summary['status_signal']} "
              f"buy={summary['buy_lots']} sell={summary['sell_lots']} m1={summary['m1_time']}",
              component="webhook", direction="in", **summary)
    if payload.get("action") != "futu_data":        # [R94] Futu 封包大且每 5 分鐘一次，另存
        webhook_log_session.save_payload(payload)

    started = now_ts()
    try:
        response = _dispatch_post(payload)
    except Exception as exc:
        log_event(f"💥 [處理異常] {type(exc).__name__}: {exc}", severity="ERROR", component="webhook",
                  action=summary["action"])
        raise
    code, status = _response_info(response)
    log_event(f"📤 [回應] HTTP {code} {status} ({int((now_ts() - started) * 1000)} ms)",
              severity="INFO" if code < 500 else "ERROR", component="webhook", direction="out",
              action=summary["action"], http_status=code, result=status)
    return response


# ---------------------------------------------------------------------------
# [R84] WSGI fallback so `gunicorn main:app` also works.
#
# GCP buildpacks pick the server by whether GOOGLE_FUNCTION_TARGET is set at
# build time.  Set -> `functions-framework --target=...` (normal path, the
# object below is never touched).  Unset -> `gunicorn main:app`, which used to
# abort with "Failed to find attribute 'app' in 'main'" and return 503 to the
# EA even though the module itself had imported cleanly.  Exposing `app` makes
# the same source deploy correctly either way.
# ---------------------------------------------------------------------------
def _build_wsgi_app():
    from flask import Flask, request as flask_request

    wsgi = Flask(__name__)

    def _entry(_path=""):
        return receive_tradingview_signal(flask_request)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    wsgi.add_url_rule("/", "entry_root", _entry, methods=methods)
    wsgi.add_url_rule("/<path:_path>", "entry_any", _entry, methods=methods)
    return wsgi


app = _build_wsgi_app()
