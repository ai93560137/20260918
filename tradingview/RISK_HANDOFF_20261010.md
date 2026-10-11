# 持倉風險交接（2026-10-10，接 `claude/dazzling-curie-f3xzb8`）

只做資訊：唔落單、唔解鎖交易；富途報價只作監控，落單以券商即時價為準。
來源檔案由 `origin/claude/dazzling-curie-f3xzb8` 複製（嗰條分支冇改動）。repo 係公開嘅 → 建議轉私人。

報告：`python3 tradingview/risk_report.py --md tradingview/risk_report.md`

## 今次改動

| 檔案 | 改咗乜 |
|---|---|
| `tradingview/risk_report.py` | stale 腿改用 put-call parity 標價；對帳（解釋 Futu +12,771）；Θ 每日；時間前推情景；ES 上升掃描；HSI×ES 雙市場格；EW 到期日合理性；交收方式 |
| `tradingview/data_external/risk_book.json` | MHI P25000 加 `mark: parity`；MES／EW 加實物交收說明；EW 到期日依據；Futu 截圖數字 |
| `gcp_ib/futu_positions_quote.py` | `--diagnose` 重寫：印 OpenD 登入牛牛號尾 3 位、每個帳戶卡號尾 4 位、狀態（ACTIVE/DISABLED）、HKD＋USD 資金、持倉、今日／歷史訂單、成交，最後畀判斷；正常讀持倉時略過 DISABLED 帳戶、同一帳戶唔重複讀；`--push` 改為推去目前分支 |

## 未解決事項處理結果

### 1. 富途 OpenAPI 讀唔到持倉
**2026-10-10 使用者確認：OpenD 登入嘅富途 ID 唔啱，稍後會改。** 改好之後跑 `--diagnose` 驗證，再跑冇參數版本讀持倉。

核對過 futu-api 10.11 原始碼：`get_acc_list` 只會列出 **OpenD 登入嗰個用戶 ID** 名下嘅帳戶；期貨 context 預設唔按券商過濾。
「市值 0、持倉 0、9 月起成交 0」三樣同時係 0，最可能係 **OpenD 登入咗另一個富途 ID**（例如用電郵登入 OpenD，App 用手機號）。
使用者喺 Windows 跑：

```
python gcp_ib\futu_positions_quote.py --diagnose
```

然後對照：App「我的」頭像下牛牛號尾 3 位 ↔ 輸出「OpenD 登入用戶 ID」；App 期貨帳戶卡號尾 4 位 ↔ 輸出「卡號」。
唔同 → OpenD 登出，用 App 嗰個 ID 重新登入。相同但仍 0 → 確認 App 已同意 OpenAPI 交易協議，並 `pip install -U futu-api`、更新 OpenD。
輸出只有尾幾位號碼，可以貼返嚟；**唔好貼密碼或完整帳號**。

### 2. EW2610 P7750 到期日
CME 代碼 `EW`（冇數字）＝E-mini S&P 500 **月底（EOM）期權**，喺每月最後營業日到期 → **2026-10-30（週五）**。
另一個獨立證據：用現價 47 反推 IV，10/30 得 12.7%（同 MES 10/16 價平 10.2–10.7% 加斜率吻合）；若係 10/16 要 23.1%，唔合理。
⚠ 歐式、到期 ITM **自動行使成 1 手 ES 期貨**（US$50/點，名義約 US$39 萬），唔係現金結算。MES 週權同樣會交收成 MES 期貨。
仍建議喺富途合約詳情頁核對「到期日」一欄。

### 3. MHI 25000 Put 現價 stale
報告改用 parity：P ≈ C + (K − F) = 118 + (25000 − 24365) = **753**（原用 728）。週一開市後：
`python gcp_ib\futu_positions_quote.py --codes HK.MHI261029P25000000 HK.MHI261029C25000000 HK.MHI2610`
（代碼格式同 `--fixed` 組出嚟嘅一致；如報錯就用 `--chain 2026-10-29 24800 25200` 搵返正確代碼）

### 4. 舊對沖買回價／新對沖時間
冇資料可推（Futu「今日盈虧」7,959 混埋所有腿嘅隔日變動，解唔出單一買回價）。
OpenD 身份修好之後，`--diagnose` 會列出 9/1 起成交筆數，正常模式會用成交紀錄補返；或者喺 App「交易 → 歷史訂單」睇。

### 5. 週權 strangle、EW put 冇計劃／止損
本分支（`beautiful-hypatia`）同其他分支都搵唔到呢三隻倉嘅開倉計劃或止損規則（只有週權 IV 記錄儀）。
報告 §4 已標「冇登記止損規則」。要使用者講返係邊條分支／邊個工作階段叫佢開，先可以補規則；我唔會自己定。

### 6. 模型限制
已補：時間價值（Θ、過 3／6 日情景）、每腿各自 IV（已包含當刻斜率）。
未補：保證金（SPAN 由交易所計，請睇富途「維持保證金」）、滑價、sticky-delta 斜率動態。

## 重點數字（模型標價）
- 現況 +12,524 HKD；Futu 截圖 +12,771 = 用最後成交價＋匯率 ≈ 7.848，對得上；差額係 parity 改咗 put 標價（−250）。
- ES Δ ≈ +8,800 HKD／1%，EW put 佔大部分；ES 跌約 3.5% 觸硬止損；HSI 同 ES 同跌 3% 觸及；HSI +3%＋ES −3% 都觸及。
- Θ 每日約 +2,260 HKD（HSI +1,170、ES +1,090）：價唔變過 3 日權益約 819k，但過 3 日再跌 ES 3% 只剩離止損 +13.6k。

