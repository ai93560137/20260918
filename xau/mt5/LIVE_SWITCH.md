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

## 0b. 使用者決定（10-23，經總指揮）
- **四本全部轉真倉**：921、922 EURUSD、931 S1、932 跟單，全部 0.01 手起；學生照影子。（天覆陣建議 922 留 demo，使用者決定全轉。）
- **權杖「keep 123456」**：使用者明確揀唔換（總指揮喺 RISK_LADDER 記低係使用者決定同風險）。因此加 §0c 減險。

## 0c. 權杖公開嘅減險（程式已入 PR #299；真倉前要開）
入口盤點（`xau/main.py entry()`）：

| 入口 | 要乜先過 | 可以做到乜 | 減險 |
|---|---|---|---|
| GET `/`、`?format=json` | 無 | 讀狀態 | **已改**：`account_id`／`xau_account` 只露尾 2 位；`pending_cmds`／跟單 `pending`／`orders` 嘅指令 id 遮罩（`id=fe******`）→ 唔知真戶口號、唔知未完成指令 id |
| heartbeat（check_gate／heartbeat） | 權杖 ＋ **`account`＝`XAU_ACCOUNT`** | 假 K 線／假持倉／假權益 → 影響決策同階梯；收到 `cmd_text` | 真戶口號只放 env／control.json，公開 JSON 已遮罩 → 攻擊者估唔到 `account`；日誌會見「非 XAU_ACCOUNT 嘅心跳，略過」 |
| cmd_ack | 權杖 ＋ id | 冒認回報令服務以為指令已執行（EA 之後唔再收到） | **已改**：帶 `account` 就要同 `XAU_ACCOUNT` 一致（EA v0.38 回報加登入號）；`XAU_ACK_REQUIRE_ACCOUNT=1` 時冇 `account` 嘅回報一律忽略（**真倉開 1**；demo 舊 EA 用 0）；id 已遮罩所以估唔到 |
| test_cmd（HTTP／GCS） | 權杖 ＋ `XAU_TEST_CMDS=1` | 直接排 open／close／modify | **保持 `XAU_TEST_CMDS=0`**（三個服務而家都係 0；真倉後唔再開） |
| action=tg_signal（舊入口，zhuge-xau／eurusd） | 權杖 | 建立「待確認」訊號、發 Telegram 畀使用者按 ✅ | 唔會直接落單（要 Telegram callback 嘅 `TG_SIGNAL_WEBHOOK_SECRET` 標頭＋白名單）；zhuge-xau／eurusd 未設 `TG_SIGNAL_*` env → 入口等於無效。訊號書服務只收 HMAC 簽名入口（`TG_SIGNAL_INGEST_SECRET`，另一個私人密鑰） |
| Telegram callback `?tg=signal` | `TG_SIGNAL_WEBHOOK_SECRET` 標頭＋chat 白名單 | — | 未設 env → 唔生效 |
| control.json（PAUSE／STOP／本金） | GCS 寫入權限（服務帳戶） | — | 唔經 HTTP |

剩餘風險（使用者接受）：知道真戶口登入號嘅人可以用公開權杖送假心跳影響決策。登入號唔入 repo／對話／公開 JSON，只喺 env 同 control.json。

真倉前要加嘅 env（總指揮 dry-run）：`XAU_ACK_REQUIRE_ACCOUNT=1`（三個服務；要先換 EA v0.38，否則舊 EA 嘅回報會被忽略 → 指令重發）。

## 0d. 10-23 17:5x HKT 切換（使用者喺總指揮工作階段：「即刻切真倉，唔等 0b」）
- 總指揮已套用：三個服務 `XAU_ACCOUNT=<真戶口>`、`XAU_LOTS=0.01`、`XAU_MAX_LOTS=0.01`、xau-sig `SIG_FOLLOW_LOTS=0.01`；`XAU_ACK_REQUIRE_ACCOUNT=1`（四張 demo EA 已換 v0.38，使用者確認）。修訂 zhuge-xau 00031-vjw（回退 00030-sn7）、zhuge-eurusd 00016-ckn（00015-hxx）、zhuge-xau-sig 00025-4b7（00024-h5g）。09:56 UTC 起 demo 心跳被略過。
- **0b（兩產品總階梯測試）使用者決定跳過**；階梯程式本身同 demo 一樣，只係冇做兩產品同時觸發嘅演示。
- 次序：真戶口 EA `InpDryRun=true` 掛四張 → 天覆陣核實第一個真心跳 → 總指揮改三個 control.json `principal_hkd`（真戶口權益 100%）＋POSITIONS.md → 核實 ladder 用新本金 → 使用者 932／931 → 921 → 922 逐張 `InpDryRun=false` → 第一張單核實 cmd_ack 帶 account。
- 前置狀態：P1 權杖 keep（§0c 減險已部署）；P2 0b 跳過；P3 真戶口已入 env（control.json `live_account` 由總指揮填）；P4 LTC 使用者確認已卸載；P5 本金等真心跳後填；P6／P7 使用者做（下面教學）；P8 緊急停機沿用 10-20 測試；P9 總指揮寫；P10 Telegram 照舊。

