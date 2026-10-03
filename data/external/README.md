# 外部來源數據（data/external/）

**三個外部來源，每天由預設分支 `claude/gcp-trading-v12-rewrite-bz75t2` 自動彙整到這裡。**
其他分支一律從這裡取，不要各自重抓、也不要在別的分支改這個資料夾（每天會被覆蓋）。

- 彙整腳本：`scripts/external_data_sync.py`
- 排程：`.github/workflows/external_data_daily.yml`，每天 00:17 UTC（香港 08:17）
- 作業程序：[`SOP.md`](SOP.md)（每日檢查、擴充取數、差異處理）
- 最新狀態：[`STATUS.md`](STATUS.md)（每個系列的最新日期與列數、本次執行結果）
- 數據品質：[`qc/QC_REPORT.md`](qc/QC_REPORT.md)、[`qc/GATE.json`](qc/GATE.json)（第六節）

## 一、三個來源

| 來源 | 在哪裡跑 | 目前取什麼 | 頻率 | 彙整到 |
|---|---|---|---|---|
| **MT5** | 使用者的 MT5 終端機，EA 推到 Cloud Run | XAUUSD **CFD** 的 M1 | 開市時每分鐘 | `mt5/XAUUSD/M1/<年>/<日期>.csv.gz` |
| **Futu** | 使用者的 Windows 電腦，OpenD 加 `futu/push_to_gcp.py` 推到 Cloud Run | US.QQQ 5 分 K、最近到期日最接近現價 5 個行使價的 Call／Put IV 與 Greeks | 腳本常駐時每 5 分鐘 | `futu/<代號>/K_5M/<年>/<日期>.csv.gz`、`futu/<代號>/options/<年>/<日期>.csv.gz` |
| **Futu 日線抽樣** | 同上，腳本 v4 每天香港時間 16:30–21:00 一次 | `qc/futu_sample.txt` 的代號（錨點＋爭議＋隨機）最近 20 根日 K | 每天一次 | `futu/_K_DAY/<年>/<日期>.csv.gz`（含 `code` 欄） |
| **IBKR** | 雲垂的 GCP VM，IB Gateway paper 帳戶，延遲數據，唯讀 | 日經 N225、EURO STOXX 50 週權對月權 ATM IV；股票收市／開市覆核（依需求） | 平日一次；覆核依需求 | `ibkr/iv_term_structure/ib_iv_log.csv`、`ibkr/stock_closes/` |

MT5 與 Futu 的原始資料在 GCS bucket 的 `archive/` 按日封存（main.py R95），這裡是每天拉下來的副本。
IBKR 的原始資料在雲垂分支 `claude/dazzling-curie-f3xzb8`，這裡是鏡像。

### 各來源能取什麼、怎麼改

**MT5：只有 CFD。**
- 目前只有 XAUUSD。EA 送的是它掛載那張圖表的商品，而 `main.py` 把收到的 M1 一律當 XAUUSD 處理。
- 要加別的 CFD 商品，要另寫一個只送數據的 EA，並在 `main.py` 加收件與封存。找預設分支（GCP 交易系統）改。
- 歷史：這裡從 R95 部署那天開始累積。更早的 XAUUSD M1 在外匯分支 `claude/forex-data-testing-w4q3m2`（session「外匯數據測試」）的 `data/XAUUSD_M1_*.csv.gz`（同一家券商的 MT5 匯出，2022-08 起）。
- 蛇蟠陣（session「恆指黃金突破K」，分支 `claude/gifted-carson-v2tvhw`）用黃金通道，可拿 MT5 M1 合成日高日低對照。

**Futu：改環境變數就能換商品，不用改程式。**
- 在跑 OpenD 的電腦設 `FUTU_SYMBOLS`，逗號分隔，例如 `US.QQQ,US.SPY,HK.800000`。每個代號都會各自封存。
- 目前帳戶的行情權限：港股股票／期權／期貨 LV1、美股股票 LV3、美股期權 LV1、加密貨幣 LV1。美國指數、CME、COMEX、A 股、新加坡、日本、馬來西亞都**沒有**權限。
- 額度：股票期貨訂閱 100 個、30 天內歷史 K 線 100 個代號；期權各 20 個。
- 期權只取最近到期日（跳過當天到期）、最接近現價的 5 個行使價。要改範圍就改腳本的 `ATM_STRIKES` 環境變數。
- 恒指即月期貨（腳本 v6 起）：`FUTU_SYMBOLS` 加 `HK.HSI_FRONT`（小型恒指 `HK.MHI_FRONT`、國企 `HK.HHI_FRONT` 同理）。腳本每天向 Futu 查合約清單，取最後交易日在今天之後最近的一張；**最後交易日當天（香港日期）就轉下月**。5 分 K 存在 `futu/HK.HSI_FRONT/K_5M/`，日 K 存在 `futu/_K_DAY/`（`code` = `HK.HSI_FRONT`），是一條不做價差調整的連續序列；轉月當天會有一個跳空（新舊合約價差）。實際合約記在 GCP 快照的 `source`，也可用最後交易日規則反推。網站沒有期貨數據，品質比對只做內部 OHLC 檢查。在 OpenD 電腦跑 `python push_to_gcp.py --futures HSI` 可看合約清單與今天的即月。

