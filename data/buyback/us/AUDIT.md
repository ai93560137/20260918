# 美股回購授權判讀稽核

判讀規則在 `scripts/buyback_fetch.py`（`classify_sentence`）。依 `research/buyback/STRATEGY.md` §3，
回測前要確認「是否為新增或加碼授權」與「金額」兩項正確率都 ≥ 90%。稽核者：Claude（逐句人工判讀）；
歡迎抽查下表並修正判定。

判定標準：這份申報是否**首次**揭露新的或加碼的回購授權。只提到既有計畫的剩餘額度或執行進度、只延長期限、
回顧三週前（第 4 版改為十天前）已公告的授權、債券契約條款等，都算錯。

## 結果

| 輪次 | 規則版本 | 樣本 | 新授權正確率 | 金額正確率 | 備註 |
|---|---|---|---|---|---|
| A | 第 3 版（修正前） | 100 筆（種子 90210） | 92/100 | 約 96/100 | **樣本內**：看到錯誤後才修規則，之後在同一批上是 98%，不能當成準確率 |
| B | 第 3 版（最終） | 50 筆新樣本（種子 424242） | 41/50 = **82%** | 49/50 | 樣本外，未達門檻 → 修第 4 版 |
| C | 第 4 版 | 50 筆新樣本（種子 777，排除 A、B） | 45/50 = **90%** | 49/50 | 樣本外，**剛好達標**；50 筆的 95% 信賴區間約 78%–96% |

**結論**：第 4 版勉強達到預先登記的 90% 門檻。誤判多半是「回顧已公告的授權」，會讓事件日比實際晚（在已知消息後才進場），
方向上對策略不利，不會美化結果。

## C 輪（第 4 版，樣本外）

錯誤：#27（分析師簡報中的「新計畫目標」）、#31（簡報回顧、金額也錯）、#36（既有計畫的執行金額）、
#44（對近期回購的評論）、#47（延長既有計畫）。

