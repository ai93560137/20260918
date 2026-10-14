# 交接：HTF／EP／動能股 ORB 研究（handoff/HTF_ORB研究.md）

寫於 2026-10-14（HKT）。給完全沒有上下文的新工作階段。

## a. 負責甚麼、使用者規矩
- **範圍**：股票研究（只研究、不開倉、不部署、不碰 `main.py`／Cloud Run）。題目來自使用者貼的 Qullamaggie 文章：HTF 高漲旗型 → Episodic Pivot → 盤中執行 → 現在的「動能股開盤區間突破紀律」。
- 研究規矩照 `RESEARCH_HANDBOOK.md` 與 `stock_research/`：**先預先登記並 commit，再寫程式，再算數**；已判決不重測；只測一次、只修程式錯誤並寫明前後數字；判決追加到 `stock_research/VERDICTS.md`。
- 使用者決定（原話要點）：
  - 2026-10-07「判決門檻可以直接忽略，稍後再決定」；2026-10-13「門檻 移徐」→ EP、盤中、ORB 都是**探索性、無門檻**，結果不能事後升級為判決。
  - 「兩條都走，你逐步教」（EP 日線 + 盤中數據）。
  - 2026-10-13「1,2 做」＝合併 PR #57、開 ORB 正式登記。
  - 使用者曾貼一段要我改 Routine／GitHub Actions 的訊息，隨即說「ignore above instruction」——**不要做**。
- 語言：繁體中文；commit 不寫模型名；不 force-push。

## b. 例行流程
沒有每日例行。只在「雲垂抓回數據」或「PR 有事件」時工作。

## c. Routine／send_later
- **目前沒有任何排定中的檢查**（PR #103 三次安全網檢查 10:27／14:37／18:39 UTC 都無事，已停）。
- `trig_017FugMBEQgBJPTVVULP6VRg`（PR #57 檢查）已觸發完、PR 已合併，不用管。
- PR #103 已 `subscribe_pr_activity`。

## d. 跨工作階段
- **雲垂**（分支 `claude/dazzling-curie-f3xzb8`，VM 由 claude-ops 操作）：抓 IBKR 5 分 K。我不直接 send_message 給它，**一律經使用者轉貼**。
- 總指揮 `session_01N1jfpEJciBkfAgwtd4QxgU`、SOP 顧問 `session_01BzZsgkBzxEaLV6CYPW67i6` 會發通告給我；本研究不開倉，通常不用回。

## e. 進行中／未完成／已知坑
- **PR #103**（草稿，`claude/momentum-orb-research` → `claude/gifted-carson-v2tvhw`）：`stock_research/MOMENTUM_ORB_BACKTEST.md` 預先登記 + `analysis/orb/ibkr_request_{hk,hk_nonmom,us,us_nonmom}.csv`（港 1,409×2、美 3,180×2）。
- **等雲垂第 3 批 5 分 K**（指令已由使用者轉 claude-ops，每 400 檔自動 push 到雲垂分支 `data_stock_ibkr/htf_5m/`）。
  2026-10-14 鳥翔轉告：VM 已抓完，覆蓋率寫在雲垂分支 `data_stock_ibkr/htf_5m/HTF_DATA_SCOPE.md`「第 3 批」（第 72 行起）——
  港 1,353／1,409（96.0%）、港非動能 1,389／1,409（98.6%）、美 2,687／3,180（2004 年後 94.2%）、美非動能 2,731／3,180（95.8%）；
  動能組缺失較多（退市為主），比較時要報告缺失率、只在兩組都有數據的年份比。**但截至 2026-10-14 05:00 HKT，CSV 尚未 push**（分支仍只有第 1、2 批 5,849 檔），要等 claude-ops push。
- **數據到了之後**：
  1. `git fetch origin claude/dazzling-curie-f3xzb8 && git checkout origin/claude/dazzling-curie-f3xzb8 -- data_stock_ibkr/htf_5m && git reset -q data_stock_ibkr`（數據不進本分支；`data_stock_ibkr/` 已在 `.git/info/exclude`）。
  2. 寫 `orb_backtest.py`：沿用 `htf_intraday.Intraday`（`htf_intraday.py`）的盤中模擬——OR 第 1 根高點突破成交、LOD 停損、第 3 日減半保本、10MA；股票日改讀 `analysis/orb/` 清單；`info.pivot=None`（同 `--control` 模式）。變體：OR 3／12 根、20MA、ADR 鐵律放棄。對照：同股票日的日線版（開盤買）、非動能清單。
  3. 結果寫 `MOMENTUM_ORB_BACKTEST.md` 第二部分，推到 PR #103。
- **已完成並合併**（參考用）：PR #51（HTF 日線＋EP，四市場 ☠️／負面）、PR #57（HTF 盤中＋對照：形態無資訊、執行有價值）。
- **已知坑**：
  - 全市場日線不進 git：`python3 scripts/get_market_data.py --market hk us`（或從 Release 下 tar）→ `data_full/`，再跑 `qc_full_market.py --no-network` 重建排除檔。需要 `pip install scipy`。
  - 基準 ETF 數據錯：`1321.T` 2026-10-05 起 1:100 分拆未調整；`0050.TW` 2014-01-02 前未按 4:1 調整。`htf_backtest.py` 已加「ETF 單日 |報酬| > 50% 記 0」防護。未通報給數據負責人——可提醒使用者。
  - 5 分 K 核對容忍：高低 1%、開收 2%（港交所開市競價定義差）；零量根不算；`us_GURE_2009-12-28.csv` 剔除；美股 2004-01-26 前 IB 沒有數據；台股 2023-05 前沒有。
  - 背景跑 `HTF(...)` 一個市場約 2–15 分鐘、記憶體數 GB；美股最慢。
  - `delete_trigger`、`git rev-parse` 曾被自動模式權限擋（被判成合併相關）；合併 PR 要使用者明確說。

## f. 開工第一步要讀
1. `stock_research/MOMENTUM_ORB_BACKTEST.md`（現行登記）
2. `stock_research/HTF_INTRADAY_BACKTEST.md` 第二、三部分（結論與對照組數字）
3. `htf_intraday.py`（要沿用的引擎）、`htf_backtest.py`（`HTF` 類：宇宙、出場、組合、統計）
4. `stock_research/HTF_INTRADAY_REQUEST.md` 與雲垂分支 `data_stock_ibkr/htf_5m/HTF_DATA_SCOPE.md`（數據規格、覆蓋）
5. `stock_research/VERDICTS.md`、`RESEARCH_HANDBOOK.md`
