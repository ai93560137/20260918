# 文獻篩完只剩兩個外匯新候選

**結論先講。** 把外匯學術文獻（風險溢酬、事件、日內、波動率、其他機制四條線）過一遍，再拿團隊 17 條已判決的清單和富途戶口限制（BP ≈ USD 5,700、只有 CME 期貨與美股 ETF 期權、一口 M6E 來回 ≈ 4.1 基點、名義 ≤ 3 倍本金、無現貨無期貨期權）去篩，**真正值得「預先登記後只跑一次」的新候選只有兩個：Karnaukh 的 FOMC 前兩日條件式美元漂移，和 Colacito–Riddiough–Sarno 的產出缺口時間序列訊號**；第三個（Mueller–Tahbaz-Salehi–Vedolin 的 FOMC 當日空美元溢酬）量級未經核實，只能排在後面。更重要的發現是：**文獻獨立證實了團隊帳本上的每一個 ☠️**——利差、動量、價值、美元利差擇時、日內時段、COT——全都在 2010 年後或發表後衰退到接近零，團隊不是測錯，是測對了。兩個新候選的經濟規模都小（一口微型合約一年約 USD 150–600 毛利），它們的價值在於機制新、帳本上沒跑過、月頻／事件頻能扛住 4 基點成本；登記前有幾個關鍵數字（Karnaukh 的視窗與門檻定義、Colacito 的缺口建構）必須先從全文核實，因為四位研究員都開不到 PDF，所有數字來自摘要與二手摘錄。

---

## 一、執行摘要：排序後的候選清單

### 為什麼篩完這麼少