| # | 申報日 | 金額 | 判定 | 原句（節錄） |
|---|---|---|---|---|
| 0 | 2015-09-08 | 35000000.0 | ✅ | On September 8, 2015, Potbelly Corporation announced that its Board of Directors has authorized a share repurchase program of up to $35 million of the Company’s |
| 1 | 2024-11-07 | 77900000.0 | ✅ | On November 6, 2024, the Board of Directors of the Company increased the Company’s share repurchase authorization by $77.9 million to an aggregate amount of $10 |
| 2 | 2024-11-13 | 500000000.0 | ✅ | (NYSE: GPI) (“Group 1” or the “Company”), a Fortune 250 automotive retailer with 260 dealerships located in the U.S. and U.K., today announced its board of dire |
| 3 | 2021-12-16 | 75000000.0 | ✅ | The Company also announced that its Board of Directors (the “Board) has authorized a new $75 million share repurchase program to return capital to shareholders. |
| 4 | 2017-05-08 |  | ✅ | The Board of Directors recently approved a share repurchase program under which the Company may repurchase up to 5% of shares outstanding, or approximately 4 mi |
| 5 | 2020-05-11 | 100000000.0 | ✅ | Board of Directors approved a new share repurchase authorization of $100 million. |
| 6 | 2007-07-25 |  | ✅ | The Board approved an increase in the share repurchase program by an additional 8 million shares to an aggregate program of 120 million shares. |
| 7 | 2024-11-13 | 2000000000.0 | ✅ | (the Company) approved a new share repurchase program with immediate effect authorizing the Company to repurchase up to $2 billion of the Company's outstanding  |
| 8 | 2022-07-27 | 50000000.0 | ✅ | The Board of Directors of the Company authorized a stock repurchase program pursuant to which the Company may, from time to time, purchase up to $50 million of  |
| 9 | 2018-05-10 | 175000000.0 | ✅ | As part of the agreement, the Board has approved an expansion of the Company’s share repurchase authorization to $175 million and will target repurchasing share |
| 10 | 2011-02-22 |  | ✅ | (the “Company”) approved a stock repurchase program. |
| 11 | 2010-09-20 |  | ✅ | HILLSBORO, Ore., September 20, 2010 — FEI Company (Nasdaq: FEIC) announced that its board of directors has authorized a stock repurchase program that enables th |
| 12 | 2008-07-23 |  | ✅ | (Nasdaq: RBNF), (the “Company”), a leading provider of full-service community banking, investment management, trust services, and bank data and item processing, |
| 13 | 2020-03-09 |  | ✅ | (“ANGI” or the “Company”) authorized the Company to repurchase up to an additional 20 million shares of ANGI Class A common stock. |
| 14 | 2010-02-16 | 20000000.0 | ✅ | The Company announced that its Board of Directors has authorized the repurchase of up to $20 million of its common stock. |
| 15 | 2006-01-26 | 100000000.0 | ✅ | The Company’s Board of Directors has authorized a $100.0 million increase in the Company’s share repurchase program. |
| 16 | 2020-08-20 |  | ✅ | PCSB Financial Corporation (the “Company”) (NASDAQ: “PCSB”), parent of PCSB Bank, announced today that it has authorized a program to repurchase up to 844,907 s |
| 17 | 2018-04-25 |  | ✅ | (“Ethan Allen” or the “Company”) announced that its Board of Directors declared a regular quarterly cash dividend of $0.19 per share of common stock and increas |
| 18 | 2017-04-28 | 8000000.0 | ✅ | In the Press Release, the Company also announced that its Board of Directors has approved a share repurchase program, authorizing the repurchase of up to $8 mil |
| 19 | 2010-05-24 | 1000000.0 | ✅ | Las Vegas, Nevada – May 21, 2010 – Full House Resorts (NYSE Amex US: FLL) announced today that its Board of Directors has authorized a program to repurchase up  |
| 20 | 2014-12-18 | 25000000.0 | ✅ | (NASDAQ: POWL), a leading supplier of custom-engineered solutions for the management, distribution and control of electrical energy, today announced that its Bo |
| 21 | 2019-05-16 | 7500000.0 | ✅ | (NASDAQ:LAWS) (“Lawson” or the "Company"), a distributor of products and services to the MRO marketplace, today announced that its Board of Directors has author |
| 22 | 2011-05-09 | 150000000.0 | ✅ | On May 5, 2011, the Company issued a press release announcing, among other matters disclosed, that its Board of Directors has authorized the repurchase of up to |
| 23 | 2023-08-01 |  | ✅ | The company’s board of directors has authorized an increase to its stock repurchase program by an additional 2 million shares, and as a result, the company will |
| 24 | 2007-04-18 | 100000000.0 | ✅ | The Company also is announcing today that its Board of Directors has authorized a stock repurchase program that enables the Company to purchase up to $100 milli |
| 25 | 2021-02-25 |  | ✅ | As more fully described in the attached press release dated February 25, 2021, the Board of Directors of ACNB Corporation (the “Corporation”) approved on Februa |
| 26 | 2012-04-30 |  | ✅ | Upon completion of the aforementioned stock repurchase program the Board of Directors authorized the second stock repurchase program pursuant to which the Compa |
| 27 | 2008-07-29 | 2500000000.0 | ❌ 不是新授權 | Entergy: 6-8% annual earnings per share growth, a 70 to 75% dividend payout ratio target, and capacity for a new share repurchase program targeted at $2.5 billi |
| 28 | 2017-09-11 | 1470000000.0 | ✅ | Board authorized share repurchase program up to $1.47 billion, and a 29% increase in quarterly common stock dividend • Remain committed to prudently growing loa |
| 29 | 2026-07-23 | 1000000000.0 | ✅ | a new common stock repurchase authorization of up to $1 billion. |
| 30 | 2009-04-02 |  | ✅ | On March 31, 2009, the registrant’s Board of Directors approved a Stock Buyback Program. |
| 31 | 2025-01-13 | 2000000000.0 | ❌ 不是新授權 | Achievements Internalization Capital Deployment Returns Capital Allocation Authorized new $3 billion share repurchase program Royalty Pharma’s capital allocatio |
| 32 | 2013-02-13 |  | ✅ | On February 6, 2013, Blucora’s Board of Directors approved a share repurchase program. |
| 33 | 2006-06-22 |  | ✅ | SANTA BARBARA, California, June 22, 2006 - Mentor Corporation (NYSE:MNT), a leading supplier of aesthetic medical products in the United States and internationa |
| 34 | 2024-08-07 | 4000000000.0 | ✅ | The Board also authorized a $4.0 billion increase to the share repurchase program. |
| 35 | 2016-10-12 |  | ✅ | On October 12, 2016, Home Federal Bancorp, Inc. of Louisiana (the "Company") issued a press release announcing that its Board of Directors approved a seventh st |
| 36 | 2015-04-30 | 48600000.0 | ❌ 不是新授權 | Additionally, in the second quarter, the Company spent an additional $48.6 million of the approved $200 million share repurchase program. |
| 37 | 2022-05-09 |  | ✅ | Simon’s Board of Directors has authorized a new common stock repurchase program. |
| 38 | 2008-11-03 |  | ✅ | (NASDAQ:CYBI), a leading manufacturer of premium exercise equipment for the commercial and consumer markets, today reported that its Board of Directors has auth |
| 39 | 2022-02-15 |  | ✅ | In addition, our Board authorized a quarterly dividend of $0.32 per share and increased our share repurchase authorization, which reflects the ongoing strength  |
| 40 | 2013-08-22 |  | ✅ | Our current dividend increase and expanded share repurchase authorization reflect that commitment, as does our continued focus on the elements that have made No |
| 41 | 2026-01-27 | 6000000000.0 | ✅ | The company also announced that its Board has approved a new $6.0 billion share repurchase authorization. |
| 42 | 2008-02-21 |  | ✅ | On February 20, 2008, the Company announced that the Board of Directors approved the repurchase of up to 5% of the Company's outstanding common stock, or approx |
| 43 | 2022-09-26 |  | ✅ | The new repurchase program does not obligate the Company to repurchase any shares under the authorization, and the new repurchase program may be suspended, disc |
| 44 | 2019-08-07 |  | ❌ 不是新授權 | "The Board authorized repurchase program and the recent purchases of shares by the Company and management reflect ongoing confidence in our strategy and the str |
| 45 | 2019-02-04 | 5000000.0 | ✅ | (January 30, 2019) -- The Board of Directors of Arrow Financial Corporation (NasdaqGS® - AROW) on January 30, 2019, approved a new stock repurchase program auth |
| 46 | 2014-02-05 | 500000000.0 | ✅ | On February 4, 2014, the company announced that its Board of Directors had authorized a share repurchase program of up to $500 million expected to be completed  |
| 47 | 2009-04-29 |  | ❌ 不是新授權 | Walko, President and CEO of Penns Woods Bancorp, Inc., (NASDAQ: PWOD) has announced that the Company’s Board of Directors has authorized the extension of its re |
| 48 | 2013-05-03 | 30000000.0 | ✅ | On May 3, 2013, the Company also announced that its Board of Directors has approved a share repurchase program under which the Company is authorized to repurcha |
| 49 | 2011-04-21 |  | ✅ | April 21, 2011, Athens, Tennessee — Athens Bancshares Corporation (Nasdaq: “AFCB”) (the “Company”), the holding company for Athens Federal Community Bank, annou |

