# 每日新高名單（analysis/newhighs/）

每個交易日一份名單，檔名是**收市日**：

- `<日期>.md`：給人看，按港股 → 日股 → 美股、12 → 9 → 6 → 3 個月、板塊分組
- `<日期>.csv`：給程式看（其他分支、試算表）
- `summary.csv`：每天每個市場的檔數（成分股、200 日線上、12/9/6/3 個月新高）

由 `scripts/daily_topdown.py` 產生，`.github/workflows/daily_topdown.yml` 每個交易日早上自動更新並 commit。
每次都會重算最近 5 個交易日，遲到或被補回的收市數據（例如 Yahoo 暫時缺的一天）會自動補進當天的名單。
某個市場當天沒有收市就不列該市場，並按三地官方休市日曆（`universes/calendars/`）註明是「休市（假期名）」還是「有開市但數據未到」。

## 規則（跟每日報告一致）

1. 指數現任成分股（point-in-time）：港股恒生指數、日股日經225、美股 S&P 500
2. 當天收市在 200 日平均線之上（含股息還原價）
3. 當天收市價**高於**之前 N 個月（連當天 63／126／189／252 個交易日）的**盤中最高價**；
   原始價（按拆股還原、不按股息），跟報價頁「52 週高」同一把尺
4. 12 個月新高必然也是 9／6／3 個月新高，所以同一隻股票會在每個窗口各出現一次
5. 連續天數按該股自己的交易日往回數（假期不算中斷），回測時可直接用 `streak_window` / `streak_longest` 篩選

描述性篩選，未經回測，不是買入建議。

## CSV 欄位

| 欄位 | 說明 |
|---|---|
| `date` | 收市日 |
| `market` / `market_zh` | `hk` 港股、`jp` 日股、`us` 美股 |
| `window_months` | 12、9、6、3 |
| `sector` | 板塊（yfinance 行業，中文） |
| `ticker` | 顯示代號：`2359.HK`、`4502.JP`、`AMD` |
| `name` | 港股：港交所官方中文簡稱；日股：日文名；美股：英文名 |
| `close` | 當天收市價（原始價） |
| `prior_high` | 之前 N 個月的盤中最高價（收市價要高於它才算新高） |
| `pct_above_ma200` | 高於 200 日線的百分比 |
| `longest_months` | 這隻股票當天創新高的最長窗口（12／9／6／3） |
| `streak_window` | 連續第幾個交易日創**這一行窗口**的新高（且在 200 日線上）；中斷一天就由 1 重新計 |
| `streak_longest` | 連續第幾個交易日**最長窗口不變**（例如昨天 3 個月、今天升到 6 個月 → 今天是 1），跟 Telegram 的數字 emoji 一致 |
| `yahoo_ticker` | Yahoo 代號（日股是 `.T`），給程式抓數據用 |

## 其他分支怎麼讀

名單只在 `claude/gifted-carson-v2tvhw` 這條分支更新，其他分支不會自動有。要用時：

```bash
git fetch origin claude/gifted-carson-v2tvhw
git checkout origin/claude/gifted-carson-v2tvhw -- analysis/newhighs/     # 複製整個資料夾到目前分支
# 或只讀、不複製：
git show origin/claude/gifted-carson-v2tvhw:analysis/newhighs/2026-09-22.csv
```
