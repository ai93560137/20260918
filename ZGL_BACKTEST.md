# ZGL 策略回測（zgl_backtest.py）

把 TradingView 指標「智能諸葛亮0829」（ZLEMA 彩帶動能 + 首單/加單）逐行移植成
可回測的策略。這條管線與 v12 的 `backtest.py` 互相獨立：v12 回測的是 main.py
的電閘/GCP 決策流程，這裡回測的是看圖指標本身直接發單的行為。

## 策略定義

訊號端（與指標 Section 2/3/4 完全一致）：

- **動能**：`hl2` 的九條 ZLEMA（週期 6, 27, 48, …, 174，`step=21`），
  `WMA5(L1 − L9) ≥ 0` 為多方動能，反之空方。
- **首單**：多方動能 + 綠 K（`close > open`）；空方對稱。每個波段只有一次。
- **加單**：同向 K 色、距上一次進場 ≥ `add_interval` 根、次數 < `max_adds`。
- **翻轉重設**：動能轉向當根，對側觸發旗標與加單計數立即歸零。
- **盤整過濾**：`stdev(close,20)` 在 100 根內的百分位 < `sideways_level` 時，
  訂單改 log_only（不送單，但狀態機照走——與指標 `build_json` 行為一致，
  意味著被盤整吃掉的「首單」這個波段不會再補發）。

出場端（`--exit`）：

| 模式 | 行為 |
|---|---|
| `faithful` | 完全模擬目前實盤：只靠 `execution_mode=close_opposite`，舊倉要等翻轉後**第一張反向單成交**才平。指標裡 `global_trend_up/down` 從未賦值，FLIP 平倉是死代碼，所以這就是現在真實發生的事。 |
| `flipclose` | 把 FLIP 補上：動能翻轉後下一根開盤先全平，再等反向首單。 |

成交假設：訊號於收盤確立（對應 `alert.freq_once_per_bar_close`），下一根開盤
成交；資料視為 bid，買方付點差（預設 0.30）。每張單固定 0.01 手 = 1 oz，
價格每動 1 美元單張損益 1 美元。未模擬滑價、隔夜利息、保證金追繳。

## 用法

```bash
# 引擎自檢（不需要資料）
python3 zgl_backtest.py --selftest

# 真實資料：MT5 匯出的 XAUUSD M1 CSV（格式同 backtest.py，共用載入器）
python3 zgl_backtest.py XAUUSD_M1.csv --broker-offset 3 --sweep

# 單一設定 + 匯出交易
python3 zgl_backtest.py XAUUSD_M1.csv --broker-offset 3 \
  --exit flipclose --max-adds 20 --sideways-level 20 --trades zgl_trades.csv
```

`--sweep` 會掃：出場模型 × 加單上限 (0/5/20/200) × 間隔 (1/3) × 盤整過濾 (10/20/40)。
其他參數：`--trade-mode both|long|short`、`--spread`、`--step`、`--bos-smooth`、
`--equity`、`--warmup`（預設 1000 根，讓 174 期 EMA 種子收斂，之前不進場）。

## 引擎驗證狀態

- `--selftest`：WMA/EMA/ZLEMA 數學、首單唯一性、加單間隔與上限、翻轉重設，全部通過。
- `--synthetic 80000 --sweep`：合成資料端到端煙霧測試通過。
  **合成資料的損益數字不構成任何交易結論**（生成器自帶趨勢 regime，
  趨勢策略天然得利），它只證明引擎會動、統計會算。

已經確認的行為性事實（與資料無關）：

- `faithful` 模式下 `max_adds=200` 會把同時持倉堆到 2 手以上（0.01 手基準）——
  這是目前實盤設定的真實敞口上限，保證金與滑價風險都在這裡。
- 動能翻轉後、反向首根同色 K 出現前，舊倉處於無人看管狀態（FLIP 死代碼的後果）；
  `flipclose` 修掉這段裸露期，最大持倉與回撤同步下降。

## 還缺什麼

真實 XAUUSD M1 資料。本次開發環境的網路政策封鎖了所有行情源
（Dukascopy/Yahoo/stooq 均 403），因此真實回測需要二選一：

1. 把 MT5 匯出的 `XAUUSD_M1.csv` commit 進這個分支，遠端跑；或
2. 本地在 repo 根目錄執行上面的指令（只依賴標準庫 + 同目錄的 backtest.py）。

拿到真實結果前，不對「這個策略賺不賺錢」下任何結論。參考 BACKTEST.md 的教訓：
不到三個月的樣本不足以下結論，樣本內外要分開驗證。