**IBKR：雲垂負責。**
- 程式在雲垂分支 `gcp_ib/`（VM 設定、每日採集）與 `scripts/ib_stock_verify.py`（股票覆核）。
- 加指數期權市場：在 `gcp_ib/ib_collector.py` 的 `MARKETS` 加一行。
- 要股票收市／開市覆核：照鳥翔分支 `stock_research/IBKR_DATA_REQUEST.md` 的格式向雲垂提需求。
- 已知限制：加拿大、日本沒有歷史數據權限；印度、韓國沒有合約；台灣只有上市，沒有上櫃。

## 二、怎麼取（任何分支都一樣）

```bash
git fetch origin claude/gcp-trading-v12-rewrite-bz75t2
mkdir -p /tmp/ext && git archive origin/claude/gcp-trading-v12-rewrite-bz75t2 data/external | tar -x -C /tmp/ext
cat /tmp/ext/data/external/STATUS.md
```

只要一個來源：`git archive … data/external/futu | tar -x -C /tmp/ext`。
不必合併預設分支，也不影響目前分支。

```python
import csv, glob, gzip
def load(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows

gold = load("/tmp/ext/data/external/mt5/XAUUSD/M1/*/*.csv.gz")
qqq = load("/tmp/ext/data/external/futu/US.QQQ/K_5M/*/*.csv.gz")
iv = load("/tmp/ext/data/external/futu/US.QQQ/options/*/*.csv.gz")
```

## 三、欄位與時區

| 檔案 | 欄位 | 日期與時間 |
|---|---|---|
| `mt5/…/M1` | `time_server, time_utc, open, high, low, close, time` | 檔名日期與 `time_server` 是**券商伺服器時間**（夏令 UTC+3、冬令 UTC+2）。`time_utc` 用 Cloud Run 的 `BROKER_UTC_OFFSET_HOURS`（目前 3）換算，冬令期間會差 1 小時。`time` 是伺服器時間的 epoch 秒 |
| `futu/…/K_5M` | `time_key, open, high, low, close, volume` | `time_key` 與檔名日期是**交易所當地時間**：美股為美東、港股為香港 |
| `futu/…/options` | `asof_utc, spot, code, option_type, expiry, strike, iv, delta, gamma, vega, theta, last, bid, ask, volume, open_interest, asof_ts` | 每次推送一列一檔合約。`iv` 是百分比（20 = 20%）。`spot` 是當時最新 5 分 K 收盤。檔名日期跟最新 K 線同一天 |
| `ibkr/iv_term_structure/ib_iv_log.csv` | `date, market, spot, wk_exp, wk_dte, wk_atm, wk_iv, mon_exp, mon_dte, mon_atm, mon_iv, slope` | 見雲垂分支 `tradingview/DATA_PIPELINE.md` 第七節 |
| `ibkr/stock_closes/<市場>_<訊號日>.csv` | `ticker, ib_symbol, exchange, currency, con_id, signal_date, ib_close, next_date, ib_next_open, ib_next_close, status, note` | 見雲垂分支 `scripts/ib_stock_verify.py` |

## 四、規矩

- **監測與研究用，永不直接用於下單。** 下單以券商當刻的即時報價為準。
- **只存行情。** 帳戶淨值、持倉、權杖都不會進這個資料夾（這個 repo 是公開的）。
- **要加來源或商品**，改上面各來源寫的位置，再到預設分支改 `scripts/external_data_sync.py` 的對應表。未對應的來源會在 `STATUS.md` 列為「未對應的來源」。
- **週末與假日沒有新 K 線是正常的。** 平日最新日期落後兩天以上才需要查：先看 `STATUS.md` 的錯誤，再看本地腳本、EA、VM 有沒有在跑。

