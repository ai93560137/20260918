# …69 穩陣組 5 本趨勢簿（magic 937–941）：上線步驟

使用者 11-10：「揾多 5 條行真倉 69 戶口」→ 揀「穩陣組」、「每條獨立 magic，可以同時揸」。
每本簿用一個 magic，一次揸一張，每張 0.01 手；SL 放伺服器端，冇 TP，到期或者觸發出場條件就平。

| magic | 規則（IDEAS） | 入場（D1 收市後，新一日第一個心跳用市價入） | SL | 出場 |
|---|---|---|---|---|
| 937 | `spike` D1 急動＋SMA50（#1165） | 收市升（跌）≥ 1.5×ATR14，而且收市喺 SMA50 上（下） | 2×ATR14 | 收市穿 5 日相反極端，或者 10 根 D1 |
| 938 | `wide` D1 寬幅日（#1174） | 幅度 ≥ 2×ATR14，收陽做多、收陰做空 | 嗰日中位 | 5 根 D1 |
| 939 | `kelt` D1 Keltner（#1178） | 收市 > EMA20＋2×ATR14（< EMA20−2×ATR14） | 2×ATR14 | 收市返過 EMA20，或者 20 根 |
| 940 | `ichi` 一目均衡表穿雲（#1224） | 收市穿出雲而且轉換線同向 | 2×ATR14 | 收市返入雲，或者 120 根 |
| 941 | `turtle` 海龜系統 2（#1116） | 收市 > 之前 55 日最高收市（< 最低） | 2×ATR20 | 收市穿 20 日相反極端，或者 120 根 |

- 最低止蝕＝max(3 美元, 0.3×ATR14)。11-10 時 ATR14 大約 77 美元，即係每張風險大約 HK$600–1,200（wide 細啲）。
- 6 本簿（連 933 #1114）同時揸最壞情況大約 HK$6,000–7,000。每本簿各自有日停 HK$2,000（`XAU_TREND_DAY_STOP_HKD`）。
- 跟戶口總階梯：要喺 EA 嘅 `InpBotMagics` 加入 937–941（見下面第 2 步），否則戶口合計唔會計呢 5 本。
- 一致性：`research/strategy_search/parity_d1rules.py` 用 Duka 2015–22 同 MT5 2023–26 逐日比較，5 條規則合共 1,408 個訊號，方向同 risk 全部一致（`PARITY_D1RULES.md`）。
- 測試：`tests/test_xau_trend_books.py`（多本簿分流、開倉、跨簿回報、busy、到期）。

## 1. 部署（總指揮做；使用者親口批先 `--yes`）
1. PR 合併之後，總指揮跑 `gcp_agent.py --profile xausig deploy`，先 dry-run。部署完冇設 `XAU_TREND_BOOKS` 就唔會有新簿。
2. `gcp_agent.py --profile xausig env set XAU_TREND_BOOKS=937:spike,938:wide,939:kelt,940:ichi,941:turtle`，先 dry-run。
   `XAU_TREND_LIVE=1` 已經開咗（933 #1114），呢 5 本簿共用呢個開關。
3. 退版：`env unset XAU_TREND_BOOKS`，或者 rollback 去部署前嘅修訂。如果有倉，要先叫 EA 平倉：`close|all|magic=93x`。

## 2. MT5（使用者喺 …69 做，總指揮／天覆陣一步步教）
1. 喺 …69 開多 5 張 **XAUUSD** 圖，唔好用 931、933、934、935 嗰幾張。
2. 每張拖 TianfuExecutor 落去，設定：
   - `InpMagic`＝937、938、939、940、941（每張圖一個）
   - `InpUrl`＝zhuge-xau-sig 嘅網址（同 933 一樣）
   - `InpDryRun=false`
   - `InpBotMagics`：所有 …69 嘅圖都要改做包埋 937–941，例如 `931,932,933,934,935,936,937,938,939,940,941`
3. 開咗之後，網頁 `?format=json` 嘅 `trend_books[].account.received_utc` 應該喺 3 分鐘以內更新；巡檢腳本會印 `[trend 937 spike]` 等行。

## 3. 停條件（預先登記，同 #1114 一樣，每本簿各自計）
累計 ≤ −5R，或者 ≥ 12 張之後 PF < 0.8，或者連蝕 6 張 → 巡檢印「⛔」、即報總指揮，建議嗰本簿返影子；停唔停由使用者決定。

