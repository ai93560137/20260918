# 數據品質比對報告（2026-09-29 UTC）

每類數據各一個閘門。**只取 PASS 的類別**；🟡 僅同源 = 日期與抄錄沒錯、數值未經獨立來源驗證；FAIL 先看下面「未解釋的差異」。規則見 `data/external/README.md` 第六節與 `data/external/SOP.md`。

| 類別 | 閘門 | ✅ 一致 | 其中獨立來源 | ℹ️ 記錄 | ⏭️ 略過 | ⚠️ 已知 | ❌ 未解釋 |
|---|---|---:|---:|---:|---:|---:|---:|
| `futu_vs_web` | ❌ FAIL | 6 | 6 | 4 | 1 | 0 | 1 |
| `ibkr_vs_web` | ❌ FAIL | 91 | 91 | 0 | 9 | 0 | 14 |
| `web_vs_web` | ❌ FAIL | 59 | 59 | 0 | 0 | 0 | 91 |
| `canary_inputs` | 🟡 僅同源 | 236 | 0 | 0 | 2 | 0 | 0 |
| `internal` | ✅ PASS | 6 | 6 | 2 | 0 | 0 | 0 |

## 未解釋的差異（按原因歸類，每類最多列 8 筆，全部見 results_latest.csv）

### futu_vs_web｜5分K合成日線｜數值不同：1 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| US.QQQ | 2026-09-25 | high | futu_5m 745.915 | web_yahoo 745.92 | -0.0007 |  |

### ibkr_vs_web｜股票收市｜數值不同：14 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| 0144.HK | 2026-09-24 | open | ibkr 16.49 | web_yahoo 16.48 | 0.0607 |  |
| 0939.HK | 2026-09-24 | open | ibkr 9.6 | web_yahoo 9.585 | 0.1565 |  |
| 0992.HK | 2026-09-24 | open | ibkr 36.4 | web_yahoo 36.5 | -0.274 |  |
| 1038.HK | 2026-09-23 | close | ibkr 65.26 | web_yahoo 65.25 | 0.0153 |  |
| 1288.HK | 2026-09-24 | open | ibkr 6.445 | web_yahoo 6.44 | 0.0776 |  |
| 1997.HK | 2026-09-24 | open | ibkr 30.6 | web_yahoo 30.7 | -0.3257 |  |
| 2269.HK | 2026-09-24 | open | ibkr 52.4 | web_yahoo 52.5 | -0.1905 |  |
| 2359.HK | 2026-09-24 | open | ibkr 207.0 | web_yahoo 206.8 | 0.0967 |  |

### web_vs_web｜Nasdaq↔Yahoo｜數值不同：1 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| CPRT | 2026-09-22 | close | web_nasdaq 28.795 | web_yahoo 28.8 | -0.0174 | 快照 quotes_2026-09-22.json |

### web_vs_web｜Nasdaq↔Yahoo｜日期錯位：90 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| ALAB | 2026-09-24 | close | web_nasdaq 360.46 | web_yahoo 360.51 | -0.0139 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| ANF | 2026-09-24 | close | web_nasdaq 132.25 | web_yahoo 134.3 | -1.5264 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| AXON | 2026-09-24 | close | web_nasdaq 450.61 | web_yahoo 445.0 | 1.2607 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| BATRA | 2026-09-24 | close | web_nasdaq 58.09 | web_yahoo 58.85 | -1.2914 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| BG | 2026-09-24 | close | web_nasdaq 111.48 | web_yahoo 110.21 | 1.1523 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| CDW | 2026-09-24 | close | web_nasdaq 146.16 | web_yahoo 139.46 | 4.8042 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| CRWD | 2026-09-24 | close | web_nasdaq 262.49 | web_yahoo 259.67 | 1.086 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| DVN | 2026-09-24 | close | web_nasdaq 48.04 | web_yahoo 48.9 | -1.7587 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |

查明原因後，把 `代號,日期,欄位,原因,登記人` 加進 `known_issues.csv`（代號或日期可填 `*`），下次就會列為 ⚠️ 已知。查不出原因的不要登記，數據先不要用。

## 口徑不同、只記錄的欄位

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % |
|---|---|---|---|---|---:|
| US.QQQ | 2026-09-25 | volume | 27752952.0 | 30249200.0 | -8.2523 |
| US.QQQ | 2026-09-28 | volume | 19504501.0 | 41420278.0 | -52.9107 |

## 封存內部檢查

- `XAUUSD` 2026-09-25：MT5 M1 OHLC，1 根，高低不合 0，四價相同 0
- `XAUUSD` 2026-09-28：MT5 M1 OHLC，1378 根，高低不合 0，四價相同 0
- `XAUUSD` 2026-09-29：MT5 M1 OHLC，149 根，高低不合 0，四價相同 0
- `US.QQQ` 2026-09-25：期權清洗規則（手冊 §10），bid>0 2060/2060；價差≤20%中價 2060/2060；|delta| 0.10–0.90 2060/2060
- `US.QQQ` 2026-09-28：期權清洗規則（手冊 §10），bid>0 1310/1320；價差≤20%中價 1310/1320；|delta| 0.10–0.90 1320/1320

## 抽樣

- 種子 = 2026-09-29；IBKR 每市場 20 檔、Yahoo↔Nasdaq 30 檔。明細：`results_latest.csv`。
- 明天給 Futu 抓日線的清單（`futu_sample.txt`）：419 個代號，已排優先順序，本地取前 FUTU_DAILY_MAX 個。
- 明天給 IBKR 的請求清單（`ibkr_sample.txt`）：7 個指數錨點＋美股 30＋港股 15。
- `canary_inputs` 裡標「同源 Yahoo」的只驗抄錄與日期；數值真偽要看「IBKR 獨立來源」與 Futu 恒指兩項。
