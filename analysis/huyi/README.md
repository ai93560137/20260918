# 🐯 虎翼——每日大跌股賣期權（候選＋紙上紀錄）

規格：`scripts/huyi_scan.py` 檔頭；研究判決：`stock_research/BIGDROP_OPTIONS_PREREG.md` 第 9 部分；交接：`handoff/虎翼.md`。

| 時間（香港） | 市場 | 觸發 |
|---|---|---|
| 週二至六 06:17 | 美股（前一晚收市） | 虎翼工作階段每日排程 → 追加 `us` 到 `run_request.txt` 並 push |
| 週一至五 19:41 | 港股（當日收市，港交所股票期權日報） | 同上，追加 `hk` |

網頁：總指揮 tnt-hk.com/?view=huyi（`scripts/huyi_push.py`，每次掃描後推）。

輸出：`latest_<us|hk>.md` 當日候選表、`<us|hk>/<日期>.csv` 明細、`paper_log.csv` 紙上紀錄（到期自動結算）、`scan_log.csv` 每次掃描一行。

**實倉規則未定：以下全部係紙上紀錄，唔係落單指令。** repo 公開：只寫價格、張數、百分比，唔寫金額。
