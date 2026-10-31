# 🐯 虎翼——每日大跌股賣期權（候選＋紙上紀錄）

規格：`scripts/huyi_scan.py` 檔頭；研究判決：`stock_research/BIGDROP_OPTIONS_PREREG.md` 第 9 部分；交接：`handoff/虎翼.md`。

| 時間（香港） | 市場 | 觸發 |
|---|---|---|
| 週二至六 06:17 | 美股（前一晚收市） | 虎翼工作階段每日排程 → 追加 `us` 到 `run_request.txt` 並 push |
| 週一至五 19:41 | 港股（當日收市，港交所股票期權日報） | 同上，追加 `hk` |

網頁：總指揮 tnt-hk.com/?view=huyi（`scripts/huyi_push.py`，每次掃描後推）。

輸出：`latest_<us|hk>.md` 當日候選表、`<us|hk>/<日期>.csv` 明細、`paper_log.csv` 紙上紀錄（到期自動結算）、`scan_log.csv` 每次掃描一行。

**模式**：`mode.json`——2026-10-31 使用者「先做前向測試」，美港都係 `paper`；🧪＝符合實倉規則（`LIVE_RULES.md`）嘅紙上筆，成功標準見 `FORWARD_TEST.md`。轉實倉要使用者再親口批。