## B 輪（第 3 版最終，樣本外）

錯誤：#10（恢復既有計畫）、#14（股息再投資條款）、#18（18 天前的授權）、#19（月初已公告）、#21（recently announced）、
#31（法律合約）、#35（泛稱）、#36（以過去月份命名的計畫）、#47（10b5-1 交易計畫）。第 4 版已針對這些類型修正。

| # | 申報日 | 金額 | 判定 | 原句（節錄） |
|---|---|---|---|---|
| 0 | 2026-04-16 | 10000000000.0 | ✅ | • Board of Directors authorized a new common share repurchase program of $10 billion |
| 1 | 2015-05-06 |  | ✅ | The Board of Directors has also authorized the repurchase by the Company of up to an additional 8.0 million shares of its common stock under its ongoing share r |
| 2 | 2019-02-28 | 200000000.0 | ✅ | Increased credit facility to $1 billion and announced $200 million share repurchase authorization. |
| 3 | 2017-02-02 | 1000000000.0 | ✅ | On February 2, 2017, Harris announced that its Board of Directors had approved a new $1 billion share repurchase authorization, which is in addition to the rema |
| 4 | 2007-08-09 |  | ✅ | The Company also announced that its Board of Directors has authorized a stock repurchase program of up to 500,000 shares of the Company’s common shares in open  |
| 5 | 2020-02-11 | 300000000.0 | ✅ | The Board of Directors authorized the repurchase of up to $300 million of its common stock through June 30, 2021 and approved an 18% increase in stockholder div |
| 6 | 2014-06-06 | 2000000000.0 | ✅ | (NYSE: AIG) today announced that its Board of Directors has authorized the repurchase of additional shares of AIG Common Stock with an aggregate purchase price  |
| 7 | 2011-09-21 | 400000000.0 | ✅ | (Nasdaq: CY) today announced that its board of directors has authorized a new $400 million stock repurchase program for Cypress’cs common stock. |
| 8 | 2021-12-20 | 50000000.0 | ✅ | Announces Authorization of $50 Million Share Repurchase Program |
| 9 | 2020-07-28 |  | ✅ | Eagle announced that its Board of Directors has authorized the repurchase of up to 100,000 shares of its common stock, representing approximately 1.47% of outst |
| 10 | 2022-08-18 | 2000000000.0 | ❌ 不是新授權 | The Company intends to resume its $2 billion board authorized share repurchase program following the completion of the Offers. |
| 11 | 2024-08-16 | 12000000.0 | ✅ | (the “ Company ”) announced that its Board of Directors approved a share repurchase program authorizing the Company to repurchase up to $12,000,000 of the Compa |
| 12 | 2014-06-03 | 200000000.0 | ✅ | Announces Incremental $200 Million Class A Share Repurchase Authorization |
| 13 | 2012-06-15 | 50000000.0 | ✅ | (NYSE: AIR) announced today that its Board of Directors authorized the Company to repurchase up to $50 million of its outstanding shares of common stock. |
| 14 | 2025-06-30 |  | ❌ 不是新授權 | When the Company declares a Distribution, the Plan Administrator, on the shareholder’s behalf, will receive additional authorized Shares from the Company either |
| 15 | 2018-11-08 | 500000000.0 | ✅ | In addition, the Board of Directors of the Company has authorized an additional $500 million share repurchase program to be executed into 2019. |
| 16 | 2023-06-15 | 20000000.0 | ✅ | Given the current volatility in AFC Gamma’s share price, the Board of Directors has approved a share repurchase program, authorizing the Company to repurchase u |
| 17 | 2006-02-06 |  | ✅ | (the “Registrant”) announced that its Board of Directors has authorized a share repurchase program for up to 225,000 shares of the Registrant’s outstanding comm |
| 18 | 2013-08-12 | 500000000.0 | ❌ 不是新授權 | On July 25, 2013, the Company’s board of directors approved a new share repurchase program for up to $500 million of Nielsen’s outstanding common stock. |
| 19 | 2014-04-16 | 2300000000.0 | ❌ 不是新授權 | Announced a new share repurchase authorization of $2.3 billion, effective April 1st |
| 20 | 2006-12-04 |  | ✅ | On December 1, 2006, First National Bancshares, Inc., parent company of First National Bank of the South, issued a press release announcing that its Board of Di |
| 21 | 2024-03-12 | 20000000.0 | ❌ 不是新授權 | In addition, we recently announced that our board of directors approved a separate stock repurchase program for up to $20 million of our Class A common stock. |
| 22 | 2023-02-02 | 10000000.0 | ✅ | (Nasdaq:PMCB) (“PharmaCyte” or the “Company”), a biotechnology company focused on evaluating its signature live-cell encapsulation technology, Cell-in-a-Box Ò f |
| 23 | 2009-08-10 | 15000000.0 | ✅ | On August 9, 2009, ALC’s Board of Directors authorized the repurchase of up to $15 million in Class A common stock through August 9, 2010. |
| 24 | 2023-07-26 | 50000000.0 | ✅ | Today the Board of Directors authorized a new stock repurchase program to allow for repurchases of up to $50.0 million of our common stock from July 31, 2023 th |
| 25 | 2011-11-16 | 500000000.0 | ✅ | Announces Additional $500 Million Share Repurchase Authorization |
| 26 | 2021-11-10 | 100000000.0 | ✅ | On November 10, 2021, EnerSys issued a press release announcing the establishment of a new $100 million stock repurchase authorization with no expiration date a |
| 27 | 2012-11-07 | 250000000.0 | ✅ | The Board also authorized the repurchase of up to $250 million of the Company’s outstanding common stock during a two-year period. |
| 28 | 2026-02-24 | 2000000.0 | ✅ | (NASDAQ: HTCR) (“HeartCore” or the “Company”), an IPO consulting services company based in Tokyo, today announced that its Board of Directors has authorized a s |
| 29 | 2024-03-07 |  | ✅ | On March 7, 2024, the Company announced that its Board of Directors (the “Board”) has authorized, effective March 6, 2024, a common stock repurchase program to  |
| 30 | 2015-09-02 | 10000000.0 | ✅ | Announces Authorization of New $10 Million Share Repurchase Program |
| 31 | 2022-01-21 |  | ❌ 不是新授權 | Class A Common Shares pursuant to a PubCo Board approved repurchase plan or program (or otherwise in connection with a transaction approved by the PubCo Board)  |
| 32 | 2006-05-03 |  | ✅ | (NASDAQ: IOSP) today announced that its Board of Directors has authorized a further Rule 10b5-1 stock re-purchase plan. |
| 33 | 2014-07-25 |  | ✅ | The IDEXX Board of Directors has authorized the repurchase by the Company of up to an additional five million shares of its common stock under its ongoing share |
| 34 | 2011-08-17 | 20000000.0 | ✅ | (the "Company") issued a press release announcing that its Board of Directors authorized the repurchase of up to $20.0 million of the Company’s outstanding comm |
| 35 | 2015-05-08 |  | ❌ 不是新授權 | The Board of Directors has, from time to time, approved stock repurchase programs enabling Covance to repurchase shares of its common stock. |
| 36 | 2024-07-25 |  | ❌ 不是新授權 | The Company's Board of Directors authorized the repurchase of 944,279 shares through such new share repurchase plan ("April 2024 Stock Repurchase Plan"). |
| 37 | 2021-03-11 | 15000000.0 | ✅ | In addition, its board authorized the repurchase of up to $15 million of the company’s common shares. |
| 38 | 2008-12-16 | 200000000.0 | ⚠️ 金額錯 | On December 15, 2008, Exterran Holdings, Inc. issued a press release announcing that our board of directors has increased our share repurchase program, from $20 |
| 39 | 2007-07-30 | 1000000000.0 | ✅ | Company’s board of directors has authorized the re-purchase of up to $1 billion |
| 40 | 2021-09-16 | 25000000.0 | ✅ | “We’re also pleased to announce that our Board of Directors has authorized us to repurchase up to $25 million of our shares. |
| 41 | 2008-05-20 | 750000000.0 | ✅ | The company also announced today that its board of directors authorized on May 20, 2008 the repurchase of an additional $750 million of its Class A Common Stock |
| 42 | 2016-02-29 | 100000000.0 | ✅ | - Board Authorizes $100 Million Increase in Share Repurchase Program to $250 Million – |
| 43 | 2019-08-07 | 300000000.0 | ✅ | On August 7, 2019, the Board of Directors approved an incremental $300 million in share repurchases |
| 44 | 2010-08-05 | 200000000.0 | ✅ | Authorization of a new $200 million share repurchase program |
| 45 | 2022-12-15 | 30000000.0 | ✅ | (Nasdaq: OB), a leading recommendation platform for the open web, today announced the Company’s Board of Directors approved a new stock repurchase program under |
| 46 | 2015-02-27 | 100000000.0 | ✅ | The Company also announced that its Board of Directors has authorized a stock repurchase program under which the Company can repurchase up to $100 million of it |
| 47 | 2026-09-15 |  | ❌ 不是新授權 | Our Board of Directors also authorized us to enter into one or more Rule 10b5-1 trading plans for share repurchases. |
| 48 | 2025-12-18 | 150000000.0 | ✅ | Board Authorizes $150 Million Expanded Share Repurchase Authorization as Initial Step to Deploy Proceeds from Successful Sale-Leaseback Transactions |
| 49 | 2009-01-22 |  | ✅ | On January 20, 2009, the Company’s Board of Directors authorized a stock repurchase plan to repurchase up to 5% of its outstanding publicly held common stock, o |
