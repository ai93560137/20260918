# 外部數據品質 SOP（MT5／Futu／IBKR × 網站數據）

版本 1.0（2026-09-27）｜適用：預設分支 `claude/gcp-trading-v12-rewrite-bz75t2` 的 `data/external/`，以及所有取用它的分支。
配套文件：[`README.md`](README.md)（目錄、欄位、時區）、[`qc/QC_REPORT.md`](qc/QC_REPORT.md)（每天的比對結果）。

---

## 0. 一頁看懂

**目的**：任何分支用到的數據，數值和日期都要被至少一個**獨立來源**比對過。有一筆無法解釋的差異，那一類數據就停用，直到查明。

**資料流**

```
網站數據（各分支自己抓）                  外部來源（券商）
  鳥翔 gifted-carson：Yahoo 日線、Nasdaq     Futu：使用者電腦 OpenD → Cloud Run
  金絲雀：Yahoo 指數日線                     IBKR：雲垂 GCP VM → 雲垂分支
  雲垂：Yahoo 指數、HKEX                     MT5：EA → Cloud Run
            │                                        │
            └──────────────┬─────────────────────────┘
                           ▼
        預設分支每天 00:17 UTC（香港 08:17）
        1. external_data_sync.py  → data/external/（彙整）
        2. external_qc.py         → data/external/qc/（比對、閘門、明天的抽樣清單）
                           ▼
        各分支：先看 qc/GATE.json，只用 PASS 的類別
```

**角色**

| 角色 | 負責 | 不負責 |
|---|---|---|
| 使用者 | 本機 Futu 腳本與環境變數、Cloud Run 部署、GitHub Secret、IBKR 帳密；**核可**已知原因登記；決定擴充 | 手動改數據 |
| 預設分支（本 session，兼風揚陣） | 彙整、比對、閘門、抽樣清單、本 SOP 與程式；風揚陣的預測、檢討與通知 | 修別的分支的上游 |
| 雲垂 | IBKR VM：採集、每日抽樣（附錄 B）、查 IB 口徑 | 改 `data/external/` |
| 金絲雀 | 用 PASS 的數據分析，列出缺什麼 | 給新數據警報權、改抓取設定 |
| 蛇蟠陣、鳥翔、外匯 | 取用；修自己的上游（例如鳥翔的 Nasdaq 快照） | 改 `data/external/` |

**代號與分支對照**（2026-09-27 核對，2026-10-04 加風揚陣）

| 代號 | Claude session | 分支 | 與外部數據的關係 |
|---|---|---|---|
| 金絲雀 | 金絲雀作戰手冊定稿 | `claude/canary-playbook-final-3um9lp`（已合併；數據改在預設分支 `canary/` 每日更新） | 9 隻鳥全來自 Yahoo，需要 IBKR、Futu 獨立驗證 |
| 雲垂陣 | 恒指期權對沖-雲垂陣 | `claude/dazzling-curie-f3xzb8` | IBKR VM 的擁有者（附錄 B） |
| 蛇蟠陣 | 恆指黃金突破K 2 days b4策略-蛇蟠陣 | `claude/gifted-carson-v2tvhw` | 恒指期貨與黃金通道；可對照 MT5 黃金、Futu 恒指 |
| 鳥翔 | 股票研究-鳥翔 IBKR VM | `claude/stock-research-k9nzau`（網站日線與 Actions 在 `claude/gifted-carson-v2tvhw`） | 網站日線、Nasdaq 第二來源、IBKR 股票覆核 |
| 外匯 | 外匯數據測試 | `claude/forex-data-testing-w4q3m2` | XAUUSD MT5 歷史匯出、Dukascopy；做過蛇蟠陣外匯延伸測試 |
| 風揚陣 | FUTU GCP恆指波幅 | 預設分支 `claude/gcp-trading-v12-rewrite-bz75t2`（工作分支 `claude/epic-ramanujan-kp1l1v`）；手冊 `research/hsi_futures_range/FENGYANG.md` | 恒指即月期貨（Futu `HK.HSI_FRONT`）的交易日波幅與高低位預測、「高低位已出現」通知；2026-10-04 登記 |

