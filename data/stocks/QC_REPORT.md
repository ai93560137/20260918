# 數據品質日報（2026-09-22）

由 `scripts/check_data_quality.py` 產生。主來源 yfinance（`data/stocks/`）113 檔，第二來源港交所官方快照（`data/stocks_hkex/`）0 份（最新 無），公司名紀錄 106 檔。

**🔴 嚴重 12 項 ｜ 🟡 注意 111 項 ｜ ✅ 已確認 8 項**

確認沒問題的項目加進 `scripts/qc_acks.json`（key 格式 `<TICKER>:<檢查>`）。

## 🔴 嚴重（會污染回測，先處理）

| 代碼 | 檢查 | 說明 |
|---|---|---|
| 0013.HK | code_reuse_suspected | 2010-2015年是成分股（Hutchison Whampoa Ltd），但價格 2021-06-30 才開始——代碼被重新分配給別家公司，現有價格不是當年那家，回測不能拿來代表它 |
| 1880.HK | code_reuse_suspected | 2011-2018年是成分股（Belle International），但價格 2022-08-25 才開始——代碼被重新分配給別家公司，現有價格不是當年那家，回測不能拿來代表它 |
| 0013.HK | name_mismatch | yfinance「HUTCHMED (China) Limited」vs Wikipedia 2015年「Hutchison Whampoa Ltd」（相似度 0.45） |
| 0322.HK | name_mismatch | yfinance「Tingyi (Cayman Islands) Holding Corp.」vs Wikipedia 2025年「Tingyi」（相似度 0.44） |
| 0386.HK | name_mismatch | yfinance「China Petroleum & Chemical Corporation」vs Wikipedia 2025年「Sinopec Corp」（相似度 0.32） |
| 0388.HK | name_mismatch | yfinance「Hong Kong Exchanges and Clearing Limited」vs Wikipedia 2025年「HKEx Limited」（相似度 0.22） |
| 0823.HK | name_mismatch | yfinance「Link Real Estate Investment Trust」vs Wikipedia 2025年「Link REIT」（相似度 0.38） |
| 1199.HK | name_mismatch | yfinance「COSCO SHIPPING Ports Limited」vs Wikipedia 2014年「COSCO Pacific Ltd」（相似度 0.48） |
| 1880.HK | name_mismatch | yfinance「China Tourism Group Duty Free Corporation Limited」vs Wikipedia 2018年「Belle International」（相似度 0.24） |
| 2003.HK | name_mismatch | yfinance「VCREDIT Holdings Limited」vs Wikipedia 2019年「Country Garden」（相似度 0.29） |
| 2038.HK | name_mismatch | yfinance「FIH Mobile Limited」vs Wikipedia 2011年「Foxconn International Holdings Ltd」（相似度 0.26） |
| 6690.HK | name_mismatch | yfinance「Haier Smart Home Co., Ltd.」vs Wikipedia 2025年「Haier」（相似度 0.48） |

## 🟡 注意

| 代碼 | 檢查 | 說明 |
|---|---|---|
| 0011.HK | constituent_no_data | 2010-2025年是成分股（Hang Seng Bank Ltd），但主來源完全沒有價格（多半已下市/私有化——回測測不到它，倖存者偏差殘留） |
| 0494.HK | constituent_no_data | 2010-2016年是成分股（Li & Fung Ltd），但主來源完全沒有價格（多半已下市/私有化——回測測不到它，倖存者偏差殘留） |
| 0001.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0002.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0003.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0004.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0005.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0006.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0012.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0013.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0016.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0017.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0019.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0023.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0027.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0066.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0083.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0101.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0135.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0144.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0151.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0175.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0241.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0267.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0288.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0291.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0293.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0316.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0322.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0330.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0386.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0388.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0669.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0688.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0700.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0762.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0823.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0836.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0857.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0868.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0881.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0883.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0939.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0941.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0960.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0968.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0981.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0992.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1038.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1044.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1088.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1093.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1099.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1109.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1113.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1177.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1199.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1209.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1211.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1288.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1299.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1339.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1378.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1398.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1810.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1876.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1880.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1898.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1928.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1929.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 1997.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2003.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2007.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2015.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2018.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2020.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2038.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2269.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2313.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2318.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2319.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2331.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2359.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2382.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2388.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2600.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2601.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2628.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2688.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2800.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 2899.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 3328.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 3690.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 3692.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 3968.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 3988.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 6030.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 6098.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 6618.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 6690.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 6862.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9618.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9633.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9888.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9901.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9961.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9988.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 9999.HK | no_second_source | 港交所快照沒有這檔，無法交叉驗證收市價 |
| 0330.HK | ohlc_auction | 近30天 2 根開/收市價落在高低價外（多半是競價時段慣例）：2026-08-24, 2026-09-08 |
| 0960.HK | wiki_name_varies | 最新記載「Longfor Properties」，但 2023年「The Link REIT」 |
| 6098.HK | wiki_name_varies | 最新記載「Country Garden」，但 2023年「CG SERVICES」 |