## 持倉／報價更新後通知其他陣（2026-10-10 使用者確認）
觸發：使用者喺 Windows 跑 `futu_positions_quote.py --push`，推咗 `futu_positions.json` 上本分支。
本工作階段重算 `risk_report.py`，再用 `send_message` 逐個陣發短訊息（只發同佢相關嘅產品；註明「富途報價只作監控，落單以券商即時價為準」）：

| 陣 | 工作階段 | 內容 |
|---|---|---|
| 雲垂陣 | `session_01QLJsy4RoeHjPNdNha73ibt` | 全部持倉、報價、Greeks、壓力測試、離硬止損 |
| 風揚陣 | `session_01AmKfqsQjNQAkz1xgjRo2Mj` | 恒指期貨／期權部位、HSI Δ、HSI 觸硬止損位 |
| 地載陣 | `session_01QDAzw2CmhvhYWip9SRktBn` | 同風揚陣 |
| 蛇蟠陣 | `session_011i86tjK8gxGxbMdTukZp4B` | 同風揚陣 |
| 鳥翔 | — | **不通知**（使用者決定；持倉冇股票） |

## 使用者決定（2026-10-11）
- 硬止損「權益 < HK$75 萬」按**幾個戶口合計**計，維持不變；其他戶口冇持倉。出報告用 `--combined-equity <合計 HKD>`（實數唔寫入 repo）。
- 實際最先受限係富途期貨戶口保證金緩衝（報告 §8 有跌穿 0 所需變動）；使用者決定唔預先轉資金入富途。
- 已向風、雲、蛇、地四陣發通報同更正（按合計權益計，硬止損唔再近，主要風險係富途保證金）。

## 自動化（2026-10-11 部署 R147）
- 使用者部機 `gcp_ib/auto_risk.py --every 15`（啟動資料夾 `ZhugeAutoRisk.cmd`）→ `action=futu_risk` → GCS `futu/risk/latest.json`、`futu/risk/history/<日期>.json`（私人，冇公開頁面）。
- Cloud Run 修訂 `zhuge-risk-manager-00271-nz5`（R147）；出事退回：`python3 scripts/gcp_agent.py rollback --to zhuge-risk-manager-00270-z5d --yes`。
- 定時任務「四陣持倉風險通報」（平日 09:45／12:45／16:45／21:45 HKT）喺本工作階段讀 `futu/risk/latest.json`，有變先通知風雲蛇地四陣；16:45 發每日摘要；鳥翔唔通知。

## 2026-10-11 風揚陣回覆
- HSI 10/16 週權 C24900／P23750 係風揚陣「方向一」真實倉（10/10 01:44 HKT 開），規則：持有到期、唔止損、唔對沖、唔加倉；10/16 現金結算後 16:30 再開下一輪，開倉前會睇 `futu/risk/latest.json` 嘅 `metrics.cushion`。
- 10/1 起 MHI2610 即日交易唔係風揚陣嘅（仲未知係邊個）。EW P7750 開倉計劃仍然未知。
- 各陣真實持倉登記：repo 根目錄 `POSITIONS.md`（風揚陣 PR #66）。

## 2026-10-11 使用者確認
- EW2610 P7750：使用者自己人手開，唔係任何陣／工作階段叫開；冇止損規則。
- 10/1 起 MHI2610 即日多手交易：使用者自己人手做。會即時改變恒指淨 Δ 同富途保證金緩衝；auto_risk 每 15 分鐘會影到。

## 2026-10-11 部署 R149（修訂 00273-gzd）
- Cloud Run 代發 Telegram：警報出現、升級（⚠→⛔）或解除先發（權杖只喺 Cloud Run）。
- 富途保證金緩衝警報（雲垂陣轉達使用者指示）：< 6 萬通知、< 2 萬危急（可能追繳／強平）、同級每再跌 1 萬再發、回 8 萬以上解除；狀態 `futu/risk/margin_alert.json`。
- 風險模型改用富途實際 MHI 淨手數（人手即日倉計入）。
- 退回：`python3 scripts/gcp_agent.py rollback --to zhuge-risk-manager-00272-njs --yes`

## Telegram bot（2026-10-11 使用者確認）
- **@HC_Gold_Signal_bot**＝Cloud Run 環境變數 `TG_BOT_TOKEN`：地載陣落單通知（R142）；R149／R151 富途風險、保證金、未配對警報亦經呢個 bot 發（使用者話唔使另設）。
- **@HC_HK_Signal_bot**＝GitHub Actions secrets `TG_BOT_TOKEN`：金絲雀、恒指／ES 波幅報告、高低位訊號、債市、佩洛西、股票數據等 workflow。
- 將來想富途警報改用 HK bot：喺 Cloud Run 加 `TG_HK_BOT_TOKEN`／`TG_HK_CHAT_ID`（`tg_send_hk` 會自動用），唔使改程式。

## 2026-10-11 部署 R151（修訂 00275-q4x，基於 R150）
- 策略總表「💼 富途實倉（按陣）」上線；配對規則 `FUTU_TEAM_RULES`（main.py）。
- 退回：`python3 scripts/gcp_agent.py rollback --to zhuge-risk-manager-00274-tnv --yes`
