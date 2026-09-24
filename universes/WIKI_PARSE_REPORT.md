# 指數成分股（Wikipedia 解析）報告

由 `scripts/build_universe_wiki.py` 自動產生（重跑即覆蓋）。來源為 `research_output/multimarket/wiki/` 底下已存好的英文維基原始 wikitext 修訂版本，驗證用 `research_output/multimarket/probe/` 的 Nasdaq screener 與日經官方成分股頁。

**這不是官方權威來源**。年度快照（NDX、N225）視為 `<YYYY>-06-30` 起生效到下一份快照為止（跟 `universe.py` 恒指慣例一致），最後一份快照的成分股 `end` 留空；道指用歷史頁的實際調整日。`end` 為不含（第一個不是成分股的日子）。代碼為 Yahoo Finance 格式。

## 輸出檔

| 檔案 | 列數（區間） | 不同代碼數 | 最早 start |
|---|---|---|---|
| `universes/ndx/membership.csv` | 294 | 260 | 2008-06-30 |
| `universes/n225/membership.csv` | 305 | 302 | 2008-06-30 |
| `universes/djia/membership.csv` | 63 | 60 | 1987-03-12 |
| `universes/n225/current_official.csv` | 225 | 225 | 官方頁更新日 2026-09-18 |

## 一、Nasdaq-100（NDX）

格式：2008–2018 為 `#[[公司]] (TICKER)` 編號清單；2019 起為 `id="constituents"` wikitable（2025 起欄位順序改成 Ticker 在前，程式靠表頭辨認欄位）。
`ndx/current.txt`（2026-09 版）已把成分股表搬到獨立條目「List of NASDAQ-100 companies」，本身沒有名單 → **最新快照採用 2026.txt（2026-06-29 版）**。
「名單日期」是維基名單上方自述的 *current as of* 日期（2024 起不再寫），常早於修訂日。

| 年 | 修訂日 | 名單日期 | 格式 | 檔數 | 較前一年 | 備註 |
|---|---|---|---|---|---|---|
| 2008 | 2008-05-31 | May 19th, 2008 | 編號清單 | 100 | — |  |
| 2009 | 2009-06-29 | January 20, 2009 | 編號清單 | 100 | +14 / −14 |  |
| 2010 | 2010-05-28 | December 21, 2009 | 編號清單 | 100 | +9 / −9 |  |
| 2011 | 2011-06-24 | May 27, 2011 | 編號清單 | 100 | +9 / −9 |  |
| 2012 | 2012-06-21 | May 30, 2012 | 編號清單 | 100 | +10 / −10 |  |
| 2013 | 2013-06-11 | April 11, 2013 | 編號清單 | 100 | +12 / −12 |  |
| 2014 | 2014-06-21 | December 23, 2013 | 編號清單 | 101 | +14 / −13 |  |
| 2015 | 2015-06-10 | December 29, 2014 | 編號清單 | 107 | +11 / −5 |  |
| 2016 | 2016-06-11 | April 19, 2016 | 編號清單 | 108 | +17 / −16 |  |
| 2017 | 2017-06-20 | June 16, 2017 | 編號清單 | 107 | +13 / −14 |  |
| 2018 | 2018-06-27 | February 27, 2018 | 編號清單 | 103 | +8 / −12 |  |
| 2019 | 2019-05-31 | April 29, 2019 | wikitable | 103 | +9 / −9 |  |
| 2020 | 2020-06-29 | April 30, 2020 | wikitable | 103 | +10 / −10 |  |
| 2021 | 2021-06-28 | December 21, 2020 | wikitable | 102 | +10 / −11 |  |
| 2022 | 2022-06-25 | February 22nd, 2022 | wikitable | 102 | +12 / −12 |  |
| 2023 | 2023-06-29 | June 20, 2023 | wikitable | 101 | +8 / −9 |  |
| 2024 | 2024-06-28 | June 24, 2024 | wikitable | 101 | +9 / −9 |  |
| 2025 | 2025-06-24 | May 19, 2025 | wikitable | 101 | +5 / −5 |  |
| 2026 | 2026-06-29 | — | wikitable | 101 | +14 / −14 |  |

- 沿用前一年的年份：無（每年都解析成功）
- 檔數 > 100 是雙重股權（GOOGL/GOOG、FOXA/FOX、LBTYA/LBTYK、DISCA/DISCK 等）；2015–2017 年約 107–108 檔與當時「107 equity securities」的描述相符。
- 名字只出現、沒有代碼的條目：無（每一列都有代碼）。

### 疑似改名／改代碼（同年走一檔、進一檔且公司名相近；只列出，**未**自動合併）