## 1. 邊幾本轉（使用者定；天覆陣建議）

| magic | 服務 | 內容 | 建議 | 理由 |
|---|---|---|---|---|
| 932 | zhuge-xau-sig | 跟單 CTC＋DAN，0.01 手，TP1 走，原 SL（伺服器端） | **第一批** | 結構最簡單、唔靠 Opus、3 張全勝；風險＝每張原 SL（CTC 約 21 美元、DAN 6） |
| 921 | zhuge-xau | Opus 自主 XAUUSD，0.01 手，H on | 第一批（使用者 10-21「隨時轉真倉」） | 期望值仍負（−154.55／32 張），但使用者已決定；0.01 手每張風險 ≤ `XAU_MAX_SL_USD`，日蝕 −20% 停開新倉 |
| 931 | zhuge-xau-sig | S1：Opus 參考 DAN 訊號，0.01 手 | 可以同 921 一齊（使用者 10-21「訊號書都要落單」） | 0 張樣本；開倉條件比 921 嚴（要引用有效訊號），風險唔大過 921 |

> **2026-10-30 使用者（經總指揮）**：先講「931 留畀規則學生」，之後改口「**不用停**」——931 S1 照舊可以落真倉（參考 7713），`SIG_DECIDE=1` 維持；規則學生過 IDEAS #146 門檻（11-11 初判、11-25 正式）後再決定 931 點用。R353 加咗 `SIG_S1_OPEN`（預設開）做將來停 S1 嘅開關——**要停只可以用 SIG_S1_OPEN=0，唔好用 SIG_DECIDE=0**（規則學生靠 931 心跳推動，會一齊停）。
| 922 | zhuge-eurusd | Opus 自主 EURUSD，0.01 手 | **建議留 demo** | 紙上 ≥30 筆標準未達；外匯 0.01 手每 pip 0.1 美元，風險細但期望未證 |
| 學徒／學生 | zhuge-xau-sig | 影子 | 唔變 | 唔落單 |

同一個 MT5 戶口四個 magic 共用「天覆陣所有產品合計」階梯（RISK_LADDER §6c）。使用者手動 0.1 手單同其他 EA 唔計入。

## 2. 前置（全部做齊先切）

