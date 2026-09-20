# 歷史數據目錄（data/）

各策略回測共用的 M1 歷史數據。統一存放規則：

## 命名與格式

```
data/<SYMBOL>_M1_<YYYY>.csv.gz      # 每商品每年一個檔，gzip 壓縮
例：data/XAUUSD_M1_2026.csv.gz
    data/NQ_M1_2026.csv.gz
    data/HK50_M1_2026.csv.gz
```

- 內容為 MT5 匯出格式（`Time,Open,High,Low,Close,...` 或 Tab 分隔的
  `<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE>`），壓縮前後皆可被
  `backtest.py` / `zgl_backtest.py` 的載入器直接讀取（`.gz` 免解壓）。
- **時間戳一律保留券商原始時間**，不要事先轉 UTC；回測時用
  `--broker-offset` 轉換（每個檔案的時差記在下表）。
- 按年切塊是為了避開 GitHub 單檔 100MB 上限，也方便只載入需要的區間。
  M1 OHLC 一年約 35 萬根，gzip 後約 3–6 MB。

## 數據清單

| 檔案 | 商品 | 期間 | 券商時差 | 來源 | 備註 |
|---|---|---|---|---|---|
| （待補：數據上傳後在此登記） | | | | | |

## 用法

```bash
# 單一年份
python3 zgl_backtest.py data/XAUUSD_M1_2026.csv.gz --broker-offset 3 --sweep

# 跨年份：先合併（載入器會自動排序去重）
zcat data/XAUUSD_M1_*.csv.gz > /tmp/xau_all.csv
python3 zgl_backtest.py /tmp/xau_all.csv --broker-offset 3
```

## 各商品回測注意事項

單位價值不同：`zgl_backtest.py` 預設每張 0.01 手 XAUUSD = 1 oz（價格動
1 美元 = 1 USD 損益）。NQ 與 HK50 的每點價值、點差、報價貨幣都不同，
跑非黃金商品時需明確設定 `--spread`，損益一律以「報價單位 × 單位值」解讀。