---

## 1. 名詞與判定

### 1.1 獨立來源與同源

| 來源 | 背後的數據商 | 與 Yahoo 是否獨立 |
|---|---|---|
| 鳥翔 `data/equities`、金絲雀 `canary/data_external`、雲垂 `tradingview/data_external` 的指數日線 | Yahoo（yfinance） | **同源** |
| Nasdaq.com 第二收市源 | Nasdaq | 獨立 |
| Futu | 富途（交易所行情） | 獨立 |
| IBKR | 盈透（交易所行情） | 獨立 |
| MT5 | 券商 CFD 報價 | 獨立，但 CFD 與現貨本來就不會逐筆相同 |

同源比對只能證明**抄錄與日期**沒錯，不能證明數值是真的。

### 1.2 每一筆比對的標記（預先登記，不事後調整）

| 標記 | 條件 | 擋閘門 |
|---|---|---|
| ✅ 一致 | 差異 ≤ max(0.0005, 0.000001 × 數值)。吸收 Yahoo 的 float32 尾數，不吸收任何一跳價差 | 否 |
| ℹ️ 記錄 | 口徑本來不同：5 分 K 合成的開盤（首筆成交對開盤競價）、成交量 | 否 |
| ⏭️ 略過 | 對方沒有這一天（超出對方最新日期）、沒有這個代號、交易時段不完整（不完整只比收盤） | 否 |
| ⚠️ 已知 | 命中 `qc/known_issues.csv` 的登記 | 否 |
| ❌ 未解釋 | 其他一切差異，包括兩邊日期重疊區段內只有一邊有的**日期缺漏** | **是** |

自動附註：值等於對方前一或後一交易日 → 寫「日期錯位」；有第三個來源的同一天同一欄 → 寫「第三來源」的值（已錯位的來源不投票）。

### 1.3 類別閘門（`qc/GATE.json`）

| 狀態 | 條件 | 能不能用 |
|---|---|---|
| `PASS` | 沒有 ❌，且至少一筆獨立來源 ✅ | 可以 |
| `SAME_SOURCE_ONLY`（🟡 僅同源） | 沒有 ❌，但 ✅ 全部來自同源比對 | 日期與抄錄可信；**不得宣稱數值已驗證** |
| `FAIL` | 至少一筆 ❌ | **不要用**，先走第五節 |
| `NO_DATA` | 沒有任何 ✅ | 沒有證據，不要當成驗證過 |

五個類別：`futu_vs_web`、`ibkr_vs_web`、`web_vs_web`、`canary_inputs`、`internal`（說明見 README 第六節）。

---

## 2. 每日時間表

| 香港時間 | UTC | 誰 | 做什麼 |
|---|---|---|---|
| 04:00／05:00 | 20:00／21:00 | — | 美股收市（夏令／冬令） |
| 05:00 | 21:00 | — | MT5 券商換日（伺服器 UTC+3；冬令 UTC+2 則 22:00 UTC） |
| 06:30 | 22:30 | 金絲雀 | `canary_daily.yml` 在預設分支更新 `canary/data_external/`、燈色表，發 Telegram（2026-09-27 起取代 Claude 排程） |
| 約 06:00–07:56 | 約 22:00–23:56 | 鳥翔 | 網站日線與 Nasdaq 快照自動提交 |
| 07:30 前 | 23:30 前 | 雲垂 VM | IBKR 每日抽樣推回雲垂分支（附錄 B，開始後） |
| **08:17** | **00:17** | 預設分支 | 彙整 → 比對 → 提交 `STATUS.md`、`qc/`，產生今天的 `futu_sample.txt`、`ibkr_sample.txt` |
| 09:30 | 01:30 | — | 港股開市 |
| **16:30–21:00** | 08:30–13:00 | 使用者電腦 | Futu 腳本讀 `futu_sample.txt`，抓日 K 推上 GCP（隔天 08:17 被比對） |
| 開市時段 | — | 使用者電腦、EA | Futu 每 5 分鐘推 5 分 K 與期權；MT5 每分鐘推 M1 |