**11-11 更新（使用者「改」，依據 IDEAS #1271）**：933（#1114）、937（spike）、939（kelt）改做**只用累計 ≤ −8R**（攞走 PF 同連蝕兩條；歷史上嗰兩條多數係錯殺）。926、938、940、941 照舊用上面嗰套。組合回落 10R 通知線照舊。網頁顯示要等下次部署先更新；巡檢腳本即時生效。

## 4. 已知限制
- 真倉入場價係新一日第一個心跳嘅市價（回測用下一日開市價），兩者通常差幾毫子到一兩美元。
- 服務每本簿每日自動用 `xau/sig/bars/` 嘅 M1 存檔補最近 10 日日線；EA 停咗幾日，指標會由種子日線加存檔砌返。
- 冇戶口合計上限（935 有 `SIG_COMBO_ACCOUNT_MAX`）；使用者揀「可以同時揸」。

## 3. 新增 942：#1268 由上而下（11-11 使用者「#1268 開真倉」；11-12 使用者喺總指揮「確認開 942」，已部署 zhuge-xau-sig 00092-hx8）

| magic | 規則（IDEAS） | 入場（D1 收市後，新一日第一個心跳用市價入） | SL | 出場 |
|---|---|---|---|---|
| 942 | `td` 200 日線方向＋回調重拾 20 日線（#1268） | 收市 > SMA200 而且收市由 SMA20 之下升返上去 → 買；收市 < SMA200 而且由 SMA20 之上跌返落去 → 沽 | 3×ATR14 | 收市穿之前 20 日相反極端收市，或者穿返 SMA200，或者 250 根 D1 |

- 0.01 手、一次一張、SL 伺服器端、冇 TP；最低止蝕 max(3 美元, 0.3×ATR14)。SL 係 3×ATR14，比其他簿闊：ATR14 約 80 美元時每張風險大約 HK$1,900。
- 一年大約 5–6 張，贏少輸多、靠大單；歷史單條最大回落約 12R。停條件：只用累計 ≤ −8R（同 933／937／939）。
- 狀態機：狀態維持期間唔會再出訊號；止蝕之後要等狀態歸零（收市穿 20 日極端或者穿返 SMA200）再重新觸發。部署嗰刻如果狀態已經係 +1／−1，唔會補入，等下一次新觸發。
- 證據：舊黃金 1975–2004 同新黃金 2010–2026 方向一致（IDEAS #1268）、鄰近參數 20／20 都正（#1270）；標準冇顯著度要求。
- 一致性：`research/strategy_search/parity_td.py`——stooq 日線 1995–2026 逐日比較，真倉版（420 日窗）同研究版入場訊號 190／190 同日同方向、出場判斷 0 日唔一致（`PARITY_TD.md`）。測試 `tests/test_xau_trend_td.py`。
- 需要 ≥ 221 日日線：新簿第一次心跳會載入部署內置嘅 420 日種子（`trend_d1_seed.py`，到 11-06）再用 M1 存檔補最近 10 日。

### 上線步驟
1. PR 合併後，總指揮：`gcp_agent.py --profile xausig deploy`（先 dry-run）。部署完未改 env 就唔會有 942。
2. 總指揮：`gcp_agent.py --profile xausig env set XAU_TREND_BOOKS=937:spike,938:wide,939:kelt,940:ichi,941:turtle,942:td`（先 dry-run；使用者確認先 `--yes`）。
3. 使用者喺 …69 開多一張 **XAUUSD** 圖，拖 TianfuExecutor：`InpMagic=942`、`InpUrl` 同 933 一樣、`InpDryRun=false`；所有 …69 嘅圖 `InpBotMagics` 加埋 942。
4. 核實：`?format=json` 嘅 `trend_books` 有 magic 942、`d1_days` ≥ 221、心跳 3 分鐘內；巡檢印 `[trend 942 td]`。
5. 退版：env 改返冇 `942:td` 嗰串，或者 rollback；有倉先 `close|all|magic=942`。


## 4. 11-12 四本簿換規則（926／938／940／941；MT5 唔使改）

使用者 11-12：「將另外五條都加真倉，用返而家嘅 magic number」→ 揀「取代證據弱嘅簿」；喺總指揮親口確認後部署。**上面第 0 節表入面 938／940／941 嘅舊規則已經唔再行真倉（留影子）。**

