# 🌌 天覆陣 轉真倉清單（2026-10-23，使用者喺總指揮工作階段：「天覆陣真倉可以開始」）

> 規矩不變：真倉戶口號碼、本金、權杖**只放 env／GCS control.json**，唔入 repo、對話、日誌。每個 env set／部署由總指揮 dry-run → 使用者批 → `--yes`。
> 本檔係清單同現況，唔係已完成紀錄；完成一項就喺「狀態」欄打 ✅ 並寫證據位置。

## 0. 現況（10-23 09:10 UTC 讀取核實）

| 項 | 現況 | 證據 |
|---|---|---|
| 三個服務 | zhuge-xau 00028-n2x（`XAU_HOLD_RULES=on`）、zhuge-eurusd 00013-hlj、zhuge-xau-sig 00022-g6l；全部 `XAU_EXECUTE=1`、`XAU_ACCOUNT=`demo 登入號、`XAU_TEST_CMDS=0`、日蝕 PAUSE −20%／STOP 停用 | `gcp_agent.py --profile … status` |
| 權杖 | 三個服務 `WEBHOOK_SECRET_TOKEN` 已設，但值＝EA 預設 `123456`（公開 repo，handoff §6.4b；使用者 10-21 確認 demo 階段接受） | `xau/mt5/TianfuExecutor.mq5` 第 31 行 |
| control.json | 三個都 mode RUN、`principal_hkd` 已設（demo 用數）、**`live_account` 空** | `gcp_agent.py cat --object xau/control.json`（只睇欄位有冇） |
| 戶口總階梯 | 程式已上線（EA v0.35+ `InpBotMagics` 合計、服務 scope=account）；**TEST_PLAN §4 0b「兩產品各一張、合計穿 PAUSE 線 → 兩服務同時停開新倉」未有紀錄**，TEST_RESULTS 只有 10-20 單產品測試 8（本金暫改 100 → −27.8% → STOP＋平倉，scope=own） | `xau/mt5/TEST_RESULTS.md` 測試 8；`ACCOUNT_LADDER.md` §「轉真倉前置」 |
| demo 成績（10-21 起） | 921：32 張 12 賺 2 保本 18 蝕，累計 −154.55 HKD（今日 +53）；932 跟單：3 張全 TP1，+96.74；931 S1：0 張；922 EURUSD：demo 落單、紙上標準（IDEAS #28）未達 | `TEST_RESULTS.md`、狀態 JSON |
| 預先登記門檻 | 921 期望值仍負；932 3／30；931 冇樣本；922 未達 #28 | `IDEAS.md` #123／#126／#28、`TEST_PLAN.md` |

## 1. 邊幾本轉（使用者定；天覆陣建議）

| magic | 服務 | 內容 | 建議 | 理由 |
|---|---|---|---|---|
| 932 | zhuge-xau-sig | 跟單 CTC＋DAN，0.01 手，TP1 走，原 SL（伺服器端） | **第一批** | 結構最簡單、唔靠 Opus、3 張全勝；風險＝每張原 SL（CTC 約 21 美元、DAN 6） |
| 921 | zhuge-xau | Opus 自主 XAUUSD，0.01 手，H on | 第一批（使用者 10-21「隨時轉真倉」） | 期望值仍負（−154.55／32 張），但使用者已決定；0.01 手每張風險 ≤ `XAU_MAX_SL_USD`，日蝕 −20% 停開新倉 |
| 931 | zhuge-xau-sig | S1：Opus 參考 DAN 訊號，0.01 手 | 可以同 921 一齊（使用者 10-21「訊號書都要落單」） | 0 張樣本；開倉條件比 921 嚴（要引用有效訊號），風險唔大過 921 |
| 922 | zhuge-eurusd | Opus 自主 EURUSD，0.01 手 | **建議留 demo** | 紙上 ≥30 筆標準未達；外匯 0.01 手每 pip 0.1 美元，風險細但期望未證 |
| 學徒／學生 | zhuge-xau-sig | 影子 | 唔變 | 唔落單 |

同一個 MT5 戶口四個 magic 共用「天覆陣所有產品合計」階梯（RISK_LADDER §6c）。使用者手動 0.1 手單同其他 EA 唔計入。

## 2. 前置（全部做齊先切）