**一天的數據什麼時候被驗完**：交易日 D 的網站數據在 D 當晚提交，Futu 在 D 的 16:30 後（港股）或 D+1 的 16:30 後（美股）抓到，所以美股 D 的完整比對出現在 **D+2 早上 08:17** 的報告。

---

## 3. 每日作業

### 3.1 自動（不用動手）
- 彙整、比對、閘門、提交；產生兩份抽樣清單；今天有爭議的代號自動排進明天 Futu 清單的前面。

### 3.2 使用者每日（約 2 分鐘）
1. 打開 `data/external/qc/QC_REPORT.md`，看最上面的閘門表。
2. 有新的 ❌ → 照第五節處理；同一個 ❌ 連續 3 天沒人處理 → 通知負責分支。
3. 看 `data/external/STATUS.md`：平日最新日期落後兩天以上 → 第七節故障排除。
4. 確認本機 Futu 腳本在跑：控制台「📡 Futu 行情」是綠字；每天 16:30 後腳本視窗有一行「📅 日線抽樣完成：成功 N／N」。

### 3.3 取用分支每次取數前
1. `git archive` 取 `data/external`（README 第二節）。
2. 讀 `qc/GATE.json`：只用 `PASS`；`SAME_SOURCE_ONLY` 只能說「日期與抄錄已核對」；`FAIL`、`NO_DATA` 不用。
3. 研究或報告裡寫明用的是哪一天的閘門（`run_date`）。

---

## 4. 擴充取數

### 4.1 Futu：只改使用者電腦的環境變數

改完**關掉命令列重開、重啟腳本**；隔天的 `qc/results_latest.csv` 會出現新代號。

| 變數 | 作用 | 預設 | 建議 |
|---|---|---|---|
| `FUTU_DAILY_MAX` | 每天日線抽樣幾個代號（清單已排好優先順序：錨點 → 爭議 → 隨機，美:港 = 2:1） | 60 | 200 起；清單目前約 416 個，超過不會多抓 |
| `FUTU_DAILY_EXTRA` | 每天一定要抓的代號，排最前面、不佔 MAX | 空 | 例：找到 VHSI 代號後加進來 |
| `FUTU_DAILY_BARS` | 每個代號抓幾根日 K（回溯天數） | 20 | 20；要補更早的爭議再調大，上限 100 |
| `FUTU_DAILY_BATCH` | 每批訂閱幾個 | 50 | 不用改（訂閱額度 100，要留給 5 分 K） |
| `FUTU_SYMBOLS` | 5 分 K 與期權的代號（逗號分隔） | US.QQQ | 加代號就多一份 5 分 K 與期權封存 |
| `FUTU_DAILY` | `0` = 關掉日線抽樣 | 1 | — |

```bat
setx FUTU_DAILY_MAX 200
setx FUTU_DAILY_EXTRA "US.IWM,US.DIA"
REM 關掉命令列、重開，再重啟腳本
python push_to_gcp.py
```

**限制**
- 權限：港股股票／期權／期貨 LV1、美股股票 LV3、美股期權 LV1、加密貨幣 LV1。**沒有**美國指數（SPX、VIX）、CME、COMEX、日本、新加坡、A 股。
- 訂閱額度 100：腳本分批，每批訂滿 70 秒退訂再換下一批。每批約 1.5 分鐘，200 個約 6 分鐘。
- 時段：只在香港 16:30–21:00 跑；21:00 還沒抓完的，剩下的明天再抓。
- 不用歷史 K 線額度（30 天 100 個代號），因為用的是訂閱後取最新 K 線。

**找代號（例如 VHSI）**
```bat
python push_to_gcp.py --search 波幅
```
找到後：(1) 加進 `FUTU_DAILY_EXTRA`；(2) 告訴預設分支，把它對到金絲雀的 `vhsi_daily.csv`（`external_qc.py` 改一行），才會進 `canary_inputs` 比對。**不要猜代號**。

