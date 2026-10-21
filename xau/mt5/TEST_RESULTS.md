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
| 6a ✅ | 15:48:44 | 882de041 | MT5 15:38:52 關；15:40:26 put t6a；MT5 重開首個心跳 15:48:44 consume＋open（距 put 498 秒，險過 600 秒 TTL） | ok=true「done at 4133.02」1s | 361489991 | 只開一張；修訂 00012-znn（MAX_HOLD 已還原 1440） |
| 6a 平倉 | 15:50:44 | deea8411 | close all | ok=true「done at 4133.57;」 | 361489991 平 | 15:51:44 positions=[] |
| 6b ✅ | 16:11:06 | t6b | MT5 15:53:44 關；15:54:44 put；16:10 後重開 → 首個心跳 16:11:06 consume（相隔 982 秒 > 600） | 唔排：result=error「ts missing or older than 600s」 | — | positions=[]、pending=[]，冇單 |
| 10 ⏭ | — | — | 真倉戶口掛 dry-run EA 被 ignored | 總指揮決定唔做（唔想使用者喺真戶口掛 EA）；XAU_ACCOUNT 過濾有單元測試（tests/test_xau.py「非 XAU_ACCOUNT 嘅心跳 → ignored」） | — | 轉真倉前 XAU_ACCOUNT 改真倉戶口時，demo EA 心跳會被 ignored，等於實地驗證 |

## 小結
- 1–9 全部通過（第 5 嘅 EA「↩️ 重複 id」行由使用者確認；第 10 跳過）。指令→EA→ack 每次 ≤1 秒。
- 待做：XAU_TEST_CMDS=0 還原；control.json RUN；Claude 自己喺 demo 開／平 ≥3 張（M15 夠 20 根先開始）。
- 轉真倉前置：見 TEST_PLAN §4（LTC 停用確認、真倉戶口號碼、EA InpDryRun、XAU_ACCOUNT）。

## Claude 自主開平（階段 B 最後一項，目標 ≥3 張；修訂 00021-92x，mode RUN）

| # | 開倉 UTC | 方向 | 入場 | 初始 SL／TP | 調整 | 出場 | 結果（HKD，含成本） | Claude 理由（摘要） |
|---|---|---|---|---|---|---|---|---|
| C1 | 10-21 01:07 | SELL 0.01（c3207fcc，ack ok） | 4109.22 | 4114.60／4100.00（5.4／9.2 美元） | 01:08 UPDATE_STOP sl→4112.20（f935b16c，ack ok） | 01:13–01:14 伺服器端 SL 4112.20 觸發 | −28.25 | 連續兩根 M1 收穿 4111.5 區間底、M15 由 4130 向下；反抽入區間即認輸。出場後 Claude 唔追單，等跌穿 4106／企返 4113 |
| C2 | 10-21 05:30 | BUY 0.01（c95108dd，ack ok） | 4128.05 | 4121.40／4138.00（6.65／9.95 美元） | — | 05:38 Claude 主動 CLOSE（2f5eb1d8，ack ok），價約 4123.9 | −39.63 | M15 收穿 4106–4126 橫行上緣＋0.25 ATR；8 分鐘後跌返入區間，判突破失敗，未掂 SL 先細蝕離場 |

觀察：指令→ack 每次 ≤1 秒；伺服器端 SL 正常執行，服務下一個心跳見 positions=[]；止損後冇報復式再入場。之後價格反彈到 4124（突破失敗），Claude 全程 HOLD。
