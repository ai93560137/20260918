# 🌌 天覆陣 階段 B 測試記錄（demo，2026-10-20）

> 由天覆陣工作階段按 `xau/mt5/TEST_PLAN.md` §3 逐項核實；指令由總指揮 `put` 執行。時間 UTC。冇真倉戶口號碼、冇真本金。

| # | 時間 UTC | 指令 id | 指令 | EA ack | ticket | 結果 |
|---|---|---|---|---|---|---|
| 1 (第一次) | 13:34:11 | f8695f6e | open BUY 0.01 sl=4108.82 tp=4133.82 | ok=false「auto trading disabled by client」<1s | 0 | 流程通；MT5 Algo Trading 關住 → 使用者開掣後重做 |
| 1 (第二次) | 13:37:11 | f94d85e6 | open BUY 0.01 sl=4111.26 tp=4136.26 | ok=false「auto trading disabled by client」(10027) <1s | 0 | 使用者話已開 Algo Trading 仍被擋 → 要查 EA 屬性「允許算法交易」／笑臉 |
| 1 ✅ | 13:41:11 | 824bcc24 | open BUY 0.01 sl=4116.68 tp=4141.68 | ok=true「done at 4127.69」1s | 361223393 | 13:42:11 心跳 positions 有 ticket、entry 4127.69、sl/tp 齊；opened_ts=13:41:11 UTC（時差修正正確）；使用者要勾 EA 屬性「允許算法交易」先通 |
| 2 ✅ | 13:43:11 | 3c3c59fb | open BUY 0.01 sl=0（no_sl） | ok=false「no SL」1s | 0 | 冇新單，持倉仍只 361223393 |
| 3 ✅ | 13:44:11 | 9630ad00 | modify all sl=4120 tp=4141.68 | ok=true「done;」1s | — | 13:45:11 心跳 positions sl=4120.0、tp=4141.68 |
| 4 ✅ | 13:45:11 | 3b57f01b | close all | ok=true「done at 4130.40;」1s | 361223393 平 | 13:46:11 心跳 positions=[]、floating 0、daily_pnl=realized_total=+21.27 HKD |
| 5 ✅(服務側) | 14:50:53 | a22a6152 | open BUY 0.01 sl=4133.71 tp=4158.71 resend | ok=true「done at 4141.09」<1s | 361405614 | resend_until 14:53:52：14:51:52／14:52:52／14:53:52 三個心跳重帶同一 id，MT5 由始至終只有一張；EA 專家分頁「↩️ 重複 id」行待使用者確認。EA v0.32 trade_allowed 全 true |
| 7 ✅ | 14:56:53 | 95ad6fee | control.json STOP(user) → 服務自動排 close all | ok=true「done at 4141.76;」<1s | 361405614 平 | 14:57:52 positions=[]；STOP 期間冇問 Claude；之後 PAUSE 還原。今日已實現 +26.53 HKD |
| 8 ✅ | 15:12:52 | 987cf479 | 本金暫改 100；t8 open BUY 0.01 @4143.13（1b8ee860, ticket 361420917）；浮虧 −54.31 HKD → 日蝕 (26.53−54.31)/100 = −27.8% ≤ −6% | 階梯 STOP(ladder, auto_reset_day 2026-10-21)＋排 close → ack「done at 4136.30」1s | 361420917 平 | Telegram 🛑；副作用：高水位回撤 99.5% 警報（equity_peak 仍係原本金水平）、cum_loss_above=true（還原本金後下根 M1 自清）。待還原 principal／PAUSE |
| 9 ✅ | 15:22:53 | a66fd6fa / ccf50c68 | XAU_MAX_HOLD_MIN=5（修訂 00011-nt5）；t9 open BUY 0.01 @4135.73 | 15:28:53 日誌「⏱ 最長持倉 5 分鐘到，排 close」→ ack「done at 4135.55;」<1s | 361462087 開→平 | 開倉後第 6 分鐘（滿 5 分鐘後首根 M1）自動平；15:29:52 positions=[] |