## 五、一次性設定（使用者做）

1. Cloud Run 部署 R96 以上的 `main.py`（按日封存、`?view=archive` 端點；R96 起日線抽樣不蓋掉控制台快照）。
2. GitHub → Settings → Secrets and variables → Actions → 新增 `ZHUGE_GCP_URL`，值是 Cloud Run 服務網址。
3. 跑 OpenD 的電腦換上 v4 以上的 `futu/push_to_gcp.py`（每日日線抽樣），需要時設 `FUTU_SYMBOLS`。
   先部署第 1 步再換腳本，否則日線封包會暫時蓋掉控制台上的即時快照。
4. 到 Actions 手動執行一次 External data daily，確認 `STATUS.md` 三個來源都是 ✅，再看 `qc/QC_REPORT.md`。

## 六、數據品質比對與閘門（`qc/`）

每天同步完接著跑 `scripts/external_qc.py`，拿 Futu、IBKR 對照各分支從網站抓的數據。**取數據前先看 `qc/GATE.json`，只用 PASS 的類別。**

| 類別 | 比什麼 | 抽樣 |
|---|---|---|
| `futu_vs_web` | Futu 日線抽樣、Futu 5 分 K 合成日線 ↔ 網站日線（鳥翔所用的 `claude/gifted-carson-v2tvhw` 的 `data/equities`，Yahoo） | Futu 抓到的全部比 |
| `ibkr_vs_web` | IBKR 收市、次日開市、次日收市 ↔ 同上網站日線 | 每市場每天 20 檔，種子 = 執行日 |
| `web_vs_web` | Nasdaq.com 第二收市源 ↔ Yahoo（美股） | 最近 5 份快照，每份 30 檔 |
| `canary_inputs` | 金絲雀實際用的恒指、標普日線 ↔ 網站日線（**同源 Yahoo**，只驗抄錄與日期）；Futu 恒指、IBKR 指數 ↔ 金絲雀（獨立來源） | 最近 30 個交易日全比 |
| `internal` | 封存內部一致性：K 線高低關係、MT5 四價相同、期權清洗規則通過率（金絲雀手冊 §10，只記錄） | 全部 |

**判定規則（預先登記，不事後調整）**

| 標記 | 意思 | 會不會擋閘門 |
|---|---|---|
| ✅ 一致 | `|甲 − 乙| ≤ max(0.0005, 0.000001 × |乙|)`。吸收 Yahoo 的 float32 尾數，不吸收任何一跳價差 | 不會 |
| ℹ️ 記錄 | 口徑本來就不同的欄位：5 分 K 合成的開盤（首筆成交 ≠ 開盤競價）、成交量 | 不會 |
| ⏭️ 略過 | 對方沒有這一天（超出對方最新日期）、沒有這個代號、交易時段不完整（不完整只比收盤） | 不會 |
| ⚠️ 已知 | 命中 `qc/known_issues.csv` 登記的原因 | 不會 |
| ❌ 未解釋 | 其他一切差異，包括兩邊日期範圍重疊、卻只有一邊有某一天的**日期缺漏** | **會，該類 FAIL** |

類別閘門：有 ❌ → `FAIL`；有獨立來源的 ✅ → `PASS`；✅ 全部來自同源比對（例如兩邊都是 Yahoo）→ `SAME_SOURCE_ONLY`（🟡 僅同源：日期與抄錄沒錯，數值未經獨立驗證）；沒有任何 ✅ → `NO_DATA`。

- **日期錯位自動辨認**：不一致時，若甲的值等於乙的前一或後一交易日，說明欄直接寫出「日期錯位」和是哪一天。
- **第三來源投票**：兩邊不一致時，說明欄列出其他來源同一天同一欄的值；已知錯位的來源不投票。
- **爭議代號隔天重抓**：今天「數值不同」的代號會排進明天的 Futu 抽樣清單 `qc/futu_sample.txt`，讓 Futu 當第三票。
- **已知原因怎麼登記**：查明原因、而且數據**仍然可以用**，才把 `代號,日期,欄位,原因,登記人` 加進 `qc/known_issues.csv`（代號或日期可填 `*`）。
  數據本身就是錯的（例如日期錯位），不要登記，讓閘門維持 FAIL，直到來源修好。
- 輸出：`QC_REPORT.md`（給人看）、`GATE.json`（給程式看）、`results_latest.csv`（本次每一筆）、`history.csv`（每天每類一列）。