| 年 | 剔除 | 加入 |
|---|---|---|
| 2012 | ERTS (Electronic Arts Inc.) | EA (Electronic Arts Inc.) |
| 2015 | LINTA (Liberty Interactive) | QVCA (Liberty Interactive) |

### 驗證 A：最新快照 vs Nasdaq screener（現行上市清單）

最新快照 2026（101 檔）中，screener 找不到的代碼 1 檔：EA。
（screener 為 2026-09 抓取；快照為 2026-06-29，之間下市/併購/改代碼的會出現在這裡。EA 應是 2025 年宣布的私有化收購完成後下市——未另行查證。）

### 驗證 B：用 2026 版條目的「Historical components」調整表倒推，對照各年快照

調整表共 225 筆（2007-02-01 → 2026-06-22）。以 2026 快照為起點，把參考日（名單日期；沒寫就用修訂日）之後生效的調整逆向還原，再跟當年快照比對。差異多半是：代碼改名（調整表用當時代碼）、調整表漏列、或維基名單本身沒及時更新。

| 年 | 參考日 | 吻合 | 只在快照 | 只在倒推 | 套用已知改代碼後吻合 | 剩餘差異（快照 / 倒推） |
|---|---|---|---|---|---|---|
| 2008 | 2008-05-19 | 93 | BRCM CMCSA ERTS FISV GOOG LINTA SYMC | BKNG DISCK EA FI FOXA GOOGL LMCK MDLZ NLOK QRTEA | 98 | BRCM CMCSA / BKNG DISCK FOXA LMCK MDLZ |
| 2009 | 2009-01-20 | 92 | BRCM CMCSA ERTS FISV GOOG LINTA NWSA SYMC | BKNG DISCK EA FI FOXA GOOGL LMCK MDLZ NLOK QRTEA | 98 | BRCM CMCSA / BKNG DISCK LMCK MDLZ |
| 2010 | 2009-12-21 | 91 | BRCM CMCSA ERTS FISV GOOG LINTA NWSA PCLN SYMC | BKNG DISCK EA FI FOXA GOOGL LMCK MDLZ NLOK QRTEA | 98 | BRCM CMCSA / DISCK LMCK MDLZ |
| 2011 | 2011-05-27 | 90 | BRCM CMCSA CTRP ERTS FISV GOOG LINTA NWSA PCLN SYMC | BKNG DISCK EA FI FOXA GOOGL LMCK MDLZ NLOK QRTEA TCOM | 98 | BRCM CMCSA / DISCK LMCK MDLZ |
| 2012 | 2012-05-30 | 91 | BRCM CMCSA CTRP FISV GOOG LINTA NWSA PCLN SYMC | BKNG DISCK FI FOXA GOOGL LMCK MDLZ NLOK QRTEA TCOM | 98 | BRCM CMCSA / DISCK LMCK MDLZ |
| 2013 | 2013-04-11 | 91 | BRCM CMCSA FB FISV GOOG LINTA NWSA PCLN SYMC | BKNG DISCK FI FOXA GOOGL LMCK META NLOK QRTEA | 98 | BRCM CMCSA / DISCK LMCK |
| 2014 | 2013-12-23 | 93 | BRCM CMCSA FB FISV GOOG LINTA PCLN SYMC | BKNG DISCK FI LMCK META NLOK QRTEA | 98 | BRCM CMCSA GOOG / DISCK LMCK |
| 2015 | 2014-12-29 | 98 | BRCM CMCSK FB FISV LVNTA PCLN QVCA SYMC WBA | BKNG EQIX FI META NLOK QRTEA | 103 | BRCM CMCSK LVNTA WBA / EQIX |
| 2016 | 2016-04-19 | 101 | CTRP FB FISV LVNTA PCLN QVCA SYMC | BKNG FI META NLOK QRTEA TCOM | 107 | LVNTA / ∅ |
| 2017 | 2017-06-16 | 97 | CTRP FB FISV LILA LILAK LVNTA MELI PCLN QVCA SYMC | BKNG FI META NLOK QRTEA TCOM YHOO | 103 | LILA LILAK LVNTA MELI / YHOO |
| 2018 | 2018-02-27 | 99 | CTRP FB FISV SYMC | FI META NLOK TCOM | 103 | ∅ / ∅ |
| 2019 | 2019-04-29 | 98 | CTRP FB FISV SYMC WLTW | FI META NLOK TCOM WTW | 103 | ∅ / ∅ |
| 2020 | 2020-04-30 | 101 | FB FISV | FI META | 103 | ∅ / ∅ |
| 2021 | 2020-12-21 | 100 | FB FISV | FI META | 102 | ∅ / ∅ |
| 2022 | 2022-02-22 | 101 | FISV | FI | 102 | ∅ / ∅ |
| 2023 | 2023-06-20 | 101 | — | — | 101 | ∅ / ∅ |
| 2024 | 2024-06-24 | 101 | — | — | 101 | ∅ / ∅ |
| 2025 | 2025-05-19 | 101 | — | — | 101 | ∅ / ∅ |
| 2026 | 2026-06-29 | 101 | — | — | 101 | ∅ / ∅ |

