# 趨勢模板全部等權——月底操作手冊（TT_ALL_MONTHLY_RUNBOOK.md）

分支：`claude/stock-research-k9nzau`。規格凍結於 TT_MOMENTUM_BACKTEST.md 第三部分；投資人說明見 TT_ALL_INVESTOR_BRIEF.md。
一句話：**月底收市後出名單 → 下一個交易日開市成交 → 一個月不動。**

## 時間表（以香港時間計）

| 時點 | 事 |
|---|---|
| 月底最後一個交易日（各市場自己的日曆） | 收市後數據才算完整；美股收市是香港翌日 04:00–05:00 |
| **月底翌日 08:00–09:00 HKT** | 更新 9 國數據（第 1 步）；等 Release 更新完（30–60 分鐘） |
| **09:00–09:30 HKT**（港股開市前） | 出名單、發布網頁、發 Telegram（第 2–5 步） |
| 各市場下一個交易日開市 | 下單（第 6 步）；港新台韓 09:00–09:30、日 08:00、澳 08:00、印 12:15、加美 21:30 HKT |

若某市場的月底比其他市場早（假期），該市場照它自己的最後交易日出名單；腳本會自動判斷（`is_month_end`）。

## 第 1 步：更新數據（GitHub Actions，要連 Yahoo，沙盒做不到）

這兩個 workflow 在預設分支上有登記，Claude session 可以直接用 GitHub API（`actions_run_trigger`，ref = `claude/gifted-carson-v2tvhw`）觸發，不必人手到 GitHub 按；`oos_fullmarket.yml` 有 concurrency，r1 與 r2 要先後觸發。

在 GitHub → Actions 手動觸發兩個 workflow（它們固定 checkout `claude/gifted-carson-v2tvhw`，不用改分支）：
1. `vcp_fullmarket.yml`：market = `all`、backtest = `false` → 港日美，上傳 Release `fullmarket-data`
2. `oos_fullmarket.yml`：market = `r1`（台韓澳）再一次 `r2`（加印新），或逐個市場 → 上傳 Release `oos-data`

完成後 Release 附件的日期會更新。沒做這步，名單會停在舊日期（腳本會因為「不是月底」拒絕出名單）。

## 第 2 步：拿數據、出名單（Claude session 或本機）

```bash
git fetch origin claude/stock-research-k9nzau && git checkout claude/stock-research-k9nzau && git pull --no-rebase
python3 scripts/get_market_data.py                              # 9 國約 1.2 GB
python3 scripts/tt_all_signal.py --market hk sg ca in au us jp tw kr    # 不加 --force：只在月底才出
python3 scripts/tt_all_page.py
```
- 產出：`analysis/tt_all/<市場>_<日期>.csv`（名單，按代號排序）、`<市場>_latest.json`、`tg_summary.txt`、`index.html`、`log.csv` 加一行
- 某市場印「不是當月最後一個交易日，不出名單」= 該市場數據未更新到月底 → 回第 1 步

## 第 3 步：檢查（兩分鐘）

- `analysis/tt_all/log.csv` 最後 9 行：日期是各市場的月底、`test` 欄是 0
- `tg_summary.txt`：每個市場一行，✅／⛔ 與「對 50/200 日線」的正負一致（✅ 必須兩個都正）
- 抽一檔看 CSV：收市價與券商報價同一數量級（防拆股／縫接）

## 第 3b 步：第二來源覆核（GitHub Actions，push 觸發）

```bash
printf "hk 2026-09-30\nsg 2026-09-30\nca 2026-09-30\nin 2026-09-30\nau 2026-09-30\nus 2026-09-30\njp 2026-09-30\n" > analysis/tt_all/verify_request.txt   # 日期 = 各市場的訊號日（<市場>_latest.json）
git add analysis/tt_all && git commit -m "chore(tt-all): 覆核請求" && git push origin claude/stock-research-k9nzau
```
- `tt_all_verify.yml` 會跑：港 → 港交所日報表；美 → Nasdaq 歷史 API（每檔 0.3 秒，200 檔約 8 分鐘）；台 → 證交所（上市股）；日 → Yahoo!ファイナンス；
  韓澳加印新與取不到的 → Yahoo 即時重抓（同來源，只驗快照沒過期、股票還在交易）
- 完成後自動 commit `<市場>_<日期>_verify.csv`、`<市場>_verify.json`、重建 `index.html`（加「覆核」欄），並發一則 Telegram：「✅ 港股 45/45 一致（港交所日報表）」
- **有「不一致」或「無數據」的股票：下單前先查**（停牌、下市、代號改了、拆股）；不一致 > 5% 的市場先不要下單
- 之後 `git pull --no-rebase` 把 Actions 的 commit 拉回來再做第 4 步

## 第 3c 步：IBKR 第三來源覆核（雲垂分支代抓，選做但建議）