| magic | 戶口 | 舊規則 | 新規則（IDEAS） | 入場（D1 收市後，新一日第一個心跳市價入） | SL | 出場 |
|---|---|---|---|---|---|---|
| 926 | …63 | qbrk＋lvbrk（#1107／#1113） | `tdflip`（#1300） | 收市喺 SMA200 上（下），收市重新企返 SMA20 上（下） | 3×ATR14 | 只喺收市穿返 SMA200 先平，或者 250 根 |
| 938 | …69 | wide（#1174） | `tdrsi`（#1273） | 方向同上；RSI(14) 由下升穿 40（做空鏡像） | 3×ATR14 | 收市穿之前 20 日相反極端收市，或者穿返 SMA200，或者 250 根 |
| 940 | …69 | ichi（#1224） | `tdsurge`（#1285） | 方向同上；單日收市升（跌）≥ 1.5×前一日 ATR14 | 3×ATR14 | 收市穿之前 10 日相反極端收市，或者穿返 SMA200，或者 250 根 |
| 941 | …69 | turtle（#1116） | `tdx50`（#1290） | 方向同上；收市升（跌）穿 SMA50 | 3×ATR14 | 同 940 |

- 呢四條係「事件版」：冇倉時每次觸發都可以入（942 `td` 係狀態機版，要等狀態歸零）。
- 停條件：四本都只用累計 ≤ −8R（同 933／937／939／942）；組合回落 ≥ 10R 通知照舊。
- 一致性：`research/strategy_search/parity_frame.py`——stooq 日線 1973–2026 逐日比較 13,077 日，四條入場、止蝕距離、出場全部一致（`PARITY_FRAME.md`）。測試 `tests/test_xau_trend_frame.py`。
- 設定：zhuge-xau `XAU_TREND_RULES=tdflip`（冇 `XAU_TREND_ADOPT`），修訂 00088-m6k；zhuge-xau-sig `XAU_TREND_BOOKS=937:spike,938:tdrsi,939:kelt,940:tdsurge,941:tdx50,942:td`，修訂 00094-g7q。
- 退版（要使用者批）：`--profile xau rollback --to zhuge-xau-00085-z99`、`--profile xausig rollback --to zhuge-xau-sig-00092-hx8`；有倉先 `close|all|magic=<magic>`。

## 5. 11-12 停 938／941；複利手數（未部署）

- **停 938（tdrsi #1273）同 941（tdx50 #1290）**：使用者 11-12「停 938 同 941」（風險預算：…69 7 本嘅歷史回落大過戶口本金）。zhuge-xau-sig 00095-9h5，`XAU_TREND_BOOKS=937:spike,939:kelt,940:tdsurge,942:td`；退版 `--to zhuge-xau-sig-00094-g7q`。MT5 938／941 圖可以留住（服務唔出指令）或者關。真倉 6 本：926、933、937、939、940、942。
- **複利手數（使用者 11-12「利用複式策略」；程式已備、預設關、要使用者確認先開）**：
  - 新 env：`XAU_TREND_COMPOUND=1`、`XAU_TREND_COMPOUND_UNIT_HKD=<每 0.01 手所需權益>`、`XAU_TREND_COMPOUND_MAX_LOTS=0.05`（預設）。兩個服務分開設定。
  - **預設模式 `XAU_TREND_COMPOUND_MODE=ratchet`（使用者 11-12「贏的時候加注、輸的時候不加注、每次注碼一樣」）**：手數＝floor(戶口結餘最高水位 ÷ UNIT) × 0.01，最少照舊 0.01、最多 MAX_LOTS；最高水位只升唔跌（存 `<PREFIX>trend/compound.json`，成個服務所有簿共用同一個注碼）；用結餘（已平倉先算贏，浮動盈利唔算），冇結餘先用權益；只喺新開倉時計；攞唔到數就用 0.01。
  - `XAU_TREND_COMPOUND_MODE=sym`：手數跟而家權益，跌會自動減（反複利保護）。
  - ⚠ 模擬（`COMPOUND_SIM.md`）：回測原樣下棘輪同對稱差唔多；但「回報打五折」情景，…69 用棘輪會輸晒（加咗注之後唔減，一段長回落就清袋），對稱版同固定版唔會。
  - UNIT＝呢個戶口全部趨勢簿 0.01 手時嘅歷史最大回落 × 1.5（數字由 `research/strategy_search/compound_sim.py` 計，喺 send_message 報，唔寫入 repo）。**加減簿之後要重新計 UNIT。**
  - 每本簿日停（`XAU_TREND_DAY_STOP_HKD`）冇跟手數放大：手數大咗，一張止蝕可能已經過日停，嗰日其餘開倉會被擋——屬保守方向。
  - 模擬：`research/strategy_search/COMPOUND_SIM.md`。測試 `tests/test_xau_trend_compound.py`。

