# 文獻核對：月尾股債再平衡效應

> 使用者 11-14：「做文獻核對」；「如果係我哋新嘅研究發現，我哋可以將佢變成一個理論，然之後透過策略實證」。
> 第 1–3 節喺開始搜尋之前寫好並 commit（11-14 UTC）；之後各節逐步補。唔肯定嘅一律標「未核實」，唔作引用、唔作數字。

## 1. 研究問題

固定股債比例嘅機構喺月尾將組合調返目標比重，會唔會令股票指數喺月尾最後幾日出現可預測嘅回報？具體要核對我哋三個結果係咪已有文獻：

- **Q1 衰減**：效應逐段減弱（14 個市場策略每月淨：2010–15 +0.54%、2016–20 +0.33%、2021–26 +0.10%）；而且 1990 年代唔存在、2000 年後先出現。
- **Q2 唔對稱**：回報主要嚟自做多月份（股票當月跑輸債券），做空月份接近零。
- **Q3 多市場＋安慰劑**：14 個國家股指同向；同一規則搬去月中冇效應。
- 附帶：Q4 債券一邊冇對應壓力；Q5 偏離越大效應越強；Q6 季尾冇更強；Q7 跨地區相對再平衡冇效應。

## 2. 搜尋策略（事先定）

- **來源**：Google Scholar、SSRN、NBER、arXiv（q-fin）、RePEc／IDEAS、期刊網站（JF、JFE、RFS、JFQA、FAJ、JPM）；一般網絡搜尋做入口。
- **年份**：1985–2026。
- **關鍵字組合**（每組記日期、字眼、結果）：
  1. "pension fund rebalancing" month-end stock returns
  2. "rebalancing" "month-end" equity bond relative performance predict returns
  3. "The Unintended Consequences of Rebalancing" Harvey
  4. "turn of the month" effect stock returns international
  5. "predictable flows" front-running rebalancing decay
  6. "balanced funds" OR "target date funds" rebalancing price pressure equity
  7. "Dash for Cash" month-end liquidity Etula
  8. "end-of-month" reversal institutional rebalancing international evidence
  9. "quarter-end" rebalancing pension equity returns
  10. anomaly decay after publication "McLean" "Pontiff"（Q1 嘅一般文獻）
- **雪球法**：由核心論文向後（佢引用邊篇）同向前（邊篇引用佢）各睇一輪。

## 3. 納入／排除準則（事先定）

- **納入**：實證研究；研究月尾／月頭或者機構再平衡資金流同股票或者債券回報嘅關係；或者直接講可預測資金流被提前交易／異象衰減而可以解釋 Q1。期刊文章同工作論文都收，分開標示。
- **排除**：純日內微結構（同月尾無關）；冇數據嘅評論、博客、券商推廣文；只講個股層面指數調整（index reconstitution）而唔涉及股債配置；攞唔到公開摘要或者公開版本嘅（標「攞唔到」）。
- **只用公開版本**：摘要、工作論文、作者網頁；唔下載付費全文。

## 4. 搜尋紀錄（全部 2026-11-14 UTC；工具＝一般網絡搜尋，每次回最多約 10 條）