## ✅ 已確認（不再警告）

| 代碼 | 檢查 | 確認理由 |
|---|---|---|
| 0001.HK | wiki_name_varies | 真實重組：2015年長實(Cheung Kong)與和黃重組為長和(CK Hutchison)，沿用0001代碼。回測注意：同一代碼前後是不同業務結構的公司 |
| 0006.HK | wiki_name_varies | 真實改名：香港電燈集團(HK Electric Holdings)2011年改名電能實業(Power Assets)，同一公司 |
| 0101.HK | wiki_name_varies | Wikipedia 2023年修訂版本本身名字錯位一列（已核對原始 wikitext：代碼正確、名字錯位，2024年已修正），非代碼重用 |
| 0322.HK | wiki_name_varies | 同一公司：康師傅 Tingyi (Cayman Islands) Holding Corp，後期 Wikipedia 只寫簡稱 Tingyi |
| 0688.HK | wiki_name_varies | Wikipedia 2023年修訂版本本身名字錯位一列（同0101），非代碼重用 |
| 0823.HK | wiki_name_varies | Wikipedia 2023年修訂版本本身名字錯位一列（同0101），非代碼重用 |
| 1299.HK | wiki_name_varies | 同一公司：友邦保險 AIA Group，早期 Wikipedia 用舊名 American International Assurance |
| 3968.HK | wiki_name_varies | Wikipedia 2023年修訂版本本身名字錯位一列（金融分類，交通銀行3328於2023年剔除），非代碼重用 |

## 歷史已知（30 天前的逐根問題，只統計不警告）

格式：根數（最近一次日期）。回測前如果用到這些日期要留意；`nonpositive` / `ohlc_high_lt_low` 是真的髒值，回測引擎要能處理。

