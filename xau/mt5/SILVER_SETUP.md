# 白銀趨勢簿（#1442）上線步驟——未部署，等使用者批准

> 使用者 11-12「#1442 白銀真倉」。程式已寫好同測試（預設值唔變，黃金服務唔受影響）；**未部署、未開服務、未掛 EA**。
> 部署同改環境變數由總指揮做 dry-run，使用者親口批准先做。

## 規則（同回測一致，對拍 `research/strategy_search/PARITY_SILVER.md`：247 個入場逐日一致）

- 只做多。前一日收市 > 200 日線，而且單日收市升幅 ≥ 1.5 × 前一日 ATR14 → 新一日第一個心跳市價買入。
- 止蝕＝入場價 − 3 × ATR14（伺服器端），冇止賺。
- 出場：收市低過之前 10 日最低收市，或者收市跌穿 200 日線 → 新一日第一個心跳平；最多 250 根日線。
- 一次一張；止蝕嗰日嘅訊號唔入。
- 日線唔收星期日開市嗰一兩個鐘嘅 K 線（回測用交易日日線）。
- 停條件：累計 ≤ −8R（同其他趨勢簿一樣），組合回落 ≥ 10R 通知使用者。

## 回測（`MULTI2_1437.md`、IDEAS #1442）

| 數據 | 張 | 平均 R | PF | 前半／後半 | 贏隨機入場 |
|---|---|---|---|---|---|
| 白銀現貨 1968–2026 | 150 | +0.440 | 2.27 | +0.663／+0.217 | 100 百分位 |
| 白銀期貨 2000–2026 | 122 | +0.393 | 1.96 | +0.574／+0.211 | 100 百分位 |

- 平均揸約 24 日，大約每年 2–3 張。2015 年起 30 張平均 +0.247R。
- 隔夜息敏感度：年率 4% → 全期平均 +0.396R；10% → +0.329R（每張約扣 0.1R）。實際息率要睇券商規格。

## 券商規格（使用者 11-13 影 MT5 XAGUSD「規格」）

| 項目 | 值 | 對策略嘅意思 |
|---|---|---|
| 合約大小 | 5,000 安士 | 同程式預設一樣，唔使設 `XAU_CONTRACT_SIZE`；0.01 手＝50 安士 |
| 小數位 | 3 | 同程式一樣 |
| 最小手數／步長 | 0.01／0.01 | 0.01 手可以落 |
| 止蝕最小距離 | 10 點（0.01 美元） | 3×ATR 遠大過，冇影響 |
| 買入庫存費 | −9.52 點／晚（每安士 0.00952 美元）；星期三收三倍 | 0.01 手每晚約 0.48 美元；折合年率約 6.8%（銀價約 51 美元計） |
| 賣出庫存費 | +4.95 點／晚 | 只做多，用唔著 |
| 保證金 | 名義值 1% | 0.01 手約 26 美元 |
| 交易時段（伺服器時間） | 星期一至五 01:01–23:58 | 同黃金相若；冇星期日時段（UTC 星期日 23:00 開市嗰個鐘已設定唔收入日線） |

- 扣咗呢個庫存費之後嘅回測期望值：全期每張約 +0.36R（原本 +0.44R），2015 年起約 +0.18R（原本 +0.25R）。平均每張約扣 0.04–0.08R。
- 每張風險（0.01 手）：止蝕距離 3×ATR，以近期 ATR 約 2.1 美元計，約 6.2 美元 × 50 安士 ≈ 310 美元。ATR 變，風險跟住變。

## 上線前要齊嘅嘢

1. ~~券商規格~~ ✅ 11-13 已收（見上表）。
2. ~~使用者決定~~ ✅ 11-13 使用者：「…63，0.01」——戶口 …63、固定 0.01 手、唔開複利（`XAU_TREND_COMPOUND` 唔設）。
3. **日線種子更新**：上線當日用 MT5 `ExportAllM1.mq5` 匯出 XAGUSD M1（最少近 2 年），匯入研究快取後跑
   `python3 research/strategy_search/build_seed_xag.py` 重新產生 `xau/trend_d1_seed_xagusd.py`。種子尾同上線日之間唔可以有缺日。
   （而家嘅種子去到 2026-11-10。）
4. 檢查：`python3.11 -m py_compile xau/*.py`、`python3 tests/test_xau_trend_silver.py`、其他 `tests/test_xau_trend_*.py` 逐個跑、
   `python3 -m unittest scripts/test_gcp_agent.py`、`python3 research/strategy_search/parity_silver.py`。

## 部署（總指揮；全部先 dry-run）

- `python3 scripts/gcp_agent.py --profile xag deploy`（服務 `zhuge-xag` 唔存在會建立；profile 會自動加
  `XAU_SYMBOL=XAGUSD`、`XAU_EXECUTE=0`、`XAU_TREND_LONG_ONLY=1`，唔一致就拒絕部署）。
- 其餘環境變數（`env set`）：

| 變數 | 值 | 用途 |
|---|---|---|
| `XAU_TREND_LIVE` | `1` | 開趨勢簿 |
| `XAU_TREND_MAGIC` | `943` | 白銀簿 magic |
| `XAU_TREND_RULES` | `tdsurge` | #1285 規則 |
| `XAU_TREND_LOTS`／`XAU_TREND_MAX_LOTS` | `0.01`／`0.01` | 固定手數 |
| `XAU_ACTIVE_HOURS_UTC` | `00-00` | 唔行 AI |
| `XAU_ACK_REQUIRE_ACCOUNT` | `1` | 只收指定戶口嘅心跳 |
| `XAU_TEST_CMDS` | `0` | |
| `WEBHOOK_SECRET_TOKEN`、`TG_BOT_TOKEN`、`TG_CHAT_ID`、`XAU_ACCOUNT` | **唔好打明文**：`gcp_agent.py --profile xag env copy --from-profile xau WEBHOOK_SECRET_TOKEN TG_BOT_TOKEN TG_CHAT_ID XAU_ACCOUNT`（喺記憶體由 zhuge-xau 複製，計畫遮罩，`--yes` 先寫） | 心跳驗證、通知、戶口 …63 |

- 「允許未經驗證的叫用」由使用者喺控制台開（同 zhuge-xau 一樣）。
- 使用者喺 MT5 開一張 **XAGUSD** 圖，掛 `TianfuExecutor`，magic `943`，網址填 `zhuge-xag` 嘅網址，權杖同其他圖一樣。
- 核實：`?format=json` 嘅 `trend_live` on、rules `tdsurge`、日線 ≥ 300 日、`product_ok`；第一張單開咗即報。
- 退版：新服務冇舊修訂；要停就 `env set XAU_TREND_LIVE=0`（有倉先平）。

## 程式改動（預設值全部唔變）

- `xau/config.py`：產品表加 `XAGUSD`；`XAU_TREND_LONG_ONLY`（預設關）、`XAU_TREND_MIN_SL_ABS`（黃金 3、其他 0）、`XAU_TREND_DROP_SUNDAY`（黃金關、其他開）。
- `xau/trend_d1rules.py`：`plan_open`／`floor` 加參數（只做多、最低止蝕、小數位）。
- `xau/trend_live.py`：種子按產品揀（`trend_d1_seed_<symbol>`）；星期日 K 線過濾。
- `scripts/gcp_agent.py`：profile `xag`。
- 測試 `tests/test_xau_trend_silver.py`（4 個）。