剩餘差異主要來自調整表本身：部分列的剔除代碼寫成後來的代碼（如 DISCK、LMCK、MDLZ），或漏列某些股別/併購（CMCSA/CMCSK、BRCM 被 AVGO 併購）。套用已知改代碼後，2018 年起每年都**完全一致**；更早年份最多剩 7 檔差異。

### 已知代碼變更（人工整理，僅供參考；membership 仍照各年快照原樣）

| 舊代碼 | 新代碼 | 說明 | 舊代碼出現於快照 | 新代碼出現於快照 |
|---|---|---|---|---|
| ERTS | EA | Electronic Arts 2011 年改代碼 | 2008–2011 | 2012, 2015–2026 |
| NWSA | FOXA | News Corp A 股 2013 年分拆後改名 21st Century Fox（新 News Corp 另拿 NWSA） | 2009–2013 | 2014–2021 |
| GOOG | GOOGL | 2014-04 拆股前的 GOOG 是 A 股；之後 A 股 = GOOGL、新 C 股 = GOOG | 2008–2026 | 2014–2026 |
| LINTA | QVCA | Liberty Interactive 追蹤股 2014 年改代碼 | 2008–2014 | 2015–2017 |
| QVCA | QRTEA | 2018 年改名 Qurate Retail | 2015–2017 | 2018 |
| PCLN | BKNG | Priceline 2018 年改名 Booking Holdings | 2010–2017 | 2018–2026 |
| CTRP | TCOM | Ctrip 2019 年改名 Trip.com | 2011–2012, 2016–2019 | 2020–2021 |
| SYMC | NLOK | Symantec 2019 年改名 NortonLifeLock（後再改 GEN） | 2008–2019 | — |
| WLTW | WTW | Willis Towers Watson 後來改代碼 WTW | 2019 | — |
| FB | META | Facebook 2022 年改名 Meta Platforms | 2013–2021 | 2022–2026 |
| FISV | FI | Fiserv 2023 年轉 NYSE 並改代碼 | 2008–2022 | — |

注意 GOOG：2008–2013 快照裡的 GOOG 是當時的 A 股（今 GOOGL），2014 起的 GOOG 是 C 股；membership 把它當成同一個代碼連續持有（Yahoo 的 GOOG 價格序列本身就是這樣接起來的）。2014 年維基把 A/C 股標籤寫反了，但代碼集合 {GOOG, GOOGL} 正確。

## 二、日經 225（N225）

格式：各年皆為 `==Components==` 底下按行業小節的條列 `* [[公司]] ({{tyo2|7203}})`；少數寫成 `{{TYO|…}}` 或 TSE 網址（2016 DeNA）。代碼格式檢查：`^\d{4}$`，另外容許東證 2024 年起的英數混合新代碼（`^\d{3}[0-9A-Z]$`，如 285A Kioxia、543A Archion）。

**重要**：維基 N225 名單經常好幾年沒更新（見「名單日期」欄：2009–2010 版都寫 *As of June 2009*、2011–2014 版都寫 *As of April 2011*、2018–2020 版都寫 *As of April 2018*、2022–2023 版都寫 *As of October 2021*、2024–2025 版都寫 *As of October 2023*），所以某些年換手為 0、下一年一次補很多檔——這是來源滯後，不是解析錯誤。