| # | 字眼（節錄） | 回條數 | 有用 |
|---|---|---|---|
| 1 | "The Unintended Consequences of Rebalancing" Harvey Mazzoleni Melone | 10 | 核心論文＋多個二手報道 |
| 2 | pension fund rebalancing month-end stock returns relative performance stocks bonds predict | 10 | Harvey 等、Etula 等、Graziani |
| 3 | "Dash for Cash" … Etula Rinne Suominen Vaittinen | 10 | 期刊版資料 |
| 4 | "turn of the month" … McConnell Xu | 10 | McConnell & Xu 2008 及引用文 |
| 5 | target date funds … Parker Schoar Sun | 10 | Parker、Schoar、Sun 2023 |
| 6 | Graziani "end-of-month" returns reversal … | 10 | Graziani 工作論文 |
| 7 | McLean Pontiff … post-publication decay | 10 | McLean & Pontiff 2016 |
| 8 | month-end rebalancing … international evidence … | 10 | 冇搵到專門做多國股債再平衡嘅研究 |
| 9 | front-running predictable institutional flows … weaker over time | 10 | Greenwood & Sammon（指數效應消失） |
| 10 | rebalancing … front-running … decline over time 2020s | 10 | 冇搵到直接測「月尾再平衡效應近年減弱」嘅研究 |
| 11 | Ogden 1990；Lakonishok Smidt；Ariel 1987 | 10 | 三篇經典嘅書目資料 |
| 12 | asymmetric price impact … month-end rebalancing buy vs sell | 10 | 只有一般買賣衝擊唔對稱文獻，冇月尾專題 |
| 13 | Harvey 等 subsample／asymmetry／international／Sharpe（加強搜尋） | 9 | 二手摘要；冇搵到分段、唔對稱、多國結果 |
| 14 | "Turn-of-the-Month Strategies: Do They Still Work" | 16 | 只見標題同副題 |
| 15 | month-end rebalancing exchange rates … Camanho Hau Rey | 10 | Camanho、Hau、Rey 2022 |
| 16 | "Can you Front-Run Institutional Rebalancing" | 10 | 業界重做（非學術） |

**重要限制**：呢個工作環境讀唔到論文原文。NBER、SSRN、RePEc、arXiv 喺 11-14 已經加入放行清單，但直接攞網頁嘅兩個做法都被權限系統擋咗。所以下面全部內容**只係根據搜尋結果嘅摘要同二手報道**，冇一篇讀過全文；所有數字都要讀原文核實先可以寫入論文。Google Scholar、期刊網站未能逐個搜；雪球法（第 5 步）未做。

## 5. 篩選流程（PRISMA 式）

| 階段 | 數量 | 備註 |
|---|---|---|
| 搜尋回條（16 次） | 約 165 | 有重複 |
| 去重後嘅獨立文獻／文章 | 約 40 | |
| 按標題／摘要排除 | 約 27 | 博客同券商文章 14；個股指數調整而同股債配置無關 5；買賣衝擊微結構 4；其他無關 4 |
| 納入（只憑摘要，未讀全文） | 13 | 見第 6 節 |
| 全文篩選 | 0 | 讀唔到原文（見第 4 節限制） |

## 6. 資料抽取表（全部「未核實」＝只見搜尋摘要）

| # | 文獻 | 市場／期間／數據 | 主要結果（照摘要） | 衰減？ | 唔對稱？ | 多國？ |
|---|---|---|---|---|---|---|
| 1 | Harvey, Mazzoleni & Melone (2025)，NBER WP 33554 | 美國；1997–2023；標普同美債期貨日線；模擬 60／40 組合 | 股票超配時再平衡者要賣股：「Threshold」同「Calendar」訊號升一個標準差，翌日股票回報跌約 16／17 bp，債券升約 2–3 bp；Calendar 訊號喺月尾最強；兩星期內回復；估計再平衡成本約每年 8 bp（約 160 億美元）；指出可預測所以會被提前交易 | 摘要冇講。有二手資料話樣本延長到 2025 結果「更強」（未核實） | 摘要冇講 | 摘要顯示只做美國（未核實） |
| 2 | Etula, Rinne, Suominen & Vaittinen (2020)，*RFS* 33(1), 75–111 | 多國（二手資料話 23 或 26 個市場；未核實）；約 1980–2013 | 機構月尾要現金 → 月尾前賣出，價格受壓，月頭回升；美股賣出期限喺 T−4；債券亦有類似型態 | 二手資料話利率極低時效應弱啲（未核實） | 方向係「月尾前受壓」，唔睇股債相對表現 | 有 |
| 3 | Parker, Schoar & Sun (2023)，*Journal of Finance* | 美國；目標日期基金持倉 | 目標日期基金逆住資產類別超額回報買賣；股市升得多之後，佢哋持有得多嘅股票回報較低；多數再平衡喺 3 個月內完成；2019 年目標日期＋平衡基金約 4 萬億美元 | 冇講效應衰減；有講基金規模增長 | 冇 | 冇 |
| 4 | Graziani（工作論文，2024）"Time Series Reversal" | 美國標普 | 月尾回報（第四個星期五至月尾）同下個月回報負相關；歸因退休金月尾付款 | 話同經濟週期有關 | 冇 | 冇 |
| 5 | McConnell & Xu (2008)，*FAJ* | 美國 1926–2005＋30 幾個國家 | 月尾最後一日加月頭三日佔咗絕大部分股票溢價；多數國家都有；債券冇 | 有二手資料話之後已減弱（未核實） | — | 有 |
| 6 | Ariel (1987)，*JFE* 18 | 美國 1963–1981 | 回報集中喺月頭前後 | — | — | 冇 |
| 7 | Lakonishok & Smidt (1988)，*RFS* 1 | 美國道指 1897–1986 | 月尾前一日到月頭第三日回報偏高 | — | — | 冇 |
| 8 | Ogden (1990)，*JF* 45 | 美國 | 用月頭付款集中解釋月頭效應 | — | — | 冇 |
| 9 | McLean & Pontiff (2016)，*JF* | 美國個股 97 個預測因子 | 樣本外回報低 26%、發表後低 58% | 有（一般異象） | — | 冇 |
| 10 | Greenwood & Sammon（*JF*，指數效應消失） | 美國標普成份股調整 | 納入效應由 1990 年代平均 7.4% 跌到近十年不足 1%；提前交易只解釋一部分 | 有（另一種可預測資金流） | 有報剔出效應亦消失 | 冇 |
| 11 | Camanho, Hau & Rey (2022)，*RFS* 35(11) | 全球股票基金持倉 | 外國股票跑贏 → 基金再平衡賣出 → 影響匯率 | — | — | 有（基金層面） |
| 12 | 買賣價格衝擊唔對稱文獻（大手交易、過渡交易等） | 個股 | 多數發現買入嘅永久衝擊大過賣出，但方向視乎環境 | — | 有（一般性） | — |
| 13 | 業界重做（QuantReturns、Quantitativo 等，非學術） | 美國期貨 | 重做 #1，報策略夏普比率大過 1（未核實、非同行評審） | — | — | 冇 |