戶口限制把可行集合壓得很窄。一口 M6E（12,500 歐元 ≈ USD 14,400）已接近 3 倍本金上限，所以**只能單一合約、單一貨幣對**，任何籃子（橫截面）策略都不可行；標準 6E 雖然來回只有 1.4 基點，但 24 倍槓桿違反家規；FXE／FXY／FXA 期權鏈平均報價價差 **73% of premium、FXE 日量 192 口、FXA 約 10 口**，實務上不可用 ([OptionsAnalysisSuite FXE](https://www.optionsanalysissuite.com/etf/fxe/options-chain); [Macroption](https://macroption.com/currency-etf-options))；戶口沒有期貨期權，所以 6E 期權也不在選項內。研究員用合約規格重算：M6E 來回 ≈ 4.0 基點（手續費 3.1 + 一檔價差 0.87），M6B／M6J ≈ 6–7 基點、M6A ≈ 8.5 基點；用夏普 1、波動 8% 的策略推算，**要清掉 40 基點的 10 倍成本門檻，持有期至少 13 個交易日（M6E）**，日頻策略在數學上就已出局 ([CME M6E 規格](https://cmegroup.com/trading/fx/e-micros/e-micro-euro_contractSpecs_futures.html); [CME 2023 價差數據](https://www.cmegroup.com/articles/2023/unlocking-potential-during-asian-trading-hours-with-cme-fx-futures.html))。

### 排序表

| 排名 | 候選 | 機制 | 文獻量級（樣本） | 2015 後存活證據 | 戶口可行性 | 帳本狀態 | 登記優先序 |
|---|---|---|---|---|---|---|---|
| **1** | **FOMC 前兩日條件式美元漂移**（Karnaukh） | 政策資訊先反映在聯邦基金期貨，數日後才進匯市 | 每事件 **+25 基點、t 2.8、夏普 0.93**；升息前美元 +20bp、降息前 −32bp（1990 年代中至 2016–18，確切起訖未核實） | **無已發表的 2018 後樣本外檢定**；FRL 2021 說無條件式 pre-FOMC 漂移在匯市不存在（到 2019），但那是另一個假設 | 一口 M6E、持有 ≈ 2 日、每年 ≤ 8 次；毛 20–32bp vs 成本 4.1bp ≈ 5–8 倍（未達 10 倍，過 25% 規則） | **不在帳本**；22 格日曆掃描沒含 FOMC 條件 | **第一** |
| **2** | **產出缺口時間序列（EURUSD 月頻）**（Colacito–Riddiough–Sarno） | 強經濟貨幣有較高期望報酬，補償景氣循環風險；報酬主要來自即期可預測性 | 時序版 **夏普 0.65 毛／0.50 淨**；橫截面 0.72／0.50；合併 0.82（摘錄寫 1999–2016，未核實） | 無 2016 後再檢定；vendor 回測給夏普 0.03（方法未公開，衝突） | 一口 M6E、月換倉；夏普 0.5 × 8% 波動 ≈ 33bp／月毛 vs 4.1bp + 每季轉倉 ≈ 4bp | **不在帳本**：G7 月頻表用盡的是價格、利差、價值、動量、利率變動、期限利差、VIX、COT，沒有產出缺口 | **第二**（先讀全文定義缺口） |
| 3 | FOMC 公告日空美元（Mueller–Tahbaz-Salehi–Vedolin） | 受限的金融中介在公告日承擔美元需求，收溢酬 | 十大貨幣、1994–2013、16:00→16:00 紐約；「顯著更高」的超額報酬與夏普，**基點數未能讀到** | 無；兩篇匯市研究說 pre-FOMC 多外幣的漂移有 65–75% 在公告後 12–24 小時反轉 | 一口 M6E、持有 1 日；每事件毛要 ≥ 16bp 才過 25% 規則，**量級未知** | 不在帳本；與候選 1 共用事件樣本 | 候選 1 跑完後再決定 |
| 對照 | 歐元一個月方差賣方（已 🔍） | IV 系統性高於 RV | EURUSD 1M／3M 方差溢酬顯著；**USDJPY 不顯著**；外匯空波動夏普 ≈ 0.5 | 無 2015 後逐貨幣估計 | **富途戶口無法執行**：無期貨期權、FXE 價差 73% | 🔍 維持 | 不新登記；A 階段半價差必須在別的券商做；**不要加日圓腿** |

### 候選 1：Karnaukh 條件式 pre-FOMC 美元漂移

Karnaukh 的工作論文（2016–2018 版本）發現：排定 FOMC 會議前，若聯邦基金期貨指向升息，美元在公告前兩日平均升 ≈ 20 基點；指向降息則貶 ≈ 32 基點；期貨價差在會前三天就能預測接下來兩天的美元方向（R² 22%）；一個簡單策略每事件 **+25 基點、t 2.8、年化夏普 0.93**，作者解釋為政策資訊先進固定收益、再進匯市 ([Karnaukh PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0019/190315/DollarAheadFOMC_NinaKarnaukh.pdf); [AEA 2017 版](https://topcat.aeaweb.org/conference/2017/preliminary/paper/RAK7GsSa); [Macrosynergy 摘要](https://macrosynergy.com/?p=41075))。這是文獻裡**唯一每筆毛利比 4 基點成本高一個數量級的匯市規律**。它與帳本上的 ☠️「日曆／時段規律掃描」不同：那個掃描是無條件的（時段、星期、月底、月份），這個是以期貨訊號為條件的事件研究；與 FRL「消失的 pre-FOMC 漂移」也不衝突——那篇檢定的是 Lucca–Moench 式無條件漂移，在匯市本來就不存在 ([FRL 2021](https://www.sciencedirect.com/science/article/abs/pii/S1544612320315956); [Lucca–Moench](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf))。弱點有三：2009–2015 與 2020–2021 幾乎沒有預期中的目標變動，有效事件數會少；用 EURUSD 單一對表達美元籃子會多一層雜訊；**沒有任何已發表的 2018 後樣本外檢定**。

**可登記規格（一次跑完）。** 假設：排定 FOMC 公告前，聯邦基金期貨隱含的目標利率變動方向預測 EURUSD 在公告前兩個交易日的方向（預期升息 → 做空 M6E；預期降息 → 做多 M6E）。訊號：公告日 T 的 T−3 收盤，用當月與次月 ZQ 結算價算隱含目標變動 Δ；|Δ| ≥ 12.5 基點才交易，否則不進場（12.5 是預先寫死的單一門檻，不掃）。進出：T−2 紐約 17:00 進場，T 日紐約 13:00（聲明前一小時）出場；扣每筆 4.1 基點。樣本：2003-08 → 2026-08 全部排定會議（配合現有 EURUSD H1 資料）。主檢定：事件淨報酬均值 t ≥ 2.5（帳本新樣本慣例）；附加條件：2015 後子樣本均值同號。**登記前必須做的一件事**：從全文確認論文的視窗（兩日是 T−2/T−1 還是含 T 公告前）與條件門檻定義，若與上述不同，以論文為準改寫後再登記——這是讀文獻定規格，不是看數據調參數。

### 候選 2：產出缺口時間序列，EURUSD 月頻

Colacito、Riddiough 與 Sarno（JFE 2020）發現做多強經濟（高產出缺口）、做空弱經濟貨幣在橫截面和時間序列都賺，報酬主要來自即期匯率的可預測性，與常見貨幣策略不相關；**時序版夏普 0.65 毛／0.50 淨，橫截面 0.72／0.50，合併 0.82** ([NBER w26299](https://www.nber.org/system/files/working_papers/w26299/w26299.pdf); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X20301203); [VoxEU](https://cepr.org/voxeu/columns/strong-economy-strong-currency))。Riddiough 的單作者版本給出已開發國家五分位排序夏普 0.68 ([AUT PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0004/105439/82946-S-RIDDIOUGH-BusCycles.pdf))。它是研究員找到的**唯一明確報出淨成本夏普、而且訊號變化慢到月換倉就夠的總體策略**。和帳本的關係很乾淨：團隊在 G7 月頻表上用盡的是價格、利差、REER 價值、動量、利率變動、期限利差、VIX、COT 八個變數，產出缺口（實體經濟活動）不在其中；它也不是 ☠️「央行利率路徑」的變形，因為訊號是 IP 缺口不是利率。弱點：paperswithbacktest 的重跑只給夏普 0.03，方法未公開但暗示對資料版本（即時 vs 修正後的 IP）極敏感 ([paperswithbacktest](https://paperswithbacktest.com/strategies/business-cycles-and-currency-returns))；單一貨幣對的時序版一定比論文的籃子弱；而且時序版本質上是「歐元 vs 美元」的方向性賭注，有和美元利差擇時同樣的政權脆弱性。

**可登記規格（一次跑完）。** 假設：歐元區相對美國的產出缺口為正時，下月 EURUSD 超額報酬為正。訊號：每月最後交易日，用公布延後兩個月的歐元區與美國工業生產指數，缺口 = log IP 對過去 60 個月線性趨勢的偏離（只用當時可得的資料，不用 HP 全樣本濾波避免前視）；相對缺口 = 歐元區缺口 − 美國缺口；> 0 做多一口 M6E 持有一個月，< 0 做空；季度到期前一週轉倉，扣每筆 4.1 基點、每季轉倉 4 基點。樣本：1999-01 → 2026-08。主檢定：月報酬 t ≥ 2.5；若團隊認定 EURUSD 月頻屬 21 對 D1 籃子的子集，依帳本改 t ≥ 3。附加條件：2013 後子樣本均值同號。**登記前必須做的一件事**：讀全文確認論文的缺口建構（資料來源、濾波、延後月數）與時序規則的確切定義（缺口 > 0 還是 > 美國），然後把登記規格改成論文的版本；上面的 60 個月線性趨勢只是沒有全文時的保守代理。

### 候選 3：FOMC 公告日空美元溢酬

Mueller、Tahbaz-Salehi 與 Vedolin（JF 2017）：做空美元、做多其他貨幣的策略在排定 FOMC 公告日賺到顯著更高的超額報酬；對利差較大的貨幣更大，在貨幣政策不確定性高、聯準會寬鬆時更大；樣本十大貨幣、1994-01 → 2013-12、紐約 16:00 到 16:00；報酬「橫跨整個公告日，含公告前與公告後兩段」 ([Kellogg PDF](https://www.kellogg.northwestern.edu/faculty/alirezat/FXAnnouncements.pdf); [SSRN 摘要](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2705818))。問題是**每事件的基點數與 t 值在任何摘錄裡都看不到**，而且兩篇匯市高頻研究（Wang；「Jumps and Post-FOMC」2025）都說 pre-FOMC 多外幣的漂移有 65–75% 在公告後 12–24 小時被反轉 ([Georgia Tech](https://hg.gatech.edu/node/605767); [ResearchGate](https://www.researchgate.net/publication/392575747_Jumps_and_Post-FOMC_Announcement_Returns_in_Currency_Markets))。歐元對美元利差小，照論文邏輯是最弱的表達；澳幣是最強的但 M6A 來回 8.5 基點。

**可登記規格。** 假設：排定 FOMC 公告日 EURUSD 超額報酬為正。規則：T−1 紐約 16:00 做多一口 M6E，T 紐約 16:00 平倉，所有排定會議 2003-08 → 2026-08，扣 4.1 基點；主檢定 t ≥ 2.5。它與候選 1 共用 FOMC 事件樣本，帳本要記兩次；建議候選 1 先跑，候選 3 只在候選 1 判決後、且仍有登記預算時再提。

---

## 二、文獻說已死的，帳本早已埋了

這一節的價值不是新資訊，而是**獨立確認**：團隊用自己的資料殺掉的東西，和 2022–2025 年學界用 McLean–Pontiff 方法在外匯上得到的結論一致。

| 帳本 ☠️ | 團隊數字 | 文獻獨立確認 |
|---|---|---|
| G7 利差 top3／bottom3 | t 0.11；加價 0% 才 t 1.04 | Fan 等（JIFMIM 2022，G10 1977–2019）：「效率利差」夏普 GFC 前 1.08 → **GFC 後 0.25** ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1042443121001670))；Hutchinson 等（IRFA 2022）：利差、動量、價值複製後**發表後平均夏普 +0.39 → −0.32** ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4024296))；Hsu–Taylor–Wang（JIMF 2024，48 貨幣）：校正資料窺探後，一期賺的利差策略下一期通常不賺，成功「主要靠運氣」 ([IDEAS](https://ideas.repec.org/a/eee/jimfin/v143y2024ics0261560624000299.html)) |
| 12 個月 TSMOM；橫截面 12 個月動量 | t −0.69；橫截面單獨 t −1.21／−2.2 | Hutchinson 等技術規則組合夏普 **0.66 → 0.06** ([IDEAS](https://ideas.repec.org/a/eee/riibaf/v63y2022ics0275531922001659.html))；Zhang（JFE 2022）：貨幣動量基本上是利差／美元因子的自相關 ([IDEAS](https://ideas.repec.org/a/eee/jfinec/v144y2022i1p154-173.html))；Menkhoff 等的 0.95 夏普是 48 貨幣、偏向寬價差貨幣，G10 版本遠弱於此 ([BIS WP 366](https://www.bis.org/publ/work366.pdf))；週頻動量損益兩平成本低至 **2 基點**，零售不可行 ([Raza 等](https://www.sciencedirect.com/science/article/abs/pii/S0261560614000400)) |
| BIS REER 價值 | t 0.04／−1.0 | 同 Hutchinson 等：「貨幣不再對實質匯率差異反應」；Baltussen 等 200 年複製樣本外匯價值夏普只有 0.34 ([SSRN](https://papers.ssrn.com/abstract=3325720)) |
| 美元利差擇時（美國 3 個月 vs 7 外幣平均） | t −0.06；23 年只換 3 次方向 | 這就是 LRV 2014 的「dollar carry」（發表夏普 0.66）；Quantpedia 承認 2008–2018「明顯下降」 ([Quantpedia](https://quantpedia.com/the-impact-of-the-inflation-on-the-performance-of-the-us-dollar/))；第三方重跑夏普 0.12 與 −0.37 ([QuantConnect](https://www.quantconnect.com/terminal/quantpediaBacktestResult/embedded_backtest_2d8aa85733eb1e674cdc634c4b464c7c.html))；**沒有任何同行評審的 2010–2026 樣本外檢定** |
| 央行利率路徑、期限利差 | t −1.0／−1.22 | Lustig–Stathopoulos–Verdelhan（AER 2019）：利差溢酬只活在短端，10 年期 slope carry −1.96% 不顯著 ([AER](https://www.aeaweb.org/doi/10.1257/aer.20180098))；Engel 等（JIMF 2019）懷疑 Taylor 法則基本面的樣本外證據 ([NBER w24059](https://www.nber.org/system/files/working_papers/w24059/w24059.pdf)) |
| CFTC COT 反向 | F1 t −1.52、F3 1.41 | Aalto 論文：COT 極端持倉反向在股指有效，「貨幣與能源期貨只有邊際正報酬、無統計顯著」 ([Aalto](https://aaltodoc.aalto.fi/items/b84b07d6-3bd2-4040-bbcf-052b938b1f74))；ING 2022：COT 持倉「可能已失去部分解釋力」 ([ING](https://think.ing.com/downloads/pdf/article/fx-positioning-g10-currency-currencies-pairs-ukraine-volatility)) |
| 日曆／時段 22 格掃描；L1 EURUSD 09–12 UTC 做空（已放棄） | 最大 \|t\| 2.65；L1 毛 +1.88bp／日、歐元 −1.11bp／日 | **團隊的 L1 就是 Breedon–Ranaldo 效應**：貨幣在本地交易時段貶值，EUR/USD 是唯一扣銀行間價差後仍賺的對 ([SNB WP 2011-04](https://www.snb.ch/en/publications/research/working-papers/2011/working_paper_2011_04); [CXO](https://www.cxoadvisory.com/currency-trading/daily-currency-exchange-pattern/))；Krohn–Mueller–Whelan（JF 2024）：倫敦定盤後至紐約收盤 EUR 每日 +2.7bp、美元組合 1.8bp，21 年每年都在，但**不會延伸到收盤對收盤** ([Warwick 稿](https://wrap.warwick.ac.uk/id/eprint/177333/1/WRAP-foreign-exchange-fixings-returns-around-clock-Mueller-2023.pdf))。機制真、量級 1.5–2.7bp／日，4 基點成本下不可交易——與團隊放棄的理由完全一致 |
| 定盤／月底 | （未測） | 分鐘級定盤反轉 2015 年視窗拉寬後「完全消失」 ([FCA OP46](https://www.fca.org.uk/publication/occasional-papers/occasional-paper-46.pdf))；Melvin–Prins 月底效應每 10% 相對股市超額才 ≈ 14bp，且 72% 次日中午前反轉 ([ECB 工作坊稿](https://ecb.eu/events/pdf/conferences/131216/Third_FX_Workshop_MELVIN_PRINS_Equity%20hedging%20and%20exchange%20rates%20Nov%202013.pdf))——不必測 |
| NFP／CPI | （未測） | 驚奇驅動的即時跳動，無事後漂移；GBP/USD NFP 交易系統「無可利用型態」 ([Bangor](https://research.bangor.ac.uk/en/publications/predictable-responses-in-currency-markets-to-macroeconomic-news-a/))；Faust 等：美元因強數據升值「預期會被超額反轉」 ([Fed IFDP 784](https://www.federalreserve.gov/pubs/ifdp/2003/784/ifdp784.pdf))——不必測 |

一個對帳本有用的細節：團隊的利差測試死在券商 swap 加價（加價 0% t 1.04、1.25% t −1.0）。CME 期貨把利差嵌在遠期曲線、沒有每日加價 ([CME 2026](https://www.cmegroup.com/news/2026/fx-financing-costs-understanding-the-difference-between-cfds-and-futures-pricing.html))，換到富途期貨等於回到「加價 0%」口徑——但那個口徑也只有 t 1.04，所以**換工具救不回利差**，不要因為換了券商就重登記。

另外幾個文獻上活著、但戶口進不去的機制，列出來免得之後有人再提：CLS 訂單流策略（2012–2017 扣成本仍賺）要專有資料 ([AEA 2019](https://aeaweb.org/conference/2019/preliminary/paper/BRGT7QFZ))；USD/HKD 區間邊緣每輪 64–128 基點但無上市工具且 7.85 側負利差 0.5–1.5% ([HKMA 2025-06](https://www.hkma.gov.hk/eng/news-and-media/press-releases/2025/06/20250626-4/))；期權隱含波動排序（Fullwood–James–Marsh 夏普到 1.38）與偏度溢酬（G10 GFC 後不顯著）都要 OTC 期權 ([City](https://openaccess.city.ac.uk/id/eprint/24959/); [Li–Sarno–Zinna](https://www.bayes.citystgeorges.ac.uk/__data/assets/pdf_file/0011/889229/Li-Sarno-and-Zinna.pdf))；避險日圓／瑞郎在股市衝擊後的反應是同期的、文獻沒給每事件量級，寫不出門檻 ([SNB WP 2007-17](https://www.snb.ch/en/mmr/papers/id/working_paper_2007_17))；商品→加幣／澳幣的延遲預測力「稍縱即逝」 ([NBER w17998](https://www.nber.org/papers/w17998.pdf))。

---

## 三、誠實的限制：所有數字都是摘要級

四位研究員在這個環境裡**沒有一位能打開任何學術全文**（NBER、SSRN、ScienceDirect、Wiley、BIS、ECB、Fed、各大學典藏庫的 CONNECT 全部 403），搜尋額度也在約 45 次查詢後用盡；所有量級來自摘要、會議稿摘錄、搜尋引擎片段與二手整理（Quantpedia、CXO、Alpha Architect、paperswithbacktest、blog）。表格、t 值、子樣本結果一律沒讀到。下面是登記任何東西前必須先補的洞，按候選排：

**候選 1（Karnaukh）。** 論文確切樣本起訖、「兩日」視窗的定義（進出時點）、條件式訊號的門檻（期貨隱含多少基點算「預期升息」）、是用美元指數還是逐貨幣、是否扣成本、有沒有 2015 後子樣本——全部未讀到；Macrosynergy 的「1990 年代中以來」是唯一的樣本提示。25bp／t 2.8／夏普 0.93 三個數字來自 AUT 鏡像 PDF 的搜尋摘錄，應視為「待核實」。**沒有任何已發表的 2018 後樣本外複製**。

**候選 2（Colacito 等）。** 產出缺口怎麼建（資料來源、濾波、即時或修正後）、時序規則的確切定義、1999–2016 是否為全樣本、逐貨幣結果——未讀到；0.65／0.50／0.72／0.50／0.82 來自 NBER 摘錄。paperswithbacktest 的夏普 0.03 與論文衝突，方法未公開；這種落差通常來自資料版本與公布延後，必須在登記規格裡寫死延後月數。

**候選 3（MTV）。** 每事件基點數、t 值、年化夏普、逐貨幣結果、是否報告 ECB／BoE／BoJ——全部未見；只知「顯著更高」。兩篇反轉研究（Wang；Jumps 2025）的作者、樣本、量級也未讀到。

**成本與工具。** M6E 來回 4.1 基點是用合約規格和 FY2022 標準合約價差推算的，**沒有任何 2025–2026 微型合約逐產品的成交量／未平倉數據**（CME 頁面被擋或空白）；M6J 的 tick 慣例在 2010 年售品單和券商表格之間有衝突；富途除 6E／M6E 外其他微型合約是否上市、6E 期權確定不可交易，都要在戶口裡直接確認。

**衰退文獻。** Bartram 等（JFQA 2025）發表後衰退的百分比、Hutchinson 等的樣本內／外切點都未讀到；Burnside 等的淨夏普在不同版本間單位不明。這些不影響「已死」結論的方向，只影響精確度。

**VRP 對照。** EUR、JPY、AUD、GBP、CHF、CAD 逐貨幣的 1M IV−RV 波動點數沒有一張表被讀到；Della Corte 等的「平均 1.15」單位未確認；沒有同行評審的 2015–2026 樣本估計。團隊自己的 EVZ 與 IB 數據是目前最好的來源。

---

## 四、下一步：先登記 Karnaukh，資料缺口在聯邦基金期貨

**先登記候選 1**，理由是它的每筆毛利最大、持有期最短（成本最不吃）、樣本與帳本上任何東西都不重疊、而且跑一次的工程量最小。**候選 2 排第二**，但在讀到 Colacito 等全文、把缺口建構改成論文版本之前不要登記——用代理規格登記再回頭改，就是團隊反對的那種事後調整。候選 3 等候選 1 判決後再議。

雲垂 VM 上的 IB 管線需要補的資料：

| 候選 | 需要的資料 | 現況／難點 |
|---|---|---|
| 1 | 排定 FOMC 會議日期與聲明時間，2003 → 2026 | 聯準會官網，手工 CSV 即可；聲明時間歷年有變，逐年核對後寫進登記文件 |
| 1 | 30 天聯邦基金期貨（ZQ）當月與次月每日結算價，2003 → 2026 | **主要阻礙**：IB 對已到期期貨的歷史回補有限，可能要 CME DataMine 或 Nasdaq Data Link 連續合約；沒有這個就不能算 Δ，候選 1 就不能跑 |
| 1、3 | EURUSD H1，2003-08 → 2026-08 | 已有（Dukascopy／HistData），用現成的 |
| 1、3 | 6E／M6E 小時 bar（選配） | 用來驗證事件窗內的實際價差，IB 可取近年 |
| 2 | 美國工業生產（INDPRO）含 ALFRED 版本 | FRED／ALFRED 免費，可做真正的即時資料 |
| 2 | 歐元區工業生產月頻，1998 → 2026 | Eurostat／ECB SDW；**版本資料難取**，登記時用「公布延後兩個月」當保守代理並寫明 |
| 2 | EURUSD 月收盤 1999 → 2026 | 已有 |
| 全部 | 富途：M6E 以外微型合約上市清單、6E 期權不可交易的書面確認、M6E 實際成交價差抽樣（倫敦／紐約重疊時段） | 戶口內直接查，一次做完 |

帳本更新建議：新增兩個樣本列——「FOMC 事件樣本 EURUSD 2003–2026」（候選 1 與 3 共用，第一次門檻 t ≥ 2.5、第二次 t ≥ 3）與「EURUSD 月頻時序 1999–2026」（候選 2，t ≥ 2.5 或依團隊認定 ≥ 3）。

---

## 結論

這輪文獻篩選最有價值的產出不是候選，而是確認：外匯學界在 2022–2025 年用更大的樣本、更嚴的資料窺探校正，得到與團隊 17 條判決相同的結論——利差、動量、價值、美元擇時、日內時段、COT 在 2010 年後或發表後接近零。團隊的 L1 線索甚至精確對應到 Breedon–Ranaldo 與 Krohn 等人的機制與量級（每日 1–3 基點），放棄它是對的。這表示團隊的檢定流程是可信的，往後不需要再用海選去「找找看」：文獻裡能活、戶口裡能做、帳本上沒跑的東西，就是兩個——而且兩個都有一個共同特徵，訊號來自匯市以外（利率期貨、實體經濟），這與 Karnaukh「資訊先進固定收益再進匯市」和 Colacito「報酬來自即期可預測性」的機制一致，也是它們還沒被套利掉的最合理解釋。

要有心理準備的是規模：一口 M6E 上，候選 1 每年約 5–8 個有效事件、每事件淨 ≈ 20 基點，約 USD 150–250；候選 2 若達論文淨夏普的一半到全部（0.25–0.5、波動 8%），約 USD 300–600。它們的意義是驗證兩個新機制是否在這個戶口的成本下活著，不是讓 USD 5,700 翻倍；若其中一個過了 t ≥ 2.5，下一步才是討論加大規模。
