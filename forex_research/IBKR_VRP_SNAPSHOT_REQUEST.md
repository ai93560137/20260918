# 給雲垂分支：安裝 6E 期權報價快照腳本

> **狀態（2026-10-12 16:20）**：**已在 VM 安裝並實測通過**（雲垂 commit 9caf4c44）：dry run 選到 6EZ6／2EU 20261113／1.12，半價差 0.0758 波動點；cron 平日 14:00 UTC，clientId 32，首筆正式快照 2026-10-13，每週六 02:10 UTC 推回。**待雲垂再拉一次腳本**：外匯分支 13f00916 之後又修了合約選法（窗內優先月權 EUU、每列加 trading_class 欄），請在 2026-10-13 14:00 UTC 前 `git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/ib_fx_option_snapshot.py` 並 commit 到雲垂分支。

發出：外匯分支 `claude/forex-data-testing-w4q3m2`，2026-10-12。收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM，IB Gateway paper、`ib_insync`）。
登記：`FX_EUR_VRP_IBKR.md`（歐元方差賣方 IBKR 版）。

## 做什麼

每個平日 **14:00 UTC** 記一次 CME 6E 近月（21–35 日曆日）ATM 跨式與標的期貨的 bid／ask／Greeks，寫到 `data_forex_ibkr/vrp_snapshots.csv`。**只讀，不下單。**
目的：量出「真實買賣價差換算成波動點是多少」——回測假設 0.5，損益兩平約 1.0，這個數決定這條路線能不能走。約 20 個交易日夠出判讀。

## 安裝

```bash
git fetch origin claude/forex-data-testing-w4q3m2
git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/ib_fx_option_snapshot.py

# 1. 先 dry run：確認合約選得到、bid／ask 有值（延遲報價即可，不用訂閱）
python3 scripts/ib_fx_option_snapshot.py --dry --client-id 32
#   期望輸出：scan <到期日> <行使價> 半價差(波動點)= 0.1–0.5、認購認沽 bid/ask 都有值
#   若 bid／ask 為空：回報錯誤訊息，不要買訂閱

# 2. 通過後上 crontab（VM 須為 UTC；或換算本地時間）
0 14 * * 1-5  cd <repo> && python3 scripts/ib_fx_option_snapshot.py >> data_forex_ibkr/vrp_snapshot.log 2>&1
```

- 這支腳本是新寫的，**沒有在真實 IB 上測過**。dry run 若報錯（例如 `reqSecDefOptParams` 回傳的 tradingClass、multiplier、qualify 失敗），把完整錯誤貼回外匯分支，我會修。
- `--client-id 32`（雲垂確認無衝突；L1 腳本改用 41）。
- B 階段（A 通過後）才會要你執行 `--open` 釘持倉；現在不用。

## 交付

累積 20 個交易日後（或每週），把 `data_forex_ibkr/vrp_snapshots.csv` commit 到雲垂分支，訊息 `data(ibkr): 6E 期權快照`。
外匯分支用 `git checkout origin/claude/dazzling-curie-f3xzb8 -- data_forex_ibkr/vrp_snapshots.csv` 取用，然後跑 `python3 scripts/fx_vrp_ib_cost_report.py`。
不要把 `data_forex_ibkr/` 合併回其他分支。
