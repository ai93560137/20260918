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