| 年 | 修訂日 | 名單日期（As of） | 原始列數 | 不同代碼 | 較前一年 | 備註 |
|---|---|---|---|---|---|---|
| 2008 | 2008-05-16 | October 2006 | 225 | 225 | — |  |
| 2009 | 2009-06-25 | June 2009 | 226 | 226 | +13 / −12 | ⚠ 226 ≠ 225 |
| 2010 | 2010-06-25 | June 2009 | 226 | 226 | +0 / −0 | ⚠ 226 ≠ 225；與前一年相同（名單未更新） |
| 2011 | 2011-06-02 | April 2011 | 225 | 224 | +7 / −9 | ⚠ 224 ≠ 225；重複列 8830 |
| 2012 | 2012-06-19 | April 2011 | 226 | 224 | +3 / −3 | ⚠ 224 ≠ 225；重複列 6302,8830 |
| 2013 | 2013-06-09 | April 2011 | 225 | 224 | +1 / −1 | ⚠ 224 ≠ 225；重複列 8830 |
| 2014 | 2014-05-11 | April 2011 | 224 | 224 | +1 / −1 | ⚠ 224 ≠ 225 |
| 2015 | 2015-05-28 | February 2015 | 226 | 225 | +5 / −4 | 重複列 8830 |
| 2016 | 2016-05-28 | December 2015 | 226 | 225 | +5 / −5 | 重複列 8830 |
| 2017 | 2017-03-10 | February 2017 | 226 | 225 | +2 / −2 | 重複列 8830 |
| 2018 | 2018-04-24 | April 2018 | 225 | 224 | +6 / −7 | ⚠ 224 ≠ 225；重複列 4568 |
| 2019 | 2019-06-27 | April 2018 | 225 | 224 | +0 / −0 | ⚠ 224 ≠ 225；重複列 4568；與前一年相同（名單未更新） |
| 2020 | 2020-04-18 | April 2018 | 225 | 225 | +3 / −2 |  |
| 2021 | 2021-06-09 | October 2020 | 225 | 225 | +8 / −8 |  |
| 2022 | 2022-05-04 | October 2021 | 225 | 225 | +3 / −3 |  |
| 2023 | 2023-06-28 | October 2021 | 225 | 225 | +0 / −0 | 與前一年相同（名單未更新） |
| 2024 | 2024-06-02 | October 2023 | 227 | 227 | +12 / −10 | ⚠ 227 ≠ 225 |
| 2025 | 2025-06-14 | October 2023 | 227 | 227 | +0 / −0 | ⚠ 227 ≠ 225；與前一年相同（名單未更新） |
| 2026 | 2026-06-25 | April 2026 | 225 | 225 | +11 / −13 | 英數代碼 543A,285A |

- 沿用前一年的年份：無（19 份快照都有可用名單，包括 2017）
- 「重複列」= 同一代碼在兩個行業小節各列一次（維基編輯錯誤），已去重；檔數 ≠ 225 的年份是維基本身多列/漏列（沒有捏造補齊）。
- 所有代碼皆可解析，無「只有公司名」的條目。

### 逐年加入／剔除明細

