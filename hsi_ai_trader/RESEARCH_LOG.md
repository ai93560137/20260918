# 🐉 龍飛陣每日網上研究紀錄

使用者 10-27：「每一日都自己喺網上面找尋一啲新的研究方法，比時間表更早完成進度。」
規矩：
- 每日最少搵 1 個新方法或者研究（論文、可信嘅回測、交易所資料）。
- 寫低來源、重點、同我哋數據有冇衝突、下一步。
- 值得試嘅就先登記 IDEAS（預先定成功標準）再回測，唔會直接上真倉。
- 網上嘅說法當線索，唔當證據；冇樣本、冇扣成本嘅結果要講明。

| 日期 | 來源 | 重點 | 同我哋數據 | 下一步 |
|---|---|---|---|---|
| 10-27 | [MQL5：重做 Zarattini & Aziz 開市區間突破論文（5 隻指數，2015–2026）](https://www.mql5.com/en/blogs/post/776235) | 未扣成本可以重現（NQ 約 +0.13R／單），扣成本後 5 隻都同 0 分唔開，4 隻係負 | 一致：#130 樣本外 −0.13R、#131 反做更差、長歷史順勢 −0.03R ≈ 成本 | 唔再喺開市區間突破上面花時間；入場研究轉向「回調入場＋闊止蝕」 |
| 10-27 | [arXiv 2605.04004：MNQ 期貨 OHLCV 日內動能訊號證偽研究](https://arxiv.org/pdf/2605.04004) | 20 點止蝕下，回調入場有 80.7% 被止蝕；作者解讀為訊號多數捉到假突破之後嘅反轉 | 一致：MHI 舊規則 30–75 點止蝕 5 筆全部蝕；6/19 筆一入場就錯 | IDEAS #136 入場研究要同時試「闊止蝕」，唔好只改入場；記住「回調入場」唔係萬能 |
| 10-28 | [Lucca & Moench：The Pre-FOMC Announcement Drift（NY Fed SR 512）](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.html)；[Hu, Pan, Wang & Zhu 2022（JFE）](https://www.mit.edu/~zhuh/HuPanWangZhu_preannouncement.pdf) | 美股議息公佈前 24 小時有異常正回報；非農、ISM、GDP 公佈前都有類似隔夜正回報；Liberty Street 話 2011 後只係有記者會嗰啲會議先明顯 | 未驗證：文獻冇點名恒指。MHI 真倉 10-28 揸淡倉過今晚 FOMC，如果恒指都有正漂移即係逆住佢 | 登記 IDEAS #144 A，用 ^HSI 日線 2020 起驗（Actions） |
| 10-28 | [Fernandez-Perez, Frijns & Tourani-Rad 2017（J. Empirical Finance）](https://openrepository.aut.ac.nz/handle/10292/9444)；[Barchart：Trading on FOMC days](https://www.barchart.com/story/news/32925480/trading-on-fomc-days)（實務評論，唔係研究） | 公佈後約 45 分鐘內波動先升後回落；公佈前成交淡、易假突破，公佈後容易來回掃止蝕 | 一致：10-27 夜市 FOMC 前全晚窄幅（23040–23085）。冇搵到量度指數期貨事件日止蝕被掃比率嘅論文 | IDEAS #144 B 驗恒指公佈後第一日跳空同幅度；結果決定使唔使提案延長 R348 封鎖 |
| 10-29 | [Tang & Lui 2002：恒指同期貨嘅日內／週內波動模式（HKBU）](https://scholars.hkbu.edu.hk/en/publications/intraday-and-intraweek-volatility-patterns-of-hang-seng-index-and-2/)；[Fong & Frino：恒指期貨喺現貨收市前後嘅波動（Deakin）](https://www.deakin.edu.au/__data/assets/pdf_file/0018/402624/swp2004_08.pdf) | 恒指開市後頭 15–30 分鐘波動明顯高過期貨，主要係雜訊交易；現貨收市後期貨波動下降、期貨收市前再升 | 一致：我哋一年 1 分鐘數據（IDEAS #147）09:30–09:31 平均幅度 88 點（平時 17 點），09:31–09:35 係平時 2.9 倍；10-28 真倉 09:30 入場成交差 33 點 | 提案 MHI 真倉 09:28–09:36 同 09:15–09:20 唔開新倉（要使用者批） |
| 10-29 | [ProRealCode：Breakeven vs MFE](https://www.prorealcode.com/topic/breakeven-vs-mfe/)；[StockSharp 保本＋移動止蝕範例](https://doc.stocksharp.com/en/api-examples/2135_Breakeven_Trailing_Stop)（實務，唔係研究） | 保本觸發同移動止蝕啟動應該分開設；回測用收市價判斷保本會高估 MFE、錯判有冇觸發，要用高低價 | 相關：10-29 真倉最多浮賺 132 點（1.1R）觸發保本，未到 165 點移動止蝕，最後 +2 點平。冇搵到比較啟動距離嘅正式研究 | 用 swing_check.py 數據比較移動止蝕啟動 120／165 點（要先預先登記）；回測已經用高低價，冇呢個偏差 |
| 10-30 | [Grant, Wolf & Yu 2005：美國指數期貨日內價格反轉 15 年研究（J. Banking & Finance）](https://researchwith.montclair.edu/en/publications/intraday-price-reversals-in-the-us-stock-index-futures-market-a-1/)；[Yu, Rentzler & Wolf：NASDAQ-100 期貨日內動量定反轉（JOIM）](https://joim.com/downloads/nasdaq-100-index-futures-intraday-momentum-reversal)（兩個網站喺雲端被擋，只讀到搜尋摘要） | 1987–2002 開市大幅移動之後日內明顯反轉，升市後更明顯；NQ 期貨隔夜回報多數預示日內反轉，效果睇昨日／隔夜方向同星期一 | 部分一致：我哋一年恒指 1 分鐘（IDEAS #153）連續 4 支 5 分鐘同向之後追入平均 −4.5 點（對照 −2.1），等回 38.2% 入更差（−5.3）→ 連續之後輕微回吐，但扣 2 點成本兩邊都冇優勢 | 「唔追連續 K」唔成立、唔改真倉；文獻嘅「開市大幅移動後反轉」即係使用者 R286「低過開市價 0.65 日波幅」，下一步預先登記驗呢個特徵 |
| 10-30 | [edgeful：average consecutive bars report](https://www.edgeful.com/blog/posts/average-consecutive-bars-report)（工具廠商，唔係研究） | 數連續同色 K 線長度，當「幾耐會轉」參考 | 冇樣本外、冇扣成本；我哋自己驗咗（#153），連續 4 支之後勝率 47%，同擲毫差唔多 | 唔跟 |
| 10-31 | [Cheng, Jiang & Ng 2004：恒指期貨延長交易時段嘅資訊含量（J. Futures Markets）](https://ideas.repec.org/a/wly/jfutmk/v24y2004i9p861-886.html)；[So & Tse 2004：恒指、期貨、盈富嘅價格發現](https://ideas.repec.org/a/wly/jfutmk/v24y2004i9p887-907.html)（只讀到摘要） | 恒指期貨延長時段（開市前）成交有顯著價格發現，幫手解釋之後正常時段現貨回報；期貨資訊最多 | 唔一致（以而家夜市計）：我哋一年 1 分鐘（IDEAS #156）夜市方向（\|變動\| ≥ 50 點，189 日）預測下一個日市 09:40→16:25：順做 +5.6 點（t 0.42）、逆做 −9.6，前後兩半相反 → 冇優勢。論文係 2004 年舊延長時段、量度現貨開市反映，唔係日內交易 | 唔改 AI context；夜市幅度約日市 0.7 倍，記入「夜市 vs 日市」報告 |
| 10-31 | [Ginyard 2014 碩士論文：47 隻期貨趨勢跟隨，比較 11 種張數方法（scribd 全文）](https://www.scribd.com/document/512256239/Full-Text-01)；[TurtleTrader 訪問 Ginyard](https://www.turtletrader.com/?p=977) | 1990–2012 模擬：「目標波幅」定張數最好，其次「最大回撤最小化」；冇支持按連贏連輸加減注（anti-martingale）。訪問提到交易員因為驚而注碼偏細，表現遠低過理論 | 相關：MHI R305「賺 +1 張、蝕 −1 張」係按成績加減注，論文冇證據支持；但樣本係 CTA 趨勢跟隨、唔係恒指即日／波段，未扣我哋成本 | 「張數升級規則」研究（11-07）預先登記比較：固定 1 張、R305 階梯、按日波幅（ATR）定張數，用 swing_check 隨機入場 |
| 11-01 | [Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert 2018：The Impact of Volatility Targeting（JPM）](https://scholars.duke.edu/publication/1370354)；[Alpha Architect 摘要](https://alphaarchitect.com/volatility-targeting-improves-risk-adjusted-returns/)；[Quantpedia 摘要](https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies) | 股票類按波幅調倉：美股夏普 0.40 → 約 0.48–0.51，波幅嘅波幅 4.6% → 1.8%，平衡組合回撤細咗（數字來自二手摘要） | 唔一致（我哋設定）：IDEAS #165 恒指隨機入場、固定 120 點止蝕，按波幅定張數 20 種子只有 3 個好過固定張數；R305 階梯 8/20；輸贏延續性相關 0.04。論文係長期持倉組合，同我哋每筆有固定止蝕唔同 | 張數規則研究完成；提案交使用者：改固定張數或維持 R305 |
| 11-02 | [IQ Option blog：trailing stop 啟動時機](https://blog.iqoption.com/en/how-to-use-trailing-stops-without-killing-your-winners/)；[Unger Academy：系統交易嘅 trailing stop](https://ungeracademy.com/?p=5462)（實務，唔係研究；冇搵到正式論文） | 啟動時機比距離重要，唔好一入場就跟；部分平台回測 trailing stop 結果唔可靠（忽略最細止蝕距離、K 線內次序） | 部分一致：IDEAS #210 我哋 1 分鐘數據，啟動點 120／165／200 每筆差 ±1–2 點，冇一個過 +5 點門檻；120／120 回撤細 15%；隨機入場同使用者入場方向相反 | 維持 165／165；記住 1 分鐘 K 線內高低先後未知嘅限制 |
| 11-03 | [Pacer：Why Trend Following（200 日均線，2000–2022 六次熊市）](https://www.paceretfs.com/media/why_trend_following.pdf)（基金推銷材料）；[Sentiment Trader：均線斜率](https://sentimentrader.com/blog/a-bullish-to-bearish-trend-shift-for-the-sp-500)；[CQG：200 日均線趨勢跟隨](https://news.cqg.com/blogs/commentary/2012/04/trend-following-kept-simple-200-day-simple-moving-average)（實務，唔係研究） | 跌穿長期均線之後，大部分跌幅喺之後出現；代價係區間市來回 whipsaw；均線斜率可能比價喺均線上下更有用 | 一致（方向）：IDEAS #224 恒指日線跌勢日（147 日），同一入場時間做好平均 −20.0 點、做淡 +0.7 點 → 跌勢日唔做好（#129）冇錯過嘢；但做淡本身 ≈0 | 維持 #129；之後可以試「20 日均線斜率」做跌勢定義（未登記） |
| 11-04 | [LuxAlgo：MA Slope Filter](https://www.luxalgo.com/library/concept/ma-slope-filter/)；[Incredible Charts：Moving Average Filters](https://www.incrediblecharts.com/indicators/moving_averages_filters.php)；[Pedersen 等：Which Trend Is Your Friend（CBS）](https://research-api.cbs.dk/ws/files/60084063/lasse_heje_pedersen_et_al_which_trend_is_your_friend_publishersversion.pdf)（頭兩個係實務；論文冇讀到斜率 vs 位置嘅結果） | 均線斜率比「價喺均線上下」少來回；EMA 斜率同價位置幾乎一樣，用 SMA 先有分別；好多系統兩樣都用 | 方向一致但未過門檻：IDEAS #226 只做淡，20 日均線向下定義 +10.3 點／筆 vs 現行 +5.8（19/20 種子較好），差 +4.5 < +5 | 維持 #129；斜率定義記入前向觀察 |

## 2026-11-05 網上研究：收市確認 vs 日內穿均線；止蝕後同方向再入場 → IDEAS #228
- [LuxAlgo Moving Average Crossovers](https://www.luxalgo.com/library/concept/moving-average-crossovers/)、[期貨技術分析第 6 章](https://portfoliowebsite-3hz.pages.dev/research/futures-ta/chapters/ch06-trend-tools)、[TradingView SMA Cross with a Price Filter](https://de.tradingview.com/script/A1IRXgJM-SMA-Cross-with-a-Price-Filter/)：日內穿均線會「重畫」，收市確認可以減少假訊號；ES 5 分鐘 EMA 交叉扣滑價後勝率 35–45%、低過打和。實務講法，冇正式研究，冇證據話扣成本後一定改善。
- [CXO Advisory：Hachemian 等 2013 止蝕同交易頻率](https://www.cxoadvisory.com/technical-trading/higher-measurement-frequency-and-stop-losses-for-trend-followers)、[Turtle 規則](https://tradingwithrayner.com/wp-content/uploads/2014/11/turtle-strategy-revised.pdf)：止蝕後要有新訊號或者創新高先再入場。摘要未見成績，未核實。11-05 真倉被移動止蝕平倉後，再升穿夜市高位先重開，做法一致。
- 同我哋數據：IDEAS #228 用 1 分鐘數據驗「跌勢日日內企返 20 日均線做好」→ ❌，平均 −49.8 點／筆，差過隨機做好 −22.4。同 #224 一致：跌勢日做好係負期望，加均線企返條件冇幫助，反而更差。
- 下一步：11-04 嗰類「日內轉勢做好」前向照計滿 10 筆；向使用者提案硬閘門（要批）。止蝕後再入場可以留做前向觀察，暫時唔登記。

## 2026-11-06 網上研究：急升之後追好；VIX 急升期間動量 → IDEAS #229
- [European Journal of Finance（White Rose）](https://eprints.whiterose.ac.uk/170132/3/European%20Journal%20of%20Finance%20accepted.pdf)：大幅變動之後回吐、細幅變動之後延續，同移動平均規則短期優勢有關（股票及主要指數，唔係期貨）。
- [SentimenTrader：S&P 連兩日升 ≥1%](https://sentimentrader.com/blog/optimism-flat-as-buying-surrounds-holiday-break)：之後幾日上升機率 44%、平均 −0.3%（細樣本，軼事）。
- [Grant、Wolf、Yu 美國指數期貨日內反轉 15 年](https://researchwith.montclair.edu/en/publications/intraday-price-reversals-in-the-us-stock-index-futures-market-a-1/)：反轉顯著，但扣買賣差成本後大減。
- [HKBU：亞洲指數期貨對美股過度反應](https://scholars.hkbu.edu.hk/en/publications/do-the-prices-of-stock-index-futures-in-asia-overreact-to-us-mark/)：美股大變動後亞洲期貨過度反應，平靜期大減（同恒指夜市／開市相關，未用）。
- [CXO Advisory](https://cxoadvisory.com/?p=22002)、[SentimenTrader 波動率轉變](https://sentimentrader.com/blog/fears-of-a-volatility-regime-change)：VIX 急升期間動量回報轉負、失敗嘅 VIX 急升多過真正崩盤（美股，冇恒指）。
- 同我哋數據：IDEAS #229 升勢日兩日急升 ≥ 1.5 ATR 後隨機做好 −17.8 點／筆 vs 其他升勢日 +10.0，方向一致但只得 11 日、14/20 種子 → 樣本不足唔成立，前向觀察。
- 下一步：急升後追好前向記錄；VIX 深紅期間 MHI 做好成績可以喺 journal 分開記（使用者 11-06 決定唔加金絲雀閘門）。

## 2026-11-07 網上研究：恒指期貨對美股大變動過度反應 → IDEAS #2000
- [Fung、Mok、Lam 2000：美國同香港指數期貨即日反轉](https://scholars.hkbu.edu.hk/en/publications/intraday-price-reversals-for-index-futures-in-the-us-and-hong-kon/)：HSI／S&P 期貨開市大變動之後即日反轉，反轉幅度同開市變動成正比；扣成本後仍可微利（只睇到摘要）。
- [Fung、Lam、Lam 2010：亞洲指數期貨對美股過度反應](https://ideas.repec.org/a/eee/empfin/v17y2010i3p428-440.html)：美股極端變動後亞洲期貨即日反轉，平靜期減弱（摘要）。
- 同我哋數據：IDEAS #2000 美股前晚 ES |報酬| ≥ 1.5% 嘅 25 日，恒指日市逆開市跳空每筆 +12.6 點（t 0.31），前半 +44、後半 −17；其他日子 +9.0 → ❌，效果細過成本以外嘅波動，近年冇用。
- 下一步：唔上真倉；呢條線（開市逆跳空）收工，唔再調門檻。

## 2026-11-08 網上研究：200 日線跌穿後係咪阻力 → IDEAS #2001
- [Sentimentrader：Rejected at the 200-day](https://sentimentrader.com/blog/rejected-at-the-200-day)：S&P 由下面反彈到 200 日線被明顯壓返之後，1–12 星期內多數再跌（樣本數未列）。
- [iTiger 轉載 MarketWatch／Sundial：重返 200 日線未必係好事](https://itiger.com/news/2522338826)：1946 起 11 次長期企喺上面之後跌穿再收復，之後幾個月回報偏弱。
- [StockCharts：S&P 500 Nears First Test](https://articles.stockcharts.com/article/articles-dont_ignore_this_chart-2016-02-sp-500-nears-first-test-/)：首次回測 200 日線係關鍵觀察位；短暫跌穿好快收復亦常見（2011、2015、2023）。
- 同我哋數據：IDEAS #2001 用 ^NDX、^GSPC 1990 起：第一次跌穿後 60 日內反彈觸碰 200 SMA，10 日後仍喺下面只得約 50%（NDX 11/21、SPX 13/26），觸碰後 20 日報酬中位數係正。→ 使用者 2018、2022 例子成立，但唔係普遍規律。
- 下一步：STYLE 第 45 條改寫，唔再寫「200 SMA 預設強阻力」；分析欄寫 200 SMA 時要講「歷史約一半機會被壓返」，配合其他結構判斷。

## 2026-11-08（續）：200 日線觸碰擬合（使用者「擬合都得」）→ IDEAS #2002
- 47 次觸碰（^NDX＋^GSPC 1990 起），8 個特徵邏輯迴歸：樣本內 66%、留一法 55%，同擲毫差唔多。
- 單一特徵最明顯：跌穿深度（深 62% vs 淺 39% 被壓返）；其餘接近 50%。
- 而家 NQ：11/6 低 26,366 對 200 SMA 約 28,110，跌穿深度約 −6%，屬「深」組（歷史 62% 被壓返），同使用者「200 SMA 係阻力」方向一致，但樣本少。
- 結論：機械特徵分唔開，使用者睇圖嘅判斷（形態、結構）未能用簡單數字取代；繼續用並排計分睇長期成績。

## 2026-11-09 網上研究：富途 API 美期限價單「下單失敗」常見原因（MNQ／MES 首次真倉被拒）
- 背景：11-09 07:40 HKT（美東週日 18:40，CME 已開）MNQ2612 @27,184.5、MES2612 @7,426.25 限價買 1 張，富途即時「下單失敗」。參考價 Yahoo（NQ 週五收 27,085、ES 7,402），限價高過收市約 0.4%，合 tick（0.25），唔似價格問題。
- [thinkorswim：Order Rejection Reasons](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Trade/Order-Entry-Tools/Order-Rejection-Reasons.html)：限價離現價太遠會被交易所／券商價格保護拒絕。
- [Interactive Brokers：Order Placement Considerations](https://www.interactivebrokers.com/docs/tws-api/doc/orders/place-order/order-placement-considerations)：被拒時改用貼近現價嘅限價。
- [Webull HK Trade API FAQ](https://developer.webull.hk/apis/docs/trade-api/faq)：常見拒單原因——購買力／保證金唔夠、市場休市、參數無效（價格範圍、單類型唔支援）。
- 搵唔到富途官方對美期 API 拒單嘅公開說明；網上只係一般原因，冇樣本。
- 下一步：PR #763 令程式記低富途 `last_err_msg`，加 `--diagnose` 唯讀查今日兩張單嘅錯誤訊息；睇到原因先改（例如改用富途報價、改落單時段、或者確認戶口美期權限）。

## 2026-11-10 網上研究：恒指／國企相對價值；夜市報酬隔夜反轉（MHI 日內搜尋 #2032–#2038 之後）

1. **HSI 對 HSCEI 價差（相對價值）**——CME Group《Trading China Exposure》(2016)：https://www.cmegroup.com/education/files/trading-china-exposure.pdf
   - 重點：2015–16 年 HSI 同 HSCEI 相關度 ≥ 0.95；兩隻指數共用 9 隻成份股（佔 HSCEI 58%、HSI 24%）；用「期貨對理論價貴／平」組成 rich/cheap 對。HKEX 亦明講 HHI 可以做 HSCEI 對 HSI 嘅價差策略：https://www.hkex.com.hk/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Hang-Seng-China-Enterprises-Index-Futures?sc_lang=en
   - 限制：樣本只得約一年，**冇測均值回歸策略、冇扣成本、冇報回報**；搵唔到近年 HSI／HSCEI 日內價差均值回歸嘅學術或可信回測。
   - 同我哋數據：未有 HHI／HTI 分鐘數據，未能核對。下一步：要先回補 HHI、HTI（需要改 main.py、部機、部署，等使用者揀）；揀咗先登記 IDEAS（預先定：價差 z 值入場、扣兩腿成本、樣本外 2023 起）。
2. **隔夜（夜市）報酬反轉**——CSI 300 期貨隔夜反轉工作論文（年化 16.54%、Sharpe 0.9、命中 53.76%）：https://reading-9.eprints-hosting.org/111035/1/Anonymized%20manuscript-R1.pdf ；中國商品期貨日內反轉（Zheng & Luo 2024, PBFJ）：https://ideas.repec.org/a/eee/pacfin/v88y2024ics0927538x24002865.html ；HSI 期貨延長交易時段（Cheng, Jiang & Ng 2001）：https://ptsldigital.ukm.my/handle/123456789/520576
   - 重點：A 股期貨隔夜報酬傾向喺日間反轉；HSI 延長時段後，有休市嘅時段之間報酬以流動性交易效應為主（即傾向反轉）。
   - **同我哋數據衝突**：#2032 N2「逆前一晚夜市做日市」（2018-11 起恒指期貨 1 分鐘）樣本外 n=933、每筆 −14.9 點、t −1.82（k=0.3% 都係 −17.6 點、t −1.76），4 年得 1 年正；反而 N1「跟夜市」樣本外 +6.9 點、t 0.84（未合格）。即係恒指夜市→日市係**輕微延續、唔係反轉**，A 股結果唔適用，唔另登記。
   - 下一步：冇。Fung (2000／2004／2010) 恒指期貨對美股極端變動過度反應已喺 11-07（#2000）處理。

## 2026-11-11 網上研究：CPI 日前後走勢；成交量分布 POC 當支撐阻力（配合分析欄模仿使用者寫法，STYLE 第 49 條）

1. **宏觀數據公布前後嘅股指走勢**——Hu, Pan, Wang & Zhu《Premium for Heightened Uncertainty》(NBER w25817)：https://nber.org/system/files/working_papers/w25817/w25817.pdf ；附錄版：https://www.mit.edu/~zhuh/HuPanWangZhu_preannouncement.pdf
   - 重點：非農、GDP、ISM 公布**之前**有顯著正報酬（不確定性消除），公布之後細而唔顯著——即係冇「公布後反轉」；Lucca & Moench 較早嘅結論係 FOMC 以外嘅數據冇公布前漂移，兩者有分歧。搵唔到專測 CPI 日「同前一日方向相反」嘅研究；一篇市場通訊話近期 CPI 日 SPX 平均約 −0.1%，冇樣本同顯著性：https://marketmemo.beehiiv.com/p/when-inflation-stops-moving-markets
   - 同我哋數據：11-10 核對（notes/2026-11-10_ES_4h_CPI_reversal.md）——2026-06 起 6 次 CPI 日，反轉約 3–4 次，樣本太少；同文獻「公布後冇系統性反轉」一致。使用者呢個觀察照記錄、唔當規律；分析欄模仿寫法可以引用佢原話，但唔加「高機率」。
   - 下一步：唔登記 IDEAS（冇數據支持，6 個樣本做唔到檢定）；每次 CPI 日累積一行。
2. **成交量分布／POC 係咪有效支撐阻力**——搵到嘅全部係平台同教學文章（CrossTrade、NinjaTrader、ATAS、Optimus Futures），**冇同行評審或者樣本外回測**；有教學頁反而話高成交量節點「價格照穿」、POC 直接入場冇用：https://marketstalkers.thinkific.com/pages/point-of-control-volume-profile ；定義問題（時段、格仔闊度）會改變 POC 位置：https://nexusfi.com/a/market-structure/naked-vpoc-futures-trading
   - 同我哋數據：之前數據包冇成交量，測唔到。使用者文章成日用 POC（NQ 30,805、NVDA 180.72／199.27／218.77），模仿寫法畫唔到係最大差距之一。
   - 下一步（今日做）：`scripts/longfei_analyst_data.py` 加 1 小時成交量（`h1_vol`），`mimic/charts.py` 加成交量分布同 POC（`profile`）；聽日數據包有量之後，先對返使用者嘅 POC 數字（NVDA 2025-07 起 180.72）睇差幾遠，再決定用唔用。POC 當支撐阻力有冇用，等有數據再登記 IDEAS 測（對照隨機水平位）。

## 2026-11-12 網上研究：inside bar 有冇可信回測 → IDEAS #2039（恒指 4 小時，冇合格）

1. **網上證據**：搵唔到 inside bar 突破喺股指期貨嘅嚴謹樣本外研究，全部係平台示範、網誌、論壇。
   - Unger Academy（迷你標普日內只做淡嘅 inside bar 策略，片段冇結果）：https://ungeracademy.com/?p=8375
   - StrategyQuant（加 SPY 200 EMA 趨勢過濾之後回撤細咗，冇具體數字）：https://strategyquant.com/blog/inside-bar-breakout-strategy-price-action-trading/
   - Oxford Strat（42 個期貨市場 34 年測 hikkake——inside day 假突破反手，有成本同敏感度測試，但係反轉形態唔係突破）：https://oxfordstrat.com/?p=17134
   - 2012 年網誌測「優質 inside bar」日線，第一年負增長，作者自己標為過時：https://forexiation.blogspot.com/2012/05/quality-inside-bar-backtest-extended.html
2. **自己測（#2039，`research/longfei_search/mhi_intraday7.py`，恒指期貨主連 2018-11→2026-11，成本 4 點）**：三個家族六組參數全部唔合格——I1 突破跟樣本外 +5.9／+9.4 點（t 0.9–1.2）、I2 攻唔破反手 −2.4／+16.1 點（t ≤1.46）、I3 跟收紅收黑 +6.5／+13.6 點（t ≤1.86）；樣本內 t 全部 ≤1.15。
3. **程式教訓（重要）**：I1 第一次跑 +77 點 t 8、修正跳空後仲有 +60 點——都係假：用 4 小時 K 判斷突破方向時剔走咗「同一根 K 兩邊都穿」嘅情況（即係先穿一邊再打止蝕嘅輸單）。改用 1 分鐘 K 逐分鐘行之後得返 +6 點。以後突破／止蝕類回測一律用細一級數據判斷先後；結果好得離譜（t>5）先當程式錯處理。
4. 下一步：機械版 inside bar 唔再試。使用者嘅用法係「關鍵位（缺口、套牢區下緣、均線）＋inside bar」，要測就要先有機械化嘅關鍵位定義——等使用者講佢點揀水平位先登記（#2040 候選：inside bar 出現喺前一日高低位／日線 50、100、200 SMA 附近 ±0.2%）。

## 2026-11-13 天覆陣 #1456 月頭月尾效應 → 龍飛陣期貨重驗 IDEAS #2040（ES／NQ 唔成立；恒指近年強但唔穩定）

- 來源：天覆陣 `research/strategy_search/BATCH4_1456.md`（26 個現貨股指，月尾最後 1 日＋月頭 3 日，差 +9.9bp、t 5.83；2010 後減半、月尾嗰日冇優勢）；使用者 11-12「1456 教龍飛」。文獻：Lakonishok & Smidt 1988；McConnell & Xu 2008。
- 龍飛陣重驗（`research/longfei_search/tom_futures.py`，預先登記）：
  - ES=F／NQ=F 連續合約 2000-09 起：原版差 +2.3／+3.4bp（t 0.6–0.7，2015 起變負）；月頭 3 日版 +5.7／+7.9bp（t 1.3–1.4）——**唔合格**。同天覆陣現貨結果（標普 +9.1 對 +2.4）方向一樣但期貨樣本（2000 起）冇顯著性。
  - 恒指期貨 2018-11 起：月頭 3 日版差 +26.1bp（t 2.65），2020–2026 連續 7 年正；原版 +16.3bp（t 1.90）。
  - 事後分段（^HSI 現貨）：2010–2018 差 −1.8bp，九年冇效應；強嘅係 1990–2009 同 2019–2026。即係恒指呢個效應會成段消失。
- 同我哋數據衝突／一致：同 #2035 M2（恒指日市月尾月頭，樣本少）唔衝突——M2 只計日市開至收，今次係收市對收市（包隔夜跳空），月頭優勢主要喺第 1 日（+34.8bp），好可能大部分喺隔夜。
- 下一步：美股期貨唔用。恒指「月頭 3 日偏多」只做前向觀察（每月記錄一次），唔改 MHI 真倉；要測「月頭優勢係咪喺隔夜」可以用 1 分鐘數據拆開夜市／日市（#2041 候選）。已回覆天覆陣。

## 2026-11-13 每日網上研究：月頭效應喺隔夜定日市？→ IDEAS #2041（恒指月頭優勢喺日市，猜想錯）

- 來源：
  - CEPR DP14462（美股股票溢價幾乎全部喺隔夜賺）：https://repec.cepr.org/repec/cpr/ceprdp/DP14462.pdf
  - CXO Advisory（標普 1993–2006 按月內日子拆隔夜／日間）：https://www.cxoadvisory.com/calendar-effects/buy-at-the-close-and-sell-at-the-open
  - Monteiro & Manso（隔夜效應 2006 年後減弱）：https://gestin.ipcb.pt/public/site/arquivo/2016Gestin13art07.pdf
  - Advisor Perspectives 綜述：https://www.advisorperspectives.com/articles/2022/06/24/night-moves-is-the-overnight-drift-the-grandmother-of-all-market-anomalies
- 重點：搵唔到專門將月頭效應拆做隔夜／日間嘅研究；美股文獻話溢價主要喺隔夜，所以我估恒指月頭優勢都喺隔夜。
- 自己測（`research/longfei_search/tom_hsi_split.py`，恒指期貨主連 1 分鐘 2018-11→2026-11，跑之前登記）：月頭 3 個交易日對其他日
  - 日市（09:15→16:30）：+16.3bp 對 −4.3bp，差 +20.6bp，t 2.64，2019–2026 有 7 年正 → **過登記條件**
  - 朝早跳空（03:00→09:15）：差 +4.9bp，t 1.24；夜市（17:15→03:00）：差 −0.5bp，t −0.12 → 唔過
  - 合計差 +26.2bp（t 2.65），同 #2040 一致。日市三日分別 +22.8／+10.6／+15.6bp。
- 同我哋數據衝突：**同我 #2040 記錄入面「好可能大部分喺隔夜」嘅猜想相反**，已更正。同美股文獻（溢價喺隔夜）亦相反——恒指月頭嘅資金流係喺港股日市時段入。
  同 #2035 M2 表面有出入（M2 月頭日市做好淨成本後 t 0.3–1.2）：M2 計絕對點數、扣 4 點成本、4d 版仲包埋月尾嗰日；今次係同其他日比較，差入面有約 4bp 係其他日日市本身偏負。即係「月頭日市比平日好」成立，但「月頭日市做好賺到錢」證據仍然唔夠。
- 下一步：唔開落單規則，MHI 真倉唔改。前向觀察改為每月記錄頭 3 日日市開至收。未解：2010–2018 現貨冇呢個效應（#2040），1 分鐘數據得 2018-11 起，驗證唔到嗰段。
