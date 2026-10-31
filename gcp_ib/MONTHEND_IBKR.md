# 鳥翔月底名單 IBKR 核對——ib-data 自動排程（gcp_ib/run_monthend_closes.sh）

寫於 2026-10-31，鳥翔工作階段。使用者 10-31 經總指揮決定：喺 ib-data 加排程，等月底核對自動跑，唔使每月人手貼指令。

## 做乜

每月月底，鳥翔產生 Trend Template 名單，同時寫一個請求檔：`claude/stock-research-k9nzau` 分支嘅 `analysis/tt_all/ibkr_request.csv`。
ib-data 喺每月 1–8 號每日 UTC 22:05 跑 `run_monthend_closes.sh`：

1. 從公開 repo 下載請求檔，攞最新訊號日 D（只係 CSV 數據，唔執行別嘅分支嘅程式）
2. 檢查邊啲市場未齊（預設 `hk sg au us`；澳洲另跑 `--no-rth` 對照收市競價，檔名後綴 `_nortrh`）。
   一個市場要每一檔都有 ok 結果兼有下一交易日，或者係 `no_contract`／`no_data`，先算齊
3. 齊晒就即刻結束（每次幾秒）；未齊就 probe → no-rth → 正式抓
4. 掃描 password／token／secret／api key 關鍵字，冇命中先 commit 同 push 去**專用資料分支 `data/stock-ibkr`**。
   資料 repo 係 `~/stock-ibkr-data`，同程式分支分開
5. 全程寫日誌去 `/srv/ibshare/monthend.log`，claude-ops 可以用 `ssh ibdata 'tail -30 /srv/ibshare/monthend.log'` 唯讀睇

抓取程式係固定複本 `gcp_ib/ib_stock_monthend.py`，來源係鳥翔分支嘅 `scripts/ib_stock_verify.py`。同原版唔同嘅地方：
- 用 readonly 連線，clientId 61（唔同 17/23/24/31/32/41/43/45/55/77 撞）
- 支援 `--req`／`--out`／`--suffix` 參數
- 已經 ok 但未有下一交易日嘅列會重抓，所以月底後太早跑都安全
- 連唔到 Gateway 就用代碼 3 結束，並寫明原因

## 結束代碼

| 代碼 | 意思 | 點處理 |
|---|---|---|
| 0 | 完成／無事可做 | — |
| 3 | 連唔到 IB Gateway（多半卡喺免責聲明） | 跟 AGENTIC.md「IB Gateway 重啟後卡在免責聲明」用 VNC 按接受；下一日排程會自動補，或者人手重跑 |
| 4 | 關鍵字掃描命中 | 唔會推送；人手睇 `~/stock-ibkr-data/data_stock_ibkr` |
| 1 | 其他（下載請求檔失敗、推送失敗等） | 睇日誌；下一日排程會重試 |

## 使用者喺 ib-data 要貼嘅步驟（PR 合併後）

貼之前先睇提示符，要係 **`hengkychansinghing@ib-data`**，唔係 `@claude-ops`。

```bash
# @ib-data：1. 更新程式
cd ~/20260918 && git pull --rebase --autostash -q origin claude/dazzling-curie-f3xzb8
ls -l gcp_ib/run_monthend_closes.sh gcp_ib/ib_stock_monthend.py
```

```bash
# @ib-data：2. 試跑（只 probe，寫去暫存資料夾；唔提交、唔推送）
bash ~/20260918/gcp_ib/run_monthend_closes.sh --dry
tail -25 /srv/ibshare/monthend.log
```

試跑最尾應該見到「--dry 完成：正式執行會抓 [...]」。如果見到「❌ 連不到 IB Gateway」，先處理 Gateway。

```bash
# @ib-data：3. 加排程（每月 1–8 號 UTC 22:05）
(crontab -l 2>/dev/null; echo '5 22 1-8 * * bash $HOME/20260918/gcp_ib/run_monthend_closes.sh >> $HOME/monthend_cron.log 2>&1') | crontab -
crontab -l | grep monthend
```

可以揀即刻正式跑一次，唔使等排程：`bash ~/20260918/gcp_ib/run_monthend_closes.sh`。600 檔左右約 15–25 分鐘。

## 鳥翔點樣攞數據

```bash
git fetch origin data/stock-ibkr
git checkout origin/data/stock-ibkr -- data_stock_ibkr/hk_<D>.csv data_stock_ibkr/sg_<D>.csv data_stock_ibkr/au_<D>.csv data_stock_ibkr/us_<D>.csv data_stock_ibkr/au_<D>_nortrh.csv
python3 scripts/tt_all_verify.py --ibkr
```

注意：唔好 checkout 資料分支嘅 `_status.txt` 去覆寫鳥翔分支嗰份（FUND_SOP 二之二）。

## 時間點解揀 UTC 22:05

- 四個市場下一交易日都已經收市：美股冬令 21:00／夏令 20:00 UTC；港、新、澳更早
- 早過 IB Gateway 每日約 23:50 UTC 重啟
- 同 `run_vol_daily.sh`（22:30）用唔同 clientId，可以同時跑

一次大約 330 個請求，每個隔 2.5 秒，約 15 分鐘。
