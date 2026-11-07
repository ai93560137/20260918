# 🌌 936 AI 揀入場（IDEAS #1003）：影子同實倉開關

使用者 11-07：「AI 入場, 用另一個戶口, 真倉比對」，經總指揮：「A。開新 idea，隨時真倉」。
- 規矩照舊：影子 30 張，照 #1003 預先登記標準達標，總指揮 dry-run，使用者喺總指揮親口批，先可以開實倉。
- 程式預設全關，部署唔會改任何行為。

## 做法
1. 931 心跳行規則學生。rev15 出區時，`ai_entry.ask` 叫 AI 揀入場價、SL、TP，或者唔做。
   - 方向跟 rev15，入場價只准等回調，離出區價最多 15 美元。
   - SL 離入場 2–15 美元。計劃有效 30 分鐘。
   - 計劃寫入 GCS `xau/sig/aientry/`。
2. 影子成績由 `research/student_offline/ai_entry_forward.py` 計：用券商 M1，同一批出區嘅 E6S4 並排。
3. 實倉用 magic 936：EA 開一張圖用 magic 936，心跳會按 magic 分流到呢本書，指令 id 前綴 `i`。
   - 現價去到 AI 入場價先市價入，固定 0.01 手，一次一張。
   - 唔開新倉嘅情況：停線 C、control 唔係 RUN、階梯 Ⓑ／Ⓓ、EA 唔准交易、數據封鎖。

## env（zhuge-xau-sig；預設）
| env | 預設 | 作用 |
|---|---|---|
| `SIG_AIENTRY` | 0 | **1＝開影子**（問 AI、記錄計劃；每次約 1 個 Opus 調用，rev15 最多每個鐘 1 次） |
| `SIG_AIENTRY_RULES` | rev15 | 邊條規則學生出區先問 |
| `SIG_AIENTRY_MODEL` | 同 `CLAUDE_MODEL` | AI 模型 |
| `SIG_AIENTRY_MAGIC` | 936 | 實倉 magic |
| `SIG_AIENTRY_ACCOUNT` | （空） | 實倉戶口號碼（使用者揀；空＝唔核） |
| `SIG_AIENTRY_LOTS` | 0.01 | 固定手數 |
| `SIG_AIENTRY_TTL_MIN`／`_MAX_DIST`／`_SL_MIN`／`_SL_MAX` | 30／15／2／15 | 計劃有效時間同價位限制 |
| `SIG_AIENTRY_HWM_START`／`_STOP_R`／`_DD_R` | 空／8／10 | 停線 C（開實倉日起計） |
| `SIG_AIENTRY_EXECUTE` | 0 | **936 落實倉開關**；要同 `XAU_EXECUTE=1` 一齊先生效 |

## 步驟
1. **合併 PR，部署 zhuge-xau-sig**：總指揮 dry-run，使用者批。程式預設全關，部署後行為唔變。
2. **開影子**：改 env `SIG_AIENTRY=1`，總指揮 dry-run，使用者批。之後每週週報報前向進度。
3. **實倉**：要等影子達標，再由使用者批。
   - 喺另一個戶口開 XAUUSD 圖，EA magic 936，`InpBotMagics` 加 `936`（計入戶口總階梯）。
   - 改 env：`SIG_AIENTRY_ACCOUNT=<戶口>`、`SIG_AIENTRY_HWM_START=<開倉日>`、`SIG_AIENTRY_EXECUTE=1`、`XAU_EXECUTE=1`。

## 提議（要使用者確認）
- **magic 936**：訊號書 931 加 5。921–926、931–935 都已經用咗。
- **戶口 …63**：921、922、926、932 喺呢個戶口，而家全部影子，冇倉；933 喺 …69，咁就符合「另一個戶口」。
