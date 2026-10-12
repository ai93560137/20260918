# 給雲垂 VM：安裝 ZQ 每日結算採集（pre-FOMC 美元漂移前向用）

發出：外匯分支 `claude/forex-data-testing-w4q3m2`，2026-10-12。協議：`FX_FOMC_DRIFT_FORWARD.md`。只讀 IB、不下單、不花錢。

每個平日 23:30 UTC（CME 結算後）抓 ZQ 本月＋後三個月合約最近 10 天日線，合併進 `data_forex_ibkr/zq/zq_daily.csv`，並 commit 推回雲垂分支（一列 commit，很小）。外匯分支的 Actions 隔日 02:30 UTC 用 GitHub raw 讀它算訊號。clientId 45。

在 VM（`@ib-data`）貼：

```bash
cd ~/20260918 && git pull --rebase origin claude/dazzling-curie-f3xzb8
git fetch origin claude/forex-data-testing-w4q3m2
git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/ib_zq_daily.py
# 先手動跑一次（會抓並推回）
python3 scripts/ib_zq_daily.py --client-id 45 --push
tail -5 data_forex_ibkr/zq/zq_daily.csv
# 通過後上 crontab（VM 為 UTC）
( crontab -l 2>/dev/null | grep -v 'ib_zq_daily'
  echo '30 23 * * 1-5 cd $HOME/20260918 && python3 scripts/ib_zq_daily.py --client-id 45 --push >> data_forex_ibkr/zq/zq_daily.log 2>&1'
) | crontab -
crontab -l | grep ib_zq_daily
git add scripts/ib_zq_daily.py && git commit -m "ops(zq): ZQ 每日結算採集腳本與 cron" && git push origin claude/dazzling-curie-f3xzb8
```

- 第一個要用到的日子：**2026-10-23（五）** 的結算（10-28 會議的 t−3，次月合約 ZQ 2026-11）。cron 在 10-23 23:30 UTC 抓到並推回，Actions 10-24 02:30 UTC 算出訊號，10-26 17:55 UTC 紙上進場。
- 腳本若報 `qualify 失敗`：IB 偶爾對未上市遠月合約不認得，無礙；要的是本月與次月。
- 不要改既有 cron；log 檔不進 git。