### 4.2 IBKR：由雲垂的 VM 抓，照附錄 B 的規格

優先順序（依「目前哪些數據沒有獨立來源」排）：

| 優先 | 要什麼 | 為什麼 |
|---|---|---|
| P1 | 金絲雀的美股指數鳥：SPX、VIX、VIX9D、VIX3M、VVIX 日線 | 目前只有 Yahoo，Futu 沒權限，**IBKR 是唯一獨立來源** |
| P1 | 恒指 HSI、VHSI 日線（HKFE） | 恒指有 Futu，VHSI 沒有；兩個來源互證 |
| P2 | 股票每日抽樣：美股 30、港股 15（`qc/ibkr_sample.txt` 已隨機排好） | 擴大 `ibkr_vs_web` 覆蓋，並持續監測 IB 開盤價口徑 |
| P3 | 外匯、黃金（雲垂已有 `scripts/ib_fx_history.py`） | 給蛇蟠當 MT5／Dukascopy 以外的來源 |
| P3 | 更多指數期權市場（`gcp_ib/ib_collector.py` 的 `MARKETS` 加一行） | 金絲雀擴充候選鳥 |

限制：IB 歷史數據每 10 分鐘最多 60 個請求；延遲數據對 CBOE 指數是否可用**要先 probe**；API 必須唯讀。
MOVE、AXVI 在 IB 可能沒有，probe 後列出。

### 4.3 加新的來源或商品（通用步驟）
1. 使用者決定要加什麼、用在哪個研究。
2. 來源端改（Futu 環境變數、雲垂腳本、EA）。
3. 預設分支改對照表（`external_data_sync.py` 的 `series_target`、`external_qc.py` 的對照），加測試，PR。
4. 第一天的比對結果全數人工看過，才開放給分支取用。

---

## 5. 差異處理（看到 ❌ 時）

照說明欄的原因分三種：

**A. 日期錯位**（說明寫「日期錯位：…等於…前一交易日」）
1. 這是來源把日期標錯，數據本身是錯的。
2. **不要登記已知原因**，閘門維持 `FAIL`。
3. 通知該來源的負責分支修程式，並處理錯的檔（刪除或更正，要寫依據）。
4. 修好後，下一次比對自動轉綠。

**B. 日期缺漏**（說明寫「日期缺漏：只有…有這一天」）
1. 先查是不是單一市場的假期或停市（例如港股颱風）。
2. 是 → 使用者核可後登記，原因寫清楚是哪個市場、哪個事件。
3. 不是 → 來源漏抓，通知負責分支補。

**C. 數值不同**
1. 等隔天：這個代號已自動排進明天 Futu 清單前面；IBKR 抽樣開始後也會投票。
2. 看第三來源：兩個獨立來源一致、第三個不同 → 不同的那個有嫌疑。
3. 查嫌疑來源的**口徑**（例如開盤用首筆成交還是開盤競價、收盤含不含收市競價）。
4. 口徑不同、但數據仍然可用 → 使用者核可後登記，原因要寫出證據；**只對該欄位登記**，不要用 `*` 蓋掉整個代號的所有欄位。
5. 數據本身錯 → 不登記，通知來源修。

**登記格式**（`data/external/qc/known_issues.csv`，只在預設分支改，使用者核可）：
```
instrument,date,field,cause,added_by
*,*,open,IB 日線開盤為首筆成交、非開盤競價（雲垂查證，附證據連結）,使用者 2026-10-01
```

**絕對不要**：改容差、刪比對列、手改 `data/external/` 的數據、為了讓閘門變綠而登記。

### 5.1 目前未結案（2026-09-27 第一次比對）