- **2009**：加入 1334.T（Maruha Nichiro Holdings, Inc.）, 2269.T（Meiji Holdings Company, Limited）, 3086.T（J. Front Retailing Co., Ltd.）, 3099.T（Isetan Mitsukoshi Holdings Ltd.）, 3436.T（SUMCO Corp.）, 5541.T（Pacific Metals Co., Ltd.）, 6305.T（Hitachi Construction Machinery Co., Ltd.）, 6465.T（Hoshizaki Electric Co., Ltd.）, 8270.T（Uny Co., Ltd.）, 8354.T（Fukuoka Financial Group, Inc.）, 8628.T（Matsui Securities Co., Ltd.）, 8725.T（Mitsui Sumitomo Insurance Group Holdings, Inc.）, 9412.T（Sky Perfect JSAT Holdings Inc.）；剔除 1861.T（Kumagai Gumi Co., Ltd.）, 2202.T（Meiji Seika Kaisha, Ltd.）, 2261.T（Meiji Dairies Corp.）, 2602.T（The Nisshin Oillio Group, Ltd.）, 2779.T（Mitsukoshi, Ltd.）, 4045.T（Toagosei Co., Ltd.）, 4795.T（Sky Perfect Communications Inc.）, 7231.T（Topy Industries, Ltd.）, 8238.T（Isetan Co., Ltd.）, 8583.T（UFJ Nicos Co., Ltd.）, 8603.T（Nikko Cordial Corp.）, 8752.T（Mitsui Sumitomo Insurance Co., Ltd.）
- **2011**：加入 5214.T（Nippon Electric Glass Company, Limited）, 5407.T（Nisshin Steel Co., Ltd.）, 6506.T（Yaskawa Electric Corporation, Limited）, 7735.T（Dainippon Screen MFG. CO., LTD.）, 8750.T（Dai-ichi Life Insurance Company, Limited）, 8804.T（Tokyo Tatemono Co., Ltd.）, 9022.T（Central Japan Railway Company）；剔除 3404.T（Mitsubishi Rayon Co., Ltd.）, 5016.T（Nippon Mining Holdings, Inc.）, 6465.T（Hoshizaki Electric Co., Ltd.）, 6764.T（Sanyo Electric Co., Ltd.）, 6796.T（Clarion Co., Ltd.）, 6991.T（Panasonic Electric Works Co., Ltd.）, 8403.T（The Sumitomo Trust and Banking Co., Ltd.）, 8755.T（Sompo Japan Insurance Inc.）, 9205.T（Japan Airlines Corp.）
- **2012**：加入 6113.T（Amada Co. Ltd.）, 8304.T（Aozora Bank, Ltd.）, 8729.T（Sony Financial Holdings Inc.）；剔除 8404.T（Mizuho Trust & Banking Co., Ltd.）, 8606.T（Mizuho Securities Co., Ltd.）, 9737.T（CSK Holdings Corp.）
- **2013**：加入 5020.T（JX Holdings）；剔除 5001.T（Nippon Oil Corp.）
- **2014**：加入 8630.T（NKSJ Holdings, Inc.）；剔除 5405.T（Sumitomo Metal Industries, Ltd.）
- **2015**：加入 1333.T（Maruha Nichiro Holdings, Inc.）, 3863.T（Nippon Paper Group, Inc.）, 4043.T（Tokuyama Corporation）, 5405.T（Sumitomo Metal Industries, Ltd.）, 6988.T（Nitto Denko）；剔除 1334.T（Maruha Nichiro Holdings, Inc.）, 3864.T（Mitsubishi Paper Mills Ltd.）, 3893.T（Nippon Paper Group, Inc.）, 8630.T（NKSJ Holdings, Inc.）
- **2016**：加入 1808.T（Haseko Corp.）, 2432.T（Dena Co., Ltd.）, 3289.T（Tokyu Land Corp.）, 5413.T（Nisshin Steel Co., Ltd.）, 5703.T（Nippon Light Metal Co., Ltd）；剔除 3110.T（Nitto Boseki Co., Ltd.）, 5407.T（Nisshin Steel Co., Ltd.）, 5701.T（Nippon Light Metal Co., Ltd）, 8803.T（Heiwa Real Estate Co., Ltd.）, 8815.T（Tokyu Land Corp.）
- **2017**：加入 4755.T（Rakuten Inc.）, 7272.T（Yamaha Motor Corp.）；剔除 4041.T（Nippon Soda Co., Ltd.）, 6753.T（Sharp Corp.）
- **2018**：加入 6098.T（Recruit Holdings Co., Ltd.）, 6178.T（Japan Post Holdings Co., Ltd.）, 6724.T（Seiko Epson Corp.）, 7186.T（Concordia Financial Group, Inc.）, 8028.T（FamilyMart Uny Holdings Co., Ltd.）, 8630.T（Sompo Holdings, Inc.）；剔除 3865.T（Hokuetsu Paper Mills, Ltd.）, 5405.T（Sumitomo Metal Industries, Ltd.）, 6502.T（Toshiba Corp.）, 6508.T（Meidensha Corp.）, 6767.T（Mitsumi Electric Co., Ltd.）, 8270.T（Uny Co., Ltd.）, 8332.T（The Bank of Yokohama, Ltd.）
- **2020**：加入 4578.T（Otsuka Holdings Co. Co., Ltd.）, 4631.T（DIC Corporation）, 5019.T（Idemitsu Kosan Co., Ltd）；剔除 5002.T（Showa Shell Sekiyu K.K.）, 5413.T（Nisshin Steel Co., Ltd.）
- **2021**：加入 2413.T（M3 Inc.）, 3659.T（Nexon Co., Ltd.）, 4751.T（Cyberagent Inc.）, 6645.T（Omron Corp.）, 6753.T（Sharp Corp.）, 7832.T（Bandai Namco Holdings, Inc.）, 8697.T（Japan Exchange Group Inc.）, 9434.T（SoftBank Corp.）；剔除 4272.T（Nippon Kayaku Co., Ltd.）, 5715.T（Furukawa Co., Ltd.）, 6366.T（Chiyoda Corp.）, 6773.T（Pioneer Corporation）, 8028.T（FamilyMart Uny Holdings Co., Ltd.）, 8729.T（Sony Financial Holdings Inc.）, 9437.T（NTT DoCoMo, Inc.）, 9681.T（Tokyo Dome Corp.）
- **2022**：加入 6861.T（Keyence Corp.）, 6981.T（Murata Manufacturing Co., Ltd.）, 7974.T（Nintendo Co., Ltd.）；剔除 3105.T（Nisshinbo Holdings Inc.）, 5901.T（Toyo Seikan Kaisha, Ltd.）, 9412.T（SKY Perfect JSAT Holdings Inc.）
- **2024**：加入 4385.T（Mercari Inc.）, 4661.T（Oriental Land Co., Ltd.）, 5831.T（Shizuoka Financial Group (Holding company for Shizuoka Bank)）, 6273.T（SMC Corporation）, 6594.T（Nidec）, 6723.T（Renesas Electronics）, 6920.T（Lasertec）, 7741.T（Hoya Corporation）, 8591.T（Orix Co.）, 9147.T（Nippon Express Holdings Inc. (Holding company for Nippon Express)）, 9201.T（Japan Airlines Co., Ltd.）, 9843.T（Nitori Holdings Co., Ltd.）；剔除 1333.T（Maruha Nichiro Holdings, Inc.）, 3101.T（Toyobo Co., Ltd.）, 3103.T（Unitika, Ltd.）, 5703.T（Nippon Light Metal Co., Ltd）, 5707.T（Toho Zinc Co., Ltd.）, 7003.T（Mitsui Engineering & Shipbuilding Co., Ltd.）, 8303.T（Shinsei Bank, Ltd.）, 8355.T（The Shizuoka Bank, Ltd.）, 8628.T（Matsui Securities Co., Ltd.）, 9062.T（Nippon Express Co., Ltd.）
- **2026**：加入 285A.T（Kioxia Holdings Corp.）, 3092.T（ZOZO Co., Ltd）, 3697.T（SHIFT Inc.）, 4307.T（Nomura Research Institute Ltd.）, 543A.T（Archion Corp.）, 6146.T（Disco Corporation Ltd.）, 6526.T（Socionext Inc.）, 6532.T（Baycurrent Inc.）, 6963.T（Rohm Co., Ltd.）, 7453.T（Muji Co., Ltd）, 7532.T（Pan Pacific International Holdings Corp.）；剔除 2531.T（Takara Holdings Inc.）, 3863.T（Nippon Paper Industries Co., Ltd.）, 4631.T（DIC Corporation）, 5202.T（Nippon Sheet Glass Co., Ltd.）, 5232.T（Sumitomo Osaka Cement Co., Ltd.）, 5541.T（Pacific Metals Co., Ltd.）, 6674.T（GS Yuasa Corp.）, 6703.T（Oki Electric Industry Co., Ltd.）, 6952.T（Casio Computer Co., Ltd.）, 7205.T（Hino Motors, Ltd.）, 7762.T（Citizen Watch Co., Ltd.）, 9301.T（Mitsubishi Logistics Corp.）, 9613.T（NTT Data Corp.）