## 7. 質素評估

| 文獻 | 樣本長度 | 樣本外 | 成本 | 多重檢定 | 發表狀態 |
|---|---|---|---|---|---|
| Harvey 等 (2025) | 約 27 年日線 | 摘要未見 | 有估成本 | 未知 | 工作論文（未知是否已刊登） |
| Etula 等 (2020) | 約 33 年、多國 | 多國當橫向驗證 | 有估損失 | 未知 | 期刊（RFS） |
| Parker 等 (2023) | 持倉數據 | — | — | — | 期刊（JF） |
| Graziani (2024) | 長樣本（二手話 45 年） | 未知 | 未知 | 未知 | 工作論文 |
| McConnell & Xu (2008) | 80 年＋多國 | 有分段 | 冇 | — | 期刊（FAJ） |
| McLean & Pontiff (2016)、Greenwood & Sammon | 長 | 核心就係樣本外 | — | — | 期刊（JF） |
| 我哋（#1463–#1503） | 16 年、14 個市場 | 時間樣本外唔過；新地區 9／9 同向 | 0.04%；真倉口徑另計 | 預先登記、全部報告，但同一批數據測咗好多條 | 未發表 |

## 8. 綜合：逐點對照

| 我哋嘅結果 | 判斷 | 理由 |
|---|---|---|
| 核心：股票當月跑輸債券 → 月尾幾日股票偏強 | **已有** | Harvey 等 (2025) 用美國期貨日線已經記錄，仲包括門檻訊號、成本估計同提前交易。唔可以寫「首次發現」 |
| 2000 年後先出現（1990 年代冇） | **部分已有** | Harvey 等樣本由 1997 開始；Parker 等記錄目標日期基金 2000 年後急增。未見有人直接用 1990 年代做對照 |
| Q1 近年減弱（2010–15 → 2021–26） | **似乎新，但有相反講法** | 冇搵到直接測呢點嘅研究；一般異象衰減（McLean & Pontiff）同指數效應消失（Greenwood & Sammon）係同類現象。**但二手資料話 Harvey 等延長到 2025 結果更強**——同我哋相反，可能因為規則唔同（佢哋係每日訊號睇翌日；我哋係倒數第 6 日入、揸 5 日）。一定要讀原文核對先可以寫 |
| Q2 做多做空唔對稱 | **似乎新（未核實）** | 摘要同二手資料都冇提；一般買賣衝擊唔對稱文獻存在，但冇月尾再平衡專題。要注意另一個解釋：月尾／月頭本身普遍偏升（McConnell & Xu），做空一邊係逆住呢個漂移 |
| Q3 14 個市場一致 | **部分已有** | 月尾／月頭效應喺 30 幾個國家已有（McConnell & Xu；Etula 等）。但用「股票對債券當月相對表現」做訊號嘅多國證據，未搵到 |
| Q3 月中安慰劑 | **似乎新（未核實）** | 未見；Harvey 等有講 Calendar 訊號月尾最強，性質接近 |
| Q4 債券一邊冇反方向壓力 | **同文獻有出入** | Harvey 等報債券翌日升約 2–3 bp（方向符合機制）。我哋睇 5 日回報搵唔到。可能係效應細、時間窗唔同 |
| Q5 偏離越大效應越強 | **部分已有** | Harvey 等嘅訊號本身係連續變數（偏離越大訊號越強） |
| Q6 季尾冇更強 | 未見對照 | Harvey 公開講過月尾同季尾再平衡都有問題；未見數字 |
| Q7 跨地區相對再平衡冇效應 | 未見對照 | Camanho 等喺基金層面搵到跨國再平衡影響匯率，但唔係月尾指數回報 |
| Etula 等嘅「月尾前賣壓」 | **要處理嘅競爭解釋** | 佢哋預測月尾前普遍受壓、月頭反彈，同股債相對表現無關；我哋 #1499（只睇美債訊號都有效）同 #1494–#1497（月頭回吐唔顯著）可以用嚟區分 |