| 類別 | 差異 | 原因 | 負責 | 狀態 |
|---|---|---|---|---|
| `web_vs_web` | Nasdaq 快照 09-24、09-25 各抽 150 檔，全部等於 Yahoo **前一交易日** | 鳥翔 `scripts/fetch_second_source.py` 用 SPY 最後一根的日期當快照日期，沒驗證 Nasdaq 的 lastsale 已更新 | 鳥翔 | 待修（A 類，不登記） |
| `web_vs_web` | META 09-22、CPRT 09-23 差不到一分錢 | Nasdaq 報三位小數、Yahoo 兩位；Futu 第三票待確認 | 預設分支 | 觀察 |
| `ibkr_vs_web` | 美股 60 筆有 3 筆、港股 45 筆有 9 筆**開盤**不同；港股 2 筆收盤差一跳 | 疑似 IB 日線開盤是首筆成交、網站是開盤競價，未證實 | 雲垂查證；Futu 第三票 | 待查（C 類） |
| `canary_inputs` | 全部 ✅ 但只有同源 | 金絲雀 9 隻鳥全來自 Yahoo | 附錄 B（IBKR）、Futu 恒指／VHSI | 🟡 僅同源 |

⚠️ 影響：鳥翔「成交後滑價 = 成交價 ÷ IB 次日開市價 − 1」直接用 IB 開盤價，查證前結論要標「開盤口徑待確認」。

---

## 6. 變更管理

- 容差、判定規則、閘門定義是**預先登記**的。要改：新版 SOP、commit 寫明原因；舊的比對結果不回頭重算。
- 抽樣大小可以改（本機環境變數、`external_qc.py` 的 `SAMPLE_*`），不算改規則，但要在 commit 寫明。
- 程式位置：

| 檔案 | 在哪 | 做什麼 |
|---|---|---|
| `main.py` | 預設分支 → Cloud Run | 收 Futu、MT5，按日封存，`?view=archive` |
| `futu/push_to_gcp.py` | 預設分支 → 使用者電腦 | Futu 5 分 K、期權、每日日線抽樣 |
| `scripts/external_data_sync.py` | 預設分支 | 彙整 |
| `scripts/external_qc.py` | 預設分支 | 比對、閘門、抽樣清單 |
| `.github/workflows/external_data_daily.yml` | 預設分支 | 每天 00:17 UTC 排程 |
| `gcp_ib/`、`scripts/ib_*.py` | 雲垂分支 → VM | IBKR 採集 |

---

## 7. 故障排除

| 症狀 | 可能原因 | 處理 |
|---|---|---|
| `STATUS.md` 的 MT5／Futu 是 ⚠️ | Secret `ZHUGE_GCP_URL` 沒設或錯；Cloud Run 不是 R95 以上 | 檢查 Secret；部署最新 `main.py` |
| 報告沒有新的 Futu 日線 | 腳本沒在 16:30–21:00 跑；`FUTU_DAILY=0`；OpenD 沒登入 | 看腳本視窗有沒有「📅」；`python push_to_gcp.py --once --daily` 手動測 |
| 「讀不到抽樣清單」 | 電腦連不到 GitHub | 會只抓錨點與 `FUTU_DAILY_EXTRA`；檢查網路 |
| 「訂閱：…quota」 | 其他程式也佔用 OpenD 訂閱 | 調小 `FUTU_DAILY_BATCH`；關掉其他看盤程式的訂閱 |
| 「退訂失敗」 | 訂閱不到 1 分鐘 | 腳本下一輪會重試；持續發生就重啟腳本 |
| `STATUS.md` 寫「尚未開始：ib_daily_sample.csv」 | 雲垂還沒做附錄 B | 正常；做好後自動同步 |
| 某類一直 `NO_DATA` | 來源還沒資料（週末、剛啟用） | 平日連續 2 天仍 `NO_DATA` 才查 |
| 美股當天沒被比對 | 網站或 Futu 還沒有這一天 | 正常，見第二節「D+2」 |

---

## 8. 每週與每月

**每週（週一）**
- 看 `qc/history.csv`：各類 ❌ 數是否下降；同一原因連續一週未處理 → 升級給負責分支。
- 看 Futu 覆蓋：`results_latest.csv` 中 `futu_vs_web` 比到的代號數，不足 `FUTU_DAILY_MAX` 的一半就查。