| # | 項目 | 誰做 | 點做 | 狀態 |
|---|---|---|---|---|
| P1 | ~~換私人權杖~~ **使用者 10-23 決定 keep 123456** → 改為 §0c 減險：真倉前 `XAU_ACK_REQUIRE_ACCOUNT=1`（三服務）＋EA v0.38 | 總指揮＋使用者 | ~~總指揮生成一個隨機權杖（唔入對話／repo），`--profile xau env set WEBHOOK_SECRET_TOKEN=<新>`、`--profile eurusd …`、`--profile xausig …`（三個同一個值）；使用者四張圖表 EA（921、922、931、932）`InpToken` 填同一個值。**次序**：先改 EA 再改服務會令心跳 403 幾分鐘，建議先服務後 EA，中間心跳 403 屬預期（`gcp_agent conditional_env` 會提醒） | ☐ |
| P2 | **總階梯 0b 驗證（demo）** | 總指揮（put control.json）＋天覆陣核實 | demo 戶口：XAUUSD 同 EURUSD 各開一張（可以等自然開倉，或者 `XAU_TEST_CMDS=1` 用 test_cmd 開；完事要關返 0），總指揮將兩個 control.json `principal_hkd` 暫改到令合計浮虧穿 −20% → 下一根 M1 兩個服務同時 PAUSE（`ladder.level` B、「停開新倉」、Telegram）；還原本金後下根 M1 自動解。證據寫入 TEST_RESULTS | ☐ |
| P3 | **真倉戶口號碼** | 使用者→總指揮 | 使用者確認用邊個真錢戶口（有多過一個）；總指揮寫入三個 control.json `live_account`（私人）；之後 env `XAU_ACCOUNT=<真戶口>`（三個服務同一個） | ☐ |
| P4 | **LTC 跟單主帳** | 使用者 | 確認 Local Trade Copier 仍然卸載，或已排除 magic 921／931／932（否則天覆陣嘅單會被複製到從帳） | ☐ |
| P5 | **真倉本金** | 使用者→總指揮 | 三個 control.json `principal_hkd` 改成真倉分配本金（同一個數，私人）；日蝕 −20% PAUSE 線＝本金 ×20%；`equity_peak` 會隨本金重設 | ☐ |
| P6 | **真戶口 MT5 準備** | 使用者 | 真戶口 MT5：三張 XAUUSD 圖表（921／931／932）＋一張 EURUSD（922）掛 **EA v0.38**（cmd_ack 帶登入號；PR #299），`InpMagic` 921／931／932（922 如轉），`InpDryRun=true` 先；「允許 WebRequest 的 URL」加 `https://zhuge-xau-1056099871997.europe-west1.run.app` 同 `https://zhuge-xau-sig-1056099871997.europe-west1.run.app`（EURUSD 加 zhuge-eurusd）；`InpBotMagics` 預設已包 921–925、931–935；`InpLedgerStart` 設為轉真倉當日（累計由 0 起計）；`InpMaxLots` 0.01 或 0.02（第二道鎖） | ☐ |
| P7 | **demo EA 處理** | 使用者 | demo 戶口嘅 EA 全部卸載或 `InpDryRun=true`；否則兩個戶口都會送心跳，服務只收 `XAU_ACCOUNT` 嗰個，另一個 `ignored`（日誌會見） | ☐ |
| P8 | **緊急停機驗證** | 總指揮＋天覆陣 | 轉真倉前喺 demo 試一次：總指揮 put control.json `mode=STOP set_by=user` → 下一根 M1 服務排 `close\|all`、唔問 Claude；還原 RUN。另外確認 EA `InpDryRun=true` 幾秒內令指令唔執行（10-20 測試 1–9 已證） | ☐（10-20 測試 5/6 已做過 STOP／PAUSE，轉真倉前再做一次） |
| P9 | **POSITIONS.md 登記列** | 總指揮 | 開真倉前登記（magic、產品、手數、戶口＝「天覆陣真倉戶口」唔寫號碼）；配對規則 | ☐ |
| P10 | **Telegram 通知** | 天覆陣核實 | 開倉／平倉／階梯變化有 Telegram（demo 已有）；轉真倉第一張要使用者睇住 | ☐ |

## 2b. P2 總階梯 0b 具體步驟（10-23 天覆陣出；總指揮執行、天覆陣讀取核實）

**原理**：階梯用 EA 嘅 `bots_daily_pnl`（伺服器日 UTC+3 已實現，天覆陣全部 magic）＋`bots_floating`；PAUSE 線 −20%（紐約 18:00–02:00 ET 夜盤 ×1.5 ＝ −30%）。
兩個難處：(a) 今日已實現正數（+143）縮本金都穿唔到 → 要揀 **伺服器換日（21:00 UTC）之後、未有任何平倉** 嘅時段，日蝕只剩浮動；(b) 累計線 25% 一定同時穿（`bots_realized_total` −62）而且程式**先檢查累計**（edge 觸發），會令 control.reason 寫成累計——**解法**：改本金嗰次 put 同時寫 `"cum_loss_above": true`（edge 模式要由 false→true 先觸發，預設 true 就唔會觸發），淨返日蝕線。