### 疑似改代碼／控股改組（同年走一檔、進一檔且公司名相近；只列出，未自動合併）

| 年 | 剔除 | 加入 |
|---|---|---|
| 2009 | 2202.T (Meiji Seika Kaisha, Ltd.) | 2269.T (Meiji Holdings Company, Limited) |
| 2009 | 2261.T (Meiji Dairies Corp.) | 2269.T (Meiji Holdings Company, Limited) |
| 2009 | 2779.T (Mitsukoshi, Ltd.) | 3099.T (Isetan Mitsukoshi Holdings Ltd.) |
| 2009 | 4795.T (Sky Perfect Communications Inc.) | 9412.T (Sky Perfect JSAT Holdings Inc.) |
| 2009 | 8238.T (Isetan Co., Ltd.) | 3099.T (Isetan Mitsukoshi Holdings Ltd.) |
| 2009 | 8752.T (Mitsui Sumitomo Insurance Co., Ltd.) | 8725.T (Mitsui Sumitomo Insurance Group Holdings, Inc.) |
| 2015 | 1334.T (Maruha Nichiro Holdings, Inc.) | 1333.T (Maruha Nichiro Holdings, Inc.) |
| 2015 | 3893.T (Nippon Paper Group, Inc.) | 3863.T (Nippon Paper Group, Inc.) |
| 2016 | 5407.T (Nisshin Steel Co., Ltd.) | 5413.T (Nisshin Steel Co., Ltd.) |
| 2016 | 5701.T (Nippon Light Metal Co., Ltd) | 5703.T (Nippon Light Metal Co., Ltd) |
| 2016 | 8815.T (Tokyu Land Corp.) | 3289.T (Tokyu Land Corp.) |
| 2024 | 8355.T (The Shizuoka Bank, Ltd.) | 5831.T (Shizuoka Financial Group (Holding company for Shizuoka Bank)) |
| 2024 | 9062.T (Nippon Express Co., Ltd.) | 9147.T (Nippon Express Holdings Inc. (Holding company for Nippon Express)) |
| 2026 | 4631.T (DIC Corporation) | 6146.T (Disco Corporation Ltd.) |

### 驗證：最新維基快照 vs 日經官方現行名單

官方頁（更新日 2026-09-18）解析出 225 檔、34 個行業 → `universes/n225/current_official.csv`。
維基 2026 快照 225 檔；兩者交集 **224** 檔。
- 只在維基：6594.T（Nidec）
- 只在官方：4062.T（IBIDEN CO., LTD.）
- 維基 current.txt（2026-09 版）名單與 2026 快照相同。

## 三、道瓊工業平均（DJIA）

來源頁 `djia_hist/current.txt`（修訂 2026-08-16）每次調整一節、列出調整後完整名單。取 1987-03-12 起共 21 次調整（區間精確到日）。頁面只有公司名，代碼用程式內的人工對照表。