**每月（第一個週一）**
- 逐條檢查 `known_issues.csv`：證據還成立嗎？來源修好了就刪。
- 檢查 Futu、IBKR 權限與額度有沒有變。
- 視研究需要調整抽樣大小（第六節）。

---

## 附錄 A：檔案地圖（`data/external/`）

| 路徑 | 內容 |
|---|---|
| `STATUS.md`、`STATUS.json` | 每天彙整狀態 |
| `mt5/<商品>/M1/<年>/<日期>.csv.gz` | MT5 M1（券商伺服器日期） |
| `futu/<代號>/K_5M/…`、`futu/<代號>/options/…` | Futu 5 分 K、期權 |
| `futu/_K_DAY/<年>/<日期>.csv.gz` | Futu 每日日線抽樣（含 `code` 欄） |
| `ibkr/iv_term_structure/ib_iv_log.csv` | IBKR 日經／歐股週月 IV |
| `ibkr/stock_closes/` | IBKR 股票覆核（鳥翔月底名單） |
| `ibkr/daily_sample/ib_daily_sample.csv` | IBKR 每日抽樣（附錄 B 開始後） |
| `qc/QC_REPORT.md`、`qc/GATE.json` | 比對報告與閘門 |
| `qc/results_latest.csv`、`qc/history.csv` | 本次每一筆、每天每類一列 |
| `qc/futu_sample.txt`、`qc/ibkr_sample.txt` | 今天給 Futu、IBKR 的抽樣清單 |
| `qc/known_issues.csv` | 已知原因登記 |

---

## 附錄 B：IBKR 每日抽樣規格（貼給雲垂）

```text
【雲垂：IBKR 每日抽樣（外部數據品質 SOP 附錄 B）】

目的：金絲雀的美股指數鳥（SPX、VIX、VIX9D、VIX3M、VVIX）目前只有 Yahoo 一個來源，
Futu 沒有美國指數權限，IBKR 是唯一的獨立來源。另外擴大股票抽樣，持續監測 IB 開盤價口徑。

輸入：預設分支每天 00:17 UTC 產生的 data/external/qc/ibkr_sample.txt
  git fetch origin claude/gcp-trading-v12-rewrite-bz75t2
  git show origin/claude/gcp-trading-v12-rewrite-bz75t2:data/external/qc/ibkr_sample.txt
  CSV 表頭：sec_type,symbol,exchange,currency,compare_with
  前 7 列是指數錨點（IND SPX/VIX/VIX9D/VIX3M/VVIX CBOE USD、IND HSI/VHSI HKFE HKD），之後是股票（STK，美股 SMART USD、港股 SEHK HKD）。

做什麼：每個合約取最近 10 根日線（reqHistoricalData，durationStr="10 D"，barSizeSetting="1 day"，
  whatToShow="TRADES"，useRTH=True），延遲數據（reqMarketDataType(3)）即可。
  先 probe：每種合約各試一個，記下哪些沒權限或沒資料（例如 CBOE 指數延遲數據），寫進 _status。

輸出：本分支 tradingview/data_external/ib_daily_sample.csv（追加，按 date+sec_type+symbol 去重，保留最新一次）
  表頭：date,sec_type,symbol,exchange,currency,open,high,low,close,volume,fetched_utc
  date 用交易所當地日期 YYYY-MM-DD；拿不到的欄位留空，不要填 0。

時間：每天 22:00–23:30 UTC 之間跑完並推回本分支（預設分支 00:17 UTC 鏡像）。
節流：IB 每 10 分鐘最多 60 個請求；每個請求間隔 ≥ 10 秒；52 個合約約 9 分鐘。
規矩：API 唯讀；帳密只在 VM；不改預設分支；檔名與欄位不要改（要改先告訴我）。
回報：probe 結果（哪些指數拿得到）、第一次輸出的列數；預設分支隔天的 qc/QC_REPORT.md 會出現「IBKR 獨立來源」。
```