**研究缺口（暫定，全部要讀原文確認）**：(i) 月尾再平衡效應嘅時間變化——出現（約 2000）同減弱（2021 後）；(ii) 多空唔對稱同佢嘅成因；(iii) 「股債相對訊號」嘅多國面板同月中安慰劑。

## 9. 參考文獻（APA；連結＝搜尋見到嘅公開頁面；全部未讀原文）

- Ariel, R. A. (1987). A monthly effect in stock returns. *Journal of Financial Economics, 18*, 161–174.
- Camanho, N., Hau, H., & Rey, H. (2022). Global portfolio rebalancing and exchange rates. *Review of Financial Studies, 35*(11), 5228–5274. https://www.nber.org/papers/w24320
- Etula, E., Rinne, K., Suominen, M., & Vaittinen, L. (2020). Dash for cash: Monthly market impact of institutional liquidity needs. *Review of Financial Studies, 33*(1), 75–111. https://doi.org/10.1093/rfs/hhz054
- Graziani, G. (2024). *Time series reversal: An end-of-the-month perspective* [Working paper]. https://csef.it/wp-content/uploads/JMP_GG_02Nov2024.pdf
- Greenwood, R., & Sammon, M. (年份、卷期未核實). The disappearing index effect. *Journal of Finance*. https://www.nber.org/system/files/working_papers/w30748/w30748.pdf
- Harvey, C. R., Mazzoleni, M. G., & Melone, A. (2025). *The unintended consequences of rebalancing* (NBER Working Paper No. 33554). https://www.nber.org/papers/w33554
- Lakonishok, J., & Smidt, S. (1988). Are seasonal anomalies real? A ninety-year perspective. *Review of Financial Studies, 1*, 403–425.（年份有來源寫 1989，未核實）
- McConnell, J. J., & Xu, W. (2008). Equity returns at the turn of the month. *Financial Analysts Journal*.（卷期未核實）
- McLean, R. D., & Pontiff, J. (2016). Does academic research destroy stock return predictability? *Journal of Finance*.（卷期未核實）
- Ogden, J. P. (1990). Turn-of-month evaluations of liquid profits and stock returns: A common explanation for the monthly and January effects. *Journal of Finance, 45*, 1259–1272.
- Parker, J. A., Schoar, A., & Sun, Y. (2023). Retail financial innovation and stock market dynamics: The case of target date funds. *Journal of Finance*.（卷期未核實）https://www.nber.org/papers/w28028