| 調整日 | 名單檔數 | 代碼數 | 加入（代碼差集） | 剔除（代碼差集） | 頁面 ↑ | 頁面 ↓ | 一致？ |
|---|---|---|---|---|---|---|---|
| 1987-03-12 | 30 | 30 | — | — | — | — | — |
| 1991-05-06 | 30 | 30 | CAT DIS JPM | C NAV X | CAT DIS JPM | C NAV X | ✓ |
| 1997-03-17 | 30 | 30 | C HPQ JNJ WMT | BS TX WX Z | C HPQ JNJ WMT | BS TX WX Z | ✓ |
| 1999-11-01 | 30 | 30 | HD INTC MSFT T | CVX GT S UK | HD INTC MSFT T | CVX GT S UK | ✓ |
| 2003-01-27 | 30 | 30 | — | — | — | — | ✓ |
| 2004-04-08 | 30 | 30 | AIG PFE VZ | EK IP T-OLD | AIG PFE VZ | EK IP T-OLD | ✓ |
| 2005-11-21 | 30 | 30 | — | — | — | — | ✓ |
| 2008-02-19 | 30 | 30 | BAC CVX | HON MO | BAC CVX | HON MO | ✓ |
| 2008-09-22 | 30 | 30 | MDLZ | AIG | MDLZ | AIG | ✓ |
| 2009-06-08 | 30 | 30 | CSCO TRV | C MTLQQ | CSCO TRV | C MTLQQ | ✓ |
| 2012-09-24 | 30 | 30 | UNH | MDLZ | UNH | MDLZ | ✓ |
| 2013-09-23 | 30 | 30 | GS NKE V | BAC HPQ HWM | GS NKE V | BAC HPQ HWM | ✓ |
| 2015-03-19 | 30 | 30 | AAPL | T | AAPL | T | ✓ |
| 2017-09-01 | 30 | 30 | — | — | — | — | ✓ |
| 2018-06-26 | 30 | 30 | WBA | GE | WBA | GE | ✓ |
| 2019-04-02 | 30 | 30 | DOW | DD | DOW | DD | ✓ |
| 2020-04-06 | 30 | 30 | — | — | RTX | RTX | 見說明 |
| 2020-08-31 | 30 | 30 | AMGN CRM HON | PFE RTX XOM | AMGN CRM HON | PFE RTX XOM | ✓ |
| 2024-02-26 | 30 | 30 | AMZN | WBA | AMZN | WBA | ✓ |
| 2024-11-08 | 30 | 30 | NVDA SHW | DOW INTC | NVDA SHW | DOW INTC | ✓ |
| 2026-06-29 | 30 | 30 | GOOGL | VZ | GOOGL | VZ | ✓ |

「見說明」= 頁面標了加入/剔除，但兩者對應到同一個 Yahoo 代碼（同一證券改名/換殼），所以代碼層面沒有變動：
- 2020-04-06：頁面 ↑ RTX / ↓ RTX，代碼差集 +∅ / −∅

- 無法對應代碼的公司名：無
- 從 1987-03-12 名單逐次套用 ↑/↓ 回放到最新，結果與頁面最新一節（2026-06-29）的 30 檔**完全一致**。
- 頁首「Summary of changes since 1991」列出 18 個調整日，全部都有對應的一節；另有 2003-01-27, 2005-11-21 為只改名、成分不變的小節。
- 現行 30 檔：AAPL AMGN AMZN AXP BA CAT CRM CSCO CVX DIS GOOGL GS HD HON IBM JNJ JPM KO MCD MMM MRK MSFT NKE NVDA PG SHW TRV UNH V WMT
- 現行 30 檔中 Nasdaq screener 找不到的：無

### 公司名 → 代碼對照（1987 年起出現過的全部名稱）

