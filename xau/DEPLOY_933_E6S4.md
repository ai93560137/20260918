# 🌌 933 rev15 E6S4 上實倉＋高水位硬停線 C：部署計劃（下星期）

使用者 11-07：「下星期部署」→ 揀「rev15 E6S4 上 933 實倉」同硬停線「C 策略 R 線＋戶口 20%」。
規矩（使用者 11-05）：影子 30 張達標（#160 rev15 新結構 66 張 +0.241R PF 3.45 ✅）、固定細注、一次只上一條；**部署同改 env 要總指揮 dry-run＋使用者喺總指揮親口批**。

## 1. 程式（呢個 PR；預設全部關，部署程式唔會改任何行為）
| 改動 | env（預設） | 作用 |
|---|---|---|
| 933 結構覆寫 | `SIG_STUDENT_STRUCT`（空） | `rev15:6,2,4,1` → 以出區時現價為基準：入場中位退 6、區 ±2、SL 中位外 4、TP 1R（同 #160 前向 `fit_rules.simulate` 一樣）；學生影子成績唔變 |
| 933 策略層停線（選項 C） | `SIG_STUDENT_HWM_START`（空）、`SIG_STUDENT_STOP_R`（8）、`SIG_STUDENT_DD_R`（10） | 由 START 日起計 933 成交簿 R：累計 ≤ −8R 或由高位回撤 ≥ 10R → 停開新倉；唔自動解，使用者批改 START 先重開 |
| **每書獨立開關**（使用者 11-07） | `SIG_S1_EXECUTE`／`SIG_FOLLOW_EXECUTE`／`SIG_STUDENT_EXECUTE`／`SIG_G7_EXECUTE`／`SIG_COMBO_EXECUTE`（全部 0） | 訊號書真倉＝`XAU_EXECUTE=1` **而且**該書開關=1；只開 `XAU_EXECUTE` 冇書會落單。921／922 唔受影響 |
| 戶口層停線（選項 C） | `XAU_DD_STOP_PCT`（0＝唔設）、`XAU_HWM_START`（空） | 天覆陣合計由高水位回撤 ≥ 20% → 停開新倉（pause_kind hwm，唔自動解）；改 `XAU_HWM_START` ＝高水位由當時權益重新起計（轉實倉日用，避開而家 26% 舊回撤） |

測試：`tests/test_xau_hwm_c.py`（18 項）、`tests/test_xau_book_exec.py`（11 項）＋全部 `tests/test_xau_*.py`、`tests/test_wsgi_app.py`、`scripts/test_gcp_agent.py` 過；`python3.11 -m py_compile xau/*.py` 過。

## 2. 部署步驟（總指揮做，每步先 dry-run 再等使用者批）
1. 合併 PR；`gcp_agent.py --profile xausig deploy`（dry-run → 使用者批 → `--yes`）；`--profile xau deploy` 同一份程式（env 預設關，冇行為改變）。
2. zhuge-xau-sig 改 env（**一次過一個修訂**，dry-run 列清楚）：

| env | 由 | 改做 | 原因 |
|---|---|---|---|
| `XAU_EXECUTE` | 0 | **1** | 總掣（單獨開冇書會落單） |
| `SIG_STUDENT_EXECUTE` | （0） | **1** | **淨係 933 落實倉**；`SIG_S1_EXECUTE`／`SIG_FOLLOW_EXECUTE`／`SIG_G7_EXECUTE`／`SIG_COMBO_EXECUTE` 唔設（0）→ 931／932／934／935 照影子／紙上，唔使再關 `SIG_G7_LIVE`、`SIG_COMBO_LIVE`、`SIG_FOLLOW_CHANNELS` |
| `SIG_STUDENT_LIVE` | 0 | **1** | 933 開 |
| `SIG_STUDENT_LIVE_RULES` | rev15,level | **rev15** | 只上 rev15 |
| `SIG_STUDENT_STRUCT` | — | **rev15:6,2,4,1** | E6S4 |
| `SIG_STUDENT_LOTS`／`_MIN`／`_MAX_LOTS` | — | **0.01**／**0.01**／**0.01** | 固定細注（SL 4 美元 × 0.01 手 ≈ 31 HKD／張） |
| `SIG_STUDENT_MAX_CONCURRENT` | 2 | **1** | 一次一張 |
| `XAU_RISK_PCT` | 10 | **1** | 按風險計手數嘅上限亦收細（0.01 封頂） |
| `SIG_STUDENT_HWM_START` | — | **部署日（YYYY-MM-DD）** | 策略層由當日起計 |
| `XAU_DD_STOP_PCT`／`XAU_HWM_START` | 0／— | **20**／**部署日** | 戶口層 20%，高水位由部署當時重新起計 |

3. 部署後核實：`?format=json` 嘅 `student_live.struct`、`student_live.hwm`、`execute`；`book_execute` 只得 933 係 true；巡檢確認 934／935／932／931 冇新 open 指令；第一張 933 單逐張報總指揮同使用者。
4. 退版：`rollback --to <舊修訂> --yes`（只切流量）；或者 env `SIG_STUDENT_EXECUTE=0`（933 即刻返影子，其他書唔郁）。

## 3. 要使用者／總指揮決定
- a) ~~清空 `SIG_FOLLOW_CHANNELS`~~：已由每書獨立開關取代，932 紙上跟單照記。
- ⚠ **933 圖冇心跳**：`xau/sig/studentlive/account.json` 最後 2026-11-03 14:38 UTC（其他圖 11-07 照有）。部署前要喺 …69 開返一張 XAUUSD 圖、EA magic 933，見到心跳先開 env。
- b) 部署日：建議星期一（11-09）先部署程式（行為唔變），星期二開 env；或者等 11-14 週報再確認 rev15 累計先開。
- c) 戶口 …69 同時有 931／933／934／935；呢次只開 933，其他書嘅影子前向照研究腳本計。
