# 給雲垂分支的 IBKR 新聞數據需求（research/news_trade/IBKR_NEWS_REQUEST.md）

發出：數據分支 `claude/pelosi-stock-tracking-f9f94g`，2026-09-25。
收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM 上有 IB Gateway paper 帳戶、IBC 常駐、`ib_insync`，見該分支 `gcp_ib/`）。

## 0. 為甚麼要這些數據（一段話）

News trade 目前的事件時間全部來自監管申報：SEC 8-K、港交所披露易、公開資訊觀測站。
申報時間常比新聞稿晚：美股 8-K 有 16% 落在盤中，多半是盤前已經發了新聞稿，白天才補交 8-K。
IBKR 的新聞 API 有逐則標題與**精確到秒的發佈時間**，可以：
1. **校正事件時間**：用第一則新聞的時間取代 8-K 申報時間，檢查 PEAD、回購的進場日有沒有晚一天；
2. **做新題目**：分析師評等變動（Briefing.com 的 Upgrades/Downgrades）、新聞密度與情緒。
   這些都需要有時間戳的標題，是我們目前完全沒有的數據。

先 probe，看 paper 帳戶有哪些免費新聞源、歷史能回溯多深，再決定值不值得做。

## 1. 清單（按優先級；P0 先跑，P1 有空才跑）

| 優先 | 內容 | API | 範圍 | 輸出（`data_news_ibkr/`） | 用途 |
|---|---|---|---|---|---|
| **P0** | 探測：有哪些新聞源；美、港、日、台各一檔能不能拿到標題與全文；最早能回溯到哪 | `reqNewsProviders`、`reqHistoricalNews`、`reqNewsArticle` | AAPL、SPY、700.HK、7203.T、2330.TW | `_status.txt`、`_providers.csv` | 決定要不要做 |
| **P0** | 歷史新聞標題 | `reqHistoricalNews`（每次最多 300 則，從現在往前接著抓） | S&P 500 現任 503 檔，**能拉多深拉多深** | `headlines/US_<代號>.csv.gz`：`time,provider,article_id,headline` | 事件時間校正、評等變動 |
| P1 | 抽樣全文 | `reqNewsArticle` | 從已抓標題固定種子抽 2,000 篇 | `articles/<provider>/<article_id>.txt.gz` | 判斷標題夠不夠用、情緒標記的意義 |
| P2（等 probe 結果） | 前向即時新聞 | `reqMktData` generic tick 292 | 每日採集 | 另議 | 歷史不夠深時才需要，現在**不要**改 `gcp_ib/ib_collector.py` |

- IBKR 對所有 API 用戶免費開放的新聞源通常有：`BRFG`（Briefing.com General Market Columns）、
  `BRFUPDN`（Briefing.com Analyst Actions）、`DJNL`（Dow Jones Newsletters）。實際以 probe 的 `_providers.csv` 為準。
- 部分新聞源的標題前面會帶 `{A:...:L:en:K:0.97:C:...}` 這類標記（`K` 可能是情緒分數），腳本原樣保留，不做解析。

## 2. 怎樣跑（腳本已寫好在本分支）

```bash
# 在 VM 上，先把本分支的腳本和成分股名單拿過來（不要合併分支，只取檔案）
cd <repo>
git fetch origin claude/pelosi-stock-tracking-f9f94g
git checkout origin/claude/pelosi-stock-tracking-f9f94g -- scripts/ib_news_history.py data/news/sp500_cik_map.csv
mkdir -p data_news_ibkr

# 第一步一定先 probe：列新聞源、每個源試一次、試 1／3／5／10 年前、試一篇全文
python3 scripts/ib_news_history.py --port 4002 --job probe
cat data_news_ibkr/_status.txt data_news_ibkr/_providers.csv

# P0：503 檔標題（每個請求隔 2 秒；深度未知，先用 --symbols 抽 5 檔試跑估時間）
python3 scripts/ib_news_history.py --port 4002 --job headlines --symbols AAPL MSFT JPM XOM KO > data_news_ibkr/headlines_try.log 2>&1
nohup python3 scripts/ib_news_history.py --port 4002 --job headlines > data_news_ibkr/headlines.log 2>&1 &

# P1：抽樣全文
nohup python3 scripts/ib_news_history.py --port 4002 --job articles --max-articles 2000 > data_news_ibkr/articles.log 2>&1 &
```

- clientId 用 29（每日採集用 17、外匯腳本用 23），**不要和外匯的 job 同時跑**，順序排隊。
- 腳本可續抓：中斷後重跑，每檔會從已有檔的最早一則往前補。
- 連續 3 次沒有新標題就換下一檔（代表該新聞源的歷史到底了，這本身就是我要的資訊）。
- 只讀：不下單、不改帳戶；帳密只在 IBC 的 config.ini，不進 repo、不進對話。

## 3. 交付

1. 把 `data_news_ibkr/` 整個資料夾（含 `_status.txt`、`_providers.csv` 與各 `.log`）**commit 到雲垂分支**，
   commit 訊息 `data(ibkr): 新聞標題歷史`。單檔 < 25 MB 直接進 git；超過的改上傳 Release `news-data`，並在 `_status.txt` 寫明。
2. 數據分支會 `git checkout origin/claude/dazzling-curie-f3xzb8 -- data_news_ibkr` 取用。
3. **若 probe 就被擋**（`_providers.csv` 是空的，或每個源都回錯誤 10276「News feed is not allowed」）：
   **不要**去買任何新聞訂閱，先把 `_status.txt` 交回，我們再決定。

## 4. 數據分支收到後會做的檢查

- 每個新聞源的起迄、每檔每年則數、缺月；
- **時間戳時區**：拿已知事件核對，例如 Apple 財報新聞稿是美東 16:30（UTC 20:30 或 21:30），確認 `time` 是 UTC 還是 VM 本地時間；
- 與 `data/news/sp500_earnings_events.csv.gz` 對照：每個 8-K 2.02 事件前後 2 天內第一則新聞的時間，統計 8-K 晚了多少；
- 標題是否夠用、分析師評等能否從標題解析（Upgrade／Downgrade、目標價）。
通過後才寫新題目的預先登記；歷史不到 5 年就只做前向記錄，不做判決。

## 5. 不要做的事

- 不要用這些數據跑任何回測：登記與跑數都在數據分支，而且只跑一次。
- 不要訂閱任何付費新聞源。
- 不要改 `gcp_ib/ib_collector.py` 的既有市場。
- 不要把 `data_news_ibkr/` 合併回其他分支。