| 維基名稱 | 代碼 |
|---|---|
| 3M Company | MMM |
| AT&T Corporation | T-OLD |
| AT&T Inc. | T |
| Alcoa Inc. | HWM |
| Allied-Signal Incorporated | HON |
| AlliedSignal Incorporated | HON |
| Alphabet Inc. | GOOGL |
| Altria Group Incorporated | MO |
| Altria Group, Inc. | MO |
| Altria Group, Incorporated | MO |
| Aluminum Company of America | HWM |
| Amazon.com, Inc. | AMZN |
| American Express Company | AXP |
| American International Group, Inc. | AIG |
| American Telephone and Telegraph Company | T-OLD |
| Amgen Inc. | AMGN |
| Apple Inc. | AAPL |
| Bank of America Corporation | BAC |
| Bethlehem Steel Corporation | BS |
| Caterpillar Inc. | CAT |
| Chevron Corporation | CVX |
| Cisco Systems, Inc. | CSCO |
| Citigroup Inc. | C |
| Dow Inc. | DOW |
| DowDuPont Inc. | DD |
| E.I. du Pont de Nemours & Company | DD |
| Eastman Kodak Company | EK |
| Exxon Corporation | XOM |
| Exxon Mobil Corporation | XOM |
| F. W. Woolworth Company | Z |
| General Electric Company | GE |
| General Motors Corporation | MTLQQ |
| Goodyear Tire and Rubber Company | GT |
| Hewlett-Packard Company | HPQ |
| Honeywell International | HON |
| Honeywell International Inc. | HON |
| Honeywell Technologies Inc. | HON |
| Intel Corporation | INTC |
| International Business Machines Corporation | IBM |
| International Paper Company | IP |
| J.P. Morgan & Company | JPM |
| JPMorgan Chase & Co. | JPM |
| Johnson & Johnson | JNJ |
| Kraft Foods Inc. | MDLZ |
| McDonald's Corporation | MCD |
| Merck & Co., Inc. | MRK |
| Microsoft Corporation | MSFT |
| Minnesota Mining & Manufacturing Company | MMM |
| Navistar International Corporation | NAV |
| Nike, Inc. | NKE |
| Nvidia Corporation | NVDA |
| Pfizer Inc. | PFE |
| Philip Morris Companies Inc. | MO |
| Primerica | C |
| Raytheon Technologies Corporation | RTX |
| SBC Communications Inc. | T |
| Salesforce, Inc. | CRM |
| Sears Roebuck & Company | S |
| Texaco Incorporated | TX |
| The Boeing Company | BA |
| The Coca-Cola Company | KO |
| The Goldman Sachs Group, Inc. | GS |
| The Home Depot, Inc. | HD |
| The Procter & Gamble Company | PG |
| The Sherwin-Williams Company | SHW |
| The Travelers Companies, Inc. | TRV |
| The Walt Disney Company | DIS |
| Travelers Inc. | C |
| USX Corporation | X |
| Union Carbide Corporation | UK |
| United Technologies Corporation | RTX |
| UnitedHealth Group Inc. | UNH |
| UnitedHealth Group Incorporated | UNH |
| Venator | Z |
| Verizon Communications Inc. | VZ |
| Visa Inc. | V |
| Wal-Mart Stores, Inc. | WMT |
| Walgreens Boots Alliance, Inc. | WBA |
| Walmart Inc. | WMT |
| Westinghouse Electric Corporation | WX |

對照原則：(1) 仍上市的同一證券（中間只是改名/改代碼）→ 現行 Yahoo 代碼，讓價格歷史接得上；(2) 已下市/被併購 → 離開道指時的代碼（通用汽車沿用 repo S&P 500 名單的 MTLQQ）；(3) 舊 AT&T Corp.（1916–2004）的歷史代碼 T 現在屬於 SBC 這條線（SBC 1999–2004 也同時在指數內）→ 給佔位代碼 `T-OLD`（Yahoo 抓不到，回測時會因無價格被略過）。

## 已知限制

1. **維基不是官方來源**：名單是編輯者記錄的，可能滯後、漏改或打錯（N225 尤其嚴重，見上表的名單日期）。
2. **年度顆粒度**：NDX、N225 只取每年約 6/30 的修訂版本，年內的調整（NDX 每年 12 月重組＋臨時替換、2026 起每季；N225 每年 4/10 月定期調整＋臨時替換）全部被壓到 6/30；且名單自述日期常比修訂日早好幾個月甚至幾年。
3. NDX 的精確日期其實可以從 2026 版條目的「Historical components」調整表重建（本報告只拿來驗證）；若要升級成逐日區間，可改用該表（注意表內代碼是當時代碼，需處理改名）。
4. 代碼沿用各年快照當時的寫法（FB→META、GOOG/GOOGL 等不自動合併），改名清單只列在報告裡。已下市代碼可能被 Yahoo 重新分配給別家公司——`universe.py` 的「價格起始日 ≤ 入選日」檢查會擋掉新公司，但擋不住「舊代碼現在屬於一家歷史更長的公司」的情況（例如道指 T-OLD 就是為此另立）。
5. DJIA 名稱→代碼是人工對照；J.P. Morgan & Co.（2000 年前）用 JPM、Alcoa Inc. 用 HWM、Primerica/Travelers Inc. 用 C、E.I. du Pont 與 DowDuPont 都用 DD——Yahoo 上這些代碼的早年價格是否真的是當時那家公司，需要以價格資料再核對。Alphabet（2026-06-29 加入）頁面未註明股別，暫用 GOOGL，待確認。
6. N225 維基部分年份不是 225 檔（見表），未補齊；日本新式英數代碼（285A.T 等）在舊工具可能被當成非法代碼。