| 步 | 誰 | 做乜 |
|---|---|---|
| 0 | — | **時間**：週日 10-25 22:05 UTC（週一 06:05 HKT）起，黃金同外匯都開市、伺服器日剛換（daily 已實現＝0）、未有 921／922 平倉。夜盤線 −30%。10-23（五）21:00 UTC 後休市，做唔到 |
| 1 | 總指揮 | `--profile xau env set XAU_TEST_CMDS=1`、`--profile eurusd env set XAU_TEST_CMDS=1`（dry-run → 批 → --yes；兩個新修訂） |
| 2 | 總指揮 | 落兩個檔（`ts` 填 `date +%s`，10 分鐘內有效）：<br>`xau/test_cmd.json`：`{"id":"ob1","ts":<epoch>,"op":"open","side":"BUY","lots":0.01,"sl":<現價−30>,"tp":<現價+30>}`<br>`fx/eurusd/test_cmd.json`：`{"id":"ob2","ts":<epoch>,"op":"open","side":"SELL","lots":0.01,"sl":<現價+0.0100>,"tp":<現價−0.0100>}`<br>（SL／TP 放遠，免測試中被掃；lots 0.01 夠，浮動主要係點差 ≈ −2.5／−0.8 HKD） |
| 3 | 天覆陣 | 下一個心跳日誌「🧪 test_cmd 排指令」→「📨 指令回報 ok=True」；JSON `live_positions` 兩個服務各一張、`ladder.scope=account`、`ladder.daily_pnl_hkd`（＝bots_daily_pnl＋bots_floating，兩個服務數字應一樣）。**等到 daily_pnl_hkd 係負數**（通常即刻，點差） |
| 4 | 總指揮 | 兩個 control.json **同一分鐘** put：`principal_hkd` ＝ `round(|daily_pnl_hkd| / 0.5, 1)`（令 pct ≈ −50%，穿 −30% 有餘；例 daily −3.3 → 本金 6.6）、`"cum_loss_above": true`（壓住累計線）、其他欄位照舊（mode RUN、set_by user）。記低原本金 |
| 5 | 天覆陣 | 下一根 M1：兩個服務 JSON `control.mode=PAUSE`、`control.set_by=ladder`、`control.reason` 含「**當日虧損 −xx% ≤ −30% → 停開新倉（換日自動重開）**」（唔係「累計虧損」）、`ladder.level=B`、`ladder.reasons` 同一句；日誌「ℹ️ 本金已更新，高水位重設」＋ PAUSE；Telegram 兩條「⏸ 當日虧損 …」（xau、eurusd 各一）。兩個服務觸發時間差 ≤ 1 分鐘＝**0b 通過**。記 TEST_RESULTS |
| 6 | 總指揮 | 還原：兩個 control.json put `principal_hkd`＝原值、`mode:"RUN"`、`set_by:"user"`、`reason:"0b 測試完畢還原"`、`cum_loss_above:false`、刪 `auto_reset_day`（日蝕 PAUSE 本來要等紐約 17:00 換日先自動重開，所以要人手 RUN）。再落 `{"id":"ob3","ts":…,"op":"close"}` 兩個檔平測試倉 |
| 7 | 總指揮 | `--profile xau env set XAU_TEST_CMDS=0`、`--profile eurusd env set XAU_TEST_CMDS=0`（關測試入口；步 1→7 控制喺 15 分鐘內） |
| 8 | 天覆陣 | 核實：JSON `test_cmds=false`、`live_positions=[]`、`control.mode=RUN`、`ladder.level=A`、高水位已按原本金重設；`xau/test_cmd.json` 兩檔 `consumed` 已寫 |

副作用（已知，10-20 測試 8 見過）：本金縮細期間「高水位回撤 ≥10%／20%」提示會響一次（只提示）；還原本金後下根 M1 自動重設。測試倉期間 Opus／H 規則可能移止損或平倉（屬正常），步 6 用 close 收尾即可。

## 3. 切換當日次序（P1–P10 完成後）

1. 總指揮 dry-run → 使用者批 → `--yes`：
   - `--profile xau env set XAU_ACCOUNT=<真戶口> XAU_LOTS=0.01 XAU_MAX_LOTS=0.01 XAU_ACK_REQUIRE_ACCOUNT=1`
   - `--profile xausig env set XAU_ACCOUNT=<真戶口> XAU_LOTS=0.01 SIG_FOLLOW_LOTS=0.01 XAU_ACK_REQUIRE_ACCOUNT=1`（931 用 `XAU_LOTS`，932 用 `SIG_FOLLOW_LOTS`）
   - `--profile eurusd env set XAU_ACCOUNT=<真戶口> XAU_LOTS=0.01 XAU_ACK_REQUIRE_ACCOUNT=1`（使用者 10-23：922 都轉）
2. 使用者：真戶口 EA `InpDryRun=false`（先 932／931 圖表，再 921）；demo EA 卸載。
3. 天覆陣核實（讀取）：三個服務 `account_id`＝真戶口（JSON 有，唔會寫入 repo）、`ea_dry_run=false`、`trade_allowed` 全 true、`live_positions` 來源 EA、`ladder.scope=account`、principal 已設；第一次心跳日誌冇 403／ignored。
4. 第一張單 0.01 手，使用者睇住；TEST_RESULTS 另開「真倉」表（只寫 HKD 盈虧，唔寫權益）。
5. 之後：日蝕 −20% PAUSE（RISK_LADDER §6c）、使用者人手 Ⓒ／Ⓓ；每日 05:05 小結照報；真倉成績同 demo 分開計。

## 4. 回退（任何一步出事）
- 最快：真戶口 EA `InpDryRun=true`（幾秒）或卸載 EA。
- 服務：`env set XAU_EXECUTE=0`，或 `rollback --to <上一修訂>`。
- 緊急平倉：control.json `mode=STOP set_by=user`（下一根 M1 排 `close|all`）；MT5 人手平倉亦可。