| # | 項目 | 誰做 | 點做 | 狀態 |
|---|---|---|---|---|
| P1 | **換私人權杖** | 總指揮＋使用者 | 總指揮生成一個隨機權杖（唔入對話／repo），`--profile xau env set WEBHOOK_SECRET_TOKEN=<新>`、`--profile eurusd …`、`--profile xausig …`（三個同一個值）；使用者四張圖表 EA（921、922、931、932）`InpToken` 填同一個值。**次序**：先改 EA 再改服務會令心跳 403 幾分鐘，建議先服務後 EA，中間心跳 403 屬預期（`gcp_agent conditional_env` 會提醒） | ☐ |
| P2 | **總階梯 0b 驗證（demo）** | 總指揮（put control.json）＋天覆陣核實 | demo 戶口：XAUUSD 同 EURUSD 各開一張（可以等自然開倉，或者 `XAU_TEST_CMDS=1` 用 test_cmd 開；完事要關返 0），總指揮將兩個 control.json `principal_hkd` 暫改到令合計浮虧穿 −20% → 下一根 M1 兩個服務同時 PAUSE（`ladder.level` B、「停開新倉」、Telegram）；還原本金後下根 M1 自動解。證據寫入 TEST_RESULTS | ☐ |
| P3 | **真倉戶口號碼** | 使用者→總指揮 | 使用者確認用邊個真錢戶口（有多過一個）；總指揮寫入三個 control.json `live_account`（私人）；之後 env `XAU_ACCOUNT=<真戶口>`（三個服務同一個） | ☐ |
| P4 | **LTC 跟單主帳** | 使用者 | 確認 Local Trade Copier 仍然卸載，或已排除 magic 921／931／932（否則天覆陣嘅單會被複製到從帳） | ☐ |
| P5 | **真倉本金** | 使用者→總指揮 | 三個 control.json `principal_hkd` 改成真倉分配本金（同一個數，私人）；日蝕 −20% PAUSE 線＝本金 ×20%；`equity_peak` 會隨本金重設 | ☐ |
| P6 | **真戶口 MT5 準備** | 使用者 | 真戶口 MT5：四張 XAUUSD 圖表（EURUSD 留 demo 就三張）掛 EA v0.37，`InpMagic` 921／931／932（922 如轉），`InpDryRun=true` 先；「允許 WebRequest 的 URL」加 `https://zhuge-xau-1056099871997.europe-west1.run.app` 同 `https://zhuge-xau-sig-1056099871997.europe-west1.run.app`（EURUSD 加 zhuge-eurusd）；`InpBotMagics` 預設已包 921–925、931–935；`InpLedgerStart` 設為轉真倉當日（累計由 0 起計）；`InpMaxLots` 0.01 或 0.02（第二道鎖） | ☐ |
| P7 | **demo EA 處理** | 使用者 | demo 戶口嘅 EA 全部卸載或 `InpDryRun=true`；否則兩個戶口都會送心跳，服務只收 `XAU_ACCOUNT` 嗰個，另一個 `ignored`（日誌會見） | ☐ |
| P8 | **緊急停機驗證** | 總指揮＋天覆陣 | 轉真倉前喺 demo 試一次：總指揮 put control.json `mode=STOP set_by=user` → 下一根 M1 服務排 `close\|all`、唔問 Claude；還原 RUN。另外確認 EA `InpDryRun=true` 幾秒內令指令唔執行（10-20 測試 1–9 已證） | ☐（10-20 測試 5/6 已做過 STOP／PAUSE，轉真倉前再做一次） |
| P9 | **POSITIONS.md 登記列** | 總指揮 | 開真倉前登記（magic、產品、手數、戶口＝「天覆陣真倉戶口」唔寫號碼）；配對規則 | ☐ |
| P10 | **Telegram 通知** | 天覆陣核實 | 開倉／平倉／階梯變化有 Telegram（demo 已有）；轉真倉第一張要使用者睇住 | ☐ |

## 3. 切換當日次序（P1–P10 完成後）

1. 總指揮 dry-run → 使用者批 → `--yes`：
   - `--profile xau env set XAU_ACCOUNT=<真戶口> XAU_LOTS=0.01 XAU_MAX_LOTS=0.01`
   - `--profile xausig env set XAU_ACCOUNT=<真戶口> SIG_FOLLOW_LOTS=0.01`（931 用 `XAU_LOTS`，932 用 `SIG_FOLLOW_LOTS`）
   - 922 如轉：`--profile eurusd env set XAU_ACCOUNT=<真戶口> XAU_LOTS=0.01`；留 demo 就唔改（仍收 demo 心跳）
2. 使用者：真戶口 EA `InpDryRun=false`（先 932／931 圖表，再 921）；demo EA 卸載。
3. 天覆陣核實（讀取）：三個服務 `account_id`＝真戶口（JSON 有，唔會寫入 repo）、`ea_dry_run=false`、`trade_allowed` 全 true、`live_positions` 來源 EA、`ladder.scope=account`、principal 已設；第一次心跳日誌冇 403／ignored。
4. 第一張單 0.01 手，使用者睇住；TEST_RESULTS 另開「真倉」表（只寫 HKD 盈虧，唔寫權益）。
5. 之後：日蝕 −20% PAUSE（RISK_LADDER §6c）、使用者人手 Ⓒ／Ⓓ；每日 05:05 小結照報；真倉成績同 demo 分開計。

## 4. 回退（任何一步出事）
- 最快：真戶口 EA `InpDryRun=true`（幾秒）或卸載 EA。
- 服務：`env set XAU_EXECUTE=0`，或 `rollback --to <上一修訂>`。
- 緊急平倉：control.json `mode=STOP set_by=user`（下一根 M1 排 `close|all`）；MT5 人手平倉亦可。
