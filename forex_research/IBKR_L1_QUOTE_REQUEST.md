# 給雲垂分支：安裝 L1 前向測試的 IBKR 報價腳本

> **狀態（2026-10-12）**：雲垂已回覆（其分支 `data_forex_ibkr/_l1_vrp_install_status.txt`）：沙盒碰不到 VM，**實測要由使用者在 VM 貼該檔第 4 節的指令**；clientId 改 41；每週六 02:10 UTC 由 `gcp_ib/push_fx_quotes.sh` 推回 CSV。

發出：外匯分支 `claude/forex-data-testing-w4q3m2`，2026-10-12。收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM，IB Gateway paper、`ib_insync`）。

## 做什麼

EURUSD 倫敦上午前向測試（`FX_L1_FORWARD.md`）每天 09:00 UTC 賣、12:00 UTC 買回，紙上成交價來自 Dukascopy。
請在 VM 上每個平日 **08:59、11:59 UTC** 各記一次 IBKR EURUSD（IDEALPRO）即時 bid／ask，作為點差的第二來源。**只讀，不下單。**

## 安裝（約 5 分鐘）

```bash
# 1. 只取一個檔（不要合併分支）
git fetch origin claude/forex-data-testing-w4q3m2
git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/ib_l1_quote.py

# 2. 連線測試（延遲報價，確認 Gateway 通；此行會寫入 label=test_delayed）
python3 scripts/ib_l1_quote.py --label test --delayed --client-id 41

# 3. 即時報價測試（外匯 IDEALPRO 通常免訂閱；若 bid／ask 為空代表沒即時權限，請回報，不要改用延遲）
python3 scripts/ib_l1_quote.py --label test --client-id 41

# 4. crontab（VM 時區須為 UTC；或改成對應本地時間）
59 8  * * 1-5  cd <repo> && python3 scripts/ib_l1_quote.py --label 0859 --client-id 41 >> data_forex_ibkr/l1_quote.log 2>&1
59 11 * * 1-5  cd <repo> && python3 scripts/ib_l1_quote.py --label 1159 --client-id 41 >> data_forex_ibkr/l1_quote.log 2>&1
```

注意：
- `--client-id 41` 避開你們既有程序的 clientId；若衝突請換號。
- 腳本等 5 秒取樣，所以實際時間約 08:59:05／11:59:05，csv 的 `utc_time` 已記真實時間。
- 把測試列（label 含 `test`）從 `l1_quotes.csv` 刪掉再開 cron，或保留亦可（外匯分支會過濾）。

## 交付

每週或每月把 `data_forex_ibkr/l1_quotes.csv`（欄位 `utc_time,label,bid,ask,spread_bp`）commit 到雲垂分支，訊息 `data(ibkr): L1 報價快照`。
外匯分支用 `git checkout origin/claude/dazzling-curie-f3xzb8 -- data_forex_ibkr/l1_quotes.csv` 取用。不要把 `data_forex_ibkr/` 合併回其他分支。

## 外匯分支會怎麼用

與同日 `forward/l1_paper.csv` 的 09:00／12:00 點差對照（Dukascopy 實測 09:00 約 0.34 基點、12:00 約 0.21 基點；IBKR 點差若系統性大於 0.5 基點，成本假設要上調並另行登記）。不用來改變 L1 的訊號或對窗。