| 代碼 | nonpositive | ohlc_high_lt_low | ohlc_auction | bigmove |
|---|---|---|---|---|
| 0001.HK |  | 1（2009-12-24） | 3（2011-10-07） |  |
| 0002.HK |  | 2（2009-12-24） | 1（2010-02-04） |  |
| 0003.HK |  |  | 1（2011-04-04） |  |
| 0004.HK |  |  | 12（2026-04-22） |  |
| 0005.HK |  | 5（2010-01-19） | 2（2012-03-28） |  |
| 0006.HK |  | 2（2010-02-04） | 1（2023-11-03） |  |
| 0012.HK |  |  | 3（2022-11-14） |  |
| 0013.HK |  |  | 1（2026-06-11） |  |
| 0016.HK |  | 4（2010-02-04） |  |  |
| 0017.HK |  | 3（2010-02-04） | 3（2026-06-04） |  |
| 0019.HK |  | 3（2010-02-04） | 6（2025-08-11） |  |
| 0023.HK |  | 2（2010-01-19） | 10（2024-06-24） |  |
| 0027.HK |  | 2（2010-01-15） | 1（2011-04-04） | 1（2008-12-18） |
| 0066.HK |  |  | 3（2011-10-07） |  |
| 0083.HK |  | 4（2010-01-19） | 7（2024-07-17） |  |
| 0101.HK |  | 3（2010-02-04） | 4（2025-09-16） |  |
| 0135.HK |  | 7（2010-07-12） | 3（2026-02-09） |  |
| 0144.HK |  | 2（2010-01-19） | 10（2026-03-04） |  |
| 0151.HK |  | 4（2010-01-19） | 5（2025-09-25） |  |
| 0175.HK |  | 7（2010-07-16） | 1（2011-04-04） |  |
| 0241.HK |  | 4（2009-12-24） | 11（2017-03-06） | 6（2015-04-15） |
| 0267.HK |  | 2（2010-01-19） | 6（2024-06-18） | 1（2008-10-21） |
| 0291.HK |  | 2（2010-02-04） | 6（2025-11-12） | 2（2015-09-18） |
| 0293.HK |  | 2（2010-01-19） | 4（2026-04-10） |  |
| 0316.HK |  | 1（2009-12-31） | 31（2025-10-08） |  |
| 0322.HK |  | 2（2010-02-04） | 8（2026-04-30） |  |
| 0330.HK |  | 1（2010-01-15） | 10（2026-08-19） | 4（2025-08-22） |
| 0386.HK |  | 1（2009-12-31） | 2（2011-09-26） |  |
| 0388.HK |  | 1（2010-01-15） | 2（2011-10-07） |  |
| 0669.HK |  | 2（2009-12-31） | 1（2011-09-26） | 1（2008-10-30） |
| 0688.HK |  | 2（2010-01-19） | 1（2011-10-07） |  |
| 0700.HK |  | 2（2010-01-15） | 1（2014-05-15） |  |
| 0762.HK |  |  | 1（2011-04-04） |  |
| 0823.HK |  |  | 1（2011-04-04） |  |
| 0836.HK |  | 2（2010-02-04） | 4（2020-09-07） |  |
| 0857.HK |  | 5（2010-06-25） | 2（2011-02-18） |  |
| 0881.HK |  |  | 17（2026-07-31） |  |
| 0883.HK |  | 2（2010-01-15） | 4（2011-10-07） |  |
| 0939.HK |  | 2（2009-04-23） | 1（2011-10-07） |  |
| 0941.HK |  | 1（2009-04-23） | 1（2011-04-04） |  |
| 0960.HK |  |  | 2（2017-04-13） |  |
| 0968.HK |  |  | 1（2018-12-07） |  |
| 0981.HK |  | 3（2010-07-19） |  | 2（2009-11-11） |
| 0992.HK |  | 4（2010-07-09） | 1（2011-10-07） |  |
| 1038.HK |  | 1（2009-12-24） |  |  |
| 1044.HK |  | 4（2010-01-19） | 2（2025-02-28） |  |
| 1088.HK |  | 1（2010-01-15） | 2（2011-10-07） |  |
| 1093.HK |  | 9（2010-07-02） |  |  |
| 1099.HK |  | 2（2010-02-04） | 3（2011-11-08） |  |
| 1109.HK |  | 3（2010-01-19） | 2（2011-09-26） |  |
| 1113.HK |  |  | 1（2023-10-09） |  |
| 1177.HK |  | 2（2010-01-19） | 3（2015-09-21） |  |
| 1199.HK |  | 3（2010-07-08） | 7（2026-05-14） |  |
| 1209.HK |  |  | 3（2023-07-26） |  |
| 1211.HK |  |  | 1（2011-10-07） | 1（2008-09-29） |
| 1288.HK |  |  | 2（2011-10-07） |  |
| 1299.HK |  |  | 2（2011-10-07） |  |
| 1339.HK |  |  | 1（2022-02-15） |  |
| 1378.HK |  |  | 5（2018-05-18） |  |
| 1398.HK |  | 2（2010-01-15） | 2（2011-10-07） |  |
| 1880.HK |  |  | 1（2024-12-30） |  |
| 1898.HK |  | 2（2009-12-31） | 4（2023-11-01） |  |
| 1928.HK |  |  | 2（2011-10-07） |  |
| 1929.HK |  |  | 2（2024-03-06） |  |
| 1997.HK |  |  | 5（2025-12-22） |  |
| 2003.HK |  |  | 19（2026-07-29） |  |
| 2007.HK |  | 6（2010-06-23） | 4（2011-09-26） | 1（2022-11-14） |
| 2018.HK |  | 1（2010-01-15） | 2（2015-07-27） |  |
| 2020.HK |  | 4（2010-01-19） | 5（2016-10-24） |  |
| 2038.HK |  | 2（2009-12-31） | 3（2026-08-03） |  |
| 2269.HK |  |  | 1（2017-07-04） |  |
| 2313.HK |  | 8（2010-07-06） | 1（2016-07-06） |  |
| 2318.HK |  | 1（2010-01-15） | 3（2011-10-07） |  |
| 2319.HK |  | 2（2009-12-31） | 2（2011-10-07） | 1（2008-09-23） |
| 2331.HK |  |  | 4（2015-09-09） |  |
| 2359.HK |  |  | 1（2019-12-16） |  |
| 2382.HK |  | 2（2009-12-31） | 2（2012-11-29） |  |
| 2388.HK |  | 2（2009-12-31） | 1（2011-10-07） |  |
| 2600.HK |  | 5（2009-12-31） | 1（2024-02-08） |  |
| 2601.HK |  |  | 3（2015-12-31） |  |
| 2628.HK |  | 1（2010-01-15） | 2（2021-06-28） |  |
| 2688.HK |  |  | 3（2025-08-13） |  |
| 2800.HK | 19（2010-01-04） |  | 4（2010-12-28） |  |
| 2899.HK |  | 1（2009-09-17） |  |  |
| 3328.HK |  | 4（2010-03-25） | 2（2022-11-25） |  |
| 3692.HK |  |  | 6（2026-07-09） |  |
| 3968.HK |  |  | 1（2011-10-07） |  |
| 3988.HK |  | 3（2010-06-23） | 1（2011-04-04） |  |
| 6030.HK |  |  |  | 8（2011-10-06） |
| 6098.HK |  |  | 2（2025-12-03） |  |
| 6862.HK |  |  | 2（2020-08-05） |  |
| 9633.HK |  |  | 3（2025-12-17） |  |
| 9901.HK |  |  | 2（2025-09-05） | 2（2021-07-26） |
| AAPL |  |  |  | 1（2000-09-29） |
| NVDA |  |  |  | 1（2000-03-07） |
