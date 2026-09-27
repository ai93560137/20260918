# 數據品質比對報告（2026-09-27 UTC）

每類數據各一個閘門。**只取 PASS 的類別**；FAIL 先看下面「未解釋的差異」。規則見 `data/external/README.md` 第六節。

| 類別 | 閘門 | ✅ 一致 | ℹ️ 記錄 | ⏭️ 略過 | ⚠️ 已知 | ❌ 未解釋 |
|---|---|---:|---:|---:|---:|---:|
| `futu_vs_web` | ✅ PASS | 4 | 2 | 1 | 0 | 0 |
| `ibkr_vs_web` | ❌ FAIL | 91 | 0 | 9 | 0 | 14 |
| `web_vs_web` | ❌ FAIL | 59 | 0 | 0 | 0 | 61 |
| `canary_inputs` | ✅ PASS | 236 | 0 | 1 | 0 | 0 |
| `internal` | ✅ PASS | 2 | 1 | 0 | 0 | 0 |

## 未解釋的差異（按原因歸類，每類最多列 8 筆，全部見 results_latest.csv）

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

### web_vs_web｜Nasdaq↔Yahoo｜數值不同：2 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| META | 2026-09-22 | close | web_nasdaq 736.595 | web_yahoo 736.6 | -0.0007 | 快照 quotes_2026-09-22.json |
| CPRT | 2026-09-23 | close | web_nasdaq 28.865 | web_yahoo 28.87 | -0.0173 | 快照 quotes_2026-09-23.json |

### web_vs_web｜Nasdaq↔Yahoo｜日期錯位：59 筆

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |
|---|---|---|---|---|---:|---|
| ABT | 2026-09-24 | close | web_nasdaq 103.49 | web_yahoo 101.07 | 2.3944 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| AJG | 2026-09-24 | close | web_nasdaq 229.64 | web_yahoo 227.13 | 1.1051 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| APP | 2026-09-24 | close | web_nasdaq 315.25 | web_yahoo 312.47 | 0.8897 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| BBWI | 2026-09-24 | close | web_nasdaq 17.02 | web_yahoo 16.8 | 1.3095 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| BR | 2026-09-24 | close | web_nasdaq 163.45 | web_yahoo 162.66 | 0.4857 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| CNC | 2026-09-24 | close | web_nasdaq 62.08 | web_yahoo 61.92 | 0.2584 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| COHR | 2026-09-24 | close | web_nasdaq 300.6 | web_yahoo 290.61 | 3.4376 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |
| D | 2026-09-24 | close | web_nasdaq 61.17 | web_yahoo 60.4 | 1.2748 | 快照 quotes_2026-09-24.json；日期錯位：web_nasdaq 的值等於 web_yahoo 的前一交易日 2026-09-23 |

查明原因後，把 `代號,日期,欄位,原因,登記人` 加進 `known_issues.csv`（代號或日期可填 `*`），下次就會列為 ⚠️ 已知。查不出原因的不要登記，數據先不要用。

## 口徑不同、只記錄的欄位

| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % |
|---|---|---|---|---|---:|
| US.QQQ | 2026-09-25 | open | 742.83 | 742.84 | -0.0013 |
| US.QQQ | 2026-09-25 | volume | 27752952.0 | 30017218.0 | -7.5432 |

## 封存內部檢查

- `US.QQQ` 2026-09-25：期權清洗規則（手冊 §10），bid>0 10/10；價差≤20%中價 10/10；|delta| 0.10–0.90 10/10

## 抽樣

- 種子 = 2026-09-27；IBKR 每市場 20 檔、Yahoo↔Nasdaq 30 檔。明細：`results_latest.csv`。
- 明天給 Futu 抓日線的清單（`futu_sample.txt`）：46 個代號，含錨點 HK.800000, US.SPY, US.QQQ。
