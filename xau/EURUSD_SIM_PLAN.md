# EURUSD 即日回測模擬方案（922 停 API 後）— 待使用者批

使用者 10-27 原話：「EURUSD 暫停 API CALL，暫時只做即日回測模擬」。總指揮 14:23 UTC 已把 zhuge-eurusd `XAU_ACTIVE_HOURS_UTC` 改成 `00-00`
（零長度時段：空倉永遠唔問 Claude，Haiku 篩選同 Opus 都停；有倉時仍會管倉），修訂 **00024-b78**（退回 `rollback --to zhuge-eurusd-00023-c87` 即恢復 07–17）。
核實（14:26 UTC）：922 空倉、usage_today 由 14:23 起凍結（$3.69、259 次決策）、之後再冇 decide 紀錄、心跳正常。

參考龍飛陣 R295（`research/longfei_rulesim/rulesim.py`）：每日收市後用當日 1 分鐘 K 線按機械規則回測，唔叫 AI，令學習樣本唔斷。
**只係紙上回測，唔落單；規則一次過寫死，改規則要登記 IDEAS。**

## 1. 數據（而家嘅缺口）
- zhuge-eurusd 只存最近 400 根 M1（`fx/eurusd/m1.json`，≈6.7 小時）同 M15，冇全日存檔；決策日誌只有 07–17 UTC 每分鐘價、冇高低。
- **A1（建議，主）**：`xau/main.py` 心跳：每根新 M1 收盤 `append_jsonl("fx/eurusd/bars/<UTC 日>.jsonl", bar)`（同 decisions 日誌同頻率、每分鐘一次 GCS append；
  EA 重啟時 `m1_hist` 回填一併寫入）。十行內改動，xau／xau-sig 一樣受惠（金價存檔）。部署要使用者批。
- **A2（後備／補歷史）**：Actions 用 yfinance `EURUSD=X` 1 分鐘（只回 7 日）補 10-20 起嘅日子，標記「估算」（非經紀價、有缺口）。
- 日線趨勢：yfinance `EURUSD=X` 日線 20 日均線（同 R295 美股做法）。

## 2. 規則（R295 外匯版「倫敦開市區間突破」，一次過寫死）
1. 開市區間（OR）＝ **07:00–07:30 UTC** 高低位（倫敦開市；922 原本活躍時段 07–17 UTC 嘅開頭）。
2. 之後第一支 **5 分鐘 K 線收市**突破 OR 先入場；**每日最多 1 張**；15:00 UTC 之後唔開新倉。
3. 只順日線方向：昨收 > 20 日均線只做好、< 只做淡（同 R280／R293 邏輯）。
4. 止蝕＝OR 另一邊；最少 **7 pip**（＝ R340 `MODIFY_MIN_DIST` 5＋1＋1，經紀 stops level 要 ≥6）、多過 **25 pip** 唔做（SL 太闊＝區間日）。
5. 浮賺 ≥ 1R 止蝕移開倉價，再跟最近 3 支 M5 低／高位收緊（只准收緊）——即係 `hold_rules` 嘅紙上版。
6. **17:00 UTC 收市平倉**（922 原本時段尾）；同一支 K 線掂止蝕又掂目標當止蝕（保守）。
7. 成本每張 **1.0 pip**（`PRODUCT["spread_pips"]`）。注碼 0.01 手：1 pip ＝ US$0.10 ≈ 0.78 HKD，方便同 922 真倉（E1–E4 合計 −12.63 HKD）直接比。
- 同時免費跑變體（只記錄、唔影響主規則）：(B) OR 60 分鐘；(C) OR 闊度 ≥ 前 20 日中位數先做；(D) 冇日線過濾。

## 3. 輸出
- GCS `fx/eurusd/rulesim/<日>.json`（當日 OR、有冇入場、入場／出場價、pip、HKD、原因）＋ `fx/eurusd/rulesim/summary.json`（累計、各變體）。
- 每日 Actions `eurusd_rulesim.yml` **17:40 UTC（01:40 HKT）週一至五**（收市 17:00 後）；只讀 GCS＋yfinance，$0 API。
- zhuge-eurusd 頁加「🧪 即日回測（規則版）」一節（同 `main.py` 龍飛陣 `_lf_rulesim_section` 做法）。

## 4. 預先登記（IDEAS #139）檢討標準
- **20 個交易日**或 **≥10 張**後判：(a) 扣 1 pip 成本後期望值 > 0；(b) 最大回撤 < 3R；(c) 勝率×平均贏 vs 輸 嘅 profit factor ≥ 1.2；
  (d) 同 922 Opus 真倉（10-23–10-27 四張 −12.63 HKD）比，同期紙上成績要好過佢。
- 達標 → 提案「922 規則引擎真倉（唔叫 API）」交使用者批；唔達標 → EURUSD 繼續停，變體 B／C／D 有邊個達標就再登記，唔喺同一批數據上調參數。

## 5. 要使用者批嘅動作
1. A1 存檔改動部署 zhuge-eurusd（同埗 zhuge-xau 可選）——總指揮 dry-run，使用者批 `--yes`。
2. 開 Actions workflow `eurusd_rulesim.yml`（預設分支生效；只讀 GCS，用現有 WIF）。
3. 規則 §2 照上面寫死（如要改 OR 時段／最少止蝕先講）。