- **11-12 複利已開（sym）**：使用者睇完三個版本模擬後揀「跌會減」。zhuge-xau 00091-g5k、zhuge-xau-sig 00097-5zq：`XAU_TREND_COMPOUND=1`、`XAU_TREND_COMPOUND_MODE=sym`、UNIT 各自設定（數字喺 env，唔寫入 repo）、MAX_LOTS 用預設 0.05。開嗰刻兩戶手數仍係 0.01。核實：`?format=json` 嘅 `trend_live.compound`／`trend_books[].compound` 同 `lots`。退版：zhuge-xau → 00090-js6（關複利）；zhuge-xau-sig → 00096-qhx。

## 6. 新增 944：#1421 日線方向＋H4 MACD（使用者 11-13「#1421 轉真倉」→「63 0.01」：戶口 …63、固定 0.01 手；**11-13 已部署 zhuge-xau 00093-nqm**；退版 00092-cvc＝只關 944、00091-g5k＝返舊程式）

- **規則 `h4macd`**（`xau/trend_h4rules.py`；對拍 `research/strategy_search/PARITY_H4MACD.md`：2010–2026 共 25,455 根 H4，329／329 個訊號同根同方向、風險相差 0%、追蹤出場 0 個唔一致）：
  - 方向＝日線 #1268 狀態機喺上一個已完成 UTC 日嘅狀態（+1 只做多、−1 只做空、0 唔做）——即係只喺 #1268「出手期間」先做。
  - 入場＝H4 收市時 MACD(12,26,9) 柱由 ≤ 0 轉 > 0（做空鏡像）；只睇 08:00／12:00／16:00 UTC 開嗰三根；下一根 H4 開市（12:00／16:00／20:00 UTC）第一個心跳市價入，遲過 15 分鐘唔追。
  - 止蝕＝max(2×ATR14(H4), 3 美元, 0.3×上一日 D1 ATR14)，伺服器端；冇止賺。
  - 出場＝入場後任何一根 H4 收市穿之前 20 根最低（做空：最高）收市 → 下一根開市平；或者新一日日線狀態唔再係持倉方向 → 新一日第一個心跳平。一次一張、冇時間上限。
- **回測**（IDEAS #1421，黃金 M1 2010–2026，每張扣 0.5 美元）：273 張（約每年 16 張）、勝率 34%、平均 +0.505R、PF 1.89；2010–14 +0.663／2015–22 +0.292／2023–26 +0.770；多 +0.563／空 +0.411；每月最大回撤 13.3R。
  **弱點**：H4 數據喺 #1323–1327 已經睇過（第二次用），當時定咗「合格都只入影子等前向」；前向到 11-13 只有 1 張；利潤靠少數大單（勝率 34%）；
  只喺 #1268 出手期間做，方向同 926（#1300）／942（#1268）一致，會疊加同一方向嘅風險。
- **現況（11-13）**：日線狀態 −1（只做空）；H4 ATR14 約 33 → 止蝕距離約 66 美元 → 0.01 手每張風險約 66 美元。最近訊號大約每星期一個。
- **部署（總指揮；先 dry-run，使用者親口批）**：
  - 使用者揀 …63：先 `--profile xau deploy` 新程式，再 `--profile xau env set XAU_TREND_BOOKS=944:h4macd XAU_TREND_FIXED_MAGICS=944`（zhuge-xau 第一本額外簿；926 設定唔變）。
  - H4 冷啟動種子 `xau/trend_h4_seed.py`（券商 M1 砌，到 2026-11-13 12:00 UTC；`research/strategy_search/build_seed_h4.py --csv`）；種子尾同上線之間嘅缺口由服務 M1 存檔（最近 10 日）自動補，所以要喺種子日期後 10 日內上線，否則重砌。
  - **手數**：使用者定固定 0.01 手 → `XAU_TREND_FIXED_MAGICS=944`（呢本簿唔跟複利；926 照跟，UNIT 唔使改）。
  - MT5：使用者開一張 XAUUSD 圖（任何週期）掛 `TianfuExecutor`，`InpMagic=944`，網址同該戶口其他圖一樣，`InpDryRun=false`。
  - 核實：`?format=json` 嘅 `trend_books` 有 944、`h4_bars` ≥ 300、`d1_days` ≥ 300、心跳正常；第一張單即報。
- **停條件**：累計 ≤ −8R（巡檢腳本同網頁已加 `h4macd`）；組合回落 ≥ 10R 通知使用者。
- 測試：`tests/test_xau_trend_h4.py`（5 個）；其餘 `tests/test_xau_trend_*.py` 逐個檔跑。