月底名單出來後 `analysis/tt_all/ibkr_request.csv` 已自動更新（第 2 步 `tt_all_signal.py` 產生）。到雲垂 session 貼 `stock_research/IBKR_DATA_REQUEST.md` 第 2 節的指令（probe → closes → commit 到雲垂分支），約 30 分鐘交貨；然後在本分支：

```bash
git fetch origin claude/dazzling-curie-f3xzb8
git checkout origin/claude/dazzling-curie-f3xzb8 -- data_stock_ibkr
python3 scripts/tt_all_verify.py --ibkr      # 寫 <市場>_<日期>_verify_ibkr.csv、<市場>_verify_ibkr.json、tg_verify_ibkr.txt
python3 scripts/tt_all_page.py               # 網頁多一欄「IB」與「IBKR 覆核」統計
```

- 能比的市場：美、澳、港、新、台主板（IB 無台灣上櫃；加、日帳戶無歷史數據權限；印、韓無合約）。
- IB 的「下一交易日開市價」存在 `_verify_ibkr.csv` 的 `ibkr_next_open`，是執行基準：第 7 步記錄成交後，滑價 = 成交價 ÷ 開市價 − 1。
- 把 `tg_verify_ibkr.txt` 內容寫進 `.github/tg_outbox_research.txt` 並 push 就發到 Telegram。

## 第 4 步：發布網頁

在 Claude session 說「重新發布月底名單網頁」：把 `analysis/tt_all/index.html` 重新發布到**同一個**連結 https://claude.ai/artifact/MidE38TQkYwN6pjoHFn9sP （路徑不變即更新，連結不變）。

## 第 5 步：發 Telegram 摘要

```bash
cp analysis/tt_all/tg_summary.txt .github/tg_outbox_research.txt
git add analysis/tt_all .github/tg_outbox_research.txt
git commit -m "chore(tt-all): 月底名單 YYYY-MM-DD"
git push origin claude/stock-research-k9nzau        # push 即觸發 send-telegram-research，約 20 秒送達
```

## 第 6 步：下單（下一個交易日開市）

只做「試行」等級的市場（港、新、加、印、澳）；日美觀察；台韓不做。每個市場：
1. 看該市場的 ✅／⛔：**⛔ = 這個市場本月全部賣出、持現金**，名單只作記錄
2. ✅ 且名單 ≤ 40 檔：全部等權；> 40 檔：只買網頁上 ★ 標記的 40 檔（隨機種子 = 年月，可重現）
3. 對照上月持倉：**留任的不動**（省成本），賣出不在新名單的，買入新進的
4. 每檔金額 = 該市場衛星倉資金 ÷ 檔數；下**開市市價單**（回測假設 = 開市價），不追價、不分批
5. 衛星倉總額 ≤ 總資產 10%，核心 ETF 不動
6. 當月內：什麼都不做。跌破均線、跌 20%、大市轉弱都不動，下月底才重選

## 第 7 步：記錄成交（假設檢驗，不是走流程）

`analysis/tt_all/executions.csv`（自己填），欄位：`date,market,ticker,side,qty,fill_price,open_price,slippage_pct,note`
- `slippage_pct` = (成交價 − 當日開市價) ÷ 開市價，買入為正代表比回測假設差
- 每月看：平均滑價 > 0.5% → 執行方式要改（例如改用開市前掛單）

## 第 8 步：每月覆核（下月底出新名單時一起做）

- 記錄各市場本月實際報酬、同期 ETF 報酬、等權宇宙報酬（後者由腳本補）
- **證偽（寫死，不改）**：前向 12 個月相對當地 ETF 跑輸 15 個百分點，或相對全市場等權為負 → 停止該市場
- 前 12 個月不因為單月結果好壞改任何規則

## 最省事的做法

9 月底已排定：session 會在 2026-10-01 08:30 HKT 自動醒來做第 1 步、10:00 HKT 做第 2–5 步（`send_later`）。之後每月：月底翌日早上開 Claude session 說：
「**跑月底名單：拿數據、出 9 國名單、覆核、發布網頁、發 Telegram**」——第 2 到 5 步一次做完（覆核要等 Actions 約 10 分鐘），你只需做第 6、7 步。

## 常見問題
- **某市場沒出名單**：數據未更新到月底（第 1 步沒跑或 Yahoo 抓失敗），看 Actions 記錄
- **美股名單 0 檔**：個股數據比 ETF 舊一天以上，腳本已改為取覆蓋 ≥ 50% 的最後一天；若仍 0 檔，重跑第 1 步
- **名單裡有仙股／異常高報酬**：規格沒有價格門檻，忠實呈現；要加過濾屬規格變更，須另開登記
- **工作流程能不能自動排程**：本分支的 `tt_all_signal.yml` 只能在預設分支上排程；要自動化需在預設分支放薄殼 workflow，由使用者決定
