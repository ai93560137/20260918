# 每日全市場數據管線＋Minervini 每日訊號＋紙上前向（stock_research/FULLMARKET_DAILY_PIPELINE.md）

**狀態：設計登記（2026-11-06）**。使用者 2026-11-06 在總指揮工作階段親口批准：①建每日全市場數據管線；②長期每月排程跑紙上前向記錄。
經總指揮轉達（session_01Mt8CWjUZpGvDAD6UBLEAti）。**實倉、Telegram 照舊暫停**；預設分支改動經 PR，使用者說「合併」才生效。

## 一、為甚麼要

SATELLITE_MARKETS.md 第四節：9 國都沒有每日全市場數據，所以 Minervini（規格用全市場成交額前 N）既不能每日出訊號，也沒有市場合乎實倉條件。
現時全市場數據只在月底由 `vcp_fullmarket.yml`／`oos_fullmarket.yml` refresh 一次。

## 二、設計

| 項目 | 做法 |
|---|---|
| 數據源 | Yahoo（yfinance），沿用 `scripts/fetch_full_market.py --refresh-all`（每批 100 檔、`auto_adjust=False`、收市＋30 分鐘才保留當日）：**每日整段重抓**，不做「只補最近幾日」，避免拆股／除息後還原比例接不上 |
| 宇宙 | 候選池 `universes/full/<m>_pool.txt` 不變（約 2.3 萬檔）；每日不重建候選池（沿用月底流程） |
| 品質 | 每日：`qc_full_market.py --no-network`（結構檢查、重建排除檔）。第二來源核對仍按月（現有流程） |
| 存放 | 日線不進 git：覆寫 Release `fullmarket-data`（港日美）／`oos-data`（其餘 6 國）的 `<m>.tar`（`--clobber`），另存 Actions 快取 |
| 每日產出（commit 到本分支） | `analysis/minervini/<收市日>_<m>.csv`：明日觀察名單（形態已成、收市未過樞紐點、趨勢模板＋大市過濾成立；樞紐點、買入上限 ×1.05、止損 ×0.925）；`research/forward/ledger_<m>.csv`（紙上前向帳本，前向起點 2026-11-06）＋`research/forward/README.md` |
| 每月產出 | `research/forward/<年月>.md`：月度快照（每市場筆數、已平倉／未平倉、平均淨報酬；描述性） |
| 工作流程 | 預設分支新增 `.github/workflows/fullmarket_daily.yml`（`workflow_dispatch`，checkout 本分支跑程式，同其他股票工作流程）；`group` 輸入：`asia`（港日台韓澳印新）、`americas`（美加）、`monthly`（只出月度快照，不抓數） |
| 排程 | 用 Cloud Scheduler（GitHub cron 實測遲 3–4 小時）。三個工作，規格見第四節，由總指揮加入 `ops/scheduler_jobs.json` |
| Telegram | 不發（10-13 起暫停；工作流程內不加任何 Telegram 步驟） |

## 三、預計用量

- 9 國候選池共約 2.3 萬檔、每日約 230 批下載。按月底 refresh 的經驗，每批約 15–40 秒，整體約 **1.5–3 小時 runner 時間／日**；用 matrix 每市場一個 job 並行，每組牆鐘約 30–60 分鐘。
- 倉庫公開 → GitHub Actions 標準 runner 分鐘不收費；Release 每日覆寫約 1.2 GB（不累積版本）。
- 風險：Yahoo 限流（429）。對策：每市場 `--budget-min 50`、批次重試；某市場當日沒抓齊（`fetch_full_market.py` 回傳 3）→ 該市場當日不出訊號、不更新前向帳本，名單檔註明「數據未齊」，下一日補。

## 四、Cloud Scheduler 工作規格（交總指揮）

| name | time_zone | schedule | workflow | inputs |
|---|---|---|---|---|
| `stock-fullmarket-asia` | Asia/Hong_Kong | `20 19 * * 1-5` | `fullmarket_daily.yml` | `{"group": "asia"}` |
| `stock-fullmarket-americas` | America/New_York | `40 18 * * 1-5` | `fullmarket_daily.yml` | `{"group": "americas"}` |
| `stock-forward-monthly` | Asia/Hong_Kong | `25 11 1 * *` | `fullmarket_daily.yml` | `{"group": "monthly"}` |

（亞洲最遲收市是印度 15:30 IST＝18:00 HKT；美加 16:00 ET 收市，用紐約時區免受夏令時影響；每月 1 日中午出上月快照。）

## 五、驗收

1. PR 合併前：在本分支用一次性測試工作流程只跑新加坡（最小市場），確認抓數、QC、Release 上載、名單與帳本 commit 都正常；測完刪除測試工作流程。
2. 合併後第一個交易日：檢查三組各一次的運行時間、成功市場數；寫回本文件第六節。
3. 每日報告（`daily_topdown.py`）照舊；`analysis/minervini/` 是新增的全市場名單，兩者並存。

## 六、運行紀錄

- **2026-11-06 合併前測試**（本分支一次性工作流程，只跑新加坡，run 42162578211，測完已刪除）：還原 Release → 整段重抓約 1.5 分鐘 → QC → 覆寫 `oos-data/sg.tar` → 名單（2026-11-05 收市 0 檔）＋帳本（數據到 2026-11-05、前向 0 筆）→ commit → 摘要 commit，全部步驟成功。正式工作流程待預設分支 PR 合併。
